"""Authorized Inquiry state transitions and lifecycle projection."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from enum import StrEnum

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.authorization import deny, scoped_channel_account_ids, scoped_inquiries
from app.models.business import ChannelAccount, Inquiry, InquiryEvent, InquiryMessage, InternalNotification, Message
from app.models.user import User

ARCHIVE_AFTER = timedelta(days=30)
DELETE_AFTER = timedelta(days=90)


class InquiryAction(StrEnum):
    ASSIGN = "assign"
    COMPLETE = "processed"
    IGNORE = "ignored"
    REACTIVATE = "reactivate"


def as_utc(value: datetime) -> datetime:
    """Normalize database timestamps from dialects that drop timezone info."""
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def lifecycle_stage(inquiry: Inquiry, *, now: datetime | None = None) -> str:
    """Project the confirmed 30/90-day lifecycle without deleting or mutating."""
    if inquiry.last_activity_at is None:
        return "unknown"
    now = now or datetime.now(timezone.utc)
    elapsed = now - as_utc(inquiry.last_activity_at)
    if elapsed >= DELETE_AFTER:

        return "purge_due"
    if elapsed >= ARCHIVE_AFTER:
        return "archived_silent"
    return "active"


def _operator_has_all_message_scopes(db: Session, user: User, inquiry_id: int) -> bool:
    account_ids = db.scalars(
        select(Message.channel_account_id)
        .join(InquiryMessage, InquiryMessage.message_id == Message.id)
        .where(InquiryMessage.inquiry_id == inquiry_id)
    ).all()
    if not account_ids:
        inquiry_source = db.scalar(select(Inquiry.source_channel_account_id).where(Inquiry.id == inquiry_id))
        if inquiry_source is None:
            return False
        account_ids = [inquiry_source]
    return all(
        db.scalar(
            select(
                scoped_channel_account_ids(user)
                .where(ChannelAccount.id == account_id)
                .exists()
            )
        )
        for account_id in set(account_ids)
    )


def transition_inquiry(
    db: Session,
    user: User,
    inquiry_id: int,
    action: InquiryAction,
    *,
    target_sales_user_id: int | None = None,
    business_type: str | None = None,
    now: datetime | None = None,
) -> Inquiry:
    """Authorize first, lock the inquiry, then atomically transition and audit."""
    if user.role == "sales":
        raise HTTPException(status_code=403, detail="没有权限访问")

    # Query predicates enforce caller scope before loading or locking the object.
    inquiry = db.scalar(
        scoped_inquiries(user)
        .where(Inquiry.id == inquiry_id)
        .with_for_update()
    )
    if inquiry is None:
        # Compatibility for pre-association inquiries: permit an action only
        # when their source account is in scope. Read routes remain message-scoped.
        source_query = (
            select(Inquiry)
            .where(
                Inquiry.id == inquiry_id,
                Inquiry.source_channel_account_id.in_(scoped_channel_account_ids(user)),
            )
            .with_for_update()
        )
        if user.role == "sales":
            source_query = select(Inquiry).where(
                Inquiry.id == inquiry_id,
                Inquiry.assigned_sales_user_id == user.id,
            ).with_for_update()
        inquiry = db.scalar(source_query)
    if inquiry is None:
        raise deny()

    # Only actions that mutate every linked source message require grants for
    # every source account. Inquiry-only transitions use the Inquiry scope above.
    if action in {InquiryAction.COMPLETE, InquiryAction.IGNORE}:
        linked_message_count = db.scalar(
            select(func.count())
            .select_from(InquiryMessage)
            .where(InquiryMessage.inquiry_id == inquiry.id)
        ) or 0
        if linked_message_count and not _operator_has_all_message_scopes(db, user, inquiry.id):
            raise HTTPException(status_code=403, detail="没有权限访问")

    now = now or datetime.now(timezone.utc)
    action_value = action.value
    current = inquiry.handling_status

    # Exact retries are idempotent and must not append another event.
    if action_value == current:
        if action is InquiryAction.ASSIGN and target_sales_user_id == inquiry.assigned_sales_user_id:
            return inquiry
        if action in {InquiryAction.COMPLETE, InquiryAction.IGNORE, InquiryAction.REACTIVATE}:
            return inquiry
        raise HTTPException(status_code=409, detail="该动作已提交且目标状态不一致")
    if current in {"processed", "ignored"} and action not in {InquiryAction.REACTIVATE}:
        raise HTTPException(status_code=409, detail="当前链路已处理；请先恢复链路或等待新消息")

    previous = current
    event_type: str
    event_target: int | None = None
    try:
        if action is InquiryAction.ASSIGN:
            if target_sales_user_id == inquiry.assigned_sales_user_id and inquiry.status == "assigned":
                return inquiry
            if inquiry.status != "new":
                raise HTTPException(status_code=403, detail="询盘已分配给其他业务员")
            if target_sales_user_id is None:
                raise HTTPException(status_code=422, detail="必须指定业务员")
            if business_type not in {"inquiry", "after_sales"}:
                raise HTTPException(status_code=422, detail="必须指定业务类型")
            from app.models.user import User as UserModel

            target = db.scalar(
                select(UserModel).where(
                    UserModel.id == target_sales_user_id,
                    UserModel.role == "sales",
                    UserModel.is_active.is_(True),
                )
            )
            if target is None:
                raise HTTPException(status_code=403, detail="没有权限访问")
            inquiry.assigned_sales_user_id = target.id
            inquiry.business_type = business_type
            inquiry.status = "assigned"
            event_type = "inquiry_transferred"
            event_target = target.id
        elif action is InquiryAction.COMPLETE:
            if current != "pending":
                raise HTTPException(status_code=409, detail="仅待处理链路可标记已处理")
            inquiry.handling_status = "processed"
            _process_linked_messages(db, inquiry.id)
            event_type = "inquiry_processed"
        elif action is InquiryAction.IGNORE:
            if current != "pending":
                raise HTTPException(status_code=409, detail="仅待处理链路可忽略")
            inquiry.handling_status = "ignored"
            _process_linked_messages(db, inquiry.id, handling_status="ignored")
            event_type = "inquiry_ignored"
        elif action is InquiryAction.REACTIVATE:
            if current not in {"processed", "ignored"}:
                raise HTTPException(status_code=409, detail="当前链路无需恢复")
            if inquiry.last_activity_at is None:
                raise HTTPException(status_code=409, detail="该链路期限未知，不能按静默期规则恢复")
            elapsed = now - as_utc(inquiry.last_activity_at)
            if elapsed >= DELETE_AFTER:
                raise HTTPException(status_code=409, detail="已到期清理的链路不能恢复")
            inquiry.handling_status = "pending"
            event_type = "inquiry_reactivated"
        else:
            raise HTTPException(status_code=422, detail="不支持的链路动作")

        inquiry.last_activity_at = now
        if action is InquiryAction.ASSIGN:
            from app.models.business import InternalNotification

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
                event_type=event_type,
                actor_user_id=user.id,
                from_status=previous,
                to_status=inquiry.handling_status,
                target_user_id=event_target,
                occurred_at=now,
            )
        )
        db.flush()
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(inquiry)
    return inquiry


def _process_linked_messages(db: Session, inquiry_id: int, handling_status: str = "processed") -> None:
    messages = db.scalars(
        select(Message)
        .join(InquiryMessage, InquiryMessage.message_id == Message.id)
        .where(InquiryMessage.inquiry_id == inquiry_id)
        .with_for_update()
    ).all()
    for message in messages:
        if message.handling_status == "pending":
            message.handling_status = handling_status
            if message.overview is not None:
                db.delete(message.overview)
