from collections.abc import Mapping
from typing import Any

from .contracts import ProviderCapabilities


class FakeTestProvider:
    """In-memory provider used only by isolated tests; never a real connection."""

    name = "fake_test_only"
    test_only = True

    def __init__(
        self,
        channel_type: str,
        capabilities: ProviderCapabilities,
        *,
        messages: list[Mapping[str, Any]] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.channel_type = channel_type
        self.capabilities = capabilities
        self.messages = list(messages or [])
        self.error = error
        self.receive_calls = 0
        self.revoke_calls = 0

    def receive(self, *, external_account_id: str) -> list[Mapping[str, Any]]:
        del external_account_id
        self.receive_calls += 1
        if self.error is not None:
            raise self.error
        return list(self.messages)

    def revoke(self) -> None:
        self.revoke_calls += 1
