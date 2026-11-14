"""Require a non-empty department identity for every account.

Legacy accounts without a department are assigned to the explicit
"unassigned" bucket, which grants no implied department-specific access.
"""

from alembic import op
import sqlalchemy as sa

revision = "0025_department_identity"
down_revision = "0024_manager_overlay_department"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE users SET department = 'unassigned' "
            "WHERE department IS NULL OR trim(department) = ''"
        )
    )
    with op.batch_alter_table("users") as batch_op:
        batch_op.alter_column(
            "department",
            existing_type=sa.String(length=64),
            nullable=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.alter_column(
            "department",
            existing_type=sa.String(length=64),
            nullable=True,
        )
