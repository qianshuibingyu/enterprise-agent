from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import hash_password
from app.database import get_db
from app.main import app
from app.models.base import Base
from app.models.business import (
    ChannelAccount,
    ChannelGrant,
    Inquiry,
    InquiryAttachment,
    InquiryEvent,
    InternalNotification,
    InquiryMessage,
    Message,
    MessageAttachment,
)
from app.models.overview import MessageOverview
from app.models.user import User
from app.models.permissions import UserChannelPreauthorization, UserDepartmentGrant
from app.authorization import department_read_scope, has_department_identity, scoped_inquiries, scoped_messages


@pytest.fixture
def business_client():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session = sessionmaker(bind=engine, expire_on_commit=False)
    Base.metadata.create_all(engine)
    with testing_session() as db:
        db.add_all(
            [
                User(username="operator", password_hash=hash_password("operator1"), role="staff", department="inquiry", is_active=True, must_change_password=False),
                User(username="other-operator", password_hash=hash_password("otherop1"), role="staff", department="inquiry", is_active=True, must_change_password=False),
                User(username="sales", password_hash=hash_password("salespass1"), role="sales", department="inquiry", is_active=True, must_change_password=False),
                User(username="other-sales", password_hash=hash_password("othersale1"), role="sales", department="inquiry", is_active=True, must_change_password=False),
                User(username="empty-operator", password_hash=hash_password("emptyop1"), role="staff", department="inquiry", is_active=True, must_change_password=False),
                User(username="admin", password_hash=hash_password("adminpass1"), role="admin", department="administration", is_active=True, must_change_password=False),
            ]
        )
        db.flush()
        db.add_all([
            UserChannelPreauthorization(user_id=1, channel_type="gmail", granted_by_user_id=6),
            UserChannelPreauthorization(user_id=1, channel_type="outlook", granted_by_user_id=6),
            UserChannelPreauthorization(user_id=2, channel_type="outlook", granted_by_user_id=6),
            UserChannelPreauthorization(user_id=5, channel_type="gmail", granted_by_user_id=6),
            UserChannelPreauthorization(user_id=5, channel_type="whatsapp", granted_by_user_id=6),
        ])
        first_account = ChannelAccount(owner_user_id=1, channel_type="gmail", status="connected")
        blocked_account = ChannelAccount(owner_user_id=1, channel_type="outlook", status="blocked")
        other_account = ChannelAccount(owner_user_id=2, channel_type="outlook", status="connected")
        revoked_account = ChannelAccount(owner_user_id=1, channel_type="gmail", status="revoked")
        admin_account = ChannelAccount(owner_user_id=6, channel_type="gmail", status="connected")
        db.add_all([first_account, blocked_account, other_account, revoked_account, admin_account])
        db.flush()
        db.add_all(
            [
                ChannelGrant(channel_account_id=first_account.id, channel_type="gmail", owner_user_id=1),
                ChannelGrant(channel_account_id=blocked_account.id, channel_type="outlook", owner_user_id=1),
                ChannelGrant(channel_account_id=other_account.id, channel_type="outlook", owner_user_id=2),
                ChannelGrant(channel_account_id=revoked_account.id, channel_type="gmail", owner_user_id=1),
                ChannelGrant(channel_account_id=admin_account.id, channel_type="gmail", owner_user_id=6),
                Message(
                    channel_account_id=first_account.id,
                    provider="gmail_api_pubsub",
                    external_message_id="fixture-gmail-1",
                    direction="inbound",
                    status="received",
                    handling_status="pending",
                    occurred_at=datetime(2026, 10, 23, tzinfo=timezone.utc),
                    raw_content="Fake fixture message",
                    customer_contact="Customer <customer@example.com>",
                    normalized_customer_contact="customer@example.com",
                    contact_identity_state="certain",
                    contact_identity_kind="email",
                    link_state="linked",
                    attachments=[
                        MessageAttachment(
                            original_filename="fixture.pdf",
                            media_type="application/pdf",
                            size_bytes=42,
                            storage_reference="vault://fixture/secret-reference",
                        )
                    ],
                ),
                Message(
                    channel_account_id=revoked_account.id,
                    provider="gmail_api_pubsub",
                    external_message_id="revoked-gmail-1",
                    direction="inbound",
                    status="received",
                    handling_status="pending",
                    occurred_at=datetime(2026, 10, 23, tzinfo=timezone.utc),
                    raw_content="Revoked account historical message",
                    customer_contact="Secret <secret-revoked@example.com>",
                    customer_nickname="Secret",
                    normalized_customer_contact="secret-revoked@example.com",
                    contact_identity_state="certain",
                    contact_identity_kind="email",
                    link_state="linked",
                ),
                Message(
                    channel_account_id=first_account.id,
                    provider="gmail_api_pubsub",
                    external_message_id="fixture-unmatched-review",
                    direction="inbound",
                    status="received",
                    handling_status="pending",
                    occurred_at=datetime(2026, 10, 23, tzinfo=timezone.utc),
                    raw_content="manual review fixture",
                    customer_contact="private-review@example.com",
                    normalized_customer_contact="private-review@example.com",
                    contact_identity_state="identity_uncertain",
                    contact_identity_kind="email",
                    link_state="manual_review",
                ),
                Message(
                    channel_account_id=first_account.id,
                    provider="gmail_api_pubsub",
                    external_message_id="fixture-unmatched",
                    direction="inbound",
                    status="received",
                    handling_status="pending",
                    occurred_at=datetime(2026, 10, 23, tzinfo=timezone.utc),
                    raw_content="unmatched fixture",
                    customer_contact="private-unmatched@example.com",
                    normalized_customer_contact="private-unmatched@example.com",
                    contact_identity_state="certain",
                    contact_identity_kind="email",
                    link_state="unmatched",
                ),
                Message(
                    channel_account_id=other_account.id,
                    provider="outlook_imap",
                    external_message_id="fixture-outlook-1",
                    direction="inbound",
                    status="received",
                    handling_status="pending",
                    occurred_at=datetime(2026, 10, 23, 1, tzinfo=timezone.utc),
                    raw_content="Other fixture message",
                    customer_contact="other@example.com",
                    normalized_customer_contact="other@example.com",
                    contact_identity_state="certain",
                    contact_identity_kind="email",
                    link_state="linked",
                ),
                Message(
                    channel_account_id=other_account.id,
                    provider="outlook_imap",
                    external_message_id="fixture-outlook-2",
                    direction="inbound",
                    status="processed",
                    handling_status="pending",
                    occurred_at=datetime(2026, 10, 23, 2, tzinfo=timezone.utc),
                    raw_content="Assigned sales fixture message",
                    customer_contact="mine@example.com",
                    normalized_customer_contact="mine@example.com",
                    contact_identity_state="certain",
                    contact_identity_kind="email",
                    link_state="linked",
                ),
                Inquiry(
                    customer_contact="customer@example.com",
                    department="inquiry",
                    normalized_customer_contact="customer@example.com",
                    contact_identity_state="certain",
                    contact_identity_kind="email",
                    customer_nickname="Customer",
                    raw_message="Need a quote",
                    source_channel_account_id=first_account.id,
                    status="new",
                    handling_status="pending",
                    events=[
                        InquiryEvent(
                            event_type="inquiry_created",
                            from_status=None,
                            to_status="new",
                            occurred_at=datetime(2026, 10, 23, 3, tzinfo=timezone.utc),
                        )
                    ],
                    message_links=[
                        InquiryMessage(inquiry_id=1, message_id=1, position=1, link_source="fixture"),
                    ],
                ),
                Inquiry(
                    customer_contact="other@example.com",
                    department="inquiry",
                    normalized_customer_contact="other@example.com",
                    contact_identity_state="certain",
                    contact_identity_kind="email",
                    customer_nickname="Other Customer",
                    raw_message="Other inquiry",
                    source_channel_account_id=other_account.id,
                    status="new",
                    assigned_sales_user_id=4,
                ),
                Inquiry(
                    customer_contact="mine@example.com",
                    department="inquiry",
                    normalized_customer_contact="mine@example.com",
                    contact_identity_state="certain",
                    contact_identity_kind="email",
                    customer_nickname="Assigned Customer",
                    raw_message="Assigned inquiry",
                    source_channel_account_id=other_account.id,
                    status="assigned",
                    handling_status="pending",
                    assigned_sales_user_id=3,
                    last_activity_at=datetime(2026, 10, 23, 4, tzinfo=timezone.utc),
                    events=[
                        InquiryEvent(
                            event_type="inquiry_created",
                            from_status=None,
                            to_status="new",
                            occurred_at=datetime(2026, 10, 23, 4, tzinfo=timezone.utc),
                        ),
                        InquiryEvent(
                            event_type="inquiry_transferred",
                            actor_user_id=1,
                            from_status="new",
                            to_status="assigned",
                            target_user_id=3,
                            occurred_at=datetime(2026, 10, 23, 5, tzinfo=timezone.utc),
                        ),
                    ],
                    message_links=[InquiryMessage(inquiry_id=3, message_id=6, position=1, link_source="fixture")],
                    attachments=[
                        InquiryAttachment(
                            original_filename="photo.png",
                            media_type="image/png",
                            size_bytes=12,
                            storage_reference="inquiry/3/photo.png",
                        )
                    ],
                ),
                Inquiry(
                    customer_contact="revoked@example.com",
                    department="inquiry",
                    normalized_customer_contact="revoked@example.com",
                    contact_identity_state="certain",
                    contact_identity_kind="email",
                    customer_nickname="Revoked Customer",
                    raw_message="Revoked source inquiry",
                    source_channel_account_id=revoked_account.id,
                    status="assigned",
                    handling_status="pending",
                    assigned_sales_user_id=3,
                ),
            ]
        )
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
    return response


def test_department_reader_identity_and_scope_contract(business_client):
    with business_client.testing_session() as db:
        readers = {
            role: User(username=f"{role}-reader", password_hash=hash_password("readerpass1"),
                       role=role, department=role.title(), is_active=True, must_change_password=False)
            for role in ("engineering", "production", "procurement")
        }
        db.add_all(readers.values())
        db.flush()
        db.add(UserDepartmentGrant(user_id=readers["engineering"].id, department="Production", granted_by_user_id=6))
        db.commit()
        assert all(has_department_identity(user) for user in readers.values())
        assert not has_department_identity(User(role="engineering", department="  "))
        assert not has_department_identity(User(role="procurement", department="  "))
        assert not has_department_identity(User(role="engineering", department="unassigned"))
        assert set(db.scalars(department_read_scope(readers["engineering"])).all()) == {"Production", "Engineering"}


def test_department_readers_are_denied_customer_message_scopes(business_client):
    with business_client.testing_session() as db:
        user = User(username="engineering-reader", password_hash=hash_password("readerpass1"), role="engineering", department="Engineering", is_active=True, must_change_password=False)
        db.add(user)
        db.commit()
        assert db.scalars(scoped_inquiries(user)).all() == []
        assert db.scalars(scoped_messages(user)).all() == []


def test_business_resources_require_authentication(business_client):
    assert business_client.get("/api/inquiry-transfer-targets").status_code == 401
    assert business_client.get("/api/channel-accounts").status_code == 401
    assert business_client.get("/api/messages").status_code == 401
    assert business_client.get("/api/inquiries").status_code == 401
    assert business_client.post("/api/internal-ai/query", json={"query": "inquiries"}).status_code == 401


def test_channel_account_list_allows_null_external_account_id(business_client):
    login(business_client, "operator", "operator1")

    response = business_client.get("/api/channels/accounts")

    assert response.status_code == 200
    accounts = response.json()
    assert accounts
    assert any(account["external_account_id"] is None for account in accounts)


def test_gmail_account_initialization_is_idempotent_and_not_provider_connected(business_client):
    login(business_client, "empty-operator", "emptyop1")
    csrf = business_client.cookies.get("ea_csrf")
    headers = {"Origin": "https://testserver", "X-CSRF-Token": csrf}

    first = business_client.post("/api/channels/gmail/accounts", headers=headers)
    second = business_client.post("/api/channels/gmail/accounts", headers=headers)

    assert first.status_code == 200
    assert first.json()["channel_type"] == "gmail"
    assert first.json()["status"] == "not_ready"
    assert first.json()["external_account_id"] is None
    assert second.status_code == 200
    assert second.json()["id"] == first.json()["id"]
    assert second.json()["status"] == "not_ready"


def test_legacy_owned_account_stays_readable_without_channel_preauthorization(business_client):
    """Accounts created before the 0019 grant table must not be locked out.

    Preauthorization gates onboarding a *new* channel, not reading history that
    was already collected under an account the operator owns (ChannelGrant).
    """
    with business_client.testing_session() as db:
        legacy = User(
            username="legacy-operator",
            password_hash=hash_password("legacyop1"),
            role="staff",
            department="inquiry",
            is_active=True,
            must_change_password=False,
        )
        db.add(legacy)
        db.flush()
        account = ChannelAccount(owner_user_id=legacy.id, channel_type="gmail", status="connected")
        db.add(account)
        db.flush()
        db.add(ChannelGrant(
            channel_account_id=account.id,
            channel_type="gmail",
            owner_user_id=legacy.id,
        ))
        db.add(Message(
            channel_account_id=account.id,
            provider="gmail_api_pubsub",
            external_message_id="legacy-preauth-free",
            direction="inbound",
            status="received",
            handling_status="pending",
            occurred_at=datetime(2026, 10, 23, tzinfo=timezone.utc),
            raw_content="legacy account message",
            customer_contact="legacy@example.com",
            normalized_customer_contact="legacy@example.com",
            contact_identity_state="certain",
            contact_identity_kind="email",
            link_state="unmatched",
        ))
        db.commit()

    login(business_client, "legacy-operator", "legacyop1")
    accounts = business_client.get("/api/channel-accounts")
    assert accounts.status_code == 200
    assert any(item["channel_type"] == "gmail" for item in accounts.json())
    messages = business_client.get("/api/messages")
    assert messages.status_code == 200
    assert "legacy-preauth-free" in {item["external_message_id"] for item in messages.json()["items"]}

    # Onboarding a different channel still requires an admin grant.
    csrf = business_client.cookies.get("ea_csrf")
    denied = business_client.post(
        "/api/channels/whatsapp/accounts",
        headers={"Origin": "https://testserver", "X-CSRF-Token": csrf},
    )
    assert denied.status_code == 403


def test_first_login_user_cannot_write_business_state_with_valid_csrf(business_client):
    """Stage 1 step 3: require_csrf and current_user must agree during forced password change."""
    def headers():
        return {"Origin": "https://testserver", "X-CSRF-Token": business_client.cookies.get("ea_csrf")}

    with business_client.testing_session() as db:
        pending = User(
            username="pending-operator",
            password_hash=hash_password("pendingop1"),
            role="staff",
            department="inquiry",
            is_active=True,
            must_change_password=True,
        )
        db.add(pending)
        db.flush()
        db.add(UserChannelPreauthorization(
            user_id=pending.id,
            channel_type="gmail",
            granted_by_user_id=6,
        ))
        db.commit()
        pending_id = pending.id
        before = db.get(Inquiry, 1)
        snapshot = (before.status, before.handling_status, before.assigned_sales_user_id)

    login(business_client, "pending-operator", "pendingop1")
    read = business_client.get("/api/messages", headers=headers())
    assert read.status_code == 403
    assert read.json()["detail"] == "首次登录必须修改密码"

    writes = [
        business_client.post("/api/channels/gmail/accounts", headers=headers()),
        business_client.post("/api/inquiries/1/transfer", json={"sales_user_id": 3}, headers=headers()),
        business_client.post("/api/inquiries/1/action", json={"action": "ignored"}, headers=headers()),
    ]
    assert [response.status_code for response in writes] == [403, 403, 403]
    assert all(response.json()["detail"] == "首次登录必须修改密码" for response in writes)

    with business_client.testing_session() as db:
        assert db.scalars(
            select(ChannelAccount).where(ChannelAccount.owner_user_id == pending_id)
        ).all() == []
        current = db.get(Inquiry, 1)
        assert (current.status, current.handling_status, current.assigned_sales_user_id) == snapshot

    # The two necessary exceptions still work: change password, then use the API.
    assert business_client.patch(
        "/auth/password", json={"new_password": "changedpass1"}, headers=headers()
    ).status_code == 200
    login(business_client, "pending-operator", "changedpass1")
    assert business_client.post("/api/channels/gmail/accounts", headers=headers()).status_code == 200


def test_first_login_user_can_logout_before_password_change(business_client):
    with business_client.testing_session() as db:
        db.add(User(
            username="pending-logout",
            password_hash=hash_password("pendinglo1"),
            role="staff",
            department="inquiry",
            is_active=True,
            must_change_password=True,
        ))
        db.commit()

    login(business_client, "pending-logout", "pendinglo1")
    headers = {"Origin": "https://testserver", "X-CSRF-Token": business_client.cookies.get("ea_csrf")}
    assert business_client.post("/auth/logout", headers=headers).status_code == 204
    assert business_client.get("/auth/me").status_code == 401


def test_channel_creation_requires_operating_role_and_admin_preauthorization(business_client):
    """Stage 1 step 3: a valid session/CSRF alone must never authorize onboarding."""
    def headers():
        return {"Origin": "https://testserver", "X-CSRF-Token": business_client.cookies.get("ea_csrf")}

    with business_client.testing_session() as db:
        before_ids = set(db.scalars(select(ChannelAccount.id)).all())

    login(business_client, "sales", "salespass1")
    assert business_client.post("/api/channels/gmail/accounts", headers=headers()).status_code == 403
    business_client.post("/auth/logout", headers=headers())

    # Administrators may connect channels on their own behalf (then transfer
    # the account to an operator). They are exempt from operator preauthorization
    # but still cannot touch any message read/write endpoint.
    login(business_client, "admin", "adminpass1")
    admin_created = business_client.post("/api/channels/gmail/accounts", headers=headers())
    assert admin_created.status_code == 200
    assert admin_created.json()["id"] == 5
    assert admin_created.json()["owner_user_id"] == 6
    assert {item["channel_type"] for item in business_client.get("/api/channels").json()} == {"gmail", "outlook", "whatsapp"}
    business_client.post("/auth/logout", headers=headers())

    login(business_client, "operator", "operator1")
    assert business_client.post("/api/channels/whatsapp/accounts", headers=headers()).status_code == 403
    assert {item["channel_type"] for item in business_client.get("/api/channels").json()} == {"gmail", "outlook"}
    business_client.post("/auth/logout", headers=headers())

    login(business_client, "empty-operator", "emptyop1")
    assert business_client.post("/api/channels/gmail/accounts", headers=headers()).status_code == 200
    assert business_client.post("/api/channels/outlook/accounts", headers=headers()).status_code == 403

    with business_client.testing_session() as db:
        new_ids = set(db.scalars(select(ChannelAccount.id)).all()) - before_ids
        assert len(new_ids) == 1
        created = db.get(ChannelAccount, new_ids.pop())
        assert (created.owner_user_id, created.channel_type) == (5, "gmail")


def test_legacy_unlinked_inquiry_is_not_exposed_without_visible_messages(business_client):
    """Stage 1 step 3: old records without links are not guessed into a reader's scope."""
    with business_client.testing_session() as db:
        assert list(db.get(Inquiry, 2).message_links) == []

    login(business_client, "operator", "operator1")
    headers = {"Origin": "https://testserver", "X-CSRF-Token": business_client.cookies.get("ea_csrf")}
    listing = business_client.get("/api/inquiries")
    assert 2 not in {item["id"] for item in listing.json()["items"]}
    assert business_client.get("/api/inquiries/2").status_code == 404
    assert business_client.post(
        "/api/inquiries/2/action", json={"action": "ignored"}, headers=headers
    ).status_code == 403
    business_client.post("/auth/logout", headers=headers)

    # Admin keeps the confirmed company-wide inquiry scope even for unlinked rows.
    login(business_client, "admin", "adminpass1")
    headers = {"Origin": "https://testserver", "X-CSRF-Token": business_client.cookies.get("ea_csrf")}
    admin_listing = business_client.get("/api/inquiries")
    assert 2 in {item["id"] for item in admin_listing.json()["items"]}
    assert business_client.get("/api/inquiries/2").status_code == 200
    assert business_client.post(
        "/api/inquiries/2/action", json={"action": "ignored"}, headers=headers
    ).status_code == 200

    with business_client.testing_session() as db:
        assert db.get(Inquiry, 2).handling_status == "ignored"
        assert db.scalars(select(InquiryMessage).where(InquiryMessage.inquiry_id == 2)).all() == []


def test_gmail_account_initialization_requires_authentication(business_client):
    assert business_client.post("/api/channels/gmail/accounts").status_code == 401


def test_whatsapp_revoke_removes_empty_shell_and_allows_fresh_pairing(business_client):
    """撤销 = 清理干净: an empty shell must be deleted, not left as a zombie."""
    login(business_client, "empty-operator", "emptyop1")
    csrf = business_client.cookies.get("ea_csrf")
    headers = {"Origin": "https://testserver", "X-CSRF-Token": csrf}

    first = business_client.post("/api/channels/whatsapp/accounts", headers=headers)
    assert first.status_code == 200
    account_id = first.json()["id"]
    assert first.json()["status"] == "not_ready"

    revoked = business_client.post(
        f"/api/channels/accounts/{account_id}/revoke",
        headers=headers,
    )
    assert revoked.status_code == 200
    assert revoked.json()["status"] == "removed"
    assert revoked.json()["cleanup"] == "removed"
    assert business_client.get("/api/channel-accounts").json() == []
    with business_client.testing_session() as db:
        assert db.get(ChannelAccount, account_id) is None
        assert db.scalars(select(ChannelGrant).where(ChannelGrant.channel_account_id == account_id)).all() == []

    fresh = business_client.post("/api/channels/whatsapp/accounts", headers=headers)
    assert fresh.status_code == 200
    # SQLite may reuse the deleted row's id; what matters is that the new
    # record is a clean, unbound shell with no revoked-history marker.
    assert fresh.json()["status"] == "not_ready"
    assert fresh.json()["external_account_id"] is None


def test_admin_history_regrant_restores_revoked_account_for_operator(business_client):
    """Channel preauthorization is unrelated to a revoked history marker."""
    def headers():
        return {"Origin": "https://testserver", "X-CSRF-Token": business_client.cookies.get("ea_csrf")}

    login(business_client, "empty-operator", "emptyop1")
    created = business_client.post("/api/channels/whatsapp/accounts", headers=headers())
    assert created.status_code == 200
    account_id = created.json()["id"]
    # Shells with collected history are archived, never deleted silently.
    with business_client.testing_session() as db:
        db.add(Message(
            channel_account_id=account_id,
            provider="whatsapp_baileys",
            external_message_id="wa-history-1",
            direction="inbound",
            status="received",
            handling_status="pending",
            occurred_at=datetime(2026, 11, 1, tzinfo=timezone.utc),
            raw_content="collected before disconnect",
            link_state="linked",
        ))
        db.commit()
    revoked = business_client.post(f"/api/channels/accounts/{account_id}/revoke", headers=headers())
    assert revoked.status_code == 200
    assert revoked.json()["cleanup"] == "archived_with_history"
    assert business_client.post("/api/channels/whatsapp/accounts", headers=headers()).status_code == 403
    assert business_client.get("/api/channel-accounts").json() == []
    business_client.post("/auth/logout", headers=headers())

    login(business_client, "admin", "adminpass1")
    listing = business_client.get("/auth/admin/channel-accounts")
    assert listing.status_code == 200
    target = next(item for item in listing.json() if item["id"] == account_id)
    assert target["history_access_revoked"] is True
    assert target["status"] == "revoked"

    regranted = business_client.post(
        f"/auth/admin/channel-accounts/{account_id}/history-access", headers=headers()
    )
    assert regranted.status_code == 200
    assert regranted.json()["account_status"] == "not_ready"
    target = next(item for item in business_client.get("/auth/admin/channel-accounts").json() if item["id"] == account_id)
    assert target["history_access_revoked"] is False
    assert target["status"] == "not_ready"
    business_client.post("/auth/logout", headers=headers())

    login(business_client, "empty-operator", "emptyop1")
    assert account_id in {item["id"] for item in business_client.get("/api/channel-accounts").json()}
    reused = business_client.post("/api/channels/whatsapp/accounts", headers=headers())
    assert reused.status_code == 200
    assert reused.json()["id"] == account_id


def test_revoked_channel_is_not_readable_but_history_is_retained(business_client):
    login(business_client, "operator", "operator1")

    accounts = business_client.get("/api/channel-accounts")
    messages = business_client.get("/api/messages")
    inquiries = business_client.get("/api/inquiries")

    assert accounts.status_code == 200
    assert all(account["status"] != "revoked" for account in accounts.json())
    assert messages.status_code == 200
    assert all(message["external_message_id"] != "revoked-gmail-1" for message in messages.json()["items"])
    assert inquiries.status_code == 200
    assert [item["id"] for item in inquiries.json()["items"]] == [1]
    assert [item["id"] for item in inquiries.json()["items"][0]["messages"]] == [1]
    assert "Revoked account historical message" not in str(inquiries.json()["items"])
    assert "Secret <secret-revoked@example.com>" not in str(inquiries.json()["items"])
    # The only Inquiry tied to this revoked source has no visible linked message.
    # Its detail is hidden as 404 and the list total/sort contains no trace.
    assert business_client.get("/api/messages/2").status_code == 403
    assert business_client.get("/api/inquiries/4").status_code == 404


def test_operator_reads_authorized_safe_message_content_only(business_client):
    login(business_client, "operator", "operator1")

    response = business_client.get("/api/messages/1/content")

    assert response.status_code == 200
    body = response.json()
    assert body["source"] == {
        "kind": "cached_safe_text",
        "provider": "gmail_api_pubsub",
        "external_message_id": "fixture-gmail-1",
        "live_refetch": False,
        "fallback_reason": "provider_refetch_unavailable",
        "authoritative": True,
        "refetch_status": "snapshot",
        "snapshot_at": body["source"]["snapshot_at"],
    }
    assert body["raw_content_exposed"] is False
    assert body["parsed_content"]["content_format"] == "text/plain"
    assert body["parsed_content"]["content_sanitized"] is True
    assert body["full_text"] == "Fake fixture message"
    assert body["preview_text"] == "Fake fixture message"
    assert body["attachments"] == [{
        "id": body["attachments"][0]["id"],
        "original_filename": "fixture.pdf",
        "media_type": "application/pdf",
        "size_bytes": 42,
    }]
    assert "storage_reference" not in body["attachments"][0]
    assert "raw_content" not in body


def test_message_content_rejects_cross_account_and_revoked_messages(business_client):
    login(business_client, "operator", "operator1")

    assert business_client.get("/api/messages/5/content").status_code == 403
    assert business_client.get("/api/messages/2/content").status_code == 403
    assert business_client.get("/api/messages/999/content").status_code == 403


def test_review_messages_are_filtered_and_scoped(business_client):
    login(business_client, "operator", "operator1")
    review = business_client.get("/api/messages", params={"needs_review": "true"})
    assert review.status_code == 200
    assert {item["external_message_id"] for item in review.json()["items"]} == {"fixture-unmatched-review"}


def test_operator_reads_only_granted_owned_channel_and_inquiries(business_client):
    login(business_client, "operator", "operator1")

    messages = business_client.get("/api/messages")
    assert messages.status_code == 200
    messages_by_external_id = {
        message["external_message_id"]: message for message in messages.json()["items"]
    }
    assert set(messages_by_external_id) == {
        "fixture-gmail-1",
        "fixture-unmatched-review",
        "fixture-unmatched",
    }
    message = messages_by_external_id["fixture-gmail-1"]
    assert message["channel_type"] == "gmail"
    assert message["ingestion_status"] == "received"
    assert message["handling_status"] == "pending"
    assert message["attachments"] == [
        {
            "id": message["attachments"][0]["id"],
            "original_filename": "fixture.pdf",
            "media_type": "application/pdf",
            "size_bytes": 42,
        }
    ]
    assert "storage_reference" not in message["attachments"][0]
    assert business_client.get("/api/messages/2").status_code == 403
    assert business_client.get("/api/messages/999").status_code == 403

    accounts = business_client.get("/api/channel-accounts")
    assert accounts.status_code == 200
    assert [account["channel_type"] for account in accounts.json()] == ["gmail", "outlook"]
    assert accounts.json()[1]["status"] == "blocked"

    inquiries = business_client.get("/api/inquiries")
    assert inquiries.status_code == 200
    inquiry_data = inquiries.json()["items"][0]
    assert inquiry_data["timeline_complete"] is True
    assert inquiry_data["attachments"] == []
    assert inquiry_data["source_channel_account_id"] is None
    assert inquiry_data["contact_sources"][0]["raw_customer_contact"] == "Customer <customer@example.com>"
    assert inquiry_data["messages"][0]["id"] == 1
    assert inquiry_data["messages"][0]["provider"] == "gmail_api_pubsub"
    assert inquiry_data["messages"][0]["external_message_id"] == "fixture-gmail-1"
    assert inquiry_data["messages"][0]["overview_status"] == "not_generated"
    assert "raw_content" not in inquiry_data["messages"][0]
    assert inquiry_data["messages"][0]["overview_text"] is None
    assert "raw_content" not in inquiry_data
    assert "display_text" not in inquiry_data
    assert all(message["overview_text"] is None for message in inquiry_data["messages"])
    assert "Revoked account historical message" not in str(inquiries.json()["items"][0])
    assert "secret-revoked@example.com" not in str(inquiries.json()["items"][0])
    assert len(inquiries.json()["items"][0]["messages"]) == 1
    assert [event["event_type"] for event in inquiries.json()["items"][0]["timeline"]] == ["inquiry_created"]

    assert business_client.get("/api/inquiries/2").status_code == 404


def test_sales_reads_only_assigned_inquiry_and_notification(business_client):
    login(business_client, "sales", "salespass1")

    messages = business_client.get("/api/messages")
    assert messages.status_code == 200
    # Sales can read only messages linked to their assigned inquiry, never
    # unrelated account-wide mail.
    assert [message["id"] for message in messages.json()["items"]] == [6]
    assert business_client.get("/api/messages/1").status_code == 403
    assert business_client.get("/api/messages/6").status_code == 200
    assert business_client.get("/api/messages/5").status_code == 403
    assert business_client.get("/api/messages/2").status_code == 403
    assert business_client.get("/api/messages/999").status_code == 403

    inquiries = business_client.get("/api/inquiries")
    assert inquiries.status_code == 200
    assert [inquiry["id"] for inquiry in inquiries.json()["items"]] == [3]
    assert [message["id"] for message in inquiries.json()["items"][0]["messages"]] == [6]
    # Inquiry responses never aggregate message/inquiry attachment metadata;
    # authorized attachments are available only from the scoped message endpoint.
    assert inquiries.json()["items"][0]["attachments"] == []
    assert inquiries.json()["items"][0]["timeline_complete"] is True
    assert [event["event_type"] for event in inquiries.json()["items"][0]["timeline"]] == [
        "inquiry_created",
        "inquiry_transferred",
    ]

    assert business_client.get("/api/inquiries/2").status_code == 404
    assert business_client.get("/api/notifications/1").status_code == 403
    assert business_client.get("/api/inquiries/4").status_code == 404


def test_sales_cannot_read_revoked_source_inquiry(business_client):
    login(business_client, "sales", "salespass1")

    inquiries = business_client.get("/api/inquiries")

    assert inquiries.status_code == 200
    assert [item["id"] for item in inquiries.json()["items"]] == [3]
    assert business_client.get("/api/inquiries/4").status_code == 404


def test_external_binding_is_scoped_and_prevents_duplicate_accounts(business_client):
    login(business_client, "operator", "operator1")
    csrf = business_client.cookies.get("ea_csrf")
    headers = {"Origin": "https://testserver", "X-CSRF-Token": csrf}

    first = business_client.post(
        "/api/channels/accounts/1/external-binding",
        json={"external_account_id": "fixture-external-1", "status": "external_authorization_required"},
        headers=headers,
    )
    duplicate = business_client.post(
        "/api/channels/accounts/1/external-binding",
        json={"external_account_id": "fixture-external-1", "status": "external_authorization_required"},
        headers=headers,
    )

    assert first.status_code == 200
    assert first.json()["external_account_id"] == "fixture-external-1"
    assert duplicate.status_code == 200


def test_operator_can_list_transfer_targets(business_client):
    login(business_client, "operator", "operator1")

    response = business_client.get("/api/inquiry-transfer-targets")

    assert response.status_code == 200
    assert response.json() == [
        {"id": 3, "username": "sales", "full_name": None, "name": "sales", "role": "sales"},
        {"id": 4, "username": "other-sales", "full_name": None, "name": "other-sales", "role": "sales"},
    ]


def test_non_operator_roles_cannot_list_transfer_targets(business_client):
    with business_client.testing_session() as db:
        db.add(User(username="manager", password_hash=hash_password("manager1"), role="operations", manager_overlay_enabled=True, department="inquiry", is_active=True, must_change_password=False))
        db.commit()
    login(business_client, "sales", "salespass1")

    response = business_client.get("/api/inquiry-transfer-targets")

    assert response.status_code == 403
    assert response.json()["detail"] == "没有权限访问"
    business_client.post("/auth/logout", headers={"Origin": "https://testserver", "X-CSRF-Token": business_client.cookies.get("ea_csrf")})
    login(business_client, "manager", "manager1")
    assert business_client.get("/api/inquiry-transfer-targets").status_code == 403


def test_operator_transfer_is_idempotent_for_same_target(business_client):
    # 负责人对外展示的是员工姓名，账号只是登录凭据；转交人则是点「分配」的运营账号。
    with business_client.testing_session() as db:
        db.get(User, 3).full_name = "销售一"
        db.get(User, 1).full_name = "运营一"
        db.commit()

    login(business_client, "operator", "operator1")
    csrf = business_client.cookies.get("ea_csrf")
    headers = {"Origin": "https://testserver", "X-CSRF-Token": csrf}
    body = {"sales_user_id": 3}

    first = business_client.post("/api/inquiries/1/transfer", json=body, headers=headers)
    second = business_client.post("/api/inquiries/1/transfer", json=body, headers=headers)
    different_target = business_client.post(
        "/api/inquiries/1/transfer",
        json={"sales_user_id": 4},
        headers=headers,
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["status"] == "assigned"
    assert second.json()["assigned_sales_user_id"] == 3
    # 详情头部显示「员工姓名」，账号仅作副标识，绝不出现「用户 #3」。
    assert second.json()["assigned_sales_name"] == "销售一"
    assert second.json()["assigned_sales_username"] == "sales"
    # 转交人 = 点「分配」的运营，与负责人分开记录。
    assert second.json()["transferred_by_name"] == "运营一"
    assert second.json()["transferred_by_username"] == "operator"
    assert second.json()["transferred_at"] is not None
    assert different_target.status_code == 403
    assert len(second.json()["timeline"]) == 2
    assert [event["event_type"] for event in second.json()["timeline"]].count("inquiry_transferred") == 1
    assert business_client.get("/api/notifications/1").status_code == 403
    assert business_client.get("/api/notifications/2").status_code == 403

    business_client.post(
        "/auth/logout",
        headers={"Origin": "https://testserver", "X-CSRF-Token": csrf},
    )
    login(business_client, "sales", "salespass1")
    assert business_client.get("/api/notifications/1").status_code == 200
    assert business_client.get("/api/notifications/2").status_code == 403


def test_unscoped_user_cannot_read_inquiry_timeline(business_client):
    login(business_client, "other-operator", "otherop1")

    response = business_client.get("/api/inquiries/1")

    assert response.status_code == 404
    assert response.json()["detail"] == "没有权限访问"


def test_sales_cannot_transfer_or_change_inquiry_state(business_client):
    login(business_client, "sales", "salespass1")
    csrf = business_client.cookies.get("ea_csrf")
    headers = {"Origin": "https://testserver", "X-CSRF-Token": csrf}

    transfer = business_client.post(
        "/api/inquiries/3/transfer",
        json={"sales_user_id": 4},
        headers=headers,
    )
    action = business_client.post(
        "/api/inquiries/3/action",
        json={"action": "processed"},
        headers=headers,
    )

    assert transfer.status_code == 403
    assert action.status_code == 403
    assert action.json()["detail"] == "没有权限访问"


def test_inquiry_handling_actions_are_idempotent_and_audited(business_client):
    login(business_client, "operator", "operator1")
    csrf = business_client.cookies.get("ea_csrf")
    headers = {"Origin": "https://testserver", "X-CSRF-Token": csrf}

    first = business_client.post(
        "/api/inquiries/1/action",
        json={"action": "ignored"},
        headers=headers,
    )
    second = business_client.post(
        "/api/inquiries/1/action",
        json={"action": "ignored"},
        headers=headers,
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["handling_status"] == "ignored"
    assert second.json()["handling_status"] == "ignored"
    assert [event["event_type"] for event in second.json()["timeline"]] == [
        "inquiry_created",
        "inquiry_ignored",
    ]


def test_inquiry_handling_action_can_be_processed_and_analysis_counts_it(business_client):
    login(business_client, "operator", "operator1")
    csrf = business_client.cookies.get("ea_csrf")
    response = business_client.post(
        "/api/inquiries/1/action",
        json={"action": "processed"},
        headers={"Origin": "https://testserver", "X-CSRF-Token": csrf},
    )

    assert response.status_code == 200
    assert response.json()["handling_status"] == "processed"
    analysis = business_client.post("/api/internal-analysis", json={"operation": "read"})
    assert analysis.status_code == 200
    assert analysis.json()["inquiries_by_handling_status"] == {
        "pending": 0,
        "processed": 1,
        "ignored": 0,
    }


def test_inquiry_handling_action_rolls_back_event_and_status_on_commit_failure(monkeypatch, business_client):
    login(business_client, "operator", "operator1")
    csrf = business_client.cookies.get("ea_csrf")
    original_commit = Session.commit

    def fail_commit(self):
        raise RuntimeError("fixture audit commit failure")

    monkeypatch.setattr(Session, "commit", fail_commit)
    response = business_client.post(
        "/api/inquiries/1/action",
        json={"action": "ignored"},
        headers={"Origin": "https://testserver", "X-CSRF-Token": csrf},
    )
    assert response.status_code == 500

    monkeypatch.setattr(Session, "commit", original_commit)
    login(business_client, "operator", "operator1")
    inquiry = business_client.get("/api/inquiries/1")
    assert inquiry.json()["handling_status"] == "pending"
    assert [event["event_type"] for event in inquiry.json()["timeline"]] == ["inquiry_created"]


def test_invalid_human_action_is_rejected_before_database_write(business_client):
    login(business_client, "operator", "operator1")
    csrf = business_client.cookies.get("ea_csrf")
    response = business_client.post(
        "/api/messages/1/action",
        json={"action": "send"},
        headers={"Origin": "https://testserver", "X-CSRF-Token": csrf},
    )

    assert response.status_code == 422
    assert business_client.get("/api/messages/1").status_code == 200


def test_message_handling_actions_are_idempotent_and_persisted(business_client):
    login(business_client, "operator", "operator1")
    csrf = business_client.cookies.get("ea_csrf")
    headers = {"Origin": "https://testserver", "X-CSRF-Token": csrf}

    first = business_client.post(
        "/api/messages/1/action",
        json={"action": "processed"},
        headers=headers,
    )
    assert first.status_code == 409
    assert "关联询盘" in first.json()["detail"]
    assert business_client.get("/api/messages/1").json()["handling_status"] == "pending"


def test_message_handling_action_rolls_back_on_database_failure(monkeypatch, business_client):
    login(business_client, "operator", "operator1")
    csrf = business_client.cookies.get("ea_csrf")
    original_commit = Session.commit

    def fail_commit(self):
        raise RuntimeError("fixture message commit failure")

    monkeypatch.setattr(Session, "commit", fail_commit)
    response = business_client.post(
        "/api/inquiries/1/action",
        json={"action": "processed"},
        headers={"Origin": "https://testserver", "X-CSRF-Token": csrf},
    )
    assert response.status_code == 500

    monkeypatch.setattr(Session, "commit", original_commit)
    login(business_client, "operator", "operator1")
    assert business_client.get("/api/inquiries/1").json()["handling_status"] == "pending"
    assert business_client.get("/api/messages/1").json()["handling_status"] == "pending"


def test_human_action_does_not_reveal_unscoped_inquiry(business_client):
    login(business_client, "operator", "operator1")
    csrf = business_client.cookies.get("ea_csrf")
    response = business_client.post(
        "/api/inquiries/2/action",
        json={"action": "processed"},
        headers={"Origin": "https://testserver", "X-CSRF-Token": csrf},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "没有权限访问"


def test_transfer_requires_csrf_and_does_not_change_without_it(business_client):
    login(business_client, "operator", "operator1")

    response = business_client.post(
        "/api/inquiries/1/transfer",
        json={"sales_user_id": 3},
        headers={"Origin": "https://testserver"},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "CSRF 校验失败"


def test_operator_transfer_sets_assigned_and_creates_internal_notification(business_client):
    login(business_client, "operator", "operator1")
    csrf = business_client.cookies.get("ea_csrf")

    response = business_client.post(
        "/api/inquiries/1/transfer",
        json={"sales_user_id": 3},
        headers={"Origin": "https://testserver", "X-CSRF-Token": csrf},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "assigned"
    assert response.json()["assigned_sales_user_id"] == 3
    assert [event["event_type"] for event in response.json()["timeline"]] == [
        "inquiry_created",
        "inquiry_transferred",
    ]
    assert response.json()["timeline"][1]["actor_user_id"] == 1
    assert response.json()["timeline"][1]["target_user_id"] == 3

    business_client.post("/auth/logout", headers={"Origin": "https://testserver", "X-CSRF-Token": csrf})
    login(business_client, "sales", "salespass1")
    notifications = business_client.get("/api/notifications/1")
    assert notifications.status_code == 200
    assert notifications.json()["inquiry_id"] == 1
    assert notifications.json()["notification_type"] == "inquiry_assigned"


def test_transfer_rollback_keeps_inquiry_unassigned(monkeypatch, business_client):
    login(business_client, "operator", "operator1")
    csrf = business_client.cookies.get("ea_csrf")
    original_commit = Session.commit

    def fail_commit(self):
        raise RuntimeError("fixture commit failure")

    monkeypatch.setattr(Session, "commit", fail_commit)
    response = business_client.post(
        "/api/inquiries/1/transfer",
        json={"sales_user_id": 3},
        headers={"Origin": "https://testserver", "X-CSRF-Token": csrf},
    )

    assert response.status_code == 500

    monkeypatch.undo()
    login(business_client, "operator", "operator1")
    inquiry = business_client.get("/api/inquiries/1")
    assert inquiry.status_code == 200
    assert inquiry.json()["status"] == "new"
    assert inquiry.json()["assigned_sales_user_id"] is None
    assert [event["event_type"] for event in inquiry.json()["timeline"]] == ["inquiry_created"]


def test_transfer_db_failure_rolls_back_notification_and_event(monkeypatch, business_client):
    login(business_client, "operator", "operator1")
    csrf = business_client.cookies.get("ea_csrf")
    original_commit = Session.commit

    def fail_commit(self):
        raise RuntimeError("fixture database failure")

    monkeypatch.setattr(Session, "commit", fail_commit)
    response = business_client.post(
        "/api/inquiries/1/transfer",
        json={"sales_user_id": 3},
        headers={"Origin": "https://testserver", "X-CSRF-Token": csrf},
    )
    assert response.status_code == 500

    monkeypatch.setattr(Session, "commit", original_commit)
    login(business_client, "operator", "operator1")
    inquiry = business_client.get("/api/inquiries/1")
    assert inquiry.status_code == 200
    assert inquiry.json()["status"] == "new"
    assert inquiry.json()["assigned_sales_user_id"] is None
    assert [event["event_type"] for event in inquiry.json()["timeline"]] == ["inquiry_created"]


def test_internal_analysis_returns_zero_for_empty_authorized_scope(business_client):
    login(business_client, "empty-operator", "emptyop1")

    response = business_client.post(
        "/api/internal-analysis",
        json={"operation": "read"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["mode"] == "read_only"
    assert data["read_only"] is True
    assert data["mutation_performed"] is False
    assert data["write_operations_performed"] == 0
    assert data["unlinked_messages"] == []
    assert data["messages_needing_manual_review"] == []
    assert data["pending_message_count"] == 0
    assert data["inquiries_by_status"] == {"new": 0, "assigned": 0}
    assert data["inquiries_by_handling_status"] == {
        "pending": 0,
        "processed": 0,
        "ignored": 0,
    }
    assert data["my_transfers"] == []
    assert data["channel_statuses"] == []
    assert data["messages_by_link_state"] == {"pending": 0, "linked": 0, "unmatched": 0, "manual_review": 0, "not_linkable": 0}
    assert data["inquiries_by_lifecycle_stage"] == {"unknown": 0, "active": 0, "archived_silent": 0, "purge_due": 0}


def _business_read_snapshot(session):
    return {
        "inquiries": tuple(session.execute(select(Inquiry.id, Inquiry.status, Inquiry.handling_status, Inquiry.assigned_sales_user_id, Inquiry.last_activity_at)).all()),
        "messages": tuple(session.execute(select(Message.id, Message.handling_status, Message.link_state, Message.contact_identity_state, Message.contact_identity_kind, Message.customer_contact, Message.normalized_customer_contact, Message.original_sender_contact)).all()),
        "events": tuple(session.execute(select(InquiryEvent.id, InquiryEvent.inquiry_id, InquiryEvent.event_type, InquiryEvent.message_id)).all()),
        "notifications": tuple(session.execute(select(InternalNotification.id, InternalNotification.inquiry_id, InternalNotification.notification_type, InternalNotification.content)).all()),
        "accounts": tuple(session.execute(select(ChannelAccount.id, ChannelAccount.status)).all()),
        "links": tuple(session.execute(select(InquiryMessage.inquiry_id, InquiryMessage.message_id, InquiryMessage.position)).all()),
    }


def test_internal_analysis_excludes_revoked_only_inquiry_and_manual_review_is_scoped(business_client):
    login(business_client, "operator", "operator1")
    response = business_client.post("/api/internal-analysis", json={"operation": "read"})
    assert response.status_code == 200
    data = response.json()
    assert all(row["id"] != 2 for row in data["unlinked_messages"])
    assert all(row["id"] != 2 for row in data["messages_needing_manual_review"])
    # Blocked account remains an authorized account and is surfaced distinctly.
    assert any(row["channel_account_id"] == 2 and row["status"] == "blocked" for row in data["channel_statuses"])


def test_internal_analysis_exposes_admin_inquiry_aggregate_and_sales_scope(business_client):
    login(business_client, "admin", "adminpass1")
    admin_data = business_client.post("/api/internal-analysis", json={"operation": "read"}).json()
    assert admin_data["query_scope"] == "company_wide_inquiry_inspection"
    assert admin_data["pending_message_count"] == 4
    assert admin_data["inquiries_by_status"] == {"new": 2, "assigned": 2}
    for key in ("unlinked_messages", "messages_needing_manual_review"):
        for row in admin_data[key]:
            assert "provider" not in row
            assert "external_message_id" not in row
            assert "channel_account_id" not in row
    for row in admin_data["channel_statuses"]:
        assert "channel_account_id" not in row

    business_client.post("/auth/logout", headers={"Origin": "https://testserver", "X-CSRF-Token": business_client.cookies.get("ea_csrf")})
    login(business_client, "sales", "salespass1")
    sales_data = business_client.post("/api/internal-analysis", json={"operation": "read"}).json()
    assert sales_data["pending_message_count"] == 1
    assert sales_data["inquiries_by_status"] == {"new": 0, "assigned": 1}
    assert sales_data["messages_by_link_state"]["linked"] == 1


def test_internal_analysis_is_authorized_and_read_only(business_client, monkeypatch):
    login(business_client, "operator", "operator1")
    commit_calls = []
    original_commit = Session.commit

    def track_commit(session):
        commit_calls.append(True)
        return original_commit(session)

    with business_client.testing_session() as snapshot_session:
        before_snapshot = _business_read_snapshot(snapshot_session)
    monkeypatch.setattr(Session, "commit", track_commit)
    response = business_client.post(
        "/api/internal-analysis",
        json={"operation": "read"},
    )

    assert response.status_code == 200
    assert commit_calls == []
    with business_client.testing_session() as snapshot_session:
        after_snapshot = _business_read_snapshot(snapshot_session)
    assert after_snapshot == before_snapshot
    data = response.json()
    assert data["mode"] == "read_only"
    assert data["read_only"] is True
    assert data["pending_message_count"] == 3
    assert data["pending_inbound_message_count"] == 3
    assert data["pending_contact_count"] == 2
    assert data["messages_by_link_state"]["linked"] == 1
    assert data["messages_by_link_state"]["manual_review"] == 1
    assert data["messages_by_link_state"]["unmatched"] == 1
    assert data["messages_by_identity_state"]["identity_uncertain"] == 1
    assert data["inquiries_by_lifecycle_stage"]["unknown"] == 1
    assert len(data["unlinked_messages"]) == 1
    assert "customer_contact" not in data["unlinked_messages"][0]
    assert data["messages_needing_manual_review"][0]["id"] == 3
    assert data["messages_by_identity_state"]["certain"] == 2
    assert data["messages_by_identity_state"]["identity_uncertain"] == 1
    assert data["recent_events"][0]["event_type"] == "inquiry_created"
    assert data["unlinked_messages"][0]["id"] == 4
    assert data["inquiries_by_status"] == {"new": 1, "assigned": 0}
    assert data["inquiries_by_handling_status"] == {
        "pending": 1,
        "processed": 0,
        "ignored": 0,
    }
    assert data["my_transfers"] == []
    assert data["test_only"]
    assert len(data["recent_events"]) == 1
    assert data["recent_events"][0]["inquiry_id"] == 1
    assert data["channel_statuses"] == [
        {
            "channel_account_id": 1,
            "channel_type": "gmail",
            "status": "connected",
            "is_abnormal": False,
        },
        {
            "channel_account_id": 2,
            "channel_type": "outlook",
            "status": "blocked",
            "is_abnormal": True,
        },
    ]
    assert "test_only" in data

    inquiries = business_client.get("/api/inquiries")
    assert [item["status"] for item in inquiries.json()["items"]] == ["new"]


def test_internal_analysis_includes_blocked_but_authorized_account_and_excludes_revoked(business_client):
    login(business_client, "operator", "operator1")
    with business_client.testing_session() as db:
        db.add(Message(
            channel_account_id=2,
            provider="outlook_mcp_graph",
            external_message_id="blocked-fixture",
            direction="inbound",
            status="received",
            handling_status="pending",
            occurred_at=datetime(2026, 10, 24, tzinfo=timezone.utc),
            raw_content="blocked account fixture",
            customer_contact="blocked@example.com",
            normalized_customer_contact="blocked@example.com",
            contact_identity_state="certain",
            contact_identity_kind="email",
            link_state="unmatched",
        ))
        db.commit()

    response = business_client.post("/api/internal-analysis", json={"operation": "read"})
    assert response.status_code == 200
    data = response.json()
    assert data["pending_message_count"] == 4
    assert any(item["channel_account_id"] == 2 and item["status"] == "blocked" for item in data["channel_statuses"])
    assert 2 not in {item["channel_account_id"] for item in data["unlinked_messages"]} or any(
        item["provider"] == "outlook_mcp_graph" for item in data["unlinked_messages"]
    )
    assert all("secret-revoked@example.com" not in str(item) for item in data["unlinked_messages"])


def test_sales_analysis_is_scoped_to_assigned_inquiries(business_client):
    login(business_client, "sales", "salespass1")

    response = business_client.post(
        "/api/internal-analysis",
        json={"operation": "read"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["pending_message_count"] == 1
    assert data["pending_inbound_message_count"] == 1
    assert data["pending_contact_count"] == 1
    assert data["messages_by_link_state"]["linked"] == 1
    assert data["unlinked_messages"] == []
    assert data["messages_needing_manual_review"] == []
    assert data["inquiries_by_lifecycle_stage"]["active"] == 1
    assert data["inquiries_by_status"] == {"new": 0, "assigned": 1}
    assert data["inquiries_by_handling_status"] == {
        "pending": 1,
        "processed": 0,
        "ignored": 0,
    }
    assert [item["inquiry_id"] for item in data["my_transfers"]] == [3]
    assert data["my_transfers"][0]["current_stage"] == "assigned"
    assert data["my_transfers"][0]["recent_event"]["source"] == "inquiry_events"
    assert data["my_transfers"][0]["recent_event"]["event_history_available"] is True
    assert data["channel_statuses"] == []
    assert data["event_history_available"] is True
    assert data["event_source"] == "inquiry_events"


def test_internal_analysis_requires_auth_and_non_read_is_guidance(business_client, monkeypatch):
    assert business_client.post("/api/internal-analysis").status_code == 401

    login(business_client, "operator", "operator1")
    from sqlalchemy.orm import Session

    original_commit = Session.commit
    commits = []
    def track_commit(self):
        commits.append(True)
        return original_commit(self)
    monkeypatch.setattr(Session, "commit", track_commit)

    with business_client.testing_session() as snapshot_session:
        before_snapshot = _business_read_snapshot(snapshot_session)
    for operation in ("create", "update", "delete", "assign", "send"):
        response = business_client.post(
            "/api/internal-analysis",
            json={"operation": operation},
        )
        assert response.status_code == 200
        assert response.json()["mode"] == "guidance"
        assert response.json()["read_only"] is True
        assert response.json()["page"] == ("/messages" if operation == "send" else "/inquiries")
        with business_client.testing_session() as snapshot_session:
            assert _business_read_snapshot(snapshot_session) == before_snapshot
    assert commits == []
    with business_client.testing_session() as snapshot_session:
        assert _business_read_snapshot(snapshot_session) == before_snapshot


def test_internal_ai_is_read_only_and_returns_operation_guidance(business_client):
    login(business_client, "operator", "operator1")

    with business_client.testing_session() as snapshot_session:
        before_snapshot = _business_read_snapshot(snapshot_session)
    read = business_client.post(
        "/api/internal-ai/query",
        json={"query": "inquiries", "operation": "read"},
    )
    assert read.status_code == 200
    assert read.json()["mode"] == "read_only"
    assert read.json()["actor_id"] == 1
    assert read.json()["read_only"] is True
    assert "display_text" not in read.json()["data"][0]
    assert read.json()["data"][0]["messages"][0]["id"] == 1
    assert "Revoked account historical message" not in str(read.json()["data"])
    assert "secret-revoked@example.com" not in str(read.json()["data"])
    assert read.json()["data"][0]["timeline_complete"] is True
    with business_client.testing_session() as snapshot_session:
        assert _business_read_snapshot(snapshot_session) == before_snapshot

    write = business_client.post(
        "/api/internal-ai/query",
        json={"query": "inquiries", "operation": "assign"},
    )
    assert write.status_code == 200
    assert write.json()["mode"] == "guidance"
    assert write.json()["read_only"] is True
    assert write.json()["page"] == "/inquiries"
    with business_client.testing_session() as snapshot_session:
        assert _business_read_snapshot(snapshot_session) == before_snapshot


def test_inbox_list_contract_supports_authorized_filters_sorting_and_pagination(business_client):
    login(business_client, "operator", "operator1")

    messages = business_client.get(
        "/api/messages",
        params={
            "handling_status": "pending",
            "ingestion_status": "received",
            "channel_account_id": 1,
            "sort": "occurred_at",
            "descending": "true",
            "page": 1,
            "page_size": 1,
        },
    )
    inquiries = business_client.get(
        "/api/inquiries",
        params={
            "status": "new",
            "handling_status": "pending",
            "channel_account_id": 1,
            "sort": "updated_at",
            "descending": "true",
            "page": 1,
            "page_size": 1,
        },
    )

    assert messages.status_code == inquiries.status_code == 200
    assert set(messages.json()) == {"items", "page", "page_size", "has_more"}
    assert set(inquiries.json()) == {"items", "page", "page_size", "has_more", "total_count"}
    assert messages.json()["page"] == inquiries.json()["page"] == 1
    assert messages.json()["page_size"] == inquiries.json()["page_size"] == 1
    assert [item["external_message_id"] for item in messages.json()["items"]] == ["fixture-unmatched"]
    assert messages.json()["has_more"] is True
    assert [item["id"] for item in inquiries.json()["items"]] == [1]
    assert messages.json()["items"][0]["ingestion_status"] == "received"
    assert messages.json()["items"][0]["handling_status"] == "pending"
    assert inquiries.json()["items"][0]["status"] == "new"
    assert inquiries.json()["items"][0]["handling_status"] == "pending"


def test_inbox_list_empty_result_is_a_valid_authorized_response(business_client):
    login(business_client, "operator", "operator1")

    response = business_client.get(
        "/api/inquiries",
        params={"handling_status": "processed", "channel_account_id": 1},
    )

    assert response.status_code == 200
    assert response.json() == {
        "items": [],
        "page": 1,
        "page_size": 50,
        "has_more": False,
        "total_count": 0,
    }


def test_inbox_filter_cannot_escape_authorized_channel_scope(business_client):
    login(business_client, "operator", "operator1")

    response = business_client.get(
        "/api/messages",
        params={"channel_account_id": 3},
    )

    assert response.status_code == 200
    assert response.json()["items"] == []


def test_inbox_rejects_invalid_filters_and_paging_before_query_execution(business_client):
    login(business_client, "operator", "operator1")

    invalid_requests = [
        ("/api/messages", {"handling_status": "send"}),
        ("/api/messages", {"ingestion_status": "queued"}),
        ("/api/messages", {"sort": "raw_content"}),
        ("/api/messages", {"page": 0}),
        ("/api/messages", {"page_size": 101}),
        ("/api/inquiries", {"status": "closed"}),
        ("/api/inquiries", {"handling_status": "send"}),
        ("/api/inquiries", {"sort": "id"}),
        ("/api/inquiries", {"channel_account_id": 0}),
    ]

    for path, params in invalid_requests:
        response = business_client.get(path, params=params)
        assert response.status_code == 422, (path, params, response.text)



def test_admin_reads_company_inquiries_and_handles_messages_without_sending(business_client, monkeypatch):
    """Admins inspect inquiries and handle messages, but cannot send as customers."""
    import app.business_routes as business_routes

    monkeypatch.setattr(business_routes, "schedule_message_overview", lambda *args, **kwargs: None)
    with business_client.testing_session() as db:
        db.add(MessageOverview(
            message_id=1,
            status="ready",
            overview_text="Customer <customer@example.com> called +1 (650) 253-0000 about an order.",
        ))
        db.commit()
    login(business_client, "admin", "adminpass1")

    accounts = business_client.get("/api/channel-accounts")
    inquiries = business_client.get("/api/inquiries")
    assert accounts.status_code == 200
    assert {row["id"] for row in accounts.json()} == {1, 2, 3, 4, 5}
    assert inquiries.status_code == 200
    assert {row["id"] for row in inquiries.json()["items"]} == {1, 2, 3, 4}
    assert business_client.get("/api/inquiries/1").status_code == 200
    assert business_client.get("/api/inquiries/4").status_code == 200
    assert business_client.get("/api/inquiries/1").json()["messages"]

    admin_messages = business_client.get("/api/messages?handling_status=all")
    assert admin_messages.status_code == 200
    assert {row["id"] for row in admin_messages.json()["items"]} == {1, 3, 4, 5, 6}
    for row in admin_messages.json()["items"]:
        assert row["direction"] == "inbound"
        assert row["attachments"] == []
        for key in ("customer_contact", "normalized_customer_contact", "original_sender_contact", "provider", "external_message_id", "channel_account_id", "channel_account_external_id"):
            assert key not in row
    message_detail = business_client.get("/api/messages/1")
    assert message_detail.status_code == 403
    message_content = business_client.get("/api/messages/1/content")
    assert message_content.status_code == 403
    message_overview = business_client.get("/api/messages/1/overview")
    assert message_overview.status_code == 200
    assert "Fake fixture message" not in message_overview.text
    assert "customer@example.com" not in message_overview.text
    assert "fixture-gmail-1" not in message_overview.text
    admin_message_row = next(row for row in admin_messages.json()["items"] if row["id"] == 1)
    assert "display_text" not in admin_message_row
    assert "display_excerpt" not in admin_message_row
    assert "customer_contact" not in admin_message_row
    assert "external_message_id" not in admin_message_row
    assert admin_message_row["safe_content_status"] == "ready"
    assert admin_message_row["overview_status"] == "ready"
    assert admin_message_row["overview"]["text"] == "[redacted] [email redacted] called [phone redacted] about an order."
    assert "failure_code" not in admin_message_row["overview"]
    ungenerated_admin_row = next(row for row in admin_messages.json()["items"] if row["id"] == 3)
    assert ungenerated_admin_row["overview_status"] == "not_generated"
    assert ungenerated_admin_row["overview"] is None
    assert business_client.get("/api/messages/2").status_code == 403
    assert business_client.get("/api/messages/2/content").status_code == 403
    assert business_client.get("/api/messages/2/overview").status_code == 403
    assert business_client.get("/api/messages/1/provider-action").status_code == 403
    assert business_client.get("/api/messages/1/inquiry-candidates").status_code == 403
    assert business_client.get("/api/messages/999").status_code == 403
    admin_logs = business_client.get("/api/operation-logs", params={"inquiry_id": 1})
    assert admin_logs.status_code == 200
    assert isinstance(admin_logs.json(), list)
    admin_ai = business_client.post("/api/internal-ai/query", json={"query": "inquiries"})
    assert admin_ai.status_code == 200
    assert "customer@example.com" not in admin_ai.text
    assert "fixture-gmail-1" not in admin_ai.text
    assert "external_message_id" not in admin_ai.text
    assert "channel_account_external_id" not in admin_ai.text

    csrf = business_client.cookies.get("ea_csrf")
    headers = {"Origin": "https://testserver", "X-CSRF-Token": csrf}
    # Channel onboarding is open to admins on their OWN accounts, but the
    # personal account list must not turn into a company-wide message view.
    assert {row["id"] for row in business_client.get("/api/channels/accounts").json()} == {5}
    assert business_client.post(
        "/api/integrations/gmail/authorize/start", params={"account_id": 5}, headers=headers
    ).status_code != 403
    with business_client.testing_session() as db:
        overview = db.get(MessageOverview, 1)
        overview.status = "failed"
        overview.failure_code = "fixture-failure"
        db.commit()
    failed_admin_row = next(
        row for row in business_client.get("/api/messages?handling_status=all").json()["items"]
        if row["id"] == 1
    )
    assert failed_admin_row["overview_status"] == "failed"
    assert failed_admin_row["overview"]["status"] == "failed"
    assert failed_admin_row["overview"]["text"] is None
    assert "failure_code" not in failed_admin_row["overview"]
    assert business_client.post("/api/messages/1/action", json={"action": "processed"}, headers=headers).status_code == 409
    assert business_client.post("/api/messages/1/overview/retry", headers=headers).status_code == 200
    assert business_client.post("/api/inquiries/1/action", json={"action": "processed"}, headers=headers).status_code == 200
    with business_client.testing_session() as db:
        db.get(Inquiry, 1).last_activity_at = datetime.now(timezone.utc) - timedelta(days=45)
        db.commit()
    assert business_client.post("/api/inquiries/1/reactivate", headers=headers).status_code == 200
    assert business_client.post("/api/messages/2/overview/retry", headers=headers).status_code == 403
    with business_client.testing_session() as db:
        outbound = Message(
            channel_account_id=1,
            provider="gmail_api_pubsub",
            external_message_id="fixture-outbound-1",
            direction="outbound",
            status="processed",
            handling_status="pending",
            occurred_at=datetime.now(timezone.utc),
            raw_content="fixture outbound",
            link_state="linked",
        )
        db.add(outbound)
        db.flush()
        db.add(MessageOverview(message_id=outbound.id, status="failed", failure_code="fixture-failure"))
        db.commit()
        outbound_id = outbound.id
    assert business_client.post(f"/api/messages/{outbound_id}/overview/retry", headers=headers).status_code == 403
    assert business_client.post("/api/messages/1/send", json={"text": "not allowed"}, headers=headers).status_code in {404, 405}
    # Reassignment is the one inquiry write an admin keeps.
    assert business_client.post(
        "/api/inquiries/3/transfer",
        json={"sales_user_id": 4, "business_type": "inquiry"},
        headers=headers,
    ).status_code == 200


def test_operator_scope_excludes_outbound_messages_and_hides_mixed_chain_logs(business_client):
    from app.models.business import OperationLog

    login(business_client, "operator", "operator1")
    csrf = business_client.cookies.get("ea_csrf")
    headers = {"Origin": "https://testserver", "X-CSRF-Token": csrf}

    handled = business_client.post(
        "/api/inquiries/1/action", json={"action": "processed"}, headers=headers
    )
    assert handled.status_code == 200
    logs = business_client.get("/api/operation-logs", params={"inquiry_id": 1})
    assert logs.status_code == 200
    assert any(row["object_type"] == "inquiry" and row["object_id"] == 1 for row in logs.json())

    with business_client.testing_session() as db:
        outbound = Message(
            channel_account_id=1,
            provider="gmail_api_pubsub",
            external_message_id="operator-outbound-linked",
            direction="outbound",
            status="processed",
            handling_status="pending",
            occurred_at=datetime.now(timezone.utc),
            raw_content="fixture outbound",
            link_state="linked",
        )
        db.add(outbound)
        db.flush()
        db.add(InquiryMessage(inquiry_id=1, message_id=outbound.id, position=2, link_source="fixture"))
        db.add(MessageOverview(message_id=outbound.id, status="failed", failure_code="fixture-failure"))
        db.add(OperationLog(
            actor_user_id=1,
            actor_name="operator",
            operation_name="outbound-only-log",
            object_type="message",
            object_id=outbound.id,
            result="success",
        ))
        db.commit()
        outbound_id = outbound.id

    listed_messages = business_client.get("/api/messages?handling_status=all")
    assert listed_messages.status_code == 200
    assert outbound_id not in {row["id"] for row in listed_messages.json()["items"]}
    assert business_client.get(f"/api/messages/{outbound_id}").status_code == 403
    assert business_client.get(f"/api/messages/{outbound_id}/content").status_code == 403
    assert business_client.post(
        f"/api/messages/{outbound_id}/action",
        json={"action": "processed"},
        headers=headers,
    ).status_code == 403
    assert business_client.post(
        f"/api/messages/{outbound_id}/archive/restore", headers=headers
    ).status_code == 403
    assert business_client.post(
        f"/api/messages/{outbound_id}/overview/retry", headers=headers
    ).status_code == 403
    inquiry = business_client.get("/api/inquiries/1")
    assert inquiry.status_code == 200
    assert outbound_id not in {row["id"] for row in inquiry.json()["messages"]}
    logs = business_client.get("/api/operation-logs", params={"inquiry_id": 1})
    assert logs.status_code == 200
    assert all(not (row["object_type"] == "inquiry" and row["object_id"] == 1) for row in logs.json())
    assert all(row["operation_name"] != "outbound-only-log" for row in logs.json())


def test_admin_can_reassign_and_handle_company_inquiries(business_client):
    login(business_client, "admin", "adminpass1")
    csrf = business_client.cookies.get("ea_csrf")
    headers = {"Origin": "https://testserver", "X-CSRF-Token": csrf}

    targets = business_client.get("/api/inquiry-transfer-targets")
    reassigned = business_client.post(
        "/api/inquiries/3/transfer",
        json={"sales_user_id": 4, "business_type": "inquiry"},
        headers=headers,
    )
    handled = business_client.post(
        "/api/inquiries/1/action", json={"action": "processed"}, headers=headers
    )

    assert targets.status_code == 200
    assert {row["id"] for row in targets.json()} == {3, 4}
    assert reassigned.status_code == 200
    assert reassigned.json()["assigned_sales_user_id"] == 4
    assert [event["event_type"] for event in reassigned.json()["timeline"]].count("inquiry_transferred") == 2
    assert handled.status_code == 200

    db = business_client.testing_session()
    try:
        from app.models.business import InquiryEvent, OperationLog
        events = db.scalars(select(InquiryEvent).where(InquiryEvent.inquiry_id == 3)).all()
        logs = db.scalars(select(OperationLog).where(OperationLog.object_type == "inquiry", OperationLog.object_id == 3)).all()
        assert sum(event.event_type == "inquiry_transferred" for event in events) == 2
        assert any(log.operation_name == "分配客户链路" and log.actor_user_id == 6 for log in logs)
    finally:
        db.close()


def test_blocked_account_is_in_scope_but_revoked_account_is_not(business_client):
    login(business_client, "operator", "operator1")

    response = business_client.get("/api/messages", params={"channel_account_id": 2})

    assert response.status_code == 200
    assert response.json()["items"] == []
    assert business_client.get("/api/messages", params={"channel_account_id": 4}).json()["items"] == []
    # Blocked accounts remain in authorized account scope, but revoked accounts
    # and their associated Inquiry summaries stay hidden.
    assert business_client.get("/api/messages/2").status_code == 403
    assert business_client.get("/api/messages/2/content").status_code == 403


def test_pagination_boundaries_are_stable_and_empty_pages_do_not_leak(business_client):
    login(business_client, "operator", "operator1")

    first = business_client.get("/api/messages", params={"page": 1, "page_size": 1, "descending": "false"})
    second = business_client.get("/api/messages", params={"page": 2, "page_size": 1, "descending": "false"})
    beyond = business_client.get("/api/messages", params={"page": 3, "page_size": 1, "descending": "false"})

    assert first.status_code == second.status_code == beyond.status_code == 200
    assert len(first.json()["items"]) == 1
    assert len(second.json()["items"]) == 1
    assert len(beyond.json()["items"]) == 1
    assert first.json()["page"] == 1
    assert second.json()["page"] == 2
    assert beyond.json()["has_more"] is False



def test_provider_action_uses_scoped_message_and_only_supports_verified_gmail_id(business_client):
    login(business_client, "operator", "operator1")

    gmail = business_client.get("/api/messages/1/provider-action")
    cross_account = business_client.get("/api/messages/5/provider-action")
    revoked = business_client.get("/api/messages/2/provider-action")

    assert gmail.status_code == 200
    assert gmail.json()["supported"] is True
    assert gmail.json()["action"] == "open_message"
    assert gmail.json()["url"].startswith("https://mail.google.com/mail/u/0/#all/")
    assert "token" not in gmail.json()["url"]
    assert cross_account.status_code == 403
    assert revoked.status_code == 403


def test_sales_and_cross_account_cannot_get_provider_action(business_client):
    login(business_client, "sales", "salespass1")
    assert business_client.get("/api/messages/1/provider-action").status_code == 403

    business_client.post(
        "/auth/logout",
        headers={"Origin": "https://testserver", "X-CSRF-Token": business_client.cookies.get("ea_csrf")},
    )
    login(business_client, "other-operator", "otherop1")
    assert business_client.get("/api/messages/1/provider-action").status_code == 403



def test_human_actions_reject_changing_an_already_completed_terminal_state(business_client):
    login(business_client, "operator", "operator1")
    csrf = business_client.cookies.get("ea_csrf")
    headers = {"Origin": "https://testserver", "X-CSRF-Token": csrf}

    inquiry_done = business_client.post(
        "/api/inquiries/1/action", json={"action": "processed"}, headers=headers
    )
    message_done = business_client.post(
        "/api/messages/1/action", json={"action": "ignored"}, headers=headers
    )
    inquiry_reverse = business_client.post(
        "/api/inquiries/1/action", json={"action": "ignored"}, headers=headers
    )
    message_reverse = business_client.post(
        "/api/messages/1/action", json={"action": "processed"}, headers=headers
    )

    assert inquiry_done.status_code == 200
    assert message_done.status_code == 409
    assert inquiry_reverse.status_code == 409
    assert message_reverse.status_code == 200
    assert business_client.get("/api/inquiries/1").json()["handling_status"] == "processed"
    assert business_client.get("/api/messages/1").json()["handling_status"] == "processed"


def test_repeated_same_terminal_action_is_idempotent_without_extra_inquiry_event(business_client):
    login(business_client, "operator", "operator1")
    csrf = business_client.cookies.get("ea_csrf")
    headers = {"Origin": "https://testserver", "X-CSRF-Token": csrf}

    first = business_client.post(
        "/api/inquiries/1/action", json={"action": "processed"}, headers=headers
    )
    second = business_client.post(
        "/api/inquiries/1/action", json={"action": "processed"}, headers=headers
    )

    assert first.status_code == second.status_code == 200
    assert [event["event_type"] for event in second.json()["timeline"]] == [
        "inquiry_created", "inquiry_processed"
    ]



def test_unassigned_department_has_no_department_identity_or_scope(business_client):
    with business_client.testing_session() as db:
        user = User(username="legacy-unassigned", password_hash=hash_password("legacy1"), role="engineering", department="unassigned", is_active=True, must_change_password=False)
        db.add(user)
        db.flush()
        db.add(UserDepartmentGrant(user_id=user.id, department="unassigned", granted_by_user_id=6))
        inquiry = Inquiry(customer_contact="legacy@example.invalid", normalized_customer_contact="legacy@example.invalid", contact_identity_state="certain", contact_identity_kind="email", customer_nickname="Legacy", raw_message="legacy", department="unassigned", source_channel_account_id=1, status="new", handling_status="pending")
        db.add(inquiry)
        db.commit()
        assert has_department_identity(user) is False
        assert db.scalars(department_read_scope(user)).all() == []
        assert db.scalars(scoped_inquiries(user)).all() == []
        assert db.scalars(scoped_messages(user)).all() == []


def test_cross_function_authorization_contract_matches_for_sales_and_operator(business_client):
    login(business_client, "operator", "operator1")

    operator_analysis = business_client.post("/api/internal-analysis", json={"operation": "read"})
    operator_ai = business_client.post("/api/internal-ai/query", json={"query": "inquiries"})
    operator_notifications = business_client.post("/api/internal-ai/query", json={"query": "notifications"})

    assert operator_analysis.status_code == operator_ai.status_code == operator_notifications.status_code == 200
    assert operator_analysis.json()["inquiries_by_status"] == {"new": 1, "assigned": 0}
    assert [item["id"] for item in operator_ai.json()["data"]] == [1]
    assert operator_notifications.json()["data"] == []
    assert business_client.get("/api/inquiries/2").status_code == 404
    assert business_client.post(
        "/api/inquiries/2/action",
        json={"action": "processed"},
        headers={"Origin": "https://testserver", "X-CSRF-Token": business_client.cookies.get("ea_csrf")},
    ).status_code == 403

    csrf = business_client.cookies.get("ea_csrf")
    business_client.post("/auth/logout", headers={"Origin": "https://testserver", "X-CSRF-Token": csrf})
    login(business_client, "sales", "salespass1")

    sales_analysis = business_client.post("/api/internal-analysis", json={"operation": "read"})
    sales_ai = business_client.post("/api/internal-ai/query", json={"query": "inquiries"})
    sales_notifications = business_client.post("/api/internal-ai/query", json={"query": "notifications"})

    assert sales_analysis.status_code == sales_ai.status_code == sales_notifications.status_code == 200
    assert sales_analysis.json()["inquiries_by_status"] == {"new": 0, "assigned": 1}
    assert [item["id"] for item in sales_ai.json()["data"]] == [3]
    assert sales_notifications.json()["data"] == []
    assert business_client.get("/api/inquiries/1").status_code == 404
    assert business_client.post(
        "/api/inquiries/1/action",
        json={"action": "processed"},
        headers={"Origin": "https://testserver", "X-CSRF-Token": business_client.cookies.get("ea_csrf")},
    ).status_code == 403


def test_revoked_assigned_inquiry_is_absent_from_all_sales_reads_and_actions(business_client):
    login(business_client, "sales", "salespass1")

    assert [item["id"] for item in business_client.get("/api/inquiries").json()["items"]] == [3]
    for path, payload in [
        ("/api/inquiries/4/action", {"action": "processed"}),
        ("/api/inquiries/4/transfer", {"sales_user_id": 3}),
    ]:
        csrf = business_client.cookies.get("ea_csrf")
        response = business_client.post(
            path,
            json=payload,
            headers={"Origin": "https://testserver", "X-CSRF-Token": csrf},
        )
        assert response.status_code == 403
    assert business_client.get("/api/inquiries/4").status_code == 404


def test_website_form_channel_excludes_mislabeled_and_forwarded_messages(business_client):
    from app.message_ingestion import WEBSITE_FORM_EMAIL

    login(business_client, "operator", "operator1")
    session_gen = app.dependency_overrides[get_db]()
    db = next(session_gen)
    try:
        now = datetime(2026, 11, 5, 8, 0, 0, tzinfo=timezone.utc)
        db.add_all(
            [
                Message(
                    channel_account_id=1,
                    provider="gmail_api_pubsub",
                    external_message_id="wf-valid",
                    direction="inbound",
                    status="received",
                    handling_status="pending",
                    occurred_at=now,
                    raw_content="form submission",
                    customer_contact=WEBSITE_FORM_EMAIL,
                    is_website_form=True,
                    contact_identity_state="unsupported",
                    link_state="linked",
                ),
                Message(
                    channel_account_id=1,
                    provider="gmail_api_pubsub",
                    external_message_id="wf-stale-165",
                    direction="inbound",
                    status="received",
                    handling_status="pending",
                    occurred_at=now,
                    raw_content="Medium Daily Digest",
                    customer_contact="noreply@medium.com",
                    is_website_form=True,
                    contact_identity_state="unsupported",
                    link_state="linked",
                ),
                Message(
                    channel_account_id=1,
                    provider="gmail_api_pubsub",
                    external_message_id="wf-forwarded",
                    direction="inbound",
                    status="received",
                    handling_status="pending",
                    occurred_at=now,
                    raw_content="Forwarded Medium Daily Digest",
                    customer_contact=WEBSITE_FORM_EMAIL,
                    original_sender_contact="noreply@medium.com",
                    is_website_form=True,
                    contact_identity_state="unsupported",
                    link_state="linked",
                ),
            ]
        )
        db.commit()
    finally:
        session_gen.close()

    form = business_client.get("/api/messages?channel_type=website_form&handling_status=all")
    assert form.status_code == 200
    # 白名单邮箱转发的真表单（wf-forwarded）也计入渠道；只有发件人非白名单的
    # 历史误标（wf-stale-165）被排除。
    assert sorted(item["external_message_id"] for item in form.json()["items"]) == [
        "wf-forwarded",
        "wf-valid",
    ]

    all_messages = business_client.get("/api/messages?handling_status=all")
    assert all_messages.status_code == 200
    by_id = {item["external_message_id"]: item for item in all_messages.json()["items"]}
    assert by_id["wf-stale-165"]["is_website_form"] is False
    assert by_id["wf-stale-165"]["channel_type"] == "gmail"
    assert by_id["wf-stale-165"]["customer_contact"] == "noreply@medium.com"
    assert by_id["wf-forwarded"]["is_website_form"] is True


def test_null_department_resources_are_denied_for_sales_and_operations(business_client):
    """Customer resources without a department mapping are deny-by-default."""
    with business_client.testing_session() as db:
        sales = db.get(User, 3)
        operator = db.get(User, 1)
        sales.department = "  "
        operator.department = "  "
        db.get(Inquiry, 3).department = "  "
        db.flush()
        assert db.scalars(scoped_inquiries(sales)).all() == []
        assert db.scalars(scoped_messages(sales)).all() == []
        assert db.scalars(scoped_inquiries(operator)).all() == []
        linked_operator_messages = db.scalars(scoped_messages(operator)).all()
        assert [message.id for message in linked_operator_messages] == [3, 4]


def test_departmentless_engineering_roles_remain_data_dark(business_client):
    with business_client.testing_session() as db:
        readers = [
            User(username=f"blank-{role}", password_hash="unused", role=role, department="  ", is_active=True)
            for role in ("engineering", "production", "procurement")
        ]
        db.add_all(readers)
        db.flush()
        for reader in readers:
            assert not has_department_identity(reader)
            assert db.scalars(scoped_inquiries(reader)).all() == []
            assert db.scalars(scoped_messages(reader)).all() == []
