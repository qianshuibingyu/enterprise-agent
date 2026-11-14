from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import hash_password
from app.database import get_db
from app.main import app
from app.models.base import Base
from app.models.business import ChannelAccount, ChannelGrant
from app.models.user import User


@pytest.fixture
def external_client(monkeypatch):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    Base.metadata.create_all(engine)
    with session_factory() as db:
        db.add(User(
            username="operator",
            password_hash=hash_password("operator1"),
            role="staff",
            department="inquiry",
            is_active=True,
            must_change_password=False,
        ))
        db.flush()
        account = ChannelAccount(
            owner_user_id=1,
            channel_type="gmail",
            external_account_id="gog-account-fixture",
            status="connected",
        )
        db.add(account)
        db.flush()
        db.add(ChannelGrant(
            channel_account_id=account.id,
            channel_type="gmail",
            owner_user_id=1,
        ))
        db.commit()

    def override_db():
        with session_factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    monkeypatch.setenv("GMAIL_PUBSUB_PUSH_TOKEN", "fixture-push-token")
    with TestClient(app, base_url="https://testserver") as client:
        yield client
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)
    engine.dispose()


def login(client):
    csrf = client.get("/auth/csrf", headers={"Origin": "https://testserver"})
    response = client.post(
        "/auth/login",
        json={"username": "operator", "password": "operator1"},
        headers={"Origin": "https://testserver", "X-CSRF-Token": csrf.json()["csrf_token"]},
    )
    assert response.status_code == 200


def event(external_account_id="gog-account-fixture"):
    return {
        "external_account_id": external_account_id,
        "external_message_id": "gateway-message-1",
        "direction": "inbound",
        "status": "received",
        "occurred_at": datetime(2026, 10, 27, tzinfo=timezone.utc).isoformat(),
        "raw_content": "fixture gateway message",
        "attachments": [],
    }


def test_external_ingress_requires_configured_source_token(external_client):
    response = external_client.post(
        "/api/integrations/gmail/ingress/1",
        json=event(),
    )
    assert response.status_code == 403


def test_external_ingress_normalizes_canonical_provider_and_is_idempotent(external_client):
    headers = {"X-External-Ingress-Token": "fixture-push-token"}

    first = external_client.post(
        "/api/integrations/gmail/ingress/1", json=event(), headers=headers
    )
    duplicate = external_client.post(
        "/api/integrations/gmail/ingress/1", json=event(), headers=headers
    )

    assert first.status_code == 202
    assert first.json()["provider"] == "gmail_api_pubsub"
    assert first.json()["created"] is True
    assert duplicate.status_code == 202
    assert duplicate.json()["created"] is False


def test_external_ingress_rejects_wrong_external_account_mapping(external_client):
    headers = {"X-External-Ingress-Token": "fixture-push-token"}

    response = external_client.post(
        "/api/integrations/gmail/ingress/1",
        json=event("different-external-account"),
        headers=headers,
    )

    assert response.status_code == 404


def test_external_ingress_rejects_unknown_channel_or_account(external_client):
    headers = {"X-External-Ingress-Token": "fixture-push-token"}

    unknown_channel = external_client.post(
        "/api/integrations/unknown/ingress/1", json=event(), headers=headers
    )
    unknown_account = external_client.post(
        "/api/integrations/gmail/ingress/999", json=event(), headers=headers
    )

    assert unknown_channel.status_code == 404
    assert unknown_account.status_code == 404
