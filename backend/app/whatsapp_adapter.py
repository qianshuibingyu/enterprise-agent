"""Client contract for the project-owned WhatsApp/Baileys adapter."""

from dataclasses import dataclass
import os
from typing import Any, Mapping, Protocol

import httpx


class WhatsAppAdapterConfigurationError(RuntimeError):
    pass


class WhatsAppAdapterUnavailableError(RuntimeError):
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
    qr: str = ""
    expires_at: str = ""


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
        try:
            response = self.http.request(
                method,
                f"{self.base_url}{path}",
                headers={"Authorization": f"Bearer {self.token}"},
                **kwargs,
            )
        except httpx.RequestError as exc:
            raise WhatsAppAdapterUnavailableError("WhatsApp bridge is unreachable") from exc
        if response.status_code in {401, 403}:
            raise WhatsAppAdapterConfigurationError("WhatsApp adapter authorization failed")
        if response.status_code >= 400:
            raise WhatsAppAdapterUnavailableError(f"WhatsApp bridge returned HTTP {response.status_code}")
        return response.json()

    def start_pairing(self, *, channel_account_id: int) -> PairingResponse:
        # The bridge waits up to ~15s for WhatsApp to emit a QR (longer on a
        # cold start with full-history sync), so pairing needs a dedicated
        # timeout that is strictly larger than the bridge deadline.
        pair_timeout = float(os.environ.get("WHATSAPP_PAIR_TIMEOUT_SECONDS", "30"))
        data = self._request(
            "POST",
            f"/internal/whatsapp/accounts/{channel_account_id}/pair",
            timeout=pair_timeout,
        )
        return PairingResponse(qr=str(data["qr"]), expires_at=str(data["expires_at"]))

    def status(self, *, channel_account_id: int) -> AdapterStatus:
        data = self._request("GET", f"/internal/whatsapp/accounts/{channel_account_id}/status")
        return AdapterStatus(
            state=str(data["state"]),
            external_account_id=data.get("external_account_id"),
            detail=data.get("detail"),
            qr=str(data.get("qr") or ""),
            expires_at=str(data.get("expires_at") or ""),
        )

    def disconnect(self, *, channel_account_id: int) -> AdapterStatus:
        data = self._request("POST", f"/internal/whatsapp/accounts/{channel_account_id}/disconnect")
        return AdapterStatus(
            state=str(data["state"]),
            external_account_id=data.get("external_account_id"),
            detail=data.get("detail"),
        )

    def resolve_lid_phone(self, *, channel_account_id: int, lid: str) -> str | None:
        """Ask the adapter which phone number a LID chat belongs to.

        WhatsApp delivers direct chats under a privacy ``<id>@lid`` JID. Only the
        linked device can map that id back to a phone number, and only a phone
        number can open a chat, so historical rows are repaired through here.
        """
        data = self._request(
            "POST",
            f"/internal/whatsapp/accounts/{channel_account_id}/lid-phone",
            json={"lid": lid},
        )
        phone = data.get("phone")
        return phone if isinstance(phone, str) and phone.isdigit() else None

    def fetch_message(self, *, channel_account_id: int, message_id: str) -> dict[str, Any]:
        """Fetch one message from the paired WhatsApp session by opaque ID."""
        return self._request(
            "GET",
            f"/internal/whatsapp/accounts/{channel_account_id}/messages/{message_id}",
        )


class WhatsAppAdapterClient(Protocol):
    def start_pairing(self, *, channel_account_id: int) -> PairingResponse:
        ...

    def status(self, *, channel_account_id: int) -> AdapterStatus:
        ...

    def disconnect(self, *, channel_account_id: int) -> AdapterStatus:
        ...

    def resolve_lid_phone(self, *, channel_account_id: int, lid: str) -> str | None:
        ...

    def fetch_message(self, *, channel_account_id: int, message_id: str) -> Mapping[str, Any]:
        ...

    def receive(self, *, channel_account_id: int) -> list[Mapping[str, Any]]:
        ...
