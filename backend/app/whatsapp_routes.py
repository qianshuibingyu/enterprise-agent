import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from app.auth import current_user, require_csrf
from app.authorization import scoped_channel_account_ids
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
    # The owner must retain management access to revoked accounts so they can
    # explicitly reconnect them; normal data reads remain status-scoped.
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
    if account is None:
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
    return {
        "channel_account_id": account.id,
        "qr": pairing.qr,
        "expires_at": pairing.expires_at,
        "test_only": False,
    }


@router.get("/accounts/{account_id}/pair/status")
def pairing_status(
    account_id: int,
    user: Annotated[User, Depends(current_user)],
    db: Session = Depends(get_db),
    adapter: WhatsAppAdapterClient = Depends(get_whatsapp_adapter),
) -> dict[str, int | str | None]:
    account = _account(db, user, account_id)
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
    account.status = "revoked"
    db.commit()
    return {
        "channel_account_id": account.id,
        "state": state.state,
        "external_account_id": state.external_account_id,
        "detail": state.detail,
    }
