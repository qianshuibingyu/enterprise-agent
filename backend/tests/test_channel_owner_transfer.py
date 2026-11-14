"""Administrator can hand legacy admin-owned channel accounts to an operator.

The three channels in the original deployment were created while logged in as
``admin``. After admins were restricted to read-only inquiries, those accounts
(and every message under them) were invisible to the operating role. Ownership
is the single source of truth for message scope, so it must be transferable
without reconnecting the provider or dropping collected history.
"""

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import hash_password
from app.database import get_db
from app.main import app
from app.models.base import Base
from app.models.business import ChannelAccount, ChannelGrant, Message
from app.models.permissions import UserChannelPreauthorization
from app.models.user import User


@pytest.fixture
def owner_transfer_client():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session = sessionmaker(bind=engine, expire_on_commit=False)
    Base.metadata.create_all(engine)
    with testing_session() as db:
        admin = User(username="admin", password_hash=hash_password("adminpass1"), role="admin", department="administration", is_active=True, must_change_password=False)
        user1 = User(username="user1", password_hash=hash_password("user1pass1"), role="staff", department="inquiry", is_active=True, must_change_password=False)
        user2 = User(username="user2", password_hash=hash_password("user2pass1"), role="staff", department="inquiry", is_active=True, must_change_password=False)
        sales = User(username="sales", password_hash=hash_password("salespass1"), role="sales", department="inquiry", is_active=True, must_change_password=False)
        db.add_all([admin, user1, user2, sales])
        db.flush()
        accounts = [
            ChannelAccount(owner_user_id=admin.id, channel_type="gmail", status="verified_inbound", external_account_id="105019478337100638951"),
            ChannelAccount(owner_user_id=admin.id, channel_type="whatsapp", status="verified_inbound", external_account_id="8615914193183:19@s.whatsapp.net"),
            ChannelAccount(owner_user_id=admin.id, channel_type="outlook", status="verified_inbound", external_account_id="1ee714b1593489d8"),
        ]
        db.add_all(accounts)
        db.flush()
        db.add_all([
            ChannelGrant(channel_account_id=account.id, channel_type=account.channel_type, owner_user_id=admin.id)
            for account in accounts
        ])
        db.add(Message(
            channel_account_id=accounts[0].id,
            provider="gmail_api_pubsub",
            external_message_id="legacy-admin-gmail-1",
            direction="inbound",
            status="received",
            handling_status="pending",
            occurred_at=datetime(2026, 11, 12, tzinfo=timezone.utc),
            raw_content="Message collected while the account belonged to admin",
            customer_contact="buyer@example.com",
            normalized_customer_contact="buyer@example.com",
            contact_identity_state="certain",
            contact_identity_kind="email",
            link_state="linked",
        ))
        db.commit()

    def override_db():
        with testing_session() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    with TestClient(app, base_url="https://testserver", raise_server_exceptions=True) as client:
        client.testing_session = testing_session
        yield client
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)
    engine.dispose()


def login(client, username, password):
    csrf = client.get("/auth/csrf", headers={"Origin": "https://testserver"})
    response = client.post(
        "/auth/login",
        json={"username": username, "password": password},
        headers={"Origin": "https://testserver", "X-CSRF-Token": csrf.json()["csrf_token"]},
    )
    assert response.status_code == 200
    return client.cookies.get("ea_csrf")


def transfer(client, csrf, account_ids, **target):
    return client.post(
        "/auth/admin/channel-accounts/transfer-owner",
        json={"account_ids": account_ids, **target},
        headers={"Origin": "https://testserver", "X-CSRF-Token": csrf},
    )


def test_admin_transfers_all_three_accounts_to_user1(owner_transfer_client):
    client = owner_transfer_client
    csrf = login(client, "admin", "adminpass1")

    response = transfer(client, csrf, [1, 2, 3], owner_username="user1")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["owner_username"] == "user1"
    assert [item["id"] for item in body["transferred"]] == [1, 2, 3]
    assert body["skipped"] == []
    assert set(body["preauthorizations_granted"]) == {"gmail", "outlook", "whatsapp"}
    with client.testing_session() as db:
        accounts = db.scalars(select(ChannelAccount).order_by(ChannelAccount.id)).all()
        assert [account.owner_user_id for account in accounts] == [2, 2, 2]
        grants = db.scalars(select(ChannelGrant).order_by(ChannelGrant.channel_account_id)).all()
        assert len(grants) == 3
        assert all(grant.owner_user_id == 2 for grant in grants)
        assert all(grant.owner_user_id == account.owner_user_id for grant, account in zip(grants, accounts))
        preauth = db.scalars(select(UserChannelPreauthorization.channel_type).where(UserChannelPreauthorization.user_id == 2)).all()
        assert set(preauth) == {"gmail", "outlook", "whatsapp"}


def test_operator_sees_history_and_channels_after_transfer(owner_transfer_client):
    client = owner_transfer_client
    csrf = login(client, "admin", "adminpass1")
    assert transfer(client, csrf, [1, 2, 3], owner_user_id=2).status_code == 200

    login(client, "user1", "user1pass1")
    accounts = client.get("/api/channel-accounts")
    assert accounts.status_code == 200
    assert len(accounts.json()) == 3
    channels = client.get("/api/channels")
    assert channels.status_code == 200
    assert {item["channel_type"] for item in channels.json()} == {"gmail", "outlook", "whatsapp"}
    messages = client.get("/api/messages")
    assert messages.status_code == 200
    assert [item["external_message_id"] for item in messages.json()["items"]] == ["legacy-admin-gmail-1"]


def test_transfer_rejects_non_admin_and_non_operating_targets(owner_transfer_client):
    client = owner_transfer_client
    csrf = login(client, "user1", "user1pass1")
    assert transfer(client, csrf, [1], owner_username="user1").status_code == 403

    csrf = login(client, "admin", "adminpass1")
    assert transfer(client, csrf, [1], owner_user_id=4).status_code == 409  # sales
    assert transfer(client, csrf, [1], owner_user_id=1).status_code == 409  # admin
    assert transfer(client, csrf, [1], owner_user_id=999).status_code == 404
    assert transfer(client, csrf, [1]).status_code == 422
    assert transfer(client, csrf, [], owner_user_id=2).status_code == 422
    assert transfer(client, csrf, [999], owner_user_id=2).status_code == 404


def test_transfer_skips_conflicting_same_channel_account(owner_transfer_client):
    client = owner_transfer_client
    with client.testing_session() as db:
        existing = ChannelAccount(owner_user_id=2, channel_type="gmail", status="connected")
        db.add(existing)
        db.flush()
        db.add(ChannelGrant(channel_account_id=existing.id, channel_type="gmail", owner_user_id=2))
        db.commit()
        existing_id = existing.id
    csrf = login(client, "admin", "adminpass1")

    response = transfer(client, csrf, [1, 2, 3], owner_username="user1")

    assert response.status_code == 200
    body = response.json()
    assert [item["id"] for item in body["transferred"]] == [2, 3]
    assert len(body["skipped"]) == 1
    assert str(existing_id) in body["skipped"][0]["reason"]
    with client.testing_session() as db:
        assert db.get(ChannelAccount, 1).owner_user_id == 1


def test_admin_can_onboard_channels_without_operator_preauthorization(owner_transfer_client):
    client = owner_transfer_client
    csrf = login(client, "admin", "adminpass1")
    headers = {"Origin": "https://testserver", "X-CSRF-Token": csrf}

    channels = client.get("/api/channels")
    assert channels.status_code == 200
    assert {item["channel_type"] for item in channels.json()} == {"gmail", "outlook", "whatsapp"}
    # Admin is exempt from the operator-only preauthorization grant.
    created = client.post("/api/channels/gmail/accounts", headers=headers)
    assert created.status_code == 200
    assert created.json()["owner_user_id"] == 1
    started = client.post("/api/channels/gmail/authorize", headers=headers)
    assert started.status_code == 200
    assert started.json()["channel_type"] == "gmail"
    # Admins retain company-wide inspection access, but onboarding on their
    # personal account does not grant provider actions or account ownership.
    assert client.get("/api/messages").status_code == 200
    # Admins get safe company-wide list summaries, not message detail/content.
    assert client.get("/api/messages/1").status_code == 403
    assert client.get("/api/integrations/outlook/accounts/3/messages").status_code == 403


def test_transfer_deletes_target_stale_shells_instead_of_skipping(owner_transfer_client):
    """The reported bug: two revoked shells blocked all three transfers."""
    client = owner_transfer_client
    with client.testing_session() as db:
        stale_gmail = ChannelAccount(owner_user_id=2, channel_type="gmail", status="revoked", external_account_id="105019478337100638951")
        stale_outlook = ChannelAccount(owner_user_id=2, channel_type="outlook", status="revoked")
        db.add_all([stale_gmail, stale_outlook])
        db.flush()
        db.add_all([
            ChannelGrant(channel_account_id=stale_gmail.id, channel_type="gmail", owner_user_id=2),
            ChannelGrant(channel_account_id=stale_outlook.id, channel_type="outlook", owner_user_id=2),
        ])
        db.commit()
        stale_ids = [stale_gmail.id, stale_outlook.id]
    csrf = login(client, "admin", "adminpass1")

    # "全选" in the admin table also selects the stale shells themselves. The
    # batch must still succeed and skip those rows once they are cleaned up.
    response = transfer(client, csrf, [1, 2, 3, *stale_ids], owner_username="user1")

    assert response.status_code == 200, response.text
    body = response.json()
    assert [item["id"] for item in body["transferred"]] == [1, 2, 3]
    assert sorted(item["id"] for item in body["skipped"]) == stale_ids
    assert all("已在本次转移中清理" in item["reason"] for item in body["skipped"])
    assert sorted(item["id"] for item in body["retired_shells"]) == stale_ids
    assert all(item["deleted"] for item in body["retired_shells"])
    with client.testing_session() as db:
        assert all(db.get(ChannelAccount, shell_id) is None for shell_id in stale_ids)
        assert all(db.get(ChannelAccount, account_id).owner_user_id == 2 for account_id in (1, 2, 3))

    login(client, "user1", "user1pass1")
    assert {item["channel_type"] for item in client.get("/api/channels").json()} == {"gmail", "outlook", "whatsapp"}
    assert [item["external_message_id"] for item in client.get("/api/messages").json()["items"]] == ["legacy-admin-gmail-1"]


def test_transfer_moves_stale_shell_history_and_archives_duplicates(owner_transfer_client):
    client = owner_transfer_client
    with client.testing_session() as db:
        shell = ChannelAccount(owner_user_id=2, channel_type="gmail", status="revoked")
        db.add(shell)
        db.flush()
        db.add(ChannelGrant(channel_account_id=shell.id, channel_type="gmail", owner_user_id=2))
        db.add_all([
            Message(
                channel_account_id=shell.id, provider="gmail_api_pubsub",
                external_message_id="shell-only-1", direction="inbound", status="received",
                handling_status="pending", occurred_at=datetime(2026, 11, 5, tzinfo=timezone.utc),
                raw_content="moved history", link_state="linked",
            ),
            Message(
                channel_account_id=shell.id, provider="gmail_api_pubsub",
                external_message_id="legacy-admin-gmail-1", direction="inbound", status="received",
                handling_status="pending", occurred_at=datetime(2026, 11, 5, 1, tzinfo=timezone.utc),
                raw_content="duplicate stays archived", link_state="linked",
            ),
        ])
        db.commit()
        shell_id = shell.id
    csrf = login(client, "admin", "adminpass1")

    response = transfer(client, csrf, [1], owner_user_id=2)

    assert response.status_code == 200
    assert len(response.json()["transferred"]) == 1
    retired = response.json()["retired_shells"][0]
    assert retired["id"] == shell_id and retired["deleted"] is False
    assert retired["history_messages_moved"] == 1
    with client.testing_session() as db:
        archived = db.get(ChannelAccount, shell_id)
        assert archived is not None and archived.status == "revoked"
        moved = db.scalar(select(Message).where(Message.channel_account_id == 1, Message.external_message_id == "shell-only-1"))
        assert moved is not None
        assert db.scalar(select(Message).where(Message.channel_account_id == shell_id, Message.external_message_id == "legacy-admin-gmail-1")) is not None


def test_transfer_is_idempotent(owner_transfer_client):
    client = owner_transfer_client
    csrf = login(client, "admin", "adminpass1")
    assert len(transfer(client, csrf, [1], owner_user_id=2).json()["transferred"]) == 1

    second = transfer(client, csrf, [1], owner_user_id=2)

    assert second.status_code == 200
    assert second.json()["transferred"] == []
    assert "已归属" in second.json()["skipped"][0]["reason"]
    with client.testing_session() as db:
        grants = db.scalars(select(ChannelGrant).where(ChannelGrant.channel_account_id == 1)).all()
        assert len(grants) == 1 and grants[0].owner_user_id == 2
