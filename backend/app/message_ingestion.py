from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping, Protocol

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.business import Message, MessageAttachment

MESSAGE_IDENTITY_CONSTRAINT = "uq_messages_account_provider_external_id"


class ReceivingProvider(Protocol):
    name: str

    def receive(self, *, external_account_id: str) -> list[Mapping[str, Any]]:
        ...


@dataclass(frozen=True)
class AttachmentInput:
    original_filename: str
    media_type: str
    size_bytes: int
    storage_reference: str


@dataclass(frozen=True)
class InboundMessageInput:
    channel_account_id: int
    provider: str
    external_message_id: str
    direction: str
    status: str
    occurred_at: datetime
    raw_content: str
    attachments: tuple[AttachmentInput, ...] = ()


@dataclass(frozen=True)
class IngestResult:
    message: Message
    created: bool


def map_provider_message(
    *,
    channel_account_id: int,
    provider: str,
    message: Mapping[str, Any],
) -> InboundMessageInput:
    """Map an adapter-normalized message into the common ingest contract.

    Provider adapters own parsing provider payloads and ID semantics. This
    boundary only validates the fields shared by all providers. ``attachments``
    may be absent or empty; an attachment entry must have complete metadata.
    """
    required = (
        "external_message_id",
        "direction",
        "status",
        "occurred_at",
        "raw_content",
    )
    missing = [field for field in required if field not in message]
    if missing:
        raise ValueError(f"missing normalized message fields: {', '.join(missing)}")

    attachment_inputs: list[AttachmentInput] = []
    for index, attachment in enumerate(message.get("attachments") or ()):
        if not isinstance(attachment, Mapping):
            raise ValueError(f"attachment {index} metadata is invalid")
        attachment_fields = (
            "original_filename",
            "media_type",
            "size_bytes",
            "storage_reference",
        )
        missing_attachment = [field for field in attachment_fields if field not in attachment]
        if missing_attachment:
            raise ValueError(
                f"attachment {index} missing metadata: {', '.join(missing_attachment)}"
            )
        attachment_inputs.append(
            AttachmentInput(
                original_filename=str(attachment["original_filename"]),
                media_type=str(attachment["media_type"]),
                size_bytes=int(attachment["size_bytes"]),
                storage_reference=str(attachment["storage_reference"]),
            )
        )

    external_message_id = message["external_message_id"]
    if not isinstance(external_message_id, str) or not external_message_id.strip():
        raise ValueError("external_message_id must be a non-empty string")

    return InboundMessageInput(
        channel_account_id=channel_account_id,
        provider=provider,
        external_message_id=external_message_id,
        direction=str(message["direction"]),
        status=str(message["status"]),
        occurred_at=message["occurred_at"],
        raw_content=str(message["raw_content"]),
        attachments=tuple(attachment_inputs),
    )


def ingest_provider_message(
    db: Session,
    *,
    channel_account_id: int,
    provider: str,
    message: Mapping[str, Any],
) -> IngestResult:
    """Map one adapter-normalized message and persist it idempotently."""
    return ingest_message(
        db,
        map_provider_message(
            channel_account_id=channel_account_id,
            provider=provider,
            message=message,
        ),
    )


def ingest_provider_batch(
    db: Session,
    *,
    channel_account_id: int,
    provider: ReceivingProvider,
    external_account_id: str,
) -> list[IngestResult]:
    """Pull a provider batch and persist each normalized message.

    No in-process deduplication is used; every item goes through the database
    unique constraint and the same idempotent ingest service.
    """
    batch_savepoint = db.begin_nested()
    try:
        results = [
            ingest_provider_message(
                db,
                channel_account_id=channel_account_id,
                provider=provider.name,
                message=message,
            )
            for message in provider.receive(external_account_id=external_account_id)
        ]
        db.commit()
    except Exception:
        if batch_savepoint.is_active:
            batch_savepoint.rollback()
        db.rollback()
        raise
    return results


def ingest_message(db: Session, payload: InboundMessageInput) -> IngestResult:
    """Persist one provider-normalized message with database-backed idempotency.

    Provider-specific ID semantics stay in the adapter. The common scope is
    channel account + provider + opaque external message ID.
    """
    if payload.direction not in {"inbound", "outbound"}:
        raise ValueError("unsupported message direction")
    if payload.status not in {"received", "processed", "failed"}:
        raise ValueError("unsupported message status")

    existing = _find_existing(db, payload)
    if existing is not None:
        return IngestResult(message=existing, created=False)

    message = Message(
        channel_account_id=payload.channel_account_id,
        provider=payload.provider,
        external_message_id=payload.external_message_id,
        direction=payload.direction,
        status=payload.status,
        occurred_at=payload.occurred_at,
        raw_content=payload.raw_content,
        attachments=[
            MessageAttachment(
                original_filename=attachment.original_filename,
                media_type=attachment.media_type,
                size_bytes=attachment.size_bytes,
                storage_reference=attachment.storage_reference,
            )
            for attachment in payload.attachments
        ],
    )
    savepoint = db.begin_nested()
    db.add(message)
    try:
        db.flush()
    except IntegrityError as exc:
        savepoint.rollback()
        if not _is_identity_conflict(exc):
            raise
        existing = _find_existing(db, payload)
        if existing is None:
            raise
        return IngestResult(message=existing, created=False)
    except Exception:
        savepoint.rollback()
        raise
    else:
        savepoint.commit()
    return IngestResult(message=message, created=True)


def _is_identity_conflict(error: IntegrityError) -> bool:
    """Return whether the database reports the message identity unique key."""
    constraint_name = getattr(getattr(error, "orig", None), "diag", None)
    constraint_name = getattr(constraint_name, "constraint_name", None)
    if constraint_name == MESSAGE_IDENTITY_CONSTRAINT:
        return True
    error_text = str(error).lower()
    if MESSAGE_IDENTITY_CONSTRAINT in error_text:
        return True
    return (
        "unique constraint failed: messages.channel_account_id, messages.provider, "
        "messages.external_message_id"
    ) in error_text


def _find_existing(db: Session, payload: InboundMessageInput) -> Message | None:
    return (
        db.query(Message)
        .filter(
            Message.channel_account_id == payload.channel_account_id,
            Message.provider == payload.provider,
            Message.external_message_id == payload.external_message_id,
        )
        .one_or_none()
    )
