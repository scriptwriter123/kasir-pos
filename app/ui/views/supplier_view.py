from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy.exc import SQLAlchemyError

from app.core.exceptions import AuthorizationError, ValidationError
from app.models import Supplier
from app.services.supplier_service import SupplierService
from app.ui.widgets import (
    TableSearchBar,
    create_copyright_label,
    create_dashboard_back_button,
)


class SupplierFormDialog(QDialog):
    def __init__(
        self,
        supplier: Supplier | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.supplier = supplier
        self.setWindowTitle("Ubah Supplier" if supplier else "Tambah Supplier")
        self.setMinimumWidth(440)

        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.code_input = QLineEdit()
        self.code_input.setMaxLength(30)
        self.code_input.setPlaceholderText("Contoh: SUP-001")
        self.name_input = QLineEdit()
        self.name_input.setMaxLength(150)
        self.name_input.setPlaceholderText("Nama perusahaan / pemasok")
        self.phone_input = QLineEdit()
        self.phone_input.setMaxLength(30)
        self.phone_input.setPlaceholderText("Nomor telepon / WhatsApp")
        self.address_input = QLineEdit()
        self.address_input.setPlaceholderText("Alamat supplier")

        form.addRow("Kode supplier *", self.code_input)
        form.addRow("Nama supplier *", self.name_input)
        form.addRow("Telepon", self.phone_input)
        form.addRow("Alamat", self.address_input)
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

        if supplier is not None:
            self.code_input.setText(supplier.code)
            self.name_input.setText(supplier.name)
            self.phone_input.setText(supplier.phone or "")
            self.address_input.setText(supplier.address or "")

    def _validate_and_accept(self):
        if not self.code_input.text().strip():
            QMessageBox.warning(
                self,
                "Kode supplier wajib",
                "Isi kode supplier.",
            )
            self.code_input.setFocus()
            return
        if not self.name_input.text().strip():
            QMessageBox.warning(
                self,
                "Nama supplier wajib",
                "Isi nama supplier.",
            )
            self.name_input.setFocus()
            return
        self.accept()

    def form_data(self) -> dict:
        return {
            "supplier_id": self.supplier.id if self.supplier else None,
            "code": self.code_input.text(),
            "name": self.name_input.text(),
            "phone": self.phone_input.text(),
            "address": self.address_input.text(),
        }


class SupplierView(QWidget):
    back_requested = Signal()
    purchases_requested = Signal()

    def __init__(self, actor, session, parent=None, *, embedded=False):
        super().__init__(parent)
        self.actor = actor
        self.service = SupplierService(session)
        self.supplier_ids: list[int] = []

        root = QVBoxLayout(self)
        if embedded:
            # Di-embed sebagai tab di jendela Belanja dan Supplier;
            # judul & tombol kembali ditangani jendela induk.
            root.setContentsMargins(0, 8, 0, 0)
        else:
            root.setContentsMargins(32, 26, 32, 30)
        root.setSpacing(14)

        if not embedded:
            header = QHBoxLayout()
            self.back_button = create_dashboard_back_button(self)
            self.back_button.clicked.connect(self.back_requested.emit)
            title = QLabel("Data Supplier")
            title.setStyleSheet(
                "font-size: 25px; font-weight: 700; color: #ffffff;"
            )
            header.addWidget(self.back_button)
            header.addWidget(title)
            header.addStretch(1)
            root.addLayout(header)

        description = QLabel(
            "Catat dan perbarui informasi pemasok: kode, nama, nomor telepon, "
            "dan alamat."
        )
        description.setWordWrap(True)
        description.setStyleSheet("color: #a1a1aa;")
        root.addWidget(description)

        actions = QHBoxLayout()
        self.add_button = QPushButton("Tambah Supplier")
        self.add_button.clicked.connect(self._add_supplier)
        self.edit_button = QPushButton("Ubah Supplier")
        self.edit_button.clicked.connect(self._edit_selected_supplier)
        self.delete_button = QPushButton("Hapus Supplier")
        self.delete_button.clicked.connect(self._delete_selected_supplier)
        self.refresh_button = QPushButton("Muat Ulang")
        self.refresh_button.clicked.connect(self.refresh_suppliers)
        self.purchases_button = QPushButton("Catat Pembelian / Hutang")
        self.purchases_button.clicked.connect(self.purchases_requested.emit)
        actions.addWidget(self.add_button)
        actions.addWidget(self.edit_button)
        actions.addWidget(self.delete_button)
        actions.addWidget(self.refresh_button)
        actions.addWidget(self.purchases_button)
        actions.addStretch(1)
        root.addLayout(actions)

        self.supplier_table = QTableWidget(0, 4)
        self.supplier_table.setHorizontalHeaderLabels(
            ["Kode", "Nama Supplier", "Telepon", "Alamat"]
        )
        self.supplier_table.setEditTriggers(
            QTableWidget.EditTrigger.NoEditTriggers
        )
        self.supplier_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self.supplier_table.setSelectionMode(
            QTableWidget.SelectionMode.SingleSelection
        )
        self.supplier_table.horizontalHeader().setStretchLastSection(True)
        self.supplier_table.doubleClicked.connect(self._edit_selected_supplier)
        self.supplier_search = TableSearchBar(
            self.supplier_table, "Cari supplier..."
        )
        root.addWidget(self.supplier_search)
        root.addWidget(self.supplier_table, 1)
        root.addWidget(
            create_copyright_label(self),
            alignment=Qt.AlignmentFlag.AlignRight,
        )
        self.refresh_suppliers()

    def refresh_suppliers(self):
        try:
            suppliers = self.service.list_suppliers(self.actor)
        except (AuthorizationError, SQLAlchemyError) as exc:
            QMessageBox.critical(self, "Supplier gagal dimuat", str(exc))
            return

        self.supplier_ids = []
        self.supplier_table.setRowCount(len(suppliers))
        for row, supplier in enumerate(suppliers):
            self.supplier_ids.append(supplier.id)
            values = (
                supplier.code,
                supplier.name,
                supplier.phone or "-",
                supplier.address or "-",
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.supplier_table.setItem(row, column, item)
        self.supplier_table.resizeColumnsToContents()

    def _add_supplier(self):
        dialog = SupplierFormDialog(parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._save_form(dialog)

    def _edit_selected_supplier(self, *_args):
        row = self.supplier_table.currentRow()
        if row < 0:
            QMessageBox.information(
                self,
                "Pilih supplier",
                "Pilih supplier yang akan diubah.",
            )
            return
        supplier = self.service.session.get(Supplier, self.supplier_ids[row])
        if supplier is None or supplier.deleted_at is not None:
            QMessageBox.warning(
                self,
                "Supplier tidak ditemukan",
                "Muat ulang daftar supplier.",
            )
            self.refresh_suppliers()
            return
        dialog = SupplierFormDialog(supplier=supplier, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._save_form(dialog)

    def _delete_selected_supplier(self):
        row = self.supplier_table.currentRow()
        if row < 0:
            QMessageBox.information(
                self,
                "Pilih supplier",
                "Pilih supplier yang akan dihapus.",
            )
            return
        supplier_id = self.supplier_ids[row]
        supplier_name = self.supplier_table.item(row, 1).text()
        answer = QMessageBox.question(
            self,
            "Hapus supplier",
            f"Supplier {supplier_name} akan dihapus dari data aktif. "
            "Riwayat pembelian tetap tersimpan. Lanjutkan?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self.service.delete_supplier(self.actor, supplier_id)
        except (AuthorizationError, ValidationError, SQLAlchemyError) as exc:
            QMessageBox.warning(self, "Supplier tidak dapat dihapus", str(exc))
            return
        self.refresh_suppliers()

    def _save_form(self, dialog: SupplierFormDialog):
        try:
            supplier = self.service.save_supplier(self.actor, **dialog.form_data())
        except (AuthorizationError, ValidationError, SQLAlchemyError) as exc:
            QMessageBox.warning(self, "Supplier tidak dapat disimpan", str(exc))
            return
        self.refresh_suppliers()
        QMessageBox.information(
            self,
            "Supplier tersimpan",
            f"Data {supplier.name} berhasil disimpan.",
        )
