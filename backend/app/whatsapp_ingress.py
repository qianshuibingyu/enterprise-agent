"""Authenticated inbound callback contract for the project Baileys adapter."""

from datetime import datetime
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.external_events import ingest_external_event, verify_ingress_token
from app.models.business import ChannelAccount
from app.overview_service import schedule_message_overview

router = APIRouter(prefix="/api/integrations/whatsapp", tags=["whatsapp-inbound"])


class WhatsAppInboundEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    external_account_id: str = Field(min_length=1, max_length=255)
    external_message_id: str = Field(min_length=1, max_length=512)
    direction: str
    status: str
    occurred_at: datetime
    raw_content: str
    customer_contact: str | None = Field(default=None, max_length=255)
    customer_nickname: str | None = Field(default=None, max_length=255)
    attachments: list[dict[str, Any]] = Field(default_factory=list)


@router.post("/accounts/{account_id}/inbound", status_code=status.HTTP_202_ACCEPTED)
def receive_whatsapp_event(
    account_id: int,
    event: WhatsAppInboundEvent,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    ingress_token: str | None = Header(default=None, alias="X-WhatsApp-Adapter-Token"),
) -> dict[str, int | str | bool]:
    verify_ingress_token("whatsapp", ingress_token)
    account = db.scalar(
        select(ChannelAccount).where(
            ChannelAccount.id == account_id,
            ChannelAccount.channel_type == "whatsapp",
            ChannelAccount.external_account_id == event.external_account_id,
            ChannelAccount.status != "revoked",
        )
    )
    if account is None:
        raise HTTPException(status_code=404, detail="渠道账号不存在")
    result = ingest_external_event(
        db,
        channel_type="whatsapp",
        channel_account_id=account.id,
        event=event.model_dump(),
    )
    if account.status == "connected_pending_inbound":
        # A valid adapter event that reaches idempotent persistence proves the
        # real WhatsApp inbound path, whether this delivery created or found it.
        account.status = "verified_inbound"
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    if result.created:
        background_tasks.add_task(schedule_message_overview, result.message.id)
    return {
        "accepted": True,
        "created": result.created,
        "message_id": result.message.id,
        "provider": "whatsapp_web_baileys",
    }
