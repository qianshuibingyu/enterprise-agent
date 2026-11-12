"""Persist whether an assigned customer chain is inquiry or after-sales."""

from alembic import op
import sqlalchemy as sa


revision = "0014_inquiry_business_type"
down_revision = "0013_inquiry_messages"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("inquiries", sa.Column("business_type", sa.String(length=16), nullable=True))
    op.create_index("ix_inquiries_business_type", "inquiries", ["business_type"])
    op.create_check_constraint(
        "ck_inquiries_business_type",
        "inquiries",
        "business_type IS NULL OR business_type IN ('inquiry', 'after_sales')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_inquiries_business_type", "inquiries", type_="check")
    op.drop_index("ix_inquiries_business_type", table_name="inquiries")
    op.drop_column("inquiries", "business_type")
