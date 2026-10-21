from pathlib import Path
import sqlite3

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import persist_env_value, settings as app_settings
from app.core.exceptions import AuthorizationError, ValidationError
from app.models import Category, Product, Unit
from app.services.store_settings_service import StoreSettingsService
from app.services.payment_settings_service import PaymentSettingsService


class StoreSettingsView(QWidget):
    settings_saved = Signal(object)

    def __init__(
        self,
        actor,
        service: StoreSettingsService,
        payment_service: PaymentSettingsService | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.actor = actor
        self.service = service
        self.payment_service = payment_service
        self.logo_source: str | None = None
        self.remove_logo = False
        self.store = None
        self.payment_settings = None
        self._editing = False
        self._syncing_all = False
        self._action_rows: list[tuple[QPushButton, QPushButton, QPushButton]] = []

        # Halaman tab pertama jendela Manajemen Toko: "Pengaturan Toko".
        self.store_tab = QWidget()
        store_layout = QVBoxLayout(self.store_tab)
        store_layout.setContentsMargins(16, 16, 16, 16)
        store_layout.setSpacing(16)

        hint = QLabel(
            "Atur identitas toko (nama, slogan, alamat, WhatsApp, logo, dan "
            "folder snapshot database produk) pada form ini. Klik Ubah lalu "
            "Simpan untuk menyimpan; metode pembayaran kasir diatur pada "
            "tab Seting Pembayaran Kasir."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #a1a1aa;")
        store_layout.addWidget(hint)

        form = QFormLayout()
        self.name_input = QLineEdit()
        self.name_input.setMaxLength(150)
        self.name_input.setPlaceholderText("Nama toko")
        self.slogan_input = QLineEdit()
        self.slogan_input.setMaxLength(200)
        self.slogan_input.setPlaceholderText("Slogan toko")
        self.address_input = QLineEdit()
        self.address_input.setPlaceholderText("Alamat lengkap toko")
        self.whatsapp_input = QLineEdit()
        self.whatsapp_input.setMaxLength(30)
        self.whatsapp_input.setPlaceholderText("Contoh: +62 812 3456 7890")
        form.addRow("Nama toko *", self.name_input)
        form.addRow("Slogan", self.slogan_input)
        form.addRow("Alamat", self.address_input)
        form.addRow("Nomor WhatsApp", self.whatsapp_input)

        logo_row = QHBoxLayout()
        self.logo_preview = QLabel("Belum ada logo")
        self.logo_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.logo_preview.setFixedSize(110, 90)
        self.logo_preview.setStyleSheet(
            "border: 1px dashed #3f3f4a; color: #a1a1aa; background: #1a1a1e;"
        )
        logo_buttons = QVBoxLayout()
        self.choose_logo_button = QPushButton("Pilih Logo")
        self.choose_logo_button.clicked.connect(self._choose_logo)
        self.remove_logo_button = QPushButton("Hapus Logo")
        self.remove_logo_button.clicked.connect(self._remove_logo)
        logo_buttons.addWidget(self.choose_logo_button)
        logo_buttons.addWidget(self.remove_logo_button)
        logo_buttons.addStretch(1)
        logo_row.addWidget(self.logo_preview)
        logo_row.addLayout(logo_buttons)
        logo_row.addStretch(1)
        form.addRow("Logo (opsional)", logo_row)

        db_folder_row = QHBoxLayout()
        self.db_folder_input = QLineEdit(app_settings.product_export_dir or "")
        self.db_folder_input.setReadOnly(True)
        self.db_folder_input.setPlaceholderText(
            "Belum ada folder — klik Browse"
        )
        self.db_folder_input.setToolTip(
            "Folder penyimpanan snapshot tabel produk (pos-produk.db) "
            "untuk diedit eksternal (CSV/Excel/aplikasi database) lalu "
            "diimpor kembali lewat menu Import Data."
        )
        self.db_folder_browse_button = QPushButton("Browse")
        self.db_folder_browse_button.clicked.connect(
            self._browse_database_folder
        )
        db_folder_row.addWidget(self.db_folder_input, 1)
        db_folder_row.addWidget(self.db_folder_browse_button)
        form.addRow("Pilih Folder Simpan Database", db_folder_row)
        store_layout.addLayout(form)
        store_layout.addStretch(1)
        store_layout.addLayout(self._create_action_row())

        # Halaman tab terakhir jendela Manajemen Toko:
        # "Seting Pembayaran Kasir".
        self.payment_tab = QWidget()
        payment_layout = QVBoxLayout(self.payment_tab)
        payment_layout.setContentsMargins(16, 16, 16, 16)
        payment_layout.setSpacing(12)

        payment_description = QLabel(
            "Pilih metode pembayaran yang tersedia pada jendela kasir. "
            "Jika hanya Tunai (Offline) yang dipilih, kasir hanya dapat menerima tunai. "
            "Metode non-tunai baru muncul di kasir bila dicentang dan status "
            "wizard-nya sudah Aktif."
        )
        payment_description.setWordWrap(True)
        payment_description.setStyleSheet("color: #a1a1aa;")
        payment_layout.addWidget(payment_description)

        self.payment_cash = QCheckBox("Tunai (Offline)")
        self.payment_qris_dana = QCheckBox("QRIS DANA")
        self.payment_qris_midtrans = QCheckBox("QRIS MIDTRANS")
        self.payment_transfer = QCheckBox("TF (m BANKING)")
        self.payment_all = QCheckBox("Semua (termasuk tunai)")

        self.payment_cash.toggled.connect(self._sync_all_checkbox)
        self.payment_qris_dana.toggled.connect(self._sync_all_checkbox)
        self.payment_qris_midtrans.toggled.connect(self._sync_all_checkbox)
        self.payment_transfer.toggled.connect(self._sync_all_checkbox)
        self.payment_all.toggled.connect(self._on_all_toggled)

        self._payment_setting_buttons: list[QPushButton] = []
        self._payment_status_labels: dict[str, QLabel] = {}

        payment_grid = QGridLayout()
        payment_grid.setColumnStretch(0, 1)
        payment_grid.setColumnStretch(1, 1)
        payment_grid.setColumnStretch(2, 0)
        payment_grid.setHorizontalSpacing(12)
        payment_grid.setVerticalSpacing(10)
        payment_row = 0

        def add_payment_row(
            checkbox: QCheckBox, with_setting: bool, method_code: str | None = None
        ):
            nonlocal payment_row
            payment_grid.addWidget(checkbox, payment_row, 0)
            if with_setting:
                if method_code:
                    status_label = QLabel("")
                    status_label.setStyleSheet("color: #a1a1aa;")
                    self._payment_status_labels[method_code] = status_label
                    payment_grid.addWidget(status_label, payment_row, 1)
                setting_button = QPushButton("SETTING")
                setting_button.setFixedWidth(90)
                setting_button.clicked.connect(
                    lambda _=False, label=checkbox.text(): self._open_payment_wizard(label)
                )
                payment_grid.addWidget(setting_button, payment_row, 2)
                self._payment_setting_buttons.append(setting_button)
            payment_row += 1

        add_payment_row(self.payment_cash, with_setting=False)
        add_payment_row(self.payment_qris_dana, True, "QRIS_DANA")
        add_payment_row(self.payment_qris_midtrans, True, "QRIS_MIDTRANS")
        add_payment_row(self.payment_transfer, True, "BANK")
        add_payment_row(self.payment_all, with_setting=True)
        payment_layout.addLayout(payment_grid)
        payment_layout.addStretch(1)
        payment_layout.addLayout(self._create_action_row())

        self._load_store()
        self._set_editing(False)
        self._refresh_payment_status_labels()

    def _refresh_payment_status_labels(self):
        from app.models import PaymentWizardState
        from app.services.payment_wizard_service import STATUS_LABELS

        statuses: dict[str, str] = {}
        if self.payment_service is not None:
            try:
                statuses = {
                    row.method: row.status
                    for row in self.payment_service.session.query(
                        PaymentWizardState
                    ).all()
                }
            except SQLAlchemyError:
                statuses = {}
        for method, label in self._payment_status_labels.items():
            status = statuses.get(method, "not_started")
            label.setText(f"Status: {STATUS_LABELS.get(status, status)}")
            color = "#4ade80" if status == "active" else "#a1a1aa"
            label.setStyleSheet(f"color: {color};")

    def _load_store(self):
        try:
            self.store = self.service.get_store()
        except SQLAlchemyError as exc:
            QMessageBox.critical(self, "Gagal memuat pengaturan toko", str(exc))
            self.store = None
        self.logo_source = None
        self.remove_logo = False
        self.name_input.setText(self.store.name if self.store else "")
        self.slogan_input.setText(
            self.store.slogan if self.store and self.store.slogan else ""
        )
        self.address_input.setText(
            self.store.address if self.store and self.store.address else ""
        )
        self.whatsapp_input.setText(
            self.store.whatsapp if self.store and self.store.whatsapp else ""
        )
        self._show_logo(self.store.logo_path if self.store else None)
        self._load_payment_settings()

    def _load_payment_settings(self):
        if self.payment_service is None:
            return
        try:
            self.payment_settings = self.payment_service.get_settings()
        except SQLAlchemyError as exc:
            QMessageBox.critical(self, "Gagal memuat pengaturan pembayaran", str(exc))
            self.payment_settings = None
            return
        self._syncing_all = True
        self.payment_cash.setChecked(self.payment_settings.cash_enabled)
        self.payment_qris_dana.setChecked(self.payment_settings.qris_dana_enabled)
        self.payment_qris_midtrans.setChecked(
            self.payment_settings.qris_midtrans_enabled
        )
        self.payment_transfer.setChecked(self.payment_settings.transfer_enabled)
        all_enabled = all(
            box.isChecked()
            for box in (
                self.payment_cash,
                self.payment_qris_dana,
                self.payment_qris_midtrans,
                self.payment_transfer,
            )
        )
        self.payment_all.setChecked(all_enabled)
        self._syncing_all = False

    def _sync_all_checkbox(self, _checked: bool):
        if self._syncing_all:
            return
        self._syncing_all = True
        all_enabled = all(
            box.isChecked()
            for box in (
                self.payment_cash,
                self.payment_qris_dana,
                self.payment_qris_midtrans,
                self.payment_transfer,
            )
        )
        self.payment_all.setChecked(all_enabled)
        self._syncing_all = False

    def _on_all_toggled(self, checked: bool):
        if self._syncing_all:
            return
        self._syncing_all = True
        self.payment_cash.setChecked(checked)
        self.payment_qris_dana.setChecked(checked)
        self.payment_qris_midtrans.setChecked(checked)
        self.payment_transfer.setChecked(checked)
        self._syncing_all = False

    def _open_payment_wizard(self, label: str):
        method = {
            "QRIS DANA": "QRIS_DANA",
            "QRIS MIDTRANS": "QRIS_MIDTRANS",
            "TF (m BANKING)": "BANK",
        }.get(label)
        if method is None or self.payment_service is None:
            QMessageBox.information(
                self,
                "Wizard Pembayaran",
                f"Pengaturan detail {label} akan diatur melalui Wizard.\n"
                "Wizard belum tersedia dan akan menyusul.",
            )
            return
        self._open_wizard(method)

    def _open_wizard(self, method: str):
        from app.services.payment_wizard_service import PaymentWizardService
        from app.ui.views.payment_wizard_view import PaymentWizardDialog

        service = PaymentWizardService(self.payment_service.session)
        dialog = PaymentWizardDialog(method, self.actor, service, self)
        dialog.exec()
        self._refresh_payment_status_labels()

    def reload_settings(self):
        self._load_store()
        self.db_folder_input.setText(app_settings.product_export_dir or "")
        self._set_editing(False)

    def _show_logo(self, logo_path: str | None):
        self.logo_preview.clear()
        if logo_path and Path(logo_path).is_file():
            pixmap = QPixmap(logo_path)
            if not pixmap.isNull():
                self.logo_preview.setPixmap(
                    pixmap.scaled(
                        self.logo_preview.size(),
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
                return
        self.logo_preview.setText("Belum ada logo")

    def _create_action_row(self) -> QHBoxLayout:
        action_row = QHBoxLayout()
        action_row.addStretch(1)
        edit_button = QPushButton("Ubah")
        edit_button.clicked.connect(self._begin_edit)
        save_button = QPushButton("Simpan")
        save_button.clicked.connect(self._save)
        cancel_button = QPushButton("Batal")
        cancel_button.clicked.connect(self._cancel_edit)
        action_row.addWidget(edit_button)
        action_row.addWidget(save_button)
        action_row.addWidget(cancel_button)
        self._action_rows.append((edit_button, save_button, cancel_button))
        if not hasattr(self, "edit_button"):
            self.edit_button = edit_button
            self.save_button = save_button
            self.cancel_button = cancel_button
        return action_row

    def _begin_edit(self):
        self._editing = True
        self._set_editing(True)

    def _set_editing(self, editing: bool):
        self.name_input.setReadOnly(not editing)
        self.slogan_input.setReadOnly(not editing)
        self.address_input.setReadOnly(not editing)
        self.whatsapp_input.setReadOnly(not editing)
        self.choose_logo_button.setEnabled(editing)
        self.remove_logo_button.setEnabled(editing)
        self.db_folder_browse_button.setEnabled(editing)
        for checkbox in (
            self.payment_cash,
            self.payment_qris_dana,
            self.payment_qris_midtrans,
            self.payment_transfer,
            self.payment_all,
        ):
            checkbox.setEnabled(editing)
        for setting_button in self._payment_setting_buttons:
            setting_button.setEnabled(editing)
        for edit_button, save_button, cancel_button in self._action_rows:
            edit_button.setVisible(not editing)
            save_button.setVisible(editing)
            cancel_button.setVisible(editing)
        self._editing = editing

    def _choose_logo(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Pilih Logo Toko",
            "",
            "Gambar (*.png *.jpg *.jpeg *.bmp *.webp)",
        )
        if not file_path:
            return
        pixmap = QPixmap(file_path)
        if pixmap.isNull():
            QMessageBox.warning(
                self,
                "Logo tidak valid",
                "File yang dipilih tidak dapat dibaca sebagai gambar.",
            )
            return
        self.logo_source = file_path
        self.remove_logo = False
        self._show_logo(file_path)

    def _remove_logo(self):
        self.logo_source = None
        self.remove_logo = True
        self._show_logo(None)

    def _browse_database_folder(self):
        start_dir = self.db_folder_input.text().strip() or str(
            app_settings.data_dir
        )
        folder = QFileDialog.getExistingDirectory(
            self,
            "Pilih Folder Simpan Database",
            start_dir,
        )
        if folder:
            self.db_folder_input.setText(folder)

    PRODUCTS_DB_FILENAME = "pos-produk.db"

    def _save_products_database(self) -> bool:
        chosen = self.db_folder_input.text().strip()
        if not chosen:
            return True
        folder = Path(chosen).expanduser()
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            QMessageBox.warning(
                self,
                "Folder tidak dapat disimpan",
                str(exc),
            )
            return False
        target = folder / self.PRODUCTS_DB_FILENAME
        if target.exists():
            answer = QMessageBox.question(
                self,
                "File produk sudah ada",
                f"File {self.PRODUCTS_DB_FILENAME} sudah ada di folder "
                "tersebut. Timpa dengan data produk terbaru dari aplikasi?\n"
                "Pilih Tidak bila file sedang diedit di aplikasi lain.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                self._persist_product_export_dir(folder)
                return True
        try:
            self._export_products_snapshot(target)
        except (OSError, sqlite3.Error, SQLAlchemyError) as exc:
            QMessageBox.warning(
                self,
                "Database produk tidak dapat disimpan",
                str(exc),
            )
            return False
        self._persist_product_export_dir(folder)
        QMessageBox.information(
            self,
            "Database produk disimpan",
            f"Snapshot tabel produk tersimpan di:\n{target}\n\n"
            "File berisi tabel produk (serta kategori & satuan sebagai "
            "referensi) dan dapat diedit dengan aplikasi SQLite, CSV, "
            "atau Excel, lalu diimpor kembali lewat menu Import Data.",
        )
        return True

    def _persist_product_export_dir(self, folder: Path) -> None:
        try:
            app_settings.product_export_dir = str(folder)
            persist_env_value("PRODUCT_EXPORT_DIR", str(folder))
        except OSError as exc:
            QMessageBox.warning(
                self,
                "Folder tidak dapat disimpan",
                str(exc),
            )

    def _export_products_snapshot(self, target: Path) -> None:
        session = self.service.session
        categories = session.scalars(
            select(Category).where(Category.deleted_at.is_(None))
        ).all()
        units = session.scalars(
            select(Unit).where(Unit.deleted_at.is_(None))
        ).all()
        products = session.scalars(
            select(Product).where(Product.deleted_at.is_(None))
        ).all()
        if target.exists():
            target.unlink()
        conn = sqlite3.connect(str(target))
        try:
            conn.execute(
                "CREATE TABLE categories ("
                "id INTEGER PRIMARY KEY, name TEXT NOT NULL)"
            )
            conn.execute(
                "CREATE TABLE units ("
                "id INTEGER PRIMARY KEY, name TEXT NOT NULL, "
                "symbol TEXT NOT NULL)"
            )
            conn.execute(
                "CREATE TABLE products ("
                "id INTEGER PRIMARY KEY, "
                "sku TEXT NOT NULL, "
                "barcode TEXT, "
                "name TEXT NOT NULL, "
                "category_id INTEGER, "
                "unit_id INTEGER, "
                "purchase_price INTEGER NOT NULL DEFAULT 0, "
                "selling_price INTEGER NOT NULL DEFAULT 0, "
                "stock_qty INTEGER NOT NULL DEFAULT 0, "
                "min_stock INTEGER NOT NULL DEFAULT 0, "
                "is_active INTEGER NOT NULL DEFAULT 1, "
                "deleted_at TEXT)"
            )
            conn.executemany(
                "INSERT INTO categories (id, name) VALUES (?, ?)",
                [(category.id, category.name) for category in categories],
            )
            conn.executemany(
                "INSERT INTO units (id, name, symbol) VALUES (?, ?, ?)",
                [(unit.id, unit.name, unit.symbol) for unit in units],
            )
            conn.executemany(
                "INSERT INTO products ("
                "id, sku, barcode, name, category_id, unit_id, "
                "purchase_price, selling_price, stock_qty, min_stock, "
                "is_active, deleted_at"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        product.id,
                        product.sku,
                        product.barcode or "",
                        product.name,
                        product.category_id,
                        product.unit_id,
                        product.purchase_price,
                        product.selling_price,
                        product.stock_qty,
                        product.min_stock,
                        1 if product.is_active else 0,
                        None,
                    )
                    for product in products
                ],
            )
            conn.commit()
        finally:
            conn.close()

    def _save(self):
        try:
            store = self.service.save(
                self.actor,
                name=self.name_input.text(),
                slogan=self.slogan_input.text(),
                address=self.address_input.text(),
                whatsapp=self.whatsapp_input.text(),
                logo_source=self.logo_source,
                remove_logo=self.remove_logo,
            )
        except (AuthorizationError, ValidationError, SQLAlchemyError) as exc:
            QMessageBox.warning(self, "Pengaturan tidak tersimpan", str(exc))
            return
        except OSError as exc:
            QMessageBox.warning(self, "Logo tidak dapat disimpan", str(exc))
            return

        self.store = store
        self.logo_source = None
        self.remove_logo = False
        self._show_logo(store.logo_path)
        self._set_editing(False)
        self.settings_saved.emit(store)
        QMessageBox.information(
            self,
            "Pengaturan tersimpan",
            "Profil toko berhasil diperbarui.",
        )
        if not self._save_products_database():
            return
        self._save_payment_settings()

    def _save_payment_settings(self):
        if self.payment_service is None:
            return
        try:
            self.payment_settings = self.payment_service.save(
                self.actor,
                cash_enabled=self.payment_cash.isChecked(),
                qris_dana_enabled=self.payment_qris_dana.isChecked(),
                qris_midtrans_enabled=self.payment_qris_midtrans.isChecked(),
                transfer_enabled=self.payment_transfer.isChecked(),
            )
        except (AuthorizationError, ValidationError, SQLAlchemyError) as exc:
            QMessageBox.warning(self, "Pengaturan pembayaran tidak tersimpan", str(exc))

    def _cancel_edit(self):
        self._load_store()
        self.db_folder_input.setText(app_settings.product_export_dir or "")
        self._set_editing(False)
