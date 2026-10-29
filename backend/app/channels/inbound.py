from dataclasses import dataclass
from typing import Any, ClassVar, Mapping, Protocol

from sqlalchemy.exc import DBAPIError, DisconnectionError, IntegrityError, InterfaceError, OperationalError
from sqlalchemy.orm import Session

from app.message_ingestion import IngestResult, ingest_provider_message


class InboundFailure(RuntimeError):
    category: ClassVar[str] = "inbound_failure"
    retryable: ClassVar[bool] = False

    def __init__(self, message: str, *, cause: BaseException | None = None) -> None:
        super().__init__(message)
        if cause is not None:
            self.__cause__ = cause


class ProviderRateLimited(InboundFailure):
    category = "provider_rate_limited"
    retryable = True


class ProviderTemporaryFailure(InboundFailure):
    category = "provider_temporary_failure"
    retryable = True


class InvalidProviderAuthorization(InboundFailure):
    category = "authorization_invalid"
    retryable = False


class SourceValidationFailure(InboundFailure):
    category = "source_validation_failed"
    retryable = False


class MessageContractError(InboundFailure, ValueError):
    category = "message_contract_invalid"
    retryable = False


class ProviderPermanentFailure(InboundFailure):
    category = "provider_permanent_failure"
    retryable = False


class ProviderAuthorizationFailure(InboundFailure):
    category = "provider_authorization_failed"
    retryable = False


class DatabaseTemporaryFailure(InboundFailure):
    category = "database_temporary_failure"
    retryable = True


class DatabasePermanentFailure(InboundFailure):
    category = "database_permanent_failure"
    retryable = False


def classify_database_error(error: BaseException) -> InboundFailure:
    if isinstance(error, InboundFailure):
        return error
    if isinstance(error, IntegrityError):
        return DatabasePermanentFailure("inbound database constraint failed", cause=error)
    if isinstance(error, (OperationalError, InterfaceError, DisconnectionError)):
        return DatabaseTemporaryFailure("inbound database is temporarily unavailable", cause=error)
    if isinstance(error, DBAPIError) and error.connection_invalidated:
        return DatabaseTemporaryFailure("inbound database connection was invalidated", cause=error)
    return DatabasePermanentFailure("inbound database operation failed", cause=error)


class GmailHistoryClient(Protocol):
    def list_history(self, *, account_id: int, history_id: str) -> list[Mapping[str, Any]]:
        ...

    def fetch_message(self, *, account_id: int, message_id: str) -> Mapping[str, Any]:
        ...


@dataclass(frozen=True)
class InboundBatchResult:
    results: list[IngestResult]
    cursor: str | None


def ingest_gmail_history(
    db: Session,
    *,
    account_id: int,
    history_id: str,
    client: GmailHistoryClient,
    push_token: str,
    expected_push_token: str,
) -> InboundBatchResult:
    if not push_token or push_token != expected_push_token:
        raise SourceValidationFailure("invalid Gmail push authorization")

    try:
        events = client.list_history(account_id=account_id, history_id=history_id)
        results: list[IngestResult] = []
        cursor: str | None = None
        for event in events:
            message_id = event.get("message_id")
            if not isinstance(message_id, str) or not message_id:
                continue
            event_cursor = event.get("history_id")
            normalized = client.fetch_message(account_id=account_id, message_id=message_id)
            result = ingest_provider_message(
                db,
                channel_account_id=account_id,
                # Gmail API/Pub/Sub history is the canonical production path.
                provider="gmail_api_pubsub",
                message=normalized,
            )
            results.append(result)
            if event_cursor is not None:
                cursor = str(event_cursor)

        db.commit()
    except (ProviderRateLimited, ProviderTemporaryFailure):
        db.rollback()
        raise
    except (SourceValidationFailure, InvalidProviderAuthorization):
        db.rollback()
        raise
    except ValueError as exc:
        db.rollback()
        raise MessageContractError("normalized inbound message contract is invalid", cause=exc) from exc
    except (DBAPIError, IntegrityError) as exc:
        db.rollback()
        raise classify_database_error(exc) from exc
    except Exception:
        db.rollback()
        raise
    return InboundBatchResult(results=results, cursor=cursor)
