import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton, QTabWidget
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.core.exceptions import AuthorizationError, ValidationError
from app.models import Role, User
from app.repositories.user_repository import UserRepository
from app.services.inventory_service import InventoryService
from app.services.user_management_service import UserManagementService
from app.ui.views.user_management_view import UserManagementView


@pytest.fixture
def user_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = Session(engine)
    yield session
    session.close()
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def qt_app():
    return QApplication.instance() or QApplication([])


def make_user(session: Session, username: str, role_name: str) -> User:
    role = session.query(Role).filter_by(name=role_name).first()
    if role is None:
        role = Role(name=role_name)
        session.add(role)
        session.flush()
    user = User(
        username=username,
        full_name=username.title(),
        password_hash="not-used-in-this-test",
        role=role,
    )
    session.add(user)
    session.flush()
    return user


def make_inventory(session: Session) -> InventoryService:
    return InventoryService(session)


ITEM = {
    "kode_inventaris": "INV-001",
    "nama_barang": "Kursi Lipat",
    "jumlah": 12,
    "satuan": "pcs",
    "tanggal_perolehan": "2026-10-01",
    "harga_perolehan": 900000,
    "lokasi": "Rak A1",
    "kondisi": "Baik",
    "keterangan": "Beli di pasar",
}


def test_inventory_service_crud(user_session: Session):
    owner = make_user(user_session, "owner", "OWNER")
    service = make_inventory(user_session)

    created = service.create_item(owner, **ITEM)
    assert created.kode_inventaris == "INV-001"
    assert created.kondisi == "Baik"
    assert [i.id for i in service.list_items(owner)] == [created.id]

    updated = service.update_item(
        owner,
        created.id,
        **{**ITEM, "nama_barang": "Kursi Plastik", "jumlah": 20},
    )
    assert updated.nama_barang == "Kursi Plastik"
    assert updated.jumlah == 20
    assert str(updated.tanggal_perolehan) == "2026-10-01"

    service.delete_item(owner, created.id)
    assert service.list_items(owner) == []
    with pytest.raises(ValidationError, match="tidak ditemukan"):
        service.update_item(owner, created.id, **ITEM)


def test_inventory_service_validation(user_session: Session):
    owner = make_user(user_session, "owner", "OWNER")
    service = make_inventory(user_session)

    with pytest.raises(ValidationError, match="Kode inventaris wajib diisi"):
        service.create_item(owner, **{**ITEM, "kode_inventaris": "  "})
    with pytest.raises(ValidationError, match="Nama barang wajib diisi"):
        service.create_item(owner, **{**ITEM, "nama_barang": ""})
    with pytest.raises(ValidationError, match="Jumlah tidak boleh minus"):
        service.create_item(owner, **{**ITEM, "jumlah": -1})
    with pytest.raises(ValidationError, match="Tanggal perolehan wajib"):
        service.create_item(owner, **{**ITEM, "tanggal_perolehan": None})
    with pytest.raises(ValidationError, match="Kondisi harus"):
        service.create_item(owner, **{**ITEM, "kondisi": "Baru"})

    service.create_item(owner, **ITEM)
    with pytest.raises(ValidationError, match="Kode inventaris sudah digunakan"):
        service.create_item(owner, **{**ITEM, "nama_barang": "Lain"})

    with pytest.raises(AuthorizationError, match="Hanya OWNER"):
        service.create_item(
            make_user(user_session, "kasir", "CASHIER"), **ITEM
        )


def test_manajemen_toko_view_has_tabs(user_session: Session, qt_app):
    owner = make_user(user_session, "owner", "OWNER")
    service = UserManagementService(user_session, UserRepository(user_session))
    view = UserManagementView(owner, service)
    view.resize(1200, 760)
    view.show()
    qt_app.processEvents()

    tabs = view.findChildren(QTabWidget)
    assert tabs, "Jendela Manajemen Toko harus memakai tab"
    assert [tabs[0].tabText(i) for i in range(tabs[0].count())] == [
        "Pengaturan Toko",
        "Modal Awal",
        "Catat Pengeluaran",
        "Bayar Pengeluaran",
        "Tambah Karyawan",
        "Inventaris Toko",
        "Seting Pembayaran Kasir",
    ]
    # Tab "Modal Awal" = input Modal + checkbox aktivasi Laporan Keuangan.
    assert tabs[0].widget(1) is view.financial_view
    assert view.financial_view.activate_checkbox.text() == (
        "Aktifkan Laporan Keuangan"
    )
    # Tab "Catat Pengeluaran" = form simpan; tab "Bayar Pengeluaran" =
    # form pembayaran hutang.
    assert tabs[0].widget(2) is view.expense_entry_view
    assert tabs[0].widget(3) is view.expense_payment_view
    assert [
        button.text()
        for button in view.expense_entry_view.findChildren(QPushButton)
    ] == ["Simpan Pengeluaran", "Kosongkan"]
    # Tab Bayar: input + tombol Cari di atas tabel, lalu Bayar Sekarang.
    assert [
        button.text()
        for button in view.expense_payment_view.findChildren(QPushButton)
    ] == ["Cari", "Bayar Sekarang"]
    assert (
        view.expense_payment_view.expense_search.input.placeholderText()
        == "Cari pengeluaran..."
    )
    # Status Pembayaran di tab Catat: dropdown Tunai / Hutang / DP.
    entry = view.expense_entry_view
    assert [
        entry.status_input.itemText(index)
        for index in range(entry.status_input.count())
    ] == ["Tunai", "Hutang", "DP"]
    # Field Metode Pembayaran dihapus; Jumlah DP muncul hanya saat DP.
    assert not hasattr(entry, "payment_method_input")
    assert entry.dp_amount_input.isHidden()
    entry.status_input.setCurrentIndex(2)
    assert not entry.dp_amount_input.isHidden()
    entry.status_input.setCurrentIndex(1)
    assert entry.dp_amount_input.isHidden()
    entry.status_input.setCurrentIndex(0)
    # Tabel di tab Bayar: semua field pengeluaran berstatus Hutang/DP.
    # Input di bawah tabel sudah dihapus (bayar otomatis dari Kas).
    payment = view.expense_payment_view
    assert not hasattr(payment, "amount_input")
    assert not hasattr(payment, "sisa_input")
    assert not hasattr(payment, "payment_account_input")
    assert payment.expense_table.columnCount() == 9
    assert [
        payment.expense_table.horizontalHeaderItem(column).text()
        for column in range(payment.expense_table.columnCount())
    ] == [
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
    # Tab "Keuangan" lama sudah dihapus.
    assert not hasattr(view, "finance_operations_view")
    view.close()


def test_inventory_tab_crud(user_session: Session, qt_app, monkeypatch):
    monkeypatch.setattr(
        QMessageBox,
        "information",
        lambda *args, **kwargs: QMessageBox.StandardButton.Ok,
    )
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
    )
    owner = make_user(user_session, "owner", "OWNER")
    service = UserManagementService(user_session, UserRepository(user_session))
    view = UserManagementView(owner, service)
    view.resize(1200, 760)
    view.show()
    qt_app.processEvents()

    # CREATE lewat form
    view.inv_kode_input.setText("INV-100")
    view.inv_nama_input.setText("Meja Kerja")
    view.inv_jumlah_input.setValue(5)
    view.inv_satuan_input.setText("unit")
    view.inv_harga_input.setValue(500000)
    view.inv_lokasi_input.setText("Gudang")
    view.inv_kondisi_input.setCurrentText("Rusak Ringan")
    view.inv_keterangan_input.setText("Meja kayu")
    view.inv_create_button.click()
    qt_app.processEvents()
    assert view.inv_table.rowCount() == 1
    assert view.inv_table.item(0, 0).text() == "INV-100"
    assert view.inv_table.item(0, 5).text() == "500.000"
    assert view.inv_table.item(0, 7).text() == "Rusak Ringan"

    # UPDATE lewat Edit Terpilih → form → Simpan Perubahan
    view.inv_table.selectRow(0)
    view.inv_edit_button.click()
    qt_app.processEvents()
    assert view._editing_item_id is not None
    assert view.inv_edit_button.text() == "Simpan Perubahan"
    assert view.inv_create_button.isEnabled() is False
    view.inv_jumlah_input.setValue(9)
    view.inv_edit_button.click()
    qt_app.processEvents()
    assert view._editing_item_id is None
    assert view.inv_table.item(0, 2).text() == "9"

    # DELETE lewat Hapus Terpilih
    view.inv_table.selectRow(0)
    view.inv_delete_button.click()
    qt_app.processEvents()
    assert view.inv_table.rowCount() == 0

    view.close()
