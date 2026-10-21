"""add tabel login_history (riwayat login — sumber absensi)

Revision ID: 20261017_02
Revises: 20261017_01
Create Date: 2026-10-17 01:30:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20261017_02"
down_revision: Union[str, Sequence[str], None] = "20261017_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "login_history",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("login_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_login_history_user_id", "login_history", ["user_id"], unique=False
    )
    op.create_index(
        "ix_login_history_login_at", "login_history", ["login_at"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_login_history_login_at", table_name="login_history")
    op.drop_index("ix_login_history_user_id", table_name="login_history")
    op.drop_table("login_history")
