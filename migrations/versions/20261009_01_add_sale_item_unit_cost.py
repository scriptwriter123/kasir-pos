"""snapshot unit cost for sale items

Revision ID: 20261009_01
Revises: 491571e68f2e
Create Date: 2026-10-09 01:45:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20261009_01"
down_revision: Union[str, Sequence[str], None] = "491571e68f2e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "sale_items",
        sa.Column("unit_cost", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("sale_items", "unit_cost")
