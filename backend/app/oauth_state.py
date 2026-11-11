"""Short-lived, one-time OAuth state boundary for provider authorization."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import secrets


@dataclass(frozen=True)
class OAuthState:
    value: str
    channel_account_id: int
    expires_at: datetime


class OAuthStateStore:
    """In-memory seam for tests; production must use a server-side store."""

    def __init__(self, *, ttl: timedelta = timedelta(minutes=10)) -> None:
        self._ttl = ttl
        self._states: dict[str, OAuthState] = {}

    def issue(self, *, channel_account_id: int) -> OAuthState:
        state = OAuthState(
            value=secrets.token_urlsafe(32),
            channel_account_id=channel_account_id,
            expires_at=datetime.now(timezone.utc) + self._ttl,
        )
        self._states[state.value] = state
        return state

    def consume(self, value: str, *, channel_account_id: int) -> OAuthState | None:
        state = self._states.get(value)
        if state is None or state.channel_account_id != channel_account_id:
            return None
        return self._consume_valid(value, state)

    def invalidate_account(self, channel_account_id: int) -> None:
        for value, state in list(self._states.items()):
            if state.channel_account_id == channel_account_id:
                self._states.pop(value, None)

    def validate_any(self, value: str) -> OAuthState | None:
        state = self._states.get(value)
        if state is None:
            return None
        if state.expires_at <= datetime.now(timezone.utc):
            self._states.pop(value, None)
            return None
        return state

    def consume_any(self, value: str) -> OAuthState | None:
        """Consume a valid state when the callback has no account query value.

        The state remains the account binding. Callers must authorize the
        returned account before using it; the callback must not trust a
        browser-supplied account id.
        """
        state = self._states.get(value)
        if state is None:
            return None
        return self._consume_valid(value, state)

    def _consume_valid(self, value: str, state: OAuthState) -> OAuthState | None:
        if state.expires_at <= datetime.now(timezone.utc):
            self._states.pop(value, None)
            return None
        # Consume only after the binding and expiry checks succeed.
        return self._states.pop(value)
