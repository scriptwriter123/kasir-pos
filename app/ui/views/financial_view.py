from datetime import date, datetime

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy.exc import SQLAlchemyError

from app.core.exceptions import (
    AuthorizationError,
    LicenseExpiredError,
    ValidationError,
)
from app.models import Expense
from app.services.financial_service import ACCOUNT_CODES, FinancialService
from app.ui.widgets import TableSearchBar, attach_status_focus_hint
from app.utils.formatters import rupiah

_STATUS_STYLES = {
    "ok": (
        "color: #86efac; background: #12291b; padding: 8px; "
        "border-radius: 6px;"
    ),
    "warn": (
        "color: #fdba74; background: #3a2410; padding: 8px; "
        "border-radius: 6px;"
    ),
    "error": (
        "color: #fecaca; background: #3f1d1d; padding: 8px; "
        "border-radius: 6px;"
    ),
    "muted": "color: #a1a1aa; padding: 4px;",
}


def _money_input() -> QDoubleSpinBox:
    field = QDoubleSpinBox()
    field.setDecimals(0)
    field.setRange(0, 2_000_000_000)
    field.setGroupSeparatorShown(True)
    field.setSingleStep(10_000)
    return field


class FinancialView(QWidget):
    """Tab "Modal Awal": input saldo Modal + aktivasi Laporan Keuangan.

    Laporan Keuangan adalah fitur premium (versi berbayar dan masa
    trial). Pengguna mengisi nilai Modal lalu mencentang checkbox
    "Aktifkan Laporan Keuangan"; pembukuan diaktifkan dengan saldo
    awal akun Modal per hari ini.
    """

    books_activated = Signal()

    def __init__(
        self,
        actor,
        session,
        parent=None,
        *,
        read_only: bool = False,
    ):
        super().__init__(parent)
        self.actor = actor
        self.session = session
        self.read_only = bool(read_only)
        self.service = FinancialService(
            session,
            transaction_locked=self.read_only,
        )
        self._modal_account = next(
            (
                account
                for account in self.service.accounts("EQUITY")
                if account.code == ACCOUNT_CODES["owner_equity"]
            ),
            None,
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(32, 26, 32, 30)
        root.setSpacing(14)

        if self.read_only:
            banner = QLabel(
                "MODE BACA-SAJA — aktivasi Laporan Keuangan terkunci karena "
                "masa lisensi berakhir."
            )
            banner.setStyleSheet(
                "color: #fef3c7; background: #78350f; border-radius: 8px; "
                "padding: 9px 12px; font-weight: 600;"
            )
            banner.setWordWrap(True)
            root.addWidget(banner)

        self.setup_status = QLabel()
        self.setup_status.setWordWrap(True)
        self.setup_status.setStyleSheet(_STATUS_STYLES["warn"])
        root.addWidget(self.setup_status)

        modal_row = QHBoxLayout()
        modal_row.setSpacing(12)
        modal_label = QLabel("Modal")
        modal_label.setStyleSheet("font-weight: 600; color: #ffffff;")
        self.modal_input = _money_input()
        self.modal_input.setPrefix("Rp ")
        self.modal_input.setMinimumWidth(240)
        modal_row.addWidget(modal_label)
        modal_row.addWidget(self.modal_input)
        modal_row.addStretch(1)
        root.addLayout(modal_row)

        self.activate_checkbox = QCheckBox("Aktifkan Laporan Keuangan")
        self.activate_checkbox.setStyleSheet(
            "font-weight: 600; color: #ffffff;"
        )
        root.addWidget(self.activate_checkbox)

        hint = QLabel(
            "Fitur premium untuk versi berbayar dan masa trial. Centang "
            "setelah nilai Modal diisi; pembukuan diaktifkan dengan saldo "
            "awal per hari ini dan tidak dapat diulang."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #a1a1aa;")
        root.addWidget(hint)
        root.addStretch(1)

        self.activate_checkbox.toggled.connect(self._on_activation_toggled)
        self.modal_input.valueChanged.connect(lambda _value: self.refresh_view())
        self.refresh_view()

    def refresh_view(self):
        try:
            initialized = self.service.is_initialized()
            if initialized:
                settings = self.service.settings()
                self.setup_status.setStyleSheet(_STATUS_STYLES["ok"])
                self.setup_status.setText(
                    "Laporan Keuangan aktif sejak "
                    f"{settings.effective_from.strftime('%d-%m-%Y')}. "
                    "Pembukuan siap digunakan untuk operasional toko."
                )
            else:
                self.setup_status.setStyleSheet(_STATUS_STYLES["warn"])
                self.setup_status.setText(
                    "Laporan Keuangan belum aktif. Isi nilai Modal lalu "
                    "centang Aktifkan Laporan Keuangan."
                )
            if initialized:
                self._set_checkbox(True)
            self.modal_input.setEnabled(not initialized and not self.read_only)
            self.activate_checkbox.setEnabled(
                not initialized
                and not self.read_only
                and self.modal_input.value() > 0
            )
        except (AuthorizationError, SQLAlchemyError) as exc:
            QMessageBox.warning(self, "Data keuangan gagal dimuat", str(exc))

    def _on_activation_toggled(self, checked: bool):
        if not checked or self.service.is_initialized():
            return
        amount = int(self.modal_input.value())
        if amount <= 0:
            QMessageBox.warning(
                self,
                "Modal belum diisi",
                "Masukkan nilai Modal sebelum mengaktifkan Laporan Keuangan.",
            )
            self._set_checkbox(False)
            return
        if self._modal_account is None:
            QMessageBox.warning(
                self,
                "Akun Modal tidak tersedia",
                "Akun Modal (3000) belum ada di daftar akun. Ulangi "
                "proses setup awal toko.",
            )
            self._set_checkbox(False)
            return
        try:
            self.service.initialize(
                self.actor,
                date.today(),
                {self._modal_account.id: amount},
            )
        except (
            AuthorizationError,
            LicenseExpiredError,
            ValidationError,
            SQLAlchemyError,
        ) as exc:
            QMessageBox.warning(
                self, "Laporan Keuangan gagal diaktifkan", str(exc)
            )
            self._set_checkbox(False)
            return
        QMessageBox.information(
            self,
            "Laporan Keuangan diaktifkan",
            f"Modal {rupiah(amount)} dicatat sebagai saldo awal per "
            f"{date.today():%d-%m-%Y}.",
        )
        self.refresh_view()
        self.books_activated.emit()

    def _set_checkbox(self, checked: bool):
        self.activate_checkbox.blockSignals(True)
        self.activate_checkbox.setChecked(checked)
        self.activate_checkbox.blockSignals(False)


class ExpenseEntryView(QWidget):
    """Tab "Catat Pengeluaran": form pencatatan pengeluaran operasional."""

    def __init__(
        self,
        actor,
        service: FinancialService,
        parent=None,
        *,
        read_only: bool = False,
    ):
        super().__init__(parent)
        self.actor = actor
        self.service = service
        self.read_only = bool(read_only)

        root = QVBoxLayout(self)
        root.setContentsMargins(32, 26, 32, 30)
        root.setSpacing(12)

        if self.read_only:
            banner = QLabel(
                "MODE BACA-SAJA — pencatatan pengeluaran terkunci karena "
                "masa lisensi berakhir."
            )
            banner.setStyleSheet(
                "color: #fef3c7; background: #78350f; border-radius: 8px; "
                "padding: 9px 12px; font-weight: 600;"
            )
            banner.setWordWrap(True)
            root.addWidget(banner)

        description = QLabel(
            "Catat pengeluaran operasional toko (sewa, listrik, gaji, "
            "dll). Pengeluaran dibukukan pada tanggal pengeluaran; sisa "
            "yang belum dibayar menjadi hutang dan dibayar lewat tab "
            "Bayar Pengeluaran."
        )
        description.setWordWrap(True)
        description.setStyleSheet("color: #a1a1aa;")
        root.addWidget(description)

        form = QFormLayout()
        form.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow
        )
        self.account_input = QComboBox()
        self.accounts = [
            account
            for account in service.accounts("EXPENSE")
            if account.code != "5000"
        ]
        for account in self.accounts:
            self.account_input.addItem(
                f"{account.code} · {account.name}",
                account.id,
            )
        self.amount_input = _money_input()
        self.incurred_date_input = QDateEdit()
        self.incurred_date_input.setCalendarPopup(True)
        self.incurred_date_input.setDisplayFormat("dd MMMM yyyy")
        self.incurred_date_input.setDate(date.today())
        self.payee_input = QLineEdit()
        self.payee_input.setPlaceholderText("Nama penerima/vendor")
        self.memo_input = QTextEdit()
        self.memo_input.setMaximumHeight(72)
        self.status_input = QComboBox()
        self.status_input.addItem("Tunai", "CASH")
        self.status_input.addItem("Hutang", "HUTANG")
        self.status_input.addItem("DP", "DP")
        self.due_date_input = QDateEdit()
        self.due_date_input.setCalendarPopup(True)
        self.due_date_input.setDisplayFormat("dd MMMM yyyy")
        self.due_date_input.setDate(date.today())
        self.payment_account_input = QComboBox()
        self.cash_accounts = [
            account
            for account in service.accounts("ASSET")
            if account.code in {"1000", "1010"}
        ]
        for account in self.cash_accounts:
            self.payment_account_input.addItem(account.name, account.id)
        self.dp_amount_input = _money_input()
        self.dp_amount_input.setValue(0)

        form.addRow("Kategori beban *", self.account_input)
        form.addRow("Tanggal pengeluaran *", self.incurred_date_input)
        form.addRow("Penerima / vendor", self.payee_input)
        form.addRow("Keterangan", self.memo_input)
        form.addRow("Total pengeluaran (Rp) *", self.amount_input)
        form.addRow("Status Pembayaran *", self.status_input)
        form.addRow("Jumlah DP (Rp)", self.dp_amount_input)
        form.addRow("Tanggal jatuh tempo", self.due_date_input)
        form.addRow("Bayar dari akun", self.payment_account_input)
        self.form = form
        root.addLayout(form)

        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet(_STATUS_STYLES["muted"])
        root.addWidget(self.status_label)

        actions = QHBoxLayout()
        actions.addStretch(1)
        self.save_button = QPushButton("Simpan Pengeluaran")
        self.save_button.clicked.connect(self._save_expense)
        self.clear_button = QPushButton("Kosongkan")
        self.clear_button.clicked.connect(self._reset_form)
        actions.addWidget(self.save_button)
        actions.addWidget(self.clear_button)
        root.addLayout(actions)
        root.addStretch(1)

        self._inputs = [
            self.account_input,
            self.amount_input,
            self.incurred_date_input,
            self.payee_input,
            self.memo_input,
            self.status_input,
            self.due_date_input,
            self.payment_account_input,
            self.dp_amount_input,
        ]
        self.status_input.currentIndexChanged.connect(self._on_status_changed)
        self.refresh_view()

    def _on_status_changed(self, *_args):
        enabled = not self.read_only and self.service.is_initialized()
        status = self.status_input.currentData()
        tunai_selected = status == "CASH"
        dp_selected = status == "DP"
        self.due_date_input.setEnabled(enabled and not tunai_selected)
        self.payment_account_input.setEnabled(enabled and not tunai_selected)
        self.form.setRowVisible(self.dp_amount_input, dp_selected)
        self.dp_amount_input.setEnabled(enabled and dp_selected)

    def refresh_view(self):
        try:
            if self.read_only:
                enabled = False
                self.status_label.setStyleSheet(_STATUS_STYLES["warn"])
                self.status_label.setText(
                    "MODE BACA-SAJA — pencatatan pengeluaran terkunci."
                )
            else:
                enabled = self.service.is_initialized()
                if enabled:
                    self.status_label.setStyleSheet(_STATUS_STYLES["muted"])
                    self.status_label.setText("")
                else:
                    self.status_label.setStyleSheet(_STATUS_STYLES["warn"])
                    self.status_label.setText(
                        "Laporan Keuangan belum aktif. Aktifkan dulu di "
                        "tab Modal Awal."
                    )
            for widget in self._inputs:
                widget.setEnabled(enabled)
            self.save_button.setEnabled(enabled)
            self.clear_button.setEnabled(enabled)
            self._on_status_changed()
        except (AuthorizationError, SQLAlchemyError) as exc:
            QMessageBox.warning(self, "Data keuangan gagal dimuat", str(exc))

    def _save_expense(self):
        status = self.status_input.currentData()
        total = int(self.amount_input.value())
        if status == "CASH":
            initial_payment = total
        elif status == "DP":
            initial_payment = int(self.dp_amount_input.value())
        else:
            initial_payment = 0
        account_id = (
            self.payment_account_input.currentData()
            if initial_payment
            else None
        )
        account = next(
            (item for item in self.cash_accounts if item.id == account_id),
            None,
        )
        payment_method = (
            "CASH" if account is None or account.code == "1000" else "BANK"
        )
        try:
            self.service.create_expense(
                self.actor,
                account_id=self.account_input.currentData(),
                amount=total,
                incurred_at=datetime.combine(
                    self.incurred_date_input.date().toPython(),
                    datetime.min.time(),
                ).astimezone(),
                payee=self.payee_input.text(),
                description=self.memo_input.toPlainText(),
                due_date=(
                    None
                    if status == "CASH"
                    else self.due_date_input.date().toPython()
                ),
                initial_payment=initial_payment,
                payment_account_id=account_id,
                payment_method=payment_method,
                payment_status=status,
            )
        except (
            AuthorizationError,
            LicenseExpiredError,
            ValidationError,
            SQLAlchemyError,
        ) as exc:
            self.status_label.setStyleSheet(_STATUS_STYLES["error"])
            self.status_label.setText(f"Pengeluaran gagal disimpan: {exc}")
            QMessageBox.warning(self, "Pengeluaran gagal disimpan", str(exc))
            return
        detail = (
            f" dengan DP {rupiah(initial_payment)}" if status == "DP" else ""
        )
        self.status_label.setStyleSheet(_STATUS_STYLES["ok"])
        self.status_label.setText(
            f"Pengeluaran {rupiah(total)}{detail} berhasil disimpan."
        )
        self._reset_form(clear_status=True)

    def _reset_form(self, clear_status: bool = False):
        self.account_input.setCurrentIndex(0)
        self.amount_input.setValue(0)
        self.incurred_date_input.setDate(date.today())
        self.payee_input.clear()
        self.memo_input.clear()
        self.status_input.setCurrentIndex(0)
        self.dp_amount_input.setValue(0)
        self.due_date_input.setDate(date.today())
        if self.payment_account_input.count():
            self.payment_account_input.setCurrentIndex(0)
        if clear_status:
            self.status_label.setStyleSheet(_STATUS_STYLES["ok"])


class ExpensePaymentView(QWidget):
    """Tab "Bayar Pengeluaran": tabel Hutang/DP + tombol Bayar Sekarang.

    Daftar tabel = pengeluaran dengan Status Pembayaran "Hutang" atau
    "DP" yang diinput lewat tab Catat Pengeluaran. Tanpa input tambahan:
    "Bayar Sekarang" melunasi sisa tagihan langsung dari akun Kas.
    """

    _STATUS_TEXT = {"CASH": "Tunai", "HUTANG": "Hutang", "DP": "DP"}

    def __init__(
        self,
        actor,
        service: FinancialService,
        parent=None,
        *,
        read_only: bool = False,
    ):
        super().__init__(parent)
        self.actor = actor
        self.service = service
        self.read_only = bool(read_only)
        self._expenses: list[Expense] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(32, 26, 32, 30)
        root.setSpacing(12)

        if self.read_only:
            banner = QLabel(
                "MODE BACA-SAJA — pembayaran pengeluaran terkunci karena "
                "masa lisensi berakhir."
            )
            banner.setStyleSheet(
                "color: #fef3c7; background: #78350f; border-radius: 8px; "
                "padding: 9px 12px; font-weight: 600;"
            )
            banner.setWordWrap(True)
            root.addWidget(banner)

        description = QLabel(
            "Tabel berisi pengeluaran berstatus Pembayaran Hutang atau "
            "DP (diinput di tab Catat Pengeluaran). Pilih baris lalu "
            'tekan "Bayar Sekarang" — sisa tagihan langsung dilunasi '
            "dari akun Kas."
        )
        description.setWordWrap(True)
        description.setStyleSheet("color: #a1a1aa;")
        root.addWidget(description)

        self.expense_table = QTableWidget(0, 9)
        self.expense_table.setHorizontalHeaderLabels(
            [
                "Tanggal",
                "Kategori",
                "Penerima",
                "Keterangan",
                "Total",
                "Dibayar",
                "Sisa",
                "Status",
                "Jatuh Tempo",
            ]
        )
        self.expense_table.setEditTriggers(
            QTableWidget.EditTrigger.NoEditTriggers
        )
        self.expense_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self.expense_table.setSelectionMode(
            QTableWidget.SelectionMode.SingleSelection
        )
        self.expense_search = TableSearchBar(
            self.expense_table, "Cari pengeluaran..."
        )
        root.addWidget(self.expense_search)
        root.addWidget(self.expense_table, 1)
        attach_status_focus_hint(self.expense_table)

        self.cash_accounts = [
            account
            for account in service.accounts("ASSET")
            if account.code in {"1000", "1010"}
        ]

        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet(_STATUS_STYLES["muted"])
        root.addWidget(self.status_label)

        actions = QHBoxLayout()
        actions.addStretch(1)
        self.pay_button = QPushButton("Bayar Sekarang")
        self.pay_button.clicked.connect(self._pay)
        actions.addWidget(self.pay_button)
        root.addLayout(actions)
        root.addStretch(1)

        self.refresh_view()

    def refresh_view(self):
        try:
            if self.read_only:
                enabled = False
                self.status_label.setStyleSheet(_STATUS_STYLES["warn"])
                self.status_label.setText(
                    "MODE BACA-SAJA — pembayaran pengeluaran terkunci."
                )
            elif not self.service.is_initialized():
                enabled = False
                self.status_label.setStyleSheet(_STATUS_STYLES["warn"])
                self.status_label.setText(
                    "Laporan Keuangan belum aktif. Aktifkan dulu di tab "
                    "Modal Awal."
                )
            else:
                enabled = True
                self._reload_table()
                if self._expenses:
                    self.status_label.setStyleSheet(_STATUS_STYLES["muted"])
                    self.status_label.setText("")
                else:
                    self.status_label.setStyleSheet(_STATUS_STYLES["muted"])
                    self.status_label.setText(
                        "Tidak ada pengeluaran dengan status Hutang atau DP."
                    )
            self.expense_table.setEnabled(enabled)
            self.pay_button.setEnabled(enabled and bool(self._expenses))
        except (AuthorizationError, SQLAlchemyError) as exc:
            QMessageBox.warning(self, "Data keuangan gagal dimuat", str(exc))

    def _reload_table(self):
        selected_id = None
        row = self.expense_table.currentRow()
        if 0 <= row < len(self._expenses):
            selected_id = self._expenses[row].id
        self._expenses = [
            expense
            for expense in self.service.list_expenses(self.actor)
            if expense.payment_status in {"HUTANG", "DP"}
        ]
        self.expense_table.setRowCount(len(self._expenses))
        for row, expense in enumerate(self._expenses):
            values = (
                expense.incurred_at.astimezone().strftime("%d-%m-%Y"),
                expense.category,
                expense.payee or "-",
                expense.description or "-",
                rupiah(expense.amount),
                rupiah(expense.paid_amount),
                rupiah(expense.amount - expense.paid_amount),
                self._STATUS_TEXT.get(
                    expense.payment_status, expense.payment_status
                ),
                expense.due_date.strftime("%d-%m-%Y")
                if expense.due_date
                else "-",
            )
            for column, value in enumerate(values):
                self.expense_table.setItem(row, column, QTableWidgetItem(value))
            if expense.payment_status == "DP":
                self.expense_table.item(row, 7).setToolTip(
                    "DP (uang muka) yang telah dibayarkan: "
                    + rupiah(expense.paid_amount)
                )
        target_row = -1
        if selected_id is not None:
            for row, expense in enumerate(self._expenses):
                if expense.id == selected_id:
                    target_row = row
                    break
        if target_row < 0 and self._expenses:
            target_row = 0
        if target_row >= 0:
            self.expense_table.selectRow(target_row)
        self.expense_table.resizeColumnsToContents()

    def current_expense(self):
        """Baris terpilih pada tabel (fallback: baris pertama)."""
        if not self._expenses:
            return None
        selection = self.expense_table.selectionModel()
        rows = (
            sorted({index.row() for index in selection.selectedRows()})
            if selection is not None
            else []
        )
        if not rows:
            row = self.expense_table.currentRow()
            rows = [row] if 0 <= row < len(self._expenses) else []
        if not rows:
            rows = [0]
        return self._expenses[rows[0]]

    def _pay(self):
        expense = self.current_expense()
        if expense is None:
            QMessageBox.information(
                self,
                "Pilih pengeluaran",
                "Tidak ada pengeluaran berstatus Hutang atau DP untuk "
                "dibayar.",
            )
            return
        amount = expense.amount - expense.paid_amount
        if amount <= 0:
            self.refresh_view()
            return
        payment_account = next(
            (
                account
                for account in self.cash_accounts
                if account.code == "1000"
            ),
            self.cash_accounts[0] if self.cash_accounts else None,
        )
        if payment_account is None:
            QMessageBox.warning(
                self,
                "Akun Kas/Bank tidak tersedia",
                "Periksa daftar akun.",
            )
            return
        method = "CASH" if payment_account.code == "1000" else "BANK"
        payee = expense.payee or expense.description or expense.category
        try:
            self.service.record_expense_payment(
                self.actor,
                expense.id,
                amount,
                payment_account.id,
                method,
            )
        except (
            AuthorizationError,
            LicenseExpiredError,
            ValidationError,
            SQLAlchemyError,
        ) as exc:
            self.status_label.setStyleSheet(_STATUS_STYLES["error"])
            self.status_label.setText(f"Pembayaran gagal dicatat: {exc}")
            QMessageBox.warning(self, "Pembayaran gagal dicatat", str(exc))
            return
        self.refresh_view()
        self.status_label.setStyleSheet(_STATUS_STYLES["ok"])
        self.status_label.setText(
            f"Pembayaran {rupiah(amount)} untuk pengeluaran {payee} "
            "berhasil dicatat."
        )
