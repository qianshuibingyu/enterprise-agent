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
from app.channel_routes import create_gmail_account, revoke_channel
from app.provider_auth_routes import _oauth_states, gmail_authorize_callback
from app.gmail_oauth import GmailAuthorization
from fastapi import HTTPException
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
from app.models.permissions import UserChannelPreauthorization


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
            department="inquiry",
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


def _gmail_revoke_fixture(db, *, with_history: bool):
    owner = User(username="owner", password_hash="hash", role="staff", department="inquiry", is_active=True, must_change_password=False)
    db.add(owner)
    db.flush()
    account = ChannelAccount(owner_user_id=owner.id, channel_type="gmail", status="connected",
                             external_account_id="owner@example.com", gmail_credential_ciphertext="old-secret",
                             credential_reference="old", gmail_watch_history_id="old-cursor")
    db.add(account)
    db.flush()
    db.add(ChannelGrant(channel_account_id=account.id, channel_type="gmail", owner_user_id=owner.id))
    db.add(UserChannelPreauthorization(user_id=owner.id, channel_type="gmail", granted_by_user_id=owner.id))
    if with_history:
        db.add(Message(
            channel_account_id=account.id,
            provider="gmail_api_pubsub",
            external_message_id="gmail-history-1",
            direction="inbound",
            status="received",
            handling_status="pending",
            occurred_at=datetime(2026, 11, 1, tzinfo=timezone.utc),
            raw_content="collected before revoke",
            link_state="linked",
        ))
    db.commit()
    return owner, account


def test_gmail_revoke_of_empty_shell_is_fully_cleaned_up():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, expire_on_commit=False)() as db:
        owner, account = _gmail_revoke_fixture(db, with_history=False)
        account_id = account.id
        state = _oauth_states.issue(channel_account_id=account_id).value
        revoke_channel(account_id, (owner, None), db)
        assert _oauth_states.validate_any(state) is None
        assert account.gmail_credential_ciphertext is None
        assert account.credential_reference is None
        assert account.gmail_watch_history_id is None
        # No revoked zombie shell remains: reconnect creates a clean new record.
        assert db.get(ChannelAccount, account_id) is None
        assert db.scalars(select(ChannelGrant).where(ChannelGrant.channel_account_id == account_id)).all() == []
        fresh = create_gmail_account((owner, None), db)
        # SQLite can reuse the deleted row's id; the point is that the new
        # shell is clean (no credentials, no external mapping, no revoke flag).
        assert fresh["status"] == "not_ready"
        assert fresh["external_account_id"] is None
        assert db.get(ChannelAccount, fresh["id"]).history_access_revoked_at is None
    engine.dispose()


def test_gmail_revoke_archives_shell_with_collected_history():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, expire_on_commit=False)() as db:
        owner, account = _gmail_revoke_fixture(db, with_history=True)
        revoke_channel(account.id, (owner, None), db)
        # History is never destroyed: the shell is archived and reusing it is
        # refused until an administrator restores history access.
        with pytest.raises(HTTPException) as exc:
            create_gmail_account((owner, None), db)
        assert exc.value.status_code == 403
        assert "历史访问已撤销" in exc.value.detail
        assert account.status == "revoked"
        assert account.external_account_id == "owner@example.com"
        assert account.gmail_credential_ciphertext is None
    engine.dispose()


def test_gmail_reconnect_rejects_different_provider_identity(monkeypatch):
    monkeypatch.setenv("GMAIL_CREDENTIAL_ENCRYPTION_KEY", "configured")
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, expire_on_commit=False)() as db:
        owner = User(username="owner", password_hash="hash", role="staff", department="inquiry", is_active=True, must_change_password=False)
        db.add(owner)
        db.flush()
        account = ChannelAccount(owner_user_id=owner.id, channel_type="gmail", status="not_ready", external_account_id="original@example.com")
        db.add(account)
        db.flush()
        db.add(ChannelGrant(channel_account_id=account.id, channel_type="gmail", owner_user_id=owner.id))
        db.commit()
        state = _oauth_states.issue(channel_account_id=account.id).value

        class OtherAccountOAuth:
            def exchange_code(self, *, code, state):
                return GmailAuthorization("access", "fresh", "other@example.com")

        with pytest.raises(HTTPException) as exc:
            gmail_authorize_callback("code", state, owner, db, OtherAccountOAuth())
        assert exc.value.status_code == 409
        assert account.status == "not_ready"
        assert account.gmail_credential_ciphertext is None
    engine.dispose()


def test_gmail_callback_redacts_query_before_access_log():
    import asyncio
    from app.main import RedactGmailCallbackAccessLog

    scope = {"type": "http", "path": "/api/integrations/gmail/authorize/callback", "query_string": b"code=secret-code&state=secret-state"}
    seen = []

    async def inner(scope, receive, send):
        assert scope["query_string"] == b"code=secret-code&state=secret-state"
        await send({"type": "http.response.start", "status": 400, "headers": []})

    async def send(message):
        seen.append(scope["query_string"])

    asyncio.run(RedactGmailCallbackAccessLog(inner)(scope, None, send))
    assert seen == [b""]


def test_gmail_denied_callback_checks_scope_and_consumes_state(caplog):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, expire_on_commit=False)() as db:
        owner = User(username="owner", password_hash="hash", role="staff", department="inquiry", is_active=True, must_change_password=False)
        other = User(username="other", password_hash="hash", role="staff", department="inquiry", is_active=True, must_change_password=False)
        db.add_all([owner, other])
        db.flush()
        account = ChannelAccount(owner_user_id=owner.id, channel_type="gmail", status="not_ready")
        db.add(account)
        db.flush()
        db.add(ChannelGrant(channel_account_id=account.id, channel_type="gmail", owner_user_id=owner.id))
        db.commit()
        state = _oauth_states.issue(channel_account_id=account.id).value
        with pytest.raises(HTTPException) as exc:
            gmail_authorize_callback(None, state, other, db, object(), error="access_denied")
        assert exc.value.status_code == 403
        assert _oauth_states.validate_any(state) is not None
        with pytest.raises(HTTPException) as exc:
            gmail_authorize_callback(None, state, owner, db, object(), error="access_denied")
        assert exc.value.status_code == 400
        assert _oauth_states.validate_any(state) is None
        assert account.status == "not_ready"
        assert state not in caplog.text
    engine.dispose()


def test_gmail_reconnect_does_not_restore_missing_grant():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, expire_on_commit=False)() as db:
        owner = User(username="owner", password_hash="hash", role="staff", department="inquiry", is_active=True, must_change_password=False)
        db.add(owner)
        db.flush()
        account = ChannelAccount(owner_user_id=owner.id, channel_type="gmail", status="revoked", gmail_credential_ciphertext="old")
        db.add(account)
        db.commit()
        with pytest.raises(HTTPException) as exc:
            create_gmail_account((owner, None), db)
        assert exc.value.status_code == 403
        assert account.status == "revoked"
        assert db.query(ChannelGrant).count() == 0
    engine.dispose()


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
    response = client.post(
        "/api/integrations/gmail/pubsub/1",
        json={"message": {"data": encode_notification("history-1")}},
        headers=headers(),
    )

    assert response.status_code == 503
    assert response.headers["Retry-After"] == "60"
    assert fake.message_calls == []
    assert counts()["gmail_status"] == "connected_pending_inbound"


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
