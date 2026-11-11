"""Index the inbox sort and filter paths."""

from alembic import op


revision = "0017_message_feed_indexes"
down_revision = "0016_operation_logs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_messages_handling_occurred_id",
        "messages",
        ["handling_status", "occurred_at", "id"],
    )
    op.create_index(
        "ix_messages_account_handling_occurred_id",
        "messages",
        ["channel_account_id", "handling_status", "occurred_at", "id"],
    )


def downgrade() -> None:
    op.drop_index("ix_messages_account_handling_occurred_id", table_name="messages")
    op.drop_index("ix_messages_handling_occurred_id", table_name="messages")
