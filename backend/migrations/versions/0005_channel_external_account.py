"""Add external runtime account mapping for channel ingress.

Revision ID: 0005_channel_external_account
Revises: 0004_inquiry_events
Create Date: 2026-10-27
"""

from alembic import op
import sqlalchemy as sa


revision = "0005_channel_external_account"
down_revision = "0004_inquiry_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "channel_accounts",
        sa.Column("external_account_id", sa.String(length=255), nullable=True),
    )
    op.create_index(
        "ix_channel_accounts_external_account_id",
        "channel_accounts",
        ["external_account_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_channel_accounts_external_account_id",
        table_name="channel_accounts",
    )
    op.drop_column("channel_accounts", "external_account_id")
