"""bulk price rules multi tier (max 3 per produk)

Revision ID: 20261016_01
Revises: 20261013_02
Create Date: 2026-10-16 10:30:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20261016_01"
down_revision: Union[str, Sequence[str], None] = "20261013_02"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "bulk_price_rules_new",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("quantity_threshold", sa.Integer(), nullable=False),
        sa.Column("discount_percent", sa.Numeric(5, 2), nullable=False),
        sa.Column("special_price", sa.Integer(), nullable=False),
        sa.Column("pricing_mode", sa.String(length=10), nullable=False),
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
        sa.CheckConstraint(
            "special_price >= 0",
            name="ck_bulk_price_rules_special_price_nonnegative",
        ),
        sa.CheckConstraint(
            "pricing_mode IN ('PRICE', 'PERCENT')",
            name="ck_bulk_price_rules_pricing_mode",
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "product_id",
            "quantity_threshold",
            name="uq_bulk_price_rules_product_threshold",
        ),
    )
    op.execute(
        "INSERT INTO bulk_price_rules_new ("
        "id, product_id, quantity_threshold, discount_percent, "
        "special_price, pricing_mode, created_at, updated_at"
        ") SELECT "
        "id, product_id, quantity_threshold, discount_percent, "
        "special_price, pricing_mode, created_at, updated_at "
        "FROM bulk_price_rules"
    )
    op.drop_table("bulk_price_rules")
    op.rename_table("bulk_price_rules_new", "bulk_price_rules")


def downgrade() -> None:
    op.create_table(
        "bulk_price_rules_old",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("quantity_threshold", sa.Integer(), nullable=False),
        sa.Column("discount_percent", sa.Numeric(5, 2), nullable=False),
        sa.Column("special_price", sa.Integer(), nullable=False),
        sa.Column("pricing_mode", sa.String(length=10), nullable=False),
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
        sa.CheckConstraint(
            "special_price >= 0",
            name="ck_bulk_price_rules_special_price_nonnegative",
        ),
        sa.CheckConstraint(
            "pricing_mode IN ('PRICE', 'PERCENT')",
            name="ck_bulk_price_rules_pricing_mode",
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("product_id"),
    )
    op.execute(
        "INSERT INTO bulk_price_rules_old ("
        "id, product_id, quantity_threshold, discount_percent, "
        "special_price, pricing_mode, created_at, updated_at"
        ") SELECT "
        "id, product_id, quantity_threshold, discount_percent, "
        "special_price, pricing_mode, created_at, updated_at "
        "FROM bulk_price_rules "
        "WHERE id IN ("
        "  SELECT MIN(id) FROM bulk_price_rules GROUP BY product_id"
        ")"
    )
    op.drop_table("bulk_price_rules")
    op.rename_table("bulk_price_rules_old", "bulk_price_rules")
