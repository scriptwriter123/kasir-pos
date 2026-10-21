import csv

from openpyxl import load_workbook
import pytest
from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QApplication, QPushButton
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.database import Base
from app.core.exceptions import AuthorizationError
from app.models import (
    Category,
    Product,
    Role,
    StockMovement,
    Unit,
    User,
)
from app.services.product_import_service import (
    PRODUCT_HEADERS,
    ProductImportService,
)
from app.ui.views.master_data_view import (
    EditExcelDialog,
    MasterDataView,
    ProductFileImportDialog,
)


@pytest.fixture
def import_session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as session:
            role = Role(name="OWNER")
            cashier_role = Role(name="CASHIER")
            category = Category(name="Minuman")
            unit = Unit(name="Botol", symbol="btl")
            session.add_all([role, cashier_role, category, unit])
            session.flush()
            owner = User(
                username="import-owner",
                full_name="Import Owner",
                password_hash="unused",
                role=role,
            )
            cashier = User(
                username="import-cashier",
                full_name="Import Cashier",
                password_hash="unused",
                role=cashier_role,
            )
            existing = Product(
                sku="OLD-1",
                barcode="100",
                name="Produk Lama",
                category=category,
                unit=unit,
                purchase_price=1000,
                selling_price=2000,
                stock_qty=8,
                min_stock=2,
            )
            session.add_all([owner, cashier, existing])
            session.commit()
            yield session, owner, cashier, category, unit, existing
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


@pytest.fixture
def qt_app():
    app = QApplication.instance() or QApplication([])
    yield app
    for widget in app.topLevelWidgets():
        widget.close()
        widget.deleteLater()
    app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


def record(
    sku="NEW-1",
    name="Produk Baru",
    stock=5,
    *,
    category="Minuman",
    unit="Botol",
    symbol="btl",
):
    return dict(
        zip(
            PRODUCT_HEADERS,
            [
                sku,
                "",
                name,
                category,
                unit,
                symbol,
                "",
                1000,
                2000,
                stock,
                1,
                "Ya",
            ],
        )
    )


def test_import_records_updates_existing_without_changing_stock_and_tracks_new(
    import_session,
):
    session, owner, _cashier, _category, _unit, existing = import_session
    service = ProductImportService(session)

    result = service.import_records(
        owner,
        [
            record(
                sku=existing.sku,
                name="Nama Diperbarui",
                stock=99,
            ),
            record(stock=4),
        ],
    )

    assert result == {"created": 1, "updated": 1, "errors": []}
    session.refresh(existing)
    assert existing.name == "Nama Diperbarui"
    assert existing.stock_qty == 8
    new_product = session.scalar(select(Product).where(Product.sku == "NEW-1"))
    assert new_product is not None
    assert new_product.stock_qty == 4
    movement = session.scalar(
        select(StockMovement).where(StockMovement.product_id == new_product.id)
    )
    assert movement is not None
    assert movement.movement_type == "INITIAL_STOCK"


def test_import_rejects_invalid_file_without_partial_writes(import_session):
    session, owner, _cashier, _category, _unit, _existing = import_session
    service = ProductImportService(session)
    result = service.import_records(
        owner,
        [record(), record(sku="NEW-1", name="Duplikat")],
    )

    assert result["created"] == result["updated"] == 0
    assert "SKU duplikat" in result["errors"][0]
    assert session.scalar(select(Product).where(Product.sku == "NEW-1")) is None


def test_import_requires_owner(import_session):
    session, _owner, cashier, _category, _unit, _existing = import_session
    with pytest.raises(AuthorizationError):
        ProductImportService(session).import_records(cashier, [record()])


def test_excel_template_roundtrips_through_import(import_session, tmp_path):
    session, owner, _cashier, _category, _unit, _existing = import_session
    service = ProductImportService(session)
    path = service.export_template(tmp_path / "products.xlsx")
    workbook = load_workbook(path)
    sheet = workbook.active
    assert tuple(cell.value for cell in sheet[1]) == PRODUCT_HEADERS
    sheet.append(
        [
            "XLS-1",
            "",
            "Produk Excel",
            "Minuman",
            "Botol",
            "btl",
            "",
            1000,
            2500,
            6,
            2,
            "Ya",
        ]
    )
    workbook.save(path)
    workbook.close()

    result = service.import_file(owner, path)

    assert result == {"created": 1, "updated": 1, "errors": []}
    imported = session.scalar(select(Product).where(Product.sku == "XLS-1"))
    assert imported is not None
    assert imported.name == "Produk Excel"
    assert imported.stock_qty == 6


def test_csv_import_accepts_reordered_headers(import_session, tmp_path):
    session, owner, _cashier, _category, _unit, _existing = import_session
    csv_path = tmp_path / "products.csv"
    headers = list(reversed(PRODUCT_HEADERS))
    values = record(sku="CSV-1", name="Produk CSV")
    with csv_path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=headers)
        writer.writeheader()
        writer.writerow(values)

    result = ProductImportService(session).import_file(owner, csv_path)

    assert result == {"created": 1, "updated": 0, "errors": []}
    product = session.scalar(select(Product).where(Product.sku == "CSV-1"))
    assert product is not None
    assert product.name == "Produk CSV"


def test_import_database_merges_products_without_importing_other_data(
    import_session,
    tmp_path,
):
    session, owner, _cashier, _category, _unit, existing = import_session
    source_path = tmp_path / "source.db"
    source_engine = create_engine(f"sqlite:///{source_path}")
    Base.metadata.create_all(source_engine)
    try:
        with Session(source_engine) as source:
            role = Role(name="OWNER")
            category = Category(name="Snack")
            unit = Unit(name="Pack", symbol="pak")
            source.add_all([role, category, unit])
            source.flush()
            cashier = User(
                username="source-owner",
                full_name="Source Owner",
                password_hash="unused",
                role=role,
            )
            source.add(cashier)
            source.flush()
            source.add(
                Product(
                    sku="DB-1",
                    name="Produk Database",
                    category=category,
                    unit=unit,
                    purchase_price=500,
                    selling_price=1000,
                    stock_qty=12,
                    min_stock=2,
                )
            )
            source.commit()

        service = ProductImportService(session)
        preview = service.preview_database(source_path)
        assert len(preview) == 1
        result = service.import_database(owner, source_path)

        assert result == {"created": 1, "updated": 0, "errors": []}
        assert session.scalar(select(Product).where(Product.sku == "DB-1")) is not None
        assert session.scalar(select(Category).where(Category.name == "Snack")) is not None
        assert session.scalar(select(Unit).where(Unit.name == "Pack")) is not None
        assert existing.stock_qty == 8
        assert session.scalar(select(User).where(User.username == "source-owner")) is None
    finally:
        source_engine.dispose()


def test_import_menu_has_four_workflows(import_session, qt_app):
    session, owner, *_ = import_session
    view = MasterDataView(owner, session)
    assert view.import_button.text() == "Import Data   ▾"
    from app.ui.theme import PALETTE

    assert f"QToolButton {{ background: {PALETTE['accent']}" in view.import_button.styleSheet()
    assert "color: white" in view.import_button.styleSheet()
    back_button = view.findChild(QPushButton, "dashboardBackButton")
    assert back_button is not None
    assert not back_button.icon().isNull()
    assert [action.text() for action in view.import_button.menu().actions()] == [
        "Import Excel",
        "Import database",
        "Import CSV",
        "Edit Excel",
    ]
    assert ProductFileImportDialog("excel", view.import_service, owner, view)
    assert EditExcelDialog(view.import_service, owner, view)
    view.close()
