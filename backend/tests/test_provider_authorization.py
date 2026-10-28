from datetime import timedelta

import pytest

from app.oauth_state import OAuthStateStore


def test_oauth_state_is_one_time_and_account_scoped():
    store = OAuthStateStore(ttl=timedelta(minutes=1))
    state = store.issue(channel_account_id=7)

    assert store.consume(state.value, channel_account_id=8) is None
    assert store.consume(state.value, channel_account_id=7) is not None
    assert store.consume(state.value, channel_account_id=7) is None
