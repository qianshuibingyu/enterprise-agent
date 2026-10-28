"""Provider runtime control contracts.

The backend owns authorization and account scope, while protocol-specific
runtimes own WhatsApp/Baileys sessions, Google API calls, or Outlook MCP
sessions. Concrete clients are injected so tests never need external access.
"""

from dataclasses import dataclass
from typing import Any, Mapping, Protocol


@dataclass(frozen=True)
class RuntimeStatus:
    state: str
    external_account_id: str | None = None
    detail: str | None = None


@dataclass(frozen=True)
class PairingQr:
    value: str
    expires_at: str


class WhatsAppAdapter(Protocol):
    def start_pairing(self, *, account_id: int) -> PairingQr:
        ...

    def status(self, *, account_id: int) -> RuntimeStatus:
        ...

    def disconnect(self, *, account_id: int) -> RuntimeStatus:
        ...

    def receive(self, *, account_id: int) -> list[Mapping[str, Any]]:
        ...


class GmailRuntime(Protocol):
    def start_watch(self, *, account_id: int) -> RuntimeStatus:
        ...

    def stop_watch(self, *, account_id: int) -> RuntimeStatus:
        ...

    def reconcile(self, *, account_id: int, history_id: str) -> list[Mapping[str, Any]]:
        ...


class OutlookMcpRuntime(Protocol):
    def authorization_url(self, *, account_id: int) -> str:
        ...

    def status(self, *, account_id: int) -> RuntimeStatus:
        ...

    def list_messages(self, *, account_id: int) -> list[Mapping[str, Any]]:
        ...
