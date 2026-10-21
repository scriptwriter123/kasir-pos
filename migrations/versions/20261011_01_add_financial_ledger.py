"""add double-entry financial ledger

Revision ID: 20261011_01
Revises: 20261010_03
Create Date: 2026-10-11 00:15:00

"""
from datetime import datetime, timezone
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20261011_01"
down_revision: Union[str, Sequence[str], None] = "20261010_03"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


DEFAULT_ACCOUNTS = (
    ("1000", "Kas", "ASSET", True),
    ("1010", "Bank", "ASSET", True),
    ("1200", "Persediaan Barang", "ASSET", True),
    ("2000", "Hutang Usaha", "LIABILITY", True),
    ("3000", "Modal Pemilik", "EQUITY", True),
    ("3100", "Saldo Awal", "EQUITY", True),
    ("4000", "Penjualan", "REVENUE", True),
    ("5000", "Harga Pokok Penjualan", "EXPENSE", True),
    ("6000", "Beban Operasional", "EXPENSE", False),
    ("6100", "Beban Sewa", "EXPENSE", False),
    ("6200", "Beban Listrik dan Air", "EXPENSE", False),
    ("6300", "Beban Internet dan Telepon", "EXPENSE", False),
    ("6400", "Beban Gaji", "EXPENSE", False),
    ("6500", "Beban Transportasi", "EXPENSE", False),
    ("6600", "Beban Perlengkapan", "EXPENSE", False),
    ("6700", "Beban Perbaikan dan Perawatan", "EXPENSE", False),
    ("6800", "Beban Bank dan Administrasi", "EXPENSE", False),
    ("6900", "Beban Lain-lain", "EXPENSE", False),
)


def upgrade() -> None:
    op.create_table(
        "accounts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=20), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("account_type", sa.String(length=20), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("is_system", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "account_type IN ('ASSET', 'LIABILITY', 'EQUITY', 'REVENUE', 'EXPENSE')",
            name="ck_accounts_account_type",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code"),
    )
    now = datetime.now(timezone.utc)
    op.bulk_insert(
        sa.table(
            "accounts",
            sa.column("code", sa.String()),
            sa.column("name", sa.String()),
            sa.column("account_type", sa.String()),
            sa.column("is_active", sa.Boolean()),
            sa.column("is_system", sa.Boolean()),
            sa.column("created_at", sa.DateTime()),
            sa.column("updated_at", sa.DateTime()),
        ),
        [
            {
                "code": code,
                "name": name,
                "account_type": account_type,
                "is_active": True,
                "is_system": is_system,
                "created_at": now,
                "updated_at": now,
            }
            for code, name, account_type, is_system in DEFAULT_ACCOUNTS
        ],
    )

    op.create_table(
        "financial_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=True),
        sa.Column("initialized_by", sa.Integer(), nullable=True),
        sa.Column("initialized_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["initialized_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.bulk_insert(
        sa.table(
            "financial_settings",
            sa.column("id", sa.Integer()),
            sa.column("effective_from", sa.Date()),
            sa.column("initialized_by", sa.Integer()),
            sa.column("initialized_at", sa.DateTime()),
            sa.column("created_at", sa.DateTime()),
            sa.column("updated_at", sa.DateTime()),
        ),
        [
            {
                "id": 1,
                "effective_from": None,
                "initialized_by": None,
                "initialized_at": None,
                "created_at": now,
                "updated_at": now,
            }
        ],
    )

    op.create_table(
        "journal_entries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("entry_date", sa.Date(), nullable=False),
        sa.Column("source_type", sa.String(length=30), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("memo", sa.String(length=250), nullable=False),
        sa.Column("posted_by", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["posted_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_type",
            "source_id",
            name="uq_journal_entries_source",
        ),
    )
    op.create_index(
        "ix_journal_entries_entry_date",
        "journal_entries",
        ["entry_date"],
    )
    op.create_table(
        "journal_lines",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("journal_entry_id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("debit", sa.Integer(), nullable=False),
        sa.Column("credit", sa.Integer(), nullable=False),
        sa.Column("description", sa.String(length=250), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "(debit > 0 AND credit = 0) OR (credit > 0 AND debit = 0)",
            name="ck_journal_lines_one_sided_amount",
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["accounts.id"],
        ),
        sa.ForeignKeyConstraint(
            ["journal_entry_id"],
            ["journal_entries.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_journal_lines_journal_entry_id",
        "journal_lines",
        ["journal_entry_id"],
    )

    with op.batch_alter_table("expenses") as batch_op:
        batch_op.add_column(
            sa.Column(
                "paid_amount",
                sa.Integer(),
                nullable=False,
                server_default="0",
            )
        )
        batch_op.add_column(sa.Column("due_date", sa.Date(), nullable=True))
        batch_op.add_column(sa.Column("payee", sa.String(length=150), nullable=True))
        batch_op.add_column(sa.Column("account_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_expenses_account_id_accounts",
            "accounts",
            ["account_id"],
            ["id"],
        )
        batch_op.create_check_constraint(
            "ck_expenses_paid_amount_range",
            "paid_amount >= 0 AND paid_amount <= amount",
        )

    op.create_table(
        "financial_payments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("purchase_order_id", sa.Integer(), nullable=True),
        sa.Column("expense_id", sa.Integer(), nullable=True),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("payment_method", sa.String(length=30), nullable=False),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "amount > 0",
            name="ck_financial_payments_amount_positive",
        ),
        sa.CheckConstraint(
            "(purchase_order_id IS NOT NULL AND expense_id IS NULL) OR "
            "(purchase_order_id IS NULL AND expense_id IS NOT NULL)",
            name="ck_financial_payments_single_document",
        ),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["expense_id"], ["expenses.id"]),
        sa.ForeignKeyConstraint(
            ["purchase_order_id"],
            ["purchase_orders.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_financial_payments_purchase_order_id",
        "financial_payments",
        ["purchase_order_id"],
    )
    op.create_index(
        "ix_financial_payments_expense_id",
        "financial_payments",
        ["expense_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_financial_payments_expense_id",
        table_name="financial_payments",
    )
    op.drop_index(
        "ix_financial_payments_purchase_order_id",
        table_name="financial_payments",
    )
    op.drop_table("financial_payments")
    with op.batch_alter_table("expenses") as batch_op:
        batch_op.drop_constraint(
            "ck_expenses_paid_amount_range",
            type_="check",
        )
        batch_op.drop_constraint(
            "fk_expenses_account_id_accounts",
            type_="foreignkey",
        )
        batch_op.drop_column("account_id")
        batch_op.drop_column("payee")
        batch_op.drop_column("due_date")
        batch_op.drop_column("paid_amount")
    op.drop_index("ix_journal_lines_journal_entry_id", table_name="journal_lines")
    op.drop_table("journal_lines")
    op.drop_index("ix_journal_entries_entry_date", table_name="journal_entries")
    op.drop_table("journal_entries")
    op.drop_table("financial_settings")
    op.drop_table("accounts")
