import base64
import binascii
import json
import os
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from hmac import compare_digest
from typing import Any, Mapping, Protocol

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.channels.inbound import (
    InboundBatchResult,
    InvalidProviderAuthorization,
    SourceValidationFailure,
    ingest_gmail_history,
)
from app.database import get_db
from app.gmail_client import GmailApiClient, GmailConfigurationError
from app.models.business import ChannelAccount, ChannelGrant

router = APIRouter(prefix="/api/integrations/gmail", tags=["gmail"])


class GmailClient(Protocol):
    def list_history(self, *, account_id: int, history_id: str) -> list[Mapping[str, Any]]:
        ...

    def fetch_message(self, *, account_id: int, message_id: str) -> Mapping[str, Any]:
        ...


class PubSubMessage(BaseModel):
    data: str = Field(min_length=1)


class PubSubEnvelope(BaseModel):
    message: PubSubMessage
    subscription: str | None = None


class UnconfiguredGmailClient:
    def list_history(self, *, account_id: int, history_id: str) -> list[Mapping[str, Any]]:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="gmail provider is not configured",
        )

    def fetch_message(self, *, account_id: int, message_id: str) -> Mapping[str, Any]:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="gmail provider is not configured",
        )


def get_gmail_client() -> GmailClient:
    """Construct the server-side Gmail client without exposing credentials."""
    try:
        return GmailApiClient()
    except GmailConfigurationError:
        return UnconfiguredGmailClient()


def _push_token(request: Request, query_token: str | None) -> str:
    return query_token or request.headers.get("X-Gmail-PubSub-Token", "")


def _expected_push_token() -> str:
    return os.environ.get("GMAIL_PUBSUB_PUSH_TOKEN", "")


def _decode_history_id(envelope: PubSubEnvelope) -> str:
    try:
        decoded = base64.b64decode(envelope.message.data, validate=True)
        notification = json.loads(decoded)
    except (ValueError, TypeError, binascii.Error, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail="invalid Gmail Pub/Sub payload") from exc

    history_id = notification.get("historyId")
    if not isinstance(history_id, str) or not history_id:
        raise HTTPException(status_code=400, detail="Gmail historyId is required")
    return history_id


def _connected_gmail_account(db: Session, account_id: int) -> ChannelAccount:
    account = db.scalar(
        select(ChannelAccount).where(
            ChannelAccount.id == account_id,
            ChannelAccount.channel_type == "gmail",
            ChannelAccount.status == "connected",
            select(ChannelGrant.channel_account_id).where(
                ChannelGrant.channel_account_id == ChannelAccount.id,
                ChannelGrant.channel_type == ChannelAccount.channel_type,
                ChannelGrant.owner_user_id == ChannelAccount.owner_user_id,
            ).exists(),
        )
    )
    if account is None:
        raise HTTPException(status_code=403, detail="没有权限访问")
    return account


@router.post("/pubsub/{channel_account_id}", status_code=status.HTTP_202_ACCEPTED)
def gmail_pubsub(
    channel_account_id: int,
    envelope: PubSubEnvelope,
    request: Request,
    query_token: str | None = Query(default=None, alias="token"),
    db: Session = Depends(get_db),
    client: GmailClient = Depends(get_gmail_client),
) -> dict[str, int | str | None]:
    expected_token = _expected_push_token()
    if not expected_token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="gmail push authentication is not configured",
        )
    push_token = _push_token(request, query_token)
    if not compare_digest(push_token, expected_token):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="没有权限访问")

    _connected_gmail_account(db, channel_account_id)
    history_id = _decode_history_id(envelope)
    try:
        result: InboundBatchResult = ingest_gmail_history(
            db,
            account_id=channel_account_id,
            history_id=history_id,
            client=client,
            push_token=push_token,
            expected_push_token=expected_token,
        )
    except (InvalidProviderAuthorization, SourceValidationFailure) as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="没有权限访问") from exc

    return {
        "accepted": len(result.results),
        "created": sum(item.created for item in result.results),
        "cursor": result.cursor,
    }
