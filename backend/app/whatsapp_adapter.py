"""Client contract for the project-owned WhatsApp/Baileys adapter."""

from dataclasses import dataclass
import os
from typing import Any, Mapping, Protocol

import httpx


class WhatsAppAdapterConfigurationError(RuntimeError):
    pass


@dataclass(frozen=True)
class PairingResponse:
    qr: str
    expires_at: str


@dataclass(frozen=True)
class AdapterStatus:
    state: str
    external_account_id: str | None = None
    detail: str | None = None


class HttpWhatsAppAdapterClient:
    def __init__(self, *, http: httpx.Client | None = None) -> None:
        base_url = os.environ.get("WHATSAPP_ADAPTER_URL", "").rstrip("/")
        token = os.environ.get("WHATSAPP_ADAPTER_TOKEN", "")
        if not base_url or not token:
            raise WhatsAppAdapterConfigurationError("WhatsApp adapter is not configured")
        self.base_url = base_url
        self.token = token
        self.http = http or httpx.Client(timeout=float(os.environ.get("WHATSAPP_CONNECT_TIMEOUT_SECONDS", "10")))

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        response = self.http.request(
            method,
            f"{self.base_url}{path}",
            headers={"Authorization": f"Bearer {self.token}"},
            **kwargs,
        )
        if response.status_code in {401, 403}:
            raise WhatsAppAdapterConfigurationError("WhatsApp adapter authorization failed")
        if response.status_code >= 400:
            raise WhatsAppAdapterConfigurationError("WhatsApp adapter request failed")
        return response.json()

    def start_pairing(self, *, channel_account_id: int) -> PairingResponse:
        data = self._request("POST", f"/internal/whatsapp/accounts/{channel_account_id}/pair")
        return PairingResponse(qr=str(data["qr"]), expires_at=str(data["expires_at"]))

    def status(self, *, channel_account_id: int) -> AdapterStatus:
        data = self._request("GET", f"/internal/whatsapp/accounts/{channel_account_id}/status")
        return AdapterStatus(
            state=str(data["state"]),
            external_account_id=data.get("external_account_id"),
            detail=data.get("detail"),
        )

    def disconnect(self, *, channel_account_id: int) -> AdapterStatus:
        data = self._request("POST", f"/internal/whatsapp/accounts/{channel_account_id}/disconnect")
        return AdapterStatus(
            state=str(data["state"]),
            external_account_id=data.get("external_account_id"),
            detail=data.get("detail"),
        )


class WhatsAppAdapterClient(Protocol):
    def start_pairing(self, *, channel_account_id: int) -> PairingResponse:
        ...

    def status(self, *, channel_account_id: int) -> AdapterStatus:
        ...

    def disconnect(self, *, channel_account_id: int) -> AdapterStatus:
        ...

    def receive(self, *, channel_account_id: int) -> list[Mapping[str, Any]]:
        ...
