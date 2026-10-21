"""allow DP (down payment) purchase payment status

Revision ID: 20261017_03
Revises: 20261017_02
Create Date: 2026-10-17 03:05:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20261017_03"
down_revision: Union[str, Sequence[str], None] = "20261017_02"
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
    with op.batch_alter_table("purchase_orders") as batch_op:
        batch_op.drop_constraint(
            "ck_purchase_orders_payment_status",
            type_="check",
        )
        batch_op.drop_constraint(
            "ck_purchase_orders_payment_terms",
            type_="check",
        )
        batch_op.create_check_constraint(
            "ck_purchase_orders_payment_status",
            "payment_status IN ('PAID', 'TEMPO', 'DP')",
        )
        batch_op.create_check_constraint(
            "ck_purchase_orders_payment_terms",
            "(payment_status = 'PAID' AND paid_amount = subtotal) OR "
            "(payment_status = 'TEMPO' AND due_date IS NOT NULL) OR "
            "(payment_status = 'DP' AND paid_amount > 0 "
            "AND paid_amount < subtotal AND due_date IS NOT NULL)",
        )


def downgrade() -> None:
    _disable_sqlite_foreign_keys()
    op.execute(
        "UPDATE purchase_orders SET payment_status = 'TEMPO' "
        "WHERE payment_status = 'DP'"
    )
    with op.batch_alter_table("purchase_orders") as batch_op:
        batch_op.drop_constraint(
            "ck_purchase_orders_payment_terms",
            type_="check",
        )
        batch_op.drop_constraint(
            "ck_purchase_orders_payment_status",
            type_="check",
        )
        batch_op.create_check_constraint(
            "ck_purchase_orders_payment_status",
            "payment_status IN ('PAID', 'TEMPO')",
        )
        batch_op.create_check_constraint(
            "ck_purchase_orders_payment_terms",
            "(payment_status = 'PAID' AND paid_amount = subtotal) OR "
            "(payment_status = 'TEMPO' AND due_date IS NOT NULL)",
        )
