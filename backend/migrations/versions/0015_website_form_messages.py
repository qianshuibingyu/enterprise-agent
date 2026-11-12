"""Keep known website form submissions outside customer identity grouping."""

from alembic import op
import sqlalchemy as sa

from app.contact_identity import normalize_email


revision = "0015_website_form_messages"
down_revision = "0014_inquiry_business_type"
branch_labels = None
depends_on = None

WEBSITE_FORM_EMAIL = "lingorm1115@outlook.com"


def upgrade() -> None:
    op.add_column(
        "messages",
        sa.Column("is_website_form", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index("ix_messages_is_website_form", "messages", ["is_website_form"])

    bind = op.get_bind()
    rows = bind.execute(sa.text(
        "SELECT id, channel_account_id, occurred_at, raw_content, customer_contact, "
        "original_sender_contact, customer_nickname FROM messages WHERE direction = 'inbound'"
    )).mappings().all()
    for message in rows:
        if normalize_email(message["customer_contact"]).normalized != WEBSITE_FORM_EMAIL:
            continue

        bind.execute(sa.text(
            "UPDATE messages SET is_website_form = TRUE, normalized_customer_contact = NULL, "
            "contact_identity_state = 'unsupported', contact_identity_kind = NULL, "
            "customer_nickname = '官网表单提交', link_state = 'linked' WHERE id = :id"
        ), {"id": message["id"]})
        bind.execute(sa.text("DELETE FROM inquiry_messages WHERE message_id = :id"), {"id": message["id"]})

        inquiry_id = bind.execute(sa.text(
            "INSERT INTO inquiries (customer_contact, normalized_customer_contact, "
            "contact_identity_state, contact_identity_kind, customer_nickname, raw_message, "
            "source_channel_account_id, status, handling_status, last_activity_at) "
            "VALUES (:contact, NULL, 'unsupported', NULL, :contact, :body, :account_id, "
            "'new', 'pending', :occurred_at) RETURNING id"
        ), {
            "contact": f"官网表单提交 #{message['id']}",
            "body": message["raw_content"],
            "account_id": message["channel_account_id"],
            "occurred_at": message["occurred_at"],
        }).scalar_one()
        bind.execute(sa.text(
            "INSERT INTO inquiry_messages (inquiry_id, message_id, position, link_source) "
            "VALUES (:inquiry_id, :message_id, 1, 'initial_inbound')"
        ), {"inquiry_id": inquiry_id, "message_id": message["id"]})
        bind.execute(sa.text(
            "INSERT INTO inquiry_events (inquiry_id, event_type, to_status, message_id, occurred_at) "
            "VALUES (:inquiry_id, 'inquiry_created', 'new', :message_id, :occurred_at)"
        ), {
            "inquiry_id": inquiry_id,
            "message_id": message["id"],
            "occurred_at": message["occurred_at"],
        })


def downgrade() -> None:
    bind = op.get_bind()
    count = bind.execute(sa.text("SELECT count(*) FROM messages WHERE is_website_form = TRUE")).scalar_one()
    if count:
        raise RuntimeError("Cannot downgrade while website form messages have independent inquiry chains")
    op.drop_index("ix_messages_is_website_form", table_name="messages")
    op.drop_column("messages", "is_website_form")
