"""add cashier daily reports

Revision ID: 20261010_01
Revises: 20261009_04
Create Date: 2026-10-10 18:20:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20261010_01"
down_revision: Union[str, Sequence[str], None] = "20261009_04"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "cashier_daily_reports",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("cashier_id", sa.Integer(), nullable=False),
        sa.Column("report_date", sa.Date(), nullable=False),
        sa.Column("sales_count", sa.Integer(), nullable=False),
        sa.Column("sales_total", sa.Integer(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "sales_count >= 0 AND sales_total >= 0",
            name="ck_cashier_daily_reports_totals_nonnegative",
        ),
        sa.ForeignKeyConstraint(["cashier_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("cashier_id", "report_date"),
    )
    op.create_index(
        op.f("ix_cashier_daily_reports_report_date"),
        "cashier_daily_reports",
        ["report_date"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_cashier_daily_reports_report_date"),
        table_name="cashier_daily_reports",
    )
    op.drop_table("cashier_daily_reports")
