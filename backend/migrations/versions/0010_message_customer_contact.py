"""Add provider-derived contact display fields to messages.

Revision ID: 0010_message_customer_contact
Revises: 0009_outlook_account_credential
Create Date: 2026-11-04
"""

from alembic import op
import sqlalchemy as sa


revision = "0010_message_customer_contact"
down_revision = "0009_outlook_account_credential"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "messages",
        sa.Column("customer_contact", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "messages",
        sa.Column("customer_nickname", sa.String(length=255), nullable=True),
    )
    op.create_index(
        "ix_messages_customer_contact",
        "messages",
        ["customer_contact"],
    )


def downgrade() -> None:
    op.drop_index("ix_messages_customer_contact", table_name="messages")
    op.drop_column("messages", "customer_nickname")
    op.drop_column("messages", "customer_contact")
