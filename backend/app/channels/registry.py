from app.channels.contracts import ProviderCapabilities, ProviderDescriptor
from app.channels.providers import FakeTestProvider, UnconfiguredRealProvider


PROVIDERS = {
    "gmail": ProviderDescriptor(
        channel_type="gmail",
        display_name="Gmail",
        provider_name="gmail_api_pubsub",
        integration_type="event_hook",
        guide="需要 Google OAuth、Gmail API 和 Pub/Sub；Pub/Sub 只提供变化信号，详情由 History/Message API 拉取。",
        capabilities=ProviderCapabilities(
            inbound=True, outbound=False, realtime=True, webhook=True, polling=False,
            attachments=True, requires_public_endpoint=True,
        ),
        real_integration=False,
        blocked_reason="real_provider_not_configured",
    ),
    "outlook": ProviderDescriptor(
        channel_type="outlook",
        display_name="Outlook IMAP",
        provider_name="outlook_imap",
        integration_type="mail_listener",
        guide="首期只接收入站邮件；生产优先确认 OAuth2/XOAuth2，不默认使用 Basic Auth。",
        capabilities=ProviderCapabilities(
            inbound=True, outbound=False, realtime=False, webhook=False, polling=True,
            attachments=True, requires_public_endpoint=False,
        ),
        real_integration=False,
        blocked_reason="real_provider_not_configured",
    ),
    "whatsapp": ProviderDescriptor(
        channel_type="whatsapp",
        display_name="WhatsApp Web（Baileys）",
        provider_name="whatsapp_web_baileys",
        integration_type="chat_channel",
        guide="通过独立 WhatsApp adapter service 管理 QR、auth state、长连接和入站；不是 Meta Cloud API。",
        capabilities=ProviderCapabilities(
            inbound=True, outbound=True, realtime=True, webhook=False, polling=False,
            attachments=True, requires_public_endpoint=False,
        ),
        real_integration=False,
        blocked_reason="baileys_adapter_not_configured",
    ),
}


def provider_descriptor(channel_type: str) -> ProviderDescriptor:
    try:
        return PROVIDERS[channel_type]
    except KeyError as exc:
        raise ValueError("unsupported channel type") from exc


def provider_for(channel_type: str, *, test_mode: bool):
    descriptor = provider_descriptor(channel_type)
    if test_mode:
        return FakeTestProvider(channel_type, descriptor.capabilities)
    return UnconfiguredRealProvider(channel_type, descriptor.blocked_reason or "provider unavailable")
