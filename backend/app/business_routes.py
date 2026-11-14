from typing import Annotated, Any, Literal, Mapping
from datetime import datetime, timedelta, timezone
import logging
import re
from urllib.parse import quote

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.auth import current_user, require_csrf
from app.content_security import legacy_contact_view, redact_contact_text
from app.contact_identity import normalize_email, normalize_whatsapp
from app.business_service import InquiryAction, _operator_has_all_message_scopes, as_utc, lifecycle_stage, transition_inquiry
from app.authorization import (
    can_operate_channels,
    channel_onboarding_account_ids,
    deny,
    inquiry_message_account_scope,
    get_scoped_inquiry,
    get_scoped_message,
    get_scoped_notification,
    scoped_channel_account_ids,
    scoped_inquiries,
    scoped_messages,
    validate_read_query,
)
from app.database import get_db
from app.message_ingestion import WEBSITE_FORM_EMAIL, effective_website_form
from app.message_semantics import (
    CONTENT_STATE_HIDDEN,
    CONTENT_STATE_READY,
    content_state,
    inline_safe_text,
    is_revoked_content,
    needs_body_repair,
    safe_content_view,
)
from app.gmail_client import GmailApiClient, GmailConfigurationError
from app.gmail_credentials import GmailCredentialError, decrypt_refresh_token
from app.models.business import (
    ChannelAccount,
    Inquiry,
    InquiryEvent,
    InquiryMessage,
    InternalNotification,
    Message,
    OperationLog,
)
from app.models.overview import MessageOverview
from app.models.permissions import ManagerPermissionGrant
from app.overview_service import ensure_message_overview, schedule_message_overview
from app.outlook_graph import OutlookGraphError, outlook_graph_client_for_ciphertext
from app.outlook_credentials import OutlookCredentialError, decrypt_refresh_token as decrypt_outlook_refresh_token
from app.whatsapp_adapter import (
    HttpWhatsAppAdapterClient,
    WhatsAppAdapterConfigurationError,
    WhatsAppAdapterUnavailableError,
)
from app.channels.inbound import ProviderAuthorizationFailure, ProviderPermanentFailure, ProviderRateLimited, ProviderTemporaryFailure
from app.provider_links import (
    OUTLOOK_WEB_HOSTS,
    outlook_account_is_personal,
    outlook_inbox_url,
    outlook_web_link,
)
from app.provider_transport import classify_network_failure, provider_proxy_summary
from app.models.user import User, UserSession

router = APIRouter(prefix="/api", tags=["business"])
logger = logging.getLogger(__name__)

INQUIRY_STATUSES = ("new", "assigned")
INQUIRY_HANDLING_STATUSES = ("pending", "processed", "ignored")

WHATSAPP_WEB_INBOX = "https://web.whatsapp.com/"

__all__ = ["router", "OUTLOOK_WEB_HOSTS"]


def _whatsapp_phone(value: str | None) -> str | None:
    """Return an E.164-style phone only when it is safe for a desktop deep link.

    Only a personal number (``<phone>@s.whatsapp.net``) can address a chat.
    Group JIDs (``@g.us``) and privacy-linked ids (``@lid``) are not phone
    numbers; converting them would open a chat with a stranger, so they are
    rejected and the caller falls back to the WhatsApp root.
    """
    if not value:
        return None
    candidate = value.strip()
    if "@" in candidate:
        user, _, host = candidate.partition("@")
        if host.strip().lower() != "s.whatsapp.net":
            return None
        candidate = user
    # A JID may carry a device suffix: 8613812345678:12@s.whatsapp.net
    candidate = candidate.split(":", 1)[0]
    candidate = re.sub(r"[\s().+-]", "", candidate)
    return candidate if candidate.isdigit() and 6 <= len(candidate) <= 15 else None


class TransferBody(BaseModel):
    sales_user_id: int = Field(gt=0)
    business_type: Literal["inquiry", "after_sales"] = "inquiry"


class InquiryMessageLinkBody(BaseModel):
    message_id: int = Field(gt=0)
    confirm_identity: bool = False


class MessageLinkCandidatesBody(BaseModel):
    message_id: int = Field(gt=0)


class InquiryActionBody(BaseModel):
    action: Literal["processed", "ignored"]


class MessageBulkActionBody(BaseModel):
    """One operator action applied to a bounded selection of visible messages."""

    message_ids: list[int] = Field(min_length=1, max_length=100)
    action: Literal["processed", "ignored"]


class InternalAIQuery(BaseModel):
    query: Literal["channel_accounts", "inquiries", "notifications"]
    operation: Literal["read", "create", "update", "delete", "assign", "send"] = "read"


class InternalAnalysisQuery(BaseModel):
    operation: Literal["read", "create", "update", "delete", "assign", "send"] = "read"


def _attachment_view(attachment: object) -> dict[str, object]:
    return {
        "id": attachment.id,
        "original_filename": attachment.original_filename,
        "media_type": attachment.media_type,
        "size_bytes": attachment.size_bytes,
    }


def _account_view(account: ChannelAccount) -> dict[str, int | str]:
    return {
        "id": account.id,
        "owner_user_id": account.owner_user_id,
        "channel_type": account.channel_type,
        "status": account.status,
    }


def _visible_inquiry_events(db: Session, user: User, inquiry: Inquiry) -> list[InquiryEvent]:
    if user.role == "admin":
        visible_ids = _visible_linked_message_ids(db, user, inquiry)
        all_ids = set(db.scalars(
            select(InquiryMessage.message_id).where(InquiryMessage.inquiry_id == inquiry.id)
        ).all())
        event_filter = InquiryEvent.message_id.in_(visible_ids)
        if all_ids == visible_ids and visible_ids:
            event_filter = or_(InquiryEvent.message_id.is_(None), event_filter)
        return db.scalars(
            select(InquiryEvent)
            .where(InquiryEvent.inquiry_id == inquiry.id, event_filter)
            .order_by(InquiryEvent.occurred_at, InquiryEvent.id)
        ).all()
    visible_ids = _visible_linked_message_ids(db, user, inquiry)
    all_ids = set(db.scalars(
        select(InquiryMessage.message_id).where(InquiryMessage.inquiry_id == inquiry.id)
    ).all())
    if not visible_ids:
        return []
    event_filter = InquiryEvent.message_id.in_(visible_ids)
    if all_ids == visible_ids:
        event_filter = or_(InquiryEvent.message_id.is_(None), event_filter)
    return db.scalars(
        select(InquiryEvent)
        .where(InquiryEvent.inquiry_id == inquiry.id, event_filter)
        .order_by(InquiryEvent.occurred_at, InquiryEvent.id)
    ).all()


def _batch_visible_message_ids(
    db: Session, user: User, inquiry_ids: list[int]
) -> dict[int, set[int]]:
    if not inquiry_ids:
        return {}
    query = (
        select(InquiryMessage.inquiry_id, InquiryMessage.message_id)
        .join(Message, Message.id == InquiryMessage.message_id)
        .join(ChannelAccount, ChannelAccount.id == Message.channel_account_id)
        .where(
            InquiryMessage.inquiry_id.in_(inquiry_ids),
            ChannelAccount.status != "revoked",
            ChannelAccount.history_access_revoked_at.is_(None),
        )
    )
    if user.role == "admin":
        query = query.where(Message.direction == "inbound")
    query = query.where(Message.channel_account_id.in_(inquiry_message_account_scope(user)))
    visible: dict[int, set[int]] = {}
    for inquiry_id, message_id in db.execute(query):
        visible.setdefault(inquiry_id, set()).add(message_id)
    return visible


def _loaded_inquiry_events(inquiry: Inquiry, visible_message_ids: set[int]) -> list[InquiryEvent]:
    if not visible_message_ids:
        return []
    linked_ids = {link.message_id for link in inquiry.message_links}
    return [
        event
        for event in sorted(inquiry.events, key=lambda item: (item.occurred_at, item.id))
        if linked_ids == visible_message_ids or event.message_id in visible_message_ids
    ]


def _assignee_labels(db: Session, inquiries: list[Inquiry]) -> dict[int, dict[str, str]]:
    """Resolve owner ids to display labels in one query per page, not per inquiry.

    负责人对外显示的是「员工姓名」（真人可读），用户名只是登录凭据、作为副标识。
    """
    owner_ids = {inquiry.assigned_sales_user_id for inquiry in inquiries if inquiry.assigned_sales_user_id is not None}
    if not owner_ids:
        return {}
    rows = db.execute(
        select(User.id, User.username, User.full_name).where(User.id.in_(owner_ids))
    ).all()
    return {
        user_id: {"username": username, "name": full_name or username}
        for user_id, username, full_name in rows
    }


def _transfer_labels(db: Session, inquiries: list[Inquiry]) -> dict[int, dict[str, object]]:
    """Resolve the latest "who handed this over" per inquiry in one query.

    转交人 = 点了「分配」的那个运营账号（`inquiry_transferred` 事件的 actor），
    与负责人（target）是两个人，必须分开显示。
    """
    inquiry_ids = [inquiry.id for inquiry in inquiries]
    if not inquiry_ids:
        return {}
    rows = db.execute(
        select(
            InquiryEvent.inquiry_id,
            InquiryEvent.actor_user_id,
            InquiryEvent.occurred_at,
            User.username,
            User.full_name,
        )
        .join(User, User.id == InquiryEvent.actor_user_id, isouter=True)
        .where(
            InquiryEvent.inquiry_id.in_(inquiry_ids),
            InquiryEvent.event_type == "inquiry_transferred",
        )
        .order_by(InquiryEvent.inquiry_id, InquiryEvent.occurred_at.desc(), InquiryEvent.id.desc())
    ).all()
    latest: dict[int, dict[str, object]] = {}
    for inquiry_id, actor_id, occurred_at, username, full_name in rows:
        if inquiry_id in latest:
            continue  # 只保留最近一次转交
        latest[inquiry_id] = {
            "name": (full_name or username) if actor_id is not None else None,
            "username": username,
            "at": occurred_at,
        }
    return latest


def _assignee_label(db: Session, user_id: int | None) -> dict[str, str] | None:
    if user_id is None:
        return None
    row = db.execute(
        select(User.username, User.full_name).where(User.id == user_id)
    ).first()
    if row is None:
        return None
    username, full_name = row
    return {"username": username, "name": full_name or username}


def _linked_message_content_view(message: Message, user: User) -> dict[str, object]:
    """Sanitized body shown as the primary text of a customer-chain message.

    Administrators keep their read-only inquiry view but never receive message
    bodies, even through this embedded channel.
    """
    if user.role == "admin":
        return {
            "content_state": CONTENT_STATE_HIDDEN,
            "safe_content_status": content_state(message.raw_content),
            "safe_text": None,
            "safe_text_truncated": False,
        }
    text, truncated = inline_safe_text(message.raw_content)
    return {
        "content_state": content_state(message.raw_content),
        "safe_text": text,
        "safe_text_truncated": truncated,
    }


def _inquiry_view(
    db: Session,
    user: User,
    inquiry: Inquiry,
    *,
    visible_message_ids: set[int] | None = None,
    visible_events: list[InquiryEvent] | None = None,
    assignee_labels: dict[int, dict[str, str]] | None = None,
    transfer_labels: dict[int, dict[str, object]] | None = None,
) -> dict[str, object]:
    visible_message_ids = visible_message_ids if visible_message_ids is not None else _visible_linked_message_ids(db, user, inquiry)
    linked_messages = [
        link.message
        for link in sorted(inquiry.message_links, key=lambda item: (item.position, item.message_id))
        if link.message_id in visible_message_ids
    ]
    visible_events = visible_events if visible_events is not None else _visible_inquiry_events(db, user, inquiry)
    all_linked_ids = {link.message_id for link in inquiry.message_links}
    if user.role == "admin" and all_linked_ids != visible_message_ids:
        visible_events = [event for event in visible_events if event.message_id in visible_message_ids]
    elif user.role != "admin" and all_linked_ids != visible_message_ids:
        # Generic Inquiry events may reflect activity from a hidden source.
        # For partial views expose only events explicitly tied to a visible message.
        visible_events = [event for event in visible_events if event.message_id in visible_message_ids]
    contact_sources = [
        {
            "raw_customer_contact": None if user.role == "admin" else message.customer_contact,
            "normalized_customer_contact": None if user.role == "admin" else message.normalized_customer_contact,
            "contact_identity_state": "unsupported" if user.role == "admin" else message.contact_identity_state,
            "contact_identity_kind": None if user.role == "admin" else message.contact_identity_kind,
            "customer_nickname": None if user.role == "admin" else message.customer_nickname,
            **({} if user.role == "admin" else {"channel_account_id": message.channel_account_id}),
            "channel_type": "website_form" if effective_website_form(message) else message.channel_account.channel_type,
        }
        for message in linked_messages
    ]
    assignee = (
        (assignee_labels or {}).get(inquiry.assigned_sales_user_id)
        or _assignee_label(db, inquiry.assigned_sales_user_id)
        or {}
    )
    transfer = (
        (transfer_labels or {}).get(inquiry.id)
        or _transfer_labels(db, [inquiry]).get(inquiry.id)
        or {}
    )
    return {
        "id": inquiry.id,
        "contact_sources": contact_sources,
        "source_channel_account_id": None,
        "status": inquiry.status,
        "handling_status": inquiry.handling_status,
        "business_type": inquiry.business_type,
        "assigned_sales_user_id": inquiry.assigned_sales_user_id,
        # 负责人按「员工姓名」展示，用户名作为辅助标识；绝不显示「用户 #3」。
        "assigned_sales_name": assignee.get("name"),
        "assigned_sales_username": assignee.get("username"),
        # 转交人：点「分配」的运营账号，与负责人不是同一个人。
        "transferred_by_name": transfer.get("name"),
        "transferred_by_username": transfer.get("username"),
        "transferred_at": transfer.get("at"),
        "last_activity_at": inquiry.last_activity_at if visible_message_ids else None,
        "lifecycle_stage": lifecycle_stage(inquiry) if visible_message_ids else "unknown",
        "created_at": inquiry.created_at,
        "updated_at": inquiry.updated_at if visible_message_ids else None,
        "timeline": [_event_view(event) for event in visible_events],
        "timeline_complete": bool(visible_events),
        # Attachments remain Message-scoped and are available only from each
        # authorized Message endpoint; never aggregate them onto Inquiry.
        "attachments": [],
        "messages": [
            {
                "id": message.id,
                **({} if user.role == "admin" else {"channel_account_id": message.channel_account_id}),
                **({} if user.role == "admin" else {
                    "channel_account_external_id": message.channel_account.external_account_id,
                    "provider": message.provider,
                    "external_message_id": message.external_message_id,
                }),
                "channel_type": "website_form" if effective_website_form(message) else message.channel_account.channel_type,
                "direction": message.direction,
                "handling_status": message.handling_status,
                "occurred_at": message.occurred_at,
                # Admin inquiry view exposes masked summary only, never body text.
                **_linked_message_content_view(message, user),
                "overview_status": (
                    "not_applicable_revoked" if is_revoked_content(message.raw_content)
                    else message.overview.status if message.overview
                    else "not_generated"
                ),
                "safe_content_status": content_state(message.raw_content),
                "overview_text": (
                    redact_contact_text(
                        message.overview.overview_text,
                        (message.customer_contact, message.normalized_customer_contact, message.original_sender_contact, message.customer_nickname),
                    )
                    if user.role == "admin" and message.overview and message.overview.status == "ready" and not is_revoked_content(message.raw_content)
                    else None if user.role == "admin" or is_revoked_content(message.raw_content)
                    else message.overview.overview_text if message.overview else None
                ),
            }
            for message in linked_messages
        ],
    }


def _event_view(event: InquiryEvent) -> dict[str, object]:
    return {
        "id": event.id,
        "event_type": event.event_type,
        "actor_user_id": event.actor_user_id,
        "from_status": event.from_status,
        "to_status": event.to_status,
        "target_user_id": event.target_user_id,
        "occurred_at": event.occurred_at,
        "created_at": event.created_at,
    }


def _record_operation(
    db: Session,
    user: User,
    *,
    name: str,
    object_type: str,
    object_id: int | None,
    result: str = "success",
    detail: str | None = None,
) -> None:
    db.add(OperationLog(
        actor_user_id=user.id,
        actor_name=user.username,
        operation_name=name,
        object_type=object_type,
        object_id=object_id,
        result=result,
        detail=detail,
    ))
    db.commit()


@router.get("/operation-logs")
def list_operation_logs(
    user: Annotated[User, Depends(current_user)],
    db: Session = Depends(get_db),
    limit: int = Query(default=100, ge=1, le=200),
    inquiry_id: int | None = Query(default=None, gt=0),
) -> list[dict[str, object]]:
    if user.role != "admin" and not can_operate_channels(user):
        raise deny()
    query = select(OperationLog)
    if inquiry_id is None and user.role == "admin":
        query = query.where(OperationLog.actor_user_id == user.id)
    if inquiry_id is not None:
        inquiry = db.scalar(scoped_inquiries(user).where(Inquiry.id == inquiry_id))
        if inquiry is None:
            raise deny()
        all_linked_message_ids = set(db.scalars(
            select(InquiryMessage.message_id).where(InquiryMessage.inquiry_id == inquiry_id)
        ).all())
        visible_linked_message_ids = set(db.scalars(
            select(InquiryMessage.message_id)
            .join(Message, Message.id == InquiryMessage.message_id)
            .where(
                InquiryMessage.inquiry_id == inquiry_id,
                Message.id.in_(scoped_messages(user).with_only_columns(Message.id)),
            )
        ).all())
        linked_message_logs = and_(
            OperationLog.object_type == "message",
            OperationLog.object_id.in_(visible_linked_message_ids),
        )
        if all_linked_message_ids == visible_linked_message_ids:
            query = query.where(or_(
                linked_message_logs,
                and_(OperationLog.object_type == "inquiry", OperationLog.object_id == inquiry_id),
            ))
        else:
            query = query.where(linked_message_logs)
    else:
        query = query.where(OperationLog.actor_user_id == user.id)
    rows = db.scalars(
        query.order_by(OperationLog.created_at.desc(), OperationLog.id.desc()).limit(limit)
    ).all()
    return [
        {
            "id": row.id,
            "actor_name": row.actor_name,
            "operation_name": row.operation_name,
            "object_type": row.object_type,
            "object_id": row.object_id,
            "result": row.result,
            "detail": None if user.role == "admin" else row.detail,
            "created_at": row.created_at,
        }
        for row in rows
    ]


def _identity_candidate_query(db: Session, message: Message, user: User | None = None) -> list[Inquiry]:
    contact = message.normalized_customer_contact
    channel = message.channel_account.channel_type
    if message.contact_identity_state != "certain" or not contact:
        return []
    if message.contact_identity_kind == "email":
        contact_predicate = or_(
            Inquiry.normalized_customer_contact == contact,
            and_(
                Inquiry.normalized_customer_contact.is_(None),
                func.lower(Inquiry.customer_contact) == contact,
            ),
        )
        channel_predicate = ChannelAccount.channel_type.in_(("gmail", "outlook"))
        identity_predicate = or_(
            Inquiry.contact_identity_kind == "email",
            and_(
                Inquiry.contact_identity_kind.is_(None),
                func.lower(Inquiry.customer_contact) == contact,
            ),
        )
    elif message.contact_identity_kind == "whatsapp":
        contact_predicate = Inquiry.normalized_customer_contact == contact
        channel_predicate = ChannelAccount.channel_type == "whatsapp"
        identity_predicate = Inquiry.contact_identity_kind == "whatsapp"
    else:
        return []
    query = (
        select(Inquiry)
        .join(ChannelAccount, ChannelAccount.id == Inquiry.source_channel_account_id)
        .where(
            contact_predicate,
            channel_predicate,
            identity_predicate,
            or_(
                Inquiry.contact_identity_state == "certain",
                and_(Inquiry.contact_identity_state == "needs_manual_review", Inquiry.contact_identity_kind.is_(None)),
            ),
            ChannelAccount.status != "revoked",
            Inquiry.id.in_(scoped_inquiries(user).with_only_columns(Inquiry.id) if user is not None else select(Inquiry.id)),
            Inquiry.id != (message.inquiry_link.inquiry_id if message.inquiry_link else -1),
        )
        .distinct()
        .order_by(Inquiry.updated_at.desc(), Inquiry.id)
    )
    return db.scalars(query).all()


def _manual_confirmation_candidates(db: Session, message: Message, user: User, limit: int = 50) -> list[Inquiry]:
    """List authorized, channel-compatible inquiries for an operator to review.

    This never matches or guesses an identity: it only surfaces objects the
    caller may already see, so an operator can explicitly confirm which chain a
    message belongs to when the sender identity could not be established.
    """
    channel_type = message.channel_account.channel_type
    if channel_type == "whatsapp":
        allowed = ("whatsapp",)
    elif channel_type in {"gmail", "outlook"}:
        allowed = ("gmail", "outlook")
    else:
        return []
    query = (
        select(Inquiry)
        .join(ChannelAccount, ChannelAccount.id == Inquiry.source_channel_account_id, isouter=True)
        .where(
            or_(ChannelAccount.channel_type.in_(allowed), Inquiry.source_channel_account_id.is_(None)),
            or_(ChannelAccount.status.is_(None), ChannelAccount.status != "revoked"),
            Inquiry.id.in_(scoped_inquiries(user).with_only_columns(Inquiry.id)),
            Inquiry.id != (message.inquiry_link.inquiry_id if message.inquiry_link else -1),
        )
        .distinct()
        .order_by(Inquiry.updated_at.desc(), Inquiry.id)
        .limit(limit)
    )
    return db.scalars(query).all()


def _message_view(message: Message, db: Session | None = None, user: User | None = None) -> dict[str, object]:
    account = message.channel_account
    if user is not None and user.role == "admin":
        # Admin message APIs are a summary/status surface only. Inquiry detail
        # uses its separate redacted projection; never return message bodies,
        # contacts, source IDs, attachments, or provider links here.
        overview = message.overview
        return {
            "id": message.id,
            "channel_type": "website_form" if effective_website_form(message) else account.channel_type,
            "direction": message.direction,
            "ingestion_status": message.status,
            "handling_status": message.handling_status,
            "occurred_at": message.occurred_at,
            "created_at": message.created_at,
            "inquiry_id": message.inquiry_link.inquiry_id if message.inquiry_link else None,
            "link_state": message.link_state,
            "safe_content_status": content_state(message.raw_content),
            "overview_status": (
                "not_applicable_revoked" if is_revoked_content(message.raw_content)
                else overview.status if overview is not None
                else "not_generated"
            ),
            "overview": (
                {
                    "status": overview.status,
                    "text": redact_contact_text(
                        overview.overview_text,
                        (message.customer_contact, message.normalized_customer_contact, message.original_sender_contact, message.customer_nickname),
                    ) if overview.status == "ready" else None,
                }
                if overview is not None and not is_revoked_content(message.raw_content)
                else None
            ),
            "attachments": [],
        }
    contact = message.customer_contact
    nickname = message.customer_nickname
    if not contact and not nickname:
        contact, nickname = legacy_contact_view(message.raw_content, message.provider)
    form = effective_website_form(message)
    return {
        "id": message.id,
        "channel_account_id": message.channel_account_id,
        "channel_type": "website_form" if form else account.channel_type,
        "provider": message.provider,
        "external_message_id": message.external_message_id,
        "customer_contact": "官网表单" if form else contact,
        "normalized_customer_contact": None if form else message.normalized_customer_contact,
        "original_sender_contact": None if form else message.original_sender_contact,
        "contact_identity_state": "unsupported" if form else message.contact_identity_state,
        "contact_identity_kind": None if form else message.contact_identity_kind,
        "customer_nickname": "官网表单" if form else nickname,
        "direction": message.direction,
        "ingestion_status": message.status,
        "handling_status": message.handling_status,
        "occurred_at": message.occurred_at,
        "created_at": message.created_at,
        # 清洗后的安全原文（含撤回语义），中文概述只是辅助信息。
        **safe_content_view(message.raw_content),
        "inquiry_id": message.inquiry_link.inquiry_id if message.inquiry_link else None,
        "link_state": message.link_state,
        "is_website_form": form,
        "overview": (
            {
                "status": message.overview.status,
                "text": message.overview.overview_text,
                "failure_code": message.overview.failure_code,
                "retry_count": message.overview.retry_count,
                "provider_name": message.overview.provider_name,
                "model_name": message.overview.model_name,
                "prompt_version": message.overview.prompt_version,
            }
            if message.overview is not None and not is_revoked_content(message.raw_content)
            else None
        ),
        "attachments": [_attachment_view(attachment) for attachment in message.attachments],
    }


@router.get("/channel-accounts")
def list_channel_accounts(
    user: Annotated[User, Depends(current_user)],
    db: Session = Depends(get_db),
) -> list[dict[str, int | str]]:
    if user.role != "admin" and not can_operate_channels(user):
        return []
    account_scope = inquiry_message_account_scope(user) if user.role == "admin" else scoped_channel_account_ids(user)
    accounts = db.scalars(
        select(ChannelAccount)
        .where(ChannelAccount.id.in_(account_scope))
        .order_by(ChannelAccount.id)
    ).all()
    return [_account_view(account) for account in accounts]


REFETCH_CHECK_ACTIONS = {
    "credentials_missing": "账号没有保存 refresh token，请在「我的 / 接入账号」撤销后重新授权该渠道。",
    "credential_decrypt_failed": "凭据无法解密：服务端加密密钥与授权时不一致，请恢复原密钥并重新授权。",
    "oauth_config_missing": "服务端缺少 OAuth CLIENT_ID / CLIENT_SECRET，请检查 .env 后重新授权。",
    "authorization_expired": "授权已失效，请重新授权该渠道。",
    "provider_unavailable": "provider 返回错误，请查看 backend 日志中的具体错误类型。",
    "network_unavailable": "实时回源需要后端直连 provider，当前出站链路不可用。",
    "session_offline": "点「开始关联」重新扫码即可，历史消息不受影响。",
    "bridge_unreachable": "whatsapp-bridge 不可达，请检查容器状态与 WHATSAPP_ADAPTER_URL。",
    "adapter_not_configured": "WHATSAPP_ADAPTER_URL / WHATSAPP_ADAPTER_TOKEN 未配置。",
    "unsupported_channel": "该渠道不支持实时回源。",
    "unknown": "回源链路出现未知错误，请查看 backend 日志。",
}

# A failure the operator cannot fix by looking at the page: the account is
# simply not linked yet. These are informational, not errors.
NOT_READY_FAILURES = {"session_offline", "unsupported_channel"}

_classify_network_failure = classify_network_failure


@router.get("/channel-accounts/{account_id}/refetch-check")
def check_channel_refetch(
    account_id: int,
    user: Annotated[User, Depends(current_user)],
    db: Session = Depends(get_db),
) -> dict[str, object]:
    """Probe the real live-refetch chain for one authorized account.

    Each step performs an actual credential/token/provider call. No token,
    secret, or customer content is returned; only fixed diagnostic labels.
    An administrator who connected a channel themselves may run the same
    diagnostic on their own account before handing it to an operator.
    """
    account = db.scalar(
        select(ChannelAccount).where(
            ChannelAccount.id == account_id,
            ChannelAccount.id.in_(channel_onboarding_account_ids(user)),
            ChannelAccount.history_access_revoked_at.is_(None),
        )
    )
    if account is None:
        raise HTTPException(status_code=404, detail="没有权限访问")

    steps: list[dict[str, object]] = []

    def record(name: str, ok: bool, detail: str) -> None:
        steps.append({"name": name, "ok": ok, "detail": detail})

    channel = account.channel_type
    failure_kind: str | None = None
    failure_detail: dict[str, str] | None = None
    ready = False

    if channel in {"gmail", "outlook"}:
        record("出站网络配置", True, provider_proxy_summary())
        ciphertext = account.gmail_credential_ciphertext if channel == "gmail" else account.outlook_credential_ciphertext
        client: object | None = None
        if not ciphertext:
            record("凭据已保存", False, "账号没有保存加密 refresh token")
            failure_kind = "credentials_missing"
        else:
            record("凭据已保存", True, "账号已保存加密 refresh token")
            try:
                if channel == "gmail":
                    client = GmailApiClient(refresh_token=decrypt_refresh_token(ciphertext))
                else:
                    client = outlook_graph_client_for_ciphertext(ciphertext)
            except (GmailCredentialError, OutlookCredentialError):
                failure_kind = "credential_decrypt_failed"
                record("凭据解密 / OAuth 配置", False, "凭据无法解密或加密密钥不匹配")
            except GmailConfigurationError:
                failure_kind = "oauth_config_missing"
                record("凭据解密 / OAuth 配置", False, "OAuth 客户端配置不完整")
            except OutlookGraphError as exc:
                # outlook_graph_client_for_ciphertext reports a decryption
                # failure as a generic Graph error; keep it actionable.
                if "credential" in str(exc).lower():
                    failure_kind = "credential_decrypt_failed"
                    record("凭据解密 / OAuth 配置", False, "凭据无法解密或加密密钥不匹配")
                else:
                    failure_kind = "oauth_config_missing"
                    record("凭据解密 / OAuth 配置", False, "OAuth 客户端配置不完整")

        if client is not None and failure_kind is None:
            record("凭据解密 / OAuth 配置", True, "refresh token 可解密，OAuth 客户端配置完整")
            try:
                if channel == "gmail":
                    client._get("profile")
                else:
                    client._get("/me", {"$select": "id"})
                record("渠道 API 可达", True, "provider 已用该账号凭据成功响应")
                ready = True
            except ProviderAuthorizationFailure:
                failure_kind = "authorization_expired"
                record("渠道 API 可达", False, "provider 拒绝了访问令牌（401/403）")
            except (ProviderRateLimited, ProviderTemporaryFailure, ProviderPermanentFailure):
                failure_kind = "provider_unavailable"
                record("渠道 API 可达", False, "provider 返回了错误状态码")
            except OutlookGraphError as exc:
                message = str(exc).lower()
                if "authorization" in message:
                    failure_kind = "authorization_expired"
                    record("渠道 API 可达", False, "provider 拒绝了访问令牌（401/403）")
                elif "mapping" in message:
                    failure_kind = "provider_unavailable"
                    record("渠道路由校验", False, "Graph 返回的账号与本地映射不一致，请重新授权")
                else:
                    failure_kind = "provider_unavailable"
                    record("渠道 API 可达", False, "provider 返回错误状态")
            except (httpx.HTTPError, OSError) as exc:
                failure_kind = "network_unavailable"
                failure_detail = _classify_network_failure(exc)
                host = f"（{failure_detail['host']}）" if failure_detail["host"] else ""
                record("渠道 API 可达", False, f"无法连接 provider{host}：{failure_detail['label']}")
            except Exception as exc:
                failure_kind = "unknown"
                record("渠道 API 可达", False, f"未预期错误：{type(exc).__name__}")
                logger.warning("Refetch check failed account_id=%s error=%s", account.id, type(exc).__name__)
    elif channel == "whatsapp":
        try:
            state = HttpWhatsAppAdapterClient().status(channel_account_id=account.id)
            record("Bridge 可达", True, f"bridge 状态：{state.state}")
            connected = state.state in {"connected", "connected_pending_inbound"}
            record("会话在线", connected, "会话已连接" if connected else "会话未连接，需重新扫码")
            ready = connected
            if not connected:
                failure_kind = "session_offline"
        except WhatsAppAdapterConfigurationError:
            failure_kind = "adapter_not_configured"
            record("Bridge 可达", False, "adapter 配置不完整")
        except WhatsAppAdapterUnavailableError:
            failure_kind = "bridge_unreachable"
            record("Bridge 可达", False, "bridge 不可达")
    else:
        failure_kind = "unsupported_channel"

    history_available = bool(
        db.scalar(
            select(func.count()).select_from(Message).where(Message.channel_account_id == account.id)
        )
        or 0
    )

    if ready:
        severity = "ok"
    elif failure_kind in NOT_READY_FAILURES:
        severity = "not_ready"
    else:
        severity = "action_required"

    action = "实时回源链路可用。" if ready else REFETCH_CHECK_ACTIONS.get(failure_kind or "unknown", "")
    if failure_detail is not None:
        action = f"{action}{failure_detail['hint']}"

    return {
        "account_id": account.id,
        "channel_type": channel,
        "ready": ready,
        "failure_kind": failure_kind,
        "severity": severity,
        "recommended_action": action,
        "error_class": failure_detail["error_class"] if failure_detail else None,
        "network": (
            {"kind": failure_detail["kind"], "label": failure_detail["label"], "host": failure_detail["host"]}
            if failure_detail
            else None
        ),
        "history_available": history_available,
        "steps": steps,
    }


@router.get("/messages")
def list_messages(
    user: Annotated[User, Depends(current_user)],
    db: Session = Depends(get_db),
    handling_status: Literal["all", "pending", "processed", "ignored"] = Query(default="pending"),
    assignment_status: Literal["all", "assigned", "unassigned"] = Query(default="all"),
    ingestion_status: Literal["received", "processed", "failed"] | None = Query(default=None),
    channel_account_id: int | None = Query(default=None, gt=0),
    channel_type: Literal["website_form"] | None = Query(default=None),
    needs_review: bool = Query(default=False),
    sort: Literal["occurred_at", "created_at"] = Query(default="occurred_at"),
    descending: bool = Query(default=True),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
) -> dict[str, object]:
    if user.role not in {"admin", "staff", "operations", "ops", "sales"}:
        raise deny()
    query = scoped_messages(user)
    if handling_status != "all":
        query = query.where(Message.handling_status == handling_status)
    if assignment_status == "assigned":
        query = query.where(Message.inquiry_link.has(Inquiry.assigned_sales_user_id.is_not(None)))
    elif assignment_status == "unassigned":
        query = query.where(~Message.inquiry_link.has(Inquiry.assigned_sales_user_id.is_not(None)))
    if ingestion_status is not None:
        query = query.where(Message.status == ingestion_status)
    if channel_account_id is not None:
        query = query.where(Message.channel_account_id == channel_account_id)
    if channel_type == "website_form":
        # 只认规定的固定表单发件人（白名单邮箱），无论是否转发/代发；
        # 历史误标（发件人并非白名单邮箱）由 effective_website_form 复查剔除。
        form_sender = or_(
            func.lower(Message.customer_contact) == WEBSITE_FORM_EMAIL,
            func.lower(Message.customer_contact).like(f"%<{WEBSITE_FORM_EMAIL}>"),
        )
        query = query.where(
            Message.is_website_form.is_(True),
            form_sender,
        )
    if needs_review:
        query = query.where(~Message.inquiry_link.has(), or_(
            Message.link_state == "manual_review",
            Message.contact_identity_state.in_(("forwarded", "identity_uncertain", "needs_manual_review")),
        ))
    sort_column = Message.occurred_at if sort == "occurred_at" else Message.created_at
    ordering = sort_column.desc() if descending else sort_column.asc()
    offset = (page - 1) * page_size
    messages = db.scalars(
        query.options(
            selectinload(Message.channel_account),
            selectinload(Message.attachments),
            selectinload(Message.overview),
            selectinload(Message.inquiry_link),
        )
        .order_by(ordering, Message.id.desc() if descending else Message.id.asc())
        .offset(offset)
        .limit(page_size + 1)
    ).all()
    has_more = len(messages) > page_size
    messages = messages[:page_size]
    # A stub snapshot is only a real 撤回 when no original can be recovered.
    _heal_recoverable_messages(db, user, messages)
    return {
        "items": [_message_view(message, db, user) for message in messages],
        "page": page,
        "page_size": page_size,
        "has_more": has_more,
    }


@router.get("/messages/{message_id}")
def get_message(
    message_id: int,
    user: Annotated[User, Depends(current_user)],
    db: Session = Depends(get_db),
) -> dict[str, object]:
    if user.role in {"admin", "engineering", "procurement", "production"}:
        raise deny()
    message = get_scoped_message(db, user, message_id)
    # Message keeps its own content/provider data; the optional link state is
    # computed from identity metadata and authorized Inquiry candidates only.
    return _message_view(message, db, user)


def _resolve_outlook_web_link(db: Session, message: Message, account: ChannelAccount) -> str | None:
    """Repair a stored Outlook message that has no provider link yet.

    Rows ingested before the link column existed (or before the read stopped
    filtering on unread state) carry no link, which used to degrade every click
    to a generic inbox. The stored refresh token lets the backend ask Graph for
    the authoritative link once, and the result is persisted so the next click
    is local.
    """
    if not account.outlook_credential_ciphertext:
        return None
    identity = (message.external_message_id or "").strip()
    if not identity:
        return None
    try:
        client = outlook_graph_client_for_ciphertext(account.outlook_credential_ciphertext)
        link = outlook_web_link(client.message_web_link(identity))
    except OutlookGraphError:
        return None
    if link is None:
        return None
    message.provider_web_link = link
    try:
        db.commit()
    except Exception:
        db.rollback()
    return link


def _repair_message_body(db: Session, message: Message, body: str) -> bool:
    """Persist a recovered provider body over a stale, bodyless stub snapshot.

    WhatsApp can deliver a bodyless protocol stub first and the real message for
    the same id moments later. The ingest row then keeps claiming 已撤回 /
    原文不再可用 even though the original is visible in the "查看客户消息"
    dialog. Healing the stored snapshot makes list, chain and detail views agree
    on one authoritative body instead of contradicting each other.
    """
    body = str(body)
    if not needs_body_repair(getattr(message, "raw_content", ""), body):
        return False
    message.raw_content = body
    link = getattr(message, "inquiry_link", None)
    inquiry = getattr(link, "inquiry", None) if link is not None else None
    if inquiry is not None and needs_body_repair(getattr(inquiry, "raw_message", ""), body):
        inquiry.raw_message = body
    try:
        db.commit()
    except Exception:
        db.rollback()
        logger.warning(
            "WhatsApp body repair failed to commit: message_id=%s",
            getattr(message, "id", None),
        )
        return False
    # The overview was skipped while the row looked revoked; regenerate it from
    # the recovered text. A failure here must not undo the committed body.
    try:
        ensure_message_overview(db, message, force=True)
        db.commit()
    except Exception:
        db.rollback()
        logger.warning(
            "Overview regeneration failed after WhatsApp body repair: message_id=%s",
            getattr(message, "id", None),
        )
    logger.info("Recovered WhatsApp body for message %s", getattr(message, "id", None))
    return True


def _heal_recoverable_messages(
    db: Session,
    user: User,
    messages: list[Message],
    *,
    limit: int = 6,
) -> int:
    """Bounded, best-effort self-healing of stub snapshots on read surfaces.

    Only operator roles may trigger a provider refetch, and only WhatsApp rows
    still labelled 已撤回 are candidates. An unconfigured or failing bridge
    leaves the row untouched and never breaks the response.
    """
    if user.role not in {"staff", "operations", "ops"}:
        return 0
    healed = 0
    for message in messages:
        if healed >= limit:
            break
        if not is_revoked_content(getattr(message, "raw_content", "")):
            continue
        if not str(getattr(message, "provider", "") or "").startswith("whatsapp"):
            continue
        try:
            view, diagnostic = _safe_provider_content(
                message, allow_provider_refetch=True, db=db
            )
        except Exception:
            logger.warning(
                "WhatsApp body recheck failed: message_id=%s",
                getattr(message, "id", None),
            )
            continue
        if diagnostic is None and view.get("content_state") == CONTENT_STATE_READY:
            healed += 1
    return healed


def _safe_provider_content(
    message: Message,
    *,
    full: bool = False,
    allow_provider_refetch: bool = True,
    db: Session | None = None,
) -> tuple[dict[str, object], str | None]:
    """Refresh provider content when possible; otherwise return the stored snapshot.

    The ingest snapshot is authoritative: mail and IM messages are immutable, and
    WhatsApp cannot serve arbitrary historical messages by ID. A live refetch is
    therefore a best-effort integrity check, never a prerequisite for showing
    the original text. ``full`` selects the unbounded renderer used by the
    original-content detail view.
    """
    def render(value: Any) -> dict[str, object]:
        return safe_content_view(value, full=full)

    account = getattr(message, "channel_account", None)
    identity = (getattr(message, "external_message_id", None) or "").strip()
    cached = render(getattr(message, "raw_content", ""))
    if not allow_provider_refetch:
        return cached, "provider_refetch_not_requested"
    if not identity:
        return cached, "provider_message_id_missing"
    if account is None:
        return cached, "channel_account_unavailable"

    try:
        if message.provider in {"gmail_api_pubsub", "gmail_pubsub", "gmail"} and getattr(account, "gmail_credential_ciphertext", None):
            client = GmailApiClient(
                refresh_token=decrypt_refresh_token(account.gmail_credential_ciphertext)
            )
            fetched = client.fetch_message(account_id=account.id, message_id=identity)
            raw_content = fetched.get("raw_content") if isinstance(fetched, Mapping) else None
        elif message.provider == "outlook_mcp_graph" and getattr(account, "outlook_credential_ciphertext", None):
            client = outlook_graph_client_for_ciphertext(account.outlook_credential_ciphertext)
            fetched = client.fetch_message(
                external_account_id=getattr(account, "external_account_id", None) or "",
                message_id=identity,
            )
            body = fetched.get("body") if isinstance(fetched, Mapping) else None
            raw_content = body.get("content") if isinstance(body, Mapping) else None
            if not isinstance(raw_content, str) or not raw_content.strip():
                raw_content = (fetched.get("bodyPreview") or fetched.get("body_preview") or "") if isinstance(fetched, Mapping) else ""
        elif message.provider in {"whatsapp_web_baileys", "whatsapp_baileys", "whatsapp"}:
            fetched = HttpWhatsAppAdapterClient().fetch_message(
                channel_account_id=account.id,
                message_id=identity,
            )
            raw_content = fetched.get("raw_content") if isinstance(fetched, Mapping) else None
        else:
            return cached, "provider_refetch_unavailable"

        # An empty/unrecognized provider result is a failed refresh, not a
        # successful blank body: keep the already stored safe message visible.
        if not isinstance(raw_content, str) or not raw_content.strip():
            return cached, "provider_content_empty"
        refreshed = render(raw_content)
        if not refreshed["display_text"].strip():
            return cached, "provider_content_unrenderable"
        # The provider still has the customer's words: this was not a revoke.
        # Persist the recovered body so every other surface stops claiming
        # 「已撤回 / 原文不再可用」.
        if db is not None and needs_body_repair(getattr(message, "raw_content", ""), raw_content):
            _repair_message_body(db, message, raw_content)
        return refreshed, None
    except GmailConfigurationError:
        logger.warning(
            "Gmail content refetch unavailable: provider configuration is missing "
            "message_id=%s external_message_id=%s",
            getattr(message, "id", None),
            identity,
        )
        return cached, "provider_configuration_missing"
    except GmailCredentialError:
        logger.warning(
            "Gmail content refetch unavailable: account credential could not be decrypted "
            "message_id=%s external_message_id=%s",
            getattr(message, "id", None),
            identity,
        )
        return cached, "provider_credentials_unavailable"
    except ProviderAuthorizationFailure:
        # Distinguish an expired/revoked OAuth grant from an unreachable
        # provider so operators know to re-authorize instead of chasing network.
        logger.warning(
            "Provider content refetch unauthorized: provider=%s message_id=%s",
            getattr(message, "provider", None),
            getattr(message, "id", None),
        )
        return cached, "provider_authorization_failed"
    except WhatsAppAdapterUnavailableError:
        # The bridge session may be down or its cache cold, but the inbound
        # snapshot was persisted at ingestion. Replaying it is a successful
        # retrieval of the stored original, not a content error.
        return cached, "persisted_snapshot_replayed"
    except (
        OutlookGraphError,
        ProviderPermanentFailure,
        ProviderRateLimited,
        ProviderTemporaryFailure,
        WhatsAppAdapterConfigurationError,
        httpx.HTTPError,
        OSError,
        ValueError,
    ) as exc:
        logger.warning(
            "Provider content refetch failed: provider=%s message_id=%s "
            "external_message_id=%s error=%s",
            getattr(message, "provider", None),
            getattr(message, "id", None),
            identity,
            type(exc).__name__,
        )
        return cached, "provider_refetch_failed"


@router.get("/messages/{message_id}/content")
def get_message_content(
    message_id: int,
    user: Annotated[User, Depends(current_user)],
    db: Session = Depends(get_db),
) -> dict[str, object]:
    """Return the authoritative original text to an authorized operating user.

    Admin inquiry access is summary-only; this direct body endpoint must not
    turn the UI's hidden message-body controls into a bypass.
    """
    if user.role == "admin":
        raise deny()
    # Scope must be resolved before selecting a provider or attempting a fetch.
    message = get_scoped_message(db, user, message_id)
    content, refetch_diagnostic = _safe_provider_content(
        message,
        full=True,
        allow_provider_refetch=user.role in {"staff", "operations", "ops"},
        # A successful refetch of a real body heals a stale 撤回 snapshot.
        db=db if user.role in {"staff", "operations", "ops"} else None,
    )
    lines = content["display_text"].splitlines()
    preview = "\n".join(lines[:8])
    snapshot_at = message.created_at or message.occurred_at
    return {
        "message_id": message.id,
        "channel_type": message.channel_account.channel_type,
        "provider": message.provider,
        "external_message_id": message.external_message_id,
        "direction": message.direction,
        "occurred_at": message.occurred_at,
        "source": {
            "kind": "provider_refetch" if refetch_diagnostic is None else "cached_safe_text",
            "provider": message.provider,
            "external_message_id": message.external_message_id,
            "live_refetch": refetch_diagnostic is None,
            "fallback_reason": refetch_diagnostic,
            "authoritative": True,
            "refetch_status": "refreshed" if refetch_diagnostic is None else "snapshot",
            "snapshot_at": snapshot_at.isoformat() if snapshot_at is not None else None,
        },
        "raw_content_exposed": False,
        # 撤回消息没有可回读的正文；前端据此显示「已撤回」而不是英文占位符。
        "content_state": content["content_state"],
        "parsed_content": content,
        "preview_text": preview,
        "full_text": content["display_text"],
        "can_expand": preview != content["display_text"],
        "attachments": [_attachment_view(attachment) for attachment in message.attachments],
    }


@router.get("/messages/{message_id}/provider-action")
def get_message_provider_action(
    message_id: int,
    user: Annotated[User, Depends(current_user)],
    db: Session = Depends(get_db),
) -> dict[str, object]:
    if user.role in {"admin", "sales", "engineering", "procurement", "production"}:
        raise deny()
    message = get_scoped_message(db, user, message_id)
    account = message.channel_account
    base = {
        "supported": False,
        "channel_type": account.channel_type,
        "action": "none",
        "url": None,
        "web_url": None,
        "reason": "当前消息没有可验证的渠道处理入口",
    }
    if account.status in {"blocked", "system_error"}:
        base["reason"] = "当前渠道账号不可用"
        return base
    if account.channel_type == "gmail" and message.external_message_id.strip():
        # The message ID is provider-issued and stored under the authorized
        # account. No token, OAuth state, or client secret is placed in URL.
        url = f"https://mail.google.com/mail/u/0/#all/{quote(message.external_message_id, safe='')}"
        return {
            "supported": True,
            "channel_type": "gmail",
            "action": "open_message",
            "url": url,
            "web_url": url,
            "reason": None,
        }
    if account.channel_type == "outlook":
        link = outlook_web_link(message.provider_web_link)
        if link is None:
            link = _resolve_outlook_web_link(db, message, account)
        if link is not None:
            return {
                "supported": True,
                "channel_type": "outlook",
                "action": "open_message",
                "url": link,
                "web_url": link,
                "reason": None,
            }
        # No per-message link is available. Open the mailbox that can actually
        # serve this account instead of a host that forces a Microsoft sign-in.
        personal = outlook_account_is_personal(
            external_account_id=account.external_account_id,
        )
        return {
            "supported": True,
            "channel_type": "outlook",
            "action": "open_inbox",
            "url": outlook_inbox_url(personal=personal),
            "web_url": None,
            "reason": "当前邮件没有可用的邮件链接，已打开对应 Outlook 网页收件箱",
        }
    elif account.channel_type == "whatsapp":
        contact = _whatsapp_phone(message.customer_contact)
        if contact is None:
            # Older WhatsApp rows may not have customer_contact populated, but
            # the adapter's scoped external id starts with the remote JID.
            remote_jid = message.external_message_id.split(":", 1)[0].strip()
            contact = _whatsapp_phone(remote_jid)
        if contact is not None:
            return {
                "supported": True,
                "channel_type": "whatsapp",
                "action": "open_chat",
                "url": f"whatsapp://send?phone={quote(contact, safe='')}",
                # WhatsApp Desktop is not installed on every workstation, and
                # a browser cannot report that failure. Keep a web fallback.
                "web_url": f"https://wa.me/{quote(contact, safe='')}",
                "reason": None,
            }
        return {
            "supported": True,
            "channel_type": "whatsapp",
            "action": "open_inbox",
            "url": "whatsapp://",
            "web_url": WHATSAPP_WEB_INBOX,
            "reason": "当前消息没有可验证的客户手机号（群聊或 LID 联系人），已打开 WhatsApp",
        }
    return base


def _inquiry_message_options():
    return (
        selectinload(Inquiry.message_links)
        .selectinload(InquiryMessage.message)
        .selectinload(Message.channel_account),
        selectinload(Inquiry.message_links)
        .selectinload(InquiryMessage.message)
        .selectinload(Message.attachments),
        selectinload(Inquiry.message_links)
        .selectinload(InquiryMessage.message)
        .selectinload(Message.overview),
    )


def _visible_linked_message_ids(db: Session, user: User, inquiry: Inquiry) -> set[int]:
    query = (
        select(InquiryMessage.message_id)
        .join(Message, Message.id == InquiryMessage.message_id)
        .join(ChannelAccount, ChannelAccount.id == Message.channel_account_id)
        .where(
            InquiryMessage.inquiry_id == inquiry.id,
            ChannelAccount.status != "revoked",
            ChannelAccount.history_access_revoked_at.is_(None),
        )
    )
    if user.role == "admin":
        query = query.where(Message.direction == "inbound")
    query = query.where(
        Message.channel_account_id.in_(inquiry_message_account_scope(user)),
        Message.direction == "inbound",
    )
    return set(db.scalars(query).all())


def _inquiry_response(
    db: Session,
    user: User,
    inquiry: Inquiry,
    *,
    visible_message_ids: set[int] | None = None,
    visible_events: list[InquiryEvent] | None = None,
    assignee_labels: dict[int, dict[str, str]] | None = None,
    transfer_labels: dict[int, dict[str, object]] | None = None,
) -> dict[str, object]:
    # Callers that expose/read an Inquiry enforce visibility in their scoped
    # SQL query. A transition may return a still-authorized Inquiry whose
    # associations are partially/fully hidden; serialize only visible messages.
    visible_ids = visible_message_ids if visible_message_ids is not None else _visible_linked_message_ids(db, user, inquiry)
    return _inquiry_view(
        db, user, inquiry,
        visible_message_ids=visible_ids,
        visible_events=visible_events,
        assignee_labels=assignee_labels,
        transfer_labels=transfer_labels,
    )


@router.get("/inquiries")
def list_inquiries(
    user: Annotated[User, Depends(current_user)],
    db: Session = Depends(get_db),
    status: Literal["new", "assigned"] | None = Query(default=None),
    handling_status: Literal["pending", "processed", "ignored"] | None = Query(default=None),
    channel_account_id: int | None = Query(default=None, gt=0),
    sort: Literal["created_at", "updated_at"] = Query(default="updated_at"),
    descending: bool = Query(default=True),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
) -> dict[str, object]:
    visible_message_query = (
        select(InquiryMessage.inquiry_id)
        .join(Message, Message.id == InquiryMessage.message_id)
        .join(ChannelAccount, ChannelAccount.id == Message.channel_account_id)
        .where(
            InquiryMessage.inquiry_id == Inquiry.id,
            Message.channel_account_id.in_(inquiry_message_account_scope(user)),
        )
    )
    visible_message_query = visible_message_query.where(
        ChannelAccount.status != "revoked",
        ChannelAccount.history_access_revoked_at.is_(None),
    )
    visible_message_query = visible_message_query.where(Message.direction == "inbound")
    base_query = scoped_inquiries(user)
    if user.role != "admin":
        base_query = base_query.where(exists(visible_message_query))
    if status is not None:
        base_query = base_query.where(Inquiry.status == status)
    if handling_status is not None:
        base_query = base_query.where(Inquiry.handling_status == handling_status)
    if channel_account_id is not None:
        base_query = base_query.where(
            select(InquiryMessage.inquiry_id)
            .join(Message, Message.id == InquiryMessage.message_id)
            .join(ChannelAccount, ChannelAccount.id == Message.channel_account_id)
            .where(
                InquiryMessage.inquiry_id == Inquiry.id,
                ChannelAccount.status != "revoked",
                ChannelAccount.history_access_revoked_at.is_(None),
                Message.channel_account_id == channel_account_id,
                Message.channel_account_id.in_(inquiry_message_account_scope(user)),
            )
            .exists()
        )
    total_count = db.scalar(select(func.count()).select_from(base_query.subquery())) or 0
    query = base_query.options(
        selectinload(Inquiry.attachments),
        selectinload(Inquiry.events),
        *_inquiry_message_options(),
    )
    sort_column = Inquiry.created_at if sort == "created_at" else Inquiry.updated_at
    ordering = sort_column.desc() if descending else sort_column.asc()
    offset = (page - 1) * page_size
    inquiries = db.scalars(
        query.order_by(ordering, Inquiry.id.desc() if descending else Inquiry.id.asc())
        .offset(offset)
        .limit(page_size + 1)
    ).all()
    has_more = len(inquiries) > page_size
    inquiries = inquiries[:page_size]
    visible_by_inquiry = _batch_visible_message_ids(db, user, [item.id for item in inquiries])
    assignee_labels = _assignee_labels(db, inquiries)
    transfer_labels = _transfer_labels(db, inquiries)
    return {
        "items": [
            _inquiry_response(
                db,
                user,
                inquiry,
                visible_message_ids=visible_by_inquiry.get(inquiry.id, set()),
                visible_events=(
                    _visible_inquiry_events(db, user, inquiry)
                    if user.role == "admin"
                    else _loaded_inquiry_events(
                        inquiry, visible_by_inquiry.get(inquiry.id, set())
                    )
                ),
                assignee_labels=assignee_labels,
                transfer_labels=transfer_labels,
            )
            for inquiry in inquiries
        ],
        "page": page,
        "page_size": page_size,
        "has_more": has_more,
        "total_count": total_count,
    }


@router.get("/inquiries/{inquiry_id}")
def get_inquiry(
    inquiry_id: int,
    user: Annotated[User, Depends(current_user)],
    db: Session = Depends(get_db),
) -> dict[str, object]:
    inquiry = db.scalar(
        scoped_inquiries(user)
        .where(Inquiry.id == inquiry_id)
        .options(
            selectinload(Inquiry.attachments),
            selectinload(Inquiry.events),
            *_inquiry_message_options(),
        )
    )
    if inquiry is None:
        raise HTTPException(status_code=404, detail="没有权限访问")
    visible_message_ids = _visible_linked_message_ids(db, user, inquiry)
    if not visible_message_ids and user.role != "admin":
        raise HTTPException(status_code=404, detail="没有权限访问")
    _heal_recoverable_messages(
        db,
        user,
        [
            link.message
            for link in inquiry.message_links
            if link.message_id in visible_message_ids
        ],
    )
    return _inquiry_response(db, user, inquiry, visible_message_ids=visible_message_ids)


@router.get("/messages/{message_id}/inquiry-candidates")
def list_message_inquiry_candidates(
    message_id: int,
    user: Annotated[User, Depends(current_user)],
    db: Session = Depends(get_db),
) -> dict[str, object]:
    """Return exact-identity candidate inquiries without guessing a link."""
    if user.role not in {"staff", "operations", "ops"}:
        raise deny()
    message = get_scoped_message(db, user, message_id)
    if effective_website_form(message):
        return {"message_id": message.id, "match_state": "unsupported_identity", "items": []}
    if message.inquiry_link is not None:
        linked_inquiry = db.scalar(
            scoped_inquiries(user).where(Inquiry.id == message.inquiry_link.inquiry_id)
        )
        return {
            "message_id": message.id,
            "match_state": "linked",
            "items": ([{"id": linked_inquiry.id}] if linked_inquiry is not None else []),
        }
    contact = message.normalized_customer_contact
    if message.contact_identity_state in {"forwarded", "identity_uncertain", "needs_manual_review"}:
        # Surface reviewable chains instead of an empty panel. Selection is an
        # explicit operator decision; no identity is inferred from message text.
        candidates = _manual_confirmation_candidates(db, message, user)
        return {
            "message_id": message.id,
            "match_state": "manual_confirmation_required",
            "identity_state": message.contact_identity_state,
            "requires_identity_confirmation": True,
            "items": [
                {
                    "id": candidate.id,
                    "status": candidate.status,
                    "handling_status": candidate.handling_status,
                    "customer_contact": candidate.customer_contact,
                    "customer_nickname": candidate.customer_nickname,
                    "contact_identity_kind": candidate.contact_identity_kind,
                    "contact_identity_state": candidate.contact_identity_state,
                }
                for candidate in candidates
            ],
        }
    if message.contact_identity_state != "certain" or not contact:
        return {"message_id": message.id, "match_state": "missing_identity", "items": []}
    channel_type = message.channel_account.channel_type
    if channel_type in {"gmail", "outlook"}:
        identity_kind = "email"
    elif channel_type == "whatsapp":
        identity_kind = "whatsapp_phone"
    else:
        return {"message_id": message.id, "match_state": "unsupported_identity", "items": []}
    if message.contact_identity_state == "unsupported" or not message.normalized_customer_contact:
        return {"message_id": message.id, "match_state": "unsupported_identity", "items": []}

    candidates = _identity_candidate_query(db, message, user)
    if message.link_state == "manual_review" and len(candidates) > 1:
        match_state = "multiple"
    else:
        match_state = "multiple" if len(candidates) > 1 else "unique" if candidates else "none"
    # Candidate inspection is read-only. Persistent link_state is set by
    # ingress or explicit association, never as a side effect of this GET.
    return {
        "message_id": message.id,
        "match_state": match_state,
        "identity_kind": identity_kind,
        "identity_state": message.contact_identity_state,
        "items": [
            {
                "id": candidate.id,
                "status": candidate.status,
                "handling_status": candidate.handling_status,
                "customer_contact": candidate.customer_contact,
                "customer_nickname": candidate.customer_nickname,
            }
            for candidate in candidates
        ],
    }


@router.post("/inquiries/{inquiry_id}/messages")
def link_message_to_inquiry(
    inquiry_id: int,
    body: InquiryMessageLinkBody,
    pair: Annotated[tuple[User, UserSession], Depends(require_csrf)],
    db: Session = Depends(get_db),
) -> dict[str, object]:
    user, _ = pair
    if user.role not in {"staff", "operations", "ops"}:
        raise deny()
    # Authorize the target before inspecting an existing link, so a conflict
    # cannot disclose anything about an inquiry outside the caller's scope.
    inquiry = db.scalar(
        scoped_inquiries(user).where(Inquiry.id == inquiry_id).with_for_update()
        .options(*_inquiry_message_options())
    )
    if inquiry is None:
        raise HTTPException(status_code=403, detail="没有权限访问")
    message = get_scoped_message(db, user, body.message_id, for_update=True)
    if effective_website_form(message):
        raise HTTPException(status_code=409, detail="官网表单提交按独立联系人处理，不能合并到其他客户链路")
    if message.inquiry_link is not None:
        if message.inquiry_link.inquiry_id != inquiry_id:
            # Do not reveal the other linked Inquiry, only that this Message is used.
            raise HTTPException(status_code=409, detail="消息已关联其他询盘")
    target_channel = message.channel_account.channel_type
    expected_kind = "whatsapp" if target_channel == "whatsapp" else "email"
    # Manual identity confirmation: the operator explicitly chose this chain,
    # so its confirmed identity is adopted. Nothing is inferred from message
    # text, and the write is deferred until every validation has passed.
    effective_identity_state = message.contact_identity_state
    effective_identity_kind = message.contact_identity_kind
    effective_contact = message.normalized_customer_contact
    identity_confirmed_by_operator = False
    if body.confirm_identity and effective_identity_state != "certain":
        if inquiry.contact_identity_state != "certain" or not inquiry.normalized_customer_contact:
            raise HTTPException(status_code=409, detail="目标询盘身份未确认，不能用于人工核验")
        if inquiry.contact_identity_kind != expected_kind:
            raise HTTPException(status_code=409, detail="身份类型与渠道不匹配")
        effective_identity_state = "certain"
        effective_identity_kind = expected_kind
        effective_contact = inquiry.normalized_customer_contact
        identity_confirmed_by_operator = True
    if effective_identity_state != "certain" or inquiry.contact_identity_state != "certain":
        raise HTTPException(status_code=409, detail="联系人身份尚未确认，不能建立关联")
    contact = inquiry.normalized_customer_contact
    if effective_identity_kind != inquiry.contact_identity_kind:
        raise HTTPException(status_code=409, detail="身份类型不匹配")
    if not contact or effective_contact != contact:
        raise HTTPException(status_code=409, detail="联系人与询盘不匹配")
    inquiry_channels = db.scalars(
        select(ChannelAccount.channel_type)
        .join(Message, Message.channel_account_id == ChannelAccount.id)
        .join(InquiryMessage, InquiryMessage.message_id == Message.id)
        .where(InquiryMessage.inquiry_id == inquiry.id)
        .distinct()
    ).all()
    source_channels = set(inquiry_channels)
    source_account_ids = set(db.scalars(
        select(Message.channel_account_id)
        .join(InquiryMessage, InquiryMessage.message_id == Message.id)
        .where(InquiryMessage.inquiry_id == inquiry.id)
    ).all())
    if not source_channels:
        source_channels = {inquiry.source_channel_account.channel_type} if inquiry.source_channel_account else set()
        if inquiry.source_channel_account_id is not None:
            source_account_ids.add(inquiry.source_channel_account_id)
    if any(
        not db.scalar(
            select(scoped_channel_account_ids(user).where(ChannelAccount.id == account_id).exists())
        )
        for account_id in source_account_ids
    ):
        raise HTTPException(status_code=403, detail="没有权限访问")
    if target_channel == "whatsapp":
        if effective_identity_kind != "whatsapp" or inquiry.contact_identity_kind != "whatsapp" or source_channels != {"whatsapp"}:
            raise HTTPException(status_code=409, detail="WhatsApp 只能关联同一手机号身份的WhatsApp链路")
    elif target_channel in {"gmail", "outlook"}:
        if effective_identity_kind != "email" or inquiry.contact_identity_kind != "email" or any(channel not in {"gmail", "outlook"} for channel in source_channels):
            raise HTTPException(status_code=409, detail="邮箱消息只能关联同邮箱身份的邮件链路")
    else:
        raise HTTPException(status_code=409, detail="当前渠道不支持 Inquiry 关联")
    if message.inquiry_link is not None:
        if message.inquiry_link.inquiry_id == inquiry.id:
            return _inquiry_response(db, user, inquiry)
        raise HTTPException(status_code=409, detail="消息已关联其他询盘")
    try:
        position = db.scalar(
            select(func.coalesce(func.max(InquiryMessage.position), 0) + 1)
            .where(InquiryMessage.inquiry_id == inquiry.id)
        )
        db.add(
            InquiryMessage(
                inquiry_id=inquiry.id,
                message_id=message.id,
                position=position,
                link_source="manual",
            )
        )
        if identity_confirmed_by_operator:
            message.contact_identity_state = "certain"
            message.contact_identity_kind = effective_identity_kind
            message.normalized_customer_contact = effective_contact
            message.customer_contact = effective_contact
        message.link_state = "linked"
        db.add(
            InquiryEvent(
                inquiry_id=inquiry.id,
                event_type="manual_link" if identity_confirmed_by_operator else "inquiry_message_linked",
                actor_user_id=user.id,
                from_status=inquiry.handling_status,
                to_status=inquiry.handling_status,
                message_id=message.id,
            )
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(inquiry)
    _record_operation(db, user, name="确认客户归属", object_type="message", object_id=message.id)
    return _inquiry_response(db, user, inquiry)


@router.post("/inquiries/{inquiry_id}/action")
def inquiry_action(
    inquiry_id: int,
    body: InquiryActionBody,
    pair: Annotated[tuple[User, UserSession], Depends(require_csrf)],
    db: Session = Depends(get_db),
) -> dict[str, object]:
    user, _ = pair
    action = InquiryAction.COMPLETE if body.action == "processed" else InquiryAction.IGNORE
    inquiry = transition_inquiry(db, user, inquiry_id, action)
    _record_operation(
        db, user,
        name="标记已处理" if body.action == "processed" else "忽略客户链路",
        object_type="inquiry",
        object_id=inquiry.id,
    )
    inquiry = db.scalar(
        scoped_inquiries(user).where(Inquiry.id == inquiry.id)
        .options(selectinload(Inquiry.attachments), selectinload(Inquiry.events), *_inquiry_message_options())
    )
    if inquiry is None:
        return {"id": inquiry_id, "handling_status": action, "messages": [], "timeline": [], "readable": False}
    return _inquiry_response(db, user, inquiry)


@router.post("/inquiries/{inquiry_id}/reactivate")
def reactivate_inquiry(
    inquiry_id: int,
    pair: Annotated[tuple[User, UserSession], Depends(require_csrf)],
    db: Session = Depends(get_db),
) -> dict[str, object]:
    user, _ = pair
    inquiry = transition_inquiry(db, user, inquiry_id, InquiryAction.REACTIVATE)
    _record_operation(
        db, user,
        name="恢复链路",
        object_type="inquiry",
        object_id=inquiry.id,
    )
    inquiry = db.scalar(
        scoped_inquiries(user).where(Inquiry.id == inquiry.id)
        .options(selectinload(Inquiry.attachments), selectinload(Inquiry.events), *_inquiry_message_options())
    )
    if inquiry is None:
        return {"id": inquiry_id, "handling_status": "pending", "messages": [], "timeline": [], "readable": False}
    return _inquiry_response(db, user, inquiry)


@router.post("/messages/{message_id}/overview/retry")
def retry_message_overview(
    message_id: int,
    pair: Annotated[tuple[User, UserSession], Depends(require_csrf)],
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> dict[str, object]:
    user, _ = pair
    manager_retry_authorized = False
    if user.manager_overlay_enabled or user.role == "manager":
        if not user.is_active:
            raise deny()
        authorized_inquiry = (
            select(Inquiry.id)
            .join(InquiryMessage, InquiryMessage.inquiry_id == Inquiry.id)
            .join(
                ManagerPermissionGrant,
                and_(
                    ManagerPermissionGrant.manager_user_id == user.id,
                    ManagerPermissionGrant.department == user.department,
                    ManagerPermissionGrant.target_user_id == Inquiry.assigned_sales_user_id,
                    ManagerPermissionGrant.department == Inquiry.department,
                    ManagerPermissionGrant.permission == "retry",
                ),
            )
            .join(User, User.id == Inquiry.assigned_sales_user_id)
            .join(Message, Message.id == InquiryMessage.message_id)
            .join(ChannelAccount, ChannelAccount.id == Message.channel_account_id)
            .where(
                InquiryMessage.message_id == message_id,
                Inquiry.assigned_sales_user_id.is_not(None),
                User.is_active.is_(True),
                User.department == Inquiry.department,
                Inquiry.department == user.department,
                Inquiry.department.is_not(None),
                User.department.is_not(None),
                ManagerPermissionGrant.department.is_not(None),
                ManagerPermissionGrant.department.is_not(None),
                ChannelAccount.status != "revoked",
                ChannelAccount.history_access_revoked_at.is_(None),
                Message.direction == "inbound",
                Message.handling_status == "pending",
            )
            .limit(1)
        )
        message = db.scalar(
            select(Message)
            .where(
                Message.id == message_id,
                Message.handling_status == "pending",
                Message.overview.has(MessageOverview.status == "failed"),
                exists(authorized_inquiry),
            )
            .with_for_update()
        )
        if message is None:
            # The overlay adds narrowly granted retry scope; it must not replace
            # the base role's existing retry scope.
            try:
                message = get_scoped_message(db, user, message_id, for_update=True)
            except HTTPException:
                raise deny()
            if message.handling_status != "pending" or user.role not in {"admin", "staff", "operations", "ops"}:
                raise deny()
        else:
            manager_retry_authorized = True
    else:
        message = get_scoped_message(db, user, message_id, for_update=True)
        if message.handling_status != "pending":
            raise deny()
        if user.role == "admin" and (message.overview is None or message.overview.status != "failed"):
            raise deny()
        if user.role == "admin" and message.direction != "inbound":
            raise deny()
        if user.role not in {"admin", "staff", "operations", "ops"}:
            raise deny()
    overview = message.overview
    if overview is None:
        overview = MessageOverview(
            message_id=message.id,
            status="pending",
            provider_name=message.provider,
        )
        db.add(overview)
    else:
        overview.retry_count += 1
        overview.status = "pending"
        overview.failure_code = None
        overview.overview_text = None
    db.commit()
    background_tasks.add_task(schedule_message_overview, message.id, actor_user_id=user.id)
    _record_operation(
        db, user,
        name="提交重新生成",
        object_type="message",
        object_id=message.id,
        detail="已提交后台处理",
    )
    if manager_retry_authorized:
        return {"status": "retry_accepted"}
    return _message_view(message, db, user)


@router.post("/messages/{message_id}/archive/restore")
def restore_message(
    message_id: int,
    pair: Annotated[tuple[User, UserSession], Depends(require_csrf)],
    db: Session = Depends(get_db),
) -> dict[str, object]:
    user, _ = pair
    message = get_scoped_message(db, user, message_id, for_update=True)
    if user.role not in {"admin", "staff", "operations", "ops"} or message.handling_status not in {"processed", "ignored"}:
        raise HTTPException(status_code=409, detail="该消息不在可恢复归档范围内")

    now = datetime.now(timezone.utc)
    inquiry = None
    link = message.inquiry_link
    if link is not None:
        # 锁住所属链路并确认它仍在读权限范围内；查不到时优雅跳过，
        # 只恢复消息本身，不向上回写链路状态。
        inquiry = db.scalar(
            scoped_inquiries(user)
            .where(Inquiry.id == link.inquiry_id)
            .with_for_update()
        )
        # 仅在链路确实需要被重新激活时，才要求操作者对该链路全部关联
        # 消息来源账号都有授权，避免借一条可见消息激活含不可见消息的链路。
        if inquiry is not None and inquiry.handling_status in {"processed", "ignored"}:
            if inquiry.last_activity_at is None or (
                datetime.now(timezone.utc) - as_utc(inquiry.last_activity_at)
            ) >= timedelta(days=90):
                raise HTTPException(status_code=409, detail="已到期清理的链路不能恢复")
            if not _operator_has_all_message_scopes(db, user, inquiry.id):
                raise HTTPException(status_code=403, detail="没有权限访问")

    message.handling_status = "pending"
    if inquiry is not None and inquiry.handling_status in {"processed", "ignored"}:
        previous = inquiry.handling_status
        inquiry.handling_status = "pending"
        inquiry.last_activity_at = now
        db.add(
            InquiryEvent(
                inquiry_id=inquiry.id,
                event_type="inquiry_reactivated",
                from_status=previous,
                to_status="pending",
                message_id=message.id,
                actor_user_id=user.id,
                occurred_at=now,
            )
        )
        db.add(
            OperationLog(
                actor_user_id=user.id,
                actor_name=user.username,
                operation_name="恢复链路",
                object_type="inquiry",
                object_id=inquiry.id,
                result="success",
            )
        )
    db.add(
        OperationLog(
            actor_user_id=user.id,
            actor_name=user.username,
            operation_name="恢复消息",
            object_type="message",
            object_id=message.id,
            result="success",
        )
    )
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(message)
    return _message_view(message, db, user)


@router.get("/messages/{message_id}/overview")
def get_message_overview(
    message_id: int,
    user: Annotated[User, Depends(current_user)],
    db: Session = Depends(get_db),
) -> dict[str, object]:
    message = get_scoped_message(db, user, message_id)
    if message.overview is None:
        return {"message_id": message.id, "overview": None}
    return {"message_id": message.id, "overview": _message_view(message, db, user)["overview"]}


@router.post("/messages/{message_id}/action")
def message_action(
    message_id: int,
    body: InquiryActionBody,
    pair: Annotated[tuple[User, UserSession], Depends(require_csrf)],
    db: Session = Depends(get_db),
) -> dict[str, object]:
    user, _ = pair
    if user.role not in {"admin", "staff", "operations", "ops"}:
        raise deny()
    message = get_scoped_message(db, user, message_id, for_update=True)

    if message.handling_status == body.action:
        return _message_view(message, db, user)
    # A delete-for-everyone stub has no recoverable customer body, so it must
    # not be marked 已处理. It can still be 忽略: an operator has to be able to
    # clear a wrongly classified or already-known revoke from the pending queue.
    if is_revoked_content(message.raw_content) and body.action == "processed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="客户已撤回的消息不能标记已处理，可选择忽略",
        )
    if message.inquiry_link is not None:
        if message.inquiry_link.inquiry.handling_status in {"processed", "ignored"}:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="关联询盘已完成处理，不能单独改变消息状态")
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="关联询盘中的消息须通过询盘统一处理")
    if message.handling_status in {"processed", "ignored"}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="该消息已完成处理，不能重复改变终态")
    try:
        message.handling_status = body.action
        if message.overview is not None:
            db.delete(message.overview)
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(message)
    _record_operation(
        db,
        user,
        name="标记已处理" if body.action == "processed" else "忽略消息",
        object_type="message",
        object_id=message.id,
    )
    return _message_view(message, db, user)


@router.post("/messages/bulk-action")
def message_bulk_action(
    body: MessageBulkActionBody,
    pair: Annotated[tuple[User, UserSession], Depends(require_csrf)],
    db: Session = Depends(get_db),
) -> dict[str, object]:
    """Process a whole selection in one request.

    The list view groups unlinked WhatsApp group / contact messages purely for
    display, so before this endpoint existed an operator had to click each row.
    Every row still goes through the same scope, terminal-state and
    linked-inquiry rules as the single-message action. A 撤回 row may be 忽略
    (so it can be cleared from the queue) but never 标记已处理. Linked rows are handled
    through their inquiry (which processes all sibling messages) instead of
    being mutated one by one, matching the existing single-row behaviour.

    A skipped row is reported rather than aborting the batch: a stale selection
    should not prevent the rest of the queue from being cleared.
    """
    user, _ = pair
    if user.role not in {"admin", "staff", "operations", "ops"}:
        raise deny()

    # Preserve caller order and drop duplicates; one row must never be applied twice.
    message_ids = list(dict.fromkeys(body.message_ids))
    if any(message_id <= 0 for message_id in message_ids):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="消息编号无效")

    visible = {
        message.id: message
        for message in db.scalars(
            scoped_messages(user).where(Message.id.in_(message_ids))
        ).all()
    }

    direct: list[Message] = []
    inquiry_ids: list[int] = []
    skipped: list[dict[str, object]] = []

    def skip(message_id: int | None, reason: str, detail: str, **extra: object) -> None:
        skipped.append({"message_id": message_id, "reason": reason, "detail": detail, **extra})

    for message_id in message_ids:
        message = visible.get(message_id)
        if message is None:
            skip(message_id, "not_visible", "消息不在当前授权范围内")
            continue
        if is_revoked_content(message.raw_content) and body.action == "processed":
            skip(message_id, "revoked", "客户已撤回，不能标记已处理；可改用批量忽略")
            continue
        if message.handling_status != "pending":
            skip(message_id, "already_final", "该消息已完成处理，不能重复改变终态")
            continue
        link = message.inquiry_link
        if link is not None:
            if link.inquiry_id not in inquiry_ids:
                inquiry_ids.append(link.inquiry_id)
            continue
        direct.append(message)

    updated_message_ids: list[int] = []
    if direct:
        try:
            for message in direct:
                message.handling_status = body.action
                if message.overview is not None:
                    db.delete(message.overview)
            db.commit()
        except Exception:
            db.rollback()
            raise
        updated_message_ids = [message.id for message in direct]

    # transition_inquiry owns its own transaction and audits the linked chain.
    # Handle inquiries after the direct rows are committed so one rejected
    # chain cannot roll back the rest of a partially valid selection.
    action = InquiryAction.COMPLETE if body.action == "processed" else InquiryAction.IGNORE
    updated_inquiry_ids: list[int] = []
    for inquiry_id in inquiry_ids:
        try:
            transition_inquiry(db, user, inquiry_id, action)
        except HTTPException as exc:
            skip(None, "inquiry_action_failed", str(exc.detail), inquiry_id=inquiry_id)
            continue
        updated_inquiry_ids.append(inquiry_id)

    if updated_message_ids or updated_inquiry_ids:
        _record_operation(
            db,
            user,
            name="批量标记已处理" if body.action == "processed" else "批量忽略消息",
            object_type="message",
            object_id=None,
            detail=f"消息 {len(updated_message_ids)} 条 / 询盘 {len(updated_inquiry_ids)} 条；跳过 {len(skipped)} 项",
        )

    return {
        "action": body.action,
        "updated_message_ids": updated_message_ids,
        "updated_inquiry_ids": updated_inquiry_ids,
        "skipped": skipped,
    }


@router.get("/inquiry-transfer-targets")
def list_inquiry_transfer_targets(
    user: Annotated[User, Depends(current_user)],
    db: Session = Depends(get_db),
) -> list[dict[str, object]]:
    if (
        user.role != "admin"
        and (not can_operate_channels(user) or user.manager_overlay_enabled)
    ):
        raise deny()
    targets = db.scalars(
        select(User)
        .where(User.role == "sales", User.is_active.is_(True))
        .order_by(User.id)
    ).all()
    return [
        {
            "id": target.id,
            "username": target.username,
            "full_name": target.full_name,
            "name": target.full_name or target.username,
            "role": target.role,
        }
        for target in targets
    ]


@router.post("/inquiries/{inquiry_id}/transfer")
def transfer_inquiry(
    inquiry_id: int,
    body: TransferBody,
    pair: Annotated[tuple[User, UserSession], Depends(require_csrf)],
    db: Session = Depends(get_db),
) -> dict[str, object]:
    user, _ = pair
    inquiry = transition_inquiry(
        db,
        user,
        inquiry_id,
        InquiryAction.ASSIGN,
        target_sales_user_id=body.sales_user_id,
        business_type=body.business_type,
    )
    inquiry_id = inquiry.id
    _record_operation(
        db,
        user,
        name="分配客户链路",
        object_type="inquiry",
        object_id=inquiry_id,
        detail=f"业务类型：{'询盘' if body.business_type == 'inquiry' else '售后'}",
    )
    inquiry = db.scalar(
        scoped_inquiries(user).where(Inquiry.id == inquiry_id)
        .options(selectinload(Inquiry.attachments), selectinload(Inquiry.events), *_inquiry_message_options())
    )
    if inquiry is None:
        # A legacy unlinked inquiry may be writable by its source-account scope
        # but is intentionally absent from message-scoped reads.
        return {
            "id": inquiry_id,
            "status": "assigned",
            "assigned_sales_user_id": body.sales_user_id,
            "messages": [],
            "timeline": [],
            "readable": False,
        }
    return _inquiry_response(db, user, inquiry)


@router.get("/notifications/{notification_id}")
def get_notification(
    notification_id: int,
    user: Annotated[User, Depends(current_user)],
    db: Session = Depends(get_db),
) -> dict[str, int | str]:
    notification = get_scoped_notification(db, user, notification_id)
    return {
        "id": notification.id,
        "inquiry_id": notification.inquiry_id,
        "notification_type": notification.notification_type,
        "content": notification.content,
    }


@router.post("/internal-analysis")
def internal_analysis(
    body: InternalAnalysisQuery,
    user: Annotated[User, Depends(current_user)],
    db: Session = Depends(get_db),
) -> dict[str, object]:
    if body.operation != "read":
        guidance_pages = {
            "create": "/inquiries",
            "update": "/inquiries",
            "assign": "/inquiries",
            "delete": "/inquiries",
            "send": "/messages",
        }
        return {
            "mode": "guidance",
            "operation": body.operation,
            "message": "该只读工作台不会执行写操作，请在有权限的业务页面确认后操作。",
            "page": guidance_pages.get(body.operation, "/inquiries"),
            "read_only": True,
        }

    # Every aggregate is built from the same authorization-scoped subqueries
    # used by the inbox. No object is loaded before the scope predicate.
    inquiry_query = scoped_inquiries(user).subquery()
    message_query = scoped_messages(user).subquery()
    account_scope = inquiry_message_account_scope(user) if user.role == "admin" else scoped_channel_account_ids(user)
    pending_messages = db.scalar(
        select(func.count()).select_from(message_query).where(
            message_query.c.status == "received",
            message_query.c.handling_status == "pending",
            message_query.c.direction == "inbound",
        )
    ) or 0
    if user.role == "sales":
        # Sales scope is already restricted to messages linked to assigned
        # inquiries; count those visible Message rows, not inquiry rows.
        pending_messages = db.scalar(
            select(func.count()).select_from(message_query).where(
                message_query.c.handling_status == "pending",
                message_query.c.direction == "inbound",
            )
        ) or 0
    status_rows = db.execute(
        select(inquiry_query.c.status, func.count())
        .select_from(inquiry_query)
        .group_by(inquiry_query.c.status)
        .order_by(inquiry_query.c.status)
    ).all()
    handling_status_rows = db.execute(
        select(inquiry_query.c.handling_status, func.count())
        .select_from(inquiry_query)
        .group_by(inquiry_query.c.handling_status)
        .order_by(inquiry_query.c.handling_status)
    ).all()
    assigned_rows = db.execute(
        select(
            inquiry_query.c.id,
            inquiry_query.c.status,
            inquiry_query.c.assigned_sales_user_id,
            inquiry_query.c.updated_at,
        )
        .select_from(inquiry_query)
        .where(inquiry_query.c.assigned_sales_user_id == user.id)
        .order_by(inquiry_query.c.updated_at.desc(), inquiry_query.c.id)
    ).mappings().all()
    assigned_ids = [row["id"] for row in assigned_rows]
    recent_events = {}
    if assigned_ids:
        assigned_inquiries = db.scalars(
            scoped_inquiries(user)
            .where(Inquiry.id.in_(assigned_ids))
            .options(selectinload(Inquiry.message_links), selectinload(Inquiry.events))
        ).all()
        assigned_visible = _batch_visible_message_ids(db, user, [item.id for item in assigned_inquiries])
        recent_events = {
            assigned_inquiry.id: visible_events[-1]
            for assigned_inquiry in assigned_inquiries
            if (visible_events := _loaded_inquiry_events(
                assigned_inquiry, assigned_visible.get(assigned_inquiry.id, set())
            ))
        }
    lifecycle_rows = db.execute(
        select(inquiry_query.c.id, inquiry_query.c.last_activity_at)
        .select_from(inquiry_query)
    ).all()
    lifecycle_counts = {"unknown": 0, "active": 0, "archived_silent": 0, "purge_due": 0}
    now = datetime.now(timezone.utc)
    for row in lifecycle_rows:
        if row.last_activity_at is None:
            stage = "unknown"
        else:
            elapsed = now - as_utc(row.last_activity_at)

            stage = "purge_due" if elapsed >= timedelta(days=90) else "archived_silent" if elapsed >= timedelta(days=30) else "active"
        lifecycle_counts[stage] += 1

    link_state_rows = db.execute(
        select(Message.link_state, func.count())
        .where(Message.id.in_(select(message_query.c.id)))
        .group_by(Message.link_state)
        .order_by(Message.link_state)
    ).all()
    linked_message_count = db.scalar(
        select(func.count())
        .select_from(InquiryMessage)
        .join(Message, Message.id == InquiryMessage.message_id)
        .where(Message.id.in_(select(message_query.c.id)))
    ) or 0
    link_state_counts = {
        state: next((count for row_state, count in link_state_rows if row_state == state), 0)
        for state in ("pending", "linked", "unmatched", "manual_review", "not_linkable")
    }
    identity_state_rows = db.execute(
        select(Message.contact_identity_state, func.count())
        .where(Message.id.in_(select(message_query.c.id)))
        .group_by(Message.contact_identity_state)
    ).all()
    identity_state_counts = {
        state: next((count for row_state, count in identity_state_rows if row_state == state), 0)
        for state in ("certain", "forwarded", "identity_uncertain", "needs_manual_review", "unsupported")
    }
    link_state_counts["linked"] = max(link_state_counts["linked"], linked_message_count)

    unlinked_query = (
        select(Message.id, Message.channel_account_id, Message.provider, Message.external_message_id, Message.contact_identity_state, Message.link_state, Message.occurred_at)
        .where(
            Message.id.in_(select(message_query.c.id)),
            ~exists(select(InquiryMessage.message_id).where(InquiryMessage.message_id == Message.id)),
            Message.direction == "inbound",
            Message.handling_status == "pending",
            Message.link_state == "unmatched",
        )
        .order_by(Message.occurred_at.desc(), Message.id.desc())
        .limit(100)
    )
    unlinked_rows = db.execute(unlinked_query).mappings().all()

    contact_group_query = (
        select(Message.normalized_customer_contact)
        .where(
            Message.id.in_(select(message_query.c.id)),
            Message.handling_status == "pending",
            Message.direction == "inbound",
            Message.normalized_customer_contact.is_not(None),
            Message.contact_identity_state == "certain",
        )
        .group_by(Message.normalized_customer_contact)
        .subquery()
    )
    pending_contact_count = db.scalar(select(func.count()).select_from(contact_group_query)) or 0
    pending_message_total = db.scalar(
        select(func.count()).select_from(message_query).where(
            message_query.c.handling_status == "pending",
            message_query.c.direction == "inbound",
        )
    ) or 0
    manual_review_rows = db.execute(
        select(Message.id, Message.provider, Message.external_message_id, Message.link_state, Message.contact_identity_state, Message.occurred_at)
        .where(
            Message.id.in_(select(message_query.c.id)),
            Message.direction == "inbound",
            or_(
                Message.link_state == "manual_review",
                Message.contact_identity_state.in_(("forwarded", "identity_uncertain", "needs_manual_review")),
            ),
        )
        .order_by(Message.occurred_at.desc(), Message.id.desc())
        .limit(100)
    ).mappings().all()
    event_inquiry_ids = db.scalars(select(inquiry_query.c.id)).all()
    visible_events = []
    if event_inquiry_ids:
        visible_inquiries = db.scalars(
            scoped_inquiries(user)
            .where(Inquiry.id.in_(event_inquiry_ids))
            .options(selectinload(Inquiry.message_links), selectinload(Inquiry.events))
        ).all()
        visible_by_inquiry = _batch_visible_message_ids(db, user, [item.id for item in visible_inquiries])
        event_map = {
            inquiry.id: _loaded_inquiry_events(
                inquiry, visible_by_inquiry.get(inquiry.id, set())
            )
            for inquiry in visible_inquiries
        }
        visible_events = [
            {
                "inquiry_id": inquiry_id,
                "event_type": event.event_type,
                "occurred_at": event.occurred_at,
                "actor_user_id": event.actor_user_id,
            }
            for inquiry_id, events in event_map.items()
            for event in events[-3:]
        ]
        visible_events.sort(key=lambda event: event["occurred_at"], reverse=True)
        visible_events = visible_events[:100]

    account_rows = db.execute(
        select(ChannelAccount.id, ChannelAccount.channel_type, ChannelAccount.status)
        .where(ChannelAccount.id.in_(account_scope))
        .order_by(ChannelAccount.id)
    ).mappings().all()

    return {
        "mode": "read_only",
        "read_only": True,
        "generated_at": now,
        "mutation_performed": False,
        "write_operations_performed": 0,
        "query_scope": (
            "company_wide_inquiry_inspection"
            if user.role == "admin"
            else "current_user_authorized_objects"
        ),
        "test_only": "来源模型未声明；请以当前 fixture/test_only 环境标记解释",
        "stage_source": "inquiries.status",
        "event_source": "inquiry_events" if recent_events else "inquiries.updated_at",
        "event_history_available": bool(recent_events),
        "actor_id": user.id,
        "pending_message_count": pending_messages,
        "pending_inbound_message_count": pending_message_total,
        "pending_contact_count": pending_contact_count,
        "inquiries_by_lifecycle_stage": lifecycle_counts,
        "messages_by_link_state": {
            state: link_state_counts[state]
            for state in ("pending", "linked", "unmatched", "manual_review", "not_linkable")
        },
        "messages_by_identity_state": identity_state_counts,
        "unlinked_messages": [
            {
                "id": row["id"],
                **({} if user.role == "admin" else {
                    "channel_account_id": row["channel_account_id"],
                    "provider": row["provider"],
                    "external_message_id": row["external_message_id"],
                }),
                "identity_state": row["contact_identity_state"],
                "link_state": row["link_state"],
                "occurred_at": row["occurred_at"],
            }
            for row in unlinked_rows
        ],
        "messages_needing_manual_review": [
            {
                "id": row["id"],
                **({} if user.role == "admin" else {
                    "provider": row["provider"],
                    "external_message_id": row["external_message_id"],
                }),
                "link_state": row["link_state"],
                "identity_state": row["contact_identity_state"],
                "occurred_at": row["occurred_at"],
            }
            for row in manual_review_rows
        ],
        "recent_events": visible_events,
        "actions": [
            {"operation": "create", "page": "/inquiries", "label": "创建/查看询盘"},
            {"operation": "assign", "page": "/inquiries", "label": "分配或转交"},
            {"operation": "update", "page": "/inquiries", "label": "处理或恢复链路"},
            {"operation": "send", "page": "/messages", "label": "仅由运营在消息页面主动发送"},
        ],
        "inquiries_by_status": {
            status: next(
                (count for row_status, count in status_rows if str(row_status) == status),
                0,
            )
            for status in INQUIRY_STATUSES
        },
        "inquiries_by_handling_status": {
            handling_status: next(
                (
                    count
                    for row_status, count in handling_status_rows
                    if str(row_status) == handling_status
                ),
                0,
            )
            for handling_status in INQUIRY_HANDLING_STATUSES
        },
        "my_transfers": [
            {
                "inquiry_id": row["id"],
                "status": row["status"],
                "assigned_sales_user_id": row["assigned_sales_user_id"],
                "updated_at": row["updated_at"],
                "current_stage": row["status"],
                "recent_event": (
                    {
                        "type": recent_events[row["id"]].event_type,
                        "occurred_at": recent_events[row["id"]].occurred_at,
                        "source": "inquiry_events",
                        "event_history_available": True,
                    }
                    if row["id"] in recent_events
                    else (
                        {
                            "type": "last_known_update",
                            "occurred_at": row["updated_at"],
                            "source": "inquiries.updated_at",
                            "event_history_available": False,
                        }
                        if row["updated_at"] is not None
                        else None
                    )
                ),
            }
            for row in assigned_rows
        ],
        "channel_statuses": [
            {
                **({} if user.role == "admin" else {"channel_account_id": row["id"]}),
                "channel_type": row["channel_type"],
                "status": row["status"],
                "is_abnormal": row["status"] in {"blocked", "error", "revoked", "not_connected"},
            }
            for row in account_rows
        ],
    }


@router.post("/internal-ai/query")
def internal_ai_query(
    body: InternalAIQuery,
    user: Annotated[User, Depends(current_user)],
    db: Session = Depends(get_db),
) -> dict[str, object]:
    validate_read_query(body.query)
    if body.operation != "read":
        return {
            "mode": "guidance",
            "read_only": True,
            "message": "该操作不会由内部 AI 执行，请在对应业务页面确认后提交。",
            "page": f"/{body.query}",
        }
    if user.role == "admin" and body.query != "inquiries":
        raise HTTPException(status_code=403, detail="没有权限访问")

    if body.query == "channel_accounts":
        result = db.scalars(
            select(ChannelAccount)
            .where(ChannelAccount.id.in_(scoped_channel_account_ids(user)))
            .order_by(ChannelAccount.id)
        ).all()
        data = [_account_view(account) for account in result]
    elif body.query == "inquiries":
        result = db.scalars(
            scoped_inquiries(user)
            .options(
                selectinload(Inquiry.attachments),
                selectinload(Inquiry.events),
                *_inquiry_message_options(),
            )
            .order_by(Inquiry.id)
        ).all()
        visible_by_inquiry = _batch_visible_message_ids(db, user, [item.id for item in result])
        data = [
            _inquiry_response(
                db,
                user,
                inquiry,
                visible_message_ids=visible_by_inquiry.get(inquiry.id, set()),
                visible_events=(
                    _visible_inquiry_events(db, user, inquiry)
                    if user.role == "admin"
                    else _loaded_inquiry_events(
                        inquiry, visible_by_inquiry.get(inquiry.id, set())
                    )
                ),
            )
            for inquiry in result
        ]
    else:
        notification_scope = (
            select(InternalNotification)
            .join(Inquiry, InternalNotification.inquiry_id == Inquiry.id)
            .where(Inquiry.assigned_sales_user_id == user.id)
        )
        if user.role == "sales":
            notification_scope = notification_scope.where(
                Inquiry.id.in_(scoped_inquiries(user).with_only_columns(Inquiry.id)),
                exists(
                    select(InquiryMessage.message_id)
                    .select_from(InquiryMessage)
                    .join(Message, Message.id == InquiryMessage.message_id)
                    .join(ChannelAccount, ChannelAccount.id == Message.channel_account_id)
                    .where(
                        InquiryMessage.inquiry_id == Inquiry.id,
                        ChannelAccount.status != "revoked",
                        ChannelAccount.history_access_revoked_at.is_(None),
                    )
                    .correlate(Inquiry)
                )
            )
        else:
            notification_scope = notification_scope.where(
                exists(
                    select(InquiryMessage.message_id)
                    .select_from(InquiryMessage)
                    .join(Message, Message.id == InquiryMessage.message_id)
                    .where(
                        InquiryMessage.inquiry_id == Inquiry.id,
                        Message.channel_account_id.in_(inquiry_message_account_scope(user)),
                    )
                    .correlate(Inquiry)
                )
            )
        result = db.scalars(notification_scope.order_by(InternalNotification.id)).all()
        data = [
            {
                "id": notification.id,
                "inquiry_id": notification.inquiry_id,
                "notification_type": notification.notification_type,
                "content": notification.content,
            }
            for notification in result
        ]

    return {
        "mode": "read_only",
        "read_only": True,
        "query": body.query,
        "message": "查询结果已按当前登录用户权限过滤。",
        "page": f"/{body.query}",
        "actor_id": user.id,
        "data": data,
    }
