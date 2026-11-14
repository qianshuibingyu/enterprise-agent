"""Microsoft identity platform OAuth client for read-only Outlook access."""

from __future__ import annotations

from dataclasses import dataclass
import os
from urllib.parse import urlencode

import httpx

from app.outlook_mcp import OutlookMcpConfigurationError
from app.provider_transport import provider_http_client


class OutlookOAuthProviderError(OutlookMcpConfigurationError):
    """A Microsoft OAuth/Graph response rejected the authorization flow."""

    def __init__(self, message: str, *, stage: str, provider_code: str | None = None):
        super().__init__(message)
        self.stage = stage
        self.provider_code = provider_code


@dataclass(frozen=True)
class OutlookAuthorization:
    access_token: str
    refresh_token: str | None
    external_account_id: str
    email: str | None


class OutlookOAuthClient:
    def __init__(self, *, http: httpx.Client | None = None) -> None:
        # `common` is required for an app that supports personal Outlook
        # accounts as well as organizational accounts. A tenant UUID would
        # exclude personal-account sign-in from this authority.
        configured_authority = os.environ.get("OUTLOOK_AUTHORITY", "").strip()
        configured_tenant = os.environ.get("OUTLOOK_TENANT_ID", "").strip()
        # Existing deployments may have copied the tenant UUID into the new
        # authority setting. For an app registered for personal accounts,
        # that value would exclude outlook.com users; treat it as legacy and
        # use Microsoft's common authority.
        self.tenant_id = (
            "common"
            if not configured_authority or configured_authority == configured_tenant
            else configured_authority
        )
        self.client_id = os.environ.get("OUTLOOK_CLIENT_ID")
        self.client_secret = os.environ.get("OUTLOOK_CLIENT_SECRET")
        self.redirect_uri = os.environ.get("OUTLOOK_REDIRECT_URI")
        configured_scopes = os.environ.get(
            "OUTLOOK_SCOPES",
            "openid profile email offline_access Mail.Read",
        )
        # Graph /me is used to bind the OAuth result to ChannelAccount. Ensure
        # the delegated identity permission is requested even when an older
        # deployment has an OUTLOOK_SCOPES value without User.Read.
        scope_values = configured_scopes.split()
        if "User.Read" not in scope_values:
            scope_values.append("User.Read")
        self.scopes = " ".join(dict.fromkeys(scope_values))
        if not self.client_id or not self.client_secret or not self.redirect_uri:
            raise OutlookMcpConfigurationError("Outlook OAuth configuration is incomplete")
        self.http = http or provider_http_client(
            float(os.environ.get("OUTLOOK_TIMEOUT_SECONDS", "20"))
        )
        self.authorize_endpoint = (
            f"https://login.microsoftonline.com/{self.tenant_id}/oauth2/v2.0/authorize"
        )
        self.token_endpoint = (
            f"https://login.microsoftonline.com/{self.tenant_id}/oauth2/v2.0/token"
        )
        self.userinfo_endpoint = "https://graph.microsoft.com/v1.0/me"

    def authorization_url(self, *, state: str) -> str:
        query = urlencode({
            "client_id": self.client_id,
            "response_type": "code",
            "redirect_uri": self.redirect_uri,
            "response_mode": "query",
            "scope": self.scopes,
            "state": state,
        })
        return f"{self.authorize_endpoint}?{query}"

    def exchange_code(self, *, code: str) -> OutlookAuthorization:
        response = self.http.post(
            self.token_endpoint,
            data={
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "code": code,
                "redirect_uri": self.redirect_uri,
                "grant_type": "authorization_code",
                "scope": self.scopes,
            },
        )
        if response.status_code >= 400:
            provider_code = _provider_error_code(response)
            raise OutlookOAuthProviderError(
                "Microsoft OAuth code exchange failed",
                stage="token_exchange",
                provider_code=provider_code,
            )
        data = response.json()
        access_token = data.get("access_token")
        if not isinstance(access_token, str) or not access_token:
            raise OutlookOAuthProviderError(
                "Microsoft OAuth response has no access token",
                stage="token_exchange",
                provider_code=_provider_error_code(response),
            )
        identity = self.http.get(
            self.userinfo_endpoint,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if identity.status_code >= 400:
            provider_code = _provider_error_code(identity)
            raise OutlookOAuthProviderError(
                "Microsoft account identity lookup failed",
                stage="identity_lookup",
                provider_code=provider_code,
            )
        profile = identity.json()
        subject = profile.get("id")
        if not isinstance(subject, str) or not subject:
            raise OutlookOAuthProviderError(
                "Microsoft account identity is missing",
                stage="identity_lookup",
                provider_code=_provider_error_code(identity),
            )
        email = profile.get("mail") or profile.get("userPrincipalName")
        return OutlookAuthorization(
            access_token=access_token,
            refresh_token=data.get("refresh_token") if isinstance(data.get("refresh_token"), str) else None,
            external_account_id=subject,
            email=email if isinstance(email, str) else None,
        )


def _provider_error_code(response: httpx.Response) -> str | None:
    """Extract Microsoft's non-sensitive error identifier for diagnostics."""
    try:
        payload = response.json()
    except ValueError:
        return None
    code = payload.get("error") if isinstance(payload, dict) else None
    if isinstance(code, dict):
        code = code.get("code")
    return code if isinstance(code, str) and code else None
