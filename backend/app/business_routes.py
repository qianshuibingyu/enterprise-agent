from typing import Annotated, Literal
import re
from urllib.parse import quote

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.auth import current_user, require_csrf
from app.content_security import content_view, legacy_contact_view
from app.authorization import (
    can_transfer_inquiry,
    get_scoped_inquiry,
    get_scoped_message,
    get_scoped_notification,
    scoped_channel_account_ids,
    scoped_inquiries,
    scoped_messages,
    validate_read_query,
)
from app.database import get_db
from app.gmail_client import GmailApiClient, GmailConfigurationError
from app.gmail_credentials import GmailCredentialError, decrypt_refresh_token
from app.models.business import (
    ChannelAccount,
    Inquiry,
    InquiryEvent,
    InternalNotification,
    Message,
)
from app.models.overview import MessageOverview
from app.overview_service import ensure_message_overview, schedule_message_overview
from app.outlook_graph import OutlookGraphError, outlook_graph_client_for_ciphertext
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
from app.models.user import User, UserSession

router = APIRouter(prefix="/api", tags=["business"])

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


class InquiryActionBody(BaseModel):
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


def _inquiry_view(inquiry: Inquiry) -> dict[str, object]:
    return {
        "id": inquiry.id,
        "customer_contact": inquiry.customer_contact,
        "customer_nickname": inquiry.customer_nickname,
        **content_view(inquiry.raw_message),
        "source_channel_account_id": inquiry.source_channel_account_id,
        "status": inquiry.status,
        "handling_status": inquiry.handling_status,
        "assigned_sales_user_id": inquiry.assigned_sales_user_id,
        "created_at": inquiry.created_at,
        "updated_at": inquiry.updated_at,
        "timeline": [_event_view(event) for event in sorted(
            inquiry.events,
            key=lambda event: (event.occurred_at, event.id),
        )],
        "timeline_complete": bool(inquiry.events),
        "attachments": [_attachment_view(attachment) for attachment in inquiry.attachments],
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


def _message_view(message: Message) -> dict[str, object]:
    account = message.channel_account
    contact = message.customer_contact
    nickname = message.customer_nickname
    if not contact and not nickname:
        contact, nickname = legacy_contact_view(message.raw_content, message.provider)
    return {
        "id": message.id,
        "channel_account_id": message.channel_account_id,
        "channel_type": account.channel_type,
        "provider": message.provider,
        "external_message_id": message.external_message_id,
        "customer_contact": contact,
        "customer_nickname": nickname,
        "direction": message.direction,
        "ingestion_status": message.status,
        "handling_status": message.handling_status,
        "occurred_at": message.occurred_at,
        "created_at": message.created_at,
        **content_view(message.raw_content),
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
            if message.overview is not None
            else None
        ),
        "attachments": [_attachment_view(attachment) for attachment in message.attachments],
    }


@router.get("/channel-accounts")
def list_channel_accounts(
    user: Annotated[User, Depends(current_user)],
    db: Session = Depends(get_db),
) -> list[dict[str, int | str]]:
    accounts = db.scalars(
        select(ChannelAccount)
        .where(ChannelAccount.id.in_(scoped_channel_account_ids(user)))
        .order_by(ChannelAccount.id)
    ).all()
    return [_account_view(account) for account in accounts]


@router.get("/messages")
def list_messages(
    user: Annotated[User, Depends(current_user)],
    db: Session = Depends(get_db),
    handling_status: Literal["pending", "processed", "ignored"] | None = Query(default="pending"),
    ingestion_status: Literal["received", "processed", "failed"] | None = Query(default=None),
    channel_account_id: int | None = Query(default=None, gt=0),
    sort: Literal["occurred_at", "created_at"] = Query(default="occurred_at"),
    descending: bool = Query(default=True),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
) -> dict[str, object]:
    query = scoped_messages(user)
    if handling_status is not None:
        query = query.where(Message.handling_status == handling_status)
    if ingestion_status is not None:
        query = query.where(Message.status == ingestion_status)
    if channel_account_id is not None:
        query = query.where(Message.channel_account_id == channel_account_id)
    sort_column = Message.occurred_at if sort == "occurred_at" else Message.created_at
    ordering = sort_column.desc() if descending else sort_column.asc()
    offset = (page - 1) * page_size
    messages = db.scalars(
        query.options(
            selectinload(Message.channel_account),
            selectinload(Message.attachments),
            selectinload(Message.overview),
        )
        .order_by(ordering, Message.id.desc() if descending else Message.id.asc())
        .offset(offset)
        .limit(page_size)
    ).all()
    return {
        "items": [_message_view(message) for message in messages],
        "page": page,
        "page_size": page_size,
        "has_more": len(messages) == page_size,
    }


@router.get("/messages/{message_id}")
def get_message(
    message_id: int,
    user: Annotated[User, Depends(current_user)],
    db: Session = Depends(get_db),
) -> dict[str, object]:
    message = get_scoped_message(db, user, message_id)
    # The response intentionally contains only source/account and ingestion
    # fields; inquiry linkage is not modeled yet.
    return _message_view(message)


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


def _safe_provider_content(message: Message) -> tuple[dict[str, object], str | None]:
    """Try a server-side provider refresh without exposing provider payloads."""
    account = message.channel_account
    identity = message.external_message_id.strip()
    if not identity:
        return content_view(message.raw_content), "provider_message_id_missing"

    try:
        if message.provider == "gmail_api_pubsub" and account.gmail_credential_ciphertext:
            client = GmailApiClient(
                refresh_token=decrypt_refresh_token(account.gmail_credential_ciphertext)
            )
            fetched = client.fetch_message(account_id=account.id, message_id=identity)
            return content_view(fetched.get("raw_content")), None
        if message.provider == "outlook_mcp_graph" and account.outlook_credential_ciphertext:
            client = outlook_graph_client_for_ciphertext(account.outlook_credential_ciphertext)
            fetched = client.fetch_message(
                external_account_id=account.external_account_id or "",
                message_id=identity,
            )
            body = fetched.get("body")
            raw_content = body.get("content") if isinstance(body, dict) else None
            if not isinstance(raw_content, str):
                raw_content = fetched.get("bodyPreview") or fetched.get("body_preview") or ""
            return content_view(raw_content), None
        if message.provider == "whatsapp_web_baileys":
            fetched = HttpWhatsAppAdapterClient().fetch_message(
                channel_account_id=account.id,
                message_id=identity,
            )
            return content_view(fetched.get("raw_content")), None
        return content_view(message.raw_content), "provider_refetch_unavailable"
    except (
        GmailConfigurationError,
        GmailCredentialError,
        OutlookGraphError,
        ProviderAuthorizationFailure,
        ProviderPermanentFailure,
        ProviderRateLimited,
        ProviderTemporaryFailure,
        WhatsAppAdapterConfigurationError,
        WhatsAppAdapterUnavailableError,
        httpx.HTTPError,
        OSError,
        ValueError,
    ):
        return content_view(message.raw_content), "provider_refetch_failed"


@router.get("/messages/{message_id}/content")
def get_message_content(
    message_id: int,
    user: Annotated[User, Depends(current_user)],
    db: Session = Depends(get_db),
) -> dict[str, object]:
    """Return authorized provider content with safe cached fallback."""
    # Scope must be resolved before selecting a provider or attempting a fetch.
    message = get_scoped_message(db, user, message_id)
    content, refetch_error = _safe_provider_content(message)
    lines = content["display_text"].splitlines()
    preview = "\\n".join(lines[:3])
    return {
        "message_id": message.id,
        "channel_type": message.channel_account.channel_type,
        "provider": message.provider,
        "external_message_id": message.external_message_id,
        "direction": message.direction,
        "occurred_at": message.occurred_at,
        "source": {
            "kind": "provider_refetch" if refetch_error is None else "cached_safe_text",
            "provider": message.provider,
            "external_message_id": message.external_message_id,
            "live_refetch": refetch_error is None,
            "fallback_reason": refetch_error,
        },
        "raw_content_exposed": False,
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
    query = scoped_inquiries(user)
    if status is not None:
        query = query.where(Inquiry.status == status)
    if handling_status is not None:
        query = query.where(Inquiry.handling_status == handling_status)
    if channel_account_id is not None:
        query = query.where(Inquiry.source_channel_account_id == channel_account_id)
    sort_column = Inquiry.created_at if sort == "created_at" else Inquiry.updated_at
    ordering = sort_column.desc() if descending else sort_column.asc()
    offset = (page - 1) * page_size
    inquiries = db.scalars(
        query.options(
            selectinload(Inquiry.attachments),
            selectinload(Inquiry.events),
        ).order_by(ordering, Inquiry.id.desc() if descending else Inquiry.id.asc())
        .offset(offset)
        .limit(page_size)
    ).all()
    return {
        "items": [_inquiry_view(inquiry) for inquiry in inquiries],
        "page": page,
        "page_size": page_size,
        "has_more": len(inquiries) == page_size,
    }


@router.get("/inquiries/{inquiry_id}")
def get_inquiry(
    inquiry_id: int,
    user: Annotated[User, Depends(current_user)],
    db: Session = Depends(get_db),
) -> dict[str, object]:
    inquiry = get_scoped_inquiry(db, user, inquiry_id)
    return _inquiry_view(inquiry)


@router.post("/inquiries/{inquiry_id}/action")
def inquiry_action(
    inquiry_id: int,
    body: InquiryActionBody,
    pair: Annotated[tuple[User, UserSession], Depends(require_csrf)],
    db: Session = Depends(get_db),
) -> dict[str, object]:
    user, _ = pair
    inquiry = get_scoped_inquiry(db, user, inquiry_id, for_update=True)
    if user.role == "sales":
        raise HTTPException(status_code=403, detail="没有权限访问")
    if inquiry.handling_status == body.action:
        return _inquiry_view(inquiry)
    if inquiry.handling_status in {"processed", "ignored"}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="该询盘已完成处理，不能重复改变终态")
    previous_handling_status = inquiry.handling_status
    event_type = f"inquiry_{body.action}"
    try:
        inquiry.handling_status = body.action
        db.add(
            InquiryEvent(
                inquiry_id=inquiry.id,
                event_type=event_type,
                actor_user_id=user.id,
                from_status=previous_handling_status,
                to_status=body.action,
            )
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(inquiry)
    return _inquiry_view(inquiry)


@router.post("/messages/{message_id}/overview/retry")
def retry_message_overview(
    message_id: int,
    pair: Annotated[tuple[User, UserSession], Depends(require_csrf)],
    db: Session = Depends(get_db),
) -> dict[str, object]:
    user, _ = pair
    message = get_scoped_message(db, user, message_id, for_update=True)
    if user.role == "sales" or message.handling_status != "pending":
        raise HTTPException(status_code=409, detail="该消息不在待处理范围内")
    ensure_message_overview(db, message, force=True)
    db.commit()
    return _message_view(message)


@router.post("/messages/{message_id}/archive/restore")
def restore_message(
    message_id: int,
    pair: Annotated[tuple[User, UserSession], Depends(require_csrf)],
    db: Session = Depends(get_db),
) -> dict[str, object]:
    user, _ = pair
    message = get_scoped_message(db, user, message_id, for_update=True)
    if user.role == "sales" or message.handling_status not in {"processed", "ignored"}:
        raise HTTPException(status_code=409, detail="该消息不在可恢复归档范围内")
    message.handling_status = "pending"
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(message)
    return _message_view(message)


@router.get("/messages/{message_id}/overview")
def get_message_overview(
    message_id: int,
    user: Annotated[User, Depends(current_user)],
    db: Session = Depends(get_db),
) -> dict[str, object]:
    message = get_scoped_message(db, user, message_id)
    if message.overview is None:
        return {"message_id": message.id, "overview": None}
    return {"message_id": message.id, "overview": _message_view(message)["overview"]}


@router.post("/messages/{message_id}/action")
def message_action(
    message_id: int,
    body: InquiryActionBody,
    pair: Annotated[tuple[User, UserSession], Depends(require_csrf)],
    db: Session = Depends(get_db),
) -> dict[str, object]:
    user, _ = pair
    message = get_scoped_message(db, user, message_id, for_update=True)
    if user.role == "sales":
        raise HTTPException(status_code=403, detail="没有权限访问")

    if message.handling_status == body.action:
        return _message_view(message)
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
    return _message_view(message)


@router.get("/inquiry-transfer-targets")
def list_inquiry_transfer_targets(
    user: Annotated[User, Depends(current_user)],
    db: Session = Depends(get_db),
) -> list[dict[str, int | str]]:
    if user.role == "sales":
        raise HTTPException(status_code=403, detail="没有权限访问")
    targets = db.scalars(
        select(User)
        .where(User.role == "sales", User.is_active.is_(True))
        .order_by(User.id)
    ).all()
    return [
        {"id": target.id, "username": target.username, "role": target.role}
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
    if user.role == "sales":
        raise HTTPException(status_code=403, detail="没有权限访问")

    inquiry = get_scoped_inquiry(db, user, inquiry_id, for_update=True)
    sales_user = db.scalar(
        select(User).where(
            User.id == body.sales_user_id,
            User.role == "sales",
            User.is_active.is_(True),
        )
    )
    if sales_user is None:
        raise HTTPException(status_code=403, detail="没有权限访问")

    if inquiry.status == "assigned" and inquiry.assigned_sales_user_id == body.sales_user_id:
        return _inquiry_view(inquiry)
    if not can_transfer_inquiry(db, user, inquiry) or inquiry.status != "new":
        raise HTTPException(status_code=403, detail="没有权限访问")

    previous_status = inquiry.status
    try:
        inquiry.assigned_sales_user_id = sales_user.id
        inquiry.status = "assigned"
        db.add(
            InternalNotification(
                inquiry_id=inquiry.id,
                notification_type="inquiry_assigned",
                content=f"新的客户询盘已转交给你，业务链路编号为 {inquiry.id}。",
            )
        )
        db.add(
            InquiryEvent(
                inquiry_id=inquiry.id,
                event_type="inquiry_transferred",
                actor_user_id=user.id,
                from_status=previous_status,
                to_status=inquiry.status,
                target_user_id=sales_user.id,
            )
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(inquiry)
    return _inquiry_view(inquiry)


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
        return {
            "mode": "guidance",
            "message": "该操作不会由内部分析执行，请在对应业务页面确认后提交。",
            "page": "/inquiries",
            "read_only": True,
        }

    # Every aggregate is built from the same authorization-scoped subqueries
    # used by the inbox. No object is loaded before the scope predicate.
    inquiry_query = scoped_inquiries(user).subquery()
    message_query = scoped_messages(user).subquery()
    account_scope = scoped_channel_account_ids(user)

    pending_messages = db.scalar(
        select(func.count()).select_from(message_query).where(
            message_query.c.status == "received",
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
            inquiry_query.c.customer_nickname,
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
        event_rows = db.scalars(
            select(InquiryEvent)
            .where(InquiryEvent.inquiry_id.in_(assigned_ids))
            .order_by(InquiryEvent.occurred_at.desc(), InquiryEvent.id.desc())
        ).all()
        recent_events = {
            event.inquiry_id: event
            for event in reversed(event_rows)
        }
    account_rows = db.execute(
        select(ChannelAccount.id, ChannelAccount.channel_type, ChannelAccount.status)
        .where(ChannelAccount.id.in_(account_scope))
        .order_by(ChannelAccount.id)
    ).mappings().all()

    return {
        "mode": "read_only",
        "read_only": True,
        "test_only": "来源模型未声明；请以当前 fixture/test_only 环境标记解释",
        "stage_source": "inquiries.status",
        "event_source": "inquiry_events" if recent_events else "inquiries.updated_at",
        "event_history_available": bool(recent_events),
        "actor_id": user.id,
        "pending_message_count": pending_messages,
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
                "customer_nickname": row["customer_nickname"],
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
                "channel_account_id": row["id"],
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
            .options(selectinload(Inquiry.attachments), selectinload(Inquiry.events))
            .order_by(Inquiry.id)
        ).all()
        data = [_inquiry_view(inquiry) for inquiry in result]
    else:
        result = db.scalars(
            select(InternalNotification)
            .join(Inquiry, InternalNotification.inquiry_id == Inquiry.id)
            .join(ChannelAccount, ChannelAccount.id == Inquiry.source_channel_account_id)
            .where(
                Inquiry.assigned_sales_user_id == user.id,
                ChannelAccount.status != "revoked",
            )
            .order_by(InternalNotification.id)
        ).all()
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
