import pytest

from app.whatsapp_state import account_status_for_adapter_state


@pytest.mark.parametrize("state", ["disconnected", "reconnecting", "starting"])
def test_transient_disconnect_does_not_revoke_mapped_whatsapp_account(state):
    assert account_status_for_adapter_state("connected_pending_inbound", state, True) == "connected_pending_inbound"


def test_logged_out_device_is_recoverable_not_terminal():
    # WhatsApp unlinking the device must leave the account re-pairable: the
    # bridge clears the dead credentials, so status must go back to not_ready
    # instead of the terminal "revoked" that only an admin action produces.
    assert account_status_for_adapter_state("connected_pending_inbound", "logged_out", True) == "not_ready"
    assert account_status_for_adapter_state("verified_inbound", "revoked", True) == "not_ready"


def test_admin_history_revocation_stays_terminal():
    assert account_status_for_adapter_state("revoked", "logged_out", True) == "revoked"


def test_revoked_state_is_not_cleared_by_transient_status():
    assert account_status_for_adapter_state("revoked", "reconnecting", True) == "revoked"


def test_connected_without_external_mapping_is_not_ready():
    assert account_status_for_adapter_state("not_ready", "connected", False) == "not_ready"
