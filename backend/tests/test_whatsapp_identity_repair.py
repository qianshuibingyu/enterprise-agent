from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.contact_identity import normalize_whatsapp
from app.identity_repair import repair_whatsapp_contact_identity
from app.message_ingestion import ingest_provider_message, map_provider_message
from app.models.base import Base
from app.models.business import ChannelAccount, Inquiry, InquiryMessage, Message
from app.models.user import User

BASE_TIME = datetime(2026, 11, 13, 6, 0, tzinfo=timezone.utc)


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session = sessionmaker(bind=engine, expire_on_commit=False)
    Base.metadata.create_all(engine)
    with testing_session() as db:
        db.add(User(username="ops", password_hash="hash", role="staff", department="inquiry", is_active=True, must_change_password=False))
        db.flush()
        active = ChannelAccount(owner_user_id=1, channel_type="whatsapp", external_account_id="wa-1", status="connected")
        revoked = ChannelAccount(owner_user_id=1, channel_type="whatsapp", external_account_id="wa-2", status="revoked")
        db.add_all([active, revoked])
        db.commit()
        yield db
    Base.metadata.drop_all(engine)
    engine.dispose()


def stored_message(
    account_id: int,
    *,
    external_id: str,
    contact: str | None,
    minutes: int = 0,
    identity_state: str = "needs_manual_review",
    link_state: str = "manual_review",
    nickname: str = "Hamudi",
) -> Message:
    return Message(
        channel_account_id=account_id,
        provider="whatsapp_web_baileys",
        external_message_id=external_id,
        direction="inbound",
        status="received",
        handling_status="pending",
        occurred_at=BASE_TIME + timedelta(minutes=minutes),
        raw_content="hello",
        customer_contact=contact,
        normalized_customer_contact=None,
        contact_identity_state=identity_state,
        contact_identity_kind=None,
        customer_nickname=nickname,
        link_state=link_state,
    )


def test_bare_whatsapp_digits_become_e164_only_for_provider_values():
    assert normalize_whatsapp("46735037108").state == "needs_manual_review"
    identity = normalize_whatsapp("46735037108", assume_international=True)
    assert identity.normalized == "+46735037108"
    assert identity.state == "certain"
    assert identity.kind == "whatsapp"
    # A too-short value is never padded into a guessed number.
    assert normalize_whatsapp("12345", assume_international=True).state == "needs_manual_review"


def test_whatsapp_ingest_normalizes_jid_digits_and_links_without_review(db_session):
    mapped = map_provider_message(
        channel_account_id=1,
        provider="whatsapp_web_baileys",
        message={
            "external_message_id": "46735037108@s.whatsapp.net::abc",
            "direction": "inbound",
            "status": "received",
            "occurred_at": BASE_TIME,
            "raw_content": "我们要两个",
            "customer_contact": "46735037108",
            "customer_nickname": "Hamudi",
        },
    )
    assert mapped.contact_identity_state == "certain"
    assert mapped.contact_identity_kind == "whatsapp"
    assert mapped.normalized_customer_contact == "+46735037108"

    result = ingest_provider_message(
        db_session,
        channel_account_id=1,
        provider="whatsapp_web_baileys",
        message={
            "external_message_id": "46735037108@s.whatsapp.net::abc",
            "direction": "inbound",
            "status": "received",
            "occurred_at": BASE_TIME,
            "raw_content": "我们要两个",
            "customer_contact": "46735037108",
            "customer_nickname": "Hamudi",
        },
    )
    db_session.commit()

    assert result.message.link_state == "linked"
    assert result.message.inquiry_link is not None
    inquiry = db_session.scalar(select(Inquiry).where(Inquiry.id == result.message.inquiry_link.inquiry_id))
    assert inquiry.normalized_customer_contact == "+46735037108"
    assert inquiry.contact_identity_state == "certain"
    assert inquiry.contact_identity_kind == "whatsapp"
    # The phone the customer actually messaged from is kept for display.
    assert inquiry.customer_contact == "46735037108"


def test_repair_confirms_stored_whatsapp_numbers_and_creates_one_chain(db_session):
    db_session.add_all(
        [
            stored_message(1, external_id="m1", contact="46735037108"),
            stored_message(1, external_id="m2", contact="46735037108", minutes=1),
            stored_message(1, external_id="m3", contact="46735037108", minutes=2),
            # Group chat: the adapter cannot expose a phone number for it.
            stored_message(1, external_id="1234@g.us:5678:g1", contact=None, link_state="manual_review"),
            # LID-only chat: still no number, so it stays a manual decision.
            stored_message(1, external_id="999@lid:0:l1", contact=None, link_state="manual_review"),
        ]
    )
    db_session.commit()

    stats = repair_whatsapp_contact_identity(db_session)
    db_session.commit()

    assert stats == {"scanned": 3, "confirmed": 3, "linked": 3, "inquiries_created": 1}
    chain = db_session.scalars(select(Inquiry)).all()
    assert len(chain) == 1
    assert chain[0].normalized_customer_contact == "+46735037108"
    linked = db_session.scalars(
        select(Message).where(Message.link_state == "linked").order_by(Message.id)
    ).all()
    assert [message.external_message_id for message in linked] == ["m1", "m2", "m3"]
    links = db_session.scalars(select(InquiryMessage).order_by(InquiryMessage.position)).all()
    assert [link.position for link in links] == [1, 2, 3]
    # Manual decisions are untouched.
    untouched = db_session.scalars(
        select(Message).where(Message.link_state == "manual_review").order_by(Message.id)
    ).all()
    assert [message.external_message_id for message in untouched] == [
        "1234@g.us:5678:g1",
        "999@lid:0:l1",
    ]
    assert all(message.contact_identity_state == "needs_manual_review" for message in untouched)

    # Re-running the repair changes nothing.
    assert repair_whatsapp_contact_identity(db_session) == {
        "scanned": 0,
        "confirmed": 0,
        "linked": 0,
        "inquiries_created": 0,
    }


def test_repair_does_not_reopen_a_chain_the_operator_ignored(db_session):
    db_session.add(
        Inquiry(
            customer_contact="46735037108",
            normalized_customer_contact="+46735037108",
            contact_identity_state="certain",
            contact_identity_kind="whatsapp",
            customer_nickname="Hamudi",
            raw_message="old",
            source_channel_account_id=1,
            status="new",
            handling_status="ignored",
        )
    )
    db_session.add(stored_message(1, external_id="late", contact="46735037108"))
    db_session.commit()

    stats = repair_whatsapp_contact_identity(db_session)
    db_session.commit()

    message = db_session.scalar(select(Message).where(Message.external_message_id == "late"))
    assert message.contact_identity_state == "certain"
    assert message.link_state == "manual_review"
    assert message.inquiry_link is None
    assert len(db_session.scalars(select(Inquiry)).all()) == 1
    assert stats["inquiries_created"] == 0
    assert stats["linked"] == 0


def test_repair_skips_revoked_whatsapp_accounts(db_session):
    db_session.add(stored_message(2, external_id="old", contact="46735037108"))
    db_session.commit()

    stats = repair_whatsapp_contact_identity(db_session)
    db_session.commit()

    message = db_session.scalar(select(Message).where(Message.external_message_id == "old"))
    assert stats["scanned"] == 0
    assert message.contact_identity_state == "needs_manual_review"
    assert message.link_state == "manual_review"
