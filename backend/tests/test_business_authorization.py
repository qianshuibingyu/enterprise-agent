from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import hash_password
from app.database import get_db
from app.main import app
from app.models.base import Base
from app.models.business import (
    ChannelAccount,
    ChannelGrant,
    Inquiry,
    InquiryAttachment,
    InquiryEvent,
    InternalNotification,
    Message,
    MessageAttachment,
)
from app.models.user import User


@pytest.fixture
def business_client():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session = sessionmaker(bind=engine, expire_on_commit=False)
    Base.metadata.create_all(engine)
    with testing_session() as db:
        db.add_all(
            [
                User(username="operator", password_hash=hash_password("operator1"), role="staff", is_active=True, must_change_password=False),
                User(username="other-operator", password_hash=hash_password("otherop1"), role="staff", is_active=True, must_change_password=False),
                User(username="sales", password_hash=hash_password("salespass1"), role="sales", is_active=True, must_change_password=False),
                User(username="other-sales", password_hash=hash_password("othersale1"), role="sales", is_active=True, must_change_password=False),
                User(username="empty-operator", password_hash=hash_password("emptyop1"), role="staff", is_active=True, must_change_password=False),
            ]
        )
        db.flush()
        first_account = ChannelAccount(owner_user_id=1, channel_type="gmail", status="connected")
        blocked_account = ChannelAccount(owner_user_id=1, channel_type="outlook", status="blocked")
        other_account = ChannelAccount(owner_user_id=2, channel_type="outlook", status="connected")
        revoked_account = ChannelAccount(owner_user_id=1, channel_type="gmail", status="revoked")
        db.add_all([first_account, blocked_account, other_account, revoked_account])
        db.flush()
        db.add_all(
            [
                ChannelGrant(channel_account_id=first_account.id, channel_type="gmail", owner_user_id=1),
                ChannelGrant(channel_account_id=blocked_account.id, channel_type="outlook", owner_user_id=1),
                ChannelGrant(channel_account_id=other_account.id, channel_type="outlook", owner_user_id=2),
                ChannelGrant(channel_account_id=revoked_account.id, channel_type="gmail", owner_user_id=1),
                Message(
                    channel_account_id=first_account.id,
                    provider="gmail_api_pubsub",
                    external_message_id="fixture-gmail-1",
                    direction="inbound",
                    status="received",
                    handling_status="pending",
                    occurred_at=datetime(2026, 10, 23, tzinfo=timezone.utc),
                    raw_content="Fake fixture message",
                    attachments=[
                        MessageAttachment(
                            original_filename="fixture.pdf",
                            media_type="application/pdf",
                            size_bytes=42,
                            storage_reference="vault://fixture/secret-reference",
                        )
                    ],
                ),
                Message(
                    channel_account_id=revoked_account.id,
                    provider="gmail_api_pubsub",
                    external_message_id="revoked-gmail-1",
                    direction="inbound",
                    status="received",
                    handling_status="pending",
                    occurred_at=datetime(2026, 10, 23, tzinfo=timezone.utc),
                    raw_content="Revoked account historical message",
                ),
                Message(
                    channel_account_id=other_account.id,
                    provider="outlook_imap",
                    external_message_id="fixture-outlook-1",
                    direction="inbound",
                    status="received",
                    handling_status="pending",
                    occurred_at=datetime(2026, 10, 23, 1, tzinfo=timezone.utc),
                    raw_content="Other fixture message",
                ),
                Message(
                    channel_account_id=other_account.id,
                    provider="outlook_imap",
                    external_message_id="fixture-outlook-2",
                    direction="inbound",
                    status="processed",
                    handling_status="pending",
                    occurred_at=datetime(2026, 10, 23, 2, tzinfo=timezone.utc),
                    raw_content="Assigned sales fixture message",
                ),
                Inquiry(
                    customer_contact="customer@example.com",
                    customer_nickname="Customer",
                    raw_message="Need a quote",
                    source_channel_account_id=first_account.id,
                    status="new",
                    handling_status="pending",
                    events=[
                        InquiryEvent(
                            event_type="inquiry_created",
                            from_status=None,
                            to_status="new",
                            occurred_at=datetime(2026, 10, 23, 3, tzinfo=timezone.utc),
                        )
                    ],
                ),
                Inquiry(
                    customer_contact="other@example.com",
                    customer_nickname="Other Customer",
                    raw_message="Other inquiry",
                    source_channel_account_id=other_account.id,
                    status="new",
                    assigned_sales_user_id=4,
                ),
                Inquiry(
                    customer_contact="mine@example.com",
                    customer_nickname="Assigned Customer",
                    raw_message="Assigned inquiry",
                    source_channel_account_id=other_account.id,
                    status="assigned",
                    handling_status="pending",
                    assigned_sales_user_id=3,
                    events=[
                        InquiryEvent(
                            event_type="inquiry_created",
                            from_status=None,
                            to_status="new",
                            occurred_at=datetime(2026, 10, 23, 4, tzinfo=timezone.utc),
                        ),
                        InquiryEvent(
                            event_type="inquiry_transferred",
                            actor_user_id=1,
                            from_status="new",
                            to_status="assigned",
                            target_user_id=3,
                            occurred_at=datetime(2026, 10, 23, 5, tzinfo=timezone.utc),
                        ),
                    ],
                    attachments=[
                        InquiryAttachment(
                            original_filename="photo.png",
                            media_type="image/png",
                            size_bytes=12,
                            storage_reference="inquiry/3/photo.png",
                        )
                    ],
                ),
                Inquiry(
                    customer_contact="revoked@example.com",
                    customer_nickname="Revoked Customer",
                    raw_message="Revoked source inquiry",
                    source_channel_account_id=revoked_account.id,
                    status="assigned",
                    handling_status="pending",
                    assigned_sales_user_id=3,
                ),
            ]
        )
        db.commit()

    def override_db():
        with testing_session() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    with TestClient(app, base_url="https://testserver", raise_server_exceptions=False) as client:
        yield client
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)
    engine.dispose()


def login(client, username, password):
    csrf = client.get("/auth/csrf", headers={"Origin": "https://testserver"})
    response = client.post(
        "/auth/login",
        json={"username": username, "password": password},
        headers={"Origin": "https://testserver", "X-CSRF-Token": csrf.json()["csrf_token"]},
    )
    assert response.status_code == 200
    return response


def test_business_resources_require_authentication(business_client):
    assert business_client.get("/api/inquiry-transfer-targets").status_code == 401
    assert business_client.get("/api/channel-accounts").status_code == 401
    assert business_client.get("/api/messages").status_code == 401
    assert business_client.get("/api/inquiries").status_code == 401
    assert business_client.post("/api/internal-ai/query", json={"query": "inquiries"}).status_code == 401


def test_revoked_channel_is_not_readable_but_history_is_retained(business_client):
    login(business_client, "operator", "operator1")

    accounts = business_client.get("/api/channel-accounts")
    messages = business_client.get("/api/messages")
    inquiries = business_client.get("/api/inquiries")

    assert accounts.status_code == 200
    assert all(account["status"] != "revoked" for account in accounts.json())
    assert messages.status_code == 200
    assert all(message["external_message_id"] != "revoked-gmail-1" for message in messages.json())
    assert inquiries.status_code == 200
    assert all(item["source_channel_account_id"] != 4 for item in inquiries.json())
    assert business_client.get("/api/messages/2").status_code == 403
    assert business_client.get("/api/inquiries/2").status_code == 403


def test_operator_reads_only_granted_owned_channel_and_inquiries(business_client):
    login(business_client, "operator", "operator1")

    messages = business_client.get("/api/messages")
    assert messages.status_code == 200
    assert [message["external_message_id"] for message in messages.json()] == ["fixture-gmail-1"]
    assert messages.json()[0]["channel_type"] == "gmail"
    assert messages.json()[0]["ingestion_status"] == "received"
    assert messages.json()[0]["handling_status"] == "pending"
    assert messages.json()[0]["attachments"] == [
        {
            "id": messages.json()[0]["attachments"][0]["id"],
            "original_filename": "fixture.pdf",
            "media_type": "application/pdf",
            "size_bytes": 42,
        }
    ]
    assert "storage_reference" not in messages.json()[0]["attachments"][0]
    assert business_client.get("/api/messages/2").status_code == 403
    assert business_client.get("/api/messages/999").status_code == 403

    accounts = business_client.get("/api/channel-accounts")
    assert accounts.status_code == 200
    assert [account["channel_type"] for account in accounts.json()] == ["gmail", "outlook"]
    assert accounts.json()[1]["status"] == "blocked"

    inquiries = business_client.get("/api/inquiries")
    assert inquiries.status_code == 200
    assert [inquiry["raw_message"] for inquiry in inquiries.json()] == ["Need a quote"]
    assert inquiries.json()[0]["timeline_complete"] is True
    assert [event["event_type"] for event in inquiries.json()[0]["timeline"]] == ["inquiry_created"]

    assert business_client.get("/api/inquiries/2").json()["detail"] == "没有权限访问"
    assert business_client.get("/api/inquiries/2").status_code == 403


def test_sales_reads_only_assigned_inquiry_and_notification(business_client):
    login(business_client, "sales", "salespass1")

    messages = business_client.get("/api/messages")
    assert messages.status_code == 200
    # Message has no inquiry/conversation relation yet, so sales must not
    # receive account-wide messages through an assigned inquiry.
    assert messages.json() == []
    assert business_client.get("/api/messages/1").status_code == 403
    assert business_client.get("/api/messages/999").status_code == 403

    inquiries = business_client.get("/api/inquiries")
    assert inquiries.status_code == 200
    assert [inquiry["id"] for inquiry in inquiries.json()] == [3]
    assert inquiries.json()[0]["attachments"][0]["media_type"] == "image/png"
    assert "storage_reference" not in inquiries.json()[0]["attachments"][0]
    assert inquiries.json()[0]["timeline_complete"] is True
    assert [event["event_type"] for event in inquiries.json()[0]["timeline"]] == [
        "inquiry_created",
        "inquiry_transferred",
    ]

    assert business_client.get("/api/inquiries/2").status_code == 403
    assert business_client.get("/api/notifications/1").status_code == 403
    assert business_client.get("/api/inquiries/4").status_code == 403


def test_sales_cannot_read_revoked_source_inquiry(business_client):
    login(business_client, "sales", "salespass1")

    inquiries = business_client.get("/api/inquiries")

    assert inquiries.status_code == 200
    assert [item["id"] for item in inquiries.json()] == [3]
    assert business_client.get("/api/inquiries/4").status_code == 403


def test_external_binding_is_scoped_and_prevents_duplicate_accounts(business_client):
    login(business_client, "operator", "operator1")
    csrf = business_client.cookies.get("ea_csrf")
    headers = {"Origin": "https://testserver", "X-CSRF-Token": csrf}

    first = business_client.post(
        "/api/channels/accounts/1/external-binding",
        json={"external_account_id": "fixture-external-1", "status": "external_authorization_required"},
        headers=headers,
    )
    duplicate = business_client.post(
        "/api/channels/accounts/1/external-binding",
        json={"external_account_id": "fixture-external-1", "status": "external_authorization_required"},
        headers=headers,
    )

    assert first.status_code == 200
    assert first.json()["external_account_id"] == "fixture-external-1"
    assert duplicate.status_code == 200


def test_operator_can_list_transfer_targets(business_client):
    login(business_client, "operator", "operator1")

    response = business_client.get("/api/inquiry-transfer-targets")

    assert response.status_code == 200
    assert response.json() == [
        {"id": 3, "username": "sales", "role": "sales"},
        {"id": 4, "username": "other-sales", "role": "sales"},
    ]


def test_sales_cannot_list_transfer_targets(business_client):
    login(business_client, "sales", "salespass1")

    response = business_client.get("/api/inquiry-transfer-targets")

    assert response.status_code == 403
    assert response.json()["detail"] == "没有权限访问"


def test_operator_transfer_is_idempotent_for_same_target(business_client):
    login(business_client, "operator", "operator1")
    csrf = business_client.cookies.get("ea_csrf")
    headers = {"Origin": "https://testserver", "X-CSRF-Token": csrf}
    body = {"sales_user_id": 3}

    first = business_client.post("/api/inquiries/1/transfer", json=body, headers=headers)
    second = business_client.post("/api/inquiries/1/transfer", json=body, headers=headers)
    different_target = business_client.post(
        "/api/inquiries/1/transfer",
        json={"sales_user_id": 4},
        headers=headers,
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["status"] == "assigned"
    assert second.json()["assigned_sales_user_id"] == 3
    assert different_target.status_code == 403
    assert len(second.json()["timeline"]) == 2
    assert [event["event_type"] for event in second.json()["timeline"]].count("inquiry_transferred") == 1
    assert business_client.get("/api/notifications/1").status_code == 403
    assert business_client.get("/api/notifications/2").status_code == 403

    business_client.post(
        "/auth/logout",
        headers={"Origin": "https://testserver", "X-CSRF-Token": csrf},
    )
    login(business_client, "sales", "salespass1")
    assert business_client.get("/api/notifications/1").status_code == 200
    assert business_client.get("/api/notifications/2").status_code == 403


def test_unscoped_user_cannot_read_inquiry_timeline(business_client):
    login(business_client, "other-operator", "otherop1")

    response = business_client.get("/api/inquiries/1")

    assert response.status_code == 403
    assert response.json()["detail"] == "没有权限访问"


def test_sales_cannot_transfer_or_change_inquiry_state(business_client):
    login(business_client, "sales", "salespass1")
    csrf = business_client.cookies.get("ea_csrf")
    headers = {"Origin": "https://testserver", "X-CSRF-Token": csrf}

    transfer = business_client.post(
        "/api/inquiries/3/transfer",
        json={"sales_user_id": 4},
        headers=headers,
    )
    action = business_client.post(
        "/api/inquiries/3/action",
        json={"action": "processed"},
        headers=headers,
    )

    assert transfer.status_code == 403
    assert action.status_code == 403
    assert action.json()["detail"] == "没有权限访问"


def test_inquiry_handling_actions_are_idempotent_and_audited(business_client):
    login(business_client, "operator", "operator1")
    csrf = business_client.cookies.get("ea_csrf")
    headers = {"Origin": "https://testserver", "X-CSRF-Token": csrf}

    first = business_client.post(
        "/api/inquiries/1/action",
        json={"action": "ignored"},
        headers=headers,
    )
    second = business_client.post(
        "/api/inquiries/1/action",
        json={"action": "ignored"},
        headers=headers,
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["handling_status"] == "ignored"
    assert second.json()["handling_status"] == "ignored"
    assert [event["event_type"] for event in second.json()["timeline"]] == [
        "inquiry_created",
        "inquiry_ignored",
    ]


def test_inquiry_handling_action_can_be_processed_and_analysis_counts_it(business_client):
    login(business_client, "operator", "operator1")
    csrf = business_client.cookies.get("ea_csrf")
    response = business_client.post(
        "/api/inquiries/1/action",
        json={"action": "processed"},
        headers={"Origin": "https://testserver", "X-CSRF-Token": csrf},
    )

    assert response.status_code == 200
    assert response.json()["handling_status"] == "processed"
    analysis = business_client.post("/api/internal-analysis", json={"operation": "read"})
    assert analysis.status_code == 200
    assert analysis.json()["inquiries_by_handling_status"] == {
        "pending": 0,
        "processed": 1,
        "ignored": 0,
    }


def test_inquiry_handling_action_rolls_back_event_and_status_on_commit_failure(monkeypatch, business_client):
    login(business_client, "operator", "operator1")
    csrf = business_client.cookies.get("ea_csrf")
    original_commit = Session.commit

    def fail_commit(self):
        raise RuntimeError("fixture audit commit failure")

    monkeypatch.setattr(Session, "commit", fail_commit)
    response = business_client.post(
        "/api/inquiries/1/action",
        json={"action": "ignored"},
        headers={"Origin": "https://testserver", "X-CSRF-Token": csrf},
    )
    assert response.status_code == 500

    monkeypatch.setattr(Session, "commit", original_commit)
    login(business_client, "operator", "operator1")
    inquiry = business_client.get("/api/inquiries/1")
    assert inquiry.json()["handling_status"] == "pending"
    assert [event["event_type"] for event in inquiry.json()["timeline"]] == ["inquiry_created"]


def test_invalid_human_action_is_rejected_before_database_write(business_client):
    login(business_client, "operator", "operator1")
    csrf = business_client.cookies.get("ea_csrf")
    response = business_client.post(
        "/api/messages/1/action",
        json={"action": "send"},
        headers={"Origin": "https://testserver", "X-CSRF-Token": csrf},
    )

    assert response.status_code == 422
    assert business_client.get("/api/messages/1").status_code == 200


def test_message_handling_actions_are_idempotent_and_persisted(business_client):
    login(business_client, "operator", "operator1")
    csrf = business_client.cookies.get("ea_csrf")
    headers = {"Origin": "https://testserver", "X-CSRF-Token": csrf}

    first = business_client.post(
        "/api/messages/1/action",
        json={"action": "processed"},
        headers=headers,
    )
    second = business_client.post(
        "/api/messages/1/action",
        json={"action": "processed"},
        headers=headers,
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["handling_status"] == "processed"
    assert second.json()["handling_status"] == "processed"
    assert business_client.get("/api/messages/1").json()["handling_status"] == "processed"


def test_message_handling_action_rolls_back_on_database_failure(monkeypatch, business_client):
    login(business_client, "operator", "operator1")
    csrf = business_client.cookies.get("ea_csrf")
    original_commit = Session.commit

    def fail_commit(self):
        raise RuntimeError("fixture message commit failure")

    monkeypatch.setattr(Session, "commit", fail_commit)
    response = business_client.post(
        "/api/messages/1/action",
        json={"action": "ignored"},
        headers={"Origin": "https://testserver", "X-CSRF-Token": csrf},
    )
    assert response.status_code == 500

    monkeypatch.setattr(Session, "commit", original_commit)
    login(business_client, "operator", "operator1")
    assert business_client.get("/api/messages/1").json()["handling_status"] == "pending"


def test_human_action_does_not_reveal_unscoped_inquiry(business_client):
    login(business_client, "operator", "operator1")
    csrf = business_client.cookies.get("ea_csrf")
    response = business_client.post(
        "/api/inquiries/2/action",
        json={"action": "processed"},
        headers={"Origin": "https://testserver", "X-CSRF-Token": csrf},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "没有权限访问"


def test_transfer_requires_csrf_and_does_not_change_without_it(business_client):
    login(business_client, "operator", "operator1")

    response = business_client.post(
        "/api/inquiries/1/transfer",
        json={"sales_user_id": 3},
        headers={"Origin": "https://testserver"},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "CSRF 校验失败"


def test_operator_transfer_sets_assigned_and_creates_internal_notification(business_client):
    login(business_client, "operator", "operator1")
    csrf = business_client.cookies.get("ea_csrf")

    response = business_client.post(
        "/api/inquiries/1/transfer",
        json={"sales_user_id": 3},
        headers={"Origin": "https://testserver", "X-CSRF-Token": csrf},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "assigned"
    assert response.json()["assigned_sales_user_id"] == 3
    assert [event["event_type"] for event in response.json()["timeline"]] == [
        "inquiry_created",
        "inquiry_transferred",
    ]
    assert response.json()["timeline"][1]["actor_user_id"] == 1
    assert response.json()["timeline"][1]["target_user_id"] == 3

    business_client.post("/auth/logout", headers={"Origin": "https://testserver", "X-CSRF-Token": csrf})
    login(business_client, "sales", "salespass1")
    notifications = business_client.get("/api/notifications/1")
    assert notifications.status_code == 200
    assert notifications.json()["inquiry_id"] == 1
    assert notifications.json()["notification_type"] == "inquiry_assigned"


def test_transfer_rollback_keeps_inquiry_unassigned(monkeypatch, business_client):
    login(business_client, "operator", "operator1")
    csrf = business_client.cookies.get("ea_csrf")
    original_commit = None

    def fail_commit(self):
        nonlocal original_commit
        original_commit = self
        raise RuntimeError("fixture commit failure")

    monkeypatch.setattr(Session, "commit", fail_commit)
    response = business_client.post(
        "/api/inquiries/1/transfer",
        json={"sales_user_id": 3},
        headers={"Origin": "https://testserver", "X-CSRF-Token": csrf},
    )

    assert response.status_code == 500
    assert original_commit is not None
    assert original_commit.in_transaction() is False

    monkeypatch.undo()
    login(business_client, "operator", "operator1")
    inquiry = business_client.get("/api/inquiries/1")
    assert inquiry.status_code == 200
    assert inquiry.json()["status"] == "new"
    assert inquiry.json()["assigned_sales_user_id"] is None
    assert [event["event_type"] for event in inquiry.json()["timeline"]] == ["inquiry_created"]


def test_transfer_db_failure_rolls_back_notification_and_event(monkeypatch, business_client):
    login(business_client, "operator", "operator1")
    csrf = business_client.cookies.get("ea_csrf")
    original_commit = Session.commit

    def fail_commit(self):
        raise RuntimeError("fixture database failure")

    monkeypatch.setattr(Session, "commit", fail_commit)
    response = business_client.post(
        "/api/inquiries/1/transfer",
        json={"sales_user_id": 3},
        headers={"Origin": "https://testserver", "X-CSRF-Token": csrf},
    )
    assert response.status_code == 500

    monkeypatch.setattr(Session, "commit", original_commit)
    login(business_client, "operator", "operator1")
    inquiry = business_client.get("/api/inquiries/1")
    assert inquiry.status_code == 200
    assert inquiry.json()["status"] == "new"
    assert inquiry.json()["assigned_sales_user_id"] is None
    assert [event["event_type"] for event in inquiry.json()["timeline"]] == ["inquiry_created"]


def test_internal_analysis_returns_zero_for_empty_authorized_scope(business_client):
    login(business_client, "empty-operator", "emptyop1")

    response = business_client.post(
        "/api/internal-analysis",
        json={"operation": "read"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["mode"] == "read_only"
    assert data["read_only"] is True
    assert data["pending_message_count"] == 0
    assert data["inquiries_by_status"] == {"new": 0, "assigned": 0}
    assert data["inquiries_by_handling_status"] == {
        "pending": 0,
        "processed": 0,
        "ignored": 0,
    }
    assert data["my_transfers"] == []
    assert data["channel_statuses"] == []


def test_internal_analysis_is_authorized_and_read_only(business_client):
    login(business_client, "operator", "operator1")

    response = business_client.post(
        "/api/internal-analysis",
        json={"operation": "read"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["mode"] == "read_only"
    assert data["read_only"] is True
    assert data["pending_message_count"] == 1
    assert data["inquiries_by_status"] == {"new": 1, "assigned": 0}
    assert data["inquiries_by_handling_status"] == {
        "pending": 1,
        "processed": 0,
        "ignored": 0,
    }
    assert data["my_transfers"] == []
    assert data["test_only"]
    assert data["channel_statuses"] == [
        {
            "channel_account_id": 1,
            "channel_type": "gmail",
            "status": "connected",
            "is_abnormal": False,
        },
        {
            "channel_account_id": 2,
            "channel_type": "outlook",
            "status": "blocked",
            "is_abnormal": True,
        },
    ]
    assert "test_only" in data

    inquiries = business_client.get("/api/inquiries")
    assert [item["status"] for item in inquiries.json()] == ["new"]


def test_sales_analysis_is_scoped_to_assigned_inquiries(business_client):
    login(business_client, "sales", "salespass1")

    response = business_client.post(
        "/api/internal-analysis",
        json={"operation": "read"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["pending_message_count"] == 0
    assert data["inquiries_by_status"] == {"new": 0, "assigned": 1}
    assert data["inquiries_by_handling_status"] == {
        "pending": 1,
        "processed": 0,
        "ignored": 0,
    }
    assert [item["inquiry_id"] for item in data["my_transfers"]] == [3]
    assert data["my_transfers"][0]["current_stage"] == "assigned"
    assert data["my_transfers"][0]["recent_event"]["source"] == "inquiry_events"
    assert data["my_transfers"][0]["recent_event"]["event_history_available"] is True
    assert data["channel_statuses"] == []
    assert data["event_history_available"] is True
    assert data["event_source"] == "inquiry_events"


def test_internal_analysis_requires_auth_and_non_read_is_guidance(business_client):
    assert business_client.post("/api/internal-analysis").status_code == 401

    login(business_client, "operator", "operator1")
    response = business_client.post(
        "/api/internal-analysis",
        json={"operation": "assign"},
    )

    assert response.status_code == 200
    assert response.json()["mode"] == "guidance"
    assert response.json()["read_only"] is True
    assert response.json()["page"] == "/inquiries"


def test_internal_ai_is_read_only_and_returns_operation_guidance(business_client):
    login(business_client, "operator", "operator1")

    read = business_client.post(
        "/api/internal-ai/query",
        json={"query": "inquiries", "operation": "read"},
    )
    assert read.status_code == 200
    assert read.json()["mode"] == "read_only"
    assert read.json()["actor_id"] == 1
    assert read.json()["read_only"] is True
    assert [item["raw_message"] for item in read.json()["data"]] == ["Need a quote"]
    assert read.json()["data"][0]["timeline_complete"] is True

    write = business_client.post(
        "/api/internal-ai/query",
        json={"query": "inquiries", "operation": "assign"},
    )
    assert write.status_code == 200
    assert write.json()["mode"] == "guidance"
    assert write.json()["read_only"] is True
    assert write.json()["page"] == "/inquiries"
