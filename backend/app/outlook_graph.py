"""Read-only Microsoft Graph client for account-scoped Outlook access."""

from __future__ import annotations

import os
from typing import Any
from urllib.parse import quote

import httpx

from app.outlook_credentials import OutlookCredentialError, decrypt_refresh_token
from app.outlook_oauth import OutlookOAuthClient


class OutlookGraphError(RuntimeError):
    pass


class OutlookGraphClient:
    MAIL_FOLDERS = ("inbox", "junkemail")

    @staticmethod
    def _identity_matches(identity: dict[str, Any], external_account_id: str | None) -> bool:
        """Compare the stored mapping against every stable Graph identity field.

        Older accounts stored an OIDC-style subject while Graph /me returns a
        different id shape, so all stable Graph identity fields are accepted.
        A total mismatch still fails closed: it can mean the account was
        re-authorized to a different mailbox.
        """
        if not external_account_id:
            return False
        target = external_account_id.strip().lower()
        candidates = {
            str(identity.get("id") or "").lower(),
            str(identity.get("mail") or "").lower(),
            str(identity.get("userPrincipalName") or "").lower(),
        }
        return target in candidates

    def __init__(self, *, refresh_token: str, http: httpx.Client | None = None) -> None:
        self.refresh_token = refresh_token
        self.http = http or httpx.Client(
            timeout=float(os.environ.get("OUTLOOK_TIMEOUT_SECONDS", "20"))
        )
        self.oauth = OutlookOAuthClient(http=self.http)
        self._access_token: str | None = None

    def _token(self) -> str:
        if self._access_token:
            return self._access_token
        response = self.http.post(
            self.oauth.token_endpoint,
            data={
                "client_id": self.oauth.client_id,
                "client_secret": self.oauth.client_secret,
                "grant_type": "refresh_token",
                "refresh_token": self.refresh_token,
                "scope": self.oauth.scopes,
            },
        )
        if response.status_code in {401, 403}:
            raise OutlookGraphError("Outlook authorization expired")
        if response.status_code >= 400:
            raise OutlookGraphError("Outlook token refresh failed")
        token = response.json().get("access_token")
        if not isinstance(token, str) or not token:
            raise OutlookGraphError("Outlook token response is invalid")
        self._access_token = token
        return token

    def _get(self, path: str, params: dict[str, str] | None = None) -> dict[str, Any]:
        response = self.http.get(
            f"https://graph.microsoft.com/v1.0{path}",
            headers={"Authorization": f"Bearer {self._token()}"},
            params=params,
        )
        if response.status_code in {401, 403}:
            raise OutlookGraphError("Outlook Graph authorization failed")
        if response.status_code >= 400:
            raise OutlookGraphError("Outlook Graph request failed")
        payload = response.json()
        if not isinstance(payload, dict):
            raise OutlookGraphError("Outlook Graph response is invalid")
        return payload

    def list_emails(self, *, external_account_id: str, count: int = 50) -> list[dict[str, Any]]:
        """Read new (unread) messages from the account's Inbox and Junk folders.

        The unread window decides which mail enters the operations queue, which
        is why it cannot also be the only source of per-message metadata: once a
        user opens a message it leaves this window, so a row ingested earlier
        could never receive a field added to the contract later. ``webLink`` is
        repaired by :meth:`message_web_link` instead of by widening this read
        into "every message ever received".
        """
        identity = self._get("/me", {"$select": "id,mail,userPrincipalName"})
        if not self._identity_matches(identity, external_account_id):
            raise OutlookGraphError("Outlook account mapping failed")
        messages: list[dict[str, Any]] = []
        for folder in self.MAIL_FOLDERS:
            payload = self._get(
                f"/me/mailFolders/{folder}/messages",
                {
                    "$top": str(count),
                    "$filter": "receivedDateTime ge 1970-01-01T00:00:00Z and isRead eq false",
                    "$orderby": "receivedDateTime desc",
                    "$select": "id,receivedDateTime,isRead,bodyPreview,body,from,webLink,hasAttachments",
                },
            )
            values = payload.get("value", [])
            messages.extend(item for item in values if isinstance(item, dict))
        return messages

    def fetch_message(
        self,
        *,
        external_account_id: str,
        message_id: str,
    ) -> dict[str, Any]:
        """Fetch one message after verifying the delegated account mapping."""
        identity = self._get("/me", {"$select": "id,mail,userPrincipalName"})
        if not self._identity_matches(identity, external_account_id):
            raise OutlookGraphError("Outlook account mapping failed")
        message = self._get(
            f"/me/messages/{quote(message_id.strip(), safe='')}",
            {
                "$select": "id,receivedDateTime,bodyPreview,body,from,webLink,hasAttachments",
            },
        )
        if message.get("id") != message_id:
            raise OutlookGraphError("Outlook message identity failed")
        return message

    def message_web_link(self, message_id: str) -> str | None:
        """Return the provider-issued web link for one stored message.

        Used to repair rows that were ingested before the link was persisted;
        Graph is the only authority for the link, so no URL shape is invented.
        """
        response = self.http.get(
            f"https://graph.microsoft.com/v1.0/me/messages/{quote(message_id.strip(), safe='')}",
            headers={"Authorization": f"Bearer {self._token()}"},
            params={"$select": "webLink"},
        )
        if response.status_code >= 400:
            return None
        payload = response.json()
        link = payload.get("webLink") if isinstance(payload, dict) else None
        return link if isinstance(link, str) and link else None


def outlook_graph_client_for_ciphertext(ciphertext: str) -> OutlookGraphClient:
    try:
        return OutlookGraphClient(refresh_token=decrypt_refresh_token(ciphertext))
    except OutlookCredentialError as exc:
        raise OutlookGraphError("Outlook credential is unavailable") from exc
