"""add store contact and logo settings

Revision ID: 20261009_02
Revises: 20261009_01
Create Date: 2026-10-09 02:25:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20261009_02"
down_revision: Union[str, Sequence[str], None] = "20261009_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("stores", sa.Column("whatsapp", sa.String(length=30)))
    op.add_column("stores", sa.Column("logo_path", sa.String(length=500)))


def downgrade() -> None:
    op.drop_column("stores", "logo_path")
    op.drop_column("stores", "whatsapp")
