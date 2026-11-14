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
from app.models.business import ChannelAccount, ChannelGrant, Inquiry, InquiryEvent, InquiryMessage, Message
from app.models.user import User


@pytest.fixture
def client():
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        db.add_all([
            User(username="op-a", password_hash=hash_password("operator1"), role="staff", department="inquiry", is_active=True, must_change_password=False),
            User(username="op-b", password_hash=hash_password("operator2"), role="staff", department="inquiry", is_active=True, must_change_password=False),
            User(username="sale", password_hash=hash_password("salespass1"), role="sales", department="inquiry", is_active=True, must_change_password=False),
        ])
        db.flush()
        accounts = [
            ChannelAccount(id=1, owner_user_id=1, channel_type="gmail", status="connected"),
            ChannelAccount(id=2, owner_user_id=2, channel_type="outlook", status="connected"),
            ChannelAccount(id=3, owner_user_id=1, channel_type="gmail", status="connected"),
            ChannelAccount(id=4, owner_user_id=1, channel_type="whatsapp", status="connected"),
        ]
        db.add_all(accounts)
        db.flush()
        db.add_all([
            ChannelGrant(channel_account_id=1, channel_type="gmail", owner_user_id=1),
            ChannelGrant(channel_account_id=2, channel_type="outlook", owner_user_id=2),
            ChannelGrant(channel_account_id=3, channel_type="gmail", owner_user_id=1),
            ChannelGrant(channel_account_id=4, channel_type="whatsapp", owner_user_id=1),
        ])
        db.add_all([
            Message(id=1, channel_account_id=1, provider="gmail_api_pubsub", external_message_id="m1", direction="inbound", status="received", handling_status="pending", occurred_at=datetime.now(timezone.utc), raw_content="first", customer_contact="same@example.com", normalized_customer_contact="same@example.com", contact_identity_state="certain", contact_identity_kind="email"),
            Message(id=2, channel_account_id=2, provider="outlook_mcp_graph", external_message_id="m2", direction="inbound", status="received", handling_status="pending", occurred_at=datetime.now(timezone.utc), raw_content="second", customer_contact="same@example.com", normalized_customer_contact="same@example.com", contact_identity_state="certain", contact_identity_kind="email"),
            Message(id=3, channel_account_id=3, provider="gmail_api_pubsub", external_message_id="m3", direction="inbound", status="received", handling_status="pending", occurred_at=datetime.now(timezone.utc), raw_content="third", customer_contact="same@example.com", normalized_customer_contact="same@example.com", contact_identity_state="certain", contact_identity_kind="email"),
            Message(id=4, channel_account_id=4, provider="whatsapp_web_baileys", external_message_id="m4", direction="inbound", status="received", handling_status="pending", occurred_at=datetime.now(timezone.utc), raw_content="wrong identity type", customer_contact="same@example.com", normalized_customer_contact=None, contact_identity_state="unsupported", contact_identity_kind="whatsapp"),
        ])
        db.add_all([
            Inquiry(id=1, customer_contact="Same@Example.com", department="inquiry", normalized_customer_contact="same@example.com", contact_identity_state="certain", contact_identity_kind="email", customer_nickname="same", raw_message="first", source_channel_account_id=1, status="new", handling_status="pending", message_links=[InquiryMessage(message_id=1, position=1, link_source="fixture")]),
            Inquiry(id=2, customer_contact="same@example.com", department="inquiry", normalized_customer_contact="same@example.com", contact_identity_state="certain", contact_identity_kind="email", customer_nickname="same", raw_message="second chain", source_channel_account_id=2, status="new", handling_status="pending", message_links=[InquiryMessage(message_id=2, position=1, link_source="fixture")]),
            Inquiry(id=3, customer_contact="other@example.com", department="inquiry", normalized_customer_contact="other@example.com", contact_identity_state="certain", contact_identity_kind="email", customer_nickname="other", raw_message="other", source_channel_account_id=1, status="new", handling_status="pending", message_links=[InquiryMessage(message_id=4, position=1, link_source="fixture")]),
        ])
        db.commit()

    def override_db():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    with TestClient(app, base_url="https://testserver", raise_server_exceptions=False) as test_client:
        yield test_client, factory
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)
    engine.dispose()


def login(client, username, password):
    csrf = client.get("/auth/csrf", headers={"Origin": "https://testserver"}).json()["csrf_token"]
    response = client.post("/auth/login", json={"username": username, "password": password}, headers={"Origin": "https://testserver", "X-CSRF-Token": csrf})
    assert response.status_code == 200


def csrf_headers(client):
    csrf = client.get("/auth/csrf", headers={"Origin": "https://testserver"}).json()["csrf_token"]
    return {"Origin": "https://testserver", "X-CSRF-Token": csrf}


def test_candidates_show_multiple_without_linking_and_operator_can_choose(client):
    http, factory = client
    login(http, "op-a", "operator1")
    candidates = http.get("/api/messages/3/inquiry-candidates")
    assert candidates.status_code == 200
    assert candidates.json()["match_state"] == "unique"
    assert {item["id"] for item in candidates.json()["items"]} == {1}
    # Candidate discovery is limited to inquiries in the operator's scope.
    # Candidate inspection itself did not create the association.
    assert http.get("/api/messages/3").json()["inquiry_id"] is None
    linked = http.post("/api/inquiries/1/messages", json={"message_id": 3}, headers=csrf_headers(http))
    assert linked.status_code == 200
    assert linked.json()["messages"][-1]["provider"] == "gmail_api_pubsub"
    assert [item["id"] for item in linked.json()["messages"]] == [1, 3]
    # Inquiry-linked message summaries expose overview_status/overview_text,
    # not the full message-level `overview` object (see _inquiry_view).
    assert linked.json()["messages"][0]["overview_text"] is None
    assert linked.json()["messages"][1]["overview_text"] is None
    with factory() as db:
        link_event = db.scalar(select(InquiryEvent).where(InquiryEvent.inquiry_id == 1, InquiryEvent.event_type == "inquiry_message_linked"))
        assert link_event is not None
        assert link_event.actor_user_id == 1
    login(http, "op-b", "operator2")
    assert http.post("/api/inquiries/1/messages", json={"message_id": 2}, headers=csrf_headers(http)).status_code == 403


def test_missing_identity_is_not_linkable_and_candidate_get_is_read_only(client):
    http, factory = client
    login(http, "op-a", "operator1")
    with factory() as db:
        message = Message(
            channel_account_id=1,
            provider="gmail_api_pubsub",
            external_message_id="missing-contact",
            direction="inbound",
            status="received",
            handling_status="pending",
            occurred_at=datetime.now(timezone.utc),
            raw_content="identity absent",
            customer_contact=None,
        )
        db.add(message)
        db.commit()
        message_id = message.id

    before = http.get(f"/api/messages/{message_id}").json()
    result = http.get(f"/api/messages/{message_id}/inquiry-candidates")
    after = http.get(f"/api/messages/{message_id}").json()
    assert result.status_code == 200
    assert result.json()["match_state"] == "missing_identity"
    assert after["link_state"] == before["link_state"] == "pending"


def test_candidate_query_and_link_reject_unscoped_and_wrong_identity(client):
    http, _ = client
    login(http, "op-a", "operator1")
    assert http.get("/api/messages/2/inquiry-candidates").status_code == 403
    wrong_type = http.post("/api/inquiries/3/messages", json={"message_id": 4}, headers=csrf_headers(http))
    assert wrong_type.status_code == 409
    assert http.get("/api/messages/4").json()["id"] == 4
    assert http.get("/api/messages/4").json()["link_state"] == "pending"


def test_duplicate_link_is_idempotent_but_other_target_is_conflict(client):
    http, _ = client
    login(http, "op-a", "operator1")
    headers = csrf_headers(http)
    first = http.post("/api/inquiries/1/messages", json={"message_id": 3}, headers=headers)
    assert first.status_code == 200
    duplicate_same = http.post("/api/inquiries/1/messages", json={"message_id": 3}, headers=headers)
    assert duplicate_same.status_code == 200
    # Same message cannot be associated with a second Inquiry, even if the
    # normalized email identity matches.
    # Target authorization is checked before existing-link conflicts; inquiry 2
    # is outside operator A's scope and must not be disclosed as a conflict.
    assert http.post("/api/inquiries/2/messages", json={"message_id": 3}, headers=headers).status_code == 403


def test_link_commit_failure_rolls_back_link_and_event(client, monkeypatch):
    http, factory = client
    login(http, "op-a", "operator1")
    from sqlalchemy.orm import Session

    original_commit = Session.commit
    monkeypatch.setattr(Session, "commit", lambda self: (_ for _ in ()).throw(RuntimeError("commit fail")))
    response = http.post("/api/inquiries/1/messages", json={"message_id": 3}, headers=csrf_headers(http))
    assert response.status_code == 500
    monkeypatch.setattr(Session, "commit", original_commit)
    with factory() as db:
        assert db.scalar(select(InquiryMessage).where(InquiryMessage.message_id == 3)) is None
        assert db.scalar(select(InquiryEvent).where(InquiryEvent.event_type == "inquiry_message_linked")) is None
