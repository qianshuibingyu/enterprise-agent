import httpx
import pytest

from app.outlook_graph import OutlookGraphClient, OutlookGraphError


def client_for(handler):
    return OutlookGraphClient(
        refresh_token="fixture-refresh-token",
        http=httpx.Client(transport=httpx.MockTransport(handler)),
    )


def test_graph_reads_inbox_and_junk_email_after_account_identity_matches(monkeypatch):
    monkeypatch.setenv("OUTLOOK_CLIENT_ID", "fixture-client")
    monkeypatch.setenv("OUTLOOK_CLIENT_SECRET", "fixture-secret")
    monkeypatch.setenv("OUTLOOK_REDIRECT_URI", "https://testserver/callback")
    calls = []
    query_params = []

    def handler(request: httpx.Request):
        calls.append(str(request.url))
        query_params.append(dict(request.url.params))
        if request.url.path.endswith("/token"):
            return httpx.Response(200, json={"access_token": "fixture-access"})
        if request.url.path.endswith("/me"):
            return httpx.Response(200, json={"id": "ms-subject-1"})
        folder = request.url.path.split("/")[-2]
        return httpx.Response(
            200,
            json={
                "value": [{
                    "id": f"graph-{folder}-message-1",
                    "receivedDateTime": "2026-11-02T10:00:00Z",
                    "bodyPreview": "fixture outlook message",
                }],
            },
        )

    messages = client_for(handler).list_emails(
        external_account_id="ms-subject-1", count=10
    )
    assert {message["id"] for message in messages} == {
        "graph-inbox-message-1",
        "graph-junkemail-message-1",
    }
    assert any("/me?" in url for url in calls)
    assert any("mailFolders/inbox/messages" in url for url in calls)
    assert any("mailFolders/junkemail/messages" in url for url in calls)
    message_query_params = [params for params in query_params if "$top" in params]
    assert all(
        params["$filter"] == "receivedDateTime ge 1970-01-01T00:00:00Z and isRead eq false"
        for params in message_query_params
    )
    assert all("isRead" in params["$select"] for params in message_query_params)


def test_graph_rejects_account_mapping_mismatch(monkeypatch):
    monkeypatch.setenv("OUTLOOK_CLIENT_ID", "fixture-client")
    monkeypatch.setenv("OUTLOOK_CLIENT_SECRET", "fixture-secret")
    monkeypatch.setenv("OUTLOOK_REDIRECT_URI", "https://testserver/callback")

    def handler(request: httpx.Request):
        if request.url.path.endswith("/token"):
            return httpx.Response(200, json={"access_token": "fixture-access"})
        return httpx.Response(200, json={"id": "other-subject"})

    with pytest.raises(OutlookGraphError):
        client_for(handler).list_emails(
            external_account_id="expected-subject", count=10
        )


def test_graph_maps_authorization_identity_from_me(monkeypatch):
    monkeypatch.setenv("OUTLOOK_CLIENT_ID", "fixture-client")
    monkeypatch.setenv("OUTLOOK_CLIENT_SECRET", "fixture-secret")
    monkeypatch.setenv("OUTLOOK_REDIRECT_URI", "https://testserver/callback")

    from app.outlook_oauth import OutlookOAuthClient

    def handler(request: httpx.Request):
        if request.url.path.endswith("/token"):
            return httpx.Response(
                200,
                json={"access_token": "fixture-access", "refresh_token": "fixture-refresh"},
            )
        return httpx.Response(
            200,
            json={"id": "ms-subject-1", "mail": "wafutechnology@outlook.com"},
        )

    authorization = OutlookOAuthClient(
        http=httpx.Client(transport=httpx.MockTransport(handler))
    ).exchange_code(code="fixture-code")
    assert authorization.external_account_id == "ms-subject-1"
    assert authorization.email == "wafutechnology@outlook.com"


def test_oauth_reports_provider_stage_and_code(monkeypatch):
    monkeypatch.setenv("OUTLOOK_CLIENT_ID", "fixture-client")
    monkeypatch.setenv("OUTLOOK_CLIENT_SECRET", "fixture-secret")
    monkeypatch.setenv("OUTLOOK_REDIRECT_URI", "https://testserver/callback")

    def handler(request: httpx.Request):
        return httpx.Response(
            400,
            json={"error": "invalid_grant", "error_description": "code expired"},
        )

    from app.outlook_oauth import OutlookOAuthClient, OutlookOAuthProviderError

    with pytest.raises(OutlookOAuthProviderError) as error:
        OutlookOAuthClient(
            http=httpx.Client(transport=httpx.MockTransport(handler))
        ).exchange_code(code="fixture-code")

    assert error.value.stage == "token_exchange"
    assert error.value.provider_code == "invalid_grant"
