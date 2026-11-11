"""Persist concise user-visible operation history."""

from alembic import op
import sqlalchemy as sa


revision = "0016_operation_logs"
down_revision = "0015_website_form_messages"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "operation_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("actor_user_id", sa.Integer(), nullable=False),
        sa.Column("actor_name", sa.String(length=64), nullable=False),
        sa.Column("operation_name", sa.String(length=64), nullable=False),
        sa.Column("object_type", sa.String(length=32), nullable=False),
        sa.Column("object_id", sa.Integer(), nullable=True),
        sa.Column("result", sa.String(length=16), nullable=False),
        sa.Column("detail", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.CheckConstraint("result IN ('success', 'failure', 'timeout')", name="ck_operation_logs_result"),
    )
    op.create_index("ix_operation_logs_actor_user_id", "operation_logs", ["actor_user_id"])
    op.create_index("ix_operation_logs_operation_name", "operation_logs", ["operation_name"])
    op.create_index("ix_operation_logs_result", "operation_logs", ["result"])
    op.create_index("ix_operation_logs_created_at", "operation_logs", ["created_at"])
    op.create_index("ix_operation_logs_actor_created", "operation_logs", ["actor_user_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_operation_logs_actor_created", table_name="operation_logs")
    op.drop_index("ix_operation_logs_created_at", table_name="operation_logs")
    op.drop_index("ix_operation_logs_result", table_name="operation_logs")
    op.drop_index("ix_operation_logs_operation_name", table_name="operation_logs")
    op.drop_index("ix_operation_logs_actor_user_id", table_name="operation_logs")
    op.drop_table("operation_logs")
