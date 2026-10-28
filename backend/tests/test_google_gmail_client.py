import httpx
import pytest

from app.google_gmail_client import GmailOAuthConfigurationError, GmailWatchHttpClient


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


def test_gmail_watch_requires_access_token(monkeypatch):
    monkeypatch.delenv("GMAIL_CLIENT_ID", raising=False)
    with pytest.raises(GmailOAuthConfigurationError):
        GmailWatchHttpClient(access_token="")
