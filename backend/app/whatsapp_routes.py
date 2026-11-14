import logging
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from app.auth import current_user, require_csrf
from app.authorization import can_connect_channels
from app.channel_cleanup import purge_channel_shell
from app.database import get_db
from app.models.business import ChannelAccount, ChannelGrant
from app.models.user import User, UserSession
from app.whatsapp_adapter import (
    AdapterStatus,
    HttpWhatsAppAdapterClient,
    PairingResponse,
    WhatsAppAdapterClient,
    WhatsAppAdapterConfigurationError,
    WhatsAppAdapterUnavailableError,
)
from app.whatsapp_state import account_status_for_adapter_state

router = APIRouter(prefix="/api/integrations/whatsapp", tags=["whatsapp"])
logger = logging.getLogger("enterprise_agent.whatsapp")


def get_whatsapp_adapter() -> WhatsAppAdapterClient:
    try:
        return HttpWhatsAppAdapterClient()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="WhatsApp Baileys adapter is not configured",
        ) from exc


def _account(db: Session, user: User, account_id: int) -> ChannelAccount:
    if not can_connect_channels(user):
        raise HTTPException(status_code=403, detail="没有权限访问")
    # Pairing/disconnect operate on an already owned account, not on channel
    # onboarding; the admin grant is enforced when the account shell is created.
    # Administrators can pair a device on their own account and then transfer
    # that account to the operator who will handle the messages.
    grant_exists = exists().where(
        ChannelGrant.channel_account_id == ChannelAccount.id,
        ChannelGrant.channel_type == "whatsapp",
        ChannelGrant.owner_user_id == user.id,
    )
    account = db.scalar(
        select(ChannelAccount).where(
            ChannelAccount.id == account_id,
            ChannelAccount.channel_type == "whatsapp",
            ChannelAccount.owner_user_id == user.id,
            grant_exists,
        )
    )
    if account is None or account.history_access_revoked_at is not None:
        raise HTTPException(status_code=403, detail="没有权限访问")
    return account


@router.post("/accounts/{account_id}/pair/start")
def start_pairing(
    account_id: int,
    pair: Annotated[tuple[User, UserSession], Depends(require_csrf)],
    db: Session = Depends(get_db),
    adapter: WhatsAppAdapterClient = Depends(get_whatsapp_adapter),
) -> dict[str, int | str]:
    user, _ = pair
    account = _account(db, user, account_id)
    try:
        pairing: PairingResponse = adapter.start_pairing(channel_account_id=account.id)
    except WhatsAppAdapterConfigurationError as exc:
        logger.warning("WhatsApp bridge authorization failed")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="WhatsApp bridge authorization is misconfigured",
        ) from exc
    except WhatsAppAdapterUnavailableError as exc:
        logger.warning("WhatsApp bridge pairing failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="WhatsApp bridge is unavailable; inspect bridge logs",
        ) from exc
    except Exception as exc:
        logger.warning("WhatsApp bridge pairing failed with an unexpected adapter error")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="WhatsApp bridge is unavailable; inspect bridge logs",
        ) from exc
    # A device that WhatsApp unlinked is re-pairable: the bridge already
    # discarded the dead credentials and produced a new QR, so the account must
    # leave the terminal "revoked" status instead of staying stuck there.
    if account.status not in {"connected", "connected_pending_inbound", "verified_inbound"}:
        account.status = "awaiting_authorization"
        db.commit()
    return {
        "channel_account_id": account.id,
        "qr": pairing.qr,
        "expires_at": pairing.expires_at,
        "test_only": False,
        "status": account.status,
    }


@router.get("/accounts/{account_id}/pair/status")
def pairing_status(
    account_id: int,
    user: Annotated[User, Depends(current_user)],
    db: Session = Depends(get_db),
    adapter: WhatsAppAdapterClient = Depends(get_whatsapp_adapter),
) -> dict[str, int | str | None]:
    account = _account(db, user, account_id)
    # A soft "revoked" status can be repaired by the owner through a fresh
    # pairing. Only a real history-access revocation (set by /disconnect and
    # /revoke) permanently blocks re-pairing and hides collected history.
    if account.history_access_revoked_at is not None:
        raise HTTPException(status_code=403, detail="没有权限访问")
    try:
        state: AdapterStatus = adapter.status(channel_account_id=account.id)
    except WhatsAppAdapterConfigurationError as exc:
        logger.warning("WhatsApp bridge authorization failed")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="WhatsApp bridge authorization is misconfigured",
        ) from exc
    except WhatsAppAdapterUnavailableError as exc:
        logger.warning("WhatsApp bridge status failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="WhatsApp bridge is unavailable; inspect bridge logs",
        ) from exc
    except Exception as exc:
        logger.warning("WhatsApp bridge status failed with an unexpected adapter error")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="WhatsApp bridge is unavailable; inspect bridge logs",
        ) from exc
    if state.external_account_id:
        account.external_account_id = state.external_account_id
    account.status = account_status_for_adapter_state(
        account.status,
        state.state,
        bool(account.external_account_id),
    )
    db.commit()
    return {
        "channel_account_id": account.id,
        "state": state.state,
        "external_account_id": state.external_account_id,
        "detail": state.detail,
        "qr": state.qr,
        "expires_at": state.expires_at,
        "status": account.status,
    }


@router.post("/accounts/{account_id}/disconnect")
def disconnect(
    account_id: int,
    pair: Annotated[tuple[User, UserSession], Depends(require_csrf)],
    db: Session = Depends(get_db),
    adapter: WhatsAppAdapterClient = Depends(get_whatsapp_adapter),
) -> dict[str, int | str | None]:
    user, _ = pair
    account = _account(db, user, account_id)
    state = adapter.disconnect(channel_account_id=account.id)
    # Disconnecting an empty pairing shell must remove the record, not leave a
    # revoked zombie that blocks re-pairing and ownership transfer later.
    removed = purge_channel_shell(db, account)
    if not removed:
        account.status = "revoked"
        account.history_access_revoked_at = datetime.now(timezone.utc)
    db.commit()
    return {
        "channel_account_id": account_id,
        "state": state.state,
        "external_account_id": state.external_account_id,
        "detail": state.detail,
        "cleanup": "removed" if removed else "archived_with_history",
    }
