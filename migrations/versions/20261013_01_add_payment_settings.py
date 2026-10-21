"""add payment settings

Revision ID: 20261013_01
Revises: 20261011_01
Create Date: 2026-10-13 00:10:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20261013_01"
down_revision: Union[str, Sequence[str], None] = "20261011_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "payment_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("cash_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("qris_dana_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("qris_midtrans_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("transfer_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("payment_settings")
