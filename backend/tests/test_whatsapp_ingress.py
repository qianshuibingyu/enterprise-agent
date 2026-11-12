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
from app.models.business import ChannelAccount, ChannelGrant, Message
from app.models.user import User


@pytest.fixture
def whatsapp_client(monkeypatch):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    Base.metadata.create_all(engine)
    with factory() as db:
        user = User(
            username="whatsapp-owner",
            password_hash=hash_password("operator1"),
            role="staff",
            is_active=True,
            must_change_password=False,
        )
        db.add(user)
        db.flush()
        account = ChannelAccount(
            owner_user_id=user.id,
            channel_type="whatsapp",
            external_account_id="wa-account-fixture",
            status="connected_pending_inbound",
        )
        db.add(account)
        db.flush()
        db.add(ChannelGrant(
            channel_account_id=account.id,
            channel_type="whatsapp",
            owner_user_id=user.id,
        ))
        db.commit()
        account_id = account.id

    def override_db():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    monkeypatch.setenv("WHATSAPP_ADAPTER_TOKEN", "fixture-adapter-token")
    with TestClient(app, base_url="https://testserver") as client:
        yield client, factory, account_id
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)
    engine.dispose()


def event(external_message_id="wa-message-1", external_account_id="wa-account-fixture"):
    return {
        "external_account_id": external_account_id,
        "external_message_id": external_message_id,
        "direction": "inbound",
        "status": "received",
        "occurred_at": datetime(2026, 10, 31, tzinfo=timezone.utc).isoformat(),
        "raw_content": "fixture WhatsApp inbound message",
        "attachments": [],
    }


def test_whatsapp_inbound_requires_adapter_authentication(whatsapp_client):
    client, _, account_id = whatsapp_client
    response = client.post(
        f"/api/integrations/whatsapp/accounts/{account_id}/inbound",
        json=event(),
    )
    assert response.status_code == 403


def test_whatsapp_inbound_maps_and_is_idempotent(whatsapp_client):
    client, factory, account_id = whatsapp_client
    headers = {"X-WhatsApp-Adapter-Token": "fixture-adapter-token"}
    first = client.post(
        f"/api/integrations/whatsapp/accounts/{account_id}/inbound",
        json=event(),
        headers=headers,
    )
    duplicate = client.post(
        f"/api/integrations/whatsapp/accounts/{account_id}/inbound",
        json=event(),
        headers=headers,
    )
    assert first.status_code == 202
    assert first.json()["provider"] == "whatsapp_web_baileys"
    assert first.json()["created"] is True
    assert duplicate.status_code == 202
    assert duplicate.json()["created"] is False
    with factory() as db:
        assert db.query(Message).count() == 1
        account = db.get(ChannelAccount, account_id)
        assert account.status == "verified_inbound"


@pytest.mark.parametrize("external_account_id", ["wrong-account", ""])
def test_whatsapp_inbound_rejects_wrong_account_mapping(whatsapp_client, external_account_id):
    client, _, account_id = whatsapp_client
    response = client.post(
        f"/api/integrations/whatsapp/accounts/{account_id}/inbound",
        json=event(external_account_id=external_account_id),
        headers={"X-WhatsApp-Adapter-Token": "fixture-adapter-token"},
    )
    assert response.status_code in {404, 422}
