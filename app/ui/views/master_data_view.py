from pathlib import Path
from decimal import Decimal

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QFormLayout,
    QHBoxLayout,
    QGroupBox,
    QLabel,
    QMessageBox,
    QLineEdit,
    QMenu,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy.exc import SQLAlchemyError

from app.core.exceptions import AuthorizationError, ValidationError
from app.models import Product
from app.services.bulk_pricing_service import BulkPricingService
from app.services.master_data_service import MasterDataService
from app.services.product_import_service import (
    PRODUCT_HEADERS,
    ProductImportError,
    ProductImportService,
)
from app.utils.formatters import rupiah
from app.ui.widgets import create_copyright_label, create_dashboard_back_button


class FileDropFrame(QFrame):
    file_dropped = Signal(str)

    def __init__(self, hint: str, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setStyleSheet(
            "QFrame { border: 2px dashed #3f3f4a; border-radius: 8px; "
            "background: #1a1a1e; }"
        )
        layout = QVBoxLayout(self)
        label = QLabel(hint)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setStyleSheet("color: #e4e4e7; border: none;")
        layout.addWidget(label)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            return
        event.ignore()

    def dropEvent(self, event):
        urls = event.mimeData().urls()
        if urls:
            self.file_dropped.emit(urls[0].toLocalFile())
            event.acceptProposedAction()
            return
        event.ignore()


class ProductFileImportDialog(QDialog):
    def __init__(self, mode: str, service: ProductImportService, actor, parent=None):
        super().__init__(parent)
        self.mode = mode
        self.service = service
        self.actor = actor
        titles = {
            "excel": "Import Produk dari Excel",
            "csv": "Import Produk dari CSV",
            "database": "Import Produk dari Database",
        }
        self.setWindowTitle(titles[mode])
        self.setMinimumSize(720, 480)

        layout = QVBoxLayout(self)
        descriptions = {
            "excel": (
                "Pilih file .xlsx dengan kolom sesuai template. SKU yang sudah "
                "ada akan memperbarui informasi produk, tetapi stok tetap."
            ),
            "csv": (
                "Pilih file .csv UTF-8 dengan kolom sesuai template Excel. SKU "
                "yang sudah ada akan diperbarui tanpa mengubah stok."
            ),
            "database": (
                "Pilih file database SQLite POS (.db, .sqlite, .sqlite3). "
                "Kategori, produk, dan satuan yang diperlukan produk akan "
                "digabungkan; transaksi dan pengguna tidak diimpor."
            ),
        }
        description = QLabel(descriptions[mode])
        description.setWordWrap(True)
        layout.addWidget(description)

        self.drop_frame = FileDropFrame("Tarik dan lepas file di sini", self)
        self.drop_frame.setMinimumHeight(72)
        self.drop_frame.file_dropped.connect(self._set_file)
        layout.addWidget(self.drop_frame)

        file_row = QHBoxLayout()
        self.file_input = QLineEdit()
        self.file_input.setReadOnly(True)
        self.file_input.setPlaceholderText("Pilih file untuk melihat pratinjau")
        file_row.addWidget(self.file_input, 1)
        self.browse_button = QPushButton("Browse...")
        self.browse_button.clicked.connect(self._browse_file)
        file_row.addWidget(self.browse_button)
        layout.addLayout(file_row)

        self.preview_table = QTableWidget(0, len(PRODUCT_HEADERS))
        self.preview_table.setHorizontalHeaderLabels(list(PRODUCT_HEADERS))
        self.preview_table.setEditTriggers(
            QTableWidget.EditTrigger.NoEditTriggers
        )
        self.preview_table.setAlternatingRowColors(True)
        layout.addWidget(self.preview_table, 1)
        self.status_label = QLabel("Pilih file untuk menampilkan pratinjau.")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        actions = QHBoxLayout()
        actions.addStretch(1)
        self.import_button = QPushButton("Import")
        self.import_button.setStyleSheet(
            "QPushButton { background: #16a34a; color: white; border: none; "
            "border-radius: 8px; padding: 9px 16px; font-weight: 600; }"
        )
        self.import_button.setEnabled(False)
        self.import_button.clicked.connect(self._import_file)
        self.cancel_button = QPushButton("Tutup")
        self.cancel_button.clicked.connect(self.reject)
        actions.addWidget(self.import_button)
        actions.addWidget(self.cancel_button)
        layout.addLayout(actions)

    def _browse_file(self):
        filters = {
            "excel": "Excel Workbook (*.xlsx)",
            "csv": "CSV (*.csv)",
            "database": "SQLite Database (*.db *.sqlite *.sqlite3)",
        }
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Pilih File",
            "",
            filters[self.mode],
        )
        if path:
            self._set_file(path)

    def _set_file(self, file_path: str):
        self.file_input.setText(file_path)
        try:
            if self.mode == "database":
                records = self.service.preview_database(file_path)
            else:
                records = self.service.preview(file_path)
        except (OSError, ProductImportError, ValueError) as exc:
            self.preview_table.setRowCount(0)
            self.status_label.setText(str(exc))
            self.import_button.setEnabled(False)
            return
        self.preview_table.setRowCount(min(len(records), 100))
        for row_index, record in enumerate(records[:100]):
            for column_index, header in enumerate(PRODUCT_HEADERS):
                self.preview_table.setItem(
                    row_index,
                    column_index,
                    QTableWidgetItem(str(record.get(header, "") or "")),
                )
        self.preview_table.resizeColumnsToContents()
        self.status_label.setText(
            f"{len(records)} baris siap dipratinjau"
            + (" (maksimal 100 baris ditampilkan)." if len(records) > 100 else ".")
        )
        self.import_button.setEnabled(bool(records))

    def _import_file(self):
        file_path = self.file_input.text()
        if not file_path:
            return
        try:
            result = (
                self.service.import_database(self.actor, file_path)
                if self.mode == "database"
                else self.service.import_file(self.actor, file_path)
            )
        except (ProductImportError, SQLAlchemyError) as exc:
            QMessageBox.warning(self, "Import gagal", str(exc))
            return
        if result["errors"]:
            QMessageBox.warning(
                self,
                "Data import tidak valid",
                "\n".join(result["errors"][:20]),
            )
            return
        QMessageBox.information(
            self,
            "Import selesai",
            f"Produk baru: {result['created']}\n"
            f"Produk diperbarui: {result['updated']}\n"
            "Stok produk yang sudah ada tidak diubah.",
        )
        self.accept()


class EditExcelDialog(QDialog):
    def __init__(self, service: ProductImportService, actor, parent=None):
        super().__init__(parent)
        self.service = service
        self.actor = actor
        self.setWindowTitle("Edit Produk dengan Excel")
        self.setMinimumWidth(560)

        layout = QVBoxLayout(self)
        instructions = QLabel(
            "Ekspor data produk ke template Excel, edit menggunakan Excel, "
            "lalu pilih file yang sudah diedit untuk mengimpor perubahan. "
            "Kolom stok hanya digunakan untuk produk baru."
        )
        instructions.setWordWrap(True)
        layout.addWidget(instructions)

        export_row = QHBoxLayout()
        self.export_path_input = QLineEdit()
        self.export_path_input.setPlaceholderText("Lokasi template .xlsx")
        export_row.addWidget(self.export_path_input, 1)
        export_browse = QPushButton("Lokasi...")
        export_browse.clicked.connect(self._browse_export_path)
        export_row.addWidget(export_browse)
        layout.addLayout(export_row)
        self.export_button = QPushButton("Ekspor Template")
        self.export_button.clicked.connect(self._export_template)
        layout.addWidget(self.export_button)

        self.edited_file_input = QLineEdit()
        self.edited_file_input.setReadOnly(True)
        self.edited_file_input.setPlaceholderText("Pilih file Excel hasil edit")
        layout.addWidget(self.edited_file_input)
        choose_edited = QPushButton("Pilih File Excel Hasil Edit...")
        choose_edited.clicked.connect(self._browse_edited_file)
        layout.addWidget(choose_edited)

        actions = QHBoxLayout()
        actions.addStretch(1)
        self.import_button = QPushButton("Import Perubahan")
        self.import_button.setEnabled(False)
        self.import_button.clicked.connect(self._import_edited_file)
        self.close_button = QPushButton("Tutup")
        self.close_button.clicked.connect(self.reject)
        actions.addWidget(self.import_button)
        actions.addWidget(self.close_button)
        layout.addLayout(actions)

    def _browse_export_path(self):
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Simpan Template Produk",
            "produk.xlsx",
            "Excel Workbook (*.xlsx)",
        )
        if path:
            output = Path(path)
            if output.suffix.casefold() != ".xlsx":
                output = output.with_suffix(".xlsx")
            self.export_path_input.setText(str(output))

    def _export_template(self):
        path = self.export_path_input.text().strip()
        if not path:
            self._browse_export_path()
            path = self.export_path_input.text().strip()
        if not path:
            return
        try:
            saved_path = self.service.export_template(path)
        except (OSError, SQLAlchemyError, ValueError) as exc:
            QMessageBox.warning(self, "Template gagal diekspor", str(exc))
            return
        QMessageBox.information(
            self,
            "Template diekspor",
            f"Template tersimpan di:\n{saved_path}",
        )

    def _browse_edited_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Pilih Excel Hasil Edit",
            "",
            "Excel Workbook (*.xlsx)",
        )
        if not path:
            return
        self.edited_file_input.setText(path)
        self.import_button.setEnabled(True)

    def _import_edited_file(self):
        path = self.edited_file_input.text()
        if not path:
            return
        try:
            result = self.service.import_file(self.actor, path)
        except (ProductImportError, SQLAlchemyError) as exc:
            QMessageBox.warning(self, "Import gagal", str(exc))
            return
        if result["errors"]:
            QMessageBox.warning(
                self,
                "Data import tidak valid",
                "\n".join(result["errors"][:20]),
            )
            return
        QMessageBox.information(
            self,
            "Import selesai",
            f"Produk baru: {result['created']}\n"
            f"Produk diperbarui: {result['updated']}\n"
            "Stok produk yang sudah ada tidak diubah.",
        )
        self.accept()


class BulkTierRow(QWidget):
    def __init__(self, label_text, get_regular_price, service, parent=None):
        super().__init__(parent)
        self._get_regular_price = get_regular_price
        self._service = service
        self.pricing_mode = "PERCENT"
        self._syncing = False

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.active_checkbox = QCheckBox(label_text)
        layout.addWidget(self.active_checkbox)
        layout.addWidget(QLabel("Qty ≥"))
        self.threshold_input = QSpinBox()
        self.threshold_input.setRange(1, 2_000_000_000)
        self.threshold_input.setValue(1)
        layout.addWidget(self.threshold_input)
        layout.addWidget(QLabel("Harga"))
        self.price_input = QDoubleSpinBox()
        self.price_input.setDecimals(0)
        self.price_input.setRange(0, 2_000_000_000)
        self.price_input.setGroupSeparatorShown(True)
        self.price_input.setSingleStep(500)
        layout.addWidget(self.price_input)
        layout.addWidget(QLabel("Diskon"))
        self.discount_input = QDoubleSpinBox()
        self.discount_input.setDecimals(2)
        self.discount_input.setRange(0.01, 100)
        self.discount_input.setSingleStep(1)
        self.discount_input.setSuffix("%")
        layout.addWidget(self.discount_input)
        layout.addStretch(1)

        self.price_input.valueChanged.connect(self._price_changed)
        self.discount_input.valueChanged.connect(self._discount_changed)

    def set_inputs_enabled(self, enabled: bool):
        for widget in (
            self.threshold_input,
            self.price_input,
            self.discount_input,
        ):
            widget.setEnabled(enabled)

    def _compute_price(self, percent: float) -> int:
        if self._service is None:
            return 0
        regular_price = self._get_regular_price()
        if regular_price <= 0:
            return 0
        return self._service.special_price(
            regular_price,
            Decimal(str(percent)),
        )

    def load_tier(
        self,
        quantity_threshold: int,
        discount_percent,
        special_price: int,
        pricing_mode: str,
    ):
        self._syncing = True
        self.threshold_input.setValue(quantity_threshold)
        self.pricing_mode = pricing_mode
        if pricing_mode == "PRICE":
            self.price_input.setValue(special_price)
            regular_price = self._get_regular_price()
            percent = (
                self._service.discount_percent_for_price(
                    regular_price,
                    special_price,
                )
                if self._service is not None and regular_price > 0
                else Decimal("1")
            )
            self.discount_input.setValue(float(percent))
        else:
            self.discount_input.setValue(float(discount_percent))
            self.price_input.setValue(
                self._compute_price(float(discount_percent))
            )
        self._syncing = False

    def load_default(self, quantity_threshold: int, discount_percent: float):
        self._syncing = True
        self.threshold_input.setValue(quantity_threshold)
        self.pricing_mode = "PERCENT"
        self.discount_input.setValue(discount_percent)
        self.price_input.setValue(self._compute_price(discount_percent))
        self._syncing = False

    def recompute_price(self):
        if self._syncing or self.pricing_mode != "PERCENT":
            return
        self._syncing = True
        self.price_input.setValue(
            self._compute_price(self.discount_input.value())
        )
        self._syncing = False

    def _price_changed(self, value: float):
        if self._syncing:
            return
        regular_price = self._get_regular_price()
        if regular_price <= 0 or self._service is None:
            return
        self.pricing_mode = "PRICE"
        percent = self._service.discount_percent_for_price(
            regular_price,
            int(value),
        )
        if percent > 0:
            self._syncing = True
            self.discount_input.setValue(float(percent))
            self._syncing = False

    def _discount_changed(self, _value: float):
        if self._syncing:
            return
        self.pricing_mode = "PERCENT"
        self.recompute_price()

    def tier_data(self) -> dict:
        return {
            "quantity_threshold": self.threshold_input.value(),
            "discount_percent": Decimal(str(self.discount_input.value())),
            "special_price": int(self.price_input.value()),
            "pricing_mode": self.pricing_mode,
        }


BULK_TIER_DEFAULTS = (
    ("Tingkat 1", 2, True, 2.0),
    ("Tingkat 2", 3, True, 5.0),
    ("Tingkat 3", 5, False, 10.0),
)


class BulkPriceDialog(QDialog):
    def __init__(
        self,
        service: BulkPricingService,
        actor,
        products,
        parent=None,
    ):
        super().__init__(parent)
        self.service = service
        self.actor = actor
        self.products = products
        self.setWindowTitle("Harga Spesial Partai")
        self.setMinimumWidth(560)

        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.product_input = QComboBox()
        for product in products:
            self.product_input.addItem(
                f"{product.name} ({product.sku})",
                product.id,
            )
        self.product_input.currentIndexChanged.connect(self._load_rule)
        form.addRow("Produk", self.product_input)

        self.regular_price_label = QLabel("-")
        self.regular_price_label.setStyleSheet(
            "font-weight: 600; color: #e4e4e7;"
        )
        form.addRow("Harga satuan saat ini", self.regular_price_label)

        quantity_hint = QLabel(
            "Harga berlaku berjenjang: saat qty dibeli, ambang tingkat "
            "tertinggi yang tercapai dipakai (contoh ambang 2 dan 3 → "
            "qty 4 memakai harga ambang 3). Maksimal 3 tingkat per produk."
        )
        quantity_hint.setWordWrap(True)
        quantity_hint.setStyleSheet("color: #a1a1aa;")
        form.addRow("", quantity_hint)
        layout.addLayout(form)

        tiers_form = QFormLayout()
        self.tier_rows: list[BulkTierRow] = []
        for label, default_qty, active, default_disc in BULK_TIER_DEFAULTS:
            row = BulkTierRow(
                label,
                lambda: self._selected_regular_price(),
                self.service,
            )
            row.active_checkbox.setChecked(active)
            row.load_default(default_qty, default_disc)
            self.tier_rows.append(row)
            tiers_form.addRow(row)
        layout.addLayout(tiers_form)

        self.rules_table = QTableWidget(0, 4)
        self.rules_table.setHorizontalHeaderLabels(
            ["Produk", "Berlaku qty >=", "Diskon", "Harga Spesial"]
        )
        self.rules_table.setEditTriggers(
            QTableWidget.EditTrigger.NoEditTriggers
        )
        self.rules_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self.rules_table.cellClicked.connect(self._select_rule_from_table)
        self.rules_table.setToolTip(
            "Klik baris untuk memilih produk dan mengubah semua tingkatnya."
        )
        self.rules_table.setMaximumHeight(180)
        layout.addWidget(self.rules_table)

        actions = QHBoxLayout()
        self.delete_button = QPushButton("Hapus Harga Spesial")
        self.delete_button.clicked.connect(self._delete_rule)
        actions.addWidget(self.delete_button)
        actions.addStretch(1)
        self.save_button = QPushButton("Simpan")
        self.save_button.setStyleSheet(
            "QPushButton { background: #007acc; color: white; border: none; "
            "border-radius: 8px; padding: 9px 14px; font-weight: 600; }"
        )
        self.save_button.clicked.connect(self._save_rule)
        close_button = QPushButton("Tutup")
        close_button.clicked.connect(self.reject)
        actions.addWidget(self.save_button)
        actions.addWidget(close_button)
        layout.addLayout(actions)
        self._refresh_rules()
        self._load_rule()

    def _selected_product(self):
        product_id = self.product_input.currentData()
        return next(
            (product for product in self.products if product.id == product_id),
            None,
        )

    def _selected_regular_price(self) -> int:
        product = self._selected_product()
        return product.selling_price if product is not None else 0

    def _load_rule(self, *_args):
        product = self._selected_product()
        if product is None:
            self.delete_button.setEnabled(False)
            self.save_button.setEnabled(False)
            self.regular_price_label.setText("-")
            return
        self.save_button.setEnabled(True)
        self.regular_price_label.setText(rupiah(product.selling_price))
        try:
            rules = self.service.rules_for_product(product.id)
        except SQLAlchemyError as exc:
            QMessageBox.warning(self, "Harga spesial gagal dimuat", str(exc))
            return
        self.delete_button.setEnabled(bool(rules))
        for row, rule in zip(self.tier_rows, rules):
            row.active_checkbox.setChecked(True)
            row.load_tier(
                rule.quantity_threshold,
                rule.discount_percent,
                rule.special_price,
                rule.pricing_mode,
            )
        for row, (_label, default_qty, active, default_disc) in zip(
            self.tier_rows[len(rules):],
            BULK_TIER_DEFAULTS[len(rules):],
        ):
            row.active_checkbox.setChecked(active if not rules else False)
            row.load_default(default_qty, default_disc)

    def _refresh_rules(self):
        try:
            rules = self.service.rules()
        except SQLAlchemyError as exc:
            QMessageBox.warning(self, "Harga spesial gagal dimuat", str(exc))
            return
        self.rules_table.setRowCount(len(rules))
        for row, rule in enumerate(rules):
            product = rule.product
            values = (
                f"{product.name} ({product.sku})",
                str(rule.quantity_threshold),
                f"{rule.discount_percent}%",
                rupiah(self.service.effective_special_price(product, rule)),
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 0:
                    item.setData(Qt.ItemDataRole.UserRole, product.id)
                    item.setToolTip("Klik untuk memilih produk ini.")
                self.rules_table.setItem(row, column, item)
        self.rules_table.resizeColumnsToContents()

    def _select_rule_from_table(self, row: int, _column: int):
        product_item = self.rules_table.item(row, 0)
        if product_item is None:
            return
        product_id = product_item.data(Qt.ItemDataRole.UserRole)
        index = self.product_input.findData(product_id)
        if index >= 0:
            self.product_input.setCurrentIndex(index)

    def _active_tiers(self) -> list[dict]:
        tiers = [row.tier_data() for row in self.tier_rows if row.active_checkbox.isChecked()]
        tiers.sort(key=lambda tier: tier["quantity_threshold"])
        return tiers

    def _save_rule(self):
        product = self._selected_product()
        if product is None:
            return
        tiers = self._active_tiers()
        if not tiers:
            QMessageBox.warning(
                self,
                "Tingkat belum dipilih",
                "Aktifkan minimal satu tingkat harga spesial partai.",
            )
            return
        thresholds = [tier["quantity_threshold"] for tier in tiers]
        if len(set(thresholds)) != len(thresholds):
            QMessageBox.warning(
                self,
                "Qty ambang kembar",
                "Setiap tingkat harus berbeda qty ambangnya "
                "(contoh 2, 3, dan 5).",
            )
            return
        try:
            self.service.save_rules(
                actor=self.actor,
                product_id=product.id,
                tiers=tiers,
            )
        except (AuthorizationError, ValidationError, SQLAlchemyError) as exc:
            QMessageBox.warning(self, "Harga spesial gagal disimpan", str(exc))
            return
        self._refresh_rules()
        self.delete_button.setEnabled(True)
        summary = ", ".join(
            f"≥{tier['quantity_threshold']} → {rupiah(tier['special_price'])}"
            for tier in tiers
        )
        QMessageBox.information(
            self,
            "Harga spesial tersimpan",
            f"Harga {product.name} berjenjang: {summary}.",
        )

    def _delete_rule(self):
        product = self._selected_product()
        if product is None:
            return
        try:
            deleted = self.service.delete_rule(self.actor, product.id)
        except (AuthorizationError, SQLAlchemyError) as exc:
            QMessageBox.warning(self, "Harga spesial gagal dihapus", str(exc))
            return
        if deleted:
            self._refresh_rules()
            self.delete_button.setEnabled(False)
            self._load_rule()
            QMessageBox.information(
                self,
                "Harga spesial dihapus",
                f"Semua tingkat harga spesial {product.name} sudah dihapus.",
            )


class CategoryBatchDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Tambah Kategori")
        self.setMinimumWidth(380)

        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.category_inputs = []
        for index in range(1, 6):
            category_input = QLineEdit()
            category_input.setMaxLength(100)
            category_input.setPlaceholderText(f"Nama kategori {index}")
            self.category_inputs.append(category_input)
            form.addRow(f"Kategori {index}", category_input)
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

    def category_names(self) -> list[str]:
        return [field.text().strip() for field in self.category_inputs]

    def _validate_and_accept(self):
        if not any(self.category_names()):
            QMessageBox.warning(
                self,
                "Kategori belum diisi",
                "Isi minimal satu nama kategori.",
            )
            return
        self.accept()


class ProductFormDialog(QDialog):
    def __init__(
        self,
        categories,
        units,
        suppliers,
        product: Product | None = None,
        bulk_pricing_service: BulkPricingService | None = None,
        bulk_rules=None,
        parent=None,
    ):
        super().__init__(parent)
        self.product = product
        self.bulk_pricing_service = bulk_pricing_service
        self.bulk_rules = list(bulk_rules or [])
        self.setWindowTitle("Ubah Produk" if product else "Tambah Produk")
        self.setMinimumWidth(520)

        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.sku_input = self._new_line_edit("SKU unik, contoh SKU-001")
        self.barcode_input = self._new_line_edit("Scan atau ketik barcode (opsional)")
        self.name_input = self._new_line_edit("Nama produk")
        self.category_input = QComboBox()
        self.category_input.addItem("Pilih kategori", None)
        for category in categories:
            self.category_input.addItem(category.name, category.id)
        self.unit_input = QComboBox()
        self.unit_input.addItem("Pilih satuan", None)
        for unit in units:
            self.unit_input.addItem(f"{unit.name} ({unit.symbol})", unit.id)
        self.supplier_input = QComboBox()
        self.supplier_input.addItem("Tidak ditentukan", None)
        for supplier in suppliers:
            self.supplier_input.addItem(
                f"{supplier.name} ({supplier.code})",
                supplier.id,
            )

        self.purchase_price = self._money_input()
        self.selling_price = self._money_input()
        self.stock_qty = QSpinBox()
        self.stock_qty.setRange(0, 2_000_000_000)
        self.min_stock = QSpinBox()
        self.min_stock.setRange(0, 2_000_000_000)
        self.active_checkbox = QCheckBox("Aktif dan dapat dicari kasir")
        self.active_checkbox.setChecked(True)

        form.addRow("SKU *", self.sku_input)
        form.addRow("Barcode", self.barcode_input)
        form.addRow("Nama produk *", self.name_input)
        form.addRow("Kategori *", self.category_input)
        form.addRow("Satuan *", self.unit_input)
        form.addRow("Supplier pilihan", self.supplier_input)
        form.addRow("Harga modal (Rp) *", self.purchase_price)
        form.addRow("Harga jual (Rp) *", self.selling_price)
        form.addRow("Stok awal", self.stock_qty)
        form.addRow("Batas minimum stok", self.min_stock)
        form.addRow(self.active_checkbox)
        layout.addLayout(form)

        bulk_group = QGroupBox("Harga Spesial Partai — Maks. 3 Tingkat (opsional)")
        bulk_form = QFormLayout(bulk_group)
        group_margins = bulk_form.contentsMargins()
        bulk_form.setContentsMargins(
            0,
            group_margins.top(),
            group_margins.right(),
            group_margins.bottom(),
        )
        self.bulk_enabled_input = QCheckBox("Aktifkan harga spesial partai")
        bulk_form.addRow(self.bulk_enabled_input)
        self.bulk_flow_label = QLabel()
        self.bulk_flow_label.setWordWrap(True)
        self.bulk_flow_label.setStyleSheet(
            "color: #93c5fd; background: #12263a; padding: 8px; "
            "border-radius: 6px;"
        )
        bulk_form.addRow("Alur harga", self.bulk_flow_label)
        self.bulk_regular_price_label = QLabel()
        self.bulk_regular_price_label.setStyleSheet(
            "font-weight: 600; color: #e4e4e7;"
        )
        bulk_form.addRow("Harga satuan normal", self.bulk_regular_price_label)
        self.bulk_tier_rows: list[BulkTierRow] = []
        for label, default_qty, active, default_disc in BULK_TIER_DEFAULTS:
            row = BulkTierRow(
                label,
                lambda: int(self.selling_price.value()),
                self.bulk_pricing_service,
            )
            row.active_checkbox.setChecked(active)
            row.load_default(default_qty, default_disc)
            row.threshold_input.valueChanged.connect(
                self._update_bulk_price_reference
            )
            row.active_checkbox.toggled.connect(
                self._update_bulk_price_reference
            )
            self.bulk_tier_rows.append(row)
            bulk_form.addRow(row)
        bulk_help = QLabel(
            "Saat qty mencapai ambang suatu tingkat, harga tingkat "
            "tertinggi yang tercapai yang dipakai. Harga tiap tingkat "
            "harus lebih rendah dari harga satuan normal; isi harga "
            "spesial atau persentase potongan, nilai lain dihitung otomatis."
        )
        bulk_help.setWordWrap(True)
        bulk_help.setStyleSheet("color: #a1a1aa;")
        bulk_form.addRow("", bulk_help)
        self.bulk_detail_widgets: list[QWidget] = [
            self.bulk_flow_label,
            self.bulk_regular_price_label,
            *self.bulk_tier_rows,
            bulk_help,
        ]
        self.bulk_enabled_input.toggled.connect(
            self._set_bulk_inputs_enabled
        )
        self.selling_price.valueChanged.connect(self._update_bulk_price_reference)
        layout.addWidget(bulk_group)

        note = QLabel(
            "Stok awal hanya diisi saat produk baru dibuat. Perubahan stok "
            "produk yang sudah ada dilakukan lewat transaksi stok agar tercatat."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: #a1a1aa;")
        layout.addWidget(note)

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

        if product is not None:
            self.sku_input.setText(product.sku)
            self.barcode_input.setText(product.barcode or "")
            self.name_input.setText(product.name)
            self._select_data(self.category_input, product.category_id)
            self._select_data(self.unit_input, product.unit_id)
            self._select_data(self.supplier_input, product.supplier_id)
            self.purchase_price.setValue(product.purchase_price)
            self.selling_price.setValue(product.selling_price)
            self.stock_qty.setValue(product.stock_qty)
            self.stock_qty.setEnabled(False)
            self.min_stock.setValue(product.min_stock)
            self.active_checkbox.setChecked(product.is_active)
        self._load_bulk_rules()

    def _validate_and_accept(self):
        if not self.sku_input.text().strip():
            QMessageBox.warning(self, "SKU wajib", "Isi SKU produk.")
            self.sku_input.setFocus()
            return
        if not self.name_input.text().strip():
            QMessageBox.warning(self, "Nama wajib", "Isi nama produk.")
            self.name_input.setFocus()
            return
        if self.category_input.currentData() is None:
            QMessageBox.warning(self, "Kategori wajib", "Pilih kategori produk.")
            self.category_input.setFocus()
            return
        if self.unit_input.currentData() is None:
            QMessageBox.warning(self, "Satuan wajib", "Pilih satuan produk.")
            self.unit_input.setFocus()
            return
        if self.bulk_enabled_input.isChecked():
            regular_price = int(self.selling_price.value())
            if regular_price <= 0:
                QMessageBox.warning(
                    self,
                    "Harga jual belum valid",
                    "Isi harga jual lebih dari Rp 0 sebelum mengaktifkan "
                    "harga spesial partai.",
                )
                self.selling_price.setFocus()
                return
            active_rows = [
                row
                for row in self.bulk_tier_rows
                if row.active_checkbox.isChecked()
            ]
            if not active_rows:
                QMessageBox.warning(
                    self,
                    "Tingkat belum dipilih",
                    "Aktifkan minimal satu tingkat harga spesial partai.",
                )
                self.bulk_tier_rows[0].active_checkbox.setFocus()
                return
            thresholds = [
                row.threshold_input.value() for row in active_rows
            ]
            if len(set(thresholds)) != len(thresholds):
                QMessageBox.warning(
                    self,
                    "Qty ambang kembar",
                    "Setiap tingkat harus berbeda qty ambangnya "
                    "(contoh 2, 3, dan 5).",
                )
                return
            for row in active_rows:
                if row.price_input.value() >= regular_price:
                    QMessageBox.warning(
                        self,
                        "Harga spesial belum valid",
                        f"Harga spesial {row.active_checkbox.text()} harus "
                        "lebih rendah dari harga jual normal.",
                    )
                    row.price_input.setFocus()
                    return
        self.accept()

    def _load_bulk_rules(self):
        regular_price = int(self.selling_price.value())
        if self.bulk_rules:
            self.bulk_enabled_input.setChecked(True)
            for row, rule in zip(self.bulk_tier_rows, self.bulk_rules):
                row.active_checkbox.setChecked(True)
                row.load_tier(
                    rule.quantity_threshold,
                    rule.discount_percent,
                    rule.special_price,
                    rule.pricing_mode,
                )
            for row, (_label, default_qty, _active, default_disc) in zip(
                self.bulk_tier_rows[len(self.bulk_rules):],
                BULK_TIER_DEFAULTS[len(self.bulk_rules):],
            ):
                row.active_checkbox.setChecked(False)
                row.load_default(default_qty, default_disc)
        self._set_bulk_inputs_enabled(self.bulk_enabled_input.isChecked())

    def _set_bulk_inputs_enabled(self, enabled: bool):
        for widget in self.bulk_detail_widgets:
            widget.setVisible(enabled)
        for row in self.bulk_tier_rows:
            row.active_checkbox.setEnabled(enabled)
            row.set_inputs_enabled(enabled)
        self._update_bulk_price_reference()

    def _update_bulk_price_reference(self, *_args):
        regular_price = int(self.selling_price.value())
        self.bulk_regular_price_label.setText(rupiah(regular_price))
        parts = [f"qty 1 = {rupiah(regular_price)} (normal)"]
        for row in sorted(
            self.bulk_tier_rows,
            key=lambda tier_row: tier_row.threshold_input.value(),
        ):
            if not row.active_checkbox.isChecked():
                continue
            parts.append(
                f"≥{row.threshold_input.value()} = "
                f"{rupiah(int(row.price_input.value()))}"
            )
        self.bulk_flow_label.setText("; ".join(parts) + ".")
        if not self.bulk_enabled_input.isChecked():
            return
        for row in self.bulk_tier_rows:
            row.recompute_price()

    def _active_tier_data(self) -> list[dict]:
        tiers = [
            row.tier_data()
            for row in self.bulk_tier_rows
            if row.active_checkbox.isChecked()
        ]
        tiers.sort(key=lambda tier: tier["quantity_threshold"])
        return tiers

    @staticmethod
    def _new_line_edit(placeholder: str) -> QLineEdit:
        line_edit = QLineEdit()
        line_edit.setPlaceholderText(placeholder)
        return line_edit

    @staticmethod
    def _money_input():
        field = QDoubleSpinBox()
        field.setDecimals(0)
        field.setRange(0, 2_000_000_000)
        field.setGroupSeparatorShown(True)
        field.setSingleStep(500)
        return field

    @staticmethod
    def _select_data(combo: QComboBox, value):
        index = combo.findData(value)
        if index >= 0:
            combo.setCurrentIndex(index)

    def form_data(self) -> dict:
        return {
            "product_id": self.product.id if self.product else None,
            "sku": self.sku_input.text(),
            "barcode": self.barcode_input.text(),
            "name": self.name_input.text(),
            "category_id": self.category_input.currentData(),
            "unit_id": self.unit_input.currentData(),
            "supplier_id": self.supplier_input.currentData(),
            "purchase_price": int(self.purchase_price.value()),
            "selling_price": int(self.selling_price.value()),
            "stock_qty": self.stock_qty.value(),
            "min_stock": self.min_stock.value(),
            "is_active": self.active_checkbox.isChecked(),
            "bulk_pricing_enabled": self.bulk_enabled_input.isChecked(),
            "bulk_tiers": self._active_tier_data(),
        }


class AddStockDialog(QDialog):
    def __init__(self, product: Product, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Tambah Stok")
        self.setMinimumWidth(360)

        layout = QVBoxLayout(self)
        form = QFormLayout()
        remaining_capacity = 2_000_000_000 - product.stock_qty
        self.product_name_label = QLabel(product.name)
        self.current_stock_label = QLabel(str(product.stock_qty))
        self.additional_stock_input = QSpinBox()
        self.additional_stock_input.setRange(
            1,
            max(1, remaining_capacity),
        )
        self.additional_stock_input.setValue(1)
        self.additional_stock_input.setEnabled(remaining_capacity > 0)
        form.addRow("Nama produk", self.product_name_label)
        form.addRow("Stok saat ini", self.current_stock_label)
        form.addRow("Stok tambahan", self.additional_stock_input)
        layout.addLayout(form)

        self.confirm_button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        self.confirm_button_box.button(
            QDialogButtonBox.StandardButton.Ok
        ).setText("Tambah Stok")
        self.confirm_button_box.button(
            QDialogButtonBox.StandardButton.Ok
        ).setEnabled(remaining_capacity > 0)
        self.confirm_button_box.accepted.connect(self.accept)
        self.confirm_button_box.rejected.connect(self.reject)
        layout.addWidget(self.confirm_button_box)


class MasterDataView(QWidget):
    back_requested = Signal()

    def __init__(self, actor, session, parent=None):
        super().__init__(parent)
        self.actor = actor
        self.service = MasterDataService(session)
        self.import_service = ProductImportService(session)
        self.bulk_pricing_service = BulkPricingService(session)

        root = QVBoxLayout(self)
        root.setContentsMargins(32, 26, 32, 30)
        root.setSpacing(14)

        header = QHBoxLayout()
        back_button = create_dashboard_back_button(self)
        back_button.clicked.connect(self.back_requested.emit)
        title = QLabel("Master Data Produk")
        title.setStyleSheet("font-size: 25px; font-weight: 700; color: #ffffff;")
        header.addWidget(back_button)
        header.addWidget(title)
        header.addStretch(1)
        root.addLayout(header)

        description = QLabel(
            "Kelola produk, kategori, harga, barcode, satuan, dan stok awal. "
            "Produk aktif langsung tersedia pada pencarian kasir."
        )
        description.setWordWrap(True)
        description.setStyleSheet("color: #a1a1aa;")
        root.addWidget(description)

        actions = QHBoxLayout()
        create_button_style = (
            "QPushButton { background: #007acc; color: white; border: none; "
            "border-radius: 8px; padding: 9px 14px; font-weight: 600; }"
            "QPushButton:hover { background: #0098ff; }"
        )
        edit_button_style = (
            "QPushButton { background: #facc15; color: #422006; border: none; "
            "border-radius: 8px; padding: 9px 14px; font-weight: 600; }"
            "QPushButton:hover { background: #eab308; }"
        )
        self.add_category_button = QPushButton("Tambah Kategori")
        self.add_category_button.setStyleSheet(create_button_style)
        self.add_category_button.clicked.connect(self._add_category)
        self.add_product_button = QPushButton("Tambah Produk")
        self.add_product_button.setStyleSheet(create_button_style)
        self.add_product_button.clicked.connect(self._add_product)
        self.bulk_price_button = QPushButton("Harga Spesial")
        self.bulk_price_button.setStyleSheet(create_button_style)
        self.bulk_price_button.clicked.connect(self._open_bulk_price_dialog)
        self.bulk_price_button.setVisible(
            getattr(getattr(actor, "role", None), "name", "").upper() == "OWNER"
        )
        self.import_button = QToolButton()
        self.import_button.setText("Import Data   ▾")
        self.import_button.setPopupMode(
            QToolButton.ToolButtonPopupMode.InstantPopup
        )
        self.import_button.setStyleSheet(
            "QToolButton { background: #007acc; color: white; border: none; "
            "border-radius: 8px; padding: 9px 14px; font-weight: 600; }"
            "QToolButton:hover { background: #0098ff; }"
            "QToolButton:pressed { background: #005995; }"
            "QToolButton::menu-indicator { image: none; }"
        )
        import_menu = QMenu(self.import_button)
        import_menu.addAction(
            "Import Excel",
            lambda _checked=False: self._open_import_dialog("excel"),
        )
        import_menu.addAction(
            "Import database",
            lambda _checked=False: self._open_import_dialog("database"),
        )
        import_menu.addAction(
            "Import CSV",
            lambda _checked=False: self._open_import_dialog("csv"),
        )
        import_menu.addAction(
            "Edit Excel",
            lambda _checked=False: self._open_edit_excel_dialog(),
        )
        self.import_button.setMenu(import_menu)
        self.edit_product_button = QPushButton("Ubah Produk")
        self.edit_product_button.setStyleSheet(edit_button_style)
        self.edit_product_button.clicked.connect(self._edit_selected_product)
        self.delete_product_button = QPushButton("Hapus Produk")
        self.delete_product_button.setStyleSheet(edit_button_style)
        self.delete_product_button.clicked.connect(self._delete_selected_product)
        self.add_stock_button = QPushButton("Tambah Stok")
        self.add_stock_button.setStyleSheet(create_button_style)
        self.add_stock_button.clicked.connect(self._add_stock_to_selected_product)
        self.refresh_button = QPushButton("Muat Ulang")
        self.refresh_button.setStyleSheet(edit_button_style)
        self.refresh_button.clicked.connect(self.refresh_products)
        for button in (
            self.add_category_button,
            self.add_product_button,
            self.import_button,
            self.bulk_price_button,
            self.add_stock_button,
        ):
            actions.addWidget(button)
        actions.addStretch(1)
        actions.addWidget(self.refresh_button)
        actions.addWidget(self.edit_product_button)
        actions.addWidget(self.delete_product_button)
        root.addLayout(actions)

        self.category_label = QLabel()
        root.addWidget(self.category_label)
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText(
            "Cari berdasarkan nama produk, kategori, atau supplier"
        )
        self.search_input.textChanged.connect(
            lambda _text: self.refresh_products()
        )
        root.addWidget(self.search_input)
        self.product_table = QTableWidget(0, 10)
        self.product_table.setHorizontalHeaderLabels(
            [
                "SKU",
                "Barcode",
                "Nama Produk",
                "Kategori",
                "Satuan",
                "Modal",
                "Harga Jual",
                "Supplier",
                "Stok",
                "Status",
            ]
        )
        self.product_table.setEditTriggers(
            QTableWidget.EditTrigger.NoEditTriggers
        )
        self.product_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self.product_table.setSelectionMode(
            QTableWidget.SelectionMode.SingleSelection
        )
        self.product_table.horizontalHeader().setStretchLastSection(True)
        self.product_table.doubleClicked.connect(self._edit_selected_product)
        root.addWidget(self.product_table, 1)
        root.addWidget(
            create_copyright_label(self),
            alignment=Qt.AlignmentFlag.AlignRight,
        )
        self.refresh_products()

    def refresh_products(self):
        try:
            categories = self.service.list_categories()
            units = {unit.id: unit for unit in self.service.list_units()}
            suppliers = {
                supplier.id: supplier
                for supplier in self.service.list_suppliers()
            }
            products = self.service.list_products()
        except SQLAlchemyError as exc:
            QMessageBox.critical(self, "Master data gagal dimuat", str(exc))
            return

        category_names = {category.id: category.name for category in categories}
        self.category_label.setText(
            "Kategori tersedia: "
            + (", ".join(category.name for category in categories) or "belum ada")
        )
        query = self.search_input.text().strip().casefold()
        if query:
            products = [
                product
                for product in products
                if query in product.name.casefold()
                or query in category_names.get(product.category_id, "").casefold()
                or query
                in (
                    suppliers[product.supplier_id].name.casefold()
                    if product.supplier_id in suppliers
                    else ""
                )
            ]
        self.product_table.setRowCount(len(products))
        self.product_ids = []
        for row, product in enumerate(products):
            self.product_ids.append(product.id)
            category = category_names.get(product.category_id, "-")
            unit = units.get(product.unit_id)
            values = (
                product.sku,
                product.barcode or "-",
                product.name,
                category,
                f"{unit.name} ({unit.symbol})" if unit else "-",
                rupiah(product.purchase_price),
                rupiah(product.selling_price),
                suppliers[product.supplier_id].name
                if product.supplier_id in suppliers
                else "-",
                str(product.stock_qty),
                "Aktif" if product.is_active else "Nonaktif",
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.product_table.setItem(row, column, item)
            if not product.is_active:
                for column in range(len(values)):
                    self.product_table.item(row, column).setForeground(
                        Qt.GlobalColor.darkGray
                    )
        self.product_table.resizeColumnsToContents()

    def _add_category(self):
        dialog = CategoryBatchDialog(parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            categories = self.service.create_categories(
                self.actor,
                dialog.category_names(),
            )
        except (AuthorizationError, ValidationError, SQLAlchemyError) as exc:
            QMessageBox.warning(self, "Kategori tidak dapat disimpan", str(exc))
            return
        QMessageBox.information(
            self,
            "Kategori tersimpan",
            f"{len(categories)} kategori berhasil ditambahkan.",
        )
        self.refresh_products()

    def _add_product(self):
        dialog = self._create_product_dialog()
        if dialog is None:
            return
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self._save_form(dialog)

    def _open_import_dialog(self, mode: str):
        dialog = ProductFileImportDialog(
            mode,
            self.import_service,
            self.actor,
            self,
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.refresh_products()

    def _open_edit_excel_dialog(self):
        dialog = EditExcelDialog(
            self.import_service,
            self.actor,
            self,
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.refresh_products()

    def _open_bulk_price_dialog(self):
        try:
            products = self.service.list_products()
        except SQLAlchemyError as exc:
            QMessageBox.warning(self, "Produk gagal dimuat", str(exc))
            return
        dialog = BulkPriceDialog(
            self.bulk_pricing_service,
            self.actor,
            products,
            self,
        )
        dialog.exec()

    def _edit_selected_product(self, *_args):
        row = self.product_table.currentRow()
        if row < 0:
            QMessageBox.information(
                self,
                "Pilih produk",
                "Pilih baris produk yang akan diubah.",
            )
            return
        product = self.service.session.get(Product, self.product_ids[row])
        if product is None:
            QMessageBox.warning(self, "Produk tidak ditemukan", "Muat ulang data.")
            self.refresh_products()
            return
        dialog = self._create_product_dialog(product)
        if dialog is None:
            return
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self._save_form(dialog)

    def _delete_selected_product(self):
        row = self.product_table.currentRow()
        if row < 0:
            QMessageBox.information(
                self,
                "Pilih produk",
                "Pilih produk yang akan dihapus.",
            )
            return
        product_id = self.product_ids[row]
        product_name = self.product_table.item(row, 2).text()
        answer = QMessageBox.question(
            self,
            "Hapus produk",
            f"Produk {product_name} akan dihapus dari data aktif. "
            "Riwayat transaksi tetap tersimpan. Lanjutkan?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self.service.delete_product(self.actor, product_id)
        except (AuthorizationError, ValidationError, SQLAlchemyError) as exc:
            QMessageBox.warning(self, "Produk tidak dapat dihapus", str(exc))
            return
        self.refresh_products()

    def _add_stock_to_selected_product(self):
        row = self.product_table.currentRow()
        if row < 0:
            QMessageBox.information(
                self,
                "Pilih produk",
                "Pilih produk yang akan ditambah stoknya.",
            )
            return

        product = self.service.session.get(Product, self.product_ids[row])
        if product is None or product.deleted_at is not None:
            QMessageBox.warning(
                self,
                "Produk tidak ditemukan",
                "Muat ulang data sebelum menambah stok.",
            )
            self.refresh_products()
            return

        dialog = AddStockDialog(product, parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            updated_product = self.service.add_stock(
                self.actor,
                product.id,
                dialog.additional_stock_input.value(),
            )
        except (AuthorizationError, ValidationError, SQLAlchemyError) as exc:
            QMessageBox.warning(self, "Stok tidak dapat ditambahkan", str(exc))
            return
        self.refresh_products()
        QMessageBox.information(
            self,
            "Stok ditambahkan",
            f"Stok {updated_product.name} sekarang "
            f"{updated_product.stock_qty}.",
        )

    def _create_product_dialog(
        self,
        product: Product | None = None,
    ) -> ProductFormDialog | None:
        try:
            return ProductFormDialog(
                self.service.list_categories(),
                self.service.list_units(),
                self.service.list_suppliers(),
                product=product,
                bulk_pricing_service=self.bulk_pricing_service,
                bulk_rules=(
                    self.bulk_pricing_service.rules_for_product(product.id)
                    if product is not None
                    else []
                ),
                parent=self,
            )
        except SQLAlchemyError as exc:
            QMessageBox.critical(self, "Gagal memuat pilihan produk", str(exc))
            return None

    def _save_form(self, dialog: ProductFormDialog):
        values = dialog.form_data()
        bulk_pricing = {
            key: values.pop(key)
            for key in (
                "bulk_pricing_enabled",
                "bulk_tiers",
            )
        }
        if values["category_id"] is None:
            QMessageBox.warning(self, "Kategori wajib", "Pilih kategori produk.")
            return
        if values["unit_id"] is None:
            QMessageBox.warning(self, "Satuan wajib", "Pilih satuan produk.")
            return
        try:
            product = self.service.save_product(self.actor, **values)
        except (AuthorizationError, ValidationError, SQLAlchemyError) as exc:
            QMessageBox.warning(self, "Produk tidak dapat disimpan", str(exc))
            return
        try:
            if bulk_pricing["bulk_pricing_enabled"]:
                self.bulk_pricing_service.save_rules(
                    actor=self.actor,
                    product_id=product.id,
                    tiers=bulk_pricing["bulk_tiers"],
                )
            else:
                self.bulk_pricing_service.delete_rule(
                    self.actor,
                    product.id,
                )
        except (AuthorizationError, ValidationError, SQLAlchemyError) as exc:
            self.refresh_products()
            QMessageBox.warning(
                self,
                "Produk tersimpan, tetapi aturan harga spesial gagal",
                f"Data produk sudah tersimpan, tetapi aturan harga spesial "
                f"belum diperbarui. Buka kembali produk atau popup Harga "
                f"Spesial untuk memperbaikinya.\n\n{exc}",
            )
            return
        self.refresh_products()
        QMessageBox.information(
            self,
            "Produk tersimpan",
            f"{product.name} ({product.sku}) tersimpan dan dapat dicari kasir "
            "jika statusnya aktif.",
        )
