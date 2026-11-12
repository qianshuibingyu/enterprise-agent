"""Regression for the Outlook "read Inbox" 500.

Graph returns receivedDateTime as an ISO string. The ingest contract declares
occurred_at as datetime but is a plain dataclass, so the string used to reach
the DateTime column unchanged and raised during flush (HTTP 500).
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
from app.models.business import ChannelAccount, ChannelGrant, Message
from app.models.user import User
from app.outlook_routes import _normalized_message, get_outlook_client
from app import outlook_routes


class FakeGraphClient:
    def list_emails(self, *, external_account_id, count=50):
        return [{
            "id": "AAMkAGI2AAA",
            "receivedDateTime": "2026-11-02T10:00:00Z",
            "body": {"content": "<p>hello from Graph</p>"},
            "from": {"emailAddress": {"address": "customer@example.com", "name": "Customer"}},
            "webLink": "https://outlook.office.com/owa/?ItemID=AAA",
        }]

    def message_web_link(self, message_id):
        return None


@pytest.fixture
def client():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        user = User(
            username="outlook-operator",
            password_hash=hash_password("operator1"),
            role="staff",
            is_active=True,
            must_change_password=False,
        )
        db.add(user)
        db.flush()
        account = ChannelAccount(
            owner_user_id=user.id,
            channel_type="outlook",
            status="connected",
            external_account_id="graph-user-id",
            outlook_credential_ciphertext="fixture-ciphertext",
        )
        db.add(account)
        db.flush()
        db.add(ChannelGrant(
            channel_account_id=account.id,
            channel_type="outlook",
            owner_user_id=user.id,
        ))
        db.commit()

    def override_db():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_outlook_client] = lambda: FakeGraphClient()
    with TestClient(app, base_url="https://testserver", raise_server_exceptions=False) as http:
        yield http, factory
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)
    engine.dispose()


def login(http):
    csrf = http.get("/auth/csrf", headers={"Origin": "https://testserver"}).json()["csrf_token"]
    response = http.post(
        "/auth/login",
        json={"username": "outlook-operator", "password": "operator1"},
        headers={"Origin": "https://testserver", "X-CSRF-Token": csrf},
    )
    assert response.status_code == 200


def test_graph_iso_string_timestamp_is_normalized():
    normalized = _normalized_message({
        "id": "AAMkAGI2AAA",
        "receivedDateTime": "2026-11-02T10:00:00Z",
        "body": {"content": "hello"},
    })
    # The mapping still carries the provider string; normalization happens at
    # the shared ingest boundary, not in the Outlook adapter.
    assert normalized["occurred_at"] == "2026-11-02T10:00:00Z"


def test_read_inbox_persists_graph_message_without_500(client, monkeypatch):
    http, factory = client
    monkeypatch.setattr(outlook_routes, "schedule_message_overview", lambda message_id: None)
    login(http)

    response = http.get("/api/integrations/outlook/accounts/1/messages")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == 1
    assert body["created"] == 1

    with factory() as db:
        stored = db.scalar(select(Message).where(Message.external_message_id == "AAMkAGI2AAA"))
        assert stored is not None
        assert isinstance(stored.occurred_at, datetime)
        # SQLite drops tzinfo on readback; PostgreSQL keeps it. Compare the
        # wall-clock value that both dialects agree on.
        assert stored.occurred_at.replace(tzinfo=None) == datetime(2026, 11, 2, 10, 0)
        assert "hello from Graph" in stored.raw_content


def test_graph_identity_matches_alternate_stable_fields():
    from app.outlook_graph import OutlookGraphClient

    identity = {"id": "guid-with-hyphens", "mail": "user@example.com", "userPrincipalName": "user@tenant"}
    assert OutlookGraphClient._identity_matches(identity, "GUID-WITH-HYPHENS")
    assert OutlookGraphClient._identity_matches(identity, "user@example.com")
    assert OutlookGraphClient._identity_matches(identity, "USER@TENANT")
    assert not OutlookGraphClient._identity_matches(identity, "someone-else")
    assert not OutlookGraphClient._identity_matches(identity, None)


def test_message_without_provider_id_is_skipped_not_persisted_as_none():
    normalized = _normalized_message({
        "receivedDateTime": "2026-11-02T10:00:00Z",
        "body": {"content": "orphan"},
    })
    assert normalized["external_message_id"] == ""
