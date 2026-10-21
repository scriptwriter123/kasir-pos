import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QLabel
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.core.exceptions import AuthorizationError, ValidationError
from app.models import Role, Supplier, User
from app.services.supplier_service import SupplierService
from app.ui.views.supplier_view import SupplierFormDialog, SupplierView
from app.ui.widgets import COPYRIGHT_CAPTION


@pytest.fixture
def supplier_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as session:
            owner_role = Role(name="OWNER")
            cashier_role = Role(name="CASHIER")
            session.add_all([owner_role, cashier_role])
            session.flush()
            owner = User(
                username="owner",
                full_name="Test Owner",
                password_hash="unused",
                role=owner_role,
            )
            cashier = User(
                username="cashier",
                full_name="Test Cashier",
                password_hash="unused",
                role=cashier_role,
            )
            session.add_all([owner, cashier])
            session.flush()
            yield session, owner, cashier
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


@pytest.fixture
def qt_app():
    return QApplication.instance() or QApplication([])


def test_supplier_service_creates_and_updates_supplier(supplier_session):
    session, owner, _cashier = supplier_session
    service = SupplierService(session)

    supplier = service.save_supplier(
        owner,
        supplier_id=None,
        code=" SUP-001 ",
        name="  Sumber Makmur ",
        phone="081234567890",
        address="  Jl. Niaga No. 1 ",
    )
    assert supplier.code == "SUP-001"
    assert supplier.name == "Sumber Makmur"
    assert supplier.phone == "081234567890"
    assert supplier.address == "Jl. Niaga No. 1"
    assert service.list_suppliers(owner) == [supplier]

    updated = service.save_supplier(
        owner,
        supplier_id=supplier.id,
        code="SUP-001",
        name="Sumber Makmur Baru",
        phone="",
        address="",
    )
    assert updated.id == supplier.id
    assert updated.name == "Sumber Makmur Baru"
    assert updated.phone is None
    assert updated.address is None


def test_supplier_service_enforces_owner_required_fields_and_unique_code(
    supplier_session,
):
    session, owner, cashier = supplier_session
    service = SupplierService(session)
    with pytest.raises(AuthorizationError):
        service.list_suppliers(cashier)
    with pytest.raises(AuthorizationError):
        service.save_supplier(
            cashier,
            supplier_id=None,
            code="SUP-001",
            name="Supplier",
            phone="",
            address="",
        )
    with pytest.raises(ValidationError, match="Kode supplier wajib"):
        service.save_supplier(
            owner,
            supplier_id=None,
            code=" ",
            name="Supplier",
            phone="",
            address="",
        )
    with pytest.raises(ValidationError, match="Nama supplier wajib"):
        service.save_supplier(
            owner,
            supplier_id=None,
            code="SUP-001",
            name=" ",
            phone="",
            address="",
        )

    service.save_supplier(
        owner,
        supplier_id=None,
        code="SUP-001",
        name="Supplier Satu",
        phone="",
        address="",
    )
    with pytest.raises(ValidationError, match="Kode supplier sudah digunakan"):
        service.save_supplier(
            owner,
            supplier_id=None,
            code="sup-001",
            name="Supplier Dua",
            phone="",
            address="",
        )


def test_supplier_service_soft_deletes_supplier(supplier_session):
    session, owner, cashier = supplier_session
    service = SupplierService(session)
    supplier = service.save_supplier(
        owner,
        supplier_id=None,
        code="SUP-DELETE",
        name="Supplier Hapus",
        phone="",
        address="",
    )

    with pytest.raises(AuthorizationError):
        service.delete_supplier(cashier, supplier.id)
    service.delete_supplier(owner, supplier.id)

    assert supplier.deleted_at is not None
    assert service.list_suppliers(owner) == []


def test_supplier_view_lists_form_and_copyright(supplier_session, qt_app):
    session, owner, _cashier = supplier_session
    SupplierService(session).save_supplier(
        owner,
        supplier_id=None,
        code="SUP-100",
        name="Pemasok Contoh",
        phone="0812",
        address="Alamat",
    )
    view = SupplierView(owner, session)
    assert view.supplier_table.rowCount() == 1
    assert view.supplier_table.item(0, 0).text() == "SUP-100"
    assert view.supplier_table.item(0, 1).text() == "Pemasok Contoh"
    assert view.delete_button.text() == "Hapus Supplier"

    dialog = SupplierFormDialog()
    credit = dialog.findChild(QLabel, "copyrightCredit")
    assert credit is not None
    assert credit.text() == COPYRIGHT_CAPTION
    dialog.close()
    view.close()
