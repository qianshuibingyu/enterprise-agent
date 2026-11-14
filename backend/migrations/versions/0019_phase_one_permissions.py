"""Add minimal phase-one department and channel permission records."""

from alembic import op
import sqlalchemy as sa

revision = "0019_phase_one_permissions"
down_revision = "0018_whatsapp_group_bindings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("department", sa.String(length=64), nullable=True))
    op.create_index("ix_users_department", "users", ["department"])
    op.add_column("inquiries", sa.Column("department", sa.String(length=64), nullable=True))
    op.create_index("ix_inquiries_department", "inquiries", ["department"])
    op.add_column("channel_accounts", sa.Column("history_access_revoked_at", sa.DateTime(timezone=True), nullable=True))

    op.create_table(
        "user_department_grants",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("department", sa.String(length=64), nullable=False),
        sa.Column("granted_by_user_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["granted_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "department", name="uq_user_department_grant"),
    )
    op.create_index("ix_user_department_grants_user_id", "user_department_grants", ["user_id"])
    op.create_index("ix_user_department_grants_department", "user_department_grants", ["department"])

    op.create_table(
        "user_channel_preauthorizations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("channel_type", sa.String(length=32), nullable=False),
        sa.Column("granted_by_user_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["granted_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "channel_type", name="uq_user_channel_preauthorization"),
    )
    op.create_index("ix_user_channel_preauthorizations_user_id", "user_channel_preauthorizations", ["user_id"])


def downgrade() -> None:
    op.drop_table("user_channel_preauthorizations")
    op.drop_table("user_department_grants")
    op.drop_column("channel_accounts", "history_access_revoked_at")
    op.drop_index("ix_inquiries_department", table_name="inquiries")
    op.drop_column("inquiries", "department")
    op.drop_index("ix_users_department", table_name="users")
    op.drop_column("users", "department")
