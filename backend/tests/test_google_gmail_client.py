import httpx
import pytest

from app.google_gmail_client import (
    GmailOAuthConfigurationError,
    GmailWatchHttpClient,
    GoogleOAuthHttpClient,
)


def test_gmail_watch_client_posts_watch_request():
    seen = {}

    def handler(request: httpx.Request):
        seen["url"] = str(request.url)
        seen["json"] = request.read()
        return httpx.Response(200, json={"historyId": "123", "expiration": "456"})

    client = GmailWatchHttpClient(
        access_token="fixture-access-token",
        http=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    result = client.start_watch(topic_name="projects/test/topics/gmail")

    assert result.history_id == "123"
    assert "gmail/v1/users/me/watch" in seen["url"]


def test_google_oauth_resolves_stable_subject_and_keeps_refresh_token_server_side(monkeypatch):
    monkeypatch.setenv("GMAIL_CLIENT_ID", "fixture-client")
    monkeypatch.setenv("GMAIL_CLIENT_SECRET", "fixture-secret")
    monkeypatch.setenv("GMAIL_REDIRECT_URI", "https://testserver/callback")

    def handler(request: httpx.Request):
        if request.url.host == "oauth2.googleapis.com":
            return httpx.Response(200, json={"access_token": "fixture-access", "refresh_token": "fixture-refresh", "scope": "openid email https://www.googleapis.com/auth/gmail.readonly"})
        assert request.url.host == "openidconnect.googleapis.com"
        assert request.headers["authorization"] == "Bearer fixture-access"
        return httpx.Response(200, json={"sub": "google-subject-1", "email": "not-used@example.test"})

    client = GoogleOAuthHttpClient(http=httpx.Client(transport=httpx.MockTransport(handler)))
    authorization = client.exchange_code(code="fixture-code", state="fixture-state")

    assert authorization.external_account_id == "google-subject-1"
    assert authorization.refresh_token == "fixture-refresh"


def test_google_oauth_rejects_missing_stable_subject(monkeypatch):
    monkeypatch.setenv("GMAIL_CLIENT_ID", "fixture-client")
    monkeypatch.setenv("GMAIL_CLIENT_SECRET", "fixture-secret")
    monkeypatch.setenv("GMAIL_REDIRECT_URI", "https://testserver/callback")

    def handler(request: httpx.Request):
        if request.url.host == "oauth2.googleapis.com":
            return httpx.Response(200, json={"access_token": "fixture-access", "scope": "openid email https://www.googleapis.com/auth/gmail.readonly"})
        return httpx.Response(200, json={"email": "not-enough@example.test"})

    client = GoogleOAuthHttpClient(http=httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(GmailOAuthConfigurationError):
        client.exchange_code(code="fixture-code", state="fixture-state")


def test_google_oauth_adds_openid_to_configured_scopes(monkeypatch):
    from urllib.parse import parse_qs, urlsplit

    monkeypatch.setenv("GMAIL_CLIENT_ID", "client")
    monkeypatch.setenv("GMAIL_CLIENT_SECRET", "secret")
    monkeypatch.setenv("GMAIL_REDIRECT_URI", "https://testserver/callback")
    monkeypatch.setenv("GMAIL_SCOPES", "https://www.googleapis.com/auth/gmail.readonly")
    client = GoogleOAuthHttpClient()
    scopes = parse_qs(urlsplit(client.authorization_url(state="state")).query)["scope"][0].split()
    assert "openid" in scopes
    assert "https://www.googleapis.com/auth/gmail.readonly" in scopes


def test_google_oauth_rejects_missing_openid_before_userinfo(monkeypatch):
    monkeypatch.setenv("GMAIL_CLIENT_ID", "client")
    monkeypatch.setenv("GMAIL_CLIENT_SECRET", "secret")
    monkeypatch.setenv("GMAIL_REDIRECT_URI", "https://testserver/callback")

    def handler(request):
        assert request.url.host == "oauth2.googleapis.com"
        return httpx.Response(200, json={"access_token": "secret", "scope": "https://www.googleapis.com/auth/gmail.readonly"})

    client = GoogleOAuthHttpClient(http=httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(GmailOAuthConfigurationError, match="OpenID"):
        client.exchange_code(code="code", state="state")


def test_gmail_watch_requires_access_token(monkeypatch):
    monkeypatch.delenv("GMAIL_CLIENT_ID", raising=False)
    with pytest.raises(GmailOAuthConfigurationError):
        GmailWatchHttpClient(access_token="")
