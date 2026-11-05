from typing import Literal

from fastapi import HTTPException
from sqlalchemy import Select, and_, exists, false, select
from sqlalchemy.orm import Session

from app.models.business import ChannelAccount, ChannelGrant, Inquiry, InternalNotification, Message
from app.models.user import User

DENIED_DETAIL = "没有权限访问"


def deny() -> HTTPException:
    return HTTPException(status_code=403, detail=DENIED_DETAIL)


def scoped_channel_account_ids(user: User) -> Select:
    """Return an authorization-scoped account-id query before loading any account."""
    return select(ChannelAccount.id).join(
        ChannelGrant,
        and_(
            ChannelGrant.channel_account_id == ChannelAccount.id,
            ChannelGrant.channel_type == ChannelAccount.channel_type,
            ChannelGrant.owner_user_id == ChannelAccount.owner_user_id,
            ChannelGrant.owner_user_id == user.id,
        ),
    ).where(
        ChannelAccount.owner_user_id == user.id,
        ChannelAccount.status != "revoked",
    )


def scoped_inquiries(user: User) -> Select:
    """Build a query whose predicates enforce the caller's object scope."""
    channel_scope = scoped_channel_account_ids(user)
    if user.role == "sales":
        return (
            select(Inquiry)
            .join(ChannelAccount, ChannelAccount.id == Inquiry.source_channel_account_id)
            .where(
                Inquiry.assigned_sales_user_id == user.id,
                ChannelAccount.status != "revoked",
            )
        )
    return select(Inquiry).where(Inquiry.source_channel_account_id.in_(channel_scope))


def scoped_messages(user: User) -> Select:
    """Build a message query scoped through the caller's authorized accounts."""
    channel_scope = scoped_channel_account_ids(user)
    if user.role == "sales":
        # Message has no inquiry/conversation foreign key yet. Do not infer
        # message visibility from an account-level inquiry assignment.
        return select(Message).where(false())
    return select(Message).where(Message.channel_account_id.in_(channel_scope))


def get_scoped_message(
    db: Session,
    user: User,
    message_id: int,
    *,
    for_update: bool = False,
) -> Message:
    query = scoped_messages(user).where(Message.id == message_id)
    if for_update:
        query = query.with_for_update()
    message = db.scalar(query)
    if message is None:
        raise deny()
    return message


def get_scoped_inquiry(
    db: Session,
    user: User,
    inquiry_id: int,
    *,
    for_update: bool = False,
) -> Inquiry:
    query = scoped_inquiries(user).where(Inquiry.id == inquiry_id)
    if for_update:
        query = query.with_for_update()
    inquiry = db.scalar(query)
    if inquiry is None:
        raise deny()
    return inquiry


def get_scoped_notification(db: Session, user: User, notification_id: int) -> InternalNotification:
    notification = db.scalar(
        select(InternalNotification)
        .join(Inquiry, InternalNotification.inquiry_id == Inquiry.id)
        .join(ChannelAccount, ChannelAccount.id == Inquiry.source_channel_account_id)
        .where(
            InternalNotification.id == notification_id,
            Inquiry.assigned_sales_user_id == user.id,
            ChannelAccount.status != "revoked",
        )
    )
    if notification is None:
        raise deny()
    return notification


def can_access_channel_account(db: Session, user: User, account_id: int) -> bool:
    return db.scalar(
        select(exists(scoped_channel_account_ids(user).where(ChannelAccount.id == account_id)))
    )


def can_transfer_inquiry(db: Session, user: User, inquiry: Inquiry) -> bool:
    return db.scalar(
        select(exists(scoped_channel_account_ids(user).where(
            ChannelAccount.id == inquiry.source_channel_account_id
        )))
    )


def validate_read_query(query: Literal["channel_accounts", "inquiries", "notifications"]) -> None:
    if query not in {"channel_accounts", "inquiries", "notifications"}:
        raise deny()
