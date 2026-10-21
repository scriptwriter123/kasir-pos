"""add payment wizard states

Revision ID: 20261013_02
Revises: 20261013_01
Create Date: 2026-10-13 01:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20261013_02"
down_revision: Union[str, Sequence[str], None] = "20261013_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "payment_wizard_states",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("method", sa.String(length=30), nullable=False, unique=True),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="not_started"),
        sa.Column("payload", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("payment_wizard_states")
