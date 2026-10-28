from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.message_ingestion import (
    AttachmentInput,
    InboundMessageInput,
    ingest_message,
    ingest_provider_batch,
    ingest_provider_message,
    map_provider_message,
)
from app.models.base import Base
from app.models.business import ChannelAccount, ChannelGrant, Message
from app.models.user import User
from app.channels.providers import FakeTestProvider
from app.channels.registry import provider_descriptor


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
        db.add_all(
            [
                User(username="one", password_hash="hash-one", role="staff", is_active=True, must_change_password=False),
                User(username="two", password_hash="hash-two", role="staff", is_active=True, must_change_password=False),
            ]
        )
        db.flush()
        first = ChannelAccount(owner_user_id=1, channel_type="gmail", status="connected")
        second = ChannelAccount(owner_user_id=2, channel_type="gmail", status="connected")
        db.add_all([first, second])
        db.flush()
        db.add_all(
            [
                ChannelGrant(channel_account_id=first.id, channel_type="gmail", owner_user_id=1),
                ChannelGrant(channel_account_id=second.id, channel_type="gmail", owner_user_id=2),
            ]
        )
        db.commit()
        yield db
    Base.metadata.drop_all(engine)
    engine.dispose()


def payload(account_id: int, *, provider="gmail_api_pubsub", external_id="provider-message-1", content="hello"):
    return InboundMessageInput(
        channel_account_id=account_id,
        provider=provider,
        external_message_id=external_id,
        direction="inbound",
        status="received",
        occurred_at=datetime(2026, 10, 22, tzinfo=timezone.utc),
        raw_content=content,
        attachments=(
            AttachmentInput(
                original_filename="quote.pdf",
                media_type="application/pdf",
                size_bytes=42,
                storage_reference="vault://message/attachment-1",
            ),
        ),
    )


def test_provider_mapping_and_ingestion_persist_normalized_message(db_session):
    normalized = map_provider_message(
        channel_account_id=1,
        provider="gmail_api_pubsub",
        message={
            "external_message_id": "gmail-1",
            "direction": "inbound",
            "status": "received",
            "occurred_at": datetime(2026, 10, 22, tzinfo=timezone.utc),
            "raw_content": "mapped content",
            "attachments": [
                {
                    "original_filename": "quote.pdf",
                    "media_type": "application/pdf",
                    "size_bytes": 42,
                    "storage_reference": "vault://message/mapped-1",
                }
            ],
        },
    )
    assert normalized.external_message_id == "gmail-1"
    result = ingest_provider_message(
        db_session,
        channel_account_id=1,
        provider="gmail_api_pubsub",
        message={
            "external_message_id": "gmail-1",
            "direction": "inbound",
            "status": "received",
            "occurred_at": datetime(2026, 10, 22, tzinfo=timezone.utc),
            "raw_content": "mapped content",
            "attachments": [
                {
                    "original_filename": "quote.pdf",
                    "media_type": "application/pdf",
                    "size_bytes": 42,
                    "storage_reference": "vault://message/mapped-1",
                }
            ],
        },
    )
    db_session.commit()

    assert result.created is True
    assert result.message.raw_content == "mapped content"
    assert result.message.attachments[0].media_type == "application/pdf"


def test_first_write_persists_normalized_message_and_attachment(db_session):
    result = ingest_message(db_session, payload(1))
    db_session.commit()

    assert result.created is True
    assert result.message.id is not None
    assert result.message.external_message_id == "provider-message-1"
    assert result.message.attachments[0].storage_reference == "vault://message/attachment-1"
    assert db_session.query(Message).count() == 1


def test_duplicate_delivery_is_idempotent_and_does_not_overwrite_content(db_session):
    first = ingest_message(db_session, payload(1, content="original"))
    db_session.commit()

    duplicate = ingest_message(db_session, payload(1, content="replayed-content"))
    db_session.commit()

    assert duplicate.created is False
    assert duplicate.message.id == first.message.id
    assert duplicate.message.raw_content == "original"
    assert len(duplicate.message.attachments) == 1
    assert db_session.query(Message).count() == 1


def test_existing_database_conflict_is_returned_without_mutating_record(db_session):
    existing = Message(
        channel_account_id=1,
        provider="gmail_api_pubsub",
        external_message_id="provider-message-2",
        direction="inbound",
        status="processed",
        occurred_at=datetime(2026, 10, 22, tzinfo=timezone.utc),
        raw_content="stored-before-retry",
    )
    db_session.add(existing)
    db_session.commit()

    result = ingest_message(db_session, payload(1, external_id="provider-message-2", content="retry"))
    assert result.created is False
    assert result.message.id == existing.id
    assert result.message.status == "processed"
    assert result.message.raw_content == "stored-before-retry"


def test_same_external_id_isolated_by_account_and_provider(db_session):
    first = ingest_message(db_session, payload(1))
    second_account = ingest_message(db_session, payload(2))
    second_provider = ingest_message(db_session, payload(1, provider="outlook_imap"))
    db_session.commit()

    assert first.created and second_account.created and second_provider.created
    assert db_session.query(Message).count() == 3


def test_missing_attachment_metadata_is_rejected_before_database_write(db_session):
    with pytest.raises(ValueError, match="attachment 0 missing metadata"):
        ingest_provider_message(
            db_session,
            channel_account_id=1,
            provider="gmail_api_pubsub",
            message={
                "external_message_id": "missing-attachment-data",
                "direction": "inbound",
                "status": "received",
                "occurred_at": datetime(2026, 10, 22, tzinfo=timezone.utc),
                "raw_content": "body",
                "attachments": [{"media_type": "image/png"}],
            },
        )
    assert db_session.query(Message).count() == 0


def test_fake_provider_batch_uses_common_ingest_path_and_database_idempotency(db_session):
    fake = FakeTestProvider("gmail", provider_descriptor("gmail").capabilities, messages=[
        {
            "external_message_id": "fake-1",
            "direction": "inbound",
            "status": "received",
            "occurred_at": datetime(2026, 10, 22, tzinfo=timezone.utc),
            "raw_content": "fake body",
        },
        {
            "external_message_id": "fake-1",
            "direction": "inbound",
            "status": "received",
            "occurred_at": datetime(2026, 10, 22, tzinfo=timezone.utc),
            "raw_content": "duplicate fake body",
        },
    ])
    results = ingest_provider_batch(
        db_session,
        channel_account_id=1,
        provider=fake,
        external_account_id="fake-account",
    )

    assert [result.created for result in results] == [True, False]
    assert db_session.query(Message).count() == 1
    assert db_session.query(Message).one().raw_content == "fake body"


def test_provider_mapping_without_attachments_is_valid(db_session):
    result = ingest_provider_message(
        db_session,
        channel_account_id=1,
        provider="outlook_imap",
        message={
            "external_message_id": "no-attachments",
            "direction": "inbound",
            "status": "received",
            "occurred_at": datetime(2026, 10, 22, tzinfo=timezone.utc),
            "raw_content": "plain body",
        },
    )
    db_session.commit()
    assert result.created is True
    assert result.message.attachments == []


def test_invalid_direction_or_status_fails_before_database_write(db_session):
    invalid = payload(1)
    with pytest.raises(ValueError, match="unsupported message direction"):
        ingest_message(
            db_session,
            InboundMessageInput(
                channel_account_id=invalid.channel_account_id,
                provider=invalid.provider,
                external_message_id=invalid.external_message_id,
                direction="sideways",
                status=invalid.status,
                occurred_at=invalid.occurred_at,
                raw_content=invalid.raw_content,
            ),
        )
    assert db_session.query(Message).count() == 0
