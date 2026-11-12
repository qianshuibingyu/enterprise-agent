"""Add account-scoped Outlook delegated credential storage.

Revision ID: 0009_outlook_account_credential
Revises: 0008_gmail_account_runtime
Create Date: 2026-11-02
"""

from alembic import op
import sqlalchemy as sa


revision = "0009_outlook_account_credential"
down_revision = "0008_gmail_account_runtime"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "channel_accounts",
        sa.Column("outlook_credential_ciphertext", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("channel_accounts", "outlook_credential_ciphertext")
