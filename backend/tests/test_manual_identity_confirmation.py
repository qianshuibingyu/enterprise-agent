"""Original-content availability and operator-driven identity confirmation.

Covers the two gaps that used to leave GM/WS originals in an error state and
the link-review panel without any actionable business logic.
"""

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import hash_password
from app.content_security import full_content_view
from app.database import get_db
from app.main import app
from app.models.base import Base
from app.models.business import ChannelAccount, ChannelGrant, Inquiry, InquiryEvent, InquiryMessage, Message
from app.models.user import User


@pytest.fixture
def client():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        user = User(
            username="reviewer",
            password_hash=hash_password("reviewer1"),
            role="staff",
            is_active=True,
            must_change_password=False,
        )
        db.add(user)
        db.flush()
        account = ChannelAccount(owner_user_id=user.id, channel_type="whatsapp", status="connected")
        db.add(account)
        db.flush()
        db.add(ChannelGrant(channel_account_id=account.id, channel_type="whatsapp", owner_user_id=user.id))
        # An inquiry becomes visible to staff only once it has a linked message.
        seed = Message(
            channel_account_id=account.id,
            provider="whatsapp_web_baileys",
            external_message_id="wa-seed-1",
            direction="inbound",
            status="received",
            handling_status="pending",
            occurred_at=datetime.now(timezone.utc),
            raw_content="first contact",
            customer_contact="+16502530000",
            normalized_customer_contact="+16502530000",
            contact_identity_state="certain",
            contact_identity_kind="whatsapp",
            link_state="linked",
        )
        db.add(seed)
        db.flush()
        db.add(Message(
            channel_account_id=account.id,
            provider="whatsapp_web_baileys",
            external_message_id="wa-review-1",
            direction="inbound",
            status="received",
            handling_status="pending",
            occurred_at=datetime.now(timezone.utc),
            raw_content="needs manual identity review",
            customer_contact=None,
            normalized_customer_contact=None,
            contact_identity_state="needs_manual_review",
            contact_identity_kind=None,
            link_state="manual_review",
        ))
        db.add(Inquiry(
            customer_contact="+16502530000",
            normalized_customer_contact="+16502530000",
            contact_identity_state="certain",
            contact_identity_kind="whatsapp",
            customer_nickname="wa customer",
            raw_message="hello",
            source_channel_account_id=account.id,
            status="new",
            handling_status="pending",
            message_links=[InquiryMessage(message_id=seed.id, position=1, link_source="fixture")],
        ))
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


def login(http):
    csrf = http.get("/auth/csrf", headers={"Origin": "https://testserver"}).json()["csrf_token"]
    response = http.post(
        "/auth/login",
        json={"username": "reviewer", "password": "reviewer1"},
        headers={"Origin": "https://testserver", "X-CSRF-Token": csrf},
    )
    assert response.status_code == 200


def csrf_headers(http):
    csrf = http.get("/auth/csrf", headers={"Origin": "https://testserver"}).json()["csrf_token"]
    return {"Origin": "https://testserver", "X-CSRF-Token": csrf}


def test_full_content_view_keeps_long_original():
    text = "line\n" * 5000
    result = full_content_view(text)
    assert result["display_text"].count("line") == 5000
    assert result["content_truncated"] is False
    assert result["content_format"] == "text/plain"


def test_original_content_is_always_available_as_authoritative_snapshot(client):
    """A failed WhatsApp live refetch must not put the original in an error state."""
    http, factory = client
    login(http)
    with factory() as db:
        message_id = db.scalar(select(Message.id).where(Message.external_message_id == "wa-review-1"))

    response = http.get(f"/api/messages/{message_id}/content")
    assert response.status_code == 200
    body = response.json()
    assert body["full_text"] == "needs manual identity review"
    assert body["source"]["authoritative"] is True
    assert body["source"]["refetch_status"] == "snapshot"
    assert body["source"]["live_refetch"] is False
    assert body["raw_content_exposed"] is False


def test_manual_confirmation_surfaces_candidates_and_completes_link(client):
    http, factory = client
    login(http)
    with factory() as db:
        message_id = db.scalar(select(Message.id).where(Message.external_message_id == "wa-review-1"))
        inquiry_id = db.scalar(select(Inquiry.id).where(Inquiry.normalized_customer_contact == "+16502530000"))

    candidates = http.get(f"/api/messages/{message_id}/inquiry-candidates")
    assert candidates.status_code == 200
    payload = candidates.json()
    assert payload["match_state"] == "manual_confirmation_required"
    assert payload["requires_identity_confirmation"] is True
    assert inquiry_id in {item["id"] for item in payload["items"]}
    assert any(item["customer_contact"] == "+16502530000" for item in payload["items"])

    # Without explicit operator confirmation the strict identity boundary holds.
    rejected = http.post(
        f"/api/inquiries/{inquiry_id}/messages",
        json={"message_id": message_id},
        headers=csrf_headers(http),
    )
    assert rejected.status_code == 409

    linked = http.post(
        f"/api/inquiries/{inquiry_id}/messages",
        json={"message_id": message_id, "confirm_identity": True},
        headers=csrf_headers(http),
    )
    assert linked.status_code == 200
    with factory() as db:
        message = db.get(Message, message_id)
        assert message.contact_identity_state == "certain"
        assert message.contact_identity_kind == "whatsapp"
        assert message.normalized_customer_contact == "+16502530000"
        assert message.link_state == "linked"
        event = db.scalar(
            select(InquiryEvent).where(
                InquiryEvent.inquiry_id == inquiry_id,
                InquiryEvent.event_type == "manual_link",
            )
        )
        assert event is not None
        assert event.actor_user_id is not None
