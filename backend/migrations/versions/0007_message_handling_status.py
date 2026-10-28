"""Add the minimal human handling status for messages.

Revision ID: 0007_message_handling_status
Revises: 0006_manual_handling_status
Create Date: 2026-10-28
"""

from alembic import op
import sqlalchemy as sa


revision = "0007_message_handling_status"
down_revision = "0006_manual_handling_status"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "messages",
        sa.Column("handling_status", sa.String(length=16), nullable=False, server_default="pending"),
    )
    op.create_index("ix_messages_handling_status", "messages", ["handling_status"])
    op.create_check_constraint(
        "ck_messages_handling_status",
        "messages",
        "handling_status IN ('pending', 'processed', 'ignored')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_messages_handling_status", "messages", type_="check")
    op.drop_index("ix_messages_handling_status", table_name="messages")
    op.drop_column("messages", "handling_status")
