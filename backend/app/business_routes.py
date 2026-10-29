from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.auth import current_user, require_csrf
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
from app.models.business import (
    ChannelAccount,
    Inquiry,
    InquiryEvent,
    InternalNotification,
    Message,
)
from app.models.user import User, UserSession

router = APIRouter(prefix="/api", tags=["business"])

INQUIRY_STATUSES = ("new", "assigned")
INQUIRY_HANDLING_STATUSES = ("pending", "processed", "ignored")


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
        "raw_message": inquiry.raw_message,
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
    return {
        "id": message.id,
        "channel_account_id": message.channel_account_id,
        "channel_type": account.channel_type,
        "provider": message.provider,
        "external_message_id": message.external_message_id,
        "direction": message.direction,
        "ingestion_status": message.status,
        "handling_status": message.handling_status,
        "occurred_at": message.occurred_at,
        "created_at": message.created_at,
        "raw_content": message.raw_content,
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
) -> list[dict[str, object]]:
    messages = db.scalars(
        scoped_messages(user)
        .options(selectinload(Message.channel_account), selectinload(Message.attachments))
        .order_by(Message.occurred_at, Message.id)
    ).all()
    return [_message_view(message) for message in messages]


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


@router.get("/inquiries")
def list_inquiries(
    user: Annotated[User, Depends(current_user)],
    db: Session = Depends(get_db),
) -> list[dict[str, object]]:
    inquiries = db.scalars(
        scoped_inquiries(user).options(
            selectinload(Inquiry.attachments),
            selectinload(Inquiry.events),
        ).order_by(Inquiry.id)
    ).all()
    return [_inquiry_view(inquiry) for inquiry in inquiries]


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
    inquiry = get_scoped_inquiry(db, user, inquiry_id)
    if user.role == "sales":
        raise HTTPException(status_code=403, detail="没有权限访问")
    if inquiry.handling_status == body.action:
        return _inquiry_view(inquiry)
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


@router.post("/messages/{message_id}/action")
def message_action(
    message_id: int,
    body: InquiryActionBody,
    pair: Annotated[tuple[User, UserSession], Depends(require_csrf)],
    db: Session = Depends(get_db),
) -> dict[str, object]:
    user, _ = pair
    message = get_scoped_message(db, user, message_id)
    if user.role == "sales":
        raise HTTPException(status_code=403, detail="没有权限访问")

    if message.handling_status == body.action:
        return _message_view(message)
    try:
        message.handling_status = body.action
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
            .where(Inquiry.assigned_sales_user_id == user.id)
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
