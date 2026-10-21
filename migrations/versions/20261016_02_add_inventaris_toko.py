"""add tabel inventaris_toko (alat & peralatan toko)

Revision ID: 20261016_02
Revises: 20261016_01
Create Date: 2026-10-17 00:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20261016_02"
down_revision: Union[str, Sequence[str], None] = "20261016_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "inventaris_toko",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("kode_inventaris", sa.String(length=50), nullable=False),
        sa.Column("nama_barang", sa.String(length=200), nullable=False),
        sa.Column("jumlah", sa.Integer(), nullable=False),
        sa.Column("satuan", sa.String(length=50), nullable=True),
        sa.Column("tanggal_perolehan", sa.Date(), nullable=True),
        sa.Column("harga_perolehan", sa.Integer(), nullable=False),
        sa.Column("lokasi", sa.String(length=100), nullable=True),
        sa.Column("kondisi", sa.String(length=20), nullable=False),
        sa.Column("keterangan", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_inventaris_toko_kode_inventaris",
        "inventaris_toko",
        ["kode_inventaris"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_inventaris_toko_kode_inventaris", table_name="inventaris_toko"
    )
    op.drop_table("inventaris_toko")
