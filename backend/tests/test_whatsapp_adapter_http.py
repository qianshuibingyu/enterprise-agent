import httpx
import pytest

from app.whatsapp_adapter import (
    HttpWhatsAppAdapterClient,
    WhatsAppAdapterConfigurationError,
    WhatsAppAdapterUnavailableError,
)


def test_whatsapp_adapter_pairing_contract(monkeypatch):
    monkeypatch.setenv("WHATSAPP_ADAPTER_URL", "http://adapter.test")
    monkeypatch.setenv("WHATSAPP_ADAPTER_TOKEN", "fixture-token")

    def handler(request: httpx.Request):
        assert request.headers["authorization"] == "Bearer fixture-token"
        return httpx.Response(200, json={"qr": "fixture-qr", "expires_at": "soon"})

    client = HttpWhatsAppAdapterClient(
        http=httpx.Client(transport=httpx.MockTransport(handler))
    )
    result = client.start_pairing(channel_account_id=7)

    assert result.qr == "fixture-qr"
    assert result.expires_at == "soon"


def test_whatsapp_adapter_status_preserves_qr(monkeypatch):
    monkeypatch.setenv("WHATSAPP_ADAPTER_URL", "http://adapter.test")
    monkeypatch.setenv("WHATSAPP_ADAPTER_TOKEN", "fixture-token")

    def handler(request: httpx.Request):
        assert request.method == "GET"
        return httpx.Response(
            200,
            json={
                "state": "awaiting_authorization",
                "qr": "data:image/png;base64,fixture-qr",
                "expires_at": "2026-11-02T03:30:00.000Z",
                "external_account_id": None,
                "detail": None,
            },
        )

    client = HttpWhatsAppAdapterClient(
        http=httpx.Client(transport=httpx.MockTransport(handler))
    )
    result = client.status(channel_account_id=7)

    assert result.state == "awaiting_authorization"
    assert result.qr == "data:image/png;base64,fixture-qr"
    assert result.expires_at == "2026-11-02T03:30:00.000Z"


def test_whatsapp_adapter_classifies_bridge_unavailable_and_token_mismatch(monkeypatch):
    monkeypatch.setenv("WHATSAPP_ADAPTER_URL", "http://adapter.test")
    monkeypatch.setenv("WHATSAPP_ADAPTER_TOKEN", "fixture-token")

    unavailable = HttpWhatsAppAdapterClient(
        http=httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(503)))
    )
    with pytest.raises(WhatsAppAdapterUnavailableError, match="HTTP 503"):
        unavailable.status(channel_account_id=7)

    unauthorized = HttpWhatsAppAdapterClient(
        http=httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(403)))
    )
    with pytest.raises(WhatsAppAdapterConfigurationError):
        unauthorized.status(channel_account_id=7)
