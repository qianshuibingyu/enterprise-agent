from datetime import datetime, timezone
from unittest.mock import Mock

import pytest
from sqlalchemy.exc import DBAPIError, IntegrityError, OperationalError

from app.channels.inbound import (
    DatabasePermanentFailure,
    DatabaseTemporaryFailure,
    MessageContractError,
    ProviderRateLimited,
    ProviderTemporaryFailure,
    SourceValidationFailure,
    classify_database_error,
    ingest_gmail_history,
)
from app.message_ingestion import InboundMessageInput, IngestResult, ingest_message
from app.models.user import User  # noqa: F401 - register the users table before mapper configuration


def test_inbound_failure_classes_expose_retry_policy_without_retrying():
    assert ProviderRateLimited("rate limited").category == "provider_rate_limited"
    assert ProviderRateLimited("rate limited").retryable is True
    assert ProviderTemporaryFailure("temporary").retryable is True
    assert SourceValidationFailure("invalid source").retryable is False


def test_source_validation_failure_does_not_call_provider():
    db = Mock()
    client = Mock()

    with pytest.raises(SourceValidationFailure) as raised:
        ingest_gmail_history(
            db,
            account_id=1,
            history_id="history-1",
            client=client,
            push_token="wrong",
            expected_push_token="expected",
        )

    assert raised.value.retryable is False
    client.list_history.assert_not_called()
    db.rollback.assert_not_called()


def test_provider_temporary_failure_is_propagated_without_retry():
    db = Mock()
    client = Mock()
    client.list_history.side_effect = ProviderTemporaryFailure("provider unavailable")

    with pytest.raises(ProviderTemporaryFailure) as raised:
        ingest_gmail_history(
            db,
            account_id=1,
            history_id="history-1",
            client=client,
            push_token="push",
            expected_push_token="push",
        )

    assert raised.value.retryable is True
    assert client.list_history.call_count == 1
    db.rollback.assert_called_once()


def test_rate_limit_is_propagated_without_retry():
    db = Mock()
    client = Mock()
    client.list_history.side_effect = ProviderRateLimited("provider rate limited")

    with pytest.raises(ProviderRateLimited) as raised:
        ingest_gmail_history(
            db,
            account_id=1,
            history_id="history-1",
            client=client,
            push_token="push",
            expected_push_token="push",
        )

    assert raised.value.retryable is True
    assert client.list_history.call_count == 1
    db.rollback.assert_called_once()


def test_provider_detail_failure_does_not_commit_or_advance_cursor():
    db = Mock()
    client = Mock()
    client.list_history.return_value = [{"history_id": "history-2", "message_id": "gmail-1"}]
    client.fetch_message.side_effect = ProviderTemporaryFailure("detail temporarily unavailable")

    with pytest.raises(ProviderTemporaryFailure):
        ingest_gmail_history(
            db,
            account_id=1,
            history_id="history-1",
            client=client,
            push_token="push",
            expected_push_token="push",
        )

    client.fetch_message.assert_called_once_with(account_id=1, message_id="gmail-1")
    db.commit.assert_not_called()
    db.rollback.assert_called_once()


def test_invalid_normalized_message_is_classified_without_commit():
    db = Mock()
    client = Mock()
    client.list_history.return_value = [{"message_id": "gmail-1"}]
    client.fetch_message.return_value = {"raw_content": "missing required fields"}

    with pytest.raises(MessageContractError) as raised:
        ingest_gmail_history(
            db,
            account_id=1,
            history_id="history-1",
            client=client,
            push_token="push",
            expected_push_token="push",
        )

    assert raised.value.category == "message_contract_invalid"
    assert raised.value.retryable is False
    assert isinstance(raised.value.__cause__, ValueError)
    db.commit.assert_not_called()
    db.rollback.assert_called_once()


def test_mapping_failure_does_not_commit_or_advance_cursor(monkeypatch):
    db = Mock()
    client = Mock()
    client.list_history.return_value = [{"history_id": "history-2", "message_id": "gmail-1"}]
    client.fetch_message.return_value = {"raw_content": "missing required fields"}

    with pytest.raises(MessageContractError, match="normalized inbound message contract") as raised:
        ingest_gmail_history(
            db,
            account_id=1,
            history_id="history-1",
            client=client,
            push_token="push",
            expected_push_token="push",
        )

    assert raised.value.retryable is False
    assert isinstance(raised.value.__cause__, ValueError)
    db.commit.assert_not_called()
    db.rollback.assert_called_once()


def test_database_error_classification_preserves_original_cause():
    temporary = OperationalError("SELECT 1", {}, RuntimeError("connection lost"))
    permanent = IntegrityError("INSERT", {}, RuntimeError("constraint failed"))

    temporary_failure = classify_database_error(temporary)
    permanent_failure = classify_database_error(permanent)

    assert isinstance(temporary_failure, DatabaseTemporaryFailure)
    assert temporary_failure.retryable is True
    assert temporary_failure.__cause__ is temporary
    assert isinstance(permanent_failure, DatabasePermanentFailure)
    assert permanent_failure.retryable is False
    assert permanent_failure.__cause__ is permanent


def test_non_unique_database_error_is_classified_as_temporary_failure():
    db = Mock()
    db.begin_nested.return_value = Mock()
    db.query.return_value.filter.return_value.one_or_none.return_value = None
    db.flush.side_effect = DBAPIError.instance(
        statement="INSERT INTO messages",
        params={},
        orig=RuntimeError("database unavailable"),
        dbapi_base_err=RuntimeError,
    )

    with pytest.raises(DBAPIError, match="database unavailable"):
        ingest_message(
            db,
            InboundMessageInput(
                channel_account_id=1,
                provider="gmail_api_pubsub",
                external_message_id="db-error",
                direction="inbound",
                status="received",
                occurred_at=datetime(2026, 10, 22, tzinfo=timezone.utc),
                raw_content="body",
            ),
        )
    db.begin_nested.return_value.rollback.assert_called_once()


def test_identity_integrity_conflict_returns_existing_message_without_mutation():
    existing = object()
    db = Mock()
    db.begin_nested.return_value = Mock()
    db.query.return_value.filter.return_value.one_or_none.side_effect = [None, existing]
    db.flush.side_effect = IntegrityError(
        "INSERT INTO messages",
        {},
        RuntimeError("uq_messages_account_provider_external_id"),
    )

    result = ingest_message(
        db,
        InboundMessageInput(
            channel_account_id=1,
            provider="gmail_api_pubsub",
            external_message_id="race",
            direction="inbound",
            status="received",
            occurred_at=datetime(2026, 10, 22, tzinfo=timezone.utc),
            raw_content="replayed",
        ),
    )

    assert result == IngestResult(message=existing, created=False)
    db.begin_nested.return_value.rollback.assert_called_once()


def test_flush_failure_rolls_back_session_and_preserves_original_error():
    db = Mock()
    db.begin_nested.return_value = Mock()
    db.query.return_value.filter.return_value.one_or_none.return_value = None
    db.flush.side_effect = RuntimeError("flush failed")

    with pytest.raises(RuntimeError, match="flush failed"):
        ingest_message(
            db,
            InboundMessageInput(
                channel_account_id=1,
                provider="gmail_api_pubsub",
                external_message_id="flush-error",
                direction="inbound",
                status="received",
                occurred_at=datetime(2026, 10, 22, tzinfo=timezone.utc),
                raw_content="body",
            ),
        )
    db.begin_nested.return_value.rollback.assert_called_once()


def test_gmail_batch_commit_failure_rolls_back_and_propagates(monkeypatch):
    db = Mock()
    client = Mock()
    client.list_history.return_value = [{"history_id": "history-2", "message_id": "gmail-1"}]
    client.fetch_message.return_value = {"external_message_id": "gmail-1"}
    result = IngestResult(message=object(), created=True)
    monkeypatch.setattr("app.channels.inbound.ingest_provider_message", lambda *args, **kwargs: result)
    db.commit.side_effect = RuntimeError("gmail batch commit failed")

    with pytest.raises(RuntimeError, match="gmail batch commit failed"):
        ingest_gmail_history(
            db,
            account_id=1,
            history_id="history-1",
            client=client,
            push_token="push-token",
            expected_push_token="push-token",
        )

    db.rollback.assert_called_once()


def test_non_identity_integrity_error_is_not_treated_as_duplicate():
    db = Mock()
    db.begin_nested.return_value = Mock()
    db.query.return_value.filter.return_value.one_or_none.return_value = None
    db.flush.side_effect = IntegrityError(
        "INSERT INTO messages",
        {},
        RuntimeError("ck_messages_status"),
    )

    with pytest.raises(IntegrityError, match="ck_messages_status"):
        ingest_message(
            db,
            InboundMessageInput(
                channel_account_id=1,
                provider="gmail_api_pubsub",
                external_message_id="check-error",
                direction="inbound",
                status="received",
                occurred_at=datetime(2026, 10, 22, tzinfo=timezone.utc),
                raw_content="body",
            ),
        )
    db.begin_nested.return_value.rollback.assert_called_once()
