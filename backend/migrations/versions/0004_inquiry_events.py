"""Add the minimal inquiry timeline event model.

Revision ID: 0004_inquiry_events
Revises: 0003_messages
Create Date: 2026-10-27
"""

from alembic import op
import sqlalchemy as sa


revision = "0004_inquiry_events"
down_revision = "0003_messages"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "inquiry_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("inquiry_id", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("actor_user_id", sa.Integer(), nullable=True),
        sa.Column("from_status", sa.String(length=16), nullable=True),
        sa.Column("to_status", sa.String(length=16), nullable=True),
        sa.Column("target_user_id", sa.Integer(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "event_type IN ('inquiry_created', 'inquiry_transferred')",
            name="ck_inquiry_events_type",
        ),
        sa.ForeignKeyConstraint(["inquiry_id"], ["inquiries.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["target_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_inquiry_events_inquiry_id", "inquiry_events", ["inquiry_id"])
    op.create_index("ix_inquiry_events_event_type", "inquiry_events", ["event_type"])
    op.create_index("ix_inquiry_events_actor_user_id", "inquiry_events", ["actor_user_id"])
    op.create_index("ix_inquiry_events_target_user_id", "inquiry_events", ["target_user_id"])
    op.create_index(
        "ix_inquiry_events_timeline",
        "inquiry_events",
        ["inquiry_id", "occurred_at", "id"],
    )


def downgrade() -> None:
    op.drop_index("ix_inquiry_events_timeline", table_name="inquiry_events")
    op.drop_index("ix_inquiry_events_target_user_id", table_name="inquiry_events")
    op.drop_index("ix_inquiry_events_actor_user_id", table_name="inquiry_events")
    op.drop_index("ix_inquiry_events_event_type", table_name="inquiry_events")
    op.drop_index("ix_inquiry_events_inquiry_id", table_name="inquiry_events")
    op.drop_table("inquiry_events")
