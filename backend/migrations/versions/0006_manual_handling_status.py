"""Add the minimal human handling status for inquiries.

Revision ID: 0006_manual_handling_status
Revises: 0005_channel_external_account
Create Date: 2026-10-28
"""

from alembic import op
import sqlalchemy as sa


revision = "0006_manual_handling_status"
down_revision = "0005_channel_external_account"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "inquiries",
        sa.Column("handling_status", sa.String(length=16), nullable=False, server_default="pending"),
    )
    op.create_index("ix_inquiries_handling_status", "inquiries", ["handling_status"])
    op.create_check_constraint(
        "ck_inquiries_handling_status",
        "inquiries",
        "handling_status IN ('pending', 'processed', 'ignored')",
    )
    op.drop_constraint("ck_inquiry_events_type", "inquiry_events", type_="check")
    op.create_check_constraint(
        "ck_inquiry_events_type",
        "inquiry_events",
        "event_type IN ('inquiry_created', 'inquiry_transferred', 'inquiry_processed', 'inquiry_ignored')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_inquiry_events_type", "inquiry_events", type_="check")
    op.create_check_constraint(
        "ck_inquiry_events_type",
        "inquiry_events",
        "event_type IN ('inquiry_created', 'inquiry_transferred')",
    )
    op.drop_constraint("ck_inquiries_handling_status", "inquiries", type_="check")
    op.drop_index("ix_inquiries_handling_status", table_name="inquiries")
    op.drop_column("inquiries", "handling_status")
