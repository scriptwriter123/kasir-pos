from datetime import date, datetime, timezone
from typing import Iterable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.exceptions import (
    AuthorizationError,
    LicenseExpiredError,
    ValidationError,
)
from app.models import (
    Account,
    AuditLog,
    Expense,
    FinancialPayment,
    FinancialSettings,
    JournalEntry,
    JournalLine,
    PurchaseOrder,
    User,
)


ACCOUNT_CODES = {
    "cash": "1000",
    "bank": "1010",
    "inventory": "1200",
    "payables": "2000",
    "owner_equity": "3000",
    "opening_equity": "3100",
    "sales": "4000",
    "cogs": "5000",
}


class FinancialService:
    def __init__(self, session: Session, *, transaction_locked: bool = False):
        self.session = session
        self.transaction_locked = transaction_locked

    def _require_transactions_allowed(self):
        if self.transaction_locked:
            raise LicenseExpiredError(
                "Masa lisensi berakhir; transaksi keuangan baru terkunci."
            )

    def settings(self) -> FinancialSettings | None:
        return self.session.get(FinancialSettings, 1)

    def is_initialized(self) -> bool:
        settings = self.settings()
        return settings is not None and settings.effective_from is not None

    def ensure_auto_initialized(self, actor_id: int | None = None) -> FinancialSettings:
        settings = self.settings()
        if settings is not None and settings.effective_from is not None:
            return settings

        today = date.today()
        if settings is None:
            settings = FinancialSettings(id=1)
            self.session.add(settings)
        settings.effective_from = today
        settings.initialized_by = actor_id
        settings.initialized_at = datetime.now(timezone.utc)
        self.session.flush()
        return settings

    def accounts(self, account_type: str | None = None) -> list[Account]:
        statement = select(Account).where(Account.is_active.is_(True))
        if account_type:
            statement = statement.where(Account.account_type == account_type)
        return list(self.session.scalars(statement.order_by(Account.code)))

    def initialize(
        self,
        actor: User,
        effective_from: date,
        opening_balances: dict[int, int],
    ) -> FinancialSettings:
        self._require_owner(actor)
        self._require_transactions_allowed()
        if effective_from > date.today():
            raise ValidationError("Tanggal mulai pembukuan tidak boleh di masa depan.")
        settings = self.settings()
        if settings is not None and settings.effective_from is not None:
            raise ValidationError("Pembukuan sudah diaktifkan dan tidak dapat diulang.")
        accounts = {
            account.id: account
            for account in self.accounts()
        }
        debit_total = 0
        credit_total = 0
        lines = []
        for account_id, amount in opening_balances.items():
            if amount < 0:
                raise ValidationError("Saldo awal tidak boleh negatif.")
            account = accounts.get(account_id)
            if account is None:
                raise ValidationError("Akun saldo awal tidak valid.")
            if account.account_type not in {"ASSET", "LIABILITY", "EQUITY"}:
                raise ValidationError(
                    "Saldo awal hanya boleh dimasukkan ke akun aset, kewajiban, atau modal."
                )
            if amount == 0:
                continue
            is_debit_normal = account.account_type == "ASSET"
            debit, credit = (
                (amount, 0) if is_debit_normal else (0, amount)
            )
            debit_total += debit
            credit_total += credit
            lines.append((account.id, debit, credit, "Saldo awal"))

        opening_account = self._account_by_code(ACCOUNT_CODES["opening_equity"])
        difference = debit_total - credit_total
        if difference > 0:
            lines.append(
                (opening_account.id, 0, difference, "Saldo awal modal penyeimbang")
            )
        elif difference < 0:
            lines.append(
                (opening_account.id, -difference, 0, "Defisit saldo awal")
            )
        if not any(debit or credit for _account_id, debit, credit, _memo in lines):
            raise ValidationError("Masukkan minimal satu saldo awal selain nol.")

        try:
            if settings is None:
                settings = FinancialSettings(id=1)
                self.session.add(settings)
            if lines:
                self._create_entry(
                    entry_date=effective_from,
                    source_type="OPENING",
                    source_id=1,
                    memo="Saldo awal pembukuan",
                    posted_by=actor.id,
                    lines=lines,
                )
            settings.effective_from = effective_from
            settings.initialized_by = actor.id
            settings.initialized_at = datetime.now(timezone.utc)
            self.session.add(
                AuditLog(
                    user_id=actor.id,
                    action="FINANCIAL_BOOKS_INITIALIZED",
                    entity_type="FinancialSettings",
                    entity_id=1,
                    detail=f"Tanggal mulai pembukuan {effective_from.isoformat()}",
                )
            )
            self.session.flush()
            self.session.commit()
            self.session.refresh(settings)
            return settings
        except Exception:
            self.session.rollback()
            raise

    def require_initialized(self) -> FinancialSettings:
        settings = self.settings()
        if settings is None or settings.effective_from is None:
            raise ValidationError(
                "Pembukuan belum diaktifkan. OWNER harus mengisi Modal lalu "
                "mengaktifkan Laporan Keuangan di tab Modal Awal "
                "(Manajemen Toko) sebelum transaksi dicatat."
            )
        return settings

    def post_sale(
        self,
        actor_id: int,
        sale,
        payments: list[dict],
        items: Iterable,
    ) -> None:
        settings = self.require_initialized()
        entry_date = self._local_date(sale.created_at)
        if entry_date < settings.effective_from:
            raise ValidationError(
                "Tanggal penjualan berada sebelum tanggal aktivasi pembukuan."
            )
        sale_account = self._account_by_code(ACCOUNT_CODES["sales"])
        cogs_account = self._account_by_code(ACCOUNT_CODES["cogs"])
        inventory_account = self._account_by_code(ACCOUNT_CODES["inventory"])
        lines = []
        remaining = int(sale.grand_total)
        for payment in payments:
            amount = min(max(0, int(payment["amount"])), remaining)
            if amount == 0:
                continue
            account = self._payment_account(str(payment["method"]))
            lines.append((account.id, amount, 0, "Penerimaan penjualan"))
            remaining -= amount
        if remaining:
            raise ValidationError("Nilai pembayaran tidak menutup total penjualan.")
        lines.append(
            (sale_account.id, 0, int(sale.grand_total), "Penjualan")
        )

        cost_total = sum(
            int(item.qty) * int(item.unit_cost or 0)
            for item in items
        )
        if any(not item.unit_cost or item.unit_cost <= 0 for item in items):
            raise ValidationError(
                "Harga modal produk belum diisi. Lengkapi harga modal sebelum "
                "transaksi agar laporan HPP akurat."
            )
        if cost_total:
            lines.append((cogs_account.id, cost_total, 0, "Harga pokok penjualan"))
            lines.append(
                (inventory_account.id, 0, cost_total, "Pengurangan persediaan")
            )
        self._create_entry(
            entry_date=entry_date,
            source_type="SALE",
            source_id=sale.id,
            memo=f"Penjualan {sale.invoice_no}",
            posted_by=actor_id,
            lines=lines,
        )

    def post_purchase(
        self,
        actor_id: int,
        purchase: PurchaseOrder,
    ) -> None:
        settings = self.require_initialized()
        entry_date = self._local_date(purchase.ordered_at)
        if entry_date < settings.effective_from:
            raise ValidationError(
                "Tanggal pembelian berada sebelum tanggal aktivasi pembukuan."
            )
        inventory = self._account_by_code(ACCOUNT_CODES["inventory"])
        payables = self._account_by_code(ACCOUNT_CODES["payables"])
        self._create_entry(
            entry_date=entry_date,
            source_type="PURCHASE",
            source_id=purchase.id,
            memo=f"Pembelian {purchase.order_no}",
            posted_by=actor_id,
            lines=[
                (inventory.id, purchase.subtotal, 0, "Persediaan barang"),
                (payables.id, 0, purchase.subtotal, "Hutang supplier"),
            ],
        )
        self.session.add(
            AuditLog(
                user_id=actor_id,
                action="PURCHASE_POSTED",
                entity_type="PurchaseOrder",
                entity_id=purchase.id,
                detail=f"Pembelian {purchase.order_no}; nominal {purchase.subtotal}",
            )
        )

    def create_expense(
        self,
        actor: User,
        *,
        account_id: int,
        amount: int,
        incurred_at: datetime,
        payee: str,
        description: str,
        due_date: date | None,
        initial_payment: int,
        payment_account_id: int | None,
        payment_method: str,
        payment_status: str | None = None,
    ) -> Expense:
        self._require_owner(actor)
        self._require_transactions_allowed()
        settings = self.require_initialized()
        if amount <= 0:
            raise ValidationError("Nominal pengeluaran harus lebih dari Rp 0.")
        if initial_payment < 0 or initial_payment > amount:
            raise ValidationError("Pembayaran awal harus antara Rp 0 dan total tagihan.")
        if payment_status is None:
            payment_status = (
                "CASH"
                if initial_payment == amount
                else "HUTANG"
                if initial_payment == 0
                else "DP"
            )
        elif payment_status not in {"CASH", "HUTANG", "DP"}:
            raise ValidationError(
                "Status pembayaran tidak valid. Pilih Tunai, Hutang, atau DP."
            )
        if payment_status == "CASH" and initial_payment != amount:
            raise ValidationError(
                "Status Tunai berarti lunas; pembayaran awal harus sama "
                "dengan total pengeluaran."
            )
        if payment_status == "HUTANG" and initial_payment != 0:
            raise ValidationError(
                "Status Hutang berarti belum ada pembayaran awal."
            )
        if payment_status == "DP" and not 0 < initial_payment < amount:
            raise ValidationError(
                "Status DP membutuhkan Jumlah DP antara Rp 1 dan di bawah "
                "total pengeluaran."
            )
        if initial_payment < amount and due_date is None:
            raise ValidationError(
                "Tanggal jatuh tempo wajib jika pengeluaran belum lunas."
            )
        account = self.session.get(Account, account_id)
        if account is None or account.account_type != "EXPENSE" or account.code == "5000":
            raise ValidationError("Pilih akun beban operasional yang valid.")
        if initial_payment and payment_account_id is None:
            raise ValidationError("Pilih akun kas atau bank untuk pembayaran.")
        expense_date = self._local_date(incurred_at)
        if expense_date < settings.effective_from:
            raise ValidationError(
                "Tanggal pengeluaran tidak boleh sebelum tanggal aktivasi pembukuan."
            )
        expense = Expense(
            recorded_by=actor.id,
            category=account.name,
            account_id=account.id,
            amount=amount,
            paid_amount=0,
            payment_status=payment_status,
            incurred_at=incurred_at,
            due_date=due_date,
            payee=payee.strip() or None,
            description=description.strip() or None,
        )
        payables = self._account_by_code(ACCOUNT_CODES["payables"])
        try:
            self.session.add(expense)
            self.session.flush()
            self._create_entry(
                entry_date=expense_date,
                source_type="EXPENSE",
                source_id=expense.id,
                memo=f"Pengeluaran: {account.name}",
                posted_by=actor.id,
                lines=[
                    (account.id, amount, 0, description or account.name),
                    (payables.id, 0, amount, "Hutang pengeluaran"),
                ],
            )
            self.session.add(
                AuditLog(
                    user_id=actor.id,
                    action="EXPENSE_RECORDED",
                    entity_type="Expense",
                    entity_id=expense.id,
                    detail=f"Pengeluaran {account.name}; nominal {amount}",
                )
            )
            if initial_payment:
                self._record_document_payment(
                    actor=actor,
                    expense=expense,
                    amount=initial_payment,
                    payment_account_id=payment_account_id,
                    payment_method=payment_method,
                    paid_at=datetime.now(timezone.utc),
                )
            self.session.commit()
            self.session.refresh(expense)
            return expense
        except Exception:
            self.session.rollback()
            raise

    def record_expense_payment(
        self,
        actor: User,
        expense_id: int,
        amount: int,
        payment_account_id: int,
        payment_method: str,
    ) -> Expense:
        self._require_owner(actor)
        self._require_transactions_allowed()
        expense = self.session.get(Expense, expense_id)
        if expense is None:
            raise ValidationError("Pengeluaran tidak ditemukan.")
        try:
            self._record_document_payment(
                actor=actor,
                expense=expense,
                amount=amount,
                payment_account_id=payment_account_id,
                payment_method=payment_method,
                paid_at=datetime.now(timezone.utc),
            )
            self.session.commit()
            self.session.refresh(expense)
            return expense
        except Exception:
            self.session.rollback()
            raise

    def record_purchase_payment(
        self,
        actor: User,
        purchase_id: int,
        amount: int,
        payment_account_id: int,
        payment_method: str,
    ) -> PurchaseOrder:
        self._require_owner(actor)
        self._require_transactions_allowed()
        purchase = self.session.get(PurchaseOrder, purchase_id)
        if purchase is None:
            raise ValidationError("Pembelian supplier tidak ditemukan.")
        try:
            self._record_document_payment(
                actor=actor,
                purchase=purchase,
                amount=amount,
                payment_account_id=payment_account_id,
                payment_method=payment_method,
                paid_at=datetime.now(timezone.utc),
            )
            self.session.commit()
            self.session.refresh(purchase)
            return purchase
        except Exception:
            self.session.rollback()
            raise

    def list_expenses(self, actor: User) -> list[Expense]:
        self._require_owner(actor)
        return list(
            self.session.scalars(
                select(Expense).order_by(
                    Expense.incurred_at.desc(),
                    Expense.id.desc(),
                )
            )
        )

    def financial_report(
        self,
        report_type: str,
        start_date: date,
        end_date: date,
    ) -> dict:
        settings = self.require_initialized()
        if start_date > end_date:
            raise ValidationError("Tanggal awal laporan harus sebelum tanggal akhir.")
        if end_date < settings.effective_from:
            raise ValidationError(
                "Periode laporan berada sebelum tanggal aktivasi pembukuan."
            )
        start_date = max(start_date, settings.effective_from)
        if report_type == "profit_loss":
            return self._profit_loss(start_date, end_date)
        if report_type == "balance_sheet":
            return self._balance_sheet(end_date)
        if report_type == "cash_flow":
            return self._cash_flow(start_date, end_date)
        if report_type == "trial_balance":
            return self._trial_balance(end_date)
        if report_type == "journal":
            return self._journal_report(start_date, end_date)
        raise ValidationError("Jenis laporan keuangan tidak dikenal.")

    def _account_activity(
        self,
        start_date: date | None,
        end_date: date,
    ) -> list[tuple[Account, int, int]]:
        statement = (
            select(
                Account,
                func.coalesce(func.sum(JournalLine.debit), 0),
                func.coalesce(func.sum(JournalLine.credit), 0),
            )
            .join(JournalLine, JournalLine.account_id == Account.id)
            .join(JournalEntry, JournalEntry.id == JournalLine.journal_entry_id)
            .where(JournalEntry.entry_date <= end_date)
            .group_by(Account.id)
            .order_by(Account.code)
        )
        if start_date is not None:
            statement = statement.where(JournalEntry.entry_date >= start_date)
        return list(self.session.execute(statement))

    def _profit_loss(self, start_date: date, end_date: date) -> dict:
        rows = []
        revenue_total = 0
        expense_total = 0
        for account, debit, credit in self._account_activity(start_date, end_date):
            if account.account_type == "REVENUE":
                amount = int(credit) - int(debit)
                revenue_total += amount
            elif account.account_type == "EXPENSE":
                amount = int(debit) - int(credit)
                expense_total += amount
            else:
                continue
            rows.append((account.code, account.name, amount))
        rows.append(("", "Total Pendapatan", revenue_total))
        rows.append(("", "Total Beban", expense_total))
        rows.append(("", "Laba (Rugi) Bersih", revenue_total - expense_total))
        return {
            "title": "Laporan Laba Rugi",
            "headers": ["Kode Akun", "Akun", "Saldo Periode"],
            "rows": rows,
            "summary": (
                f"Pendapatan {revenue_total}; beban {expense_total}; "
                f"laba/rugi bersih {revenue_total - expense_total}."
            ),
            "total_revenue": revenue_total,
            "total_expenses": expense_total,
            "net_income": revenue_total - expense_total,
        }

    def _balance_sheet(self, end_date: date) -> dict:
        activity = self._account_activity(None, end_date)
        rows: list[tuple[str, str, int]] = []
        assets_total = 0
        liabilities_total = 0
        equity_total = 0
        revenue_total = 0
        expenses_total = 0
        for account, debit, credit in activity:
            debit = int(debit)
            credit = int(credit)
            if account.account_type == "ASSET":
                balance = debit - credit
                assets_total += balance
                rows.append((account.code, account.name, balance))
            elif account.account_type == "LIABILITY":
                balance = credit - debit
                liabilities_total += balance
                rows.append((account.code, account.name, balance))
            elif account.account_type == "EQUITY":
                balance = credit - debit
                equity_total += balance
                rows.append((account.code, account.name, balance))
            elif account.account_type == "REVENUE":
                revenue_total += credit - debit
            elif account.account_type == "EXPENSE":
                expenses_total += debit - credit
        retained_income = revenue_total - expenses_total
        equity_total += retained_income
        rows.extend(
            [
                ("", "Laba (Rugi) Berjalan", retained_income),
                ("", "Total Aset", assets_total),
                ("", "Total Kewajiban", liabilities_total),
                ("", "Total Ekuitas termasuk laba berjalan", equity_total),
            ]
        )
        difference = assets_total - liabilities_total - equity_total
        return {
            "title": "Neraca",
            "headers": ["Kode Akun", "Akun", "Saldo"],
            "rows": rows,
            "summary": (
                f"Aset {assets_total}; kewajiban {liabilities_total}; "
                f"ekuitas {equity_total}; selisih neraca {difference}."
            ),
            "assets": assets_total,
            "liabilities": liabilities_total,
            "equity": equity_total,
            "difference": difference,
        }

    def _cash_flow(self, start_date: date, end_date: date) -> dict:
        cash_ids = [
            account.id
            for account in self.accounts("ASSET")
            if account.code in {"1000", "1010"}
        ]
        if not cash_ids:
            raise ValidationError("Akun Kas/Bank belum tersedia.")

        settings = self.require_initialized()
        opening_query = (
            select(
                func.coalesce(func.sum(JournalLine.debit - JournalLine.credit), 0)
            )
            .join(JournalEntry, JournalEntry.id == JournalLine.journal_entry_id)
            .where(
                JournalLine.account_id.in_(cash_ids),
            )
        )
        opening_query = opening_query.where(
            (JournalEntry.entry_date < start_date)
            | (
                (JournalEntry.source_type == "OPENING")
                & (JournalEntry.entry_date == settings.effective_from)
                & (start_date == settings.effective_from)
            )
        )
        opening = self.session.scalar(opening_query)
        cash_lines = list(
            self.session.execute(
                select(
                    JournalEntry.entry_date,
                    JournalEntry.memo,
                    Account.name,
                    JournalLine.debit,
                    JournalLine.credit,
                )
                .join(
                    JournalLine,
                    JournalLine.journal_entry_id == JournalEntry.id,
                )
                .join(Account, Account.id == JournalLine.account_id)
                .where(
                    JournalLine.account_id.in_(cash_ids),
                    JournalEntry.entry_date >= start_date,
                    JournalEntry.entry_date <= end_date,
                    JournalEntry.source_type != "OPENING",
                )
                .order_by(JournalEntry.entry_date, JournalEntry.id, JournalLine.id)
            )
        )
        running = int(opening or 0)
        rows = []
        cash_in = 0
        cash_out = 0
        for entry_date, memo, account_name, debit, credit in cash_lines:
            debit = int(debit)
            credit = int(credit)
            running += debit - credit
            cash_in += debit
            cash_out += credit
            rows.append(
                (
                    entry_date.strftime("%d-%m-%Y"),
                    memo,
                    account_name,
                    debit,
                    credit,
                    running,
                )
            )
        return {
            "title": "Laporan Arus Kas",
            "headers": [
                "Tanggal",
                "Keterangan",
                "Akun Kas/Bank",
                "Kas Masuk",
                "Kas Keluar",
                "Saldo Berjalan",
            ],
            "rows": rows,
            "summary": (
                f"Saldo awal {int(opening or 0)}; kas masuk {cash_in}; "
                f"kas keluar {cash_out}; saldo akhir {running}."
            ),
            "opening_cash": int(opening or 0),
            "cash_in": cash_in,
            "cash_out": cash_out,
            "closing_cash": running,
        }

    def _trial_balance(self, end_date: date) -> dict:
        rows = []
        debit_total = 0
        credit_total = 0
        for account, debit, credit in self._account_activity(None, end_date):
            balance = int(debit) - int(credit)
            debit_balance = max(balance, 0)
            credit_balance = max(-balance, 0)
            debit_total += debit_balance
            credit_total += credit_balance
            rows.append(
                (account.code, account.name, debit_balance, credit_balance)
            )
        rows.append(("", "Total", debit_total, credit_total))
        return {
            "title": "Neraca Saldo",
            "headers": ["Kode Akun", "Akun", "Debit", "Kredit"],
            "rows": rows,
            "summary": (
                f"Total debit {debit_total}; total kredit {credit_total}; "
                f"selisih {debit_total - credit_total}."
            ),
            "debit_total": debit_total,
            "credit_total": credit_total,
        }

    def _journal_report(self, start_date: date, end_date: date) -> dict:
        entries = list(
            self.session.scalars(
                select(JournalEntry)
                .where(
                    JournalEntry.entry_date >= start_date,
                    JournalEntry.entry_date <= end_date,
                )
                .order_by(JournalEntry.entry_date, JournalEntry.id)
            )
        )
        rows = []
        for entry in entries:
            for line in entry.lines:
                rows.append(
                    (
                        entry.entry_date.strftime("%d-%m-%Y"),
                        entry.id,
                        entry.memo,
                        line.account.code,
                        line.account.name,
                        line.debit,
                        line.credit,
                    )
                )
        return {
            "title": "Jurnal Umum",
            "headers": [
                "Tanggal",
                "No. Jurnal",
                "Keterangan",
                "Kode Akun",
                "Akun",
                "Debit",
                "Kredit",
            ],
            "rows": rows,
            "summary": f"{len(entries)} jurnal untuk periode yang dipilih.",
        }

    def _record_document_payment(
        self,
        *,
        actor: User,
        amount: int,
        payment_account_id: int,
        payment_method: str,
        paid_at: datetime,
        purchase: PurchaseOrder | None = None,
        expense: Expense | None = None,
    ) -> FinancialPayment:
        if amount <= 0:
            raise ValidationError("Nominal pembayaran harus lebih dari Rp 0.")
        if (purchase is None) == (expense is None):
            raise ValueError("Pembayaran harus terkait tepat satu dokumen.")
        settings = self.require_initialized()
        if self._local_date(paid_at) < settings.effective_from:
            raise ValidationError(
                "Tanggal pembayaran tidak boleh sebelum tanggal aktivasi pembukuan."
            )
        payable_amount = (
            purchase.subtotal - purchase.paid_amount
            if purchase is not None
            else expense.amount - expense.paid_amount
        )
        if amount > payable_amount:
            raise ValidationError(
                f"Nominal melebihi sisa hutang {payable_amount}."
            )
        payment_account = self.session.get(Account, payment_account_id)
        if (
            payment_account is None
            or payment_account.account_type != "ASSET"
            or payment_account.code not in {"1000", "1010"}
        ):
            raise ValidationError("Pilih akun Kas atau Bank untuk pembayaran.")
        payable_account = self._account_by_code(ACCOUNT_CODES["payables"])
        payment = FinancialPayment(
            purchase_order_id=purchase.id if purchase is not None else None,
            expense_id=expense.id if expense is not None else None,
            account_id=payment_account.id,
            amount=amount,
            payment_method=payment_method,
            paid_at=paid_at,
            created_by=actor.id,
        )
        self.session.add(payment)
        self.session.flush()
        self.session.add(
            AuditLog(
                user_id=actor.id,
                action="FINANCIAL_PAYMENT_RECORDED",
                entity_type="FinancialPayment",
                entity_id=payment.id,
                detail=f"Pembayaran {amount} via {payment_method}",
            )
        )
        if purchase is not None:
            purchase.paid_amount += amount
            if purchase.paid_amount == purchase.subtotal:
                purchase.payment_status = "PAID"
            elif purchase.payment_status != "DP":
                purchase.payment_status = "TEMPO"
            source_type = "PURCHASE_PAYMENT"
            memo = f"Pembayaran {purchase.order_no}"
        else:
            expense.paid_amount += amount
            if expense.paid_amount >= expense.amount:
                expense.payment_status = "CASH"
            source_type = "EXPENSE_PAYMENT"
            memo = f"Pembayaran pengeluaran #{expense.id}"
        self._create_entry(
            entry_date=self._local_date(paid_at),
            source_type=source_type,
            source_id=payment.id,
            memo=memo,
            posted_by=actor.id,
            lines=[
                (payable_account.id, amount, 0, "Pelunasan hutang"),
                (payment_account.id, 0, amount, f"Pembayaran {payment_method}"),
            ],
        )
        return payment

    def _create_entry(
        self,
        *,
        entry_date: date,
        source_type: str,
        source_id: int,
        memo: str,
        posted_by: int,
        lines: list[tuple[int, int, int, str | None]],
    ) -> JournalEntry:
        debit_total = sum(debit for _account, debit, _credit, _memo in lines)
        credit_total = sum(credit for _account, _debit, credit, _memo in lines)
        if debit_total <= 0 or debit_total != credit_total:
            raise ValidationError("Jurnal tidak seimbang; transaksi tidak dapat dibukukan.")
        entry = JournalEntry(
            entry_date=entry_date,
            source_type=source_type,
            source_id=source_id,
            memo=memo,
            posted_by=posted_by,
        )
        self.session.add(entry)
        self.session.flush()
        self.session.add_all(
            [
                JournalLine(
                    journal_entry_id=entry.id,
                    account_id=account_id,
                    debit=debit,
                    credit=credit,
                    description=description,
                )
                for account_id, debit, credit, description in lines
                if debit or credit
            ]
        )
        return entry

    def _account_by_code(self, code: str) -> Account:
        account = self.session.scalar(select(Account).where(Account.code == code))
        if account is None:
            raise ValidationError(f"Akun wajib {code} tidak ditemukan.")
        return account

    def _payment_account(self, method: str) -> Account:
        if method == "CASH":
            code = ACCOUNT_CODES["cash"]
        elif method in {"BANK", "QRIS", "EWALLET"}:
            code = ACCOUNT_CODES["bank"]
        else:
            raise ValidationError(f"Metode pembayaran tidak dikenal: {method}.")
        return self._account_by_code(code)

    @staticmethod
    def _local_date(value: datetime | None) -> date:
        if value is None:
            return datetime.now().astimezone().date()
        if value.tzinfo is None:
            value = value.astimezone()
        return value.astimezone().date()

    @staticmethod
    def _require_owner(actor: User):
        if actor.role.name.upper() != "OWNER":
            raise AuthorizationError("Hanya OWNER yang dapat mengelola keuangan.")
