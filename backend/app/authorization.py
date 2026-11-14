from typing import Literal

from fastapi import HTTPException
from sqlalchemy import Select, and_, exists, literal, or_, select
from sqlalchemy.orm import Session

from app.models.business import ChannelAccount, ChannelGrant, Inquiry, InquiryMessage, InternalNotification, Message
from app.models.user import User
from app.models.permissions import UserChannelPreauthorization, UserDepartmentGrant

DENIED_DETAIL = "没有权限访问"

# These are the only roles whose reads are department-authorized.  Their
# department is an identity boundary, not a write capability.  The registry
# of department names remains data-owned; validation therefore rejects only
# missing/blank values and does not invent a canonical list.
DEPARTMENT_READ_ROLES = {"engineering", "procurement", "production"}


UNASSIGNED_DEPARTMENT = "unassigned"


def has_department_identity(user: User) -> bool:
    """Return whether an account has a real, usable assigned department identity."""
    return bool(
        user.department
        and user.department.strip()
        and user.department.strip().casefold() != UNASSIGNED_DEPARTMENT
    )


def sales_has_department(user: User) -> bool:
    """Sales accounts need a real department identity before reading customer data."""
    return has_department_identity(user)


def department_read_scope(user: User):
    """Department values this reader may inspect, including explicit grants."""
    if user.role not in DEPARTMENT_READ_ROLES or not has_department_identity(user):
        return select(UserDepartmentGrant.department).where(False)
    return select(UserDepartmentGrant.department).where(
        UserDepartmentGrant.user_id == user.id
    ).union(select(literal(user.department)))


def deny() -> HTTPException:
    return HTTPException(status_code=403, detail=DENIED_DETAIL)


def scoped_channel_account_ids(user: User) -> Select:
    """Return an authorization-scoped account-id query before loading any account.

    Channel preauthorization is an admin grant that gates *connecting* a new
    channel (see ``has_channel_preauthorization`` / ``require_channel_preauthorization``).
    It is deliberately not a filter here: accounts created before the 0019 grant
    table (and their messages, inquiries and attachments) must stay readable for
    their owner. Read scope is still bounded by the operating role, account
    ownership, the matching ChannelGrant, and the revoked/history-revoked flags.
    An admin can withdraw the ability to connect new channels without silently
    hiding business history that was already collected under an owned account.
    """
    if user.role not in {"staff", "operations", "ops"}:
        return select(ChannelAccount.id).where(False)
    query = select(ChannelAccount.id).join(
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
        ChannelAccount.history_access_revoked_at.is_(None),
    )
    return query


def inspection_channel_account_ids():
    """Company-wide account scope for passive administrator inspection only."""
    return select(ChannelAccount.id)


def channel_onboarding_account_ids(user: User) -> Select:
    """Account scope for *connecting* channels, never for reading messages.

    An administrator may connect a channel on their own behalf and then hand
    the account to an operator who cannot complete OAuth/pairing themselves.
    Their onboarding scope is strictly the accounts they own. All message read
    and handling paths keep using ``scoped_channel_account_ids``, which returns
    an empty scope for admins, so this does not re-open the "two accounts handle
    the same inbox" conflict.
    """
    if user.role == "admin":
        return select(ChannelAccount.id).where(
            ChannelAccount.owner_user_id == user.id,
            ChannelAccount.status != "revoked",
            ChannelAccount.history_access_revoked_at.is_(None),
        )
    return scoped_channel_account_ids(user)


def can_connect_channels(user: User) -> bool:
    """Channel onboarding is available to operators and administrators."""
    return user.role == "admin" or can_operate_channels(user)


def read_channel_account_ids(user: User) -> Select:
    if user.role == "admin":
        # The personal "接入账号" page is about the signed-in account's own
        # connections. Company-wide inspection is served by the dedicated
        # /auth/admin/channel-accounts endpoint and by the inquiry read scope.
        return select(ChannelAccount.id).where(ChannelAccount.owner_user_id == user.id)
    return scoped_channel_account_ids(user)


def has_channel_preauthorization(db: Session, user: User, channel_type: str) -> bool:
    return db.scalar(select(exists().where(
        UserChannelPreauthorization.user_id == user.id,
        UserChannelPreauthorization.channel_type == channel_type,
    ))) is True


def can_operate_channels(user: User) -> bool:
    return user.role in {"staff", "operations", "ops"}


def can_read_inquiry(user: User, inquiry: Inquiry) -> bool:
    """Check department identity without widening customer/message exposure.

    Unmapped resources are deny-by-default for non-admins.  Explicit
    UserDepartmentGrant rows permit cross-department scope; callers that need
    a database predicate should use ``department_read_scope``.
    """
    if user.role == "admin":
        return True
    if not has_department_identity(user) or not inquiry.department or not inquiry.department.strip():
        return False
    if user.department == inquiry.department:
        return True
    # This object-level helper cannot safely consult the database.  Cross-
    # department grants are enforced by scoped SQL queries.
    return False


def scoped_inquiries(user: User) -> Select:
    """Build inquiry read scope; operation permission is checked separately."""
    if user.role == "admin":
        return select(Inquiry)
    if user.role in {"engineering", "procurement", "production"}:
        # Current inquiry records contain customer contact and message-linked
        # identity data, not a separately scoped department work-record view.
        return select(Inquiry).where(False)
    if user.role == "sales":
        visible_sources = (
            select(InquiryMessage.inquiry_id)
            .join(Message, Message.id == InquiryMessage.message_id)
            .join(ChannelAccount, ChannelAccount.id == Message.channel_account_id)
            .where(
                InquiryMessage.inquiry_id == Inquiry.id,
                Message.direction == "inbound",
                ChannelAccount.status != "revoked",
                ChannelAccount.history_access_revoked_at.is_(None),
            )
        )
        query = select(Inquiry).where(
            Inquiry.assigned_sales_user_id == user.id,
            exists(visible_sources),
        )
        # 业务员的范围由「负责人是我」决定：链路是否标注部门只用于运营/管理侧归口，
        # 不能反过来让被转交的人看不到刚转给自己的客户。无部门身份的业务员仍按
        # deny-by-default 处理（与工程/采购/生产一致）。
        if not sales_has_department(user):
            return query.where(False)
        return query
    visible_message = (
        select(InquiryMessage.inquiry_id)
        .join(Message, Message.id == InquiryMessage.message_id)
        .join(ChannelAccount, ChannelAccount.id == Message.channel_account_id)
        .where(
            InquiryMessage.inquiry_id == Inquiry.id,
            Message.direction == "inbound",
        )
    )
    visible_message = visible_message.where(
        Message.channel_account_id.in_(scoped_channel_account_ids(user))
    )
    query = select(Inquiry).where(exists(visible_message))
    grants = select(UserDepartmentGrant.department).where(UserDepartmentGrant.user_id == user.id)
    return query.where(and_(Inquiry.department.is_not(None), or_(Inquiry.department == user.department, Inquiry.department.in_(grants))))


def inquiry_message_account_scope(user: User) -> Select:
    if user.role == "admin":
        return inspection_channel_account_ids()
    if user.role == "sales":
        if not sales_has_department(user):
            return select(Message.channel_account_id).where(False)
        return (
            select(Message.channel_account_id)
            .join(InquiryMessage, InquiryMessage.message_id == Message.id)
            .join(Inquiry, Inquiry.id == InquiryMessage.inquiry_id)
            .join(ChannelAccount, ChannelAccount.id == Message.channel_account_id)
            .where(
                Inquiry.assigned_sales_user_id == user.id,
                Message.direction == "inbound",
                ChannelAccount.status != "revoked",
                ChannelAccount.history_access_revoked_at.is_(None),
            )
        )
    return scoped_channel_account_ids(user)


def scoped_messages(user: User) -> Select:
    """Build a role-scoped message query; admins get company-wide handling access."""
    if user.role == "admin":
        return select(Message).join(
            ChannelAccount, ChannelAccount.id == Message.channel_account_id
        ).where(
            ChannelAccount.status != "revoked",
            ChannelAccount.history_access_revoked_at.is_(None),
            Message.direction == "inbound",
        )
    channel_scope = scoped_channel_account_ids(user)
    if user.role in {"engineering", "procurement", "production"}:
        return select(Message).where(False)
    if user.role == "sales":
        # Sales read only the messages of inquiries assigned to them (§3.2);
        # the inquiry's department annotation must not hide their own customer.
        if not sales_has_department(user):
            return select(Message).where(False)
        return (
            select(Message)
            .join(InquiryMessage, InquiryMessage.message_id == Message.id)
            .join(Inquiry, Inquiry.id == InquiryMessage.inquiry_id)
            .join(ChannelAccount, ChannelAccount.id == Message.channel_account_id)
            .where(
                Inquiry.assigned_sales_user_id == user.id,
                Message.direction == "inbound",
                ChannelAccount.status != "revoked",
                ChannelAccount.history_access_revoked_at.is_(None),
            )
        )
    visible_department_grants = select(UserDepartmentGrant.department).where(
        UserDepartmentGrant.user_id == user.id
    )
    visible_linked_inquiry = exists(
        select(InquiryMessage.inquiry_id)
        .join(Inquiry, Inquiry.id == InquiryMessage.inquiry_id)
        .where(
            InquiryMessage.message_id == Message.id,
            and_(
                Inquiry.department.is_not(None),
                or_(
                    Inquiry.department == user.department,
                    Inquiry.department.in_(visible_department_grants),
                ),
            ),
        )
    )
    has_inquiry_link = exists(
        select(InquiryMessage.inquiry_id).where(InquiryMessage.message_id == Message.id)
    )
    return select(Message).where(
        Message.channel_account_id.in_(channel_scope),
        Message.direction == "inbound",
        or_(~has_inquiry_link, visible_linked_inquiry),
    )


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
    department_scope = (
        or_(
            Inquiry.department.is_(None),
            Inquiry.department == user.department,
            Inquiry.department.in_(select(UserDepartmentGrant.department).where(UserDepartmentGrant.user_id == user.id)),
        )
        if user.role == "admin"
        else and_(
            Inquiry.department.is_not(None),
            or_(
                Inquiry.department == user.department,
                Inquiry.department.in_(select(UserDepartmentGrant.department).where(UserDepartmentGrant.user_id == user.id)),
            ),
        )
    )
    notification = db.scalar(
        select(InternalNotification)
        .join(Inquiry, InternalNotification.inquiry_id == Inquiry.id)
        .where(
            InternalNotification.id == notification_id,
            Inquiry.assigned_sales_user_id == user.id,
            department_scope,
            exists(
                select(InquiryMessage.inquiry_id)
                .join(Message, Message.id == InquiryMessage.message_id)
                .join(ChannelAccount, ChannelAccount.id == Message.channel_account_id)
                .where(
                    InquiryMessage.inquiry_id == Inquiry.id,
                    ChannelAccount.status != "revoked",
                    ChannelAccount.history_access_revoked_at.is_(None),
                )
            ),
        )
    )
    if notification is None:
        raise deny()
    return notification


def can_access_channel_account(db: Session, user: User, account_id: int) -> bool:
    return db.scalar(
        select(exists(scoped_channel_account_ids(user).where(ChannelAccount.id == account_id)))
    )


def has_capability(db: Session, user: User, capability: str) -> bool:
    from app.models.permissions import UserCapabilityGrant

    return db.scalar(select(exists().where(
        UserCapabilityGrant.user_id == user.id,
        UserCapabilityGrant.capability == capability,
    ))) is True


def can_transfer_inquiry(db: Session, user: User, inquiry: Inquiry) -> bool:
    return db.scalar(select(exists(scoped_inquiries(user).where(Inquiry.id == inquiry.id))))


def validate_read_query(query: Literal["channel_accounts", "inquiries", "notifications"]) -> None:
    if query not in {"channel_accounts", "inquiries", "notifications"}:
        raise deny()
