# WhatsApp Baileys bridge

This service adapts the Chat SDK community Baileys adapter to the existing backend contract.

The upstream adapter is self-hosted and WebSocket-based: `connect()` receives messages and
`handleWebhook()` is not a usable inbound transport. The bridge therefore owns the Baileys
socket and forwards normalized inbound events to the backend callback. Both Baileys `notify`
events and provider-delivered `append` history events use the same encrypted durable inbox and
idempotent backend contract.

## Security boundary

- The service is reachable only on the Compose network; it has no published host port.
- `WHATSAPP_ADAPTER_TOKEN` is required and is used for bridge control and backend ingress.
- Baileys auth state is stored only in the `whatsapp_auth` volume.
- Do not put QR strings, auth state, session files, phone numbers, or tokens in Git, logs,
  browser storage, or API responses other than the short-lived pairing response.
- The inbox periodically compacts atomically and keeps a bounded delivered-ID tombstone set,
  so replayed history does not immediately requeue after compaction.
- `history_sync_complete` is intentionally always false: the bridge can only process history
  events that WhatsApp/Baileys actually delivers.
- This uses an unofficial WhatsApp Web API. WhatsApp may change protocols or suspend accounts.

## Build and deploy (operator action)

From the repository root, after reviewing `package.json` lock policy and the upstream package
versions:

```text
docker compose build whatsapp-bridge backend frontend
docker compose up -d db whatsapp-bridge backend frontend
```

Do not run this until the operator has supplied `WHATSAPP_ADAPTER_TOKEN` through the server's
secret manager/environment and reviewed the auth volume and backup policy. Do not run migrations
implicitly during container startup.

The first pairing is performed from the application UI. The bridge's `onQR` callback keeps the
current QR only in bridge memory until it expires; the auth state is persisted in the named
volume so a restart does not require a new pairing.

## Required verification

1. Check bridge health internally (`/healthz`) without exposing it publicly.
2. Start pairing from the application's personal/channel page.
3. The account owner scans the short-lived QR from WhatsApp Linked Devices.
4. Confirm status is `connected_pending_inbound`, not `verified_inbound`.
5. Send one dedicated test message from a test contact.
6. Confirm the bridge forwards one normalized event and the backend stores one Message.
7. Replay the same event ID and confirm no second Message is created.
8. Disconnect and confirm subsequent events are rejected while historical messages remain.

The backend does not infer or invent the external WhatsApp account ID. If the Chat SDK/Baileys
runtime cannot expose a stable account identity, mapping remains not-ready and must be completed
before real acceptance.
