import httpx

from app.whatsapp_adapter import HttpWhatsAppAdapterClient


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
