from datetime import timedelta

import pytest

from app.oauth_state import OAuthStateStore
from app.provider_auth_routes import _outlook_frontend_redirect


def test_oauth_state_is_one_time_and_account_scoped():
    store = OAuthStateStore(ttl=timedelta(minutes=1))
    state = store.issue(channel_account_id=7)

    assert store.consume(state.value, channel_account_id=8) is None
    assert store.consume(state.value, channel_account_id=7) is not None
    assert store.consume(state.value, channel_account_id=7) is None


def test_outlook_callback_redirects_to_frontend(monkeypatch):
    monkeypatch.setenv("AUTH_ORIGIN", "https://qianshuibingyu.xyz")

    response = _outlook_frontend_redirect("connected")

    assert response.status_code == 303
    assert response.headers["location"] == "https://qianshuibingyu.xyz/?outlook=connected"


def test_outlook_callback_redirect_encodes_user_message(monkeypatch):
    monkeypatch.setenv("AUTH_ORIGIN", "https://qianshuibingyu.xyz")

    response = _outlook_frontend_redirect("error", "授权失败，请稍后重试。")

    assert response.status_code == 303
    assert response.headers["location"].startswith("https://qianshuibingyu.xyz/?outlook=error&message=")
