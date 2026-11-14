"""Map Baileys transport states without confusing disconnects with revocation."""


def account_status_for_adapter_state(current_status: str, state: str, has_external_id: bool) -> str:
    if state in {"revoked", "logged_out"}:
        # A device-level logout (WhatsApp unlinked the phone) is recoverable:
        # the bridge drops the dead credentials and the owner scans a fresh QR.
        # Only an administrator history revocation is terminal, and that is
        # tracked separately by ``ChannelAccount.history_access_revoked_at``.
        if current_status == "revoked":
            return "revoked"
        return "not_ready"
    if state in {"connected", "ready", "authenticated"}:
        return "connected_pending_inbound" if has_external_id else "not_ready"
    if state in {"disconnected", "reconnecting", "starting"}:
        if current_status == "revoked":
            return "revoked"
        return "connected_pending_inbound" if has_external_id else "not_ready"
    if state == "blocked":
        return "blocked"
    if state in {"error", "system_error"}:
        return "system_error"
    return current_status
