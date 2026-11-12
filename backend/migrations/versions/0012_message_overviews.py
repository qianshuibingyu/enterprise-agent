"""Add persisted message overview state.

Revision ID: 0012_message_overviews
Revises: 0011_message_provider_web_link
Create Date: 2026-11-06
"""

from alembic import op
import sqlalchemy as sa


revision = "0012_message_overviews"
down_revision = "0011_message_provider_web_link"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "messages",
        sa.Column("test_only", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_table(
        "message_overviews",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("message_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("overview_text", sa.Text(), nullable=True),
        sa.Column("failure_code", sa.String(length=64), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("provider_name", sa.String(length=128), nullable=True),
        sa.Column("model_name", sa.String(length=255), nullable=True),
        sa.Column("prompt_version", sa.String(length=64), nullable=False, server_default="day8-v1"),
        sa.Column("test_only", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["message_id"], ["messages.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("message_id", name="uq_message_overviews_message_id"),
        sa.CheckConstraint(
            "status IN ('pending', 'ready', 'failed')",
            name="ck_message_overviews_status",
        ),
    )
    op.create_index("ix_message_overviews_message_id", "message_overviews", ["message_id"])
    op.create_index("ix_message_overviews_status", "message_overviews", ["status"])


def downgrade() -> None:
    op.drop_index("ix_message_overviews_status", table_name="message_overviews")
    op.drop_index("ix_message_overviews_message_id", table_name="message_overviews")
    op.drop_table("message_overviews")
    op.drop_column("messages", "test_only")
