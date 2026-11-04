from types import SimpleNamespace

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
from app.whatsapp_routes import get_whatsapp_adapter


class FakeAdapter:
    def __init__(self):
        self.state = "connected"
        self.fail = False

    def start_pairing(self, *, channel_account_id):
        if self.fail:
            raise RuntimeError("fixture adapter unavailable")
        return SimpleNamespace(qr="fixture-qr", expires_at="fixture-expiry")

    def status(self, *, channel_account_id):
        if self.fail:
            raise RuntimeError("fixture adapter unavailable")
        return SimpleNamespace(
            state=self.state,
            external_account_id="fixture-wa-id",
            detail=None,
            qr="",
            expires_at="",
        )

    def disconnect(self, *, channel_account_id):
        return SimpleNamespace(state="revoked", external_account_id="fixture-wa-id", detail=None)


@pytest.fixture
def whatsapp_owner_client(monkeypatch):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    Base.metadata.create_all(engine)
    with factory() as db:
        owner = User(
            username="wa-owner",
            password_hash=hash_password("ownerpass1"),
            role="staff",
            is_active=True,
            must_change_password=False,
        )
        db.add(owner)
        db.flush()
        account = ChannelAccount(
            owner_user_id=owner.id,
            channel_type="whatsapp",
            status="revoked",
            external_account_id="old-wa-id",
        )
        db.add(account)
        db.flush()
        db.add(ChannelGrant(
            channel_account_id=account.id,
            channel_type="whatsapp",
            owner_user_id=owner.id,
        ))
        db.commit()
        account_id = account.id

    fake = FakeAdapter()

    def override_db():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_whatsapp_adapter] = lambda: fake
    with TestClient(app, base_url="https://testserver") as client:
        csrf = client.get("/auth/csrf", headers={"Origin": "https://testserver"})
        login = client.post(
            "/auth/login",
            json={"username": "wa-owner", "password": "ownerpass1"},
            headers={"Origin": "https://testserver", "X-CSRF-Token": csrf.json()["csrf_token"]},
        )
        assert login.status_code == 200
        refreshed_csrf = client.get("/auth/csrf", headers={"Origin": "https://testserver"})
        assert refreshed_csrf.status_code == 200
        yield client, factory, account_id, fake, refreshed_csrf.json()["csrf_token"]
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)
    engine.dispose()


def test_owner_can_repair_revoked_account_and_transient_disconnect_does_not_revoke(whatsapp_owner_client):
    client, factory, account_id, fake, csrf_token = whatsapp_owner_client
    started = client.post(
        f"/api/integrations/whatsapp/accounts/{account_id}/pair/start",
        headers={"Origin": "https://testserver", "X-CSRF-Token": csrf_token},
    )
    assert started.status_code == 200
    assert started.json()["qr"] == "fixture-qr"

    status_response = client.get(f"/api/integrations/whatsapp/accounts/{account_id}/pair/status")
    assert status_response.status_code == 200
    assert status_response.json()["status"] == "connected_pending_inbound"

    fake.state = "disconnected"
    transient = client.get(f"/api/integrations/whatsapp/accounts/{account_id}/pair/status")
    assert transient.status_code == 200
    assert transient.json()["status"] == "connected_pending_inbound"
    with factory() as db:
        account = db.get(ChannelAccount, account_id)
        assert account.status == "connected_pending_inbound"
        assert account.external_account_id == "fixture-wa-id"


def test_pair_bridge_failure_is_returned_as_service_unavailable(whatsapp_owner_client):
    client, _, account_id, fake, csrf_token = whatsapp_owner_client
    fake.fail = True
    response = client.post(
        f"/api/integrations/whatsapp/accounts/{account_id}/pair/start",
        headers={"Origin": "https://testserver", "X-CSRF-Token": csrf_token},
    )
    assert response.status_code == 503
