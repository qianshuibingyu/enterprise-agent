from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.channels.registry import provider_descriptor
from app.database import get_db
from app.external_events import ingest_external_event, verify_ingress_token
from app.models.business import ChannelAccount

router = APIRouter(prefix="/api/integrations", tags=["external-integrations"])


class NormalizedExternalEvent(BaseModel):
    model_config = ConfigDict(extra="allow")

    external_account_id: str
    external_message_id: str
    direction: str
    status: str
    occurred_at: datetime
    raw_content: str
    attachments: list[dict[str, Any]] = Field(default_factory=list)


def _account_for_ingress(
    db: Session,
    *,
    channel_type: str,
    account_id: int,
    external_account_id: str,
) -> ChannelAccount:
    account = db.scalar(
        select(ChannelAccount).where(
            ChannelAccount.id == account_id,
            ChannelAccount.channel_type == channel_type,
            ChannelAccount.external_account_id == external_account_id,
        )
    )
    if account is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="渠道账号不存在")
    return account


@router.post("/{channel_type}/ingress/{account_id}", status_code=status.HTTP_202_ACCEPTED)
def receive_external_event(
    channel_type: str,
    account_id: int,
    event: NormalizedExternalEvent,
    db: Session = Depends(get_db),
    ingress_token: Annotated[str | None, Header(alias="X-External-Ingress-Token")] = None,
) -> dict[str, int | str | bool]:
    try:
        descriptor = provider_descriptor(channel_type)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="渠道不存在") from exc

    verify_ingress_token(channel_type, ingress_token)
    _account_for_ingress(
        db,
        channel_type=channel_type,
        account_id=account_id,
        external_account_id=event.external_account_id,
    )
    result = ingest_external_event(
        db,
        channel_type=channel_type,
        channel_account_id=account_id,
        event=event.model_dump(),
    )
    db.commit()
    return {
        "accepted": True,
        "created": result.created,
        "message_id": result.message.id,
        "provider": descriptor.key,
    }
