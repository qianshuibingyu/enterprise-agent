"""Add Gmail account-scoped credential and watch metadata.

Revision ID: 0008_gmail_account_runtime
Revises: 0007_message_handling_status
Create Date: 2026-10-30
"""

from alembic import op
import sqlalchemy as sa


revision = "0008_gmail_account_runtime"
down_revision = "0007_message_handling_status"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "channel_accounts",
        sa.Column("credential_reference", sa.String(length=512), nullable=True),
    )
    op.add_column(
        "channel_accounts",
        sa.Column("gmail_credential_ciphertext", sa.Text(), nullable=True),
    )
    op.add_column(
        "channel_accounts",
        sa.Column("gmail_watch_history_id", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "channel_accounts",
        sa.Column("gmail_watch_expiration", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("channel_accounts", "gmail_watch_expiration")
    op.drop_column("channel_accounts", "gmail_watch_history_id")
    op.drop_column("channel_accounts", "gmail_credential_ciphertext")
    op.drop_column("channel_accounts", "credential_reference")
