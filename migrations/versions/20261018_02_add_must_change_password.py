"""add must_change_password to users

Revision ID: 20261018_02
Revises: 20261018_01
Create Date: 2026-10-18 12:30:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20261018_02"
down_revision: Union[str, Sequence[str], None] = "20261018_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _disable_sqlite_foreign_keys() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "sqlite":
        return

    bind.exec_driver_sql("PRAGMA foreign_keys=OFF")
    if bind.exec_driver_sql("PRAGMA foreign_keys").scalar():
        raise RuntimeError(
            "Could not disable SQLite foreign keys for this migration"
        )


def upgrade() -> None:
    _disable_sqlite_foreign_keys()
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(
            sa.Column(
                "must_change_password",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )


def downgrade() -> None:
    _disable_sqlite_foreign_keys()
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("must_change_password")
