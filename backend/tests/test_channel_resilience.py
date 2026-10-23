from datetime import datetime, timezone
from unittest.mock import Mock

import pytest

from app.channels.inbound import _commit_or_rollback
from app.channels.providers import FakeTestProvider
from app.channels.registry import provider_descriptor


def test_inbound_commit_failure_rolls_back_and_propagates():
    db = Mock()
    db.commit.side_effect = RuntimeError("commit failed")

    with pytest.raises(RuntimeError, match="commit failed"):
        _commit_or_rollback(db)

    db.rollback.assert_called_once_with()


def test_fake_provider_expired_credential_reports_revoked_without_receive():
    provider = FakeTestProvider(
        "gmail",
        provider_descriptor("gmail").capabilities,
        messages=[
            {
                "external_message_id": "expired-1",
                "direction": "inbound",
                "status": "received",
                "occurred_at": datetime(2026, 10, 22, tzinfo=timezone.utc),
                "raw_content": "must not be received",
            }
        ],
        failure="expired",
    )

    state = provider.check_connection(external_account_id="account-1")
    assert state.status == "revoked"
    assert state.error_code == "credential_expired"
    with pytest.raises(RuntimeError, match="authorization revoked"):
        provider.receive(external_account_id="account-1")
    assert provider.receive_calls == 1


def test_fake_provider_revoke_updates_state_and_counts_call():
    provider = FakeTestProvider("gmail", provider_descriptor("gmail").capabilities)

    result = provider.revoke(external_account_id="account-1")

    assert result.status == "revoked"
    assert provider.revoke_calls == 1
    assert provider.check_connection(external_account_id="account-1").status == "not_connected"


def test_fake_provider_rate_limit_and_temporary_failure_are_visible():
    for failure, message in (
        ("rate_limited", "rate limited"),
        ("temporary", "temporary failure"),
    ):
        provider = FakeTestProvider(
            "gmail",
            provider_descriptor("gmail").capabilities,
            failure=failure,
        )
        with pytest.raises(RuntimeError, match=message):
            provider.receive(external_account_id="account-1")
        assert provider.receive_calls == 1
