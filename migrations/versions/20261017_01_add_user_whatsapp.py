"""tambah kolom users.whatsapp (No. WA)

Revision ID: 20261017_01
Revises: 20261016_02
Create Date: 2026-10-17 01:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20261017_01"
down_revision: Union[str, Sequence[str], None] = "20261016_02"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("whatsapp", sa.String(length=30), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "whatsapp")
