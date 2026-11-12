from datetime import datetime, timezone
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import business_routes
from app.auth import hash_password
from app.database import get_db
from app.main import app
from app.models.base import Base
from app.models.business import ChannelAccount, ChannelGrant, Message
from app.models.user import User


@pytest.fixture
def content_client():
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        user = User(username="content-operator", password_hash=hash_password("operator1"), role="staff", is_active=True, must_change_password=False)
        db.add(user)
        db.flush()
        account = ChannelAccount(
            owner_user_id=user.id,
            channel_type="gmail",
            status="connected",
            gmail_credential_ciphertext="ciphertext-fixture",
        )
        whatsapp_account = ChannelAccount(owner_user_id=user.id, channel_type="whatsapp", status="connected")
        db.add_all([account, whatsapp_account])
        db.flush()
        db.add_all([
            ChannelGrant(channel_account_id=account.id, channel_type="gmail", owner_user_id=user.id),
            ChannelGrant(channel_account_id=whatsapp_account.id, channel_type="whatsapp", owner_user_id=user.id),
        ])
        db.add(Message(
            channel_account_id=account.id,
            provider="gmail_api_pubsub",
            external_message_id="gmail-content-1",
            direction="inbound",
            status="received",
            handling_status="pending",
            occurred_at=datetime(2026, 11, 9, tzinfo=timezone.utc),
            raw_content="cached safe fallback",
            customer_contact="content@example.com",
        ))
        db.add(Message(
            channel_account_id=whatsapp_account.id,
            provider="whatsapp_web_baileys",
            external_message_id="wa-content-1",
            direction="inbound",
            status="received",
            handling_status="pending",
            occurred_at=datetime(2026, 11, 9, tzinfo=timezone.utc),
            raw_content="cached WhatsApp fallback",
            customer_contact="+16502530000",
        ))
        db.commit()

    def override_db():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    with TestClient(app, base_url="https://testserver", raise_server_exceptions=False) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)
    engine.dispose()


def message(*, provider: str, raw_content: str, gmail_credential_ciphertext=None, outlook_credential_ciphertext=None):
    account = SimpleNamespace(
        id=7,
        channel_type="gmail" if provider.startswith("gmail") else "outlook",
        external_account_id="outlook-account",
        gmail_credential_ciphertext=gmail_credential_ciphertext,
        outlook_credential_ciphertext=outlook_credential_ciphertext,
    )
    return SimpleNamespace(
        channel_account=account,
        external_message_id="provider-message-1",
        provider=provider,
        raw_content=raw_content,
    )


def test_gmail_provider_content_is_sanitized_before_return(monkeypatch):
    class FakeGmailClient:
        def __init__(self, *, refresh_token):
            assert refresh_token == "fixture-refresh"

        def fetch_message(self, *, account_id, message_id):
            assert (account_id, message_id) == (7, "provider-message-1")
            return {"raw_content": "<p>fresh</p><script>drop</script>"}

    monkeypatch.setattr(business_routes, "GmailApiClient", FakeGmailClient)
    monkeypatch.setattr(business_routes, "decrypt_refresh_token", lambda value: "fixture-refresh")

    content, failure = business_routes._safe_provider_content(
        message(
            provider="gmail_api_pubsub",
            raw_content="cached",
            gmail_credential_ciphertext="ciphertext",
        )
    )

    assert failure is None
    assert content["display_text"] == "fresh"
    assert content["content_format"] == "text/plain"


def test_gmail_empty_provider_body_falls_back_to_cached_text(monkeypatch):
    class EmptyGmailClient:
        def __init__(self, *, refresh_token):
            pass

        def fetch_message(self, *, account_id, message_id):
            return {"raw_content": ""}

    monkeypatch.setattr(business_routes, "GmailApiClient", EmptyGmailClient)
    monkeypatch.setattr(business_routes, "decrypt_refresh_token", lambda value: "fixture-refresh")
    content, failure = business_routes._safe_provider_content(
        message(provider="gmail_api_pubsub", raw_content="cached fallback text", gmail_credential_ciphertext="ciphertext")
    )
    assert failure == "provider_content_empty"
    assert content["display_text"] == "cached fallback text"


def test_provider_message_without_loaded_account_falls_back_without_crashing():
    orphan = SimpleNamespace(provider="whatsapp_web_baileys", external_message_id="id", raw_content="cached WhatsApp")
    content, failure = business_routes._safe_provider_content(orphan)
    assert failure == "channel_account_unavailable"
    assert content["display_text"] == "cached WhatsApp"


def test_authorized_gmail_content_route_uses_cached_fallback_when_provider_returns_empty(monkeypatch, content_client):
    class EmptyGmailClient:
        def __init__(self, *, refresh_token):
            pass

        def fetch_message(self, *, account_id, message_id):
            return {"raw_content": ""}

    monkeypatch.setattr(business_routes, "GmailApiClient", EmptyGmailClient)
    monkeypatch.setattr(business_routes, "decrypt_refresh_token", lambda value: "fixture-refresh")
    csrf = content_client.get("/auth/csrf", headers={"Origin": "https://testserver"}).json()["csrf_token"]
    login = content_client.post(
        "/auth/login",
        json={"username": "content-operator", "password": "operator1"},
        headers={"Origin": "https://testserver", "X-CSRF-Token": csrf},
    )
    assert login.status_code == 200

    response = content_client.get("/api/messages/1/content")
    assert response.status_code == 200
    body = response.json()
    assert body["parsed_content"]["display_text"] == "cached safe fallback"
    assert body["preview_text"] == "cached safe fallback"
    assert body["full_text"] == "cached safe fallback"
    assert body["source"]["live_refetch"] is False
    assert body["source"]["fallback_reason"] == "provider_content_empty"
    assert body["source"]["kind"] == "cached_safe_text"
    assert body["raw_content_exposed"] is False


def test_gmail_alias_refetch_is_supported(monkeypatch):
    class FakeGmailClient:
        def __init__(self, *, refresh_token):
            pass

        def fetch_message(self, *, account_id, message_id):
            return {"raw_content": "<p>live Gmail body</p>"}

    monkeypatch.setattr(business_routes, "GmailApiClient", FakeGmailClient)
    monkeypatch.setattr(business_routes, "decrypt_refresh_token", lambda value: "fixture-refresh")
    # Provider alias normalization is covered directly at the safe-content layer
    # so the route fixture remains representative of canonical persisted rows.
    legacy = message(provider="gmail", raw_content="cached", gmail_credential_ciphertext="ciphertext")
    content, failure = business_routes._safe_provider_content(legacy)
    assert failure is None
    assert content["display_text"] == "live Gmail body"


def test_authorized_whatsapp_content_route_uses_cached_fallback_when_bridge_returns_empty(monkeypatch, content_client):
    class EmptyWhatsAppClient:
        def fetch_message(self, *, channel_account_id, message_id):
            return {"raw_content": ""}

    monkeypatch.setattr(business_routes, "HttpWhatsAppAdapterClient", EmptyWhatsAppClient)
    csrf = content_client.get("/auth/csrf", headers={"Origin": "https://testserver"}).json()["csrf_token"]
    login = content_client.post(
        "/auth/login",
        json={"username": "content-operator", "password": "operator1"},
        headers={"Origin": "https://testserver", "X-CSRF-Token": csrf},
    )
    assert login.status_code == 200

    response = content_client.get("/api/messages/2/content")
    assert response.status_code == 200
    body = response.json()
    assert body["parsed_content"]["display_text"] == "cached WhatsApp fallback"
    assert body["source"]["live_refetch"] is False
    assert body["source"]["fallback_reason"] == "provider_content_empty"
    assert body["source"]["kind"] == "cached_safe_text"
    assert body["raw_content_exposed"] is False


def test_whatsapp_provider_content_is_refetched_and_sanitized(monkeypatch):
    class FakeWhatsAppClient:
        def __init__(self):
            pass

        def fetch_message(self, *, channel_account_id, message_id):
            assert (channel_account_id, message_id) == (7, "provider-message-1")
            return {"raw_content": "<p>fresh WhatsApp</p><script>drop</script>"}

    monkeypatch.setattr(business_routes, "HttpWhatsAppAdapterClient", FakeWhatsAppClient)

    content, failure = business_routes._safe_provider_content(
        message(
            provider="whatsapp_web_baileys",
            raw_content="cached WhatsApp",
        )
    )

    assert failure is None
    assert content["display_text"] == "fresh WhatsApp"
    assert content["content_format"] == "text/plain"



def test_outlook_provider_failure_falls_back_to_cached_safe_text(monkeypatch):
    class FakeOutlookClient:
        def fetch_message(self, *, external_account_id, message_id):
            raise httpx.ConnectError("provider unavailable")

    monkeypatch.setattr(business_routes, "outlook_graph_client_for_ciphertext", lambda value: FakeOutlookClient())

    content, failure = business_routes._safe_provider_content(
        message(
            provider="outlook_mcp_graph",
            raw_content="<p>cached</p><iframe>drop</iframe>",
            outlook_credential_ciphertext="ciphertext",
        )
    )

    assert failure == "provider_refetch_failed"
    assert content["display_text"] == "cached"
    assert content["content_format"] == "text/plain"


def test_whatsapp_bridge_offline_replays_persisted_snapshot(monkeypatch):
    """An offline bridge must not degrade the original into an error state."""
    from app.whatsapp_adapter import WhatsAppAdapterUnavailableError

    class OfflineWhatsAppClient:
        def fetch_message(self, *, channel_account_id, message_id):
            raise WhatsAppAdapterUnavailableError("WhatsApp session is not connected")

    monkeypatch.setattr(business_routes, "HttpWhatsAppAdapterClient", OfflineWhatsAppClient)
    content, failure = business_routes._safe_provider_content(
        message(provider="whatsapp_web_baileys", raw_content="persisted WhatsApp original")
    )
    assert failure == "persisted_snapshot_replayed"
    assert content["display_text"] == "persisted WhatsApp original"
