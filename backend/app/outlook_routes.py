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
from app.outlook_mcp_http import OutlookMcpError, OutlookMcpHttpClient

router = APIRouter(prefix="/api/integrations/outlook", tags=["outlook"])


def get_outlook_client() -> OutlookMcpHttpClient:
    raise HTTPException(status_code=503, detail="Outlook MCP client is not configured")


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
    client: OutlookMcpHttpClient = Depends(get_outlook_client),
    count: int = Query(default=50, ge=1, le=100),
) -> list[dict[str, object]]:
    account = _account(db, user, account_id)
    try:
        result = client.list_emails(count=count)
    except OutlookMcpError as exc:
        raise HTTPException(status_code=502, detail="Outlook MCP 读取失败") from exc

    messages = result.get("messages", result) if isinstance(result, dict) else result
    if not isinstance(messages, list):
        raise HTTPException(status_code=502, detail="Outlook MCP 返回格式无效")

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
    db.commit()
    return output
