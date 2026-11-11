import base64

import httpx
import pytest

from app.channels.inbound import (
    ProviderAuthorizationFailure,
    ProviderPermanentFailure,
    ProviderRateLimited,
    ProviderTemporaryFailure,
)
from app.gmail_client import GmailApiClient, GmailConfigurationError


def test_gmail_client_refreshes_token_and_fetches_history_and_message(monkeypatch):
    monkeypatch.setenv("GMAIL_CLIENT_ID", "client-id")
    monkeypatch.setenv("GMAIL_CLIENT_SECRET", "client-secret")
    monkeypatch.setenv("GMAIL_REFRESH_TOKEN", "refresh-token")

    requests = []

    def handler(request: httpx.Request):
        requests.append(request)
        if request.url.host == "oauth2.googleapis.com":
            return httpx.Response(200, json={"access_token": "short-lived"})
        if request.url.path.endswith("/history"):
            return httpx.Response(200, json={
                "history": [{
                    "id": "history-2",
                    "messagesAdded": [{"message": {"id": "gmail-1"}}],
                }]
            })
        return httpx.Response(200, json={
            "id": "gmail-1",
            "payload": {
                "headers": [{"name": "Date", "value": "Thu, 22 Oct 2026 08:00:00 +0000"}],
                "body": {"data": base64.urlsafe_b64encode("message body".encode()).decode().rstrip("=")},
            },
        })

    client = GmailApiClient(refresh_token="refresh-token", http=httpx.Client(transport=httpx.MockTransport(handler)))
    history = client.list_history(account_id=1, history_id="history-1")
    message = client.fetch_message(account_id=1, message_id="gmail-1")

    assert history == [{"history_id": "history-2", "message_id": "gmail-1"}]
    assert message["external_message_id"] == "gmail-1"
    assert message["raw_content"] == "message body"
    assert message["direction"] == "inbound"
    assert len(requests) == 3
    assert requests[1].headers["authorization"] == "Bearer short-lived"
    assert "client-secret" not in str(requests)
    assert "refresh-token" not in str(requests)


def test_gmail_client_extracts_nested_multipart_plain_text_before_html(monkeypatch):
    monkeypatch.setenv("GMAIL_CLIENT_ID", "client-id")
    monkeypatch.setenv("GMAIL_CLIENT_SECRET", "client-secret")
    monkeypatch.setenv("GMAIL_REFRESH_TOKEN", "refresh-token")
    plain = base64.urlsafe_b64encode(b"nested plain body").decode().rstrip("=")
    html = base64.urlsafe_b64encode(b"<p>html body</p>").decode().rstrip("=")

    def handler(request: httpx.Request):
        if request.url.host == "oauth2.googleapis.com":
            return httpx.Response(200, json={"access_token": "short-lived"})
        return httpx.Response(200, json={
            "id": "gmail-nested",
            "payload": {
                "mimeType": "multipart/mixed",
                "parts": [{
                    "mimeType": "multipart/alternative",
                    "parts": [
                        {"mimeType": "text/html", "body": {"data": html}},
                        {"mimeType": "multipart/related", "parts": [
                            {"mimeType": "text/plain", "body": {"data": plain}},
                            {"mimeType": "image/png", "filename": "inline.png", "body": {"attachmentId": "att-1"}},
                        ]},
                    ],
                }],
            },
        })

    client = GmailApiClient(refresh_token="refresh-token", http=httpx.Client(transport=httpx.MockTransport(handler)))
    result = client.fetch_message(account_id=1, message_id="gmail-nested")
    assert result["raw_content"] == "nested plain body"


def test_gmail_client_accepts_leaf_body_without_mime_type(monkeypatch):
    monkeypatch.setenv("GMAIL_CLIENT_ID", "client-id")
    monkeypatch.setenv("GMAIL_CLIENT_SECRET", "client-secret")
    monkeypatch.setenv("GMAIL_REFRESH_TOKEN", "refresh-token")

    def handler(request: httpx.Request):
        if request.url.host == "oauth2.googleapis.com":
            return httpx.Response(200, json={"access_token": "short-lived"})
        return httpx.Response(200, json={
            "id": "gmail-leaf",
            "payload": {"body": {"data": base64.urlsafe_b64encode(b"leaf text").decode().rstrip("=")}},
        })

    client = GmailApiClient(refresh_token="refresh-token", http=httpx.Client(transport=httpx.MockTransport(handler)))
    assert client.fetch_message(account_id=1, message_id="gmail-leaf")["raw_content"] == "leaf text"


def test_gmail_client_requires_server_credentials(monkeypatch):
    for name in ("GMAIL_CLIENT_ID", "GMAIL_CLIENT_SECRET", "GMAIL_REFRESH_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(GmailConfigurationError):
        GmailApiClient(refresh_token="")


def test_gmail_client_propagates_rate_limit(monkeypatch):
    monkeypatch.setenv("GMAIL_CLIENT_ID", "client-id")
    monkeypatch.setenv("GMAIL_CLIENT_SECRET", "client-secret")
    monkeypatch.setenv("GMAIL_REFRESH_TOKEN", "refresh-token")

    def handler(request: httpx.Request):
        if request.url.host == "oauth2.googleapis.com":
            return httpx.Response(200, json={"access_token": "short-lived"})
        return httpx.Response(429)

    client = GmailApiClient(refresh_token="refresh-token", http=httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(ProviderRateLimited):
        client.list_history(account_id=1, history_id="history-1")


@pytest.mark.parametrize("status_code", [401, 403])
def test_gmail_client_treats_authorization_failure_as_non_retryable(monkeypatch, status_code):
    monkeypatch.setenv("GMAIL_CLIENT_ID", "client-id")
    monkeypatch.setenv("GMAIL_CLIENT_SECRET", "client-secret")
    monkeypatch.setenv("GMAIL_REFRESH_TOKEN", "refresh-token")

    def handler(request: httpx.Request):
        if request.url.host == "oauth2.googleapis.com":
            return httpx.Response(200, json={"access_token": "short-lived"})
        return httpx.Response(status_code, text="sensitive provider details")

    client = GmailApiClient(refresh_token="refresh-token", http=httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(ProviderAuthorizationFailure) as raised:
        client.list_history(account_id=1, history_id="history-1")

    assert raised.value.retryable is False
    assert "sensitive provider details" not in str(raised.value)


def test_gmail_oauth_invalid_grant_is_authorization_failure(monkeypatch):
    monkeypatch.setenv("GMAIL_CLIENT_ID", "client-id")
    monkeypatch.setenv("GMAIL_CLIENT_SECRET", "client-secret")
    monkeypatch.setenv("GMAIL_REFRESH_TOKEN", "refresh-token")

    def handler(request: httpx.Request):
        assert request.url.host == "oauth2.googleapis.com"
        return httpx.Response(400, json={"error": "invalid_grant", "error_description": "private details"})

    client = GmailApiClient(refresh_token="refresh-token", http=httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(ProviderAuthorizationFailure) as raised:
        client.list_history(account_id=1, history_id="history-1")

    assert raised.value.retryable is False
    assert "private details" not in str(raised.value)


def test_gmail_client_treats_other_client_error_as_permanent(monkeypatch):
    monkeypatch.setenv("GMAIL_CLIENT_ID", "client-id")
    monkeypatch.setenv("GMAIL_CLIENT_SECRET", "client-secret")
    monkeypatch.setenv("GMAIL_REFRESH_TOKEN", "refresh-token")

    def handler(request: httpx.Request):
        if request.url.host == "oauth2.googleapis.com":
            return httpx.Response(200, json={"access_token": "short-lived"})
        return httpx.Response(400, text="sensitive provider details")

    client = GmailApiClient(refresh_token="refresh-token", http=httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(ProviderPermanentFailure) as raised:
        client.list_history(account_id=1, history_id="history-1")

    assert raised.value.retryable is False
    assert "sensitive provider details" not in str(raised.value)


def test_gmail_client_propagates_temporary_failure(monkeypatch):
    monkeypatch.setenv("GMAIL_CLIENT_ID", "client-id")
    monkeypatch.setenv("GMAIL_CLIENT_SECRET", "client-secret")
    monkeypatch.setenv("GMAIL_REFRESH_TOKEN", "refresh-token")

    def handler(request: httpx.Request):
        if request.url.host == "oauth2.googleapis.com":
            return httpx.Response(200, json={"access_token": "short-lived"})
        return httpx.Response(503)

    client = GmailApiClient(refresh_token="refresh-token", http=httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(ProviderTemporaryFailure):
        client.list_history(account_id=1, history_id="history-1")
