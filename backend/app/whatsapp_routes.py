from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import current_user, require_csrf
from app.authorization import scoped_channel_account_ids
from app.database import get_db
from app.models.business import ChannelAccount
from app.models.user import User, UserSession
from app.whatsapp_adapter import AdapterStatus, HttpWhatsAppAdapterClient, PairingResponse, WhatsAppAdapterClient

router = APIRouter(prefix="/api/integrations/whatsapp", tags=["whatsapp"])


def get_whatsapp_adapter() -> WhatsAppAdapterClient:
    try:
        return HttpWhatsAppAdapterClient()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="WhatsApp Baileys adapter is not configured",
        ) from exc


def _account(db: Session, user: User, account_id: int) -> ChannelAccount:
    account = db.scalar(
        select(ChannelAccount).where(
            ChannelAccount.id == account_id,
            ChannelAccount.channel_type == "whatsapp",
            ChannelAccount.id.in_(scoped_channel_account_ids(user)),
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
    pairing: PairingResponse = adapter.start_pairing(channel_account_id=account.id)
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
    state: AdapterStatus = adapter.status(channel_account_id=account.id)
    return {
        "channel_account_id": account.id,
        "state": state.state,
        "external_account_id": state.external_account_id,
        "detail": state.detail,
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
