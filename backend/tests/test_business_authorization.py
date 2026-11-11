from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
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
    InquiryMessage,
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
                User(username="admin", password_hash=hash_password("adminpass1"), role="admin", is_active=True, must_change_password=False),
            ]
        )
        db.flush()
        first_account = ChannelAccount(owner_user_id=1, channel_type="gmail", status="connected")
        blocked_account = ChannelAccount(owner_user_id=1, channel_type="outlook", status="blocked")
        other_account = ChannelAccount(owner_user_id=2, channel_type="outlook", status="connected")
        revoked_account = ChannelAccount(owner_user_id=1, channel_type="gmail", status="revoked")
        admin_account = ChannelAccount(owner_user_id=6, channel_type="gmail", status="connected")
        db.add_all([first_account, blocked_account, other_account, revoked_account, admin_account])
        db.flush()
        db.add_all(
            [
                ChannelGrant(channel_account_id=first_account.id, channel_type="gmail", owner_user_id=1),
                ChannelGrant(channel_account_id=blocked_account.id, channel_type="outlook", owner_user_id=1),
                ChannelGrant(channel_account_id=other_account.id, channel_type="outlook", owner_user_id=2),
                ChannelGrant(channel_account_id=revoked_account.id, channel_type="gmail", owner_user_id=1),
                ChannelGrant(channel_account_id=admin_account.id, channel_type="gmail", owner_user_id=6),
                Message(
                    channel_account_id=first_account.id,
                    provider="gmail_api_pubsub",
                    external_message_id="fixture-gmail-1",
                    direction="inbound",
                    status="received",
                    handling_status="pending",
                    occurred_at=datetime(2026, 10, 23, tzinfo=timezone.utc),
                    raw_content="Fake fixture message",
                    customer_contact="Customer <customer@example.com>",
                    normalized_customer_contact="customer@example.com",
                    contact_identity_state="certain",
                    contact_identity_kind="email",
                    link_state="linked",
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
                    customer_contact="Secret <secret-revoked@example.com>",
                    customer_nickname="Secret",
                    normalized_customer_contact="secret-revoked@example.com",
                    contact_identity_state="certain",
                    contact_identity_kind="email",
                    link_state="linked",
                ),
                Message(
                    channel_account_id=first_account.id,
                    provider="gmail_api_pubsub",
                    external_message_id="fixture-unmatched-review",
                    direction="inbound",
                    status="received",
                    handling_status="pending",
                    occurred_at=datetime(2026, 10, 23, tzinfo=timezone.utc),
                    raw_content="manual review fixture",
                    customer_contact="private-review@example.com",
                    normalized_customer_contact="private-review@example.com",
                    contact_identity_state="identity_uncertain",
                    contact_identity_kind="email",
                    link_state="manual_review",
                ),
                Message(
                    channel_account_id=first_account.id,
                    provider="gmail_api_pubsub",
                    external_message_id="fixture-unmatched",
                    direction="inbound",
                    status="received",
                    handling_status="pending",
                    occurred_at=datetime(2026, 10, 23, tzinfo=timezone.utc),
                    raw_content="unmatched fixture",
                    customer_contact="private-unmatched@example.com",
                    normalized_customer_contact="private-unmatched@example.com",
                    contact_identity_state="certain",
                    contact_identity_kind="email",
                    link_state="unmatched",
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
                    customer_contact="other@example.com",
                    normalized_customer_contact="other@example.com",
                    contact_identity_state="certain",
                    contact_identity_kind="email",
                    link_state="linked",
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
                    customer_contact="mine@example.com",
                    normalized_customer_contact="mine@example.com",
                    contact_identity_state="certain",
                    contact_identity_kind="email",
                    link_state="linked",
                ),
                Inquiry(
                    customer_contact="customer@example.com",
                    normalized_customer_contact="customer@example.com",
                    contact_identity_state="certain",
                    contact_identity_kind="email",
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
                    message_links=[
                        InquiryMessage(inquiry_id=1, message_id=1, position=1, link_source="fixture"),
                    ],
                ),
                Inquiry(
                    customer_contact="other@example.com",
                    normalized_customer_contact="other@example.com",
                    contact_identity_state="certain",
                    contact_identity_kind="email",
                    customer_nickname="Other Customer",
                    raw_message="Other inquiry",
                    source_channel_account_id=other_account.id,
                    status="new",
                    assigned_sales_user_id=4,
                ),
                Inquiry(
                    customer_contact="mine@example.com",
                    normalized_customer_contact="mine@example.com",
                    contact_identity_state="certain",
                    contact_identity_kind="email",
                    customer_nickname="Assigned Customer",
                    raw_message="Assigned inquiry",
                    source_channel_account_id=other_account.id,
                    status="assigned",
                    handling_status="pending",
                    assigned_sales_user_id=3,
                    last_activity_at=datetime(2026, 10, 23, 4, tzinfo=timezone.utc),
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
                    message_links=[InquiryMessage(inquiry_id=3, message_id=6, position=1, link_source="fixture")],
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
                    normalized_customer_contact="revoked@example.com",
                    contact_identity_state="certain",
                    contact_identity_kind="email",
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
    with TestClient(app, base_url="https://testserver", raise_server_exceptions=True) as client:
        client.testing_session = testing_session
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


def test_gmail_account_initialization_is_idempotent_and_not_provider_connected(business_client):
    login(business_client, "empty-operator", "emptyop1")
    csrf = business_client.cookies.get("ea_csrf")
    headers = {"Origin": "https://testserver", "X-CSRF-Token": csrf}

    first = business_client.post("/api/channels/gmail/accounts", headers=headers)
    second = business_client.post("/api/channels/gmail/accounts", headers=headers)

    assert first.status_code == 200
    assert first.json()["channel_type"] == "gmail"
    assert first.json()["status"] == "not_ready"
    assert first.json()["external_account_id"] is None
    assert second.status_code == 200
    assert second.json()["id"] == first.json()["id"]
    assert second.json()["status"] == "not_ready"


def test_gmail_account_initialization_requires_authentication(business_client):
    assert business_client.post("/api/channels/gmail/accounts").status_code == 401


def test_whatsapp_account_initialization_repairs_scope_after_revoke(business_client):
    login(business_client, "empty-operator", "emptyop1")
    csrf = business_client.cookies.get("ea_csrf")
    headers = {"Origin": "https://testserver", "X-CSRF-Token": csrf}

    first = business_client.post("/api/channels/whatsapp/accounts", headers=headers)
    assert first.status_code == 200
    account_id = first.json()["id"]
    assert first.json()["status"] == "not_ready"

    revoked = business_client.post(
        f"/api/channels/accounts/{account_id}/revoke",
        headers=headers,
    )
    assert revoked.status_code == 200
    assert revoked.json()["status"] == "revoked"

    repaired = business_client.post("/api/channels/whatsapp/accounts", headers=headers)
    assert repaired.status_code == 200
    assert repaired.json()["id"] == account_id
    assert repaired.json()["status"] == "not_ready"
    assert business_client.get("/api/channel-accounts").json() == [
        {
            "id": account_id,
            "owner_user_id": 5,
            "channel_type": "whatsapp",
            "status": "not_ready",
        }
    ]


def test_revoked_channel_is_not_readable_but_history_is_retained(business_client):
    login(business_client, "operator", "operator1")

    accounts = business_client.get("/api/channel-accounts")
    messages = business_client.get("/api/messages")
    inquiries = business_client.get("/api/inquiries")

    assert accounts.status_code == 200
    assert all(account["status"] != "revoked" for account in accounts.json())
    assert messages.status_code == 200
    assert all(message["external_message_id"] != "revoked-gmail-1" for message in messages.json()["items"])
    assert inquiries.status_code == 200
    assert [item["id"] for item in inquiries.json()["items"]] == [1]
    assert [item["id"] for item in inquiries.json()["items"][0]["messages"]] == [1]
    assert "Revoked account historical message" not in str(inquiries.json()["items"])
    assert "Secret <secret-revoked@example.com>" not in str(inquiries.json()["items"])
    # The only Inquiry tied to this revoked source has no visible linked message.
    # Its detail is hidden as 404 and the list total/sort contains no trace.
    assert business_client.get("/api/messages/2").status_code == 403
    assert business_client.get("/api/inquiries/4").status_code == 404


def test_operator_reads_authorized_safe_message_content_only(business_client):
    login(business_client, "operator", "operator1")

    response = business_client.get("/api/messages/1/content")

    assert response.status_code == 200
    body = response.json()
    assert body["source"] == {
        "kind": "cached_safe_text",
        "provider": "gmail_api_pubsub",
        "external_message_id": "fixture-gmail-1",
        "live_refetch": False,
        "fallback_reason": "provider_refetch_unavailable",
        "authoritative": True,
        "refetch_status": "snapshot",
        "snapshot_at": body["source"]["snapshot_at"],
    }
    assert body["raw_content_exposed"] is False
    assert body["parsed_content"]["content_format"] == "text/plain"
    assert body["parsed_content"]["content_sanitized"] is True
    assert body["full_text"] == "Fake fixture message"
    assert body["preview_text"] == "Fake fixture message"
    assert body["attachments"] == [{
        "id": body["attachments"][0]["id"],
        "original_filename": "fixture.pdf",
        "media_type": "application/pdf",
        "size_bytes": 42,
    }]
    assert "storage_reference" not in body["attachments"][0]
    assert "raw_content" not in body


def test_message_content_rejects_cross_account_and_revoked_messages(business_client):
    login(business_client, "operator", "operator1")

    assert business_client.get("/api/messages/5/content").status_code == 403
    assert business_client.get("/api/messages/2/content").status_code == 403
    assert business_client.get("/api/messages/999/content").status_code == 403


def test_review_messages_are_filtered_and_scoped(business_client):
    login(business_client, "operator", "operator1")
    review = business_client.get("/api/messages", params={"needs_review": "true"})
    assert review.status_code == 200
    assert {item["external_message_id"] for item in review.json()["items"]} == {"fixture-unmatched-review"}


def test_operator_reads_only_granted_owned_channel_and_inquiries(business_client):
    login(business_client, "operator", "operator1")

    messages = business_client.get("/api/messages")
    assert messages.status_code == 200
    messages_by_external_id = {
        message["external_message_id"]: message for message in messages.json()["items"]
    }
    assert set(messages_by_external_id) == {
        "fixture-gmail-1",
        "fixture-unmatched-review",
        "fixture-unmatched",
    }
    message = messages_by_external_id["fixture-gmail-1"]
    assert message["channel_type"] == "gmail"
    assert message["ingestion_status"] == "received"
    assert message["handling_status"] == "pending"
    assert message["attachments"] == [
        {
            "id": message["attachments"][0]["id"],
            "original_filename": "fixture.pdf",
            "media_type": "application/pdf",
            "size_bytes": 42,
        }
    ]
    assert "storage_reference" not in message["attachments"][0]
    assert business_client.get("/api/messages/2").status_code == 403
    assert business_client.get("/api/messages/999").status_code == 403

    accounts = business_client.get("/api/channel-accounts")
    assert accounts.status_code == 200
    assert [account["channel_type"] for account in accounts.json()] == ["gmail", "outlook"]
    assert accounts.json()[1]["status"] == "blocked"

    inquiries = business_client.get("/api/inquiries")
    assert inquiries.status_code == 200
    inquiry_data = inquiries.json()["items"][0]
    assert inquiry_data["timeline_complete"] is False
    assert inquiry_data["attachments"] == []
    assert inquiry_data["source_channel_account_id"] is None
    assert inquiry_data["contact_sources"][0]["raw_customer_contact"] == "Customer <customer@example.com>"
    assert inquiry_data["messages"][0]["id"] == 1
    assert inquiry_data["messages"][0]["provider"] == "gmail_api_pubsub"
    assert inquiry_data["messages"][0]["external_message_id"] == "fixture-gmail-1"
    assert inquiry_data["messages"][0]["overview_status"] is None
    assert "raw_content" not in inquiry_data["messages"][0]
    assert "overview_text" not in inquiry_data["messages"][0]
    assert "raw_content" not in inquiry_data
    assert "display_text" not in inquiry_data
    assert "overview_text" not in str(inquiry_data)
    assert "Revoked account historical message" not in str(inquiries.json()["items"][0])
    assert "secret-revoked@example.com" not in str(inquiries.json()["items"][0])
    assert len(inquiries.json()["items"][0]["messages"]) == 1
    assert [event["event_type"] for event in inquiries.json()["items"][0]["timeline"]] == ["inquiry_created"]

    assert business_client.get("/api/inquiries/2").status_code == 404


def test_sales_reads_only_assigned_inquiry_and_notification(business_client):
    login(business_client, "sales", "salespass1")

    messages = business_client.get("/api/messages")
    assert messages.status_code == 200
    # Sales can read only messages linked to their assigned inquiry, never
    # unrelated account-wide mail.
    assert [message["id"] for message in messages.json()["items"]] == [6]
    assert business_client.get("/api/messages/1").status_code == 403
    assert business_client.get("/api/messages/6").status_code == 200
    assert business_client.get("/api/messages/5").status_code == 403
    assert business_client.get("/api/messages/2").status_code == 403
    assert business_client.get("/api/messages/999").status_code == 403

    inquiries = business_client.get("/api/inquiries")
    assert inquiries.status_code == 200
    assert [inquiry["id"] for inquiry in inquiries.json()["items"]] == [3]
    assert [message["id"] for message in inquiries.json()["items"][0]["messages"]] == [6]
    assert inquiries.json()["items"][0]["attachments"][0]["media_type"] == "image/png"
    assert "storage_reference" not in inquiries.json()["items"][0]["attachments"][0]
    assert inquiries.json()["items"][0]["timeline_complete"] is True
    assert [event["event_type"] for event in inquiries.json()["items"][0]["timeline"]] == [
        "inquiry_created",
        "inquiry_transferred",
    ]

    assert business_client.get("/api/inquiries/2").status_code == 404
    assert business_client.get("/api/notifications/1").status_code == 403
    assert business_client.get("/api/inquiries/4").status_code == 404


def test_sales_cannot_read_revoked_source_inquiry(business_client):
    login(business_client, "sales", "salespass1")

    inquiries = business_client.get("/api/inquiries")

    assert inquiries.status_code == 200
    assert [item["id"] for item in inquiries.json()["items"]] == [3]
    assert business_client.get("/api/inquiries/4").status_code == 404


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

    assert response.status_code == 404
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
    assert first.status_code == 409
    assert "关联询盘" in first.json()["detail"]
    assert business_client.get("/api/messages/1").json()["handling_status"] == "pending"


def test_message_handling_action_rolls_back_on_database_failure(monkeypatch, business_client):
    login(business_client, "operator", "operator1")
    csrf = business_client.cookies.get("ea_csrf")
    original_commit = Session.commit

    def fail_commit(self):
        raise RuntimeError("fixture message commit failure")

    monkeypatch.setattr(Session, "commit", fail_commit)
    response = business_client.post(
        "/api/inquiries/1/action",
        json={"action": "processed"},
        headers={"Origin": "https://testserver", "X-CSRF-Token": csrf},
    )
    assert response.status_code == 500

    monkeypatch.setattr(Session, "commit", original_commit)
    login(business_client, "operator", "operator1")
    assert business_client.get("/api/inquiries/1").json()["handling_status"] == "pending"
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
    original_commit = Session.commit

    def fail_commit(self):
        raise RuntimeError("fixture commit failure")

    monkeypatch.setattr(Session, "commit", fail_commit)
    response = business_client.post(
        "/api/inquiries/1/transfer",
        json={"sales_user_id": 3},
        headers={"Origin": "https://testserver", "X-CSRF-Token": csrf},
    )

    assert response.status_code == 500

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
    assert data["mutation_performed"] is False
    assert data["write_operations_performed"] == 0
    assert data["unlinked_messages"] == []
    assert data["messages_needing_manual_review"] == []
    assert data["pending_message_count"] == 0
    assert data["inquiries_by_status"] == {"new": 0, "assigned": 0}
    assert data["inquiries_by_handling_status"] == {
        "pending": 0,
        "processed": 0,
        "ignored": 0,
    }
    assert data["my_transfers"] == []
    assert data["channel_statuses"] == []
    assert data["messages_by_link_state"] == {"pending": 0, "linked": 0, "unmatched": 0, "manual_review": 0, "not_linkable": 0}
    assert data["inquiries_by_lifecycle_stage"] == {"unknown": 0, "active": 0, "archived_silent": 0, "purge_due": 0}


def _business_read_snapshot(session):
    return {
        "inquiries": tuple(session.execute(select(Inquiry.id, Inquiry.status, Inquiry.handling_status, Inquiry.assigned_sales_user_id, Inquiry.last_activity_at)).all()),
        "messages": tuple(session.execute(select(Message.id, Message.handling_status, Message.link_state, Message.contact_identity_state, Message.contact_identity_kind, Message.customer_contact, Message.normalized_customer_contact, Message.original_sender_contact)).all()),
        "events": tuple(session.execute(select(InquiryEvent.id, InquiryEvent.inquiry_id, InquiryEvent.event_type, InquiryEvent.message_id)).all()),
        "notifications": tuple(session.execute(select(InternalNotification.id, InternalNotification.inquiry_id, InternalNotification.notification_type, InternalNotification.content)).all()),
        "accounts": tuple(session.execute(select(ChannelAccount.id, ChannelAccount.status)).all()),
        "links": tuple(session.execute(select(InquiryMessage.inquiry_id, InquiryMessage.message_id, InquiryMessage.position)).all()),
    }


def test_internal_analysis_excludes_revoked_only_inquiry_and_manual_review_is_scoped(business_client):
    login(business_client, "operator", "operator1")
    response = business_client.post("/api/internal-analysis", json={"operation": "read"})
    assert response.status_code == 200
    data = response.json()
    assert all(row["id"] != 4 for row in data["unlinked_messages"])
    assert all(row["id"] != 2 for row in data["messages_needing_manual_review"])
    # Blocked account remains an authorized account and is surfaced distinctly.
    assert any(row["channel_account_id"] == 2 and row["status"] == "blocked" for row in data["channel_statuses"])


def test_internal_analysis_exposes_only_assigned_scope_to_sales_and_admin_scope_is_not_global(business_client):
    login(business_client, "admin", "adminpass1")
    admin_data = business_client.post("/api/internal-analysis", json={"operation": "read"}).json()
    assert admin_data["query_scope"] == "current_user_authorized_objects"
    assert admin_data["pending_message_count"] == 0
    assert admin_data["inquiries_by_status"] == {"new": 0, "assigned": 0}

    business_client.post("/auth/logout", headers={"Origin": "https://testserver", "X-CSRF-Token": business_client.cookies.get("ea_csrf")})
    login(business_client, "sales", "salespass1")
    sales_data = business_client.post("/api/internal-analysis", json={"operation": "read"}).json()
    assert sales_data["pending_message_count"] == 1
    assert sales_data["inquiries_by_status"] == {"new": 0, "assigned": 1}
    assert sales_data["messages_by_link_state"]["linked"] == 1


def test_internal_analysis_is_authorized_and_read_only(business_client, monkeypatch):
    login(business_client, "operator", "operator1")
    commit_calls = []
    original_commit = Session.commit

    def track_commit(session):
        commit_calls.append(True)
        return original_commit(session)

    with business_client.testing_session() as snapshot_session:
        before_snapshot = _business_read_snapshot(snapshot_session)
    monkeypatch.setattr(Session, "commit", track_commit)
    response = business_client.post(
        "/api/internal-analysis",
        json={"operation": "read"},
    )

    assert response.status_code == 200
    assert commit_calls == []
    with business_client.testing_session() as snapshot_session:
        after_snapshot = _business_read_snapshot(snapshot_session)
    assert after_snapshot == before_snapshot
    data = response.json()
    assert data["mode"] == "read_only"
    assert data["read_only"] is True
    assert data["pending_message_count"] == 3
    assert data["pending_inbound_message_count"] == 3
    assert data["pending_contact_count"] == 2
    assert data["messages_by_link_state"]["linked"] == 1
    assert data["messages_by_link_state"]["manual_review"] == 1
    assert data["messages_by_link_state"]["unmatched"] == 1
    assert data["messages_by_identity_state"]["identity_uncertain"] == 1
    assert data["inquiries_by_lifecycle_stage"]["unknown"] == 1
    assert len(data["unlinked_messages"]) == 1
    assert "customer_contact" not in data["unlinked_messages"][0]
    assert data["messages_needing_manual_review"][0]["id"] == 3
    assert data["messages_by_identity_state"]["certain"] == 2
    assert data["messages_by_identity_state"]["identity_uncertain"] == 1
    assert data["recent_events"][0]["event_type"] == "inquiry_created"
    assert data["unlinked_messages"][0]["id"] == 4
    assert data["inquiries_by_status"] == {"new": 1, "assigned": 0}
    assert data["inquiries_by_handling_status"] == {
        "pending": 1,
        "processed": 0,
        "ignored": 0,
    }
    assert data["my_transfers"] == []
    assert data["test_only"]
    assert len(data["recent_events"]) == 1
    assert data["recent_events"][0]["inquiry_id"] == 1
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
    assert [item["status"] for item in inquiries.json()["items"]] == ["new"]


def test_internal_analysis_includes_blocked_but_authorized_account_and_excludes_revoked(business_client):
    login(business_client, "operator", "operator1")
    with business_client.testing_session() as db:
        db.add(Message(
            channel_account_id=2,
            provider="outlook_mcp_graph",
            external_message_id="blocked-fixture",
            direction="inbound",
            status="received",
            handling_status="pending",
            occurred_at=datetime(2026, 10, 24, tzinfo=timezone.utc),
            raw_content="blocked account fixture",
            customer_contact="blocked@example.com",
            normalized_customer_contact="blocked@example.com",
            contact_identity_state="certain",
            contact_identity_kind="email",
            link_state="unmatched",
        ))
        db.commit()

    response = business_client.post("/api/internal-analysis", json={"operation": "read"})
    assert response.status_code == 200
    data = response.json()
    assert data["pending_message_count"] == 4
    assert any(item["channel_account_id"] == 2 and item["status"] == "blocked" for item in data["channel_statuses"])
    assert 2 not in {item["channel_account_id"] for item in data["unlinked_messages"]} or any(
        item["provider"] == "outlook_mcp_graph" for item in data["unlinked_messages"]
    )
    assert all("secret-revoked@example.com" not in str(item) for item in data["unlinked_messages"])


def test_sales_analysis_is_scoped_to_assigned_inquiries(business_client):
    login(business_client, "sales", "salespass1")

    response = business_client.post(
        "/api/internal-analysis",
        json={"operation": "read"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["pending_message_count"] == 1
    assert data["pending_inbound_message_count"] == 1
    assert data["pending_contact_count"] == 1
    assert data["messages_by_link_state"]["linked"] == 1
    assert data["unlinked_messages"] == []
    assert data["messages_needing_manual_review"] == []
    assert data["inquiries_by_lifecycle_stage"]["active"] == 1
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


def test_internal_analysis_requires_auth_and_non_read_is_guidance(business_client, monkeypatch):
    assert business_client.post("/api/internal-analysis").status_code == 401

    login(business_client, "operator", "operator1")
    from sqlalchemy.orm import Session

    original_commit = Session.commit
    commits = []
    def track_commit(self):
        commits.append(True)
        return original_commit(self)
    monkeypatch.setattr(Session, "commit", track_commit)

    with business_client.testing_session() as snapshot_session:
        before_snapshot = _business_read_snapshot(snapshot_session)
    for operation in ("create", "update", "delete", "assign", "send"):
        response = business_client.post(
            "/api/internal-analysis",
            json={"operation": operation},
        )
        assert response.status_code == 200
        assert response.json()["mode"] == "guidance"
        assert response.json()["read_only"] is True
        assert response.json()["page"] == ("/messages" if operation == "send" else "/inquiries")
        with business_client.testing_session() as snapshot_session:
            assert _business_read_snapshot(snapshot_session) == before_snapshot
    assert commits == []
    with business_client.testing_session() as snapshot_session:
        assert _business_read_snapshot(snapshot_session) == before_snapshot


def test_internal_ai_is_read_only_and_returns_operation_guidance(business_client):
    login(business_client, "operator", "operator1")

    with business_client.testing_session() as snapshot_session:
        before_snapshot = _business_read_snapshot(snapshot_session)
    read = business_client.post(
        "/api/internal-ai/query",
        json={"query": "inquiries", "operation": "read"},
    )
    assert read.status_code == 200
    assert read.json()["mode"] == "read_only"
    assert read.json()["actor_id"] == 1
    assert read.json()["read_only"] is True
    assert [item["display_text"] for item in read.json()["data"]] == ["Fake fixture message"]
    assert "Revoked account historical message" not in str(read.json()["data"])
    assert "secret-revoked@example.com" not in str(read.json()["data"])
    assert read.json()["data"][0]["timeline_complete"] is True
    with business_client.testing_session() as snapshot_session:
        assert _business_read_snapshot(snapshot_session) == before_snapshot

    write = business_client.post(
        "/api/internal-ai/query",
        json={"query": "inquiries", "operation": "assign"},
    )
    assert write.status_code == 200
    assert write.json()["mode"] == "guidance"
    assert write.json()["read_only"] is True
    assert write.json()["page"] == "/inquiries"
    with business_client.testing_session() as snapshot_session:
        assert _business_read_snapshot(snapshot_session) == before_snapshot


def test_inbox_list_contract_supports_authorized_filters_sorting_and_pagination(business_client):
    login(business_client, "operator", "operator1")

    messages = business_client.get(
        "/api/messages",
        params={
            "handling_status": "pending",
            "ingestion_status": "received",
            "channel_account_id": 1,
            "sort": "occurred_at",
            "descending": "true",
            "page": 1,
            "page_size": 1,
        },
    )
    inquiries = business_client.get(
        "/api/inquiries",
        params={
            "status": "new",
            "handling_status": "pending",
            "channel_account_id": 1,
            "sort": "updated_at",
            "descending": "true",
            "page": 1,
            "page_size": 1,
        },
    )

    assert messages.status_code == inquiries.status_code == 200
    assert set(messages.json()) == {"items", "page", "page_size", "has_more"}
    assert set(inquiries.json()) == {"items", "page", "page_size", "has_more", "total_count"}
    assert messages.json()["page"] == inquiries.json()["page"] == 1
    assert messages.json()["page_size"] == inquiries.json()["page_size"] == 1
    assert [item["external_message_id"] for item in messages.json()["items"]] == ["fixture-unmatched"]
    assert messages.json()["has_more"] is True
    assert [item["id"] for item in inquiries.json()["items"]] == [1]
    assert messages.json()["items"][0]["ingestion_status"] == "received"
    assert messages.json()["items"][0]["handling_status"] == "pending"
    assert inquiries.json()["items"][0]["status"] == "new"
    assert inquiries.json()["items"][0]["handling_status"] == "pending"


def test_inbox_list_empty_result_is_a_valid_authorized_response(business_client):
    login(business_client, "operator", "operator1")

    response = business_client.get(
        "/api/inquiries",
        params={"handling_status": "processed", "channel_account_id": 1},
    )

    assert response.status_code == 200
    assert response.json() == {
        "items": [],
        "page": 1,
        "page_size": 50,
        "has_more": False,
        "total_count": 0,
    }


def test_inbox_filter_cannot_escape_authorized_channel_scope(business_client):
    login(business_client, "operator", "operator1")

    response = business_client.get(
        "/api/messages",
        params={"channel_account_id": 3},
    )

    assert response.status_code == 200
    assert response.json()["items"] == []


def test_inbox_rejects_invalid_filters_and_paging_before_query_execution(business_client):
    login(business_client, "operator", "operator1")

    invalid_requests = [
        ("/api/messages", {"handling_status": "send"}),
        ("/api/messages", {"ingestion_status": "queued"}),
        ("/api/messages", {"sort": "raw_content"}),
        ("/api/messages", {"page": 0}),
        ("/api/messages", {"page_size": 101}),
        ("/api/inquiries", {"status": "closed"}),
        ("/api/inquiries", {"handling_status": "send"}),
        ("/api/inquiries", {"sort": "id"}),
        ("/api/inquiries", {"channel_account_id": 0}),
    ]

    for path, params in invalid_requests:
        response = business_client.get(path, params=params)
        assert response.status_code == 422, (path, params, response.text)



def test_admin_does_not_bypass_object_scope(business_client):
    login(business_client, "admin", "adminpass1")

    accounts = business_client.get("/api/channel-accounts")
    messages = business_client.get("/api/messages")
    inquiries = business_client.get("/api/inquiries")

    assert accounts.status_code == messages.status_code == inquiries.status_code == 200
    assert accounts.json() == [
        {"id": 5, "owner_user_id": 6, "channel_type": "gmail", "status": "connected"}
    ]
    assert messages.json()["items"] == []
    assert inquiries.json()["items"] == []
    assert business_client.get("/api/messages/1").status_code == 403
    assert business_client.get("/api/inquiries/1").status_code == 404


def test_blocked_account_is_in_scope_but_revoked_account_is_not(business_client):
    login(business_client, "operator", "operator1")

    response = business_client.get("/api/messages", params={"channel_account_id": 2})

    assert response.status_code == 200
    assert response.json()["items"] == []
    assert business_client.get("/api/messages", params={"channel_account_id": 4}).json()["items"] == []
    # Blocked accounts remain in authorized account scope, but revoked accounts
    # and their associated Inquiry summaries stay hidden.
    assert business_client.get("/api/messages/2").status_code == 403
    assert business_client.get("/api/messages/2/content").status_code == 403


def test_pagination_boundaries_are_stable_and_empty_pages_do_not_leak(business_client):
    login(business_client, "operator", "operator1")

    first = business_client.get("/api/messages", params={"page": 1, "page_size": 1, "descending": "false"})
    second = business_client.get("/api/messages", params={"page": 2, "page_size": 1, "descending": "false"})
    beyond = business_client.get("/api/messages", params={"page": 3, "page_size": 1, "descending": "false"})

    assert first.status_code == second.status_code == beyond.status_code == 200
    assert len(first.json()["items"]) == 1
    assert len(second.json()["items"]) == 1
    assert len(beyond.json()["items"]) == 1
    assert first.json()["page"] == 1
    assert second.json()["page"] == 2
    assert beyond.json()["has_more"] is False



def test_provider_action_uses_scoped_message_and_only_supports_verified_gmail_id(business_client):
    login(business_client, "operator", "operator1")

    gmail = business_client.get("/api/messages/1/provider-action")
    cross_account = business_client.get("/api/messages/5/provider-action")
    revoked = business_client.get("/api/messages/2/provider-action")

    assert gmail.status_code == 200
    assert gmail.json()["supported"] is True
    assert gmail.json()["action"] == "open_message"
    assert gmail.json()["url"].startswith("https://mail.google.com/mail/u/0/#all/")
    assert "token" not in gmail.json()["url"]
    assert cross_account.status_code == 403
    assert revoked.status_code == 403


def test_sales_and_cross_account_cannot_get_provider_action(business_client):
    login(business_client, "sales", "salespass1")
    assert business_client.get("/api/messages/1/provider-action").status_code == 403

    business_client.post(
        "/auth/logout",
        headers={"Origin": "https://testserver", "X-CSRF-Token": business_client.cookies.get("ea_csrf")},
    )
    login(business_client, "other-operator", "otherop1")
    assert business_client.get("/api/messages/1/provider-action").status_code == 403



def test_human_actions_reject_changing_an_already_completed_terminal_state(business_client):
    login(business_client, "operator", "operator1")
    csrf = business_client.cookies.get("ea_csrf")
    headers = {"Origin": "https://testserver", "X-CSRF-Token": csrf}

    inquiry_done = business_client.post(
        "/api/inquiries/1/action", json={"action": "processed"}, headers=headers
    )
    message_done = business_client.post(
        "/api/messages/1/action", json={"action": "ignored"}, headers=headers
    )
    inquiry_reverse = business_client.post(
        "/api/inquiries/1/action", json={"action": "ignored"}, headers=headers
    )
    message_reverse = business_client.post(
        "/api/messages/1/action", json={"action": "processed"}, headers=headers
    )

    assert inquiry_done.status_code == 200
    assert message_done.status_code == 409
    assert inquiry_reverse.status_code == 409
    assert message_reverse.status_code == 200
    assert business_client.get("/api/inquiries/1").json()["handling_status"] == "processed"
    assert business_client.get("/api/messages/1").json()["handling_status"] == "processed"


def test_repeated_same_terminal_action_is_idempotent_without_extra_inquiry_event(business_client):
    login(business_client, "operator", "operator1")
    csrf = business_client.cookies.get("ea_csrf")
    headers = {"Origin": "https://testserver", "X-CSRF-Token": csrf}

    first = business_client.post(
        "/api/inquiries/1/action", json={"action": "processed"}, headers=headers
    )
    second = business_client.post(
        "/api/inquiries/1/action", json={"action": "processed"}, headers=headers
    )

    assert first.status_code == second.status_code == 200
    assert [event["event_type"] for event in second.json()["timeline"]] == [
        "inquiry_created", "inquiry_processed"
    ]



def test_cross_function_authorization_contract_matches_for_sales_and_operator(business_client):
    login(business_client, "operator", "operator1")

    operator_analysis = business_client.post("/api/internal-analysis", json={"operation": "read"})
    operator_ai = business_client.post("/api/internal-ai/query", json={"query": "inquiries"})
    operator_notifications = business_client.post("/api/internal-ai/query", json={"query": "notifications"})

    assert operator_analysis.status_code == operator_ai.status_code == operator_notifications.status_code == 200
    assert operator_analysis.json()["inquiries_by_status"] == {"new": 1, "assigned": 0}
    assert [item["id"] for item in operator_ai.json()["data"]] == [1]
    assert operator_notifications.json()["data"] == []
    assert business_client.get("/api/inquiries/2").status_code == 404
    assert business_client.post(
        "/api/inquiries/2/action",
        json={"action": "processed"},
        headers={"Origin": "https://testserver", "X-CSRF-Token": business_client.cookies.get("ea_csrf")},
    ).status_code == 403

    csrf = business_client.cookies.get("ea_csrf")
    business_client.post("/auth/logout", headers={"Origin": "https://testserver", "X-CSRF-Token": csrf})
    login(business_client, "sales", "salespass1")

    sales_analysis = business_client.post("/api/internal-analysis", json={"operation": "read"})
    sales_ai = business_client.post("/api/internal-ai/query", json={"query": "inquiries"})
    sales_notifications = business_client.post("/api/internal-ai/query", json={"query": "notifications"})

    assert sales_analysis.status_code == sales_ai.status_code == sales_notifications.status_code == 200
    assert sales_analysis.json()["inquiries_by_status"] == {"new": 0, "assigned": 1}
    assert [item["id"] for item in sales_ai.json()["data"]] == [3]
    assert sales_notifications.json()["data"] == []
    assert business_client.get("/api/inquiries/1").status_code == 404
    assert business_client.post(
        "/api/inquiries/1/action",
        json={"action": "processed"},
        headers={"Origin": "https://testserver", "X-CSRF-Token": business_client.cookies.get("ea_csrf")},
    ).status_code == 403


def test_revoked_assigned_inquiry_is_absent_from_all_sales_reads_and_actions(business_client):
    login(business_client, "sales", "salespass1")

    assert [item["id"] for item in business_client.get("/api/inquiries").json()["items"]] == [3]
    for path, payload in [
        ("/api/inquiries/4/action", {"action": "processed"}),
        ("/api/inquiries/4/transfer", {"sales_user_id": 3}),
    ]:
        csrf = business_client.cookies.get("ea_csrf")
        response = business_client.post(
            path,
            json=payload,
            headers={"Origin": "https://testserver", "X-CSRF-Token": csrf},
        )
        assert response.status_code == 403
    assert business_client.get("/api/inquiries/4").status_code == 404


def test_website_form_channel_excludes_mislabeled_and_forwarded_messages(business_client):
    from app.message_ingestion import WEBSITE_FORM_EMAIL

    login(business_client, "operator", "operator1")
    session_gen = app.dependency_overrides[get_db]()
    db = next(session_gen)
    try:
        now = datetime(2026, 11, 5, 8, 0, 0, tzinfo=timezone.utc)
        db.add_all(
            [
                Message(
                    channel_account_id=1,
                    provider="gmail_api_pubsub",
                    external_message_id="wf-valid",
                    direction="inbound",
                    status="received",
                    handling_status="pending",
                    occurred_at=now,
                    raw_content="form submission",
                    customer_contact=WEBSITE_FORM_EMAIL,
                    is_website_form=True,
                    contact_identity_state="unsupported",
                    link_state="linked",
                ),
                Message(
                    channel_account_id=1,
                    provider="gmail_api_pubsub",
                    external_message_id="wf-stale-165",
                    direction="inbound",
                    status="received",
                    handling_status="pending",
                    occurred_at=now,
                    raw_content="Medium Daily Digest",
                    customer_contact="noreply@medium.com",
                    is_website_form=True,
                    contact_identity_state="unsupported",
                    link_state="linked",
                ),
                Message(
                    channel_account_id=1,
                    provider="gmail_api_pubsub",
                    external_message_id="wf-forwarded",
                    direction="inbound",
                    status="received",
                    handling_status="pending",
                    occurred_at=now,
                    raw_content="Forwarded Medium Daily Digest",
                    customer_contact=WEBSITE_FORM_EMAIL,
                    original_sender_contact="noreply@medium.com",
                    is_website_form=True,
                    contact_identity_state="unsupported",
                    link_state="linked",
                ),
            ]
        )
        db.commit()
    finally:
        session_gen.close()

    form = business_client.get("/api/messages?channel_type=website_form&handling_status=all")
    assert form.status_code == 200
    # 白名单邮箱转发的真表单（wf-forwarded）也计入渠道；只有发件人非白名单的
    # 历史误标（wf-stale-165）被排除。
    assert sorted(item["external_message_id"] for item in form.json()["items"]) == [
        "wf-forwarded",
        "wf-valid",
    ]

    all_messages = business_client.get("/api/messages?handling_status=all")
    assert all_messages.status_code == 200
    by_id = {item["external_message_id"]: item for item in all_messages.json()["items"]}
    assert by_id["wf-stale-165"]["is_website_form"] is False
    assert by_id["wf-stale-165"]["channel_type"] == "gmail"
    assert by_id["wf-stale-165"]["customer_contact"] == "noreply@medium.com"
    assert by_id["wf-forwarded"]["is_website_form"] is True
