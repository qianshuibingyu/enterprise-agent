from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.message_ingestion import ingest_provider_message
from app.models.base import Base
from app.models.business import (
    ChannelAccount,
    ChannelGrant,
    Inquiry,
    InquiryEvent,
    InquiryMessage,
    Message,
)
from app.models.overview import MessageOverview
from app.models.user import User


@pytest.fixture
def link_db():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    @event.listens_for(engine, "connect")
    def enable_sqlite_foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        db.add_all([
            User(username="op1", password_hash="x", role="staff", is_active=True, must_change_password=False),
            User(username="op2", password_hash="x", role="staff", is_active=True, must_change_password=False),
            User(username="sales", password_hash="x", role="sales", is_active=True, must_change_password=False),
        ])
        db.flush()
        db.add_all([
            ChannelAccount(id=1, owner_user_id=1, channel_type="gmail", status="connected"),
            ChannelAccount(id=2, owner_user_id=2, channel_type="outlook", status="connected"),
            ChannelAccount(id=3, owner_user_id=2, channel_type="gmail", status="connected"),
        ])
        db.flush()
        db.add_all([
            ChannelGrant(channel_account_id=1, channel_type="gmail", owner_user_id=1),
            ChannelGrant(channel_account_id=2, channel_type="outlook", owner_user_id=2),
            ChannelGrant(channel_account_id=3, channel_type="gmail", owner_user_id=2),
        ])
        db.commit()
        yield db
    Base.metadata.drop_all(engine)
    engine.dispose()


def ingest(db, account_id, contact, external_id, content):
    provider = "whatsapp_web_baileys" if "@s.whatsapp.net" in contact else (
        "gmail_api_pubsub" if account_id in {1, 3} else "outlook_mcp_graph"
    )
    return ingest_provider_message(
        db,
        channel_account_id=account_id,
        provider=provider,
        message={
            "external_message_id": external_id,
            "direction": "inbound",
            "status": "received",
            "occurred_at": datetime(2026, 11, 7, tzinfo=timezone.utc),
            "raw_content": content,
            "customer_contact": contact,
        },
    )


def test_inquiry_link_lock_query_is_valid_for_postgresql(link_db):
    statements = []

    @event.listens_for(link_db, "do_orm_execute")
    def capture_query(state):
        statement = state.statement
        if getattr(statement, "_for_update_arg", None) is not None:
            statements.append(str(statement.compile(dialect=postgresql.dialect())).upper())

    ingest(link_db, 1, "lock@example.com", "lock-1", "message")
    assert len(statements) == 1
    assert "SELECT DISTINCT" not in statements[0]
    assert "FOR UPDATE OF INQUIRIES" in statements[0]


def test_inbound_messages_auto_link_by_exact_email_across_gmail_outlook(link_db):
    first = ingest(link_db, 1, "Customer@Example.com", "a", "first")
    link_db.commit()
    second = ingest(link_db, 2, "customer@example.com", "b", "second")
    link_db.commit()

    links = link_db.scalars(select(InquiryMessage).order_by(InquiryMessage.position)).all()
    assert len(links) == 2
    assert links[0].inquiry_id == links[1].inquiry_id
    assert links[0].message_id == first.message.id
    assert links[1].message_id == second.message.id
    assert first.message.raw_content == "first"
    assert second.message.raw_content == "second"
    assert first.message.link_state == second.message.link_state == "linked"


def test_later_message_for_unique_identity_continues_same_inquiry(link_db):
    first = ingest(link_db, 1, "continue@example.com", "continue-1", "first")
    link_db.commit()
    second = ingest(link_db, 3, "CONTINUE@example.com", "continue-2", "second")
    link_db.commit()
    assert second.message.inquiry_link.inquiry_id == first.message.inquiry_link.inquiry_id
    assert second.message.raw_content == "second"
    assert second.message.link_state == "linked"


def test_inbound_message_reactivates_processed_inquiry(link_db):
    first = ingest(link_db, 1, "reactivate@example.com", "reactivate-1", "first")
    inquiry_id = first.message.inquiry_link.inquiry_id
    first.message.inquiry_link.inquiry.handling_status = "processed"
    link_db.commit()

    second = ingest(link_db, 2, "REACTIVATE@example.com", "reactivate-2", "follow-up")
    link_db.commit()

    inquiry = link_db.get(Inquiry, inquiry_id)
    assert second.message.inquiry_link.inquiry_id == inquiry_id
    assert inquiry.handling_status == "pending"
    assert inquiry.events[-1].event_type == "inquiry_reactivated"
    assert inquiry.events[-1].from_status == "processed"


def test_multiple_candidate_inquiries_leave_message_unlinked(link_db):
    first = ingest(link_db, 1, "ambiguous@example.com", "ambiguous-1", "first")
    contact = first.message.customer_contact
    source = first.message.inquiry_link.inquiry.source_channel_account_id
    second_inquiry = Inquiry(
        customer_contact=contact,
        customer_nickname="Ambiguous",
        raw_message="separate inquiry, same identity",
        source_channel_account_id=source,
        status="new",
        handling_status="pending",
        events=[InquiryEvent(event_type="inquiry_created", to_status="new")],
    )
    link_db.add(second_inquiry)
    link_db.flush()
    second_message = ingest(link_db, 1, contact, "ambiguous-2", "must not guess")
    link_db.commit()

    assert second_message.message.inquiry_link is None
    assert second_message.message.link_state == "manual_review"
    assert link_db.query(InquiryMessage).filter_by(message_id=first.message.id).count() == 1
    assert link_db.query(InquiryMessage).filter_by(message_id=second_message.message.id).count() == 0

    # Once one of the ambiguous inquiries is handled, an idempotent provider
    # replay re-evaluates identity and attaches only when a single candidate remains.
    link_db.query(Inquiry).filter(Inquiry.id == second_inquiry.id).update({Inquiry.handling_status: "ignored"})
    link_db.commit()
    replay = ingest(link_db, 1, contact, "ambiguous-2", "must not overwrite stored body")
    link_db.commit()
    assert replay.created is False
    assert replay.message.inquiry_link.inquiry_id == first.message.inquiry_link.inquiry_id
    assert replay.message.raw_content == "must not guess"


def test_whatsapp_phone_does_not_merge_with_email(link_db):
    email = ingest(link_db, 1, "customer@example.com", "email", "mail")
    link_db.commit()
    wa = ingest(link_db, 1, "8613812345678@s.whatsapp.net", "wa", "whatsapp")
    link_db.commit()
    assert email.message.inquiry_link.inquiry_id != wa.message.inquiry_link.inquiry_id
    assert email.message.link_state == wa.message.link_state == "linked"


def test_link_uniqueness_and_delete_cascade_preserve_message_and_overview(link_db):
    result = ingest(link_db, 1, "customer@example.com", "unique", "body")
    inquiry = result.message.inquiry_link.inquiry
    link_db.add(MessageOverview(message_id=result.message.id, status="ready", overview_text="summary"))
    link_db.commit()
    link = result.message.inquiry_link
    duplicate = InquiryMessage(
        inquiry_id=inquiry.id,
        message_id=result.message.id,
        position=link.position + 1,
        link_source="manual",
    )
    with pytest.raises(IntegrityError):
        link_db.execute(
            InquiryMessage.__table__.insert().values(
                inquiry_id=duplicate.inquiry_id,
                message_id=duplicate.message_id,
                position=duplicate.position,
                link_source=duplicate.link_source,
            )
        )
    link_db.rollback()

    link_db.delete(inquiry)
    link_db.commit()
    assert link_db.get(Message, result.message.id) is not None
    assert link_db.scalar(select(MessageOverview).where(MessageOverview.message_id == result.message.id)) is not None
    assert link_db.scalar(select(InquiryMessage).where(InquiryMessage.message_id == result.message.id)) is None


def test_source_account_fk_is_set_null_but_message_account_remains_restrictive(link_db):
    inquiry_fk = next(
        fk for fk in Inquiry.__table__.foreign_key_constraints
        if "source_channel_account_id" in {column.name for column in fk.columns}
    )
    message_fk = next(
        fk for fk in Message.__table__.foreign_key_constraints
        if "channel_account_id" in {column.name for column in fk.columns}
    )
    assert inquiry_fk.ondelete == "SET NULL"
    assert message_fk.ondelete is None


def test_ingest_link_failure_rolls_back_message_and_inquiry(link_db, monkeypatch):
    from app import message_ingestion

    def fail(*args, **kwargs):
        raise RuntimeError("link failed")

    monkeypatch.setattr(message_ingestion, "_link_inbound_message_to_inquiry", fail)
    with pytest.raises(RuntimeError, match="link failed"):
        ingest(link_db, 1, "rollback@example.com", "rollback", "body")
    assert link_db.scalar(select(Message).where(Message.external_message_id == "rollback")) is None
    assert link_db.scalar(select(Inquiry).where(Inquiry.customer_contact == "rollback@example.com")) is None


def _staff_user(db, username="op1"):
    return db.scalar(select(User).where(User.username == username))


def test_inquiry_ignore_cascades_to_linked_pending_messages(link_db):
    from app.business_service import InquiryAction, transition_inquiry

    first = ingest(link_db, 1, "ignore-cascade@example.com", "ignore-1", "first")
    second = ingest(link_db, 1, "ignore-cascade@example.com", "ignore-2", "second")
    inquiry_id = first.message.inquiry_link.inquiry_id
    link_db.commit()

    inquiry = transition_inquiry(link_db, _staff_user(link_db), inquiry_id, InquiryAction.IGNORE)
    link_db.commit()

    assert inquiry.handling_status == "ignored"
    assert first.message.handling_status == "ignored"
    assert second.message.handling_status == "ignored"


def test_inquiry_ignore_requires_scope_of_every_linked_message_account(link_db):
    from fastapi import HTTPException

    from app.business_service import InquiryAction, transition_inquiry

    first = ingest(link_db, 1, "ignore-scope@example.com", "ignore-scope-1", "first")
    ingest(link_db, 3, "ignore-scope@example.com", "ignore-scope-2", "second")
    inquiry_id = first.message.inquiry_link.inquiry_id
    link_db.commit()

    # op1 只授权账号 1，而会话关联消息同时来自账号 3：与「已处理」一致，忽略也须拒绝。
    with pytest.raises(HTTPException) as exc_info:
        transition_inquiry(link_db, _staff_user(link_db), inquiry_id, InquiryAction.IGNORE)
    assert exc_info.value.status_code == 403
    link_db.rollback()
    assert link_db.get(Inquiry, inquiry_id).handling_status == "pending"


def test_inquiry_processed_cascade_keeps_marking_linked_messages_processed(link_db):
    from app.business_service import transition_inquiry
    from app.business_service import InquiryAction

    first = ingest(link_db, 1, "process-cascade@example.com", "process-1", "first")
    inquiry_id = first.message.inquiry_link.inquiry_id
    link_db.commit()

    inquiry = transition_inquiry(link_db, _staff_user(link_db), inquiry_id, InquiryAction.COMPLETE)
    link_db.commit()

    assert inquiry.handling_status == "processed"
    assert first.message.handling_status == "processed"


def test_website_form_only_accepts_whitelisted_direct_sender():
    from app.message_ingestion import WEBSITE_FORM_EMAIL, map_provider_message

    def payload(contact, original_sender=None):
        message = {
            "external_message_id": f"form-check-{contact}",
            "direction": "inbound",
            "status": "received",
            "occurred_at": datetime(2026, 11, 5, tzinfo=timezone.utc),
            "raw_content": "From: Medium Daily Digest <noreply@medium.com>\n\ndigest",
            "customer_contact": contact,
        }
        if original_sender is not None:
            message["original_sender_contact"] = original_sender
        return map_provider_message(
            channel_account_id=1, provider="outlook_mcp_graph", message=message
        )

    assert payload(WEBSITE_FORM_EMAIL).is_website_form is True
    assert payload("noreply@medium.com").is_website_form is False
    # 白名单邮箱转发的表单邮件仍是真表单（表单通知常经系统转发进入收件箱）。
    assert payload(WEBSITE_FORM_EMAIL, "noreply@medium.com").is_website_form is True


def test_effective_website_form_rejects_stale_mislabeled_rows():
    from app.message_ingestion import WEBSITE_FORM_EMAIL, effective_website_form

    stale = Message(customer_contact="noreply@medium.com", is_website_form=True)
    forwarded = Message(
        customer_contact=WEBSITE_FORM_EMAIL,
        original_sender_contact="noreply@medium.com",
        is_website_form=True,
    )
    valid = Message(customer_contact=WEBSITE_FORM_EMAIL, is_website_form=True)
    ordinary = Message(customer_contact="noreply@medium.com", is_website_form=False)

    assert effective_website_form(stale) is False
    assert effective_website_form(forwarded) is True
    assert effective_website_form(valid) is True
    assert effective_website_form(ordinary) is False
