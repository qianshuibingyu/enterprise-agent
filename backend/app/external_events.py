"""Authenticated ingress boundary for external channel runtimes.

The WhatsApp adapter, Gmail Pub/Sub webhook, and Outlook MCP boundary own
provider-specific protocol details. This module validates the internal ingress
token, maps an already-normalized event to the canonical provider, and
 delegates persistence to the common idempotent message service.
"""

import hmac
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.channels.registry import provider_descriptor
from app.message_ingestion import IngestResult, ingest_provider_message


@dataclass(frozen=True)
class ExternalIngressEvent:
    external_message_id: str
    direction: str
    status: str
    occurred_at: datetime
    raw_content: str
    attachments: tuple[Mapping[str, Any], ...] = ()


def expected_ingress_token(channel_type: str) -> str:
    variable = {
        "whatsapp": "WHATSAPP_ADAPTER_TOKEN",
        "gmail": "GMAIL_PUBSUB_PUSH_TOKEN",
        "outlook": "OUTLOOK_MCP_TOKEN",
    }[channel_type]
    return os.environ.get(variable, "")


def verify_ingress_token(channel_type: str, supplied: str | None) -> None:
    expected = expected_ingress_token(channel_type)
    if not expected or not supplied or not hmac.compare_digest(supplied, expected):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="没有权限访问")


def ingest_external_event(
    db: Session,
    *,
    channel_type: str,
    channel_account_id: int,
    event: Mapping[str, Any],
) -> IngestResult:
    descriptor = provider_descriptor(channel_type)
    required = (
        "external_account_id",
        "external_message_id",
        "direction",
        "status",
        "occurred_at",
        "raw_content",
    )
    missing = [field for field in required if field not in event]
    if missing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"缺少外部事件字段: {', '.join(missing)}",
        )
    return ingest_provider_message(
        db,
        channel_account_id=channel_account_id,
        provider=descriptor.key,
        message=event,
    )
