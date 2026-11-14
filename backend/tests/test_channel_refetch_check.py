"""Live-refetch chain diagnostics: verify each failure class is actionable."""

import socket
import ssl

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import business_routes
from app.auth import hash_password
from app.database import get_db
from app.gmail_credentials import GmailCredentialError
from app.main import app
from app.models.base import Base
from app.models.business import ChannelAccount, ChannelGrant
from app.models.user import User
from app.provider_transport import classify_network_failure


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
        owner = User(
            username="checker",
            password_hash=hash_password("checker1"),
            role="staff",
            department="inquiry",
            is_active=True,
            must_change_password=False,
        )
        other = User(
            username="other",
            password_hash=hash_password("other1"),
            role="staff",
            department="inquiry",
            is_active=True,
            must_change_password=False,
        )
        db.add_all([owner, other])
        db.flush()
        gmail = ChannelAccount(owner_user_id=owner.id, channel_type="gmail", status="connected")
        gmail_with_credential = ChannelAccount(
            owner_user_id=owner.id,
            channel_type="gmail",
            status="connected",
            gmail_credential_ciphertext="fixture-ciphertext",
        )
        foreign = ChannelAccount(owner_user_id=other.id, channel_type="gmail", status="connected")
        db.add_all([gmail, gmail_with_credential, foreign])
        db.flush()
        db.add_all([
            ChannelGrant(channel_account_id=gmail.id, channel_type="gmail", owner_user_id=owner.id),
            ChannelGrant(channel_account_id=gmail_with_credential.id, channel_type="gmail", owner_user_id=owner.id),
            ChannelGrant(channel_account_id=foreign.id, channel_type="gmail", owner_user_id=other.id),
        ])
        db.commit()

    def override_db():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    with TestClient(app, base_url="https://testserver", raise_server_exceptions=False) as http:
        yield http
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)
    engine.dispose()


def login(http):
    csrf = http.get("/auth/csrf", headers={"Origin": "https://testserver"}).json()["csrf_token"]
    assert http.post(
        "/auth/login",
        json={"username": "checker", "password": "checker1"},
        headers={"Origin": "https://testserver", "X-CSRF-Token": csrf},
    ).status_code == 200


def test_missing_credential_is_actionable(client):
    http = client
    login(http)
    body = http.get("/api/channel-accounts/1/refetch-check").json()
    assert body["ready"] is False
    assert body["failure_kind"] == "credentials_missing"
    assert body["severity"] == "action_required"
    assert "重新授权" in body["recommended_action"]
    assert any(not step["ok"] for step in body["steps"])


def test_undecryptable_credential_is_actionable(client, monkeypatch):
    http = client
    login(http)

    def fail(ciphertext):
        raise GmailCredentialError("cannot decrypt")

    monkeypatch.setattr(business_routes, "decrypt_refresh_token", fail)
    body = http.get("/api/channel-accounts/2/refetch-check").json()
    assert body["ready"] is False
    assert body["failure_kind"] == "credential_decrypt_failed"
    assert "加密密钥" in body["recommended_action"]


def test_healthy_gmail_chain_is_ready(client, monkeypatch):
    http = client
    login(http)
    monkeypatch.setattr(business_routes, "decrypt_refresh_token", lambda value: "refresh")

    class FakeGmailClient:
        def __init__(self, *, refresh_token):
            assert refresh_token == "refresh"

        def _get(self, path, params=None):
            assert path == "profile"
            return {"emailAddress": "fixture@example.com"}

    monkeypatch.setattr(business_routes, "GmailApiClient", FakeGmailClient)
    body = http.get("/api/channel-accounts/2/refetch-check").json()
    assert body["ready"] is True
    assert body["failure_kind"] is None
    assert all(step["ok"] for step in body["steps"])


def test_check_rejects_accounts_outside_scope(client):
    http = client
    login(http)
    assert http.get("/api/channel-accounts/3/refetch-check").status_code == 404


def test_blocked_egress_reports_host_and_transport_reason(client, monkeypatch):
    """A firewalled provider must be diagnosable, not a generic failure."""
    http = client
    login(http)
    monkeypatch.setattr(business_routes, "decrypt_refresh_token", lambda value: "refresh")

    request = httpx.Request("GET", "https://gmail.googleapis.com/gmail/v1/users/me/profile")

    class UnreachableGmailClient:
        def __init__(self, *, refresh_token):
            del refresh_token

        def _get(self, path, params=None):
            del path, params
            raise httpx.ConnectTimeout("timed out", request=request)

    monkeypatch.setattr(business_routes, "GmailApiClient", UnreachableGmailClient)
    body = http.get("/api/channel-accounts/2/refetch-check").json()

    assert body["ready"] is False
    assert body["failure_kind"] == "network_unavailable"
    assert body["severity"] == "action_required"
    assert body["network"]["kind"] == "timeout"
    assert body["network"]["host"] == "gmail.googleapis.com"
    assert body["error_class"] == "ConnectTimeout"
    assert "PROVIDER_HTTPS_PROXY" in body["recommended_action"]
    failed = [step for step in body["steps"] if not step["ok"]]
    assert failed and "gmail.googleapis.com" in failed[-1]["detail"]


def test_dns_failure_is_classified_separately():
    cause = socket.gaierror(-2, "Name or service not known")
    error = httpx.ConnectError(
        "getaddrinfo failed",
        request=httpx.Request("POST", "https://login.microsoftonline.com/common/oauth2/v2.0/token"),
    )
    error.__cause__ = cause
    detail = classify_network_failure(error)
    assert detail["kind"] == "dns"
    assert detail["host"] == "login.microsoftonline.com"
    assert "DNS" in detail["hint"]


def test_proxy_and_tls_failures_are_classified():
    proxy = httpx.ProxyError(
        "proxy refused",
        request=httpx.Request("GET", "https://graph.microsoft.com/v1.0/me"),
    )
    assert classify_network_failure(proxy)["kind"] == "proxy"
    tls = ssl.SSLError("certificate verify failed")
    assert classify_network_failure(tls)["kind"] == "tls"
