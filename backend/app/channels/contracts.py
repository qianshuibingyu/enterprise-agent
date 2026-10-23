from dataclasses import dataclass
from typing import Literal


ChannelType = Literal["gmail", "outlook", "whatsapp"]
ConnectionStatus = Literal[
    "not_connected",
    "authorizing",
    "connected",
    "blocked",
    "error",
    "revoked",
]


@dataclass(frozen=True)
class ProviderCapabilities:
    inbound: bool
    outbound: bool
    realtime: bool
    webhook: bool
    polling: bool
    attachments: bool
    requires_public_endpoint: bool


@dataclass(frozen=True)
class ProviderDescriptor:
    channel_type: ChannelType
    display_name: str
    provider_name: str
    integration_type: str
    guide: str
    capabilities: ProviderCapabilities
    real_integration: bool
    blocked_reason: str | None = None


@dataclass(frozen=True)
class AuthorizationStart:
    state: str
    authorization_url: str
    test_only: bool


@dataclass(frozen=True)
class ProviderResult:
    status: ConnectionStatus
    external_account_id: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    test_only: bool = False
