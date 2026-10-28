from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import current_user, require_csrf
from app.authorization import scoped_channel_account_ids
from app.database import get_db
from app.models.business import ChannelAccount
from app.models.user import User, UserSession
from app.channels.registry import provider_descriptor
from app.whatsapp_adapter import WhatsAppAdapterClient

router = APIRouter(prefix="/api", tags=["channels"])

_SUPPORTED_CHANNELS = {"gmail", "outlook", "whatsapp"}


class ExternalBindingBody(BaseModel):
    external_account_id: str = Field(min_length=1, max_length=255)
    status: Literal["external_authorization_required", "blocked", "error", "revoked"] = "external_authorization_required"


def _account_view(account: ChannelAccount) -> dict[str, int | str | bool]:
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
            "not_connected",
            "external_authorization_required",
            "connected",
            "blocked",
            "error",
            "revoked",
        ],
    }


def _get_scoped_account(db: Session, user: User, account_id: int) -> ChannelAccount:
    account = db.scalar(
        select(ChannelAccount).where(
            ChannelAccount.id == account_id,
            ChannelAccount.id.in_(scoped_channel_account_ids(user)),
        )
    )
    if account is None:
        raise HTTPException(status_code=403, detail="没有权限访问")
    return account


@router.get("/channels")
def list_channels(user: Annotated[User, Depends(current_user)]) -> list[dict[str, object]]:
    del user
    return [_channel_view(channel_type) for channel_type in ("gmail", "outlook", "whatsapp")]


@router.get("/channels/accounts")
def list_channel_accounts(
    user: Annotated[User, Depends(current_user)],
    db: Session = Depends(get_db),
) -> list[dict[str, int | str | bool]]:
    accounts = db.scalars(
        select(ChannelAccount)
        .where(ChannelAccount.id.in_(scoped_channel_account_ids(user)))
        .order_by(ChannelAccount.id)
    ).all()
    return [_account_view(account) for account in accounts]


@router.post("/channels/{channel_type}/authorize")
def begin_authorization(
    channel_type: str,
    pair: Annotated[tuple[User, UserSession], Depends(require_csrf)],
    db: Session = Depends(get_db),
) -> dict[str, object]:
    user, _ = pair
    if channel_type not in _SUPPORTED_CHANNELS:
        raise HTTPException(status_code=404, detail="渠道不存在")

    account = db.scalar(
        select(ChannelAccount).where(
            ChannelAccount.owner_user_id == user.id,
            ChannelAccount.channel_type == channel_type,
            ChannelAccount.id.in_(scoped_channel_account_ids(user)),
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
    account = _get_scoped_account(db, user, account_id)
    account.status = "revoked"
    db.commit()
    return {
        "channel_account_id": account.id,
        "channel_type": account.channel_type,
        "status": account.status,
        "test_only": False,
    }
