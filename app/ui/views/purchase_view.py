from datetime import date
import logging
from uuid import uuid4

logger = logging.getLogger("pos.purchase")

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy.exc import SQLAlchemyError

from app.core.exceptions import (
    AuthorizationError,
    LicenseExpiredError,
    ValidationError,
)
from app.models import Account, Product, PurchaseOrder
from app.services.master_data_service import MasterDataService
from app.services.purchase_service import PurchaseService
from app.ui.views.supplier_view import SupplierView
from app.ui.widgets import TableSearchBar, attach_status_focus_hint, create_copyright_label
from app.utils.formatters import rupiah


class NewProductDialog(QDialog):
    """Form ringkas produk baru dari tab Belanja.

    Hanya field wajib; kategori/satuan kosong dibuat otomatis
    ("Umum"/"Pcs"). Stok awal 0 — bertambah saat pembelian disimpan.
    """

    def __init__(self, master: MasterDataService, *, purchase_price=0, parent=None):
        super().__init__(parent)
        self.master = master
        self.setWindowTitle("Produk Baru")
        self.setMinimumWidth(470)

        layout = QVBoxLayout(self)
        intro = QLabel(
            "Produk belum ada di database? Buat cepat di sini. "
            "Stok awal 0 dan akan bertambah otomatis setelah QTY "
            "pembelian disimpan."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet("color: #a1a1aa;")
        layout.addWidget(intro)

        form = QFormLayout()
        self.name_input = QLineEdit()
        self.name_input.setMaxLength(200)
        self.name_input.setPlaceholderText("Nama produk, contoh: Kopi Sachet")
        self.sku_input = QLineEdit()
        self.sku_input.setMaxLength(80)
        self.sku_input.setPlaceholderText("Kosongkan untuk buat SKU otomatis")
        self.barcode_input = QLineEdit()
        self.barcode_input.setMaxLength(80)
        self.barcode_input.setPlaceholderText("Opsional, contoh: 899...")
        self.category_input = QComboBox()
        categories = master.list_categories()
        if categories:
            self.category_input.addItem("Pilih kategori", None)
            for category in categories:
                self.category_input.addItem(category.name, category.id)
        else:
            self.category_input.addItem('(otomatis: kategori "Umum")', None)
        self.unit_input = QComboBox()
        units = master.list_units()
        if units:
            self.unit_input.addItem("Pilih satuan", None)
            for unit in units:
                self.unit_input.addItem(f"{unit.name} ({unit.symbol})", unit.id)
        else:
            self.unit_input.addItem('(otomatis: satuan "Pcs")', None)
        self.purchase_price_input = QDoubleSpinBox()
        self.purchase_price_input.setDecimals(0)
        self.purchase_price_input.setRange(0, 2_000_000_000)
        self.purchase_price_input.setGroupSeparatorShown(True)
        self.purchase_price_input.setValue(int(purchase_price))
        self.selling_price_input = QDoubleSpinBox()
        self.selling_price_input.setDecimals(0)
        self.selling_price_input.setRange(1, 2_000_000_000)
        self.selling_price_input.setGroupSeparatorShown(True)
        self.selling_price_input.setValue(
            max(int(round(purchase_price * 1.3)), 1_000)
        )

        form.addRow("Nama produk *", self.name_input)
        form.addRow("SKU", self.sku_input)
        form.addRow("Barcode", self.barcode_input)
        form.addRow("Kategori", self.category_input)
        form.addRow("Satuan", self.unit_input)
        form.addRow("Harga beli (Rp)", self.purchase_price_input)
        form.addRow("Harga jual (Rp) *", self.selling_price_input)
        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._validate_and_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        layout.addWidget(
            create_copyright_label(self),
            alignment=Qt.AlignmentFlag.AlignRight,
        )

    def _validate_and_accept(self):
        if not self.name_input.text().strip():
            QMessageBox.warning(
                self,
                "Nama produk wajib",
                "Isi nama produk.",
            )
            self.name_input.setFocus()
            return
        self.accept()

    def form_data(self) -> dict:
        return {
            "name": self.name_input.text().strip(),
            "sku": self.sku_input.text().strip(),
            "barcode": self.barcode_input.text().strip(),
            "category_id": self.category_input.currentData(),
            "unit_id": self.unit_input.currentData(),
            "purchase_price": int(self.purchase_price_input.value()),
            "selling_price": int(self.selling_price_input.value()),
        }


class PurchaseView(QWidget):
    back_requested = Signal()

    def __init__(self, actor, session, parent=None, *, read_only=False):
        super().__init__(parent)
        self.actor = actor
        self.session = session
        self.read_only = bool(read_only)
        self.service = PurchaseService(
            session,
            transaction_locked=self.read_only,
        )
        self.master = MasterDataService(session)
        self.setWindowTitle("Belanja dan Supplier")

        root = QVBoxLayout(self)
        root.setContentsMargins(32, 26, 32, 30)
        root.setSpacing(12)

        header = QHBoxLayout()
        self.back_button = QPushButton("← Dashboard")
        self.back_button.clicked.connect(self.back_requested.emit)
        title = QLabel("Belanja dan Supplier")
        title.setStyleSheet("font-size: 25px; font-weight: 700; color: #ffffff;")
        header.addWidget(self.back_button)
        header.addWidget(title)
        header.addStretch(1)
        root.addLayout(header)

        self.tabs = QTabWidget()

        # ------------------------------------------------------ tab "Belanja"
        belanja_page = QWidget()
        belanja_layout = QVBoxLayout(belanja_page)
        belanja_layout.setContentsMargins(0, 8, 0, 0)
        belanja_layout.setSpacing(12)

        description = QLabel(
            "Catat barang yang sudah diterima. Pembelian Tempo menjadi hutang "
            "sampai jatuh tempo; pembelian Lunas langsung tercatat lunas; "
            "pembelian DP mencatat uang muka dan menyisakan hutang. "
            "Bila harga modal beli naik, harga jual dan harga spesial aktif "
            "otomatis menyesuaikan (margin % tetap; tidak pernah turun)."
        )
        description.setWordWrap(True)
        description.setStyleSheet("color: #a1a1aa;")
        belanja_layout.addWidget(description)

        form = QFormLayout()
        form.setVerticalSpacing(10)
        self.supplier_input = QComboBox()
        self.product_input = QComboBox()
        self.quantity_input = QSpinBox()
        self.quantity_input.setRange(1, 2_000_000_000)
        self.unit_cost_input = QDoubleSpinBox()
        self.unit_cost_input.setDecimals(0)
        self.unit_cost_input.setRange(0, 2_000_000_000)
        self.unit_cost_input.setGroupSeparatorShown(True)
        self.payment_account_input = QComboBox()
        self.payment_status_input = QComboBox()
        self.payment_status_input.addItem("Lunas", "PAID")
        self.payment_status_input.addItem("Tempo", "TEMPO")
        self.payment_status_input.addItem("DP (uang muka)", "DP")
        self.dp_amount_input = QDoubleSpinBox()
        self.dp_amount_input.setDecimals(0)
        self.dp_amount_input.setRange(0, 2_000_000_000)
        self.dp_amount_input.setGroupSeparatorShown(True)
        self.due_date_input = QDateEdit()
        self.due_date_input.setCalendarPopup(True)
        self.due_date_input.setDisplayFormat("dd MMMM yyyy")
        self.due_date_input.setDate(date.today())
        self.payment_status_input.currentIndexChanged.connect(
            self._update_due_date_state
        )
        self.product_input.currentIndexChanged.connect(
            self._update_product_cost
        )
        self.product_input.currentIndexChanged.connect(
            self._update_product_tooltip
        )
        self.product_input.setToolTip("Pilih produk untuk melihat jumlah stok.")
        self._all_products = []
        for widget in (
            self.supplier_input,
            self.product_input,
            self.quantity_input,
            self.unit_cost_input,
            self.payment_account_input,
            self.payment_status_input,
            self.dp_amount_input,
            self.due_date_input,
        ):
            widget.setMinimumHeight(30)

        form.addRow("Supplier *", self.supplier_input)
        self.low_stock_checkbox = QCheckBox("Tampilkan stok habis / menipis")
        self.low_stock_checkbox.setToolTip(
            "Tidak ada produk dengan stok habis atau di bawah 5."
        )
        self.low_stock_checkbox.toggled.connect(self._populate_product_combo)
        form.addRow(self.low_stock_checkbox)
        product_row = QHBoxLayout()
        product_row.setSpacing(8)
        product_row.addWidget(self.product_input, 1)
        self.new_product_button = QPushButton("Produk Baru")
        self.new_product_button.setStyleSheet(
            "QPushButton { background: #007acc; color: white; border: none; "
            "border-radius: 8px; padding: 7px 12px; font-weight: 600; }"
            "QPushButton:hover { background: #0098ff; }"
        )
        self.new_product_button.setToolTip(
            "Buat produk baru bila belum ada di database."
        )
        self.new_product_button.clicked.connect(self._create_product)
        product_row.addWidget(self.new_product_button)
        form.addRow("Produk *", product_row)
        form.addRow("QTY *", self.quantity_input)
        form.addRow("Harga modal per unit (Rp) *", self.unit_cost_input)
        form.addRow("Pembayaran dari akun", self.payment_account_input)
        form.addRow("Status pembelian *", self.payment_status_input)
        form.addRow("Jumlah DP (Rp)", self.dp_amount_input)
        form.addRow("Jatuh tempo *", self.due_date_input)

        actions = QHBoxLayout()
        self.record_button = QPushButton("Simpan Pembelian")
        self.record_button.clicked.connect(self._record_purchase)
        self.refresh_button = QPushButton("Muat Ulang")
        self.refresh_button.clicked.connect(self.refresh_data)
        actions.addWidget(self.record_button)
        actions.addWidget(self.refresh_button)
        actions.addStretch(1)

        form_card = QFrame()
        form_card.setObjectName("purchaseFormCard")
        form_card.setStyleSheet(
            "QFrame#purchaseFormCard { background: #1a1a1e; "
            "border: 1px solid #2d2d34; border-radius: 14px; }"
        )
        card_layout = QVBoxLayout(form_card)
        card_layout.setContentsMargins(20, 16, 20, 16)
        card_layout.setSpacing(14)
        card_layout.addLayout(form)
        card_layout.addLayout(actions)
        card_layout.addStretch(1)
        belanja_layout.addWidget(form_card, 1)

        if self.read_only:
            banner = QLabel(
                "MODE BACA-SAJA — pembelian dan pembayaran baru terkunci "
                "karena masa lisensi berakhir."
            )
            banner.setStyleSheet(
                "color: #fef3c7; background: #78350f; border-radius: 8px; "
                "padding: 9px 12px; font-weight: 600;"
            )
            banner.setWordWrap(True)
            belanja_layout.addWidget(banner)
            self.record_button.setEnabled(False)
            self.new_product_button.setEnabled(False)

        self.purchase_table = QTableWidget(0, 8)
        self.purchase_table.setHorizontalHeaderLabels(
            [
                "No. Pembelian",
                "Tanggal",
                "Supplier",
                "Produk",
                "Total",
                "Status",
                "Jatuh Tempo",
                "Sisa Hutang",
            ]
        )
        self.purchase_table.setEditTriggers(
            QTableWidget.EditTrigger.NoEditTriggers
        )
        self.purchase_table.horizontalHeader().setStretchLastSection(True)
        self.purchase_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self.purchase_table.setSelectionMode(
            QTableWidget.SelectionMode.SingleSelection
        )
        self.tabs.addTab(belanja_page, "Belanja")

        # ------------------------------------------- tab "Daftar Pembelian"
        daftar_page = QWidget()
        daftar_layout = QVBoxLayout(daftar_page)
        daftar_layout.setContentsMargins(0, 8, 0, 0)
        daftar_layout.setSpacing(12)

        daftar_description = QLabel(
            "Daftar seluruh pembelian toko — Lunas, DP (uang muka), dan "
            "Tempo — lengkap dengan total, jatuh tempo, dan sisa hutangnya."
        )
        daftar_description.setWordWrap(True)
        daftar_description.setStyleSheet("color: #a1a1aa;")
        daftar_layout.addWidget(daftar_description)

        daftar_layout.addWidget(self.purchase_table, 1)
        daftar_layout.addWidget(
            create_copyright_label(self),
            alignment=Qt.AlignmentFlag.AlignRight,
        )
        self.purchase_search = TableSearchBar(
            self.purchase_table, "Cari pembelian..."
        )
        daftar_layout.insertWidget(1, self.purchase_search)
        attach_status_focus_hint(self.purchase_table)
        self.tabs.addTab(daftar_page, "Daftar Pembelian")

        # ---------------------------------------------- tab "Kelola Supplier"
        self.supplier_view = SupplierView(actor, session, embedded=True)
        self.supplier_view.purchases_requested.connect(self._show_belanja_tab)
        self.tabs.addTab(self.supplier_view, "Kelola Supplier")

        # ------------------------------------------------- tab "Bayar Hutang"
        bayar_page = QWidget()
        bayar_layout = QVBoxLayout(bayar_page)
        bayar_layout.setContentsMargins(0, 8, 0, 0)
        bayar_layout.setSpacing(12)

        bayar_description = QLabel(
            "Pilih pembelian yang masih memiliki sisa hutang, lalu klik "
            "Bayar Hutang. Pembayaran dicatat dari akun Kas/Bank yang "
            "dipilih di tab Belanja."
        )
        bayar_description.setWordWrap(True)
        bayar_description.setStyleSheet("color: #a1a1aa;")
        bayar_layout.addWidget(bayar_description)

        debt_table_title = QLabel("Tabel Hutang")
        debt_table_title.setStyleSheet(
            "font-size: 16px; font-weight: 700; color: #ffffff;"
        )
        bayar_layout.addWidget(debt_table_title)

        self.debt_table = QTableWidget(0, 8)
        self.debt_table.setHorizontalHeaderLabels(
            [
                "No. Pembelian",
                "Tanggal",
                "Supplier",
                "Produk",
                "Total",
                "Status",
                "Jatuh Tempo",
                "Sisa Hutang",
            ]
        )
        self.debt_table.setEditTriggers(
            QTableWidget.EditTrigger.NoEditTriggers
        )
        self.debt_table.horizontalHeader().setStretchLastSection(True)
        self.debt_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self.debt_table.setSelectionMode(
            QTableWidget.SelectionMode.SingleSelection
        )
        self.debt_search = TableSearchBar(
            self.debt_table, "Cari sisa hutang..."
        )
        bayar_layout.addWidget(self.debt_search)
        bayar_layout.addWidget(self.debt_table, 1)
        attach_status_focus_hint(self.debt_table)

        self.debt_summary = QLabel()
        self.debt_summary.setStyleSheet(
            "font-weight: 700; color: #fdba74; font-size: 14px;"
        )
        bayar_layout.addWidget(self.debt_summary)

        bayar_actions = QHBoxLayout()
        self.pay_debt_button = QPushButton("Bayar Hutang")
        self.pay_debt_button.clicked.connect(self._record_selected_payment)
        bayar_actions.addWidget(self.pay_debt_button)
        bayar_actions.addStretch(1)
        bayar_layout.addLayout(bayar_actions)
        bayar_layout.addWidget(
            create_copyright_label(self),
            alignment=Qt.AlignmentFlag.AlignRight,
        )

        if self.read_only:
            self.pay_debt_button.setEnabled(False)

        self.tabs.addTab(bayar_page, "Bayar Hutang")

        root.addWidget(self.tabs)
        self.refresh_data()
        self.tabs.currentChanged.connect(self._on_tab_changed)

    def _show_belanja_tab(self):
        self.tabs.setCurrentIndex(0)

    def _on_tab_changed(self, index: int):
        if self.tabs.widget(index) is self.supplier_view:
            self.supplier_view.refresh_suppliers()
        else:
            self.refresh_data()

    def _create_product(self):
        logger.info(
            "Tombol Produk Baru diklik (read_only=%s)", self.read_only
        )
        dialog = NewProductDialog(
            self.master,
            purchase_price=int(self.unit_cost_input.value()),
            parent=self,
        )
        logger.info("NewProductDialog dibuat, exec() dipanggil")
        accepted = dialog.exec() == QDialog.DialogCode.Accepted
        logger.info("NewProductDialog exec() selesai: accepted=%s", accepted)
        if not accepted:
            return
        self._save_new_product(dialog)

    def _save_new_product(self, dialog: NewProductDialog) -> bool:
        data = dialog.form_data()
        try:
            category_id = data["category_id"]
            if category_id is None:
                category_id = self.master.ensure_default_category(
                    self.actor
                ).id
            unit_id = data["unit_id"]
            if unit_id is None:
                unit_id = self.master.ensure_default_unit(self.actor).id
            sku = data["sku"] or f"{self._sku_prefix(data['name'])}-{uuid4().hex[:6].upper()}"
            product = self.master.save_product(
                self.actor,
                product_id=None,
                sku=sku,
                barcode=data["barcode"],
                name=data["name"],
                category_id=category_id,
                unit_id=unit_id,
                purchase_price=data["purchase_price"],
                selling_price=data["selling_price"],
                stock_qty=0,
                min_stock=0,
                is_active=True,
                supplier_id=self.supplier_input.currentData(),
            )
        except (AuthorizationError, ValidationError, SQLAlchemyError) as exc:
            logger.exception("Produk baru gagal disimpan")
            QMessageBox.warning(self, "Produk tidak dapat disimpan", str(exc))
            return False
        logger.info("Produk baru tersimpan: %s (%s)", product.name, product.sku)
        self.refresh_data()
        index = self.product_input.findData(product.id)
        if index >= 0:
            self.product_input.setCurrentIndex(index)
        QMessageBox.information(
            self,
            "Produk tersimpan",
            f"{product.name} ({product.sku}) terdaftar. "
            "Isi QTY pembelian — stok bertambah saat disimpan.",
        )
        return True

    @staticmethod
    def _sku_prefix(name: str) -> str:
        base = "".join(ch for ch in name.upper() if ch.isalnum())[:6]
        return base or "PRD"

    def refresh_data(self):
        try:
            suppliers = self.service.active_suppliers(self.actor)
            products = self.service.active_products(self.actor)
            purchases = self.service.list_purchases(self.actor)
            payment_accounts = [
                account
                for account in self.service.financial.accounts("ASSET")
                if account.code in {"1000", "1010"}
            ]
        except (AuthorizationError, SQLAlchemyError) as exc:
            QMessageBox.critical(self, "Pembelian gagal dimuat", str(exc))
            return

        self.supplier_input.clear()
        for supplier in suppliers:
            self.supplier_input.addItem(
                f"{supplier.name} ({supplier.code})",
                supplier.id,
            )
        self._all_products = products
        self._update_low_stock_checkbox(products)
        self._populate_product_combo()
        self.payment_account_input.clear()
        for account in payment_accounts:
            self.payment_account_input.addItem(
                account.name,
                account.id,
            )
        self._update_product_cost()

        self.purchase_table.setRowCount(len(purchases))
        self.purchase_ids = []
        debt_entries = []
        outstanding = 0
        for row, record in enumerate(purchases):
            purchase = record["purchase"]
            self.purchase_ids.append(purchase.id)
            due = purchase.subtotal - purchase.paid_amount
            if purchase.payment_status in {"TEMPO", "DP"}:
                outstanding += due
            if purchase.payment_status == "PAID":
                status_label = "Lunas"
            elif purchase.payment_status == "DP":
                status_label = "DP (uang muka)"
            elif purchase.paid_amount:
                status_label = "Sebagian dibayar"
            else:
                status_label = "Tempo"
            values = (
                purchase.order_no,
                purchase.ordered_at.astimezone().strftime("%d-%m-%Y %H:%M")
                if purchase.ordered_at
                else "-",
                record["supplier_name"],
                record["product_name"],
                rupiah(purchase.subtotal),
                status_label,
                purchase.due_date.astimezone().strftime("%d-%m-%Y")
                if purchase.due_date
                else "-",
                rupiah(due),
            )
            dp_hint = (
                "DP (uang muka) yang telah dibayarkan: "
                + rupiah(purchase.paid_amount)
                if purchase.payment_status == "DP"
                else ""
            )
            for column, value in enumerate(values):
                self.purchase_table.setItem(
                    row,
                    column,
                    QTableWidgetItem(value),
                )
            if dp_hint:
                self.purchase_table.item(row, 5).setToolTip(dp_hint)
            if due > 0:
                debt_entries.append((purchase.id, values, dp_hint))
        self.purchase_table.resizeColumnsToContents()

        self.debt_purchase_ids = [entry[0] for entry in debt_entries]
        self.debt_table.setRowCount(len(debt_entries))
        for row, entry in enumerate(debt_entries):
            for column, value in enumerate(entry[1]):
                item = QTableWidgetItem(value)
                if column == 5 and entry[2]:
                    item.setToolTip(entry[2])
                self.debt_table.setItem(row, column, item)
        self.debt_table.resizeColumnsToContents()

        self.debt_summary.setText(
            f"Total sisa hutang pembelian (Tempo & DP): {rupiah(outstanding)}"
        )
        self._update_due_date_state()

    def _update_product_cost(self, _index: int = -1):
        product_id = self.product_input.currentData()
        if product_id is None:
            self.unit_cost_input.setValue(0)
            self.record_button.setEnabled(False)
            return
        product = self.service.get_product(self.actor, product_id)
        if product is None:
            self.record_button.setEnabled(False)
            return
        self.unit_cost_input.setValue(product.purchase_price)
        supplier_index = self.supplier_input.findData(product.supplier_id)
        if supplier_index >= 0:
            self.supplier_input.setCurrentIndex(supplier_index)
        elif self.supplier_input.count():
            self.supplier_input.setCurrentIndex(0)
        self.record_button.setEnabled(
            bool(self.supplier_input.count()) and not self.read_only
        )

    def _update_low_stock_checkbox(self, products):
        low_stock = [product for product in products if product.stock_qty < 5]
        if low_stock:
            details = "\n".join(
                f"{product.name} ({product.sku}): stok {product.stock_qty}"
                for product in low_stock
            )
            self.low_stock_checkbox.setEnabled(True)
            self.low_stock_checkbox.setToolTip(
                "Filter dropdown Produk ke daftar stok habis / menipis:\n"
                + details
            )
        else:
            if self.low_stock_checkbox.isChecked():
                self.low_stock_checkbox.setChecked(False)
            self.low_stock_checkbox.setEnabled(False)
            self.low_stock_checkbox.setToolTip(
                "Tidak ada produk dengan stok habis atau di bawah 5."
            )

    def _populate_product_combo(self, *_args):
        products = self._all_products
        if self.low_stock_checkbox.isChecked():
            products = [
                product for product in products if product.stock_qty < 5
            ]
        previous_id = self.product_input.currentData()
        self.product_input.clear()
        for product in products:
            self.product_input.addItem(
                f"{product.name} ({product.sku})",
                product.id,
            )
            self.product_input.setItemData(
                self.product_input.count() - 1,
                f"{product.name} ({product.sku})\n"
                f"{self._stock_hint(product.stock_qty)}",
                Qt.ToolTipRole,
            )
        if previous_id is not None:
            index = self.product_input.findData(previous_id)
            if index >= 0:
                self.product_input.setCurrentIndex(index)

    @staticmethod
    def _stock_hint(stock_qty: int) -> str:
        if stock_qty == 0:
            status = "STOK HABIS"
        elif stock_qty < 5:
            status = "stok menipis"
        else:
            status = "stok aman"
        return f"Jumlah stok: {stock_qty} ({status})"

    def _update_product_tooltip(self, _index: int = -1):
        product_id = self.product_input.currentData()
        if product_id is None:
            self.product_input.setToolTip(
                "Pilih produk untuk melihat jumlah stok."
            )
            return
        product = next(
            (item for item in self._all_products if item.id == product_id),
            None,
        )
        if product is None:
            product = self.service.get_product(self.actor, product_id)
        if product is None:
            self.product_input.setToolTip("")
            return
        self.product_input.setToolTip(
            f"{product.name} ({product.sku})\n"
            f"{self._stock_hint(product.stock_qty)}"
        )

    def _update_due_date_state(self, _index: int = -1):
        status = self.payment_status_input.currentData()
        self.due_date_input.setEnabled(status in {"TEMPO", "DP"})
        self.dp_amount_input.setEnabled(status == "DP")
        if status != "DP":
            self.dp_amount_input.setValue(0)

    def _record_purchase(self):
        supplier_id = self.supplier_input.currentData()
        product_id = self.product_input.currentData()
        if supplier_id is None or product_id is None:
            QMessageBox.warning(
                self,
                "Data belum lengkap",
                "Tambahkan supplier dan produk aktif sebelum mencatat pembelian.",
            )
            return

        payment_status = self.payment_status_input.currentData()
        due_date = (
            self.due_date_input.date().toPython()
            if payment_status in {"TEMPO", "DP"}
            else None
        )
        dp_amount = (
            int(self.dp_amount_input.value())
            if payment_status == "DP"
            else 0
        )
        product = self.session.get(Product, product_id)
        selling_before = product.selling_price if product is not None else None
        try:
            purchase = self.service.record_purchase(
                self.actor,
                supplier_id=supplier_id,
                product_id=product_id,
                quantity=self.quantity_input.value(),
                unit_cost=int(self.unit_cost_input.value()),
                payment_status=payment_status,
                due_date=due_date,
                payment_account_id=(
                    self.payment_account_input.currentData()
                    if payment_status in {"PAID", "DP"}
                    else None
                ),
                dp_amount=dp_amount,
            )
        except (
            AuthorizationError,
            LicenseExpiredError,
            ValidationError,
            SQLAlchemyError,
        ) as exc:
            QMessageBox.warning(self, "Pembelian tidak dapat disimpan", str(exc))
            return

        self.refresh_data()
        message = (
            f"Pembelian {purchase.order_no} tersimpan. "
            f"Total: {rupiah(purchase.subtotal)}"
        )
        if product is not None and product.selling_price != selling_before:
            message += (
                f" Harga jual diperbarui: {rupiah(selling_before)} → "
                f"{rupiah(product.selling_price)}."
            )
        QMessageBox.information(self, "Pembelian tersimpan", message)

    def _record_selected_payment(self):
        row = self.debt_table.currentRow()
        if row < 0:
            QMessageBox.information(
                self,
                "Pilih pembelian",
                "Pilih transaksi Tempo pada tabel, lalu klik Bayar Hutang.",
            )
            return
        purchase_id = self.debt_purchase_ids[row]
        purchase = self.session.get(PurchaseOrder, purchase_id)
        if purchase is None:
            QMessageBox.warning(self, "Pembelian tidak ditemukan", "Muat ulang data.")
            self.refresh_data()
            return
        remaining = purchase.subtotal - purchase.paid_amount
        amount, accepted = QInputDialog.getInt(
            self,
            "Catat Pembayaran Pembelian",
            f"Sisa hutang: {rupiah(remaining)}\nJumlah pembayaran:",
            remaining,
            1,
            remaining,
            1,
        )
        if not accepted:
            return
        payment_account_id = self.payment_account_input.currentData()
        if payment_account_id is None:
            QMessageBox.warning(
                self,
                "Akun pembayaran belum tersedia",
                "Pilih atau siapkan akun Kas/Bank terlebih dahulu.",
            )
            return
        account = self.session.get(Account, payment_account_id)
        try:
            self.service.record_payment(
                self.actor,
                purchase_id,
                amount,
                payment_account_id,
                "CASH" if account.code == "1000" else "BANK",
            )
        except (
            AuthorizationError,
            LicenseExpiredError,
            ValidationError,
            SQLAlchemyError,
        ) as exc:
            QMessageBox.warning(self, "Status pembayaran tidak berubah", str(exc))
            return
        self.refresh_data()
        refreshed = self.session.get(PurchaseOrder, purchase_id)
        if refreshed is not None and refreshed.paid_amount >= refreshed.subtotal:
            QMessageBox.information(
                self,
                "Pembelian lunas",
                "Transaksi pembelian ditandai Lunas.",
            )
        else:
            sisa = (
                refreshed.subtotal - refreshed.paid_amount
                if refreshed is not None
                else 0
            )
            QMessageBox.information(
                self,
                "Pembayaran tercatat",
                f"Pembayaran tercatat. Sisa hutang: {rupiah(sisa)}.",
            )
