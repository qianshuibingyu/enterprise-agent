"""Google OAuth and Gmail Watch contracts owned by this backend."""

from dataclasses import dataclass
import os
from typing import Protocol

from app.oauth_state import OAuthStateStore


class GmailOAuthConfigurationError(RuntimeError):
    pass


@dataclass(frozen=True)
class GmailAuthorization:
    access_token: str
    refresh_token: str | None
    external_account_id: str


class GmailOAuthClient(Protocol):
    def authorization_url(self, *, state: str) -> str:
        ...

    def exchange_code(self, *, code: str, state: str) -> GmailAuthorization:
        ...


class GmailWatchClient(Protocol):
    def start_watch(self, *, external_account_id: str) -> str:
        ...

    def stop_watch(self, *, external_account_id: str) -> None:
        ...


def gmail_oauth_configured() -> bool:
    return bool(
        os.environ.get("GMAIL_CLIENT_ID")
        and os.environ.get("GMAIL_CLIENT_SECRET")
        and os.environ.get("GMAIL_REDIRECT_URI")
    )


def issue_gmail_state(store: OAuthStateStore, *, channel_account_id: int) -> str:
    if not gmail_oauth_configured():
        raise GmailOAuthConfigurationError("Gmail OAuth is not configured")
    return store.issue(channel_account_id=channel_account_id).value
