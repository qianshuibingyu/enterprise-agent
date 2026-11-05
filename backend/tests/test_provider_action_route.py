from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import hash_password
from app.database import get_db
from app.main import app
from app.models.base import Base
from app.models.business import ChannelAccount, ChannelGrant, Message
from app.models.user import User


@pytest.fixture
def personal_outlook_client():
    """Operator owning one personal Microsoft mailbox with two messages."""
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session = sessionmaker(bind=engine, expire_on_commit=False)
    Base.metadata.create_all(engine)
    with testing_session() as db:
        db.add(
            User(
                username="operator",
                password_hash=hash_password("operator1"),
                role="staff",
                is_active=True,
                must_change_password=False,
            )
        )
        db.flush()
        account = ChannelAccount(
            owner_user_id=1,
            channel_type="outlook",
            status="verified_inbound",
            # A personal Microsoft account subject, not a work/school GUID.
            external_account_id="1ee714b1593489d8",
        )
        db.add(account)
        db.flush()
        db.add_all(
            [
                ChannelGrant(
                    channel_account_id=account.id,
                    channel_type="outlook",
                    owner_user_id=1,
                ),
                Message(
                    channel_account_id=account.id,
                    provider="outlook_mcp_graph",
                    external_message_id="graph-message-with-link",
                    direction="inbound",
                    status="received",
                    handling_status="pending",
                    occurred_at=datetime(2026, 11, 4, tzinfo=timezone.utc),
                    raw_content="has link",
                    provider_web_link="https://outlook.live.com/owa/?ItemID=fixture",
                ),
                Message(
                    channel_account_id=account.id,
                    provider="outlook_mcp_graph",
                    external_message_id="graph-message-without-link",
                    direction="inbound",
                    status="received",
                    handling_status="pending",
                    occurred_at=datetime(2026, 11, 3, tzinfo=timezone.utc),
                    raw_content="no link",
                ),
            ]
        )
        db.commit()

    def override_db():
        with testing_session() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    with TestClient(app, base_url="https://testserver", raise_server_exceptions=False) as client:
        yield client
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)
    engine.dispose()


def login(client):
    csrf = client.get("/auth/csrf", headers={"Origin": "https://testserver"})
    response = client.post(
        "/auth/login",
        json={"username": "operator", "password": "operator1"},
        headers={"Origin": "https://testserver", "X-CSRF-Token": csrf.json()["csrf_token"]},
    )
    assert response.status_code == 200


def test_outlook_action_opens_the_stored_provider_message_link(personal_outlook_client):
    login(personal_outlook_client)

    response = personal_outlook_client.get("/api/messages/1/provider-action")

    assert response.status_code == 200
    body = response.json()
    assert body["supported"] is True
    assert body["action"] == "open_message"
    assert body["url"] == "https://outlook.live.com/owa/?ItemID=fixture"
    assert body["web_url"] == body["url"]


def test_outlook_action_without_a_link_never_sends_a_personal_account_to_the_work_host(
    personal_outlook_client,
):
    login(personal_outlook_client)

    response = personal_outlook_client.get("/api/messages/2/provider-action")

    assert response.status_code == 200
    body = response.json()
    # No credential is configured in this fixture, so the Graph repair cannot
    # run; the fallback must still land on the mailbox host of a personal
    # account instead of outlook.office.com (which forces a Microsoft sign-in).
    assert body["action"] == "open_inbox"
    assert body["url"] == "https://outlook.live.com/mail/0/"
    assert "office.com" not in body["url"]
