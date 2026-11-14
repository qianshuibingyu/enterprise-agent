"""Operator-managed WhatsApp group -> customer phone bindings.

These endpoints are deliberately isolated from the automatic inquiry-linking
pipeline. They only ever READ messages (to list already-known phone numbers and
to prove a group is visible to the caller) and WRITE the
``whatsapp_group_bindings`` table plus an ``OperationLog``.

Hard rule: nothing here calls ingest_message / ingest_provider_message /
_link_inbound_message_to_inquiry / link_message_to_inquiry / transition_inquiry,
and nothing INSERTs/UPDATEs/DELETEs messages, inquiries, inquiry_messages or
inquiry_events. Phone normalization is used only to validate the operator's
input into E.164 before storing it; it is never used to match an Inquiry.
"""

from datetime import datetime, timezone
import re
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.auth import current_user, require_csrf
from app.authorization import can_operate_channels, scoped_channel_account_ids
from app.business_routes import _record_operation
from app.contact_identity import normalize_whatsapp
from app.database import get_db
from app.models.business import ChannelAccount, Message, WhatsAppGroupBinding
from app.models.user import User, UserSession

router = APIRouter(prefix="/api", tags=["whatsapp-group-bindings"])

# Group JIDs look like 120363000000000000@g.us, optionally with a "-<digits>" suffix.
GROUP_JID_RE = re.compile(r"^[0-9][0-9-]{3,40}@g\.us$")
E164_RE = re.compile(r"^\+\d{7,15}$")
DENIED = "没有权限访问"


class BindingBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    group_jid: str = Field(max_length=255)
    phone: str = Field(max_length=64)
    note: str | None = Field(default=None, max_length=255)


def _require_whatsapp_operator(db: Session, user: User) -> None:
    if user.role == "admin" or not can_operate_channels(user):
        raise HTTPException(status_code=403, detail=DENIED)
    # Group bindings are scoped by the operator's owned channel accounts below;
    # the admin preauthorization grant only gates creating a new channel shell.


def _iso(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _binding_view(db: Session, binding: WhatsAppGroupBinding) -> dict[str, object]:
    bound_by = None
    if binding.bound_by_user_id is not None:
        bound_by = db.scalar(select(User.username).where(User.id == binding.bound_by_user_id))
    return {
        "id": binding.id,
        "group_jid": binding.group_jid,
        "normalized_phone": binding.normalized_phone,
        "raw_phone": binding.raw_phone,
        "channel_account_id": binding.channel_account_id,
        "bound_by": bound_by,
        "note": binding.note,
        "created_at": _iso(binding.created_at),
        "updated_at": _iso(binding.updated_at),
    }


@router.get("/whatsapp-group-bindings")
def list_bindings(
    user: Annotated[User, Depends(current_user)],
    db: Session = Depends(get_db),
) -> list[dict[str, object]]:
    _require_whatsapp_operator(db, user)
    scope = scoped_channel_account_ids(user)
    bindings = db.scalars(
        select(WhatsAppGroupBinding)
        .where(WhatsAppGroupBinding.channel_account_id.in_(scope))
        .order_by(WhatsAppGroupBinding.id)
    ).all()
    return [_binding_view(db, binding) for binding in bindings]


@router.get("/whatsapp-phone-candidates")
def list_phone_candidates(
    user: Annotated[User, Depends(current_user)],
    db: Session = Depends(get_db),
) -> list[dict[str, object]]:
    _require_whatsapp_operator(db, user)
    # Pure read-only enumeration of customer phone numbers already obtained on
    # the caller's authorized WhatsApp accounts. This is ONLY a picker list for
    # a human to choose from: it performs no inference of "which group belongs
    # to which customer" and no automatic inquiry linking whatsoever.
    rows = db.execute(
        select(
            Message.normalized_customer_contact.label("normalized_phone"),
            func.max(Message.customer_contact).label("customer_contact"),
            func.max(Message.customer_nickname).label("customer_nickname"),
            func.max(Message.channel_account_id).label("channel_account_id"),
            func.max(Message.occurred_at).label("last_seen_at"),
            func.count(Message.id).label("message_count"),
        )
        .join(ChannelAccount, ChannelAccount.id == Message.channel_account_id)
        .where(
            ChannelAccount.channel_type == "whatsapp",
            ChannelAccount.status != "revoked",
            ChannelAccount.history_access_revoked_at.is_(None),
            Message.normalized_customer_contact.is_not(None),
            Message.normalized_customer_contact != "",
            Message.contact_identity_state == "certain",
            Message.channel_account_id.in_(scoped_channel_account_ids(user)),
        )
        .group_by(Message.normalized_customer_contact)
        .order_by(func.max(Message.occurred_at).desc())
        .limit(200)
    ).all()
    return [
        {
            "normalized_phone": row.normalized_phone,
            "customer_contact": row.customer_contact,
            "customer_nickname": row.customer_nickname,
            "channel_account_id": row.channel_account_id,
            "last_seen_at": _iso(row.last_seen_at),
            "message_count": row.message_count,
        }
        for row in rows
    ]


@router.post("/whatsapp-group-bindings")
def upsert_binding(
    body: BindingBody,
    pair: Annotated[tuple[User, UserSession], Depends(require_csrf)],
    db: Session = Depends(get_db),
) -> dict[str, object]:
    user, _ = pair
    _require_whatsapp_operator(db, user)

    group_jid = body.group_jid.strip()
    if not GROUP_JID_RE.fullmatch(group_jid):
        raise HTTPException(
            status_code=400,
            detail="群 JID 格式不正确，应为形如 120363000000000000@g.us 的 WhatsApp 群 JID",
        )

    # normalize_whatsapp is used ONLY for format validation here; the E.164
    # result is stored on the binding. No Inquiry/Message matching is performed.
    identity = normalize_whatsapp(body.phone)
    normalized = identity.normalized
    if (
        identity.state != "certain"
        or not normalized
        or not normalized.startswith("+")
        or not E164_RE.fullmatch(normalized)
    ):
        raise HTTPException(status_code=400, detail="请输入带地区码的手机号，例如 +8613800138000")

    # Prove the group actually exists and is visible to this operator. We only
    # locate messages by their external id prefix; contact/link columns are
    # neither read nor modified. Group rows have normalized contacts = NULL.
    message = db.scalar(
        select(Message)
        .where(
            or_(
                Message.external_message_id.like(f"{group_jid}:%"),
                Message.external_message_id.like(f"{group_jid}%"),
            ),
            Message.channel_account_id.in_(scoped_channel_account_ids(user)),
        )
        .order_by(Message.id)
    )
    if message is None:
        raise HTTPException(status_code=404, detail="未找到该群在授权范围内的消息，无法绑定")

    binding = db.scalar(
        select(WhatsAppGroupBinding).where(WhatsAppGroupBinding.group_jid == group_jid)
    )
    is_rebind = binding is not None
    # Legacy rows without an account cannot be safely attributed to an
    # operator, so they remain inaccessible until an explicit migration path.
    if is_rebind:
        if binding.channel_account_id is None:
            raise HTTPException(status_code=403, detail=DENIED)
        allowed_ids = set(db.scalars(scoped_channel_account_ids(user)).all())
        if binding.channel_account_id not in allowed_ids:
            raise HTTPException(status_code=403, detail=DENIED)
    if binding is None:
        binding = WhatsAppGroupBinding(
            group_jid=group_jid,
            channel_account_id=message.channel_account_id,
            normalized_phone=normalized,
            raw_phone=body.phone,
            bound_by_user_id=user.id,
            note=body.note,
        )
        db.add(binding)
    else:
        # Rebind in place: never hit the unique constraint, never create a
        # second row for the same group JID. The original channel_account_id
        # (the account that first made the group visible) is preserved.
        binding.normalized_phone = normalized
        binding.raw_phone = body.phone
        binding.bound_by_user_id = user.id
        binding.note = body.note
        binding.updated_at = datetime.now(timezone.utc)

    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(binding)
    _record_operation(
        db,
        user,
        name="改绑群聊客户" if is_rebind else "绑定群聊客户",
        object_type="whatsapp_group_binding",
        object_id=binding.id,
        detail=f"群 {group_jid} -> {normalized}"[:255],
    )
    return _binding_view(db, binding)


@router.delete("/whatsapp-group-bindings/{binding_id}")
def delete_binding(
    binding_id: int,
    pair: Annotated[tuple[User, UserSession], Depends(require_csrf)],
    db: Session = Depends(get_db),
) -> dict[str, bool]:
    user, _ = pair
    _require_whatsapp_operator(db, user)

    binding = db.get(WhatsAppGroupBinding, binding_id)
    if binding is None:
        raise HTTPException(status_code=404, detail="绑定不存在")
    if binding.channel_account_id is None:
        raise HTTPException(status_code=403, detail=DENIED)
    allowed_ids = set(db.scalars(scoped_channel_account_ids(user)).all())
    if binding.channel_account_id not in allowed_ids:
        raise HTTPException(status_code=403, detail=DENIED)

    object_id = binding.id
    detail = f"群 {binding.group_jid} -> {binding.normalized_phone}"[:255]
    try:
        db.delete(binding)
        db.commit()
    except Exception:
        db.rollback()
        raise
    _record_operation(
        db,
        user,
        name="解绑群聊客户",
        object_type="whatsapp_group_binding",
        object_id=object_id,
        detail=detail,
    )
    return {"ok": True}
