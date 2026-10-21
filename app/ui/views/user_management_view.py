from datetime import date

from PySide6.QtCore import QDate, Qt, Signal
from sqlalchemy.exc import SQLAlchemyError
from PySide6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.core.exceptions import AuthorizationError, ValidationError
from app.services.inventory_service import InventoryService
from app.services.payment_settings_service import PaymentSettingsService
from app.services.store_settings_service import StoreSettingsService
from app.services.user_management_service import UserManagementService
from app.ui.views.financial_view import (
    ExpenseEntryView,
    ExpensePaymentView,
    FinancialView,
)
from app.ui.views.store_settings_view import StoreSettingsView
from app.ui.widgets import TableSearchBar, create_dashboard_back_button


class UserManagementView(QWidget):
    back_requested = Signal()

    def __init__(
        self,
        actor,
        user_management: UserManagementService,
        parent=None,
        *,
        read_only: bool = False,
    ):
        super().__init__(parent)
        self.actor = actor
        self.user_management = user_management
        self._show_password = False

        root = QVBoxLayout(self)
        root.setContentsMargins(32, 28, 32, 32)
        root.setSpacing(16)

        header = QHBoxLayout()
        self.back_button = create_dashboard_back_button(self)
        self.back_button.clicked.connect(self.back_requested.emit)
        title = QLabel("Manajemen Toko")
        title.setStyleSheet("font-size: 25px; font-weight: 700; color: #ffffff;")
        header.addWidget(self.back_button)
        header.addWidget(title)
        header.addStretch(1)
        root.addLayout(header)

        # Konten jendela dibungkus tab: Pengaturan Toko, Modal Awal,
        # Catat Pengeluaran, Bayar Pengeluaran, Tambah Karyawan,
        # Inventaris Toko, dan Seting Pembayaran Kasir.
        self.tabs = QTabWidget()
        self.tabs.setStyleSheet(
            "QTabWidget::pane { border: 1px solid #3f3f46; "
            "border-radius: 8px; top: -1px; }"
            "QTabBar::tab { background: transparent; color: #a1a1aa; "
            "padding: 8px 16px; font-weight: 600; "
            "border-bottom: 2px solid transparent; }"
            "QTabBar::tab:selected { color: #007acc; "
            "border-bottom: 2px solid #007acc; }"
        )
        root.addWidget(self.tabs)

        self.inventory = InventoryService(user_management.session)
        self._editing_item_id = None
        self.inv_ids: list[int] = []
        self.inv_items = []

        users_page = QWidget()
        users_layout = QVBoxLayout(users_page)
        users_layout.setContentsMargins(0, 8, 0, 0)
        users_layout.setSpacing(12)

        description = QLabel(
            "Buat akun tenaga kerja lalu isi Jabatan sesuai kebutuhan "
            "toko (contoh: Manajer, Teknisi, Umum, Kasir Sore). Pilih baris "
            "lalu klik Edit untuk mengubah data langsung di tabel. Hanya "
            "OWNER yang dapat mengelola akun pengguna."
        )
        description.setWordWrap(True)
        description.setStyleSheet("color: #a1a1aa;")
        users_layout.addWidget(description)

        # Dua kolom: kiri = form tambah karyawan + tombol "Tambah
        # Pengguna" rata tengah di bawah form; kanan = tabel +
        # tombol aksi edit/hapus.
        content = QHBoxLayout()
        content.setSpacing(28)

        left_column = QVBoxLayout()
        left_column.setSpacing(12)
        self.form_layout = QFormLayout()
        self.form_layout.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow
        )
        self.username_input = QLineEdit()
        self.username_input.setMaxLength(80)
        self.username_input.setPlaceholderText("Contoh: kasir01")
        self.full_name_input = QLineEdit()
        self.full_name_input.setMaxLength(150)
        self.full_name_input.setPlaceholderText("Nama lengkap pegawai")
        self.wa_input = QLineEdit()
        self.wa_input.setMaxLength(30)
        self.wa_input.setPlaceholderText("Contoh: +62 812 3456 7890")
        self.role_input = QLineEdit()
        self.role_input.setMaxLength(50)
        self.role_input.setPlaceholderText(
            "Contoh: Manajer, Teknisi, Umum"
        )
        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_input.setPlaceholderText("Minimal 8 karakter")
        self.confirm_password_input = QLineEdit()
        self.confirm_password_input.setEchoMode(QLineEdit.EchoMode.Password)

        self.form_layout.addRow("Username", self.username_input)
        self.form_layout.addRow("Nama lengkap", self.full_name_input)
        self.form_layout.addRow("No. WA", self.wa_input)
        self.form_layout.addRow("Jabatan", self.role_input)
        self.form_layout.addRow("Password", self.password_input)
        self.form_layout.addRow("Ulangi password", self.confirm_password_input)
        left_column.addLayout(self.form_layout)

        self.create_button = QPushButton("Tambah Karyawan")
        self.create_button.setStyleSheet(
            "QPushButton { background: #007acc; color: white; border: none; "
            "border-radius: 8px; padding: 10px 16px; font-weight: 600; }"
            "QPushButton:hover { background: #0098ff; }"
        )
        self.create_button.clicked.connect(self._create_user)
        create_row = QHBoxLayout()
        create_row.setSpacing(10)
        create_row.addStretch(1)
        create_row.addWidget(self.create_button)
        create_row.addStretch(1)
        left_column.addLayout(create_row)
        left_column.addStretch(1)
        content.addLayout(left_column, 1)

        self.role_input.textChanged.connect(self._toggle_password_visibility)

        right_column = QVBoxLayout()
        right_column.setSpacing(12)

        right_column.addWidget(QLabel("Daftar Karyawan"))
        self.user_table = QTableWidget(0, 5)
        self.user_table.setHorizontalHeaderLabels(
            ["Nama", "Username", "Jabatan", "No. WA", "Password"]
        )
        self.user_table.setEditTriggers(
            QTableWidget.EditTrigger.NoEditTriggers
        )
        self.user_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self.user_table.horizontalHeader().setStretchLastSection(True)
        self.user_search = TableSearchBar(self.user_table, "Cari pengguna...")
        right_column.addWidget(self.user_search)
        right_column.addWidget(self.user_table, 1)

        self.delete_button = QPushButton("Hapus Pengguna Terpilih")
        self.delete_button.setStyleSheet(
            "QPushButton { background: #dc2626; color: white; border: none; "
            "border-radius: 8px; padding: 10px 16px; font-weight: 600; }"
            "QPushButton:hover { background: #ef4444; }"
        )
        self.delete_button.clicked.connect(self._delete_selected_user)
        self.edit_button = QPushButton("Edit Pengguna Terpilih")
        self.edit_button.setStyleSheet(
            "QPushButton { background: #f59e0b; color: white; border: none; "
            "border-radius: 8px; padding: 10px 16px; font-weight: 600; }"
            "QPushButton:hover { background: #fbbf24; }"
        )
        self.edit_button.clicked.connect(self._toggle_edit_user)
        self.cancel_edit_button = QPushButton("Batal Edit")
        self.cancel_edit_button.setStyleSheet(
            "QPushButton { background: #4b5563; color: white; border: none; "
            "border-radius: 8px; padding: 10px 16px; font-weight: 600; }"
            "QPushButton:hover { background: #6b7280; }"
        )
        self.cancel_edit_button.clicked.connect(self._cancel_edit)
        self.cancel_edit_button.hide()
        self._editing_row = None
        action_row = QHBoxLayout()
        action_row.setSpacing(10)
        action_row.addStretch(1)
        action_row.addWidget(self.edit_button)
        action_row.addWidget(self.cancel_edit_button)
        action_row.addWidget(self.delete_button)
        self.password_toggle_button = QPushButton("Tampilkan Password")
        self.password_toggle_button.setStyleSheet(
            "QPushButton { background: #4b5563; color: white; border: none; "
            "border-radius: 8px; padding: 8px 14px; font-weight: 600; }"
            "QPushButton:hover { background: #6b7280; }"
        )
        self.password_toggle_button.clicked.connect(
            self._toggle_password_column
        )
        action_row.addWidget(self.password_toggle_button)
        self.reset_password_button = QPushButton("Reset Password")
        self.reset_password_button.setStyleSheet(
            "QPushButton { background: #dc2626; color: white; border: none; "
            "border-radius: 8px; padding: 8px 14px; font-weight: 600; }"
            "QPushButton:hover { background: #ef4444; }"
        )
        self.reset_password_button.clicked.connect(self._reset_password)
        action_row.addWidget(self.reset_password_button)
        right_column.addLayout(action_row)

        content.addLayout(right_column, 2)
        users_layout.addLayout(content, 1)
        self.tabs.addTab(users_page, "Tambah Karyawan")

        self._build_inventory_tab()
        self.tabs.addTab(self._inventory_page, "Inventaris Toko")

        # Pengaturan toko digabung ke jendela ini: tab pertama
        # "Pengaturan Toko", lalu "Modal Awal" (input Modal + aktivasi
        # Laporan Keuangan), "Catat Pengeluaran", "Bayar Pengeluaran",
        # tab terakhir "Seting Pembayaran Kasir".
        self.store_settings = StoreSettingsView(
            actor,
            StoreSettingsService(user_management.session),
            payment_service=PaymentSettingsService(user_management.session),
        )
        # Controller hanya pemilik sinyal/service: jangan sampai menjadi
        # overlay (0,0,640,480) yang menelan semua klik mouse di jendela.
        self.store_settings.setParent(self)
        self.store_settings.hide()
        self.store_settings.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.tabs.insertTab(0, self.store_settings.store_tab, "Pengaturan Toko")

        # Tab "Modal Awal": cukup input saldo Modal + checkbox
        # "Aktifkan Laporan Keuangan" (fitur premium/trial).
        self.financial_view = FinancialView(
            actor, user_management.session, read_only=read_only
        )
        self.tabs.insertTab(1, self.financial_view, "Modal Awal")

        # Tab pengeluaran memakai service yang sama dengan Modal Awal.
        self.expense_entry_view = ExpenseEntryView(
            actor,
            self.financial_view.service,
            read_only=read_only,
        )
        self.tabs.insertTab(2, self.expense_entry_view, "Catat Pengeluaran")
        self.expense_payment_view = ExpensePaymentView(
            actor,
            self.financial_view.service,
            read_only=read_only,
        )
        self.tabs.insertTab(3, self.expense_payment_view, "Bayar Pengeluaran")
        # Aktivasi di tab Modal Awal langsung menghidupkan kedua tab
        # pengeluaran.
        self.financial_view.books_activated.connect(
            self._refresh_expense_views
        )

        self.tabs.addTab(
            self.store_settings.payment_tab, "Seting Pembayaran Kasir"
        )
        self.tabs.currentChanged.connect(self._on_tab_changed)

        self.refresh_users()
        self.refresh_inventory()

    def _on_tab_changed(self, index: int):
        if not (0 <= index < self.tabs.count()):
            return
        widget = self.tabs.widget(index)
        if widget is getattr(self, "financial_view", None):
            self.financial_view.refresh_view()
        elif widget is getattr(self, "expense_entry_view", None):
            self.expense_entry_view.refresh_view()
        elif widget is getattr(self, "expense_payment_view", None):
            self.expense_payment_view.refresh_view()

    def _refresh_expense_views(self):
        self.expense_entry_view.refresh_view()
        self.expense_payment_view.refresh_view()

    def refresh_financial(self):
        self.financial_view.refresh_view()
        self._refresh_expense_views()

    def refresh_users(self):
        self._exit_edit_mode()
        users = self.user_management.list_users(self.actor)
        self.user_table.setRowCount(len(users))
        self.user_ids = []
        for row, user in enumerate(users):
            self.user_ids.append(user.id)
            pw_value = (
                user.password_hash if self._show_password else "••••••••"
            )
            values = (
                user.full_name,
                user.username,
                user.role.name,
                user.whatsapp or "",
                pw_value,
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.user_table.setItem(row, column, item)
        self.user_table.resizeColumnsToContents()

    # ------------------------------------------------------------ inventaris

    def _build_inventory_tab(self):
        self._inventory_page = QWidget()
        layout = QVBoxLayout(self._inventory_page)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(12)

        hint = QLabel(
            "Inventaris toko: catat alat dan peralatan yang tidak dijual "
            "(peralatan, perlengkapan, aset toko). Isi form lalu klik "
            "Tambah Item; pilih baris di tabel untuk Edit atau Hapus."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #a1a1aa;")
        layout.addWidget(hint)

        content = QHBoxLayout()
        content.setSpacing(28)

        left = QVBoxLayout()
        left.setSpacing(12)
        form = QFormLayout()
        form.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow
        )
        self.inv_kode_input = QLineEdit()
        self.inv_kode_input.setMaxLength(50)
        self.inv_kode_input.setPlaceholderText("Contoh: INV-001")
        self.inv_nama_input = QLineEdit()
        self.inv_nama_input.setMaxLength(200)
        self.inv_nama_input.setPlaceholderText("Nama alat / peralatan")
        self.inv_jumlah_input = QSpinBox()
        self.inv_jumlah_input.setRange(0, 9_999_999)
        self.inv_satuan_input = QLineEdit()
        self.inv_satuan_input.setMaxLength(50)
        self.inv_satuan_input.setPlaceholderText("Contoh: pcs, unit, set")
        self.inv_tanggal_input = QDateEdit()
        self.inv_tanggal_input.setCalendarPopup(True)
        self.inv_tanggal_input.setDisplayFormat("dd-MM-yyyy")
        self.inv_tanggal_input.setDate(QDate.currentDate())
        self.inv_harga_input = QSpinBox()
        self.inv_harga_input.setRange(0, 2_000_000_000)
        self.inv_harga_input.setPrefix("Rp ")
        self.inv_lokasi_input = QLineEdit()
        self.inv_lokasi_input.setMaxLength(100)
        self.inv_lokasi_input.setPlaceholderText("Rak / gudang penyimpanan")
        self.inv_kondisi_input = QComboBox()
        self.inv_kondisi_input.addItems(
            ["Baik", "Rusak Ringan", "Rusak Berat"]
        )
        self.inv_keterangan_input = QLineEdit()
        self.inv_keterangan_input.setMaxLength(1000)
        self.inv_keterangan_input.setPlaceholderText("Keterangan opsional")

        form.addRow("Kode Inventaris", self.inv_kode_input)
        form.addRow("Nama Barang", self.inv_nama_input)
        form.addRow("Jumlah", self.inv_jumlah_input)
        form.addRow("Satuan", self.inv_satuan_input)
        form.addRow("Tanggal Perolehan", self.inv_tanggal_input)
        form.addRow("Harga Perolehan", self.inv_harga_input)
        form.addRow("Lokasi", self.inv_lokasi_input)
        form.addRow("Kondisi", self.inv_kondisi_input)
        form.addRow("Keterangan", self.inv_keterangan_input)
        left.addLayout(form)
        left.addStretch(1)
        content.addLayout(left, 1)

        right = QVBoxLayout()
        right.setSpacing(12)
        right.addWidget(QLabel("Daftar inventaris toko"))
        self.inv_table = QTableWidget(0, 8)
        self.inv_table.setHorizontalHeaderLabels(
            [
                "Kode",
                "Nama Barang",
                "Jumlah",
                "Satuan",
                "Tgl Perolehan",
                "Harga Perolehan",
                "Lokasi",
                "Kondisi",
            ]
        )
        self.inv_table.setEditTriggers(
            QTableWidget.EditTrigger.NoEditTriggers
        )
        self.inv_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self.inv_table.horizontalHeader().setStretchLastSection(True)
        self.inv_search = TableSearchBar(self.inv_table, "Cari inventaris...")
        right.addWidget(self.inv_search)
        right.addWidget(self.inv_table, 1)

        self.inv_edit_button = QPushButton("Edit Terpilih")
        self.inv_edit_button.setStyleSheet(
            "QPushButton { background: #f59e0b; color: white; border: none; "
            "border-radius: 8px; padding: 10px 16px; font-weight: 600; }"
            "QPushButton:hover { background: #fbbf24; }"
        )
        self.inv_edit_button.clicked.connect(self._toggle_inv_edit)
        self.inv_cancel_button = QPushButton("Batal Edit")
        self.inv_cancel_button.setStyleSheet(
            "QPushButton { background: #4b5563; color: white; border: none; "
            "border-radius: 8px; padding: 10px 16px; font-weight: 600; }"
            "QPushButton:hover { background: #6b7280; }"
        )
        self.inv_cancel_button.clicked.connect(self._cancel_inv_edit)
        self.inv_cancel_button.hide()
        self.inv_delete_button = QPushButton("Hapus Terpilih")
        self.inv_delete_button.setStyleSheet(
            "QPushButton { background: #dc2626; color: white; border: none; "
            "border-radius: 8px; padding: 10px 16px; font-weight: 600; }"
            "QPushButton:hover { background: #ef4444; }"
        )
        self.inv_delete_button.clicked.connect(self._delete_inv_selected)
        self.inv_create_button = QPushButton("Tambah Item")
        self.inv_create_button.setStyleSheet(
            "QPushButton { background: #007acc; color: white; border: none; "
            "border-radius: 8px; padding: 10px 16px; font-weight: 600; }"
            "QPushButton:hover { background: #0098ff; }"
        )
        self.inv_create_button.clicked.connect(self._add_inv_item)
        action_row = QHBoxLayout()
        action_row.setSpacing(10)
        action_row.addStretch(1)
        action_row.addWidget(self.inv_edit_button)
        action_row.addWidget(self.inv_cancel_button)
        action_row.addWidget(self.inv_delete_button)
        action_row.addWidget(self.inv_create_button)
        right.addLayout(action_row)
        content.addLayout(right, 2)

        layout.addLayout(content, 1)

    def refresh_inventory(self):
        self._exit_inv_edit_mode()
        items = self.inventory.list_items(self.actor)
        self.inv_items = list(items)
        self.inv_ids = [item.id for item in items]
        self.inv_table.setRowCount(len(items))
        for row, item in enumerate(items):
            tanggal = (
                item.tanggal_perolehan.strftime("%d-%m-%Y")
                if item.tanggal_perolehan
                else ""
            )
            values = (
                item.kode_inventaris,
                item.nama_barang,
                str(item.jumlah),
                item.satuan or "",
                tanggal,
                f"{item.harga_perolehan:,}".replace(",", "."),
                item.lokasi or "",
                item.kondisi,
            )
            for column, value in enumerate(values):
                cell = QTableWidgetItem(value)
                cell.setFlags(cell.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.inv_table.setItem(row, column, cell)
        self.inv_table.resizeColumnsToContents()

    def _toggle_inv_edit(self):
        if self._editing_item_id is not None:
            self._save_inv_edit()
            return
        row = self.inv_table.currentRow()
        if row < 0 or row >= len(self.inv_ids):
            QMessageBox.information(
                self,
                "Pilih barang",
                "Pilih barang inventaris yang akan diedit.",
            )
            return
        self._start_inv_edit(row)

    def _start_inv_edit(self, row):
        item = self.inv_items[row]
        self._editing_item_id = item.id
        self.inv_kode_input.setText(item.kode_inventaris)
        self.inv_nama_input.setText(item.nama_barang)
        self.inv_jumlah_input.setValue(item.jumlah)
        self.inv_satuan_input.setText(item.satuan or "")
        self.inv_tanggal_input.setDate(
            item.tanggal_perolehan
            or date.today()
        )
        self.inv_harga_input.setValue(item.harga_perolehan)
        self.inv_lokasi_input.setText(item.lokasi or "")
        index = self.inv_kondisi_input.findText(item.kondisi)
        if index >= 0:
            self.inv_kondisi_input.setCurrentIndex(index)
        self.inv_keterangan_input.setText(item.keterangan or "")
        self.inv_edit_button.setText("Simpan Perubahan")
        self.inv_cancel_button.show()
        self.inv_delete_button.setEnabled(False)
        self.inv_create_button.setEnabled(False)
        self.tabs.setCurrentWidget(self._inventory_page)
        self.inv_kode_input.setFocus()

    def _save_inv_edit(self):
        try:
            self.inventory.update_item(
                self.actor,
                self._editing_item_id,
                **self._inv_form_values(),
            )
        except (AuthorizationError, ValidationError, SQLAlchemyError) as exc:
            QMessageBox.warning(
                self, "Tidak dapat menyimpan perubahan", str(exc)
            )
            return
        self._clear_inv_form()
        self.refresh_inventory()
        QMessageBox.information(
            self,
            "Perubahan tersimpan",
            "Barang inventaris berhasil diperbarui.",
        )

    def _add_inv_item(self):
        try:
            self.inventory.create_item(
                self.actor,
                **self._inv_form_values(),
            )
        except (AuthorizationError, ValidationError, SQLAlchemyError) as exc:
            QMessageBox.warning(self, "Tidak dapat menambah barang", str(exc))
            return
        self._clear_inv_form()
        self.refresh_inventory()
        QMessageBox.information(
            self,
            "Barang ditambahkan",
            "Barang inventaris berhasil ditambahkan.",
        )

    def _delete_inv_selected(self):
        row = self.inv_table.currentRow()
        if row < 0 or row >= len(self.inv_ids):
            QMessageBox.information(
                self,
                "Pilih barang",
                "Pilih barang inventaris yang akan dihapus.",
            )
            return
        item = self.inv_items[row]
        answer = QMessageBox.question(
            self,
            "Hapus barang",
            f"Barang {item.kode_inventaris} - {item.nama_barang} akan dihapus "
            "dari inventaris toko. Lanjutkan?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self.inventory.delete_item(self.actor, item.id)
        except (AuthorizationError, ValidationError, SQLAlchemyError) as exc:
            QMessageBox.warning(self, "Tidak dapat menghapus barang", str(exc))
            return
        self._clear_inv_form()
        self.refresh_inventory()

    def _cancel_inv_edit(self):
        self._clear_inv_form()
        self.refresh_inventory()

    def _exit_inv_edit_mode(self):
        if self._editing_item_id is None:
            return
        self._editing_item_id = None
        self.inv_edit_button.setText("Edit Terpilih")
        self.inv_cancel_button.hide()
        self.inv_delete_button.setEnabled(True)
        self.inv_create_button.setEnabled(True)

    def _clear_inv_form(self):
        self._exit_inv_edit_mode()
        self.inv_kode_input.clear()
        self.inv_nama_input.clear()
        self.inv_jumlah_input.setValue(0)
        self.inv_satuan_input.clear()
        self.inv_tanggal_input.setDate(QDate.currentDate())
        self.inv_harga_input.setValue(0)
        self.inv_lokasi_input.clear()
        self.inv_kondisi_input.setCurrentIndex(0)
        self.inv_keterangan_input.clear()

    def _inv_form_values(self) -> dict:
        return {
            "kode_inventaris": self.inv_kode_input.text(),
            "nama_barang": self.inv_nama_input.text(),
            "jumlah": self.inv_jumlah_input.value(),
            "satuan": self.inv_satuan_input.text(),
            "tanggal_perolehan": self.inv_tanggal_input.date().toPython(),
            "harga_perolehan": self.inv_harga_input.value(),
            "lokasi": self.inv_lokasi_input.text(),
            "kondisi": self.inv_kondisi_input.currentText(),
            "keterangan": self.inv_keterangan_input.text(),
        }

    def _toggle_edit_user(self):
        if self._editing_row is not None:
            self._save_edit()
            return
        row = self.user_table.currentRow()
        if row < 0 or row >= len(self.user_ids):
            QMessageBox.information(
                self,
                "Pilih pengguna",
                "Pilih pengguna yang akan diedit.",
            )
            return
        self._start_edit(row)

    def _start_edit(self, row):
        self._editing_row = row
        self.user_table.setEditTriggers(
            QTableWidget.EditTrigger.DoubleClicked
        )
        is_owner_row = (
            self.user_table.item(row, 2) is not None
            and self.user_table.item(row, 2).text().upper() == "OWNER"
        )
        for column in range(self.user_table.columnCount()):
            item = self.user_table.item(row, column)
            if item is None:
                continue
            if is_owner_row and column == 2:
                continue
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
        self.edit_button.setText("Simpan Edit")
        self.cancel_edit_button.show()
        self.delete_button.setEnabled(False)
        first = self.user_table.item(row, 0)
        if first is not None:
            self.user_table.setCurrentItem(first)
            self.user_table.editItem(first)

    def _save_edit(self):
        row = self._editing_row
        if row is None:
            return
        user_id = self.user_ids[row]

        def cell_text(column):
            item = self.user_table.item(row, column)
            return item.text() if item else ""

        try:
            self.user_management.update_user(
                self.actor,
                user_id,
                username=cell_text(1),
                full_name=cell_text(0),
                role_name=cell_text(2),
                whatsapp=cell_text(3),
            )
        except (AuthorizationError, ValidationError, SQLAlchemyError) as exc:
            QMessageBox.warning(
                self, "Tidak dapat menyimpan perubahan", str(exc)
            )
            return
        self.refresh_users()
        QMessageBox.information(
            self,
            "Perubahan tersimpan",
            "Data pengguna berhasil diperbarui.",
        )

    def _cancel_edit(self):
        self.refresh_users()

    def _toggle_password_column(self):
        self._show_password = not self._show_password
        if self._show_password:
            self.password_toggle_button.setText("Sembunyi Password")
        else:
            self.password_toggle_button.setText("Tampilkan Password")
        self.refresh_users()

    def _reset_password(self):
        row = self.user_table.currentRow()
        if row < 0 or row >= len(self.user_ids):
            QMessageBox.information(
                self,
                "Pilih karyawan",
                "Pilih karyawan yang passwordnya akan direset.",
            )
            return
        user_id = self.user_ids[row]
        username = self.user_table.item(row, 1).text()
        full_name = self.user_table.item(row, 0).text()

        try:
            new_password = self.user_management.reset_password(
                self.actor, user_id
            )
        except (AuthorizationError, ValidationError, SQLAlchemyError) as exc:
            QMessageBox.warning(
                self, "Tidak dapat mereset password", str(exc)
            )
            return

        dialog = ResetPasswordDialog(
            full_name, username, new_password, self
        )
        if dialog.exec():
            self.refresh_users()

    def _exit_edit_mode(self):
        if self._editing_row is None:
            return
        self._editing_row = None
        self.user_table.setEditTriggers(
            QTableWidget.EditTrigger.NoEditTriggers
        )
        self.edit_button.setText("Edit Pengguna Terpilih")
        self.cancel_edit_button.hide()
        self.delete_button.setEnabled(True)

    def _delete_selected_user(self):
        row = self.user_table.currentRow()
        if row < 0:
            QMessageBox.information(
                self,
                "Pilih pengguna",
                "Pilih pengguna yang akan dihapus.",
            )
            return
        user_id = self.user_ids[row]
        username = self.user_table.item(row, 1).text()
        answer = QMessageBox.question(
            self,
            "Hapus pengguna",
            f"Akun {username} akan dihapus dan tidak dapat digunakan untuk login. "
            "Riwayat transaksi tetap tersimpan. Lanjutkan?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self.user_management.delete_user(self.actor, user_id)
        except (AuthorizationError, ValidationError, SQLAlchemyError) as exc:
            QMessageBox.warning(self, "Pengguna tidak dapat dihapus", str(exc))
            return
        self.refresh_users()

    def _create_user(self):
        password = self.password_input.text()
        if password != self.confirm_password_input.text():
            QMessageBox.warning(
                self,
                "Password tidak cocok",
                "Password dan konfirmasi password harus sama.",
            )
            return

        try:
            self.user_management.create_user(
                self.actor,
                username=self.username_input.text(),
                full_name=self.full_name_input.text(),
                password=password,
                role_name=self.role_input.text(),
                whatsapp=self.wa_input.text(),
            )
        except (AuthorizationError, ValidationError, SQLAlchemyError) as exc:
            QMessageBox.warning(self, "Tidak dapat membuat pengguna", str(exc))
            return

        self.username_input.clear()
        self.full_name_input.clear()
        self.wa_input.clear()
        self.role_input.clear()
        self.password_input.clear()
        self.confirm_password_input.clear()
        self.refresh_users()
        QMessageBox.information(
            self,
            "Pengguna ditambahkan",
            "Akun pengguna berhasil dibuat.",
        )

    def _toggle_password_visibility(self):
        """Sembunyikan field password jika jabatan adalah OWNER."""
        is_owner = "OWNER" in self.role_input.text().upper()
        self.password_input.setVisible(not is_owner)
        self.confirm_password_input.setVisible(not is_owner)
        for i in range(self.form_layout.rowCount()):
            label_item = self.form_layout.itemAt(
                i, QFormLayout.ItemRole.LabelRole
            )
            if label_item and label_item.widget():
                if label_item.widget().text() in ("Password", "Ulangi password"):
                    label_item.widget().setVisible(not is_owner)


class ResetPasswordDialog(QDialog):
    """Dialog untuk menampilkan password sementara baru kepada owner
    setelah mereset password karyawan."""

    def __init__(self, full_name: str, username: str, new_password: str,
                 parent=None):
        super().__init__(parent)
        self.setWindowTitle("Reset Password Berhasil")
        self.setModal(True)
        self.resize(420, 260)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        info = QLabel(
            f"Password sementara untuk <b>{full_name}</b> "
            f"(@{username}) telah dibuat."
        )
        info.setWordWrap(True)
        info.setStyleSheet("font-size: 14px; color: #ffffff;")
        layout.addWidget(info)

        pw_label = QLabel("Password sementara:")
        pw_label.setStyleSheet("font-size: 13px; color: #a1a1aa;")
        layout.addWidget(pw_label)

        self.pw_input = QLineEdit(new_password)
        self.pw_input.setReadOnly(True)
        self.pw_input.setStyleSheet(
            "font-size: 16px; font-family: monospace; "
            "padding: 8px; background: #1a1a1e; color: #ffffff; "
            "border: 1px solid #3f3f46; border-radius: 6px;"
        )
        layout.addWidget(self.pw_input)

        copy_btn = QPushButton("Salin Password")
        copy_btn.setStyleSheet(
            "QPushButton { background: #007acc; color: white; border: none; "
            "border-radius: 6px; padding: 8px 16px; font-weight: 600; }"
            "QPushButton:hover { background: #0098ff; }"
        )
        copy_btn.clicked.connect(self._copy_password)
        layout.addWidget(copy_btn)

        hint = QLabel(
            "Berikan password ini kepada karyawan. Karyawan wajib "
            "mengganti password pada login berikutnya."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("font-size: 12px; color: #a1a1aa;")
        layout.addWidget(hint)

        ok_btn = QPushButton("Selesai")
        ok_btn.setStyleSheet(
            "QPushButton { background: #007acc; color: white; border: none; "
            "border-radius: 6px; padding: 8px 24px; font-weight: 600; }"
            "QPushButton:hover { background: #0098ff; }"
        )
        ok_btn.clicked.connect(self.accept)
        layout.addWidget(ok_btn, alignment=Qt.AlignmentFlag.AlignRight)

    def _copy_password(self):
        from PySide6.QtGui import QGuiApplication
        clipboard = QGuiApplication.clipboard()
        clipboard.setText(self.pw_input.text())
