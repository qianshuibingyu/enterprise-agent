from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
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
    InquiryEvent,
    InquiryMessage,
    Message,
    OperationLog,
)
from app.models.user import User


def _message(message_id, account_id, external_id, handling_status, contact, link_state):
    return Message(
        id=message_id,
        channel_account_id=account_id,
        provider="gmail_api_pubsub" if account_id == 1 else "outlook_mcp_graph",
        external_message_id=external_id,
        direction="inbound",
        status="received",
        handling_status=handling_status,
        occurred_at=datetime(2026, 11, 7, tzinfo=timezone.utc),
        raw_content=f"content {external_id}",
        customer_contact=contact,
        normalized_customer_contact=contact,
        contact_identity_state="certain",
        contact_identity_kind="email",
        link_state=link_state,
    )


@pytest.fixture
def client():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    Base.metadata.create_all(engine)
    with factory() as db:
        db.add_all([
            User(username="op1", password_hash=hash_password("operator1"), role="staff", is_active=True, must_change_password=False),
            User(username="op2", password_hash=hash_password("operator2"), role="staff", is_active=True, must_change_password=False),
            User(username="sale", password_hash=hash_password("salespass1"), role="sales", is_active=True, must_change_password=False),
        ])
        db.flush()
        db.add_all([
            ChannelAccount(id=1, owner_user_id=1, channel_type="gmail", status="connected"),
            ChannelAccount(id=2, owner_user_id=2, channel_type="outlook", status="connected"),
        ])
        db.flush()
        db.add_all([
            ChannelGrant(channel_account_id=1, channel_type="gmail", owner_user_id=1),
            ChannelGrant(channel_account_id=2, channel_type="outlook", owner_user_id=2),
        ])
        db.flush()
        db.add_all([
            _message(1, 1, "ar-1", "pending", "chain@example.com", "linked"),
            _message(2, 1, "ar-2", "pending", "chain@example.com", "linked"),
            _message(3, 1, "ar-orphan", "ignored", "orphan@example.com", "unmatched"),
            _message(4, 1, "ar-mixed-1", "ignored", "mixed@example.com", "linked"),
            _message(5, 2, "ar-mixed-2", "ignored", "mixed@example.com", "linked"),
        ])
        db.flush()
        now = datetime.now(timezone.utc)
        db.add_all([
            Inquiry(
                id=1,
                customer_contact="chain@example.com",
                normalized_customer_contact="chain@example.com",
                contact_identity_state="certain",
                contact_identity_kind="email",
                customer_nickname="Chain",
                raw_message="first",
                source_channel_account_id=1,
                status="new",
                handling_status="pending",
                last_activity_at=now - timedelta(days=1),
                events=[InquiryEvent(event_type="inquiry_created", to_status="new", occurred_at=now - timedelta(days=1))],
                message_links=[
                    InquiryMessage(message_id=1, position=1, link_source="fixture"),
                    InquiryMessage(message_id=2, position=2, link_source="fixture"),
                ],
            ),
            Inquiry(
                id=3,
                customer_contact="mixed@example.com",
                normalized_customer_contact="mixed@example.com",
                contact_identity_state="certain",
                contact_identity_kind="email",
                customer_nickname="Mixed",
                raw_message="mixed",
                source_channel_account_id=1,
                status="new",
                handling_status="ignored",
                last_activity_at=now - timedelta(days=1),
                events=[InquiryEvent(event_type="inquiry_created", to_status="new", occurred_at=now - timedelta(days=1))],
                message_links=[
                    InquiryMessage(message_id=4, position=1, link_source="fixture"),
                    InquiryMessage(message_id=5, position=2, link_source="fixture"),
                ],
            ),
        ])
        db.commit()

    def override_db():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    with TestClient(app, base_url="https://testserver", raise_server_exceptions=False) as http:
        yield http, factory
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)
    engine.dispose()


def login(http):
    csrf = http.get("/auth/csrf", headers={"Origin": "https://testserver"}).json()["csrf_token"]
    response = http.post(
        "/auth/login",
        json={"username": "op1", "password": "operator1"},
        headers={"Origin": "https://testserver", "X-CSRF-Token": csrf},
    )
    assert response.status_code == 200
    return {"Origin": "https://testserver", "X-CSRF-Token": http.cookies.get("ea_csrf")}


def _ignore_and_restore(http, headers):
    ignored = http.post("/api/inquiries/1/action", json={"action": "ignored"}, headers=headers)
    assert ignored.status_code == 200, ignored.text
    restored = http.post("/api/messages/1/archive/restore", headers=headers)
    assert restored.status_code == 200, restored.text
    return restored


def test_restore_reactivates_inquiry_with_event_and_keeps_siblings_archived(client):
    http, factory = client
    headers = login(http)

    restored = _ignore_and_restore(http, headers)
    assert restored.json()["handling_status"] == "pending"

    with factory() as db:
        assert db.get(Inquiry, 1).handling_status == "pending"
        event = db.scalar(
            select(InquiryEvent).where(
                InquiryEvent.inquiry_id == 1,
                InquiryEvent.event_type == "inquiry_reactivated",
            )
        )
        assert event is not None
        assert event.message_id == 1
        assert event.from_status == "ignored"
        assert event.to_status == "pending"
        assert event.actor_user_id == 1
        assert db.get(Message, 1).handling_status == "pending"
        # 同链路其它消息仍留在归档箱，由用户逐条恢复。
        assert db.get(Message, 2).handling_status == "ignored"
        assert db.scalar(
            select(func.count()).select_from(OperationLog).where(
                OperationLog.operation_name == "恢复链路",
                OperationLog.object_type == "inquiry",
                OperationLog.object_id == 1,
            )
        ) == 1
        assert db.scalar(
            select(func.count()).select_from(OperationLog).where(
                OperationLog.operation_name == "恢复消息",
                OperationLog.object_type == "message",
                OperationLog.object_id == 1,
            )
        ) == 1


def test_transfer_is_allowed_after_restore(client):
    http, factory = client
    headers = login(http)
    transfer_body = {"sales_user_id": 3, "business_type": "inquiry"}

    ignored = http.post("/api/inquiries/1/action", json={"action": "ignored"}, headers=headers)
    assert ignored.status_code == 200, ignored.text
    blocked = http.post("/api/inquiries/1/transfer", json=transfer_body, headers=headers)
    assert blocked.status_code == 409
    assert blocked.json()["detail"] == "当前链路已处理；请先恢复链路或等待新消息"

    restored = http.post("/api/messages/1/archive/restore", headers=headers)
    assert restored.status_code == 200, restored.text
    transferred = http.post("/api/inquiries/1/transfer", json=transfer_body, headers=headers)
    assert transferred.status_code == 200, transferred.text
    assert transferred.json()["assigned_sales_user_id"] == 3


def test_reactivate_allows_recent_last_activity(client):
    http, factory = client
    headers = login(http)
    with factory() as db:
        inquiry = db.get(Inquiry, 1)
        inquiry.handling_status = "ignored"
        inquiry.last_activity_at = datetime.now(timezone.utc) - timedelta(days=10)
        db.commit()

    response = http.post("/api/inquiries/1/reactivate", headers=headers)
    assert response.status_code == 200, response.text
    assert response.json()["handling_status"] == "pending"
    with factory() as db:
        assert db.get(Inquiry, 1).handling_status == "pending"
        assert db.scalar(
            select(func.count()).select_from(OperationLog).where(
                OperationLog.operation_name == "恢复链路",
                OperationLog.object_type == "inquiry",
                OperationLog.object_id == 1,
            )
        ) == 1


def test_reactivate_still_rejects_purge_due_last_activity(client):
    http, factory = client
    headers = login(http)
    with factory() as db:
        inquiry = db.get(Inquiry, 1)
        inquiry.handling_status = "ignored"
        inquiry.last_activity_at = datetime.now(timezone.utc) - timedelta(days=95)
        db.commit()

    response = http.post("/api/inquiries/1/reactivate", headers=headers)
    assert response.status_code == 409
    assert response.json()["detail"] == "已到期清理的链路不能恢复"
    with factory() as db:
        assert db.get(Inquiry, 1).handling_status == "ignored"


def test_restore_orphan_message_does_not_error(client):
    http, factory = client
    headers = login(http)

    response = http.post("/api/messages/3/archive/restore", headers=headers)
    assert response.status_code == 200, response.text
    assert response.json()["handling_status"] == "pending"
    with factory() as db:
        assert db.get(Message, 3).handling_status == "pending"
        assert db.scalar(
            select(func.count()).select_from(InquiryEvent).where(
                InquiryEvent.event_type == "inquiry_reactivated",
                InquiryEvent.message_id == 3,
            )
        ) == 0
        assert db.scalar(
            select(func.count()).select_from(OperationLog).where(
                OperationLog.operation_name == "恢复链路"
            )
        ) == 0


def test_restore_refuses_to_reactivate_chain_with_unauthorized_sibling(client):
    http, factory = client
    headers = login(http)

    # 消息 4 对 op1 可见，但其所属链路还关联着 op1 无权的账号 2 消息，
    # 恢复这条可见消息不得激活含不可见消息的链路。
    response = http.post("/api/messages/4/archive/restore", headers=headers)
    assert response.status_code == 403, response.text
    with factory() as db:
        assert db.get(Inquiry, 3).handling_status == "ignored"
        assert db.get(Message, 4).handling_status == "ignored"


def test_restore_rolls_back_every_write_on_commit_failure(client, monkeypatch):
    from sqlalchemy.orm import Session

    http, factory = client
    headers = login(http)
    ignored = http.post("/api/inquiries/1/action", json={"action": "ignored"}, headers=headers)
    assert ignored.status_code == 200, ignored.text

    original_commit = Session.commit

    def fail_commit(self):
        raise RuntimeError("fixture restore commit failure")

    monkeypatch.setattr(Session, "commit", fail_commit)
    response = http.post("/api/messages/1/archive/restore", headers=headers)
    monkeypatch.setattr(Session, "commit", original_commit)
    assert response.status_code == 500, response.text

    with factory() as db:
        assert db.get(Inquiry, 1).handling_status == "ignored"
        assert db.get(Message, 1).handling_status == "ignored"
        assert db.scalar(
            select(func.count()).select_from(InquiryEvent).where(
                InquiryEvent.event_type == "inquiry_reactivated"
            )
        ) == 0
        assert db.scalar(
            select(func.count()).select_from(OperationLog).where(
                OperationLog.operation_name.in_(["恢复消息", "恢复链路"])
            )
        ) == 0
