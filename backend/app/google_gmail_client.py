"""Google OAuth/Gmail Watch client used after the operator grants access."""

from __future__ import annotations

from dataclasses import dataclass
import os
from urllib.parse import urlencode

import httpx

from app.gmail_oauth import GmailAuthorization, GmailOAuthConfigurationError

GOOGLE_AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
GMAIL_API_URL = "https://gmail.googleapis.com/gmail/v1/users"


class GoogleOAuthHttpClient:
    def __init__(self, *, http: httpx.Client | None = None) -> None:
        self.client_id = os.environ.get("GMAIL_CLIENT_ID")
        self.client_secret = os.environ.get("GMAIL_CLIENT_SECRET")
        self.redirect_uri = os.environ.get("GMAIL_REDIRECT_URI")
        self.scopes = os.environ.get(
            "GMAIL_SCOPES", "https://www.googleapis.com/auth/gmail.readonly"
        )
        if not self.client_id or not self.client_secret or not self.redirect_uri:
            raise GmailOAuthConfigurationError("Gmail OAuth configuration is incomplete")
        self.http = http or httpx.Client(timeout=float(os.environ.get("GMAIL_TIMEOUT_SECONDS", "20")))

    def authorization_url(self, *, state: str) -> str:
        query = urlencode({
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "scope": self.scopes,
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
        })
        return f"{GOOGLE_AUTHORIZE_URL}?{query}"

    def exchange_code(self, *, code: str, state: str) -> GmailAuthorization:
        response = self.http.post(
            GOOGLE_TOKEN_URL,
            data={
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "code": code,
                "redirect_uri": self.redirect_uri,
                "grant_type": "authorization_code",
            },
        )
        if response.status_code >= 400:
            raise GmailOAuthConfigurationError("Google OAuth code exchange failed")
        data = response.json()
        granted_scopes = set(str(data.get("scope", "")).split())
        required_scope = "https://www.googleapis.com/auth/gmail.readonly"
        if required_scope not in granted_scopes:
            raise GmailOAuthConfigurationError("Google OAuth did not grant Gmail readonly scope")
        access_token = data.get("access_token")
        if not isinstance(access_token, str) or not access_token:
            raise GmailOAuthConfigurationError("Google OAuth response has no access token")
        # The refresh token is handed to a server-side encrypted store by the
        # caller; this client never logs or returns it to the browser.
        refresh_token = data.get("refresh_token")
        identity = self.http.get(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if identity.status_code >= 400:
            raise GmailOAuthConfigurationError("Google account identity lookup failed")
        external_account_id = identity.json().get("sub")
        if not isinstance(external_account_id, str) or not external_account_id:
            raise GmailOAuthConfigurationError("Google account identity is missing")
        return GmailAuthorization(
            access_token=access_token,
            refresh_token=refresh_token if isinstance(refresh_token, str) else None,
            external_account_id=external_account_id,
        )


@dataclass(frozen=True)
class GmailWatchResult:
    history_id: str
    expiration: str | None


class GmailWatchHttpClient:
    def __init__(self, *, access_token: str, http: httpx.Client | None = None) -> None:
        if not access_token:
            raise GmailOAuthConfigurationError("Gmail access token is required")
        self.access_token = access_token
        self.http = http or httpx.Client(timeout=float(os.environ.get("GMAIL_TIMEOUT_SECONDS", "20")))

    def start_watch(self, *, topic_name: str) -> GmailWatchResult:
        response = self.http.post(
            f"{GMAIL_API_URL}/me/watch",
            headers={"Authorization": f"Bearer {self.access_token}"},
            json={"topicName": topic_name, "labelIds": ["INBOX"]},
        )
        if response.status_code >= 400:
            raise GmailOAuthConfigurationError("Gmail Watch creation failed")
        data = response.json()
        return GmailWatchResult(
            history_id=str(data["historyId"]),
            expiration=str(data["expiration"]) if data.get("expiration") else None,
        )
