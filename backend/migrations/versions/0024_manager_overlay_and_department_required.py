"""Add the per-user manager overlay and normalize legacy manager roles.

Department backfill and non-null enforcement are handled separately by 0025.
"""

from alembic import op
import sqlalchemy as sa

revision = "0024_manager_overlay_department"
down_revision = "0023_users_full_name"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("manager_overlay_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.execute(sa.text("UPDATE users SET manager_overlay_enabled = TRUE WHERE role = 'manager'"))
    op.execute(sa.text("UPDATE users SET role = 'operations' WHERE role = 'manager'"))


def downgrade() -> None:
    op.execute(sa.text("UPDATE users SET role = 'manager' WHERE manager_overlay_enabled = TRUE"))
    op.drop_column("users", "manager_overlay_enabled")
