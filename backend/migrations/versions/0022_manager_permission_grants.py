"""Add narrowly scoped manager permission grants."""
from alembic import op
import sqlalchemy as sa

revision = "0022_manager_permission_grants"
down_revision = "0021_whatsapp_contact_identity"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.create_table(
        "manager_permission_grants",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("manager_user_id", sa.Integer(), nullable=False),
        sa.Column("target_user_id", sa.Integer(), nullable=False),
        sa.Column("department", sa.String(length=64), nullable=False),
        sa.Column("permission", sa.String(length=64), nullable=False),
        sa.Column("granted_by_user_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["manager_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["target_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["granted_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("manager_user_id", "target_user_id", "department", "permission", name="uq_manager_permission_grant"),
    )
    for name, cols in [("manager_user_id", ["manager_user_id"]), ("target_user_id", ["target_user_id"]), ("department", ["department"]), ("permission", ["permission"])]:
        op.create_index("ix_manager_permission_grants_" + name, "manager_permission_grants", cols)

def downgrade() -> None:
    op.drop_table("manager_permission_grants")
