from datetime import date
from hashlib import sha256
import asyncio
import logging
import uuid

logger = logging.getLogger("pos.cashier")

from PySide6.QtCore import QEvent, Qt, QTimer, Signal, Slot
from PySide6.QtGui import (
    QColor,
    QImage,
    QKeySequence,
    QPainter,
    QPixmap,
    QShortcut,
)
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy.exc import SQLAlchemyError

from app.core.exceptions import POSException
from app.hardware.printer import ReceiptPrinter
from app.models import Product, Sale, Store
from app.repositories.product_repository import ProductRepository
from app.repositories.shift_repository import ShiftRepository
from app.services.sales_service import SalesService
from app.services.bulk_pricing_service import BulkPricingService
from app.services.cashier_daily_report_service import CashierDailyReportService
from app.services.shift_service import ShiftService
from app.services.payment_service import PaymentService, PaymentServiceError
from app.utils.formatters import rupiah
from app.ui.widgets import TableSearchBar, create_copyright_label


class CashierView(QWidget):
    logout_requested = Signal()

    def __init__(self, user, session, parent=None, *, read_only=False):
        super().__init__(parent)
        self.user = user
        self.session = session
        self.read_only = bool(read_only)
        self.products = ProductRepository(session)
        self.sales = SalesService(session, transaction_locked=self.read_only)
        self.bulk_pricing = BulkPricingService(session)
        self.daily_reports = CashierDailyReportService(session)
        self.shift_service = ShiftService(session, ShiftRepository(session))
        self.receipt_printer = ReceiptPrinter()
        self.payment_service = PaymentService()
        self.cart = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 22)
        root.setSpacing(12)

        header = QHBoxLayout()
        title = QLabel("KASIR")
        title.setStyleSheet("font-size: 25px; font-weight: 700; color: #ffffff;")
        self.date_label = QLabel(date.today().strftime("%d %B %Y"))
        self.date_label.setStyleSheet("font-size: 14px; color: #a1a1aa;")
        self.shift_label = QLabel()
        self.shift_label.setStyleSheet(
            "font-weight: 600; color: #e4e4e7; padding: 7px 10px; "
            "background: #222226; border-radius: 8px;"
        )
        self.open_shift_button = QPushButton("Buka Shift")
        self.open_shift_button.clicked.connect(self._open_shift)
        self.daily_report_button = QPushButton("Laporan")
        self.daily_report_button.clicked.connect(self._submit_daily_report)
        self.logout_button = QPushButton("Keluar")
        self.logout_button.setStyleSheet(
            "QPushButton { background: #dc2626; color: white; border: none; "
            "border-radius: 8px; padding: 8px 14px; font-weight: 600; }"
            "QPushButton:hover { background: #ef4444; }"
        )
        self.logout_button.clicked.connect(self.logout_requested.emit)
        header.addWidget(title)
        header.addSpacing(10)
        header.addWidget(self.date_label)
        header.addStretch(1)
        header.addWidget(self.shift_label)
        header.addWidget(self.open_shift_button)
        header.addWidget(self.daily_report_button)
        header.addWidget(self.logout_button)
        root.addLayout(header)

        if self.read_only:
            banner = QLabel(
                "MODE BACA-SAJA — Masa trial/lisensi berakhir. "
                "Transaksi baru terkunci; data tetap dapat dibaca dan diekspor."
            )
            banner.setStyleSheet(
                "color: #fef3c7; background: #78350f; border-radius: 8px; "
                "padding: 9px 12px; font-weight: 600;"
            )
            banner.setWordWrap(True)
            root.addWidget(banner)

        search_bar = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText(
            "Scan barcode atau cari produk berdasarkan nama / SKU"
        )
        self.search_input.returnPressed.connect(self._search_products)
        self.search_button = QPushButton("Cari Produk")
        self.search_button.clicked.connect(self._search_products)
        search_bar.addWidget(self.search_input, 1)
        search_bar.addWidget(self.search_button)
        root.addLayout(search_bar)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.product_table = QTableWidget(0, 7)
        self.product_table.setHorizontalHeaderLabels(
            [
                "SKU",
                "Produk",
                "Kategori",
                "Stok",
                "Harga Satuan",
                "Harga Spesial Partai",
                "ID",
            ]
        )
        self.product_table.setColumnHidden(6, True)
        self.product_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self.product_table.setEditTriggers(
            QTableWidget.EditTrigger.NoEditTriggers
        )
        self.product_table.horizontalHeader().setStretchLastSection(True)
        self.product_table.cellClicked.connect(self._on_product_selected)
        self.product_table.itemActivated.connect(
            lambda _item: self._add_selected_product()
        )

        cart_panel = QWidget()
        cart_layout = QVBoxLayout(cart_panel)
        cart_layout.setContentsMargins(0, 0, 0, 0)
        cart_heading = QLabel("Keranjang")
        cart_heading.setStyleSheet(
            "font-size: 17px; font-weight: 700; color: #ffffff;"
        )
        cart_layout.addWidget(cart_heading)
        self.cart_table = QTableWidget(0, 5)
        self.cart_table.setHorizontalHeaderLabels(
            ["SKU", "Produk", "Harga", "Qty", "Subtotal"]
        )
        self.cart_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.cart_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.cart_table.horizontalHeader().setStretchLastSection(True)
        self.cart_table.setColumnWidth(0, 110)
        self.cart_table.setColumnWidth(1, 220)
        self.cart_table.setColumnWidth(2, 120)
        self.cart_table.setColumnWidth(3, 90)
        self.cart_table.itemDoubleClicked.connect(
            lambda item: self._edit_cart_qty(item.row())
            if item.column() == 3
            else None
        )
        self.cart_table.installEventFilter(self)
        cart_layout.addWidget(self.cart_table, 1)
        cart_actions = QHBoxLayout()
        add_button = QPushButton("Tambah Dipilih")
        add_button.clicked.connect(self._add_selected_product)
        increase_button = QPushButton("Qty +")
        increase_button.clicked.connect(lambda: self._change_selected_qty(1))
        decrease_button = QPushButton("Qty -")
        decrease_button.clicked.connect(lambda: self._change_selected_qty(-1))
        remove_button = QPushButton("Hapus Item")
        remove_button.clicked.connect(self._remove_selected_product)
        clear_button = QPushButton("Kosongkan")
        clear_button.clicked.connect(self._clear_cart)
        cart_actions.addWidget(add_button)
        cart_actions.addWidget(increase_button)
        cart_actions.addWidget(decrease_button)
        cart_actions.addWidget(remove_button)
        cart_actions.addWidget(clear_button)
        cart_layout.addLayout(cart_actions)

        splitter.addWidget(self.product_table)
        splitter.addWidget(cart_panel)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 4)
        root.addWidget(splitter, 5)

        daily_panel = QFrame()
        daily_panel.setStyleSheet(
            "QFrame#dailyPanel { background: #1a1a1e; border: 1px solid #2d2d34; "
            "border-radius: 10px; }"
            "QLabel { border: none; background: transparent; }"
        )
        daily_panel.setObjectName("dailyPanel")
        daily_layout = QVBoxLayout(daily_panel)
        daily_layout.setContentsMargins(14, 10, 14, 10)
        daily_header = QHBoxLayout()
        daily_heading = QLabel("Transaksi Hari Ini")
        daily_heading.setStyleSheet("font-weight: 700;")
        self.daily_summary = QLabel()
        self.daily_summary.setStyleSheet("color: #e4e4e7;")
        daily_header.addWidget(daily_heading)
        daily_header.addStretch(1)
        daily_header.addWidget(self.daily_summary)
        daily_layout.addLayout(daily_header)
        self.daily_table = QTableWidget(0, 4)
        self.daily_table.setMaximumHeight(135)
        self.daily_table.setHorizontalHeaderLabels(
            ["Waktu", "Invoice", "Kasir", "Total"]
        )
        self.daily_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.daily_table.horizontalHeader().setStretchLastSection(True)
        self.daily_search = TableSearchBar(
            self.daily_table, "Cari transaksi..."
        )
        daily_layout.addWidget(self.daily_search)
        daily_layout.addWidget(self.daily_table)
        root.addWidget(daily_panel, 2)

        footer = QHBoxLayout()
        self.status_label = QLabel("Pilih atau scan produk untuk mulai.")
        self.status_label.setStyleSheet("color: #a1a1aa;")
        footer.addWidget(self.status_label, 1)
        footer.addWidget(QLabel("TOTAL"))
        self.total_label = QLabel(rupiah(0))
        self.total_label.setStyleSheet(
            "font-size: 25px; font-weight: 700; color: #ffffff; margin-right: 12px;"
        )
        footer.addWidget(self.total_label)
        self.hold_button = QPushButton("Simpan Pesanan (F5)")
        self.hold_button.clicked.connect(self._hold_cart)
        footer.addWidget(self.hold_button)
        self.resume_button = QPushButton("Lanjutkan")
        self.resume_button.clicked.connect(self._resume_cart)
        footer.addWidget(self.resume_button)
        self.pay_button = QPushButton("Bayar (F4)")
        self.pay_button.setStyleSheet(
            "QPushButton { background: #16a34a; color: white; border: none; "
            "border-radius: 8px; padding: 12px 20px; font-weight: 700; }"
            "QPushButton:hover { background: #15803d; }"
        )
        self.pay_button.clicked.connect(self._checkout)
        if self.read_only:
            self.pay_button.setEnabled(False)
            self.hold_button.setEnabled(False)
            self.open_shift_button.setEnabled(False)
            self.status_label.setText(
                "Mode baca-saja: pembayaran dan shift dinonaktifkan."
            )
        footer.addWidget(self.pay_button)
        root.addLayout(footer)

        self.held_carts = []
        self._connect_shortcuts()
        self._refresh_shift_status()
        self._refresh_daily_sales()
        self._update_cart_view()

    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(0, self.search_input.setFocus)

    def eventFilter(self, obj, event):
        if obj is self.cart_table and event.type() == QEvent.Type.KeyPress:
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                row = self.cart_table.currentRow()
                column = self.cart_table.currentColumn()
                if column == 3 and 0 <= row < self.cart_table.rowCount():
                    self._edit_cart_qty(row)
                    return True
        return super().eventFilter(obj, event)

    def _connect_shortcuts(self):
        QShortcut(QKeySequence("F2"), self, activated=self._f2_action)
        QShortcut(QKeySequence("F4"), self, activated=self._checkout)
        QShortcut(QKeySequence("F5"), self, activated=self._hold_cart)
        QShortcut(QKeySequence("Escape"), self, activated=self._clear_cart)

    def _f2_action(self):
        row = self.product_table.currentRow()
        if row >= 0:
            self._add_selected_product(row)
        else:
            self.search_input.setFocus()

    def _search_products(self):
        query = self.search_input.text().strip()
        try:
            exact_product = self.products.find_by_barcode_or_sku(query) if query else None
            if exact_product is not None and exact_product.is_active:
                self._prompt_product_quantity(exact_product)
                self.search_input.clear()
                self.search_input.setFocus()
                return
            results = self.products.search_active(query)
        except SQLAlchemyError as exc:
            self._show_error("Gagal mencari produk", str(exc))
            return

        self.product_table.setRowCount(len(results))
        for row, product in enumerate(results):
            rule = self.bulk_pricing.rule_for_product(product.id)
            special_price = (
                (
                    f"{rupiah(self.bulk_pricing.effective_special_price(product, rule))} "
                    f"(qty ≥ {rule.quantity_threshold})"
                )
                if rule is not None
                else "-"
            )
            values = (
                product.sku,
                product.name,
                (
                    product.category.name
                    if product.category is not None
                    and product.category.deleted_at is None
                    else "-"
                ),
                str(product.stock_qty),
                rupiah(product.selling_price),
                special_price,
                str(product.id),
            )
            for column, value in enumerate(values):
                self.product_table.setItem(row, column, QTableWidgetItem(value))
        self.product_table.resizeColumnsToContents()
        if not results:
            self.status_label.setText("Produk tidak ditemukan.")
        else:
            self.status_label.setText(f"{len(results)} produk ditemukan.")

    def _add_selected_product(self, row=None):
        if row is None:
            row = self.product_table.currentRow()
        if row < 0:
            self.status_label.setText("Pilih produk dari daftar terlebih dahulu.")
            return

        product_id = int(self.product_table.item(row, 6).text())
        product = self.session.get(Product, product_id)
        if product is None:
            self.status_label.setText("Produk tidak ditemukan lagi.")
            self._search_products()
            return
        self._prompt_product_quantity(product)

    def _on_product_selected(self, row: int, column: int):
        self.product_table.setCurrentCell(row, column)
        self._add_selected_product(row)

    def _prompt_product_quantity(self, product):
        if not product.is_active or product.deleted_at is not None:
            self.status_label.setText("Produk ini sudah tidak aktif.")
            return
        existing_qty = self.cart.get(product.id, {}).get("qty", 0)
        available_qty = product.stock_qty - existing_qty
        if available_qty <= 0:
            self.status_label.setText(f"Stok {product.name} tidak mencukupi.")
            return
        quantity, accepted = QInputDialog.getInt(
            self,
            "Jumlah Produk",
            f"{product.name}\nStok tersedia: {available_qty}\nMasukkan jumlah:",
            1,
            1,
            available_qty,
        )
        if not accepted:
            return
        self._add_product(product, quantity)
        self.product_table.setFocus()

    def _add_product(self, product, quantity: int):
        existing_qty = self.cart.get(product.id, {}).get("qty", 0)
        if quantity < 1 or existing_qty + quantity > product.stock_qty:
            self.status_label.setText(
                f"Jumlah melebihi stok {product.name} ({product.stock_qty})."
            )
            return
        if product.id in self.cart:
            self.cart[product.id]["qty"] += quantity
        else:
            self.cart[product.id] = {"product": product, "qty": quantity}
        self._update_cart_view()
        self.status_label.setText(f"{quantity} × {product.name} ditambahkan.")

    def _remove_selected_product(self):
        row = self.cart_table.currentRow()
        if row < 0:
            self.status_label.setText("Pilih item keranjang yang akan dihapus.")
            return
        product_id = int(self.cart_table.item(row, 0).data(Qt.ItemDataRole.UserRole))
        self.cart.pop(product_id, None)
        self._update_cart_view()

    def _change_selected_qty(self, change: int):
        row = self.cart_table.currentRow()
        if row < 0:
            self.status_label.setText("Pilih item keranjang terlebih dahulu.")
            return
        product_id = int(self.cart_table.item(row, 0).data(Qt.ItemDataRole.UserRole))
        entry = self.cart.get(product_id)
        if entry is None:
            return
        new_qty = entry["qty"] + change
        if new_qty < 1 or new_qty > max(1, entry["product"].stock_qty):
            return
        entry["qty"] = new_qty
        self._update_cart_view()

    def _edit_cart_qty(self, row: int):
        if not (0 <= row < self.cart_table.rowCount()):
            return
        product_id = int(self.cart_table.item(row, 0).data(Qt.ItemDataRole.UserRole))
        entry = self.cart.get(product_id)
        if entry is None:
            return
        quantity, accepted = QInputDialog.getInt(
            self,
            "Ubah Jumlah",
            f"Jumlah {entry['product'].name}:",
            entry["qty"],
            1,
            max(1, entry["product"].stock_qty),
        )
        if accepted:
            entry["qty"] = quantity
            self._update_cart_view()

    def _update_cart_view(self):
        self.cart_table.setRowCount(len(self.cart))
        total = 0
        for row, (product_id, entry) in enumerate(self.cart.items()):
            product = entry["product"]
            quantity = entry["qty"]
            unit_price = self.bulk_pricing.unit_price(product, quantity)
            line_total = unit_price * quantity
            total += line_total
            sku_item = QTableWidgetItem(product.sku)
            sku_item.setData(Qt.ItemDataRole.UserRole, product_id)
            qty_item = QTableWidgetItem(str(quantity))
            qty_item.setTextAlignment(
                Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter
            )
            qty_item.setData(Qt.ItemDataRole.UserRole, product_id)
            values = (
                sku_item,
                QTableWidgetItem(product.name),
                QTableWidgetItem(rupiah(unit_price)),
                qty_item,
                QTableWidgetItem(rupiah(line_total)),
            )
            for column, item in enumerate(values):
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                if column == 2 and unit_price != product.selling_price:
                    item.setToolTip(
                        f"Harga normal: {rupiah(product.selling_price)}; "
                        "harga spesial partai diterapkan."
                    )
                self.cart_table.setItem(row, column, item)
        self.cart_table.resizeColumnsToContents()
        qty_column = 3
        min_qty_width = 70
        if self.cart_table.columnWidth(qty_column) < min_qty_width:
            self.cart_table.setColumnWidth(qty_column, min_qty_width)
        self.total_label.setText(rupiah(total))
        self.pay_button.setEnabled(
            bool(self.cart)
            and self.current_shift is not None
            and not self.read_only
        )

    def _set_cart_quantity(self, row: int, quantity: int):
        product_ids = list(self.cart)
        if row >= len(product_ids):
            return
        product_id = product_ids[row]
        entry = self.cart.get(product_id)
        if entry is None:
            return
        entry["qty"] = quantity
        self._update_cart_view()

    def _clear_cart(self):
        if not self.cart:
            return
        answer = QMessageBox.question(
            self,
            "Kosongkan keranjang",
            "Hapus semua item dari keranjang?",
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.cart.clear()
            self._update_cart_view()
            self.status_label.setText("Keranjang dikosongkan.")

    def _hold_cart(self):
        if not self.cart:
            self.status_label.setText("Keranjang kosong.")
            return
        self.held_carts.append(
            {product_id: dict(entry) for product_id, entry in self.cart.items()}
        )
        held_count = len(self.held_carts)
        self.cart.clear()
        self._update_cart_view()
        self.status_label.setText(f"Pesanan disimpan ({held_count} pesanan tertahan).")

    def _resume_cart(self):
        if not self.held_carts:
            self.status_label.setText("Tidak ada pesanan yang disimpan.")
            return
        if self.cart:
            answer = QMessageBox.question(
                self,
                "Ganti keranjang",
                "Keranjang saat ini akan digantikan dengan pesanan tersimpan. Lanjutkan?",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        self.cart = self.held_carts.pop()
        self._update_cart_view()
        self.status_label.setText("Pesanan tersimpan dilanjutkan.")

    def _refresh_shift_status(self):
        try:
            shift = self.shift_service.get_open_shift(self.user)
        except SQLAlchemyError as exc:
            self._show_error("Gagal memuat shift", str(exc))
            return
        self.current_shift = shift
        if self.read_only:
            self.shift_label.setText(
                "Mode baca-saja · shift dan transaksi terkunci"
            )
            self.open_shift_button.setEnabled(False)
            self.pay_button.setEnabled(False)
        elif shift is None:
            self.shift_label.setText("Shift belum dibuka")
            self.open_shift_button.setEnabled(True)
            self.pay_button.setEnabled(False)
        else:
            self.shift_label.setText(f"Shift aktif · Modal {rupiah(shift.opening_cash)}")
            self.open_shift_button.setEnabled(False)
            self.pay_button.setEnabled(bool(self.cart))

    def _open_shift(self):
        opening_cash, accepted = QInputDialog.getInt(
            self,
            "Buka Shift",
            "Masukkan modal awal (Rupiah):",
            0,
            0,
            2_000_000_000,
            1000,
        )
        if not accepted:
            return
        try:
            self.current_shift = self.shift_service.open_shift(
                self.user,
                opening_cash,
            )
        except POSException as exc:
            self._show_error("Shift tidak dapat dibuka", str(exc))
            return
        except SQLAlchemyError as exc:
            self._show_error("Gagal membuka shift", str(exc))
            return
        self._refresh_shift_status()

    def _submit_daily_report(self):
        report_date = date.today()
        try:
            existing_report = self.daily_reports.get_for_cashier(
                self.user.id,
                report_date,
            )
            sales_count, sales_total = self.daily_reports.daily_totals(
                self.user.id,
                report_date,
            )
        except SQLAlchemyError as exc:
            self._show_error("Gagal memuat laporan kasir", str(exc))
            return

        dialog = CashierDailyReportDialog(
            report_date,
            sales_count,
            sales_total,
            existing_report.notes if existing_report is not None else "",
            self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            self.daily_reports.save(
                self.user,
                report_date,
                dialog.notes_input.toPlainText(),
            )
        except (SQLAlchemyError, ValueError) as exc:
            self._show_error("Laporan kasir gagal disimpan", str(exc))
            return
        QMessageBox.information(
            self,
            "Laporan kasir tersimpan",
            "Laporan penjualan harian dan catatan kasir berhasil disimpan.",
        )
        self.search_input.setFocus()

    def _checkout(self):
        if self.read_only:
            QMessageBox.warning(
                self,
                "Transaksi terkunci",
                "Masa trial/lisensi berakhir. Transaksi baru terkunci; "
                "data tetap dapat dibaca dan diekspor. "
                "Aktivasi lisensi untuk kembali bertransaksi.",
            )
            return
        if not self.cart:
            self.status_label.setText("Keranjang kosong.")
            return
        if self.current_shift is None:
            QMessageBox.warning(
                self,
                "Shift belum dibuka",
                "Buka shift terlebih dahulu sebelum menerima pembayaran.",
            )
            return

        total = sum(
            self.bulk_pricing.unit_price(entry["product"], entry["qty"])
            * entry["qty"]
            for entry in self.cart.values()
        )
        payment_dialog = PaymentDialog(
            total,
            self,
            enabled_methods=self._enabled_payment_methods(),
        )
        if payment_dialog.exec() != QDialog.DialogCode.Accepted:
            return
        method, amount = payment_dialog.payment()

        if method == "QRIS_MIDTRANS":
            self._checkout_qris(total)
            return

        try:
            sale = self._save_sale(total, method, amount)
        except POSException as exc:
            self._show_error("Transaksi tidak dapat diselesaikan", str(exc))
            self._refresh_shift_status()
            return
        except (SQLAlchemyError, ValueError, KeyError) as exc:
            self._show_error("Transaksi gagal", str(exc))
            return

        change = amount - total if method == "CASH" else 0
        try:
            receipt_data = self._build_receipt_data(
                sale,
                method,
                amount,
                change,
            )
        except (SQLAlchemyError, RuntimeError) as exc:
            receipt_data = None
            self._show_error(
                "Transaksi berhasil, data struk gagal dimuat",
                str(exc),
            )
        self.cart.clear()
        self._update_cart_view()
        self._refresh_daily_sales()
        self.status_label.setText(f"Transaksi {sale.invoice_no} berhasil.")
        if receipt_data is not None:
            if method == "CASH":
                self._print_receipt_direct(receipt_data)
            else:
                self._offer_receipt_output(receipt_data)
        QMessageBox.information(
            self,
            "Transaksi berhasil",
            f"Invoice: {sale.invoice_no}\n"
            f"Total: {rupiah(total)}\n"
            f"Kembalian: {rupiah(change)}",
        )
        self.search_input.setFocus()

    def _print_receipt_direct(self, receipt_data: dict):
        try:
            self.receipt_printer.print_receipt_direct(receipt_data)
            self.status_label.setText("Struk dicetak ke printer thermal.")
        except (OSError, RuntimeError) as exc:
            self._show_error("Gagal mencetak struk", str(exc))

    def _enabled_payment_methods(self) -> list[str]:
        from app.models import PaymentSettings, PaymentWizardState

        try:
            settings = (
                self.session.query(PaymentSettings)
                .order_by(PaymentSettings.id)
                .first()
            )
            wizard_status = {
                row.method: row.status
                for row in self.session.query(PaymentWizardState).all()
            }
        except SQLAlchemyError:
            settings = None
            wizard_status = {}
        if settings is None:
            return list(PaymentDialog.ALL_METHODS)

        def ready(method: str) -> bool:
            return wizard_status.get(method) == "active"

        enabled: list[str] = []
        if settings.cash_enabled:
            enabled.append("CASH")
        if settings.qris_dana_enabled and ready("QRIS_DANA"):
            enabled.append("QRIS_DANA")
        if settings.qris_midtrans_enabled and ready("QRIS_MIDTRANS"):
            enabled.append("QRIS_MIDTRANS")
        if settings.transfer_enabled and ready("BANK"):
            enabled.append("BANK")
        return enabled or ["CASH"]

    def _checkout_qris(self, total: int):
        import uuid
        order_id = f"POS-{uuid.uuid4().hex[:12].upper()}"
        self.status_label.setText("Membuat QRIS...")
        QApplication.processEvents()

        try:
            qris_result = asyncio.run(
                self.payment_service.create_qris_payment(order_id, total)
            )
            logger.debug("QRIS result: %s", qris_result)
        except PaymentServiceError as exc:
            self._show_error("Gagal membuat QRIS", str(exc))
            return
        except Exception as exc:
            self._show_error("Gagal membuat QRIS", str(exc))
            return

        qr_base64 = qris_result.get("qr_image_base64")
        qr_content_type = qris_result.get("qr_image_content_type", "image/png")
        transaction_id = qris_result.get("transaction_id")
        logger.debug("qr_base64 length: %s", len(qr_base64) if qr_base64 else 0)
        logger.debug("qr_content_type: %s", qr_content_type)

        if not qr_base64:
            self._show_error("QRIS gagal", "Midtrans tidak mengembalikan gambar QR.")
            return

        qr_dialog = QRISPaymentDialog(
            order_id=order_id,
            total=total,
            qr_base64=qr_base64,
            qr_content_type=qr_content_type,
            parent=self,
        )
        qr_dialog.payment_completed.connect(self._on_qris_payment_completed)
        qr_dialog.exec()

    @Slot(dict)
    def _on_qris_payment_completed(self, payment_result: dict):
        if not payment_result.get("paid"):
            self._show_error("Pembayaran QRIS gagal", f"Status: {payment_result.get('status', 'unknown')}")
            return

        total = sum(
            self.bulk_pricing.unit_price(entry["product"], entry["qty"])
            * entry["qty"]
            for entry in self.cart.values()
        )
        try:
            sale = self._save_sale(total, "QRIS_MIDTRANS", total)
        except POSException as exc:
            self._show_error("Transaksi tidak dapat diselesaikan", str(exc))
            self._refresh_shift_status()
            return
        except (SQLAlchemyError, ValueError, KeyError) as exc:
            self._show_error("Transaksi gagal", str(exc))
            return

        try:
            receipt_data = self._build_receipt_data(
                sale,
                "QRIS_MIDTRANS",
                total,
                0,
            )
        except (SQLAlchemyError, RuntimeError) as exc:
            receipt_data = None
            self._show_error(
                "Transaksi berhasil, data struk gagal dimuat",
                str(exc),
            )
        self.cart.clear()
        self._update_cart_view()
        self._refresh_daily_sales()
        self.status_label.setText(f"Transaksi {sale.invoice_no} berhasil.")
        if receipt_data is not None:
            self._offer_receipt_output(receipt_data)
        QMessageBox.information(
            self,
            "Transaksi QRIS berhasil",
            f"Invoice: {sale.invoice_no}\n"
            f"Total: {rupiah(total)}\n"
            f"Metode: QRIS",
        )
        self.search_input.setFocus()

    def _build_receipt_data(
        self,
        sale: Sale,
        method: str,
        amount: int,
        change: int,
    ) -> dict:
        store = self.session.get(Store, sale.store_id)
        if store is None:
            raise RuntimeError("Data toko untuk struk tidak ditemukan.")
        payment_names = {
            "CASH": "Tunai",
            "QRIS": "QRIS",
            "QRIS_MIDTRANS": "QRIS",
            "QRIS_DANA": "QRIS DANA",
            "BANK": "TF (m Banking)",
            "EWALLET": "E-Wallet",
        }
        return {
            "store_name": store.name,
            "invoice_no": sale.invoice_no,
            "created_at": sale.created_at.astimezone().strftime("%d-%m-%Y %H:%M:%S"),
            "cashier_name": self.user.full_name,
            "items": [
                {
                    "sku": entry["product"].sku,
                    "name": entry["product"].name,
                    "qty": entry["qty"],
                    "unit_price": self.bulk_pricing.unit_price(
                        entry["product"],
                        entry["qty"],
                    ),
                    "line_total": (
                        self.bulk_pricing.unit_price(
                            entry["product"],
                            entry["qty"],
                        )
                        * entry["qty"]
                    ),
                }
                for entry in self.cart.values()
            ],
            "subtotal": sale.subtotal,
            "discount": sale.discount,
            "tax": sale.tax,
            "total": sale.grand_total,
            "payment_method": payment_names[method],
            "paid": amount,
            "change": change,
        }

    def _offer_receipt_output(self, receipt_data: dict):
        prompt = QMessageBox(self)
        prompt.setWindowTitle("Cetak Struk")
        prompt.setText("Transaksi berhasil. Pilih keluaran struk:")
        thermal_button = prompt.addButton(
            "Cetak Thermal",
            QMessageBox.ButtonRole.AcceptRole,
        )
        pdf_button = prompt.addButton(
            "Simpan PDF",
            QMessageBox.ButtonRole.ActionRole,
        )
        prompt.addButton("Nanti", QMessageBox.ButtonRole.RejectRole)
        prompt.setDefaultButton(thermal_button)
        prompt.exec()

        try:
            if prompt.clickedButton() is thermal_button:
                self.receipt_printer.print_receipt(receipt_data, self)
            elif prompt.clickedButton() is pdf_button:
                file_path, _ = QFileDialog.getSaveFileName(
                    self,
                    "Simpan Struk sebagai PDF",
                    f"{receipt_data['invoice_no']}.pdf",
                    "PDF (*.pdf)",
                )
                if file_path:
                    if not file_path.lower().endswith(".pdf"):
                        file_path += ".pdf"
                    saved_path = self.receipt_printer.save_pdf(
                        receipt_data,
                        file_path,
                    )
                    self.status_label.setText(f"Struk disimpan: {saved_path}")
        except (OSError, RuntimeError) as exc:
            self._show_error("Gagal mencetak struk", str(exc))

    def _save_sale(self, total: int, method: str, amount: int) -> Sale:
        items = [
            {
                "product_id": product_id,
                "qty": entry["qty"],
                "unit_price": self.bulk_pricing.unit_price(
                    entry["product"],
                    entry["qty"],
                ),
            }
            for product_id, entry in self.cart.items()
        ]
        sale = Sale(
            invoice_no=self.sales.new_invoice_number(),
            store_id=self.current_shift.store_id,
            shift_id=self.current_shift.id,
            cashier_id=self.user.id,
            subtotal=total,
            discount=0,
            tax=0,
            grand_total=total,
            status="PAID",
        )
        return self.sales.checkout(
            sale,
            items,
            [{"method": method, "amount": amount}],
        )

    def _refresh_daily_sales(self):
        try:
            sales = self.sales.daily_sales()
        except SQLAlchemyError as exc:
            self._show_error("Gagal memuat transaksi hari ini", str(exc))
            return
        self.daily_table.setRowCount(len(sales))
        for row, sale in enumerate(sales):
            values = (
                sale.created_at.strftime("%H:%M"),
                sale.invoice_no,
                sale.cashier.full_name if sale.cashier else str(sale.cashier_id),
                rupiah(sale.grand_total),
            )
            for column, value in enumerate(values):
                self.daily_table.setItem(row, column, QTableWidgetItem(value))
        self.daily_table.resizeColumnsToContents()
        self.daily_summary.setText(
            f"{len(sales)} transaksi · {rupiah(sum(sale.grand_total for sale in sales))}"
        )

    def _show_error(self, title: str, message: str):
        self.status_label.setText(message)
        QMessageBox.warning(self, title, message)


class CashierDailyReportDialog(QDialog):
    def __init__(
        self,
        report_date: date,
        sales_count: int,
        sales_total: int,
        notes: str,
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Laporan Kasir Harian")
        self.setMinimumWidth(460)

        layout = QVBoxLayout(self)
        date_label = QLabel(f"Tanggal: {report_date.strftime('%d-%m-%Y')}")
        date_label.setStyleSheet("font-weight: 600;")
        summary = QLabel(
            f"Transaksi berhasil: {sales_count}    |    "
            f"Total penjualan: {rupiah(sales_total)}"
        )
        summary.setWordWrap(True)
        layout.addWidget(date_label)
        layout.addWidget(summary)
        layout.addWidget(QLabel("Catatan kasir"))

        self.notes_input = QPlainTextEdit()
        self.notes_input.setPlaceholderText(
            "Tulis catatan untuk laporan harian (maksimal 4000 karakter)."
        )
        self.notes_input.setPlainText(notes)
        layout.addWidget(self.notes_input)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel
            | QDialogButtonBox.StandardButton.Save
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class PaymentDialog(QDialog):
    ALL_METHODS = ("CASH", "QRIS_DANA", "QRIS_MIDTRANS", "BANK")

    def __init__(self, total: int, parent=None, enabled_methods=None):
        super().__init__(parent)
        self.setWindowTitle("Pembayaran")
        self.setModal(True)
        self.total = total

        if enabled_methods is None:
            methods = list(self.ALL_METHODS)
        else:
            methods = [m for m in self.ALL_METHODS if m in set(enabled_methods)]
            if not methods:
                methods = ["CASH"]
        self.enabled_methods = methods

        method_labels = {
            "CASH": "Tunai",
            "QRIS_DANA": "QRIS DANA",
            "QRIS_MIDTRANS": "QRIS Midtrans",
            "BANK": "TF (m Banking)",
        }

        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.method_input = QComboBox()
        for code in methods:
            self.method_input.addItem(method_labels[code], code)
        self.amount_input = QLineEdit(str(total))
        self.amount_input.setPlaceholderText("Nominal yang diterima")
        form.addRow("Total tagihan", QLabel(rupiah(total)))
        form.addRow("Metode", self.method_input)
        form.addRow("Dibayar (Rp)", self.amount_input)
        layout.addLayout(form)

        self.qr_panel = QFrame()
        self.qr_panel.setStyleSheet(
            "QFrame#qrDemoPanel { background: white; border: 1px solid #e2e8f0; "
            "border-radius: 10px; }"
            "QLabel { border: none; background: transparent; }"
        )
        self.qr_panel.setObjectName("qrDemoPanel")
        qr_layout = QVBoxLayout(self.qr_panel)
        self.qr_image = QLabel()
        self.qr_image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.qr_image.setFixedSize(220, 220)
        self.qr_title = QLabel()
        self.qr_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.qr_title.setStyleSheet("font-size: 15px; font-weight: 700;")
        self.qr_notice = QLabel(
            "Gambar demo saja. Belum dapat dipindai untuk pembayaran atau "
            "memverifikasi transaksi. Integrasi gateway direncanakan pada v1.2."
        )
        self.qr_notice.setWordWrap(True)
        self.qr_notice.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.qr_notice.setStyleSheet("color: #fdba74;")
        qr_layout.addWidget(self.qr_image, alignment=Qt.AlignmentFlag.AlignCenter)
        qr_layout.addWidget(self.qr_title)
        qr_layout.addWidget(self.qr_notice)
        layout.addWidget(self.qr_panel)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel
            | QDialogButtonBox.StandardButton.Ok
        )
        self.confirm_button = self.buttons.button(
            QDialogButtonBox.StandardButton.Ok
        )
        self.confirm_button.setText("Konfirmasi Tunai")
        self.buttons.accepted.connect(self._validate_and_accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        layout.addWidget(
            create_copyright_label(self),
            alignment=Qt.AlignmentFlag.AlignRight,
        )
        self.method_input.currentIndexChanged.connect(self._update_method_display)
        self._update_method_display()

    def payment(self) -> tuple[str, int]:
        return self.method_input.currentData(), int(self.amount_input.text())

    def _update_method_display(self):
        method = self.method_input.currentData()
        is_cash = method == "CASH"
        is_qris = method == "QRIS_MIDTRANS"
        self.qr_panel.setVisible(not is_cash)
        self.amount_input.setEnabled(is_cash or is_qris)
        self.confirm_button.setEnabled(is_cash or is_qris)

        if is_cash:
            self.confirm_button.setText("Konfirmasi Tunai")
            return
        if is_qris:
            self.amount_input.setText(str(self.total))
            self.confirm_button.setText("Lanjutkan ke QRIS")
            self.qr_title.setText("QRIS")
            self.qr_image.setPixmap(_make_demo_qr_pixmap("QRIS"))
            self.qr_notice.setText(
                "Pilih 'Lanjutkan ke QRIS' untuk membuat QR code pembayaran."
            )
            return

        self.amount_input.setText(str(self.total))
        method_names = {
            "QRIS_DANA": "QRIS DANA",
            "BANK": "TF (m BANKING)",
        }
        self.qr_title.setText(f"QR {method_names.get(method, method)} · DEMO")
        self.qr_image.setPixmap(_make_demo_qr_pixmap(method))
        self.confirm_button.setText("Belum tersedia")

    def _validate_and_accept(self):
        method = self.method_input.currentData()
        if method == "CASH":
            try:
                amount = int(self.amount_input.text())
            except ValueError:
                QMessageBox.warning(self, "Nominal tidak valid", "Masukkan nominal berupa angka.")
                return
            if amount < self.total:
                QMessageBox.warning(
                    self,
                    "Pembayaran kurang",
                    "Nominal pembayaran harus sama dengan atau lebih dari total tagihan.",
                )
                return
            self.accept()
        elif method == "QRIS_MIDTRANS":
            self.amount_input.setText(str(self.total))
            self.accept()
        else:
            QMessageBox.information(
                self,
                "Belum tersedia",
                f"Metode {method} belum tersedia. Silakan pilih Tunai atau QRIS.",
            )


class QRISPaymentDialog(QDialog):
    payment_completed = Signal(dict)

    def __init__(
        self,
        order_id: str,
        total: int,
        qr_base64: str,
        qr_content_type: str,
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Pembayaran QRIS")
        self.setModal(True)
        self.setMinimumWidth(380)
        self.order_id = order_id
        self.total = total
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(3000)
        self._poll_timer.timeout.connect(self._poll_payment_status)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        title = QLabel(f"Total: {rupiah(total)}")
        title.setStyleSheet("font-size: 20px; font-weight: 700; color: #ffffff;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        self.qr_label = QLabel()
        self.qr_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.qr_label.setFixedSize(260, 260)
        self._set_qr_image(qr_base64, qr_content_type)
        layout.addWidget(self.qr_label, alignment=Qt.AlignmentFlag.AlignCenter)

        self.status_label = QLabel("Menunggu pembayaran QRIS...")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setStyleSheet("font-size: 14px; color: #e4e4e7;")
        layout.addWidget(self.status_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setFixedHeight(4)
        layout.addWidget(self.progress_bar)

        self.cancel_button = QPushButton("Batal")
        self.cancel_button.setStyleSheet(
            "QPushButton { background: #dc2626; color: white; border: none; "
            "border-radius: 8px; padding: 10px 20px; font-weight: 600; }"
            "QPushButton:hover { background: #ef4444; }"
        )
        self.cancel_button.clicked.connect(self._cancel_payment)
        layout.addWidget(self.cancel_button, alignment=Qt.AlignmentFlag.AlignCenter)

        layout.addWidget(
            create_copyright_label(self),
            alignment=Qt.AlignmentFlag.AlignRight,
        )

        self._poll_timer.start()

    def _set_qr_image(self, base64_str: str, content_type: str):
        import base64
        logger.debug("Decoding QR: content_type=%s, base64_len=%s", content_type, len(base64_str))
        try:
            image_data = base64.b64decode(base64_str)
            logger.debug("Decoded image data length: %s", len(image_data))
            image = QImage.fromData(image_data, content_type.encode("ascii"))
            if image.isNull():
                self.qr_label.setText("Gagal memuat QR code")
                logger.debug("QImage is null!")
                return
            logger.debug("QImage size: %s", image.size())
            pixmap = QPixmap.fromImage(image).scaled(
                260, 260,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self.qr_label.setPixmap(pixmap)
            logger.debug("QR code set successfully")
        except Exception as e:
            logger.debug("Error decoding QR: %s", e)
            self.qr_label.setText(f"Error: {e}")

    def _poll_payment_status(self):
        self.status_label.setText("Memeriksa status pembayaran...")
        try:
            from app.services.payment_service import PaymentService
            service = PaymentService()
            result = asyncio.run(service.check_payment_status(self.order_id))
            if result.get("paid"):
                self._poll_timer.stop()
                self.payment_completed.emit(result)
                self.accept()
            elif result.get("status") in ("failed", "cancelled", "expired"):
                self._poll_timer.stop()
                self.status_label.setText(f"Pembayaran {result.get('status')}")
                QMessageBox.warning(self, "Pembayaran Gagal", f"Status: {result.get('status')}")
                self.reject()
        except Exception as exc:
            self.status_label.setText(f"Error: {exc}")

    def _cancel_payment(self):
        self._poll_timer.stop()
        self.reject()

    def closeEvent(self, event):
        self._poll_timer.stop()
        super().closeEvent(event)


def _make_demo_qr_pixmap(method: str, size: int = 220) -> QPixmap:
    modules = 29
    quiet_zone = 2
    cell_size = size // (modules + quiet_zone * 2)
    image_size = cell_size * (modules + quiet_zone * 2)
    image = QImage(image_size, image_size, QImage.Format.Format_RGB32)
    image.fill(QColor("white"))
    painter = QPainter(image)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#111827"))

    seed = sha256(f"POS-DEMO-{method}".encode("ascii")).digest()
    bits = [
        (seed[index % len(seed)] >> (index % 8)) & 1
        for index in range(modules * modules)
    ]
    matrix = [
        [bits[row * modules + column] for column in range(modules)]
        for row in range(modules)
    ]

    def finder_pattern(origin_x: int, origin_y: int):
        for y in range(7):
            for x in range(7):
                matrix[origin_y + y][origin_x + x] = int(
                    x in (0, 6)
                    or y in (0, 6)
                    or (2 <= x <= 4 and 2 <= y <= 4)
                )

    finder_pattern(0, 0)
    finder_pattern(modules - 7, 0)
    finder_pattern(0, modules - 7)

    for row in range(modules):
        for column in range(modules):
            in_finder = any(
                x <= column < x + 7 and y <= row < y + 7
                for x, y in (
                    (0, 0),
                    (modules - 7, 0),
                    (0, modules - 7),
                )
            )
            if matrix[row][column] and not in_finder:
                painter.drawRect(
                    (column + quiet_zone) * cell_size,
                    (row + quiet_zone) * cell_size,
                    cell_size,
                    cell_size,
                )

    for x, y in (
        (0, 0),
        (modules - 7, 0),
        (0, modules - 7),
    ):
        painter.drawRect(
            (x + quiet_zone) * cell_size,
            (y + quiet_zone) * cell_size,
            7 * cell_size,
            7 * cell_size,
        )
        painter.setBrush(QColor("white"))
        painter.drawRect(
            (x + quiet_zone + 1) * cell_size,
            (y + quiet_zone + 1) * cell_size,
            5 * cell_size,
            5 * cell_size,
        )
        painter.setBrush(QColor("#111827"))
        painter.drawRect(
            (x + quiet_zone + 2) * cell_size,
            (y + quiet_zone + 2) * cell_size,
            3 * cell_size,
            3 * cell_size,
        )

    painter.end()
    return QPixmap.fromImage(image).scaled(
        size,
        size,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.FastTransformation,
    )
