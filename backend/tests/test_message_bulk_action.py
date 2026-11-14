"""Bulk message handling: one request clears a whole selection.

The inbox groups WhatsApp group/contact messages only for display. Before the
bulk endpoint, an operator had to click "系统外已处理" on every row of a
five-message conversation. These tests pin the new contract: every row is
still checked against the single-action rules, skipped rows are reported
instead of aborting the batch, and linked rows go through their inquiry.
"""
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import hash_password
from app.database import get_db
from app.main import app
from app.models.base import Base
from app.models.business import (
    ChannelAccount,
    ChannelGrant,
    Inquiry,
    InquiryMessage,
    Message,
    OperationLog,
)
from app.models.overview import MessageOverview
from app.models.user import User


@pytest.fixture
def bulk_client():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session = sessionmaker(bind=engine, expire_on_commit=False)
    Base.metadata.create_all(engine)
    with testing_session() as db:
        operator = User(
            username="operator", password_hash=hash_password("operator1"),
            role="staff", department="inquiry", is_active=True, must_change_password=False,
        )
        outsider = User(
            username="outsider", password_hash=hash_password("outsider1"),
            role="staff", department="inquiry", is_active=True, must_change_password=False,
        )
        sales = User(
            username="sales", password_hash=hash_password("salespass1"),
            role="sales", department="inquiry", is_active=True, must_change_password=False,
        )
        db.add_all([operator, outsider, sales])
        db.flush()
        own_account = ChannelAccount(owner_user_id=operator.id, channel_type="whatsapp", status="connected")
        other_account = ChannelAccount(owner_user_id=outsider.id, channel_type="whatsapp", status="connected")
        db.add_all([own_account, other_account])
        db.flush()
        db.add_all([
            ChannelGrant(channel_account_id=own_account.id, channel_type="whatsapp", owner_user_id=operator.id),
            ChannelGrant(channel_account_id=other_account.id, channel_type="whatsapp", owner_user_id=outsider.id),
        ])

        def message(mid: int, body: str, **overrides):
            values = dict(
                id=mid,
                channel_account_id=own_account.id,
                provider="whatsapp_web_baileys",
                external_message_id=f"group-msg-{mid}@g.us",
                direction="inbound",
                status="received",
                handling_status="pending",
                occurred_at=datetime(2026, 11, 14, 8, tzinfo=timezone.utc),
                raw_content=body,
                customer_contact="1203638190-1234@g.us",
                customer_nickname="Emma Chen",
                normalized_customer_contact=None,
                contact_identity_state="unsupported",
                contact_identity_kind=None,
                link_state="unmatched",
            )
            values.update(overrides)
            return Message(**values)

        rows = [
            message(1, "there isnt a shipping way by sea"),
            message(2, "dear Miguel"),
            message(3, "please quote 300 units"),
            message(4, "any update on the sample?"),
            message(5, "[empty WhatsApp message]"),  # 客户双端删除/撤回
            message(6, "already archived", handling_status="processed"),
            message(7, "linked to an inquiry", link_state="linked"),
            message(8, "another operator's message", channel_account_id=other_account.id),
        ]
        db.add_all(rows)
        db.flush()
        inquiry = Inquiry(
            customer_contact="+8613800000000",
            department="inquiry",
            normalized_customer_contact="+8613800000000",
            contact_identity_state="certain",
            contact_identity_kind="whatsapp",
            customer_nickname="Group Customer",
            raw_message="linked to an inquiry",
            source_channel_account_id=own_account.id,
            status="assigned",
            handling_status="pending",
            assigned_sales_user_id=sales.id,
        )
        db.add(inquiry)
        db.flush()
        db.add(InquiryMessage(inquiry_id=inquiry.id, message_id=7, position=1, link_source="manual"))
        db.add(MessageOverview(message_id=1, status="ready", overview_text="物流咨询"))
        db.commit()

    def override_db():
        with testing_session() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    with TestClient(app, base_url="https://testserver", raise_server_exceptions=True) as client:
        client.testing_session = testing_session
        yield client
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)
    engine.dispose()


def login(client, username="operator", password="operator1"):
    csrf = client.get("/auth/csrf", headers={"Origin": "https://testserver"})
    response = client.post(
        "/auth/login",
        json={"username": username, "password": password},
        headers={"Origin": "https://testserver", "X-CSRF-Token": csrf.json()["csrf_token"]},
    )
    assert response.status_code == 200
    return {"Origin": "https://testserver", "X-CSRF-Token": client.cookies.get("ea_csrf")}


def post_bulk(client, headers, message_ids, action="processed"):
    return client.post(
        "/api/messages/bulk-action",
        json={"message_ids": message_ids, "action": action},
        headers=headers,
    )


def test_bulk_action_processes_whole_group_in_one_request(bulk_client):
    headers = login(bulk_client)
    response = post_bulk(bulk_client, headers, [1, 2, 3, 4])

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["action"] == "processed"
    assert sorted(body["updated_message_ids"]) == [1, 2, 3, 4]
    assert body["updated_inquiry_ids"] == []
    assert body["skipped"] == []

    with bulk_client.testing_session() as db:
        statuses = dict(db.execute(select(Message.id, Message.handling_status)).all())
        assert all(statuses[mid] == "processed" for mid in (1, 2, 3, 4))
        assert db.scalar(select(MessageOverview).where(MessageOverview.message_id == 1)) is None
        assert db.scalar(
            select(OperationLog.operation_name).where(OperationLog.operation_name == "批量标记已处理")
        ) == "批量标记已处理"


def test_bulk_action_reports_skipped_rows_without_aborting_the_batch(bulk_client):
    headers = login(bulk_client)
    # 1 是待处理；5 已撤回；6 已终态；8 越权；999 不存在。
    response = post_bulk(bulk_client, headers, [1, 5, 6, 8, 999, 1])

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["updated_message_ids"] == [1]  # 重复 id 只处理一次
    assert {item["reason"] for item in body["skipped"]} == {
        "revoked", "already_final", "not_visible",
    }
    assert len(body["skipped"]) == 4

    with bulk_client.testing_session() as db:
        statuses = dict(db.execute(select(Message.id, Message.handling_status)).all())
        assert statuses[1] == "processed"
        assert statuses[5] == "pending"
        assert statuses[8] == "pending"


def test_bulk_action_handles_linked_rows_through_their_inquiry(bulk_client):
    headers = login(bulk_client)
    response = post_bulk(bulk_client, headers, [1, 7], action="ignored")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["updated_message_ids"] == [1]
    assert body["updated_inquiry_ids"] == [1]

    with bulk_client.testing_session() as db:
        row = db.get(Message, 7)
        inquiry = db.get(Inquiry, 1)
        assert row.handling_status == "ignored"
        assert inquiry.handling_status == "ignored"


def test_bulk_action_requires_csrf_and_operator_role(bulk_client):
    assert post_bulk(bulk_client, {"Origin": "https://testserver"}, [1]).status_code in (401, 403)

    login(bulk_client)
    csrf = bulk_client.cookies.get("ea_csrf")
    assert post_bulk(
        bulk_client, {"Origin": "https://testserver"}, [1],
    ).status_code in (401, 403)

    # 业务员不能处理消息，即便持有合法 CSRF。
    bulk_client.post("/auth/logout", headers={"Origin": "https://testserver", "X-CSRF-Token": csrf})
    sales_headers = login(bulk_client, "sales", "salespass1")
    assert post_bulk(bulk_client, sales_headers, [1]).status_code == 403


def test_bulk_action_bounds_and_validates_the_selection(bulk_client):
    headers = login(bulk_client)
    assert post_bulk(bulk_client, headers, []).status_code == 422
    assert post_bulk(bulk_client, headers, list(range(1, 102))).status_code == 422
    assert post_bulk(bulk_client, headers, [0]).status_code == 422
    response = bulk_client.post(
        "/api/messages/bulk-action",
        json={"message_ids": [1], "action": "send"},
        headers=headers,
    )
    assert response.status_code == 422


def test_single_message_action_also_refuses_revoked_stubs(bulk_client):
    headers = login(bulk_client)
    response = bulk_client.post(
        "/api/messages/5/action", json={"action": "processed"}, headers=headers
    )
    assert response.status_code == 409
    assert "撤回" in response.json()["detail"]


def test_revoked_stub_can_still_be_ignored(bulk_client):
    """用户反馈：撤回的消息也应该有一个忽略按钮，不能永远卡在待办里。"""
    headers = login(bulk_client)
    single = bulk_client.post(
        "/api/messages/5/action", json={"action": "ignored"}, headers=headers
    )
    assert single.status_code == 200, single.text
    assert single.json()["handling_status"] == "ignored"

    bulk = post_bulk(bulk_client, headers, [1, 5], action="ignored")
    assert bulk.status_code == 200, bulk.text
    # 5 刚被单独忽略，属于已终态；1 正常忽略。
    assert bulk.json()["updated_message_ids"] == [1]
    assert any(item["reason"] == "already_final" for item in bulk.json()["skipped"])

    with bulk_client.testing_session() as db:
        statuses = dict(db.execute(select(Message.id, Message.handling_status)).all())
        assert statuses[1] == "ignored"
        assert statuses[5] == "ignored"


def test_bulk_processed_skips_revoked_but_bulk_ignored_clears_them(bulk_client):
    headers = login(bulk_client)
    processed = post_bulk(bulk_client, headers, [1, 5], action="processed")
    assert processed.status_code == 200
    assert 5 not in processed.json()["updated_message_ids"]
    assert any(item["reason"] == "revoked" for item in processed.json()["skipped"])

    ignored = post_bulk(bulk_client, headers, [5], action="ignored")
    assert ignored.status_code == 200
    assert ignored.json()["updated_message_ids"] == [5]
