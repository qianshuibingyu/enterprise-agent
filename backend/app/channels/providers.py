from typing import Mapping, Protocol

from app.channels.contracts import (
    AuthorizationStart,
    ChannelType,
    ProviderCapabilities,
    ProviderResult,
)


class ChannelProvider(Protocol):
    """Provider-neutral contract; adapters never receive raw browser tokens."""

    name: str
    test_only: bool

    def capabilities(self) -> ProviderCapabilities:
        ...

    def authorize_start(self, *, state: str) -> AuthorizationStart:
        ...

    def authorize_callback(self, *, state: str, callback_data: dict[str, str]) -> ProviderResult:
        ...

    def check_connection(self, *, external_account_id: str | None = None) -> ProviderResult:
        ...

    def receive(self, *, external_account_id: str) -> list[Mapping[str, object]]:
        ...

    def send(self, *, external_account_id: str, message: dict[str, str]) -> ProviderResult:
        ...

    def revoke(self, *, external_account_id: str) -> ProviderResult:
        ...


class FakeTestProvider:
    """Explicit test-only provider. It can never represent a real connection."""

    test_only = True

    def __init__(
        self,
        channel_type: ChannelType,
        capabilities: ProviderCapabilities,
        messages: list[dict[str, object]] | None = None,
        authorized: bool = True,
        failure: str | None = None,
    ):
        self.channel_type = channel_type
        self.name = f"fake-test:{channel_type}"
        self._capabilities = capabilities
        self._messages = list(messages or [])
        self.authorized = authorized
        self.failure = failure
        self.receive_calls = 0
        self.revoke_calls = 0

    def capabilities(self) -> ProviderCapabilities:
        return self._capabilities

    def authorize_start(self, *, state: str) -> AuthorizationStart:
        return AuthorizationStart(
            state=state,
            authorization_url=f"/fake-callback?state={state}",
            test_only=True,
        )

    def authorize_callback(self, *, state: str, callback_data: dict[str, str]) -> ProviderResult:
        if callback_data.get("result") == "error":
            return ProviderResult(
                status="error",
                error_code="fake_provider_error",
                error_message="测试 provider 模拟错误",
                test_only=True,
            )
        return ProviderResult(
            status="connected",
            external_account_id=f"fake-test:{self.channel_type}:{state}",
            test_only=True,
        )

    def check_connection(self, *, external_account_id: str | None = None) -> ProviderResult:
        if self.failure == "expired":
            return ProviderResult(status="revoked", error_code="credential_expired", test_only=True)
        if not external_account_id or not self.authorized:
            return ProviderResult(status="not_connected", test_only=True)
        return ProviderResult(status="connected", external_account_id=external_account_id, test_only=True)

    def receive(self, *, external_account_id: str) -> list[Mapping[str, object]]:
        self.receive_calls += 1
        if self.failure == "rate_limited":
            raise RuntimeError("fake provider rate limited")
        if self.failure == "temporary":
            raise RuntimeError("fake provider temporary failure")
        if not self.authorized or self.failure == "expired":
            raise RuntimeError("fake provider authorization revoked")
        return list(self._messages)

    def send(self, *, external_account_id: str, message: dict[str, str]) -> ProviderResult:
        return ProviderResult(status="error", error_code="fake_send_disabled", test_only=True)

    def revoke(self, *, external_account_id: str) -> ProviderResult:
        self.revoke_calls += 1
        self.authorized = False
        return ProviderResult(status="revoked", test_only=True)


class UnconfiguredRealProvider:
    """Safe placeholder: real authorization is blocked until provider config is verified."""

    test_only = False

    def __init__(self, channel_type: ChannelType, reason: str):
        self.channel_type = channel_type
        self.name = channel_type
        self.reason = reason

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            inbound=False, outbound=False, realtime=False, webhook=False,
            polling=False, attachments=False, requires_public_endpoint=False,
        )

    def authorize_start(self, *, state: str) -> AuthorizationStart:
        raise RuntimeError(self.reason)

    def authorize_callback(self, *, state: str, callback_data: dict[str, str]) -> ProviderResult:
        return ProviderResult(status="blocked", error_code="provider_not_configured", error_message=self.reason)

    def check_connection(self, *, external_account_id: str | None = None) -> ProviderResult:
        return ProviderResult(status="blocked", error_code="provider_not_configured", error_message=self.reason)

    def receive(self, *, external_account_id: str) -> list[Mapping[str, object]]:
        raise RuntimeError(self.reason)

    def send(self, *, external_account_id: str, message: dict[str, str]) -> ProviderResult:
        return ProviderResult(status="blocked", error_code="provider_not_configured", error_message=self.reason)

    def revoke(self, *, external_account_id: str) -> ProviderResult:
        return ProviderResult(status="revoked")

    # Compatibility with the current route naming while callers migrate.
    start_authorization = authorize_start
    complete_authorization = authorize_callback
