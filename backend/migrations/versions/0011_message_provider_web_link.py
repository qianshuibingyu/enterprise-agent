"""Add provider web links for authorized channel handling.

Revision ID: 0011_message_provider_web_link
Revises: 0010_message_customer_contact
Create Date: 2026-11-04
"""

from alembic import op
import sqlalchemy as sa


revision = "0011_message_provider_web_link"
down_revision = "0010_message_customer_contact"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "messages",
        sa.Column("provider_web_link", sa.String(length=2048), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("messages", "provider_web_link")
