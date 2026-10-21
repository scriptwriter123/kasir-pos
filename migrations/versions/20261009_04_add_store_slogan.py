"""add store slogan

Revision ID: 20261009_04
Revises: 20261009_03
Create Date: 2026-10-09 23:40:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20261009_04"
down_revision: Union[str, Sequence[str], None] = "20261009_03"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("stores", sa.Column("slogan", sa.String(length=200)))


def downgrade() -> None:
    op.drop_column("stores", "slogan")
