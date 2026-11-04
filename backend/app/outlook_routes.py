from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import current_user
from app.authorization import scoped_channel_account_ids
from app.database import get_db
from app.message_ingestion import ingest_provider_message
from app.models.business import ChannelAccount
from app.models.user import User
from app.outlook_graph import OutlookGraphError, OutlookGraphClient, outlook_graph_client_for_ciphertext

router = APIRouter(prefix="/api/integrations/outlook", tags=["outlook"])


def get_outlook_client(account_id: int, db: Session = Depends(get_db)) -> OutlookGraphClient:
    account = db.scalar(
        select(ChannelAccount).where(
            ChannelAccount.id == account_id,
            ChannelAccount.channel_type == "outlook",
        )
    )
    if account is None or not account.outlook_credential_ciphertext:
        raise HTTPException(status_code=503, detail="Outlook OAuth is not configured for this account")
    try:
        return outlook_graph_client_for_ciphertext(account.outlook_credential_ciphertext)
    except OutlookGraphError as exc:
        raise HTTPException(status_code=503, detail="Outlook credential is unavailable") from exc


def _account(db: Session, user: User, account_id: int) -> ChannelAccount:
    account = db.scalar(
        select(ChannelAccount).where(
            ChannelAccount.id == account_id,
            ChannelAccount.channel_type == "outlook",
            ChannelAccount.id.in_(scoped_channel_account_ids(user)),
        )
    )
    if account is None or not account.external_account_id:
        raise HTTPException(status_code=403, detail="没有权限访问")
    return account


def _normalized_message(item: dict[str, object]) -> dict[str, object]:
    return {
        "external_message_id": str(item.get("id") or item.get("message_id")),
        "direction": "inbound",
        "status": "received",
        "occurred_at": item.get("received_date_time") or item.get("receivedDateTime"),
        "raw_content": str(item.get("body_preview") or item.get("body") or ""),
        "attachments": [],
    }


@router.get("/accounts/{account_id}/messages")
def list_outlook_messages(
    account_id: int,
    user: Annotated[User, Depends(current_user)],
    db: Session = Depends(get_db),
    client: OutlookGraphClient = Depends(get_outlook_client),
    count: int = Query(default=50, ge=1, le=100),
) -> dict[str, object]:
    account = _account(db, user, account_id)
    try:
        messages = client.list_emails(
            external_account_id=account.external_account_id,
            count=count,
        )
    except OutlookGraphError as exc:
        raise HTTPException(status_code=502, detail="Outlook Graph 读取失败") from exc

    output: list[dict[str, object]] = []
    for item in messages:
        if not isinstance(item, dict):
            continue
        normalized = _normalized_message(item)
        if not normalized["external_message_id"] or normalized["occurred_at"] is None:
            continue
        ingested = ingest_provider_message(
            db,
            channel_account_id=account.id,
            provider="outlook_mcp_graph",
            message=normalized,
        )
        output.append({"id": ingested.message.id, "created": ingested.created})
    created = sum(1 for item in output if item["created"] is True)
    if output and account.status == "connected_pending_inbound":
        # A successful provider read and normalized persistence proves the
        # minimal Outlook inbound path; duplicate reads are valid evidence too.
        account.status = "verified_inbound"
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {
        "messages": output,
        "total": len(output),
        "created": created,
        "duplicates": len(output) - created,
    }
