import base64
import json
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import get_db
from app.gmail_routes import get_gmail_client
from app.main import app
from app.models.base import Base
from app.models.business import ChannelAccount, ChannelGrant
from app.models.user import User


class FakeGmailClient:
    def __init__(self):
        self.history_calls: list[tuple[int, str]] = []
        self.message_calls: list[tuple[int, str]] = []

    def list_history(self, *, account_id: int, history_id: str):
        self.history_calls.append((account_id, history_id))
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
        account = ChannelAccount(owner_user_id=1, channel_type="gmail", status="connected")
        db.add(account)
        db.flush()
        db.add(ChannelGrant(
            channel_account_id=account.id,
            channel_type="gmail",
            owner_user_id=1,
        ))
        db.commit()

    fake = FakeGmailClient()

    def override_db():
        with testing_session() as db:
            yield db

    def override_client():
        return fake

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_gmail_client] = override_client
    with TestClient(app, base_url="https://testserver") as client:
        yield client, fake
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)
    engine.dispose()


def headers(token="test-push-token"):
    return {"X-Gmail-PubSub-Token": token}


def test_gmail_pubsub_route_fetches_history_details_and_ingests(gmail_client):
    client, fake = gmail_client
    response = client.post(
        "/api/integrations/gmail/pubsub/1",
        json={"message": {"data": encode_notification("history-1")}},
        headers=headers(),
    )
    assert response.status_code == 202
    assert response.json() == {"accepted": 1, "created": 1, "cursor": "history-2"}
    assert fake.history_calls == [(1, "history-1")]
    assert fake.message_calls == [(1, "gmail-message-1")]


def test_gmail_pubsub_duplicate_delivery_is_idempotent(gmail_client):
    client, _ = gmail_client
    request = {
        "json": {"message": {"data": encode_notification("history-1")}},
        "headers": headers(),
    }
    assert client.post("/api/integrations/gmail/pubsub/1", **request).json()["created"] == 1
    assert client.post("/api/integrations/gmail/pubsub/1", **request).json()["created"] == 0


def test_gmail_pubsub_rejects_invalid_token_and_unconnected_account(gmail_client):
    client, _ = gmail_client
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


def test_gmail_pubsub_rejects_invalid_payload(gmail_client):
    client, _ = gmail_client
    response = client.post(
        "/api/integrations/gmail/pubsub/1",
        json={"message": {"data": base64.b64encode(b"{}").decode()}},
        headers=headers(),
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "Gmail historyId is required"


def test_gmail_pubsub_requires_push_auth_configuration(monkeypatch, gmail_client):
    client, _ = gmail_client
    monkeypatch.delenv("GMAIL_PUBSUB_PUSH_TOKEN")
    response = client.post(
        "/api/integrations/gmail/pubsub/1",
        json={"message": {"data": encode_notification("history-1")}},
        headers=headers(),
    )
    assert response.status_code == 503
    assert response.json()["detail"] == "gmail push authentication is not configured"


def test_gmail_pubsub_reports_unconfigured_real_client(monkeypatch, gmail_client):
    client, _ = gmail_client
    app.dependency_overrides.pop(get_gmail_client)
    response = client.post(
        "/api/integrations/gmail/pubsub/1",
        json={"message": {"data": encode_notification("history-1")}},
        headers=headers(),
    )
    assert response.status_code == 503
    assert response.json()["detail"] == "gmail provider is not configured"
