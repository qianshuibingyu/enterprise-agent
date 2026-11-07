from types import SimpleNamespace

import httpx

from app import business_routes


def message(*, provider: str, raw_content: str, gmail_credential_ciphertext=None, outlook_credential_ciphertext=None):
    account = SimpleNamespace(
        id=7,
        channel_type="gmail" if provider.startswith("gmail") else "outlook",
        external_account_id="outlook-account",
        gmail_credential_ciphertext=gmail_credential_ciphertext,
        outlook_credential_ciphertext=outlook_credential_ciphertext,
    )
    return SimpleNamespace(
        channel_account=account,
        external_message_id="provider-message-1",
        provider=provider,
        raw_content=raw_content,
    )


def test_gmail_provider_content_is_sanitized_before_return(monkeypatch):
    class FakeGmailClient:
        def __init__(self, *, refresh_token):
            assert refresh_token == "fixture-refresh"

        def fetch_message(self, *, account_id, message_id):
            assert (account_id, message_id) == (7, "provider-message-1")
            return {"raw_content": "<p>fresh</p><script>drop</script>"}

    monkeypatch.setattr(business_routes, "GmailApiClient", FakeGmailClient)
    monkeypatch.setattr(business_routes, "decrypt_refresh_token", lambda value: "fixture-refresh")

    content, failure = business_routes._safe_provider_content(
        message(
            provider="gmail_api_pubsub",
            raw_content="cached",
            gmail_credential_ciphertext="ciphertext",
        )
    )

    assert failure is None
    assert content["display_text"] == "fresh"
    assert content["content_format"] == "text/plain"


def test_whatsapp_provider_content_is_refetched_and_sanitized(monkeypatch):
    class FakeWhatsAppClient:
        def __init__(self):
            pass

        def fetch_message(self, *, channel_account_id, message_id):
            assert (channel_account_id, message_id) == (7, "provider-message-1")
            return {"raw_content": "<p>fresh WhatsApp</p><script>drop</script>"}

    monkeypatch.setattr(business_routes, "HttpWhatsAppAdapterClient", FakeWhatsAppClient)

    content, failure = business_routes._safe_provider_content(
        message(
            provider="whatsapp_web_baileys",
            raw_content="cached WhatsApp",
        )
    )

    assert failure is None
    assert content["display_text"] == "fresh WhatsApp"
    assert content["content_format"] == "text/plain"



    class FakeOutlookClient:
        def fetch_message(self, *, external_account_id, message_id):
            raise httpx.ConnectError("provider unavailable")

    monkeypatch.setattr(business_routes, "outlook_graph_client_for_ciphertext", lambda value: FakeOutlookClient())

    content, failure = business_routes._safe_provider_content(
        message(
            provider="outlook_mcp_graph",
            raw_content="<p>cached</p><iframe>drop</iframe>",
            outlook_credential_ciphertext="ciphertext",
        )
    )

    assert failure == "provider_refetch_failed"
    assert content["display_text"] == "cached"
    assert content["content_format"] == "text/plain"
