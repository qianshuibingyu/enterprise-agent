from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderCapabilities:
    inbound: bool
    outbound: bool
    realtime: bool
    webhook: bool = False
    polling: bool = False
    attachments: bool = False
    requires_public_endpoint: bool = False


@dataclass(frozen=True)
class ProviderDescriptor:
    key: str
    display_name: str
    capabilities: ProviderCapabilities
    authorization_owner: str
    ingress_kind: str
    test_only: bool = False
    legacy: bool = False
