"""Add minimal Inquiry-to-Message links.

Revision ID: 0013_inquiry_messages
Revises: 0012_message_overviews
Create Date: 2026-11-07
"""

from alembic import op
import sqlalchemy as sa

revision = "0013_inquiry_messages"
down_revision = "0012_message_overviews"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Cross-account email inquiries cannot use one source account as their
    # authorization scope. Keep it only as provenance; reads use linked-message
    # scopes. Existing rows remain unlinked (no guessed backfill).
    op.drop_constraint(
        "ck_inquiry_events_type",
        "inquiry_events", type_="check",
    )
    op.create_check_constraint(
        "ck_inquiry_events_type",
        "inquiry_events",
        "event_type IN ('inquiry_created', 'inquiry_transferred', 'inquiry_processed', 'inquiry_ignored', 'inquiry_reactivated', 'inquiry_message_linked', 'manual_link')",
    )
    op.add_column("inquiries", sa.Column("normalized_customer_contact", sa.String(length=255), nullable=True))
    op.add_column("inquiries", sa.Column("contact_identity_kind", sa.String(length=16), nullable=True))
    op.add_column("inquiries", sa.Column("contact_identity_state", sa.String(length=32), nullable=False, server_default="needs_manual_review"))
    op.create_check_constraint("ck_inquiries_contact_identity_state", "inquiries", "contact_identity_state IN ('certain', 'forwarded', 'identity_uncertain', 'needs_manual_review', 'unsupported')")
    op.create_index("ix_inquiries_normalized_customer_contact", "inquiries", ["normalized_customer_contact"])
    op.add_column("messages", sa.Column("normalized_customer_contact", sa.String(length=255), nullable=True))
    op.add_column("messages", sa.Column("contact_identity_state", sa.String(length=32), nullable=False, server_default="needs_manual_review"))
    op.add_column("messages", sa.Column("contact_identity_kind", sa.String(length=16), nullable=True))
    op.add_column("messages", sa.Column("original_sender_contact", sa.String(length=255), nullable=True))
    op.create_check_constraint("ck_messages_contact_identity_state", "messages", "contact_identity_state IN ('certain', 'forwarded', 'identity_uncertain', 'needs_manual_review', 'unsupported')")
    op.create_index("ix_messages_normalized_customer_contact", "messages", ["normalized_customer_contact"])
    op.add_column("inquiries", sa.Column("last_activity_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_inquiries_last_activity_at", "inquiries", ["last_activity_at"])
    op.alter_column(
        "inquiries", "source_channel_account_id",
        existing_type=sa.Integer(), nullable=True,
    )
    # 0002 created this FK unnamed; PostgreSQL assigns this conventional name.
    op.drop_constraint(
        "inquiries_source_channel_account_id_fkey",
        "inquiries", type_="foreignkey",
    )
    op.create_foreign_key(
        "fk_inquiries_source_channel_account_id_channel_accounts",
        "inquiries", "channel_accounts", ["source_channel_account_id"], ["id"],
        ondelete="SET NULL",
    )
    op.add_column("inquiry_events", sa.Column("message_id", sa.Integer(), nullable=True))
    op.create_foreign_key("fk_inquiry_events_message_id_messages", "inquiry_events", "messages", ["message_id"], ["id"], ondelete="SET NULL")
    op.create_index("ix_inquiry_events_message_id", "inquiry_events", ["message_id"])
    op.add_column("messages", sa.Column("link_state", sa.String(length=24), nullable=False, server_default="pending"))
    op.create_check_constraint(
        "ck_messages_link_state",
        "messages",
        "link_state IN ('pending', 'linked', 'unmatched', 'manual_review', 'not_linkable')",
    )
    op.create_index("ix_messages_link_state", "messages", ["link_state"])
    op.create_table(
        "inquiry_messages",
        sa.Column("inquiry_id", sa.Integer(), nullable=False),
        sa.Column("message_id", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("link_source", sa.String(length=32), nullable=False, server_default="inbound_match"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("inquiry_id", "message_id", name="pk_inquiry_messages"),
        sa.ForeignKeyConstraint(["inquiry_id"], ["inquiries.id"], name="fk_inquiry_messages_inquiry_id_inquiries", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["message_id"], ["messages.id"], name="fk_inquiry_messages_message_id_messages", ondelete="CASCADE"),
        sa.CheckConstraint("position > 0", name="ck_inquiry_messages_position_positive"),
        sa.UniqueConstraint("message_id", name="uq_inquiry_messages_message_id"),
        sa.UniqueConstraint("inquiry_id", "position", name="uq_inquiry_messages_position"),
    )
    op.create_index("ix_inquiry_messages_inquiry_id", "inquiry_messages", ["inquiry_id"])
    op.create_index("ix_inquiry_messages_message_id", "inquiry_messages", ["message_id"])


def downgrade() -> None:
    bind = op.get_bind()
    missing_source = bind.execute(
        sa.text("SELECT count(*) FROM inquiries WHERE source_channel_account_id IS NULL")
    ).scalar_one()
    reactivated_events = bind.execute(
        sa.text("SELECT count(*) FROM inquiry_events WHERE event_type = 'inquiry_reactivated'")
    ).scalar_one()
    linked_events = bind.execute(
        sa.text("SELECT count(*) FROM inquiry_events WHERE event_type IN ('inquiry_message_linked', 'manual_link')")
    ).scalar_one()
    if missing_source:
        raise RuntimeError(
            "Cannot downgrade 0013: assign source_channel_account_id to all inquiries first"
        )
    link_states = bind.execute(
        sa.text("SELECT count(*) FROM messages WHERE link_state != 'pending'")
    ).scalar_one()
    identity_data = bind.execute(
        sa.text("SELECT count(*) FROM messages WHERE normalized_customer_contact IS NOT NULL OR original_sender_contact IS NOT NULL OR contact_identity_state != 'needs_manual_review'")
    ).scalar_one()
    inquiry_identity_data = bind.execute(
        sa.text("SELECT count(*) FROM inquiries WHERE normalized_customer_contact IS NOT NULL OR contact_identity_state != 'needs_manual_review'")
    ).scalar_one()
    manual_link_events = bind.execute(
        sa.text("SELECT count(*) FROM inquiry_events WHERE event_type = 'manual_link'")
    ).scalar_one()
    if reactivated_events or linked_events or link_states or identity_data or inquiry_identity_data or manual_link_events:
        raise RuntimeError(
            "Cannot downgrade 0013: link history/state or normalized identity decisions would be lost"
        )

    op.drop_constraint("ck_inquiry_events_type", "inquiry_events", type_="check")
    op.create_check_constraint(
        "ck_inquiry_events_type",
        "inquiry_events",
        "event_type IN ('inquiry_created', 'inquiry_transferred', 'inquiry_processed', 'inquiry_ignored')",
    )
    op.drop_index("ix_inquiry_messages_message_id", table_name="inquiry_messages")
    op.drop_index("ix_inquiry_messages_inquiry_id", table_name="inquiry_messages")
    op.drop_table("inquiry_messages")
    op.drop_index("ix_inquiry_events_message_id", table_name="inquiry_events")
    op.drop_constraint("fk_inquiry_events_message_id_messages", "inquiry_events", type_="foreignkey")
    op.drop_column("inquiry_events", "message_id")
    op.drop_index("ix_messages_link_state", table_name="messages")
    op.drop_constraint("ck_messages_link_state", "messages", type_="check")
    op.drop_column("messages", "link_state")
    op.drop_index("ix_messages_normalized_customer_contact", table_name="messages")
    op.drop_constraint("ck_messages_contact_identity_state", "messages", type_="check")
    op.drop_column("messages", "original_sender_contact")
    op.drop_column("messages", "contact_identity_kind")
    op.drop_column("messages", "contact_identity_state")
    op.drop_column("messages", "normalized_customer_contact")
    op.drop_index("ix_inquiries_normalized_customer_contact", table_name="inquiries")
    op.drop_constraint("ck_inquiries_contact_identity_state", "inquiries", type_="check")
    op.drop_column("inquiries", "contact_identity_kind")
    op.drop_column("inquiries", "contact_identity_state")
    op.drop_column("inquiries", "normalized_customer_contact")
    op.drop_index("ix_inquiries_last_activity_at", table_name="inquiries")
    op.drop_column("inquiries", "last_activity_at")
    op.drop_constraint(
        "fk_inquiries_source_channel_account_id_channel_accounts",
        "inquiries", type_="foreignkey",
    )
    op.create_foreign_key(
        "fk_inquiries_source_channel_account_id_channel_accounts",
        "inquiries", "channel_accounts", ["source_channel_account_id"], ["id"],
    )
    # Existing rows created while accountless must be assigned a valid source
    # before rollback; this migration intentionally does not invent one.
    op.alter_column(
        "inquiries", "source_channel_account_id",
        existing_type=sa.Integer(), nullable=False,
    )
