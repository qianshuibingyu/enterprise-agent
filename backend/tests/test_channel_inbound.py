from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.base import Base
from app.models.business import ChannelAccount, ChannelGrant
from app.models.user import User

from app.channels.inbound import (
    InvalidProviderAuthorization,
    ProviderRateLimited,
    ProviderTemporaryFailure,
    ingest_gmail_history,
    ingest_outlook_unread,
    ingest_whatsapp_messages,
    is_confirmed_fetch_slot,
)


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session = sessionmaker(bind=engine, expire_on_commit=False)
    Base.metadata.create_all(engine)
    with testing_session() as db:
        db.add_all([
            User(username="one", password_hash="hash-one", role="staff", is_active=True, must_change_password=False),
            User(username="two", password_hash="hash-two", role="staff", is_active=True, must_change_password=False),
        ])
        db.flush()
        first = ChannelAccount(owner_user_id=1, channel_type="gmail", status="connected")
        second = ChannelAccount(owner_user_id=2, channel_type="gmail", status="connected")
        db.add_all([first, second])
        db.flush()
        db.add_all([
            ChannelGrant(channel_account_id=first.id, channel_type="gmail", owner_user_id=1),
            ChannelGrant(channel_account_id=second.id, channel_type="gmail", owner_user_id=2),
        ])
        db.commit()
        yield db
    Base.metadata.drop_all(engine)
    engine.dispose()


class FakeGmailClient:
    def __init__(self, events, messages):
        self.events = events
        self.messages = messages

    def list_history(self, *, account_id, history_id):
        return self.events

    def fetch_message(self, *, account_id, message_id):
        return self.messages[message_id]


class FakeOutlookClient:
    def __init__(self, messages):
        self.messages = messages

    def fetch_unread(self, *, account_id):
        return self.messages


class FakeWhatsAppClient:
    def __init__(self, authorized, messages):
        self.authorized = authorized
        self.messages = messages

    def check_authorized(self, *, account_id):
        return self.authorized

    def receive(self, *, account_id):
        return self.messages


def normalized(external_id, content="body"):
    return {
        "external_message_id": external_id,
        "direction": "inbound",
        "status": "received",
        "occurred_at": datetime(2026, 10, 22, tzinfo=timezone.utc),
        "raw_content": content,
    }


def test_gmail_history_fetches_details_and_is_idempotent(db_session):
    client = FakeGmailClient(
        events=[{"history_id": "h2", "message_id": "gmail-1"}],
        messages={"gmail-1": normalized("gmail-1", "mail body")},
    )
    first = ingest_gmail_history(
        db_session,
        account_id=1,
        history_id="h1",
        client=client,
        push_token="push-secret",
        expected_push_token="push-secret",
    )
    second = ingest_gmail_history(
        db_session,
        account_id=1,
        history_id="h1",
        client=client,
        push_token="push-secret",
        expected_push_token="push-secret",
    )
    assert first.cursor == "h2"
    assert [item.created for item in first.results] == [True]
    assert [item.created for item in second.results] == [False]


def test_gmail_invalid_push_authorization_is_rejected(db_session):
    with pytest.raises(InvalidProviderAuthorization):
        ingest_gmail_history(
            db_session,
            account_id=1,
            history_id="h1",
            client=FakeGmailClient([], {}),
            push_token="wrong",
            expected_push_token="push-secret",
        )


def test_outlook_unread_uses_imap_normalized_messages(db_session):
    result = ingest_outlook_unread(
        db_session,
        account_id=1,
        client=FakeOutlookClient([normalized("outlook-1")]),
    )
    assert [item.created for item in result.results] == [True]
    assert result.results[0].message.provider == "outlook_imap"


def test_whatsapp_requires_authorized_internal_adapter(db_session):
    with pytest.raises(InvalidProviderAuthorization):
        ingest_whatsapp_messages(
            db_session,
            account_id=1,
            client=FakeWhatsAppClient(False, [normalized("wa-1")]),
        )

    result = ingest_whatsapp_messages(
        db_session,
        account_id=1,
        client=FakeWhatsAppClient(True, [normalized("wa-1")]),
    )
    assert [item.created for item in result.results] == [True]
    assert result.results[0].message.provider == "whatsapp_web_baileys"


def test_provider_temporary_failure_and_rate_limit_are_not_hidden(db_session):
    class RateLimitedClient:
        def list_history(self, *, account_id, history_id):
            raise ProviderRateLimited("provider rate limit")

        def fetch_message(self, *, account_id, message_id):
            raise AssertionError("must not fetch after rate limit")

    class TemporaryFailureClient:
        def fetch_unread(self, *, account_id):
            raise ProviderTemporaryFailure("temporary provider failure")

    with pytest.raises(ProviderRateLimited, match="provider rate limit"):
        ingest_gmail_history(
            db_session,
            account_id=1,
            history_id="h1",
            client=RateLimitedClient(),
            push_token="push-secret",
            expected_push_token="push-secret",
        )
    with pytest.raises(ProviderTemporaryFailure, match="temporary provider failure"):
        ingest_outlook_unread(
            db_session,
            account_id=1,
            client=TemporaryFailureClient(),
        )


def test_confirmed_utc8_fetch_slots_and_injected_holiday_rule():
    not_holiday = lambda day: False
    assert is_confirmed_fetch_slot(
        datetime(2026, 10, 22, 0, 0, tzinfo=timezone.utc),
        is_holiday=not_holiday,
    )
    assert not is_confirmed_fetch_slot(
        datetime(2026, 10, 22, 1, 0, tzinfo=timezone.utc),
        is_holiday=not_holiday,
    )
    assert not is_confirmed_fetch_slot(
        datetime(2026, 10, 25, 0, 0, tzinfo=timezone.utc),
        is_holiday=not_holiday,
    )
    assert not is_confirmed_fetch_slot(
        datetime(2026, 10, 22, 0, 0, tzinfo=timezone.utc),
        is_holiday=lambda day: True,
    )
