import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.auth import current_user, require_csrf
from app.channels.registry import PROVIDERS, provider_for, provider_descriptor
from app.channels.contracts import ChannelType
from app.database import get_db
from app.models.business import ChannelAccount, ChannelGrant
from app.models.user import User, UserSession

router = APIRouter(prefix="/api/channels", tags=["channels"])

# Deliberately process-local and test-only. Real OAuth state must use a durable,
# expiring server-side store before a real provider is enabled.
_TEST_STATES: dict[str, tuple[int, int, str]] = {}


def _account_for_user(db: Session, user: User, account_id: int) -> ChannelAccount:
    grant_scope = select(ChannelGrant.channel_account_id).where(
        ChannelGrant.channel_account_id == ChannelAccount.id,
        ChannelGrant.channel_type == ChannelAccount.channel_type,
        ChannelGrant.owner_user_id == ChannelAccount.owner_user_id,
        ChannelGrant.owner_user_id == user.id,
    )
    account = db.scalar(
        select(ChannelAccount).where(
            ChannelAccount.id == account_id,
            ChannelAccount.owner_user_id == user.id,
            grant_scope.exists(),
        )
    )
    if account is None:
        raise HTTPException(status_code=403, detail="没有权限访问")
    return account


def _account_view(account: ChannelAccount) -> dict[str, int | str]:
    return {
        "id": account.id,
        "owner_user_id": account.owner_user_id,
        "channel_type": account.channel_type,
        "status": account.status,
    }


@router.get("")
def channel_catalog(
    user: Annotated[User, Depends(current_user)],
) -> list[dict[str, object]]:
    return [
        {
            "channel_type": descriptor.channel_type,
            "display_name": descriptor.display_name,
            "provider": descriptor.provider_name,
            "integration_type": descriptor.integration_type,
            "guide": descriptor.guide,
            "capabilities": descriptor.capabilities.__dict__,
            "real_integration": descriptor.real_integration,
            "blocked_reason": descriptor.blocked_reason,
            "test_provider_available": True,
        }
        for descriptor in PROVIDERS.values()
    ]


@router.get("/accounts")
def channel_accounts(
    user: Annotated[User, Depends(current_user)],
    db: Session = Depends(get_db),
) -> list[dict[str, int | str]]:
    accounts = db.scalars(
        select(ChannelAccount).where(
            ChannelAccount.owner_user_id == user.id,
            select(ChannelGrant.channel_account_id).where(
                ChannelGrant.channel_account_id == ChannelAccount.id,
                ChannelGrant.channel_type == ChannelAccount.channel_type,
                ChannelGrant.owner_user_id == ChannelAccount.owner_user_id,
                ChannelGrant.owner_user_id == user.id,
            ).exists(),
        ).order_by(ChannelAccount.id)
    ).all()
    return [_account_view(account) for account in accounts]


@router.post("/{channel_type}/accounts/{account_id}/authorize")
def start_authorization(
    channel_type: ChannelType,
    account_id: int,
    pair: Annotated[tuple[User, UserSession], Depends(require_csrf)],
    db: Session = Depends(get_db),
    test_mode: bool = Query(default=False),
) -> dict[str, object]:
    user, _ = pair
    account = _account_for_user(db, user, account_id)
    if account.channel_type != channel_type:
        raise HTTPException(status_code=403, detail="没有权限访问")

    state = secrets.token_urlsafe(24)
    provider = provider_for(channel_type, test_mode=test_mode)
    if not test_mode:
        account.status = "blocked"
        db.commit()
        return {
            "status": "blocked",
            "reason": provider_descriptor(channel_type).blocked_reason,
            "test_only": False,
        }

    start = provider.authorize_start(state=state)
    _TEST_STATES[state] = (user.id, account.id, channel_type)
    account.status = "authorizing"
    db.commit()
    return {
        "status": "authorizing",
        "authorization_url": f"/api/channels/{channel_type}/accounts/{account_id}/fake-callback?state={state}",
        "state": state,
        "test_only": True,
    }


@router.get("/{channel_type}/accounts/{account_id}/fake-callback")
def fake_callback(
    channel_type: ChannelType,
    account_id: int,
    state: str,
    user: Annotated[User, Depends(current_user)],
    db: Session = Depends(get_db),
    result: str = Query(default="success"),
) -> dict[str, object]:
    pending = _TEST_STATES.get(state)
    if pending != (user.id, account_id, channel_type):
        raise HTTPException(status_code=403, detail="没有权限访问")
    account = _account_for_user(db, user, account_id)
    provider = provider_for(channel_type, test_mode=True)
    provider_result = provider.authorize_callback(
        state=state,
        callback_data={"result": "error" if result == "error" else "success"},
    )
    _TEST_STATES.pop(state, None)
    account.status = provider_result.status
    db.commit()
    return {
        "status": provider_result.status,
        "test_only": True,
        "error_code": provider_result.error_code,
    }


@router.post("/{channel_type}/accounts/{account_id}/revoke")
def revoke_channel(
    channel_type: ChannelType,
    account_id: int,
    pair: Annotated[tuple[User, UserSession], Depends(require_csrf)],
    db: Session = Depends(get_db),
) -> dict[str, object]:
    user, _ = pair
    account = _account_for_user(db, user, account_id)
    if account.channel_type != channel_type:
        raise HTTPException(status_code=403, detail="没有权限访问")
    account.status = "revoked"
    db.commit()
    return {"status": "revoked", "test_only": False}
