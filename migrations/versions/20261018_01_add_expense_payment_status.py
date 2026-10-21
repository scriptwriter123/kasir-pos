"""add expense payment status (CASH, HUTANG, DP)

Revision ID: 20261018_01
Revises: 20261017_03
Create Date: 2026-10-18 12:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20261018_01"
down_revision: Union[str, Sequence[str], None] = "20261017_03"
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
    with op.batch_alter_table("expenses") as batch_op:
        batch_op.add_column(
            sa.Column(
                "payment_status",
                sa.String(10),
                nullable=False,
                server_default="CASH",
            )
        )
        batch_op.create_check_constraint(
            "ck_expenses_payment_status",
            "payment_status IN ('CASH', 'HUTANG', 'DP')",
        )
    op.execute(
        "UPDATE expenses SET payment_status = CASE "
        "WHEN paid_amount >= amount THEN 'CASH' "
        "WHEN paid_amount <= 0 THEN 'HUTANG' "
        "ELSE 'DP' END"
    )


def downgrade() -> None:
    _disable_sqlite_foreign_keys()
    with op.batch_alter_table("expenses") as batch_op:
        batch_op.drop_constraint(
            "ck_expenses_payment_status",
            type_="check",
        )
        batch_op.drop_column("payment_status")
