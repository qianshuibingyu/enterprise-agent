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
from app.models.business import (
    ChannelAccount,
    ChannelGrant,
    Inquiry,
    InquiryMessage,
    Message,
    OperationLog,
    WhatsAppGroupBinding,
)
from app.models.user import User
from app.models.permissions import UserChannelPreauthorization

GROUP_JID = "120363000000000000@g.us"
GROUP_JID_OTHER = "120363000000000001@g.us"
GROUP_JID_UNKNOWN = "999999999999999999@g.us"
GROUP_JID_HISTORICAL = "120363000000000009@g.us"

PHONE_A = "+8613800138000"
PHONE_B = "+8613912345678"
PHONE_C = "+8613812345678"
PHONE_D = "+8613999999999"
PHONE_E = "+14155552671"

T1 = datetime(2026, 11, 1, 9, 0, tzinfo=timezone.utc)
T2 = datetime(2026, 11, 2, 9, 0, tzinfo=timezone.utc)
T3 = datetime(2026, 11, 3, 9, 0, tzinfo=timezone.utc)
T4 = datetime(2026, 11, 4, 9, 0, tzinfo=timezone.utc)
T5 = datetime(2026, 11, 5, 9, 0, tzinfo=timezone.utc)

PROVIDER = "whatsapp_web_baileys"
DENIED = "没有权限访问"


def _message(message_id, account_id, external_id, occurred_at, *, normalized, customer_contact, nickname, identity_state, link_state):
    return Message(
        id=message_id,
        channel_account_id=account_id,
        provider=PROVIDER,
        external_message_id=external_id,
        direction="inbound",
        status="received",
        handling_status="pending",
        occurred_at=occurred_at,
        raw_content=f"body-{external_id}",
        customer_contact=customer_contact,
        normalized_customer_contact=normalized,
        contact_identity_state=identity_state,
        contact_identity_kind="whatsapp",
        customer_nickname=nickname,
        link_state=link_state,
    )


@pytest.fixture
def env():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        db.add_all([
            User(id=1, username="op-a", password_hash=hash_password("operator1"), role="staff", department="inquiry", is_active=True, must_change_password=False),
            User(id=2, username="op-b", password_hash=hash_password("operator2"), role="staff", department="inquiry", is_active=True, must_change_password=False),
            User(id=3, username="sale", password_hash=hash_password("salespass1"), role="sales", department="inquiry", is_active=True, must_change_password=False),
        ])
        db.flush()
        db.add_all([
            ChannelAccount(id=1, owner_user_id=1, channel_type="whatsapp", status="connected", external_account_id="wa-a"),
            ChannelAccount(id=2, owner_user_id=2, channel_type="whatsapp", status="connected", external_account_id="wa-b"),
            ChannelAccount(id=3, owner_user_id=1, channel_type="whatsapp", status="revoked", external_account_id="wa-revoked"),
        ])
        db.flush()
        db.add_all([
            ChannelGrant(channel_account_id=1, channel_type="whatsapp", owner_user_id=1),
            ChannelGrant(channel_account_id=2, channel_type="whatsapp", owner_user_id=2),
            ChannelGrant(channel_account_id=3, channel_type="whatsapp", owner_user_id=1),
        ])
        db.add_all([
            UserChannelPreauthorization(user_id=1, channel_type="whatsapp", granted_by_user_id=1),
            UserChannelPreauthorization(user_id=2, channel_type="whatsapp", granted_by_user_id=1),
        ])
        # Group rows carry normalized contacts = NULL (matching the bridge contract).
        # The other rows are already-obtained customer phone numbers.
        db.add_all([
            _message(1, 1, f"{GROUP_JID}:participant:gm1", T1, normalized=None, customer_contact=None, nickname=None, identity_state="unsupported", link_state="pending"),
            _message(2, 1, "p-a-1", T2, normalized=PHONE_A, customer_contact="8613800138000@s.whatsapp.net", nickname="客户A", identity_state="certain", link_state="linked"),
            _message(3, 1, "p-a-2", T3, normalized=PHONE_A, customer_contact="8613800138000@s.whatsapp.net", nickname="客户A", identity_state="certain", link_state="pending"),
            _message(4, 1, "p-c-1", T5, normalized=PHONE_C, customer_contact="8613812345678@s.whatsapp.net", nickname="客户C", identity_state="certain", link_state="pending"),
            _message(5, 2, "p-d-1", T2, normalized=PHONE_D, customer_contact="8613999999999@s.whatsapp.net", nickname="客户D", identity_state="certain", link_state="pending"),
            _message(6, 3, "p-e-1", T2, normalized=PHONE_E, customer_contact="14155552671@s.whatsapp.net", nickname="客户E", identity_state="certain", link_state="pending"),
            _message(7, 2, f"{GROUP_JID_OTHER}:participant:o1", T4, normalized=None, customer_contact=None, nickname=None, identity_state="unsupported", link_state="pending"),
        ])
        # Pre-existing inquiry chain so all three canonical tables are non-empty
        # and the "no auto-linking" snapshot comparison is meaningful.
        db.add(Inquiry(
            id=1,
            customer_contact="8613800138000@s.whatsapp.net",
            normalized_customer_contact=PHONE_A,
            contact_identity_state="certain",
            contact_identity_kind="whatsapp",
            customer_nickname="客户A",
            raw_message="seed",
            source_channel_account_id=1,
            status="new",
            handling_status="pending",
        ))
        db.flush()
        db.add(InquiryMessage(inquiry_id=1, message_id=2, position=1, link_source="fixture"))
        db.commit()

    def override_db():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    with TestClient(app, base_url="https://testserver", raise_server_exceptions=False) as http:
        yield http, factory
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)
    engine.dispose()


def login(http, username, password):
    csrf = http.get("/auth/csrf", headers={"Origin": "https://testserver"}).json()["csrf_token"]
    response = http.post(
        "/auth/login",
        json={"username": username, "password": password},
        headers={"Origin": "https://testserver", "X-CSRF-Token": csrf},
    )
    assert response.status_code == 200, response.text


def csrf_headers(http):
    csrf = http.get("/auth/csrf", headers={"Origin": "https://testserver"}).json()["csrf_token"]
    return {"Origin": "https://testserver", "X-CSRF-Token": csrf}


def snapshot(db):
    """Full row-count + key-column snapshot of the three canonical tables.

    Any automatic inquiry linking would INSERT into inquiries/inquiry_messages
    or UPDATE messages (contact/link columns); both changes show up here.
    """
    return {
        "messages": [
            (
                m.id, m.customer_contact, m.normalized_customer_contact,
                m.contact_identity_state, m.contact_identity_kind, m.link_state,
                m.external_message_id, m.raw_content, m.channel_account_id,
            )
            for m in db.scalars(select(Message).order_by(Message.id)).all()
        ],
        "inquiries": [
            (
                i.id, i.customer_contact, i.normalized_customer_contact,
                i.contact_identity_state, i.status, i.handling_status, i.business_type,
            )
            for i in db.scalars(select(Inquiry).order_by(Inquiry.id)).all()
        ],
        "inquiry_messages": [
            (l.inquiry_id, l.message_id, l.position, l.link_source)
            for l in db.scalars(
                select(InquiryMessage).order_by(InquiryMessage.inquiry_id, InquiryMessage.message_id)
            ).all()
        ],
    }


def binding_count(db):
    return len(db.scalars(select(WhatsAppGroupBinding)).all())


def test_staff_binds_group_and_never_touches_inquiry_tables(env):
    http, factory = env
    login(http, "op-a", "operator1")
    with factory() as db:
        before = snapshot(db)
        assert len(before["messages"]) == 7
        assert len(before["inquiries"]) == 1
        assert len(before["inquiry_messages"]) == 1
        assert binding_count(db) == 0

    response = http.post(
        "/api/whatsapp-group-bindings",
        json={"group_jid": GROUP_JID, "phone": PHONE_A, "note": "人工确认"},
        headers=csrf_headers(http),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["group_jid"] == GROUP_JID
    assert body["normalized_phone"] == PHONE_A
    assert body["raw_phone"] == PHONE_A
    assert body["channel_account_id"] == 1
    assert body["bound_by"] == "op-a"
    assert body["note"] == "人工确认"
    assert isinstance(body["created_at"], str)
    assert isinstance(body["updated_at"], str)

    with factory() as db:
        rows = db.scalars(select(WhatsAppGroupBinding)).all()
        assert len(rows) == 1
        assert rows[0].group_jid == GROUP_JID
        assert rows[0].normalized_phone == PHONE_A
        assert rows[0].channel_account_id == 1
        assert rows[0].bound_by_user_id == 1
        # Core regression: no automatic inquiry linking happened.
        assert snapshot(db) == before
        log = db.scalar(select(OperationLog).where(OperationLog.operation_name == "绑定群聊客户"))
        assert log is not None
        assert log.object_type == "whatsapp_group_binding"
        assert log.object_id == rows[0].id
        assert GROUP_JID in log.detail and PHONE_A in log.detail


def test_rebind_updates_single_row_without_recreating(env):
    http, factory = env
    login(http, "op-a", "operator1")
    with factory() as db:
        before = snapshot(db)

    first = http.post(
        "/api/whatsapp-group-bindings",
        json={"group_jid": GROUP_JID, "phone": PHONE_A},
        headers=csrf_headers(http),
    )
    assert first.status_code == 200, first.text
    second = http.post(
        "/api/whatsapp-group-bindings",
        json={"group_jid": GROUP_JID, "phone": PHONE_B},
        headers=csrf_headers(http),
    )
    assert second.status_code == 200, second.text
    assert second.json()["normalized_phone"] == PHONE_B
    assert second.json()["id"] == first.json()["id"]

    with factory() as db:
        rows = db.scalars(select(WhatsAppGroupBinding)).all()
        assert len(rows) == 1
        assert rows[0].normalized_phone == PHONE_B
        assert rows[0].raw_phone == PHONE_B
        assert snapshot(db) == before
        log = db.scalar(select(OperationLog).where(OperationLog.operation_name == "改绑群聊客户"))
        assert log is not None
        assert log.object_type == "whatsapp_group_binding"
        assert log.object_id == rows[0].id


def test_rebind_cannot_overwrite_another_operators_binding(env):
    """A group JID is globally unique: rebinding must not let one operator
    silently take over a binding owned by another operator's channel account."""
    http, factory = env
    with factory() as db:
        db.add(
            WhatsAppGroupBinding(
                group_jid=GROUP_JID,
                channel_account_id=2,
                normalized_phone=PHONE_D,
                raw_phone=PHONE_D,
                bound_by_user_id=2,
            )
        )
        db.commit()
        before = snapshot(db)

    login(http, "op-a", "operator1")
    response = http.post(
        "/api/whatsapp-group-bindings",
        json={"group_jid": GROUP_JID, "phone": PHONE_A},
        headers=csrf_headers(http),
    )
    assert response.status_code == 403
    with factory() as db:
        rows = db.scalars(select(WhatsAppGroupBinding)).all()
        assert len(rows) == 1
        assert rows[0].normalized_phone == PHONE_D
        assert rows[0].channel_account_id == 2
        assert snapshot(db) == before


@pytest.mark.parametrize("phone", ["13800138000", "+8613800abc", ""])
def test_invalid_phone_is_rejected_without_writes(env, phone):
    http, factory = env
    login(http, "op-a", "operator1")
    with factory() as db:
        before = snapshot(db)
    response = http.post(
        "/api/whatsapp-group-bindings",
        json={"group_jid": GROUP_JID, "phone": phone},
        headers=csrf_headers(http),
    )
    assert response.status_code == 400
    assert "地区码" in response.json()["detail"]
    with factory() as db:
        assert binding_count(db) == 0
        assert snapshot(db) == before


def test_non_group_jid_is_rejected(env):
    http, factory = env
    login(http, "op-a", "operator1")
    with factory() as db:
        before = snapshot(db)
    response = http.post(
        "/api/whatsapp-group-bindings",
        json={"group_jid": "120363000000000000@s.whatsapp.net", "phone": PHONE_A},
        headers=csrf_headers(http),
    )
    assert response.status_code == 400
    with factory() as db:
        assert binding_count(db) == 0
        assert snapshot(db) == before


def test_unknown_group_returns_404(env):
    http, factory = env
    login(http, "op-a", "operator1")
    response = http.post(
        "/api/whatsapp-group-bindings",
        json={"group_jid": GROUP_JID_UNKNOWN, "phone": PHONE_A},
        headers=csrf_headers(http),
    )
    assert response.status_code == 404
    assert "授权范围" in response.json()["detail"]
    with factory() as db:
        assert binding_count(db) == 0


def test_sales_role_is_forbidden_on_all_endpoints(env):
    http, _ = env
    login(http, "op-a", "operator1")
    created = http.post(
        "/api/whatsapp-group-bindings",
        json={"group_jid": GROUP_JID, "phone": PHONE_A},
        headers=csrf_headers(http),
    )
    assert created.status_code == 200
    binding_id = created.json()["id"]

    login(http, "sale", "salespass1")
    assert http.get("/api/whatsapp-group-bindings").status_code == 403
    assert http.get("/api/whatsapp-phone-candidates").status_code == 403
    assert http.post(
        "/api/whatsapp-group-bindings",
        json={"group_jid": GROUP_JID, "phone": PHONE_B},
        headers=csrf_headers(http),
    ).status_code == 403
    assert http.delete(
        f"/api/whatsapp-group-bindings/{binding_id}",
        headers=csrf_headers(http),
    ).status_code == 403


def test_group_outside_authorized_accounts_returns_404(env):
    http, factory = env
    login(http, "op-a", "operator1")
    response = http.post(
        "/api/whatsapp-group-bindings",
        json={"group_jid": GROUP_JID_OTHER, "phone": PHONE_A},
        headers=csrf_headers(http),
    )
    assert response.status_code == 404
    with factory() as db:
        assert binding_count(db) == 0


def test_phone_candidates_are_scoped_and_deduplicated(env):
    http, factory = env
    login(http, "op-a", "operator1")
    with factory() as db:
        before = snapshot(db)
    response = http.get("/api/whatsapp-phone-candidates")
    assert response.status_code == 200, response.text
    items = response.json()
    # Only account 1 (connected, whatsapp, in scope), deduplicated by phone.
    assert [item["normalized_phone"] for item in items] == [PHONE_C, PHONE_A]
    assert all(item["channel_account_id"] == 1 for item in items)
    by_phone = {item["normalized_phone"]: item for item in items}
    assert by_phone[PHONE_A]["message_count"] == 2
    assert by_phone[PHONE_C]["message_count"] == 1
    assert by_phone[PHONE_A]["customer_nickname"] == "客户A"
    assert isinstance(by_phone[PHONE_A]["last_seen_at"], str)
    assert PHONE_D not in by_phone  # another operator's account
    assert PHONE_E not in by_phone  # revoked account
    with factory() as db:
        assert snapshot(db) == before  # read-only


def test_delete_removes_binding_and_records_operation_log(env):
    http, factory = env
    login(http, "op-a", "operator1")
    with factory() as db:
        before = snapshot(db)
    created = http.post(
        "/api/whatsapp-group-bindings",
        json={"group_jid": GROUP_JID, "phone": PHONE_A},
        headers=csrf_headers(http),
    )
    assert created.status_code == 200
    binding_id = created.json()["id"]

    response = http.delete(
        f"/api/whatsapp-group-bindings/{binding_id}",
        headers=csrf_headers(http),
    )
    assert response.status_code == 200, response.text
    assert response.json() == {"ok": True}
    listed = http.get("/api/whatsapp-group-bindings")
    assert listed.status_code == 200
    assert all(item["group_jid"] != GROUP_JID for item in listed.json())
    with factory() as db:
        assert binding_count(db) == 0
        assert snapshot(db) == before
        log = db.scalar(select(OperationLog).where(OperationLog.operation_name == "解绑群聊客户"))
        assert log is not None
        assert log.object_type == "whatsapp_group_binding"
        assert log.object_id == binding_id


def test_null_channel_account_binding_is_hidden_and_not_mutable(env):
    http, factory = env
    login(http, "op-a", "operator1")
    with factory() as db:
        row = WhatsAppGroupBinding(
            group_jid=GROUP_JID_HISTORICAL,
            normalized_phone=PHONE_A,
            channel_account_id=None,
            bound_by_user_id=None,
        )
        db.add(row)
        db.commit()
        row_id = row.id

    listed = http.get("/api/whatsapp-group-bindings")
    assert listed.status_code == 200
    assert all(item["id"] != row_id for item in listed.json())

    response = http.delete(
        f"/api/whatsapp-group-bindings/{row_id}",
        headers=csrf_headers(http),
    )
    assert response.status_code == 403
    with factory() as db:
        assert binding_count(db) == 1
        assert db.get(WhatsAppGroupBinding, row_id) is not None
