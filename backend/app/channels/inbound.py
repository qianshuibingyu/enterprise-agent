from dataclasses import dataclass
from typing import Any, Mapping, Protocol

from sqlalchemy.orm import Session

from app.message_ingestion import IngestResult, ingest_provider_message


class ProviderRateLimited(RuntimeError):
    pass


class ProviderTemporaryFailure(RuntimeError):
    pass


class InvalidProviderAuthorization(RuntimeError):
    pass


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
        raise InvalidProviderAuthorization("invalid Gmail push authorization")

    events = client.list_history(account_id=account_id, history_id=history_id)
    results: list[IngestResult] = []
    cursor: str | None = None
    for event in events:
        message_id = event.get("message_id")
        if not isinstance(message_id, str) or not message_id:
            continue
        event_cursor = event.get("history_id")
        if event_cursor is not None:
            cursor = str(event_cursor)
        normalized = client.fetch_message(account_id=account_id, message_id=message_id)
        results.append(
            ingest_provider_message(
                db,
                channel_account_id=account_id,
                # Gmail API/Pub/Sub history is the canonical production path.
                provider="gmail_api_pubsub",
                message=normalized,
            )
        )

    db.commit()
    return InboundBatchResult(results=results, cursor=cursor)
