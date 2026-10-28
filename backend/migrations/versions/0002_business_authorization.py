"""Add channel-scoped inquiries and internal notifications.

Revision ID: 0002_business_authorization
Revises: 0001_auth_sessions
Create Date: 2026-10-22
"""

from alembic import op
import sqlalchemy as sa


revision = "0002_business_authorization"
down_revision = "0001_auth_sessions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "channel_accounts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("owner_user_id", sa.Integer(), nullable=False),
        sa.Column("channel_type", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "id", "channel_type", "owner_user_id",
            name="uq_channel_accounts_id_type_owner",
        ),
    )
    op.create_index("ix_channel_accounts_owner_user_id", "channel_accounts", ["owner_user_id"])
    op.create_index("ix_channel_accounts_channel_type", "channel_accounts", ["channel_type"])
    op.create_index("ix_channel_accounts_status", "channel_accounts", ["status"])

    op.create_table(
        "channel_grants",
        sa.Column("channel_account_id", sa.Integer(), nullable=False),
        sa.Column("channel_type", sa.String(length=32), nullable=False),
        sa.Column("owner_user_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["channel_account_id", "channel_type", "owner_user_id"],
            [
                "channel_accounts.id",
                "channel_accounts.channel_type",
                "channel_accounts.owner_user_id",
            ],
            name="fk_channel_grants_account_scope",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "channel_account_id",
            "channel_type",
            "owner_user_id",
            name="pk_channel_grants",
        ),
    )
    op.create_index("ix_channel_grants_channel_account_id", "channel_grants", ["channel_account_id"])
    op.create_index("ix_channel_grants_channel_type", "channel_grants", ["channel_type"])
    op.create_index("ix_channel_grants_owner_user_id", "channel_grants", ["owner_user_id"])

    op.create_table(
        "inquiries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("customer_contact", sa.String(length=255), nullable=False),
        sa.Column("customer_nickname", sa.String(length=255), nullable=False),
        sa.Column("raw_message", sa.Text(), nullable=False),
        sa.Column("source_channel_account_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("assigned_sales_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("status IN ('new', 'assigned')", name="ck_inquiries_status"),
        sa.ForeignKeyConstraint(["assigned_sales_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["source_channel_account_id"], ["channel_accounts.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_inquiries_source_channel_account_id", "inquiries", ["source_channel_account_id"])
    op.create_index("ix_inquiries_status", "inquiries", ["status"])
    op.create_index("ix_inquiries_assigned_sales_user_id", "inquiries", ["assigned_sales_user_id"])

    op.create_table(
        "inquiry_attachments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("inquiry_id", sa.Integer(), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("media_type", sa.String(length=128), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("storage_reference", sa.String(length=512), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["inquiry_id"], ["inquiries.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_inquiry_attachments_inquiry_id", "inquiry_attachments", ["inquiry_id"])

    op.create_table(
        "internal_notifications",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("inquiry_id", sa.Integer(), nullable=False),
        sa.Column("notification_type", sa.String(length=64), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["inquiry_id"], ["inquiries.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_internal_notifications_inquiry_id", "internal_notifications", ["inquiry_id"])


def downgrade() -> None:
    op.drop_index("ix_internal_notifications_inquiry_id", table_name="internal_notifications")
    op.drop_table("internal_notifications")
    op.drop_index("ix_inquiry_attachments_inquiry_id", table_name="inquiry_attachments")
    op.drop_table("inquiry_attachments")
    op.drop_index("ix_inquiries_assigned_sales_user_id", table_name="inquiries")
    op.drop_index("ix_inquiries_status", table_name="inquiries")
    op.drop_index("ix_inquiries_source_channel_account_id", table_name="inquiries")
    op.drop_table("inquiries")
    op.drop_index("ix_channel_grants_owner_user_id", table_name="channel_grants")
    op.drop_index("ix_channel_grants_channel_type", table_name="channel_grants")
    op.drop_index("ix_channel_grants_channel_account_id", table_name="channel_grants")
    op.drop_table("channel_grants")
    op.drop_index("ix_channel_accounts_status", table_name="channel_accounts")
    op.drop_index("ix_channel_accounts_channel_type", table_name="channel_accounts")
    op.drop_index("ix_channel_accounts_owner_user_id", table_name="channel_accounts")
    op.drop_table("channel_accounts")
