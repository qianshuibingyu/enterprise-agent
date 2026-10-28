"""Outlook MCP client contract for user-initiated delegated reads."""

from dataclasses import dataclass
import os
from typing import Any, Mapping, Protocol


class OutlookMcpConfigurationError(RuntimeError):
    pass


@dataclass(frozen=True)
class OutlookAuthorization:
    external_account_id: str
    state: str


class OutlookMcpClient(Protocol):
    def authorization_url(self, *, state: str) -> str:
        ...

    def status(self, *, external_account_id: str) -> str:
        ...

    def list_messages(self, *, external_account_id: str) -> list[Mapping[str, Any]]:
        ...


def outlook_mcp_configured() -> bool:
    return bool(os.environ.get("OUTLOOK_MCP_URL"))


def require_outlook_mcp() -> None:
    if not outlook_mcp_configured():
        raise OutlookMcpConfigurationError("Outlook MCP is not configured")
