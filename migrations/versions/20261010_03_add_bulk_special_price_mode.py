"""add manual bulk price mode and fixed special price

Revision ID: 20261010_03
Revises: 20261010_02
Create Date: 2026-10-10 22:55:00

"""
from decimal import Decimal, ROUND_HALF_UP
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20261010_03"
down_revision: Union[str, Sequence[str], None] = "20261010_02"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "bulk_price_rules",
        sa.Column("special_price", sa.Integer(), nullable=True),
    )
    op.add_column(
        "bulk_price_rules",
        sa.Column(
            "pricing_mode",
            sa.String(length=10),
            nullable=False,
            server_default="PERCENT",
        ),
    )

    connection = op.get_bind()
    rows = connection.execute(
        sa.text(
            "SELECT bulk_price_rules.id, products.selling_price, "
            "bulk_price_rules.discount_percent "
            "FROM bulk_price_rules "
            "JOIN products ON products.id = bulk_price_rules.product_id"
        )
    )
    for rule_id, selling_price, discount_percent in rows:
        value = Decimal(selling_price) * (
            Decimal("1") - Decimal(discount_percent) / Decimal("100")
        )
        special_price = int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        connection.execute(
            sa.text(
                "UPDATE bulk_price_rules SET special_price = :special_price "
                "WHERE id = :rule_id"
            ),
            {"special_price": special_price, "rule_id": rule_id},
        )

    with op.batch_alter_table("bulk_price_rules") as batch_op:
        batch_op.alter_column(
            "special_price",
            existing_type=sa.Integer(),
            nullable=False,
        )
        batch_op.create_check_constraint(
            "ck_bulk_price_rules_special_price_nonnegative",
            "special_price >= 0",
        )
        batch_op.create_check_constraint(
            "ck_bulk_price_rules_pricing_mode",
            "pricing_mode IN ('PRICE', 'PERCENT')",
        )


def downgrade() -> None:
    with op.batch_alter_table("bulk_price_rules") as batch_op:
        batch_op.drop_constraint(
            "ck_bulk_price_rules_pricing_mode",
            type_="check",
        )
        batch_op.drop_constraint(
            "ck_bulk_price_rules_special_price_nonnegative",
            type_="check",
        )
        batch_op.drop_column("pricing_mode")
        batch_op.drop_column("special_price")
