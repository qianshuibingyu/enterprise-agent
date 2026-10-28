"""Read-only Streamable HTTP client for guinacio/mcp-microsoft."""

from __future__ import annotations

import json
import os
from typing import Any

import httpx


class OutlookMcpError(RuntimeError):
    pass


class OutlookMcpConfigurationError(OutlookMcpError):
    pass


class OutlookMcpHttpClient:
    """Read-only MCP JSON-RPC client for the remote HTTP server.

    The MCP server performs Microsoft/Entra OAuth and OBO. This client forwards
    the already-authenticated caller bearer token and never persists it.
    """

    READ_TOOLS = {"list_emails", "read_email", "search_emails", "filter_emails"}

    def __init__(self, *, bearer_token: str, http: httpx.Client | None = None) -> None:
        base_url = os.environ.get("OUTLOOK_MCP_URL", "").rstrip("/")
        if not base_url:
            raise OutlookMcpConfigurationError("OUTLOOK_MCP_URL is not configured")
        if not bearer_token:
            raise OutlookMcpConfigurationError("Outlook MCP bearer token is required")
        self.url = f"{base_url}/mcp"
        self.bearer_token = bearer_token
        self.http = http or httpx.Client(
            timeout=float(os.environ.get("OUTLOOK_MCP_TIMEOUT_SECONDS", "20"))
        )
        self._request_id = 0
        self._session_id: str | None = None
        self._initialized = False

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/json, text/event-stream",
            "Authorization": f"Bearer {self.bearer_token}",
            "Content-Type": "application/json",
        }
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id
        return headers

    def _rpc(self, method: str, params: dict[str, Any] | None = None) -> Any:
        self._request_id += 1
        response = self.http.post(
            self.url,
            headers=self._headers(),
            json={
                "jsonrpc": "2.0",
                "id": self._request_id,
                "method": method,
                "params": params or {},
            },
        )
        if response.status_code in {401, 403}:
            raise OutlookMcpError("Outlook MCP authorization failed")
        if response.status_code >= 400:
            raise OutlookMcpError("Outlook MCP request failed")
        session_id = response.headers.get("Mcp-Session-Id")
        if session_id:
            self._session_id = session_id
        payload = self._decode_response(response)
        if isinstance(payload, dict) and payload.get("error"):
            raise OutlookMcpError("Outlook MCP returned an error")
        return payload.get("result") if isinstance(payload, dict) else payload

    @staticmethod
    def _decode_response(response: httpx.Response) -> Any:
        if "text/event-stream" not in response.headers.get("content-type", ""):
            return response.json()
        for line in response.text.splitlines():
            if line.startswith("data:"):
                return json.loads(line[5:].strip())
        raise OutlookMcpError("Outlook MCP returned no event data")

    def _notify(self, method: str) -> None:
        response = self.http.post(
            self.url,
            headers=self._headers(),
            json={"jsonrpc": "2.0", "method": method},
        )
        if response.status_code >= 400:
            raise OutlookMcpError("Outlook MCP notification failed")

    def initialize(self) -> None:
        if self._initialized:
            return
        self._rpc(
            "initialize",
            {
                "protocolVersion": "2025-11-25",
                "capabilities": {},
                "clientInfo": {"name": "enterprise-agent", "version": "0.1.0"},
            },
        )
        self._notify("notifications/initialized")
        self._initialized = True

    def call_read_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        if name not in self.READ_TOOLS:
            raise ValueError("only Outlook MCP read tools are allowed")
        self.initialize()
        result = self._rpc("tools/call", {"name": name, "arguments": arguments})
        if not isinstance(result, dict):
            return result
        content = result.get("content", [])
        texts = [
            item.get("text")
            for item in content
            if isinstance(item, dict) and item.get("type") == "text"
        ]
        if len(texts) == 1:
            try:
                return json.loads(texts[0])
            except (TypeError, json.JSONDecodeError):
                return texts[0]
        return texts

    def list_emails(self, *, folder: str = "inbox", count: int = 50) -> Any:
        return self.call_read_tool(
            "list_emails", {"folder": folder, "max_results": count}
        )

    def read_email(self, *, message_id: str) -> Any:
        return self.call_read_tool("read_email", {"message_id": message_id})
