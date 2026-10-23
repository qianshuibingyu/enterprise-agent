from dataclasses import dataclass
from datetime import datetime, time
from hmac import compare_digest
from typing import Any, Callable, Mapping, Protocol
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.message_ingestion import IngestResult, ingest_provider_message

UTC8 = ZoneInfo("Asia/Shanghai")


def _commit_or_rollback(db: Session) -> None:
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise


class InboundProviderError(RuntimeError):
    pass


class InvalidProviderAuthorization(InboundProviderError):
    pass


class ProviderRateLimited(InboundProviderError):
    pass


class ProviderTemporaryFailure(InboundProviderError):
    pass


class GmailHistoryClient(Protocol):
    def list_history(self, *, account_id: int, history_id: str) -> list[Mapping[str, Any]]:
        ...

    def fetch_message(self, *, account_id: int, message_id: str) -> Mapping[str, Any]:
        ...


class OutlookInboundClient(Protocol):
    def fetch_unread(self, *, account_id: int) -> list[Mapping[str, Any]]:
        ...


class WhatsAppInternalClient(Protocol):
    def check_authorized(self, *, account_id: int) -> bool:
        ...

    def receive(self, *, account_id: int) -> list[Mapping[str, Any]]:
        ...


@dataclass(frozen=True)
class InboundBatchResult:
    results: tuple[IngestResult, ...]
    cursor: str | None = None


def is_confirmed_fetch_slot(
    current: datetime,
    *,
    is_holiday: Callable[[object], bool],
) -> bool:
    """Apply the confirmed UTC+8 slots without choosing a holiday data source."""
    local = current.astimezone(UTC8)
    if local.weekday() == 6 or is_holiday(local.date()):
        return False
    return local.time().replace(second=0, microsecond=0) in {
        time(8, 0), time(9, 30), time(11, 0),
        time(14, 0), time(15, 30), time(17, 0),
    }


def ingest_gmail_history(
    db: Session,
    *,
    account_id: int,
    history_id: str,
    client: GmailHistoryClient,
    push_token: str,
    expected_push_token: str,
) -> InboundBatchResult:
    if not compare_digest(push_token, expected_push_token):
        raise InvalidProviderAuthorization("invalid Gmail Pub/Sub authorization")

    history = client.list_history(account_id=account_id, history_id=history_id)
    results: list[IngestResult] = []
    latest_history_id = history_id
    for event in history:
        event_history_id = str(event.get("history_id", history_id))
        latest_history_id = event_history_id
        message_id = event.get("message_id")
        if not message_id:
            raise ValueError("Gmail history event missing message_id")
        normalized = client.fetch_message(account_id=account_id, message_id=str(message_id))
        results.append(
            ingest_provider_message(
                db,
                channel_account_id=account_id,
                provider="gmail_api_pubsub",
                message=normalized,
            )
        )
    _commit_or_rollback(db)
    return InboundBatchResult(tuple(results), cursor=latest_history_id)


def ingest_outlook_unread(
    db: Session,
    *,
    account_id: int,
    client: OutlookInboundClient,
) -> InboundBatchResult:
    results = [
        ingest_provider_message(
            db,
            channel_account_id=account_id,
            provider="outlook_imap",
            message=message,
        )
        for message in client.fetch_unread(account_id=account_id)
    ]
    _commit_or_rollback(db)
    return InboundBatchResult(tuple(results))


def ingest_whatsapp_messages(
    db: Session,
    *,
    account_id: int,
    client: WhatsAppInternalClient,
) -> InboundBatchResult:
    if not client.check_authorized(account_id=account_id):
        raise InvalidProviderAuthorization("WhatsApp adapter account is not authorized")
    results = [
        ingest_provider_message(
            db,
            channel_account_id=account_id,
            provider="whatsapp_web_baileys",
            message=message,
        )
        for message in client.receive(account_id=account_id)
    ]
    _commit_or_rollback(db)
    return InboundBatchResult(tuple(results))
