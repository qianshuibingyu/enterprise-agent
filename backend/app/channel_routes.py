from datetime import datetime, timezone
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import current_user, require_csrf
from app.authorization import (
    can_connect_channels,
    channel_onboarding_account_ids,
    has_channel_preauthorization,
    read_channel_account_ids,
)
from app.database import get_db
from app.models.business import ChannelAccount, ChannelGrant
from app.models.user import User, UserSession
from app.channel_cleanup import purge_channel_shell
from app.channels.registry import provider_descriptor
from app.whatsapp_adapter import WhatsAppAdapterClient

router = APIRouter(prefix="/api", tags=["channels"])

_SUPPORTED_CHANNELS = {"gmail", "outlook", "whatsapp"}


class ExternalBindingBody(BaseModel):
    external_account_id: str = Field(min_length=1, max_length=255)
    status: Literal[
        "not_ready", "awaiting_authorization", "connected_pending_inbound",
        "blocked", "system_error", "revoked",
        # Legacy fixture statuses remain accepted for test-only compatibility.
        "external_authorization_required", "error",
    ] = "awaiting_authorization"


def _account_view(account: ChannelAccount) -> dict[str, int | str | bool | None]:
    return {
        "id": account.id,
        "owner_user_id": account.owner_user_id,
        "channel_type": account.channel_type,
        "external_account_id": account.external_account_id,
        "status": account.status,
        "test_only": False,
    }


def _channel_view(channel_type: str) -> dict[str, object]:
    descriptor = provider_descriptor(channel_type)
    return {
        "channel_type": channel_type,
        "provider": descriptor.key,
        "display_name": descriptor.display_name,
        "authorization_owner": descriptor.authorization_owner,
        "ingress_kind": descriptor.ingress_kind,
        "capabilities": {
            "inbound": descriptor.capabilities.inbound,
            "outbound": descriptor.capabilities.outbound,
            "realtime": descriptor.capabilities.realtime,
            "webhook": descriptor.capabilities.webhook,
            "polling": descriptor.capabilities.polling,
            "attachments": descriptor.capabilities.attachments,
            "requires_public_endpoint": descriptor.capabilities.requires_public_endpoint,
        },
        "test_only": descriptor.test_only,
        "legacy": descriptor.legacy,
        "status_values": [
            "not_ready",
            "awaiting_authorization",
            "connected_pending_inbound",
            "verified_inbound",
            "blocked",
            "system_error",
            "revoked",
        ],
    }


def require_channel_preauthorization(db: Session, user: User, channel_type: str) -> None:
    # Administrators connect channels on behalf of operators. Requiring them to
    # first grant themselves an operator-only preauthorization is pure friction
    # (and the grant endpoint rejects admin roles by design).
    if user.role == "admin":
        return
    if not can_connect_channels(user) or not has_channel_preauthorization(db, user, channel_type):
        raise HTTPException(status_code=403, detail="没有权限访问")


def require_channel_operator(user: User) -> None:
    if not can_connect_channels(user):
        raise HTTPException(status_code=403, detail="没有权限访问")


def _get_scoped_account(db: Session, user: User, account_id: int) -> ChannelAccount:
    account = db.scalar(
        select(ChannelAccount).where(
            ChannelAccount.id == account_id,
            ChannelAccount.id.in_(channel_onboarding_account_ids(user)),
        ).with_for_update()
    )
    if account is None:
        raise HTTPException(status_code=403, detail="没有权限访问")
    if account.history_access_revoked_at is not None:
        raise HTTPException(status_code=403, detail="没有权限访问")
    return account


def _owned_shells(db: Session, user: User, channel_type: str) -> tuple[ChannelAccount | None, bool]:
    """Return (reusable active shell, only_revoked_shells_exist).

    Operators often click "开始授权" and then "撤销本地连接", leaving a revoked
    shell with the same channel type. Picking the lowest id unconditionally used
    to return that dead shell forever, so every later authorization failed with
    "历史访问已撤销" even when a healthy transferred account was available.
    """
    shells = db.scalars(
        select(ChannelAccount)
        .where(
            ChannelAccount.owner_user_id == user.id,
            ChannelAccount.channel_type == channel_type,
        )
        .order_by(ChannelAccount.id)
    ).all()
    active = [
        shell for shell in shells
        if shell.status != "revoked" and shell.history_access_revoked_at is None
    ]
    if active:
        return active[0], False
    return None, bool(shells)


@router.get("/channels")
def list_channels(
    user: Annotated[User, Depends(current_user)],
    db: Session = Depends(get_db),
) -> list[dict[str, object]]:
    if not can_connect_channels(user):
        raise HTTPException(status_code=403, detail="没有权限访问")
    return [
        _channel_view(channel_type)
        for channel_type in ("gmail", "outlook", "whatsapp")
        if user.role == "admin" or has_channel_preauthorization(db, user, channel_type)
    ]


@router.get("/channels/accounts")
def list_channel_accounts(
    user: Annotated[User, Depends(current_user)],
    db: Session = Depends(get_db),
) -> list[dict[str, int | str | bool | None]]:
    accounts = db.scalars(
        select(ChannelAccount)
        .where(ChannelAccount.id.in_(read_channel_account_ids(user)))
        .order_by(ChannelAccount.id)
    ).all()
    return [_account_view(account) for account in accounts]


@router.post("/channels/whatsapp/accounts")
def create_whatsapp_account(
    pair: Annotated[tuple[User, UserSession], Depends(require_csrf)],
    db: Session = Depends(get_db),
) -> dict[str, object]:
    """Create a local WhatsApp account shell before Baileys pairing."""
    user, _ = pair
    require_channel_preauthorization(db, user, "whatsapp")
    existing, has_revoked_shell = _owned_shells(db, user, "whatsapp")
    if has_revoked_shell:
        raise HTTPException(status_code=403, detail="历史访问已撤销，需管理员重新授权")
    if existing is not None:
        grant = db.scalar(
            select(ChannelGrant).where(
                ChannelGrant.channel_account_id == existing.id,
                ChannelGrant.channel_type == existing.channel_type,
                ChannelGrant.owner_user_id == user.id,
            )
        )
        if grant is None:
            raise HTTPException(status_code=403, detail="没有权限访问")
        return _account_view(existing)
    account = ChannelAccount(
        owner_user_id=user.id,
        channel_type="whatsapp",
        status="not_ready",
    )
    db.add(account)
    db.flush()
    db.add(ChannelGrant(
        channel_account_id=account.id,
        channel_type="whatsapp",
        owner_user_id=user.id,
    ))
    db.commit()
    return _account_view(account)


@router.post("/channels/gmail/accounts")
def create_gmail_account(
    pair: Annotated[tuple[User, UserSession], Depends(require_csrf)],
    db: Session = Depends(get_db),
) -> dict[str, object]:
    """Create the local Gmail account shell before official OAuth.

    This deliberately stores no email, token, secret, or provider identity.
    """
    user, _ = pair
    require_channel_preauthorization(db, user, "gmail")
    existing, has_revoked_shell = _owned_shells(db, user, "gmail")
    if has_revoked_shell:
        raise HTTPException(status_code=403, detail="历史访问已撤销，需管理员重新授权")
    if existing is not None:
        grant = db.get(ChannelGrant, (existing.id, "gmail", user.id))
        if grant is None:
            raise HTTPException(status_code=403, detail="没有权限访问")
        return _account_view(existing)
    account = ChannelAccount(
        owner_user_id=user.id,
        channel_type="gmail",
        status="not_ready",
    )
    db.add(account)
    db.flush()
    db.add(ChannelGrant(
        channel_account_id=account.id,
        channel_type="gmail",
        owner_user_id=user.id,
    ))
    db.commit()
    return _account_view(account)


@router.post("/channels/outlook/accounts")
def create_outlook_account(
    pair: Annotated[tuple[User, UserSession], Depends(require_csrf)],
    db: Session = Depends(get_db),
) -> dict[str, object]:
    """Create the local Outlook account shell before Microsoft OAuth."""
    user, _ = pair
    require_channel_preauthorization(db, user, "outlook")
    existing, has_revoked_shell = _owned_shells(db, user, "outlook")
    if has_revoked_shell:
        raise HTTPException(status_code=403, detail="历史访问已撤销，需管理员重新授权")
    if existing is not None:
        grant = db.scalar(
            select(ChannelGrant).where(
                ChannelGrant.channel_account_id == existing.id,
                ChannelGrant.channel_type == "outlook",
                ChannelGrant.owner_user_id == user.id,
            )
        )
        if grant is None:
            raise HTTPException(status_code=403, detail="没有权限访问")
        return _account_view(existing)
    account = ChannelAccount(owner_user_id=user.id, channel_type="outlook", status="not_ready")
    db.add(account)
    db.flush()
    db.add(ChannelGrant(
        channel_account_id=account.id,
        channel_type="outlook",
        owner_user_id=user.id,
    ))
    db.commit()
    return _account_view(account)


@router.post("/channels/{channel_type}/authorize")
def begin_authorization(
    channel_type: str,
    pair: Annotated[tuple[User, UserSession], Depends(require_csrf)],
    db: Session = Depends(get_db),
) -> dict[str, object]:
    user, _ = pair
    require_channel_operator(user)
    if channel_type not in _SUPPORTED_CHANNELS:
        raise HTTPException(status_code=404, detail="渠道不存在")

    # This endpoint only explains how to authorize an account shell the caller
    # already owns. The admin preauthorization grant is enforced when a NEW
    # shell is created, so legacy accounts stay operable (see authorization.py).
    account = db.scalar(
        select(ChannelAccount).where(
            ChannelAccount.owner_user_id == user.id,
            ChannelAccount.channel_type == channel_type,
            ChannelAccount.id.in_(channel_onboarding_account_ids(user)),
        ).order_by(ChannelAccount.id)
    )
    if account is None:
        raise HTTPException(status_code=404, detail="渠道账号不存在")
    descriptor = provider_descriptor(channel_type)
    instructions = {
        "whatsapp": "请由账号所有者在本项目的 WhatsApp/Baileys 适配器中开始绑定，并使用手机 WhatsApp 扫描短时二维码完成关联设备登录。",
        "gmail": "请由账号所有者通过本项目 Google OAuth 完成 Gmail 授权；授权后由 backend 创建并维护 Gmail Watch。",
        "outlook": "请在外部 Outlook MCP Server 的授权入口完成 Microsoft Graph/Entra 个人委派授权并确认邮箱映射。",
    }
    return {
        "channel_account_id": account.id,
        "channel_type": channel_type,
        "provider": descriptor.key,
        "status": account.status,
        "authorization_owner": descriptor.authorization_owner,
        "external_authorization_required": True,
        "test_only": False,
        "message": instructions[channel_type],
    }


@router.post("/channels/accounts/{account_id}/external-binding")
def bind_external_account(
    account_id: int,
    body: ExternalBindingBody,
    pair: Annotated[tuple[User, UserSession], Depends(require_csrf)],
    db: Session = Depends(get_db),
) -> dict[str, object]:
    user, _ = pair
    require_channel_operator(user)
    account = _get_scoped_account(db, user, account_id)
    existing = db.scalar(
        select(ChannelAccount).where(
            ChannelAccount.external_account_id == body.external_account_id,
            ChannelAccount.id != account.id,
        )
    )
    if existing is not None:
        raise HTTPException(status_code=409, detail="外部账号已绑定")
    account.external_account_id = body.external_account_id
    account.status = body.status
    db.commit()
    return _account_view(account)


@router.post("/channels/accounts/{account_id}/revoke")
def revoke_channel(
    account_id: int,
    pair: Annotated[tuple[User, UserSession], Depends(require_csrf)],
    db: Session = Depends(get_db),
) -> dict[str, object]:
    user, _ = pair
    require_channel_operator(user)
    account = _get_scoped_account(db, user, account_id)
    channel_type = account.channel_type
    if account.channel_type == "gmail":
        # Drop local credentials and pending OAuth attempts; reconnect must use
        # a fresh authorization, never the revoked refresh token.
        from app.provider_auth_routes import _oauth_states
        _oauth_states.invalidate_account(account.id)
        account.gmail_credential_ciphertext = None
        account.credential_reference = None
        account.gmail_watch_history_id = None
        account.gmail_watch_expiration = None
    # "撤销本地连接" must actually clean up: an empty shell is deleted so the
    # operator can reconnect immediately. Shells that already collected
    # messages/inquiries are archived instead so history is never lost.
    removed = purge_channel_shell(db, account)
    if not removed:
        account.status = "revoked"
        account.history_access_revoked_at = datetime.now(timezone.utc)
    db.commit()
    return {
        "channel_account_id": account_id,
        "channel_type": channel_type,
        "status": "removed" if removed else "revoked",
        "cleanup": "removed" if removed else "archived_with_history",
        "test_only": False,
    }
