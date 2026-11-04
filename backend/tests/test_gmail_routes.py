import base64
import json
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.channels.inbound import ProviderTemporaryFailure
from app.database import get_db
from app.gmail_routes import get_gmail_client
from app.main import app
from app.models.base import Base
from app.models.business import (
    ChannelAccount,
    ChannelGrant,
    Inquiry,
    InquiryEvent,
    InternalNotification,
    Message,
)
from app.models.user import User


class FakeGmailClient:
    def __init__(self, events=None):
        self.history_calls: list[tuple[int, str]] = []
        self.message_calls: list[tuple[int, str]] = []
        self.events = events

    def list_history(self, *, account_id: int, history_id: str):
        self.history_calls.append((account_id, history_id))
        if self.events is not None:
            return self.events
        return [{"history_id": "history-2", "message_id": "gmail-message-1"}]

    def fetch_message(self, *, account_id: int, message_id: str):
        self.message_calls.append((account_id, message_id))
        return {
            "external_message_id": message_id,
            "direction": "inbound",
            "status": "received",
            "occurred_at": datetime(2026, 10, 22, tzinfo=timezone.utc),
            "raw_content": "test Gmail message",
        }


def encode_notification(history_id: str) -> str:
    return base64.b64encode(json.dumps({"historyId": history_id}).encode()).decode()


@pytest.fixture
def gmail_client(monkeypatch):
    monkeypatch.setenv("GMAIL_PUBSUB_PUSH_TOKEN", "test-push-token")
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session = sessionmaker(bind=engine, expire_on_commit=False)
    Base.metadata.create_all(engine)
    with testing_session() as db:
        db.add(User(
            username="gmail-owner",
            password_hash="hash",
            role="staff",
            is_active=True,
            must_change_password=False,
        ))
        db.flush()
        account = ChannelAccount(owner_user_id=1, channel_type="gmail", status="connected_pending_inbound")
        db.add(account)
        db.flush()
        db.add(ChannelGrant(
            channel_account_id=account.id,
            channel_type="gmail",
            owner_user_id=1,
        ))
        revoked_account = ChannelAccount(owner_user_id=1, channel_type="gmail", status="revoked")
        db.add(revoked_account)
        db.flush()
        db.add(ChannelGrant(
            channel_account_id=revoked_account.id,
            channel_type="gmail",
            owner_user_id=1,
        ))
        db.flush()
        inquiry = Inquiry(
            customer_contact="existing@example.com",
            customer_nickname="Existing Customer",
            raw_message="Existing inquiry",
            source_channel_account_id=account.id,
            status="new",
            handling_status="processed",
        )
        db.add(inquiry)
        db.flush()
        db.add_all(
            [
                InquiryEvent(
                    inquiry_id=inquiry.id,
                    event_type="inquiry_created",
                    to_status="new",
                ),
                InternalNotification(
                    inquiry_id=inquiry.id,
                    notification_type="existing",
                    content="Existing notification",
                ),
            ]
        )
        db.commit()

    fake = FakeGmailClient()

    def override_db():
        with testing_session() as db:
            yield db

    def counts():
        with testing_session() as db:
            return {
                "messages": db.query(Message).count(),
                "inquiries": db.query(Inquiry).count(),
                "events": db.query(InquiryEvent).count(),
                "notifications": db.query(InternalNotification).count(),
                "handling_statuses": db.execute(
                    select(Inquiry.id, Inquiry.handling_status)
                ).all(),
                "gmail_status": db.get(ChannelAccount, 1).status,
            }

    def override_client():
        return fake

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_gmail_client] = override_client
    with TestClient(app, base_url="https://testserver") as client:
        yield client, fake, counts
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)
    engine.dispose()


def headers(token="test-push-token"):
    return {"X-Gmail-PubSub-Token": token}


def test_gmail_pubsub_accepts_urlsafe_unpadded_numeric_history_id(gmail_client):
    client, fake, counts = gmail_client
    encoded = base64.urlsafe_b64encode(json.dumps({"historyId": 123456}).encode()).decode().rstrip("=")
    response = client.post(
        "/api/integrations/gmail/pubsub/1",
        json={"message": {"data": encoded}},
        headers=headers(),
    )
    assert response.status_code == 202
    assert fake.history_calls == [(1, "123456")]


def test_gmail_pubsub_route_fetches_history_details_and_ingests(gmail_client):
    client, fake, counts = gmail_client
    response = client.post(
        "/api/integrations/gmail/pubsub/1",
        json={"message": {"data": encode_notification("history-1")}},
        headers=headers(),
    )
    assert response.status_code == 202
    assert response.json() == {"accepted": 1, "created": 1, "cursor": "history-2"}
    assert fake.history_calls == [(1, "history-1")]
    assert counts()["gmail_status"] == "verified_inbound"
    assert fake.message_calls == [(1, "gmail-message-1")]


def test_gmail_pubsub_uses_persisted_cursor_and_advances_it(gmail_client):
    client, fake, counts = gmail_client
    first = client.post(
        "/api/integrations/gmail/pubsub/1",
        json={"message": {"data": encode_notification("notification-1")}},
        headers=headers(),
    )
    assert first.status_code == 202

    fake.events = [{"history_id": "history-3", "message_id": "gmail-message-2"}]
    second = client.post(
        "/api/integrations/gmail/pubsub/1",
        json={"message": {"data": encode_notification("notification-2")}},
        headers=headers(),
    )
    assert second.status_code == 202
    assert fake.history_calls == [(1, "notification-1"), (1, "history-2")]
def test_gmail_pubsub_empty_history_does_not_advance_cursor(gmail_client):
    client, fake, counts = gmail_client
    fake.events = []

    response = client.post(
        "/api/integrations/gmail/pubsub/1",
        json={"message": {"data": encode_notification("history-empty")}},
        headers=headers(),
    )

    assert response.status_code == 202
    assert response.json() == {"accepted": 0, "created": 0, "cursor": None}
    assert fake.message_calls == []


def test_gmail_pubsub_duplicate_delivery_is_idempotent(gmail_client):
    client, fake, counts = gmail_client
    request = {
        "json": {"message": {"data": encode_notification("history-1")}},
        "headers": headers(),
    }
    first = client.post("/api/integrations/gmail/pubsub/1", **request)
    second = client.post("/api/integrations/gmail/pubsub/1", **request)

    assert first.json()["created"] == 1
    assert second.json()["created"] == 0
    assert fake.history_calls == [(1, "history-1"), (1, "history-2")]
    assert fake.message_calls == [(1, "gmail-message-1"), (1, "gmail-message-1")]
    assert counts()["messages"] == 1


def test_gmail_replay_does_not_create_day4_business_side_effects(gmail_client):
    client, fake, counts = gmail_client
    before = counts()
    request = {
        "json": {"message": {"data": encode_notification("history-1")}},
        "headers": headers(),
    }

    first = client.post("/api/integrations/gmail/pubsub/1", **request)
    after_first = counts()
    second = client.post("/api/integrations/gmail/pubsub/1", **request)
    after_second = counts()

    assert first.status_code == 202
    assert second.status_code == 202
    assert first.json()["created"] == 1
    assert second.json()["created"] == 0
    assert after_first["messages"] == before["messages"] + 1
    assert after_second["messages"] == after_first["messages"]
    assert after_second["inquiries"] == before["inquiries"]
    assert after_second["events"] == before["events"]
    assert after_second["notifications"] == before["notifications"]
    assert after_second["handling_statuses"] == before["handling_statuses"]
    assert fake.message_calls == [(1, "gmail-message-1"), (1, "gmail-message-1")]


def test_gmail_pubsub_skips_missing_message_id_without_advancing_cursor(gmail_client):
    client, fake, counts = gmail_client
    fake.events = [{"history_id": "history-missing-id"}]

    response = client.post(
        "/api/integrations/gmail/pubsub/1",
        json={"message": {"data": encode_notification("history-1")}},
        headers=headers(),
    )

    assert response.status_code == 202
    assert response.json() == {"accepted": 0, "created": 0, "cursor": None}
    assert fake.message_calls == []


def test_gmail_pubsub_revoked_account_is_rejected_before_provider_call(gmail_client):
    client, fake, counts = gmail_client
    before = counts()

    response = client.post(
        "/api/integrations/gmail/pubsub/2",
        json={"message": {"data": encode_notification("history-revoked")}},
        headers=headers(),
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "没有权限访问"
    assert fake.history_calls == []
    assert fake.message_calls == []
    assert counts() == before


def test_gmail_pubsub_rejects_invalid_token_and_unconnected_account(gmail_client):
    client, fake, counts = gmail_client
    invalid = client.post(
        "/api/integrations/gmail/pubsub/1",
        json={"message": {"data": encode_notification("history-1")}},
        headers=headers("wrong-token"),
    )
    assert invalid.status_code == 403
    assert invalid.json()["detail"] == "没有权限访问"

    unconnected = client.post(
        "/api/integrations/gmail/pubsub/999",
        json={"message": {"data": encode_notification("history-1")}},
        headers=headers(),
    )
    assert unconnected.status_code == 403


def test_gmail_pubsub_provider_failure_does_not_return_cursor(gmail_client):
    client, fake, counts = gmail_client

    def fail_history(*, account_id, history_id):
        raise ProviderTemporaryFailure("provider temporarily unavailable")

    fake.list_history = fail_history
    with pytest.raises(ProviderTemporaryFailure, match="provider temporarily unavailable"):
        client.post(
            "/api/integrations/gmail/pubsub/1",
            json={"message": {"data": encode_notification("history-1")}},
            headers=headers(),
        )

    assert fake.message_calls == []


def test_gmail_pubsub_rejects_invalid_payload(gmail_client):
    client, fake, counts = gmail_client
    response = client.post(
        "/api/integrations/gmail/pubsub/1",
        json={"message": {"data": base64.b64encode(b"{}").decode()}},
        headers=headers(),
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "Gmail historyId is required"


def test_gmail_pubsub_requires_push_auth_configuration(monkeypatch, gmail_client):
    client, fake, counts = gmail_client
    monkeypatch.delenv("GMAIL_PUBSUB_PUSH_TOKEN")
    response = client.post(
        "/api/integrations/gmail/pubsub/1",
        json={"message": {"data": encode_notification("history-1")}},
        headers=headers(),
    )
    assert response.status_code == 503
    assert response.json()["detail"] == "gmail push authentication is not configured"


def test_gmail_pubsub_reports_unconfigured_real_client(monkeypatch, gmail_client):
    client, fake, counts = gmail_client
    app.dependency_overrides.pop(get_gmail_client)
    response = client.post(
        "/api/integrations/gmail/pubsub/1",
        json={"message": {"data": encode_notification("history-1")}},
        headers=headers(),
    )
    assert response.status_code == 503
    assert response.json()["detail"] == "gmail provider is not configured"
