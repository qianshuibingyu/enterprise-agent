import pytest

from app.whatsapp_state import account_status_for_adapter_state


@pytest.mark.parametrize("state", ["disconnected", "reconnecting", "starting"])
def test_transient_disconnect_does_not_revoke_mapped_whatsapp_account(state):
    assert account_status_for_adapter_state("connected_pending_inbound", state, True) == "connected_pending_inbound"


def test_logged_out_revokes_whatsapp_account():
    assert account_status_for_adapter_state("connected_pending_inbound", "logged_out", True) == "revoked"


def test_revoked_state_is_not_cleared_by_transient_status():
    assert account_status_for_adapter_state("revoked", "reconnecting", True) == "revoked"


def test_connected_without_external_mapping_is_not_ready():
    assert account_status_for_adapter_state("not_ready", "connected", False) == "not_ready"
