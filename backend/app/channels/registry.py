from .contracts import ProviderCapabilities, ProviderDescriptor


_DESCRIPTORS = {
    "gmail": ProviderDescriptor(
        key="gmail_api_pubsub",
        display_name="Gmail",
        capabilities=ProviderCapabilities(
            inbound=True,
            outbound=False,
            realtime=True,
            webhook=True,
            attachments=True,
            requires_public_endpoint=True,
        ),
        authorization_owner="google_oauth",
        ingress_kind="pubsub_webhook",
    ),
    "outlook": ProviderDescriptor(
        key="outlook_mcp_graph",
        display_name="Outlook",
        capabilities=ProviderCapabilities(
            inbound=True,
            outbound=False,
            realtime=False,
            polling=True,
            attachments=True,
        ),
        authorization_owner="outlook_mcp_entra",
        ingress_kind="mcp",
    ),
    "whatsapp": ProviderDescriptor(
        key="whatsapp_web_baileys",
        display_name="WhatsApp",
        capabilities=ProviderCapabilities(
            inbound=True,
            outbound=False,
            realtime=True,
            attachments=True,
        ),
        authorization_owner="account_owner_qr",
        ingress_kind="baileys_adapter",
    ),
}

_LEGACY_KEYS = {
    "outlook_imap": "outlook",
}


def provider_descriptor(channel_type: str) -> ProviderDescriptor:
    try:
        return _DESCRIPTORS[channel_type]
    except KeyError as exc:
        raise ValueError(f"unknown channel type: {channel_type}") from exc


def provider_descriptor_by_key(provider: str) -> ProviderDescriptor:
    channel_type = _LEGACY_KEYS.get(provider)
    if channel_type is None:
        for candidate, descriptor in _DESCRIPTORS.items():
            if descriptor.key == provider:
                return descriptor
        raise ValueError(f"unknown provider: {provider}")
    descriptor = _DESCRIPTORS[channel_type]
    return ProviderDescriptor(
        key=provider,
        display_name=descriptor.display_name,
        capabilities=descriptor.capabilities,
        authorization_owner=descriptor.authorization_owner,
        ingress_kind=descriptor.ingress_kind,
        legacy=True,
    )


def provider_descriptors() -> tuple[ProviderDescriptor, ...]:
    return tuple(_DESCRIPTORS.values())
