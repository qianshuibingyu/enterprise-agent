import json

import httpx
import pytest

from app.outlook_mcp_http import OutlookMcpHttpClient, OutlookMcpError


class FakeTransport(httpx.BaseTransport):
    def __init__(self):
        self.calls = []

    def handle_request(self, request):
        self.calls.append(json.loads(request.content))
        body = self.calls[-1]
        if body.get("method") == "initialize":
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": {}})
        if body.get("method") == "tools/call":
            assert body["params"]["name"] == "list_emails"
            return httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "id": body["id"],
                    "result": {"content": [{"type": "text", "text": '{"messages": []}'}]},
                },
            )
        return httpx.Response(200, json={"jsonrpc": "2.0", "result": {}})


def test_outlook_mcp_client_only_calls_read_tool(monkeypatch):
    monkeypatch.setenv("OUTLOOK_MCP_URL", "https://mcp.example.test")
    transport = FakeTransport()
    client = OutlookMcpHttpClient(
        bearer_token="fixture-bearer",
        http=httpx.Client(transport=transport),
    )

    assert client.list_emails(count=10) == {"messages": []}
    assert any(call.get("method") == "initialize" for call in transport.calls)
    assert any(call.get("method") == "tools/call" for call in transport.calls)
    with pytest.raises(ValueError):
        client.call_read_tool("send_email", {})
