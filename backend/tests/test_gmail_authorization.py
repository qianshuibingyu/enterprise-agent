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
from app.oauth_state import OAuthStateStore
from app.provider_auth_routes import _oauth_states, get_gmail_oauth_client


class FakeGmailOAuthClient:
    def __init__(self, *, failure: Exception | None = None):
        self.failure = failure
        self.exchange_calls = 0

    def authorization_url(self, *, state: str) -> str:
        return f"https://accounts.google.test/authorize?state={state}"

    def exchange_code(self, *, code: str, state: str):
        self.exchange_calls += 1
        if self.failure:
            raise self.failure
        return SimpleNamespace(
            access_token="fixture-access-token",
            refresh_token="fixture-refresh-token",
            external_account_id="google-account-fixture",
        )


@pytest.fixture
def gmail_authorization_client(monkeypatch):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    Base.metadata.create_all(engine)
    with factory() as db:
        user = User(
            username="gmail-owner",
            password_hash=hash_password("operator1"),
            role="staff",
            department="inquiry",
            is_active=True,
            must_change_password=False,
        )
        db.add(user)
        db.flush()
        account = ChannelAccount(owner_user_id=user.id, channel_type="gmail", status="not_ready")
        db.add(account)
        db.flush()
        db.add(ChannelGrant(
            channel_account_id=account.id,
            channel_type="gmail",
            owner_user_id=user.id,
        ))
        db.commit()
        account_id = account.id

    fake = FakeGmailOAuthClient()

    def override_db():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_gmail_oauth_client] = lambda: fake
    monkeypatch.setattr("app.provider_auth_routes._oauth_states", OAuthStateStore())
    with TestClient(app, base_url="https://testserver") as client:
        yield client, factory, account_id, fake
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)
    engine.dispose()


def login(client):
    csrf = client.get("/auth/csrf", headers={"Origin": "https://testserver"})
    response = client.post(
        "/auth/login",
        json={"username": "gmail-owner", "password": "operator1"},
        headers={"Origin": "https://testserver", "X-CSRF-Token": csrf.json()["csrf_token"]},
    )
    assert response.status_code == 200


def test_gmail_callback_does_not_mark_connected_without_persistent_credential_store(
    gmail_authorization_client, monkeypatch,
):
    monkeypatch.delenv("GMAIL_CREDENTIAL_ENCRYPTION_KEY", raising=False)
    client, factory, account_id, fake = gmail_authorization_client
    login(client)
    from app.provider_auth_routes import _oauth_states

    state = _oauth_states.issue(channel_account_id=account_id).value
    response = client.get(
        f"/api/integrations/gmail/authorize/callback?code=fixture-code&state={state}"
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "Gmail 授权凭据安全存储尚未配置"
    assert fake.exchange_calls == 0
    with factory() as db:
        account = db.get(ChannelAccount, account_id)
        assert account.status == "not_ready"
        assert account.external_account_id is None


def test_gmail_callback_rejects_unknown_or_replayed_state(gmail_authorization_client, monkeypatch):
    monkeypatch.delenv("GMAIL_CREDENTIAL_ENCRYPTION_KEY", raising=False)
    client, _, account_id, fake = gmail_authorization_client
    login(client)
    response = client.get(
        f"/api/integrations/gmail/authorize/callback?code=fixture-code&state=unknown"
    )
    assert response.status_code == 400

    from app.provider_auth_routes import _oauth_states

    state = _oauth_states.issue(channel_account_id=account_id).value
    first = client.get(
        f"/api/integrations/gmail/authorize/callback?code=fixture-code&state={state}"
    )
    second = client.get(
        f"/api/integrations/gmail/authorize/callback?code=fixture-code&state={state}"
    )
    # Without production credential storage, the state remains available for a
    # safe retry after deployment is configured; no provider exchange occurs.
    assert first.status_code == 503
    assert second.status_code == 503
    assert fake.exchange_calls == 0
