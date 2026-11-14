"""Add the employee display name used by the employee list and inquiry owner.

The console showed "用户 #3" as the inquiry owner because only the assignee id was
exposed. Employees now carry a human name that is shown next to the username, so
existing rows are backfilled with their username to stay readable.
"""

from alembic import op
import sqlalchemy as sa

revision = "0023_users_full_name"
down_revision = "0022_manager_permission_grants"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("full_name", sa.String(length=64), nullable=True))
    op.create_index("ix_users_full_name", "users", ["full_name"])
    op.execute(sa.text("UPDATE users SET full_name = username WHERE full_name IS NULL"))


def downgrade() -> None:
    op.drop_index("ix_users_full_name", table_name="users")
    op.drop_column("users", "full_name")
