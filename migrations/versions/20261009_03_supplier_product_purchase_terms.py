"""add preferred product supplier and purchase payment terms

Revision ID: 20261009_03
Revises: 20261009_02
Create Date: 2026-10-09 03:20:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20261009_03"
down_revision: Union[str, Sequence[str], None] = "20261009_02"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _disable_sqlite_foreign_keys() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "sqlite":
        return

    bind.exec_driver_sql("PRAGMA foreign_keys=OFF")
    if bind.exec_driver_sql("PRAGMA foreign_keys").scalar():
        raise RuntimeError("Could not disable SQLite foreign keys for this migration")


def upgrade() -> None:
    _disable_sqlite_foreign_keys()
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    product_columns = {
        column["name"] for column in inspector.get_columns("products")
    }
    product_foreign_keys = inspector.get_foreign_keys("products")
    has_supplier_foreign_key = any(
        foreign_key["referred_table"] == "suppliers"
        and foreign_key["constrained_columns"] == ["supplier_id"]
        for foreign_key in product_foreign_keys
    )
    with op.batch_alter_table("products") as batch_op:
        if "supplier_id" not in product_columns:
            batch_op.add_column(
                sa.Column("supplier_id", sa.Integer(), nullable=True)
            )
        if not has_supplier_foreign_key:
            batch_op.create_foreign_key(
                "fk_products_supplier_id_suppliers",
                "suppliers",
                ["supplier_id"],
                ["id"],
            )

    purchase_order_columns = {
        column["name"]: column
        for column in inspector.get_columns("purchase_orders")
    }
    newly_added_columns = set()
    if "payment_status" not in purchase_order_columns:
        op.add_column(
            "purchase_orders",
            sa.Column(
                "payment_status",
                sa.String(length=20),
                nullable=False,
                server_default="PAID",
            ),
        )
        newly_added_columns.add("payment_status")
    if "due_date" not in purchase_order_columns:
        op.add_column(
            "purchase_orders",
            sa.Column("due_date", sa.DateTime(timezone=True)),
        )
        newly_added_columns.add("due_date")
    if "paid_amount" not in purchase_order_columns:
        op.add_column(
            "purchase_orders",
            sa.Column(
                "paid_amount",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
        )
        newly_added_columns.add("paid_amount")
    op.execute("UPDATE purchase_orders SET paid_amount = subtotal")

    check_constraints = {
        constraint["name"]
        for constraint in inspector.get_check_constraints("purchase_orders")
    }
    with op.batch_alter_table("purchase_orders") as batch_op:
        if "ck_purchase_orders_payment_status" not in check_constraints:
            batch_op.create_check_constraint(
                "ck_purchase_orders_payment_status",
                "payment_status IN ('PAID', 'TEMPO')",
            )
        if "ck_purchase_orders_paid_amount" not in check_constraints:
            batch_op.create_check_constraint(
                "ck_purchase_orders_paid_amount",
                "paid_amount >= 0 AND paid_amount <= subtotal",
            )
        if "ck_purchase_orders_payment_terms" not in check_constraints:
            batch_op.create_check_constraint(
                "ck_purchase_orders_payment_terms",
                "(payment_status = 'PAID' AND paid_amount = subtotal) OR "
                "(payment_status = 'TEMPO' AND due_date IS NOT NULL)",
            )
        if (
            "payment_status" in newly_added_columns
            or purchase_order_columns.get("payment_status", {}).get("default") is not None
        ):
            batch_op.alter_column("payment_status", server_default=None)
        if (
            "paid_amount" in newly_added_columns
            or purchase_order_columns.get("paid_amount", {}).get("default") is not None
        ):
            batch_op.alter_column("paid_amount", server_default=None)


def downgrade() -> None:
    _disable_sqlite_foreign_keys()
    with op.batch_alter_table("purchase_orders") as batch_op:
        batch_op.drop_constraint(
            "ck_purchase_orders_payment_terms",
            type_="check",
        )
        batch_op.drop_constraint(
            "ck_purchase_orders_paid_amount",
            type_="check",
        )
        batch_op.drop_constraint(
            "ck_purchase_orders_payment_status",
            type_="check",
        )
        batch_op.drop_column("paid_amount")
        batch_op.drop_column("due_date")
        batch_op.drop_column("payment_status")

    with op.batch_alter_table("products") as batch_op:
        batch_op.drop_constraint(
            "fk_products_supplier_id_suppliers",
            type_="foreignkey",
        )
        batch_op.drop_column("supplier_id")
