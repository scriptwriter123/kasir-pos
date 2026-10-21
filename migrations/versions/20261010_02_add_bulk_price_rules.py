"""add bulk price rules

Revision ID: 20261010_02
Revises: 20261010_01
Create Date: 2026-10-10 22:35:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20261010_02"
down_revision: Union[str, Sequence[str], None] = "20261010_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "bulk_price_rules",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("quantity_threshold", sa.Integer(), nullable=False),
        sa.Column("discount_percent", sa.Numeric(5, 2), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "quantity_threshold >= 1",
            name="ck_bulk_price_rules_quantity_threshold_positive",
        ),
        sa.CheckConstraint(
            "discount_percent > 0 AND discount_percent <= 100",
            name="ck_bulk_price_rules_discount_percent_range",
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("product_id"),
    )


def downgrade() -> None:
    op.drop_table("bulk_price_rules")
