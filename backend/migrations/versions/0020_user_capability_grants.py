"""Add individually granted capabilities for manager overlays."""

from alembic import op
import sqlalchemy as sa

revision = "0020_user_capability_grants"
down_revision = "0019_phase_one_permissions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_capability_grants",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("capability", sa.String(length=64), nullable=False),
        sa.Column("granted_by_user_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["granted_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "capability", name="uq_user_capability_grant"),
    )
    op.create_index("ix_user_capability_grants_user_id", "user_capability_grants", ["user_id"])
    op.create_index("ix_user_capability_grants_capability", "user_capability_grants", ["capability"])


def downgrade() -> None:
    op.drop_table("user_capability_grants")
