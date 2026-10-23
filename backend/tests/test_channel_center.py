import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import hash_password
from app.channels.credentials import CredentialError, CredentialReferenceService
from app.database import get_db
from app.main import app
from app.models.base import Base
from app.models.business import ChannelAccount, ChannelGrant
from app.models.user import User


@pytest.fixture
def channel_client():
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
                User(
                    username="operator",
                    password_hash=hash_password("operator1"),
                    role="staff",
                    is_active=True,
                    must_change_password=False,
                ),
                User(
                    username="other",
                    password_hash=hash_password("otherpass1"),
                    role="staff",
                    is_active=True,
                    must_change_password=False,
                ),
            ]
        )
        db.flush()
        owned = ChannelAccount(owner_user_id=1, channel_type="gmail", status="not_connected")
        foreign = ChannelAccount(owner_user_id=2, channel_type="gmail", status="connected")
        db.add_all([owned, foreign])
        db.flush()
        db.add_all(
            [
                ChannelGrant(channel_account_id=owned.id, channel_type="gmail", owner_user_id=1),
                ChannelGrant(channel_account_id=foreign.id, channel_type="gmail", owner_user_id=2),
            ]
        )
        db.commit()

    def override_db():
        with testing_session() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
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


def csrf_headers(client):
    token = client.cookies.get("ea_csrf")
    return {"Origin": "https://testserver", "X-CSRF-Token": token}


def test_channel_catalog_requires_authentication(channel_client):
    assert channel_client.get("/api/channels").status_code == 401


def test_catalog_exposes_provider_contract_without_real_connection_claim(channel_client):
    login(channel_client)
    response = channel_client.get("/api/channels")
    assert response.status_code == 200
    channels = {item["channel_type"]: item for item in response.json()}
    assert set(channels) == {"gmail", "outlook", "whatsapp"}
    assert all(item["real_integration"] is False for item in channels.values())
    assert channels["gmail"]["provider"] == "gmail_api_pubsub"
    assert channels["outlook"]["integration_type"] == "mail_listener"
    assert channels["whatsapp"]["provider"] == "whatsapp_web_baileys"
    assert channels["whatsapp"]["capabilities"]["inbound"] is True


def test_account_listing_and_cross_user_authorization(channel_client):
    login(channel_client)
    accounts = channel_client.get("/api/channels/accounts")
    assert accounts.status_code == 200
    assert [account["owner_user_id"] for account in accounts.json()] == [1]
    denied = channel_client.post(
        "/api/channels/gmail/accounts/2/authorize?test_mode=true",
        headers=csrf_headers(channel_client),
    )
    assert denied.status_code == 403
    assert denied.json()["detail"] == "没有权限访问"


def test_fake_provider_success_error_state_and_revoke(channel_client):
    login(channel_client)
    started = channel_client.post(
        "/api/channels/gmail/accounts/1/authorize?test_mode=true",
        headers=csrf_headers(channel_client),
    )
    assert started.status_code == 200
    body = started.json()
    assert body["status"] == "authorizing"
    assert body["test_only"] is True

    callback = channel_client.get(body["authorization_url"])
    assert callback.status_code == 200
    assert callback.json() == {"status": "connected", "test_only": True, "error_code": None}
    assert channel_client.get("/api/channels/accounts").json()[0]["status"] == "connected"

    second = channel_client.post(
        "/api/channels/gmail/accounts/1/authorize?test_mode=true",
        headers=csrf_headers(channel_client),
    ).json()
    failed = channel_client.get(f'{second["authorization_url"]}&result=error')
    assert failed.status_code == 200
    assert failed.json()["status"] == "error"
    assert failed.json()["error_code"] == "fake_provider_error"

    revoked = channel_client.post(
        "/api/channels/gmail/accounts/1/revoke",
        headers=csrf_headers(channel_client),
    )
    assert revoked.status_code == 200
    assert revoked.json() == {"status": "revoked", "test_only": False}


def test_fake_callback_state_is_one_time(channel_client):
    login(channel_client)
    started = channel_client.post(
        "/api/channels/gmail/accounts/1/authorize?test_mode=true",
        headers=csrf_headers(channel_client),
    ).json()
    callback_url = started["authorization_url"]
    assert channel_client.get(callback_url).status_code == 200
    assert channel_client.get(callback_url).status_code == 403


def test_real_provider_path_is_blocked_without_external_call(channel_client):
    login(channel_client)
    response = channel_client.post(
        "/api/channels/gmail/accounts/1/authorize",
        headers=csrf_headers(channel_client),
    )
    assert response.status_code == 200
    assert response.json() == {
        "status": "blocked",
        "reason": "real_provider_not_configured",
        "test_only": False,
    }


def test_credential_service_rejects_plaintext_and_returns_non_secret_reference():
    service = CredentialReferenceService(secret="unit-test-secret")
    with pytest.raises(CredentialError, match="明文长期 token"):
        service.reference_for(token="long-lived-token")
    reference = service.reference_for(reference="vault://channel-account/1")
    assert reference.startswith("ref:")
    assert "vault" not in reference
    assert service.redacted("anything") == "[redacted]"
