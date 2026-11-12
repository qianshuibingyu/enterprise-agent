from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any, Mapping, Protocol

from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.contact_identity import normalize_email, normalize_whatsapp
from app.models.business import ChannelAccount, Inquiry, InquiryEvent, InquiryMessage, Message, MessageAttachment

MESSAGE_IDENTITY_CONSTRAINT = "uq_messages_account_provider_external_id"
WEBSITE_FORM_EMAIL = "lingorm1115@outlook.com"
# Processed inquiries may receive follow-up messages and can be reactivated;
# ignored inquiries are terminal for automatic identity matching.
RELINKABLE_INQUIRY_HANDLING_STATUSES = ("pending", "processed")


def website_form_sender_matches(customer_contact: str | None, original_sender: str | None = None) -> bool:
    """官网表单只认规定的固定白名单发件人。

    该邮箱是接收表单提交的通知邮箱，实际表单邮件常经由系统转发进入收件箱
    （带有原始发件人/外部标记），所以不要求「本人直发」——只要显示的 From
    地址精确等于白名单邮箱，即认定为官网表单。历史误标（发件人并非白名单邮箱）
    由 effective_website_form 在读取时复查剔除。
    """
    return normalize_email(customer_contact).normalized == WEBSITE_FORM_EMAIL


def effective_website_form(message: Message) -> bool:
    """读取历史数据时复查表单标记，避免旧数据/迁移造成的误标继续生效。

    判定标准与入库一致：is_website_form 标记为真，且显示的 From 确为白名单邮箱。
    """
    return bool(message.is_website_form) and website_form_sender_matches(message.customer_contact)


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
    customer_contact: str | None = None
    customer_nickname: str | None = None
    provider_web_link: str | None = None
    attachments: tuple[AttachmentInput, ...] = ()
    normalized_customer_contact: str | None = None
    contact_identity_state: str = "certain"
    contact_identity_kind: str | None = None
    contact_forwarded: bool = False
    original_sender_contact: str | None = None
    is_website_form: bool = False


@dataclass(frozen=True)
class IngestResult:
    message: Message
    created: bool


def _coerce_occurred_at(value: Any) -> datetime:
    """Normalize provider timestamps into a timezone-aware datetime.

    InboundMessageInput is a plain dataclass, so a type annotation does not
    convert anything. Graph returns ISO strings, Pydantic ingress returns
    datetimes, and Gmail parsing returns datetimes; all must reach the
    DateTime column as one concrete type or persistence raises at flush time.
    """
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            raise ValueError("occurred_at is empty")
        if text.endswith("Z"):
            text = f"{text[:-1]}+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError as exc:
            raise ValueError(f"occurred_at is not a valid ISO timestamp: {value[:64]!r}") from exc
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)
    raise ValueError("occurred_at must be a datetime or ISO timestamp string")


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

    raw_contact = str(message["customer_contact"]) if message.get("customer_contact") is not None else None
    original_sender = str(message["original_sender_contact"]) if message.get("original_sender_contact") is not None else None
    identity_source = original_sender if original_sender else raw_contact
    identity_kind = str(message.get("contact_identity_kind") or "")
    if identity_kind == "email" or (provider in {"gmail_api_pubsub", "outlook_mcp_graph"}):
        identity = normalize_email(identity_source)
    elif identity_kind == "whatsapp" or provider == "whatsapp_web_baileys":
        identity = normalize_whatsapp(raw_contact)
    else:
        identity = None
    # The website form is identified by the displayed From address only: the
    # whitelisted form mailbox. Form notifications are commonly relayed through
    # that mailbox, so relays/forwards are still genuine form submissions.
    is_website_form = website_form_sender_matches(raw_contact, original_sender)

    return InboundMessageInput(
        channel_account_id=channel_account_id,
        provider=provider,
        external_message_id=external_message_id,
        direction=str(message["direction"]),
        status=str(message["status"]),
        occurred_at=_coerce_occurred_at(message["occurred_at"]),
        raw_content=str(message["raw_content"]),
        customer_contact=raw_contact,
        customer_nickname=(
            "官网表单提交" if is_website_form else
            str(message["customer_nickname"]) if message.get("customer_nickname") is not None else None
        ),
        provider_web_link=(
            str(message["provider_web_link"])
            if message.get("provider_web_link") is not None else None
        ),
        attachments=tuple(attachment_inputs),
        normalized_customer_contact=(identity.normalized if identity is not None and not is_website_form else None),
        contact_identity_state=(
            "unsupported" if is_website_form else
            "forwarded"
            if message.get("contact_forwarded") and original_sender
            else "identity_uncertain"
            if message.get("contact_forwarded") and not original_sender
            else identity.state if identity is not None else "needs_manual_review"
        ),
        contact_identity_kind=(None if is_website_form else identity.kind if identity is not None else None),
        contact_forwarded=bool(message.get("contact_forwarded", False)),
        original_sender_contact=original_sender,
        is_website_form=is_website_form,
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
        if existing.is_website_form and not payload.is_website_form:
            existing.is_website_form = False
            existing.customer_contact = payload.customer_contact
            existing.customer_nickname = payload.customer_nickname
            existing.original_sender_contact = payload.original_sender_contact
            existing.normalized_customer_contact = (
                payload.normalized_customer_contact
                if payload.contact_identity_state == "certain"
                else None
            )
            existing.contact_identity_state = payload.contact_identity_state
            existing.contact_identity_kind = payload.contact_identity_kind
            existing.link_state = (
                "linked" if payload.contact_identity_state == "certain" else "manual_review"
            )
            if existing.inquiry_link is not None:
                inquiry = existing.inquiry_link.inquiry
                inquiry.customer_contact = payload.customer_contact or f"联系人 #{existing.id}"
                inquiry.normalized_customer_contact = existing.normalized_customer_contact
                inquiry.contact_identity_state = payload.contact_identity_state
                inquiry.contact_identity_kind = payload.contact_identity_kind
                inquiry.customer_nickname = payload.customer_nickname or payload.customer_contact or f"联系人 #{existing.id}"
                inquiry.raw_message = existing.raw_content
        if payload.contact_identity_state == "certain" and payload.normalized_customer_contact and not existing.normalized_customer_contact:
            existing.normalized_customer_contact = payload.normalized_customer_contact
            existing.contact_identity_state = "forwarded" if payload.contact_forwarded else "certain"
            existing.contact_identity_kind = payload.contact_identity_kind
            existing.original_sender_contact = payload.original_sender_contact
        # Provider re-reads can contain metadata that was unavailable when an
        # older row was first ingested. Backfill only missing presentation
        # fields; the provider identity and message body remain immutable.
        if existing.customer_contact is None and payload.customer_contact:
            existing.customer_contact = payload.customer_contact
            existing.contact_identity_state = payload.contact_identity_state
            existing.contact_identity_kind = payload.contact_identity_kind
            existing.original_sender_contact = payload.original_sender_contact
        if existing.customer_nickname is None and payload.customer_nickname:
            existing.customer_nickname = payload.customer_nickname
        if existing.provider_web_link is None and payload.provider_web_link:
            existing.provider_web_link = payload.provider_web_link
        if existing.direction == "inbound" and existing.inquiry_link is None and existing.link_state in {"pending", "manual_review", "unmatched"} and existing.contact_identity_state == "certain":
            _link_inbound_message_to_inquiry(db, existing)
        return IngestResult(message=existing, created=False)

    message = Message(
        channel_account_id=payload.channel_account_id,
        provider=payload.provider,
        external_message_id=payload.external_message_id,
        direction=payload.direction,
        status=payload.status,
        occurred_at=payload.occurred_at,
        raw_content=payload.raw_content,
        customer_contact=payload.customer_contact,
        is_website_form=payload.is_website_form,
        normalized_customer_contact=payload.normalized_customer_contact,
        contact_identity_state=payload.contact_identity_state,
        contact_identity_kind=payload.contact_identity_kind,
        original_sender_contact=payload.original_sender_contact,
        customer_nickname=payload.customer_nickname,
        provider_web_link=payload.provider_web_link,
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
    # Keep the source row, any auto-created Inquiry, and the association in one
    # savepoint. A failed link must never leave an unlinked partial ingest.
    savepoint = db.begin_nested()
    db.add(message)
    try:
        db.flush()
        if message.direction == "inbound" and (message.customer_contact or message.is_website_form):
            _link_inbound_message_to_inquiry(db, message)
        savepoint.commit()
    except IntegrityError as exc:
        savepoint.rollback()
        if not _is_identity_conflict(exc):
            raise
        existing = _find_existing(db, payload)
        if existing is None:
            raise
        return IngestResult(message=existing, created=False)
    except Exception:
        if savepoint.is_active:
            savepoint.rollback()
        raise
    return IngestResult(message=message, created=True)


def _link_inbound_message_to_inquiry(db: Session, message: Message) -> None:
    """Create or continue the unique exact-contact inquiry, without guessing ties."""
    if message.is_website_form:
        inquiry = Inquiry(
            customer_contact=f"官网表单提交 #{message.id}",
            normalized_customer_contact=None,
            contact_identity_state="unsupported",
            contact_identity_kind=None,
            customer_nickname=f"官网表单提交 #{message.id}",
            raw_message=message.raw_content,
            source_channel_account_id=message.channel_account_id,
            status="new",
            handling_status="pending",
            events=[InquiryEvent(event_type="inquiry_created", to_status="new")],
        )
        db.add(inquiry)
        db.flush()
        db.add(InquiryMessage(inquiry_id=inquiry.id, message_id=message.id, position=1, link_source="initial_inbound"))
        message.inquiry_link = db.query(InquiryMessage).filter_by(message_id=message.id).one()
        message.link_state = "linked"
        db.flush()
        return
    contact = message.normalized_customer_contact or ""
    if message.contact_identity_state != "certain" or not contact:
        message.link_state = "manual_review" if message.contact_identity_state in {"forwarded", "identity_uncertain", "needs_manual_review"} else "not_linkable"
        return
    account = db.get(ChannelAccount, message.channel_account_id)
    if account is None:
        message.link_state = "not_linkable"
        return
    message_kind = message.contact_identity_kind
    if message_kind == "email" or (message_kind is None and account.channel_type in {"gmail", "outlook"}):
        contact_match = or_(
            Inquiry.normalized_customer_contact == contact,
            and_(Inquiry.normalized_customer_contact.is_(None), func.lower(Inquiry.customer_contact) == contact),
        )
        same_identity = or_(
            Inquiry.contact_identity_state == "certain",
            and_(Inquiry.contact_identity_state == "needs_manual_review", Inquiry.contact_identity_kind.is_(None)),
        )
        identity_kind = or_(
            Inquiry.contact_identity_kind == "email",
            and_(
                Inquiry.contact_identity_kind.is_(None),
                func.lower(Inquiry.customer_contact) == contact,
            ),
        )
        source_channel = ChannelAccount.channel_type.in_(("gmail", "outlook"))
    elif message_kind == "whatsapp" or (message_kind is None and account.channel_type == "whatsapp"):
        contact_match = Inquiry.normalized_customer_contact == contact
        same_identity = Inquiry.contact_identity_state == "certain"
        identity_kind = Inquiry.contact_identity_kind == "whatsapp"
        source_channel = ChannelAccount.channel_type == "whatsapp"
    else:
        message_kind = message.contact_identity_kind
        if message_kind == "email":
            contact_match = Inquiry.normalized_customer_contact == contact
            same_identity = Inquiry.contact_identity_state == "certain"
            identity_kind = Inquiry.contact_identity_kind == "email"
            source_channel = ChannelAccount.channel_type.in_(("gmail", "outlook"))
        elif message_kind == "whatsapp":
            contact_match = Inquiry.normalized_customer_contact == contact
            same_identity = Inquiry.contact_identity_state == "certain"
            identity_kind = Inquiry.contact_identity_kind == "whatsapp"
            source_channel = ChannelAccount.channel_type == "whatsapp"
        else:
            message.link_state = "not_linkable"
            return

    candidates = db.scalars(
        select(Inquiry)
        .join(ChannelAccount, ChannelAccount.id == Inquiry.source_channel_account_id)
        .where(
            contact_match,
            same_identity,
            identity_kind,
            Inquiry.handling_status.in_(RELINKABLE_INQUIRY_HANDLING_STATUSES),
            ChannelAccount.status != "revoked",
            source_channel,
        )
        # Each inquiry references at most one channel account, so this join
        # cannot duplicate inquiries. PostgreSQL rejects DISTINCT FOR UPDATE.
        .with_for_update(of=Inquiry)
    ).all()
    if len(candidates) > 1:
        # Leave the source Message unlinked for the operator decision path.
        message.link_state = "manual_review"
        return
    created = False
    if candidates:
        inquiry = candidates[0]
        if inquiry.handling_status in {"processed", "ignored"}:
            previous_status = inquiry.handling_status
            inquiry.handling_status = "pending"
            inquiry.events.append(
                InquiryEvent(
                    event_type="inquiry_reactivated",
                    from_status=previous_status,
                    to_status="pending",
                )
            )
    else:
        message.link_state = "unmatched"
        inquiry = Inquiry(
            customer_contact=message.customer_contact or contact,
            normalized_customer_contact=contact,
            contact_identity_state=message.contact_identity_state,
            contact_identity_kind=message.contact_identity_kind,
            customer_nickname=message.customer_nickname or message.customer_contact or contact,
            raw_message=message.raw_content,
            source_channel_account_id=message.channel_account_id,
            status="new",
            handling_status="pending",
            events=[InquiryEvent(event_type="inquiry_created", to_status="new")],
        )
        db.add(inquiry)
        db.flush()
        created = True
    current_position = db.scalar(
        select(func.coalesce(func.max(InquiryMessage.position), 0) + 1)
        .where(InquiryMessage.inquiry_id == inquiry.id)
    )
    link = InquiryMessage(
        inquiry_id=inquiry.id,
        message_id=message.id,
        position=current_position,
        link_source="inbound_match" if not created else "initial_inbound",
    )
    db.add(link)
    # Assign the relationship as well as the foreign keys so callers holding
    # this Message see the newly-created link without a refresh/expiry cycle.
    message.inquiry_link = link
    message.link_state = "linked"
    db.flush()


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
