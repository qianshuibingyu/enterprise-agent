from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import base64
import os
import re
from typing import Any, Mapping

import httpx

from app.channels.inbound import (
    ProviderAuthorizationFailure,
    ProviderPermanentFailure,
    ProviderRateLimited,
    ProviderTemporaryFailure,
)

TOKEN_URL = "https://oauth2.googleapis.com/token"
GMAIL_API_URL = "https://gmail.googleapis.com/gmail/v1/users"


class GmailConfigurationError(RuntimeError):
    pass


class GmailApiClient:
    """Minimal server-side Gmail API client using an OAuth refresh token.

    Secrets are read only from the server process environment and never
    returned by this class. Provider-specific payload parsing stays here.
    """

    def __init__(self, *, refresh_token: str, http: httpx.Client | None = None):
        self.client_id = os.environ.get("GMAIL_CLIENT_ID")
        self.client_secret = os.environ.get("GMAIL_CLIENT_SECRET")
        self.refresh_token = refresh_token
        self.user_id = os.environ.get("GMAIL_USER_ID", "me")
        if not all((self.client_id, self.client_secret, self.refresh_token)):
            raise GmailConfigurationError("gmail OAuth client is not configured")
        self.http = http or httpx.Client(timeout=20.0)
        self._access_token: str | None = None

    def _token(self) -> str:
        if self._access_token:
            return self._access_token
        response = self.http.post(
            TOKEN_URL,
            data={
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "refresh_token": self.refresh_token,
                "grant_type": "refresh_token",
            },
        )
        if response.status_code == 429:
            raise ProviderRateLimited("Gmail OAuth provider rate limited")
        if response.status_code in {500, 502, 503, 504}:
            raise ProviderTemporaryFailure("Gmail OAuth provider temporarily unavailable")
        if response.status_code in {401, 403}:
            raise ProviderAuthorizationFailure("Gmail OAuth authorization failed")
        if response.status_code >= 400:
            raise ProviderPermanentFailure("Gmail OAuth refresh failed")
        token = response.json().get("access_token")
        if not isinstance(token, str) or not token:
            raise GmailConfigurationError("Gmail OAuth response has no access token")
        self._access_token = token
        return token

    def _get(self, path: str, *, params: Mapping[str, str] | None = None) -> dict[str, Any]:
        response = self.http.get(
            f"{GMAIL_API_URL}/{self.user_id}/{path}",
            params=params,
            headers={"Authorization": f"Bearer {self._token()}"},
        )
        if response.status_code == 429:
            raise ProviderRateLimited("Gmail API rate limited")
        if response.status_code in {500, 502, 503, 504}:
            raise ProviderTemporaryFailure("Gmail API temporarily unavailable")
        if response.status_code in {401, 403}:
            raise ProviderAuthorizationFailure("Gmail API authorization failed")
        if response.status_code >= 400:
            raise ProviderPermanentFailure("Gmail API request failed")
        return response.json()

    def list_history(self, *, account_id: int, history_id: str) -> list[Mapping[str, Any]]:
        del account_id
        data = self._get("history", params={"startHistoryId": history_id, "historyTypes": "messageAdded"})
        events: list[Mapping[str, Any]] = []
        for history in data.get("history", []):
            current_history_id = str(history.get("id", history_id))
            for added in history.get("messagesAdded", []):
                message = added.get("message", {})
                message_id = message.get("id")
                if message_id:
                    events.append({"history_id": current_history_id, "message_id": str(message_id)})
        return events

    def fetch_message(self, *, account_id: int, message_id: str) -> Mapping[str, Any]:
        del account_id
        data = self._get(f"messages/{message_id}", params={"format": "full"})
        headers = {
            str(item.get("name", "")).lower(): str(item.get("value", ""))
            for item in data.get("payload", {}).get("headers", [])
        }
        customer_contact, customer_nickname = _parse_sender(headers.get("from"))
        raw_content = _extract_text(data.get("payload", {}))
        occurred_at = _parse_date(headers.get("date"))
        return {
            "external_message_id": str(data["id"]),
            "direction": "inbound",
            "status": "received",
            "occurred_at": occurred_at,
            "raw_content": raw_content,
            "customer_contact": customer_contact,
            "customer_nickname": customer_nickname,
        }


def _parse_sender(value: str | None) -> tuple[str | None, str | None]:
    if not value:
        return None, None
    match = re.match(r"^\\s*(.*?)\\s*<([^<>\\s]+)>\\s*$", value)
    if match:
        nickname = match.group(1).strip().strip('"') or None
        return match.group(2), nickname
    return value.strip() or None, None


def _parse_date(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    try:
        parsed = parsedate_to_datetime(value)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError, OverflowError):
        return datetime.now(timezone.utc)


def _decode_body_data(data: str) -> str:
    try:
        encoded = data.replace("-", "+").replace("_", "/")
        encoded += "=" * (-len(encoded) % 4)
        return base64.b64decode(encoded, validate=True).decode("utf-8", errors="replace")
    except (ValueError, TypeError, UnicodeError, base64.binascii.Error):
        return data


def _extract_text(payload: Mapping[str, Any]) -> str:
    body = payload.get("body", {})
    data = body.get("data")
    if isinstance(data, str):
        return _decode_body_data(data)
    parts = payload.get("parts", [])
    text_parts = [_extract_text(part) for part in parts if isinstance(part, Mapping)]
    return "\n".join(part for part in text_parts if part)
