from typing import Annotated
import ast

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import current_user
from app.authorization import scoped_channel_account_ids
from app.database import get_db
from app.message_ingestion import ingest_provider_message
from app.models.business import ChannelAccount, Message
from app.models.user import User
from app.outlook_graph import OutlookGraphError, OutlookGraphClient, outlook_graph_client_for_ciphertext
from app.overview_service import schedule_message_overview
from app.provider_links import outlook_web_link

router = APIRouter(prefix="/api/integrations/outlook", tags=["outlook"])

# The unread read window never returns a message twice, so rows ingested before
# provider links were persisted would keep an empty link forever. Repair them in
# a bounded batch on each manual read instead of widening the queue scope.
LINK_BACKFILL_LIMIT = 20


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


def _outlook_sender(item: dict[str, object]) -> tuple[str | None, str | None]:
    sender = item.get("from")
    if not isinstance(sender, dict):
        return None, None
    address = sender.get("emailAddress")
    if not isinstance(address, dict):
        return None, None
    contact = address.get("address")
    nickname = address.get("name")
    return (
        str(contact) if isinstance(contact, str) and contact else None,
        str(nickname) if isinstance(nickname, str) and nickname else None,
    )


def _outlook_body_text(item: dict[str, object]) -> str:
    body = item.get("body")
    if isinstance(body, dict):
        content = body.get("content")
        if isinstance(content, str):
            return content
    if isinstance(body, str):
        # Some Outlook MCP responses serialize the Graph body object as a
        # Python-literal-looking string. Parse only literals; never eval provider
        # content, and only accept the expected body/content shape.
        try:
            structured = ast.literal_eval(body)
        except (SyntaxError, ValueError):
            structured = None
        if isinstance(structured, dict) and isinstance(structured.get("content"), str):
            return structured["content"]
        return body
    preview = item.get("body_preview") or item.get("bodyPreview")
    return preview if isinstance(preview, str) else ""


def _normalized_message(item: dict[str, object]) -> dict[str, object]:
    customer_contact, customer_nickname = _outlook_sender(item)
    return {
        "external_message_id": str(item.get("id") or item.get("message_id")),
        "direction": "inbound",
        "status": "received",
        "occurred_at": item.get("received_date_time") or item.get("receivedDateTime"),
        "raw_content": _outlook_body_text(item),
        "customer_contact": customer_contact,
        "customer_nickname": customer_nickname,
        "provider_web_link": (
            str(item["webLink"]) if isinstance(item.get("webLink"), str) else None
        ),
        "attachments": [],
    }


def _backfill_provider_links(
    db: Session,
    account: ChannelAccount,
    client: OutlookGraphClient,
    *,
    limit: int = LINK_BACKFILL_LIMIT,
) -> int:
    """Persist the provider web link for rows that were ingested without one."""
    pending = db.scalars(
        select(Message)
        .where(
            Message.channel_account_id == account.id,
            Message.provider == "outlook_mcp_graph",
            Message.provider_web_link.is_(None),
        )
        .order_by(Message.occurred_at.desc(), Message.id.desc())
        .limit(limit)
    ).all()
    repaired = 0
    for message in pending:
        try:
            link = outlook_web_link(client.message_web_link(message.external_message_id))
        except OutlookGraphError:
            continue
        if link is None:
            continue
        message.provider_web_link = link
        repaired += 1
    return repaired


@router.get("/accounts/{account_id}/messages")
def list_outlook_messages(
    account_id: int,
    background_tasks: BackgroundTasks,
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
    links_repaired = _backfill_provider_links(db, account, client)
    if output and account.status == "connected_pending_inbound":
        # A successful provider read and normalized persistence proves the
        # minimal Outlook inbound path; duplicate reads are valid evidence too.
        account.status = "verified_inbound"
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    for item in output:
        if item["created"] is True:
            background_tasks.add_task(schedule_message_overview, int(item["id"]))
    return {
        "messages": output,
        "total": len(output),
        "created": created,
        "duplicates": len(output) - created,
        "links_repaired": links_repaired,
    }
