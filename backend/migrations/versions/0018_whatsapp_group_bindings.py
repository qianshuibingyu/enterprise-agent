"""Persist operator-confirmed WhatsApp group -> customer phone bindings."""

from alembic import op
import sqlalchemy as sa


revision = "0018_whatsapp_group_bindings"
down_revision = "0017_message_feed_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "whatsapp_group_bindings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("group_jid", sa.String(length=255), nullable=False),
        sa.Column("channel_account_id", sa.Integer(), nullable=True),
        sa.Column("normalized_phone", sa.String(length=32), nullable=False),
        sa.Column("raw_phone", sa.String(length=64), nullable=True),
        sa.Column("bound_by_user_id", sa.Integer(), nullable=True),
        sa.Column("note", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["channel_account_id"], ["channel_accounts.id"],
            name="fk_whatsapp_group_bindings_channel_account_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["bound_by_user_id"], ["users.id"],
            name="fk_whatsapp_group_bindings_bound_by_user_id",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_whatsapp_group_bindings"),
        sa.UniqueConstraint("group_jid", name="uq_whatsapp_group_bindings_group_jid"),
        sa.CheckConstraint("normalized_phone LIKE '+%'", name="ck_whatsapp_group_bindings_phone_e164"),
        sa.CheckConstraint("group_jid LIKE '%@g.us'", name="ck_whatsapp_group_bindings_group_jid"),
    )
    op.create_index(
        "ix_whatsapp_group_bindings_normalized_phone",
        "whatsapp_group_bindings", ["normalized_phone"],
    )
    op.create_index(
        "ix_whatsapp_group_bindings_channel_account_id",
        "whatsapp_group_bindings", ["channel_account_id"],
    )
    op.create_index(
        "ix_whatsapp_group_bindings_bound_by_user_id",
        "whatsapp_group_bindings", ["bound_by_user_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_whatsapp_group_bindings_bound_by_user_id", table_name="whatsapp_group_bindings")
    op.drop_index("ix_whatsapp_group_bindings_channel_account_id", table_name="whatsapp_group_bindings")
    op.drop_index("ix_whatsapp_group_bindings_normalized_phone", table_name="whatsapp_group_bindings")
    op.drop_table("whatsapp_group_bindings")
