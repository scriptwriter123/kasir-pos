import os
from decimal import Decimal

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import QApplication, QDialog, QLabel, QMessageBox
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.core.exceptions import AuthorizationError, ValidationError
from app.models import (
    BulkPriceRule,
    Category,
    Product,
    Role,
    StockMovement,
    Supplier,
    Unit,
    User,
)
from app.repositories.product_repository import ProductRepository
from app.services.master_data_service import MasterDataService
from app.services.bulk_pricing_service import BulkPricingService
from app.services.supplier_service import SupplierService
from app.ui.views.cashier_view import CashierView
from app.ui.views.master_data_view import (
    AddStockDialog,
    BulkPriceDialog,
    CategoryBatchDialog,
    MasterDataView,
    ProductFormDialog,
)
from app.ui.widgets import COPYRIGHT_CAPTION


@pytest.fixture
def master_session():
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
            category = Category(name="Minuman")
            unit = Unit(name="Piece", symbol="pcs")
            session.add_all([owner_role, cashier_role, category, unit])
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
            yield session, owner, cashier, category, unit
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


def test_owner_can_create_category_and_product_with_initial_stock_movement(
    master_session,
):
    session, owner, _cashier, category, unit = master_session
    service = MasterDataService(session)
    snack_category = service.create_category(owner, "  Makanan Ringan ")
    product = service.save_product(
        owner,
        product_id=None,
        sku=" SNK-001 ",
        barcode=" 899123 ",
        name="  Keripik Singkong ",
        category_id=snack_category.id,
        unit_id=unit.id,
        purchase_price=5_000,
        selling_price=7_000,
        stock_qty=12,
        min_stock=3,
        is_active=True,
    )

    movement = session.scalar(
        select(StockMovement).where(StockMovement.product_id == product.id)
    )
    assert snack_category.name == "Makanan Ringan"
    assert product.sku == "SNK-001"
    assert product.barcode == "899123"
    assert product.category_id == snack_category.id
    assert product.stock_qty == 12
    assert movement is not None
    assert movement.movement_type == "INITIAL_STOCK"
    assert movement.qty == 12


def test_owner_can_create_multiple_categories_atomically(master_session):
    _session, owner, cashier, _category, _unit = master_session
    service = MasterDataService(_session)

    created = service.create_categories(
        owner,
        [" Snack ", "", "  Minuman Kemasan "],
    )

    assert [category.name for category in created] == [
        "Snack",
        "Minuman Kemasan",
    ]
    with pytest.raises(AuthorizationError):
        service.create_categories(cashier, ["Tidak Diizinkan"])
    with pytest.raises(ValidationError, match="duplikat"):
        service.create_categories(owner, ["Bumbu", " bumbu "])
    with pytest.raises(ValidationError, match="sudah ada"):
        service.create_categories(owner, ["Baru", "Minuman"])
    assert [category.name for category in service.list_categories()] == [
        "Minuman",
        "Minuman Kemasan",
        "Snack",
    ]


def test_category_batch_dialog_has_five_inputs_and_ignores_blank_fields(
    master_session,
    qt_app,
):
    dialog = CategoryBatchDialog()

    assert len(dialog.category_inputs) == 5
    dialog.category_inputs[0].setText("Makanan")
    dialog.category_inputs[2].setText("Minuman")
    assert dialog.category_names() == [
        "Makanan",
        "",
        "Minuman",
        "",
        "",
    ]
    dialog.close()


def test_owner_can_soft_delete_product_without_removing_stock_history(
    master_session,
):
    session, owner, cashier, category, unit = master_session
    service = MasterDataService(session)
    product = service.save_product(
        owner,
        product_id=None,
        sku="DRK-DELETE",
        barcode="",
        name="Produk Hapus",
        category_id=category.id,
        unit_id=unit.id,
        purchase_price=1_000,
        selling_price=2_000,
        stock_qty=3,
        min_stock=0,
        is_active=True,
    )

    with pytest.raises(AuthorizationError):
        service.delete_product(cashier, product.id)
    service.delete_product(owner, product.id)

    assert product.deleted_at is not None
    assert product.is_active is False
    assert product.stock_qty == 3
    assert service.list_products() == []
    assert session.scalar(
        select(StockMovement).where(StockMovement.product_id == product.id)
    ) is not None


def test_owner_can_add_stock_and_record_movement(master_session):
    session, owner, cashier, category, unit = master_session
    service = MasterDataService(session)
    product = service.save_product(
        owner,
        product_id=None,
        sku="STOCK-001",
        barcode="",
        name="Produk Stok",
        category_id=category.id,
        unit_id=unit.id,
        purchase_price=1_000,
        selling_price=2_000,
        stock_qty=4,
        min_stock=0,
        is_active=True,
    )

    with pytest.raises(AuthorizationError):
        service.add_stock(cashier, product.id, 3)
    with pytest.raises(ValidationError, match="lebih dari 0"):
        service.add_stock(owner, product.id, 0)

    updated = service.add_stock(owner, product.id, 3)
    movement = session.scalar(
        select(StockMovement).where(
            StockMovement.product_id == product.id,
            StockMovement.movement_type == "STOCK_ADDITION",
        )
    )
    assert updated.stock_qty == 7
    assert movement is not None
    assert movement.stock_before == 4
    assert movement.qty == 3
    assert movement.stock_after == 7
    assert movement.reference_type == "MANUAL"


def test_product_search_supports_sku_barcode_name_and_category(
    master_session,
):
    session, owner, _cashier, category, unit = master_session
    product = MasterDataService(session).save_product(
        owner,
        product_id=None,
        sku="DRK-001",
        barcode="899001",
        name="Teh Botol",
        category_id=category.id,
        unit_id=unit.id,
        purchase_price=2_000,
        selling_price=3_000,
        stock_qty=8,
        min_stock=2,
        is_active=True,
    )
    repository = ProductRepository(session)

    assert repository.find_by_barcode_or_sku("899001") is product
    assert repository.find_by_barcode_or_sku("DRK-001") is product
    assert repository.search_active("Teh Botol") == [product]
    assert repository.search_active("Minuman") == [product]


def test_master_product_can_select_a_preferred_supplier(master_session, qt_app):
    session, owner, _cashier, category, unit = master_session
    supplier = SupplierService(session).save_supplier(
        owner,
        supplier_id=None,
        code="SUP-DRINK",
        name="Pemasok Minuman",
        phone="0800",
        address="Alamat",
    )
    product = MasterDataService(session).save_product(
        owner,
        product_id=None,
        sku="DRK-004",
        barcode="",
        name="Air Mineral",
        category_id=category.id,
        unit_id=unit.id,
        purchase_price=1_000,
        selling_price=2_000,
        stock_qty=4,
        min_stock=1,
        is_active=True,
        supplier_id=supplier.id,
    )
    dialog = ProductFormDialog(
        [category],
        [unit],
        [supplier],
        product=product,
    )

    assert product.supplier_id == supplier.id
    assert dialog.supplier_input.currentData() == supplier.id
    assert dialog.form_data()["supplier_id"] == supplier.id
    dialog.close()


def test_master_data_search_filters_product_category_and_supplier(
    master_session,
    qt_app,
):
    session, owner, _cashier, category, unit = master_session
    supplier = SupplierService(session).save_supplier(
        owner,
        supplier_id=None,
        code="SUP-TEA",
        name="Pemasok Hijau",
        phone="",
        address="",
    )
    product = MasterDataService(session).save_product(
        owner,
        product_id=None,
        sku="TEA-001",
        barcode="",
        name="Teh Botol",
        category_id=category.id,
        unit_id=unit.id,
        purchase_price=1_000,
        selling_price=2_000,
        stock_qty=4,
        min_stock=0,
        is_active=True,
        supplier_id=supplier.id,
    )
    view = MasterDataView(owner, session)

    for query in ("Botol", "Minuman", "Pemasok Hijau"):
        view.search_input.setText(query)
        assert view.product_table.rowCount() == 1
        assert view.product_table.item(0, 0).text() == product.sku

    view.search_input.setText("tidak ada")
    assert view.product_table.rowCount() == 0
    view.close()


def test_owner_can_configure_bulk_price_rule_from_master_data(
    master_session,
    qt_app,
    monkeypatch,
):
    session, owner, _cashier, category, unit = master_session
    product = MasterDataService(session).save_product(
        owner,
        product_id=None,
        sku="BULK-001",
        barcode="",
        name="Produk Partai",
        category_id=category.id,
        unit_id=unit.id,
        purchase_price=1_000,
        selling_price=2_000,
        stock_qty=10,
        min_stock=0,
        is_active=True,
    )
    view = MasterDataView(owner, session)
    dialog = BulkPriceDialog(
        BulkPricingService(session),
        owner,
        [product],
        view,
    )
    assert not view.bulk_price_button.isHidden()
    assert dialog.windowTitle() == "Harga Spesial Partai"
    dialog.tier_rows[1].active_checkbox.setChecked(False)

    dialog.tier_rows[0].threshold_input.setValue(5)
    dialog.tier_rows[0].discount_input.setValue(12.5)
    assert dialog.tier_rows[0].price_input.value() == 1_750
    assert dialog.regular_price_label.text() == "Rp 2.000,00"
    monkeypatch.setattr(
        QMessageBox,
        "information",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.Ok,
    )
    dialog._save_rule()

    rule = session.scalar(
        select(BulkPriceRule).where(BulkPriceRule.product_id == product.id)
    )
    assert rule is not None
    assert rule.quantity_threshold == 5
    assert rule.discount_percent == Decimal("12.50")
    assert rule.special_price == 1_750
    assert rule.pricing_mode == "PERCENT"
    assert dialog.rules_table.rowCount() == 1

    dialog.tier_rows[0].price_input.setValue(1_600)
    assert dialog.tier_rows[0].discount_input.value() == 20
    dialog._save_rule()
    session.refresh(rule)
    assert rule.special_price == 1_600
    assert rule.discount_percent == Decimal("20.00")
    assert rule.pricing_mode == "PRICE"

    second_product = MasterDataService(session).save_product(
        owner,
        product_id=None,
        sku="BULK-002",
        barcode="",
        name="Produk Partai Kedua",
        category_id=category.id,
        unit_id=unit.id,
        purchase_price=1_000,
        selling_price=3_000,
        stock_qty=10,
        min_stock=0,
        is_active=True,
    )
    BulkPricingService(session).save_rule(
        actor=owner,
        product_id=second_product.id,
        quantity_threshold=3,
        discount_percent=Decimal("10"),
        special_price=2_700,
        pricing_mode="PERCENT",
    )
    dialog.products.append(second_product)
    dialog.product_input.addItem(
        f"{second_product.name} ({second_product.sku})",
        second_product.id,
    )
    dialog._refresh_rules()
    second_row = next(
        row
        for row in range(dialog.rules_table.rowCount())
        if dialog.rules_table.item(row, 0).data(Qt.ItemDataRole.UserRole)
        == second_product.id
    )
    dialog._select_rule_from_table(second_row, 0)
    assert dialog.product_input.currentData() == second_product.id
    assert dialog.tier_rows[0].threshold_input.value() == 3
    dialog.close()
    view.close()


def test_master_data_add_stock_dialog_shows_product_and_current_stock(
    master_session,
    qt_app,
):
    session, owner, _cashier, category, unit = master_session
    product = MasterDataService(session).save_product(
        owner,
        product_id=None,
        sku="STOCK-POPUP",
        barcode="",
        name="Produk Popup",
        category_id=category.id,
        unit_id=unit.id,
        purchase_price=1_000,
        selling_price=2_000,
        stock_qty=6,
        min_stock=0,
        is_active=True,
    )
    dialog = AddStockDialog(product)

    assert dialog.product_name_label.text() == "Produk Popup"
    assert dialog.current_stock_label.text() == "6"
    assert dialog.additional_stock_input.value() == 1
    assert dialog.additional_stock_input.minimum() == 1
    dialog.close()


def test_master_data_add_stock_button_updates_selected_product(
    master_session,
    qt_app,
    monkeypatch,
):
    session, owner, _cashier, category, unit = master_session
    product = MasterDataService(session).save_product(
        owner,
        product_id=None,
        sku="STOCK-BUTTON",
        barcode="",
        name="Produk Tombol",
        category_id=category.id,
        unit_id=unit.id,
        purchase_price=1_000,
        selling_price=2_000,
        stock_qty=2,
        min_stock=0,
        is_active=True,
    )
    view = MasterDataView(owner, session)
    view.product_table.selectRow(0)

    def accept_dialog(dialog):
        dialog.additional_stock_input.setValue(5)
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(AddStockDialog, "exec", accept_dialog)
    monkeypatch.setattr(QMessageBox, "information", lambda *args: None)
    view.add_stock_button.click()

    assert session.get(Product, product.id).stock_qty == 7
    assert view.product_table.item(0, 8).text() == "7"
    view.close()


def test_cashier_can_scan_product_created_in_master_data(
    master_session,
    qt_app,
    monkeypatch,
):
    session, owner, cashier, category, unit = master_session
    product = MasterDataService(session).save_product(
        owner,
        product_id=None,
        sku="DRK-002",
        barcode="899002",
        name="Susu Kotak",
        category_id=category.id,
        unit_id=unit.id,
        purchase_price=3_000,
        selling_price=4_000,
        stock_qty=5,
        min_stock=1,
        is_active=True,
    )
    monkeypatch.setattr(
        "PySide6.QtWidgets.QInputDialog.getInt",
        lambda *args: (2, True),
    )

    cashier_view = CashierView(cashier, session)
    cashier_view.search_input.setText(product.barcode)
    cashier_view._search_products()

    assert cashier_view.cart[product.id]["qty"] == 2
    cashier_view.search_input.setText(category.name)
    cashier_view._search_products()
    assert cashier_view.product_table.rowCount() == 1
    assert cashier_view.product_table.item(0, 2).text() == category.name
    cashier_view.close()


def test_master_data_rejects_non_owner_and_duplicate_product_identifiers(
    master_session,
):
    session, owner, cashier, category, unit = master_session
    service = MasterDataService(session)
    values = {
        "product_id": None,
        "sku": "DRK-003",
        "barcode": "899003",
        "name": "Jus",
        "category_id": category.id,
        "unit_id": unit.id,
        "purchase_price": 1_000,
        "selling_price": 2_000,
        "stock_qty": 1,
        "min_stock": 0,
        "is_active": True,
    }

    with pytest.raises(AuthorizationError):
        service.save_product(cashier, **values)
    service.save_product(owner, **values)
    with pytest.raises(ValidationError, match="SKU sudah digunakan"):
        service.save_product(
            owner,
            **{**values, "barcode": "another-code", "name": "Produk lain"},
        )
    with pytest.raises(ValidationError, match="Kategori dengan nama"):
        service.create_category(owner, "minuman")


def test_product_entry_dialog_shows_copyright_credit(master_session, qt_app):
    _session, _owner, _cashier, category, unit = master_session
    dialog = ProductFormDialog([category], [unit], [])
    credit = dialog.findChild(QLabel, "copyrightCredit")

    assert credit is not None
    assert credit.text() == COPYRIGHT_CAPTION
    dialog.close()


def test_product_form_configures_bulk_pricing_with_product(
    master_session,
    qt_app,
    monkeypatch,
):
    session, owner, _cashier, category, unit = master_session
    view = MasterDataView(owner, session)
    dialog = view._create_product_dialog()
    assert dialog is not None
    assert "≥2" in dialog.bulk_flow_label.text()

    dialog.sku_input.setText("FORM-BULK")
    dialog.name_input.setText("Produk Form Partai")
    dialog.category_input.setCurrentIndex(
        dialog.category_input.findData(category.id)
    )
    dialog.unit_input.setCurrentIndex(dialog.unit_input.findData(unit.id))
    dialog.purchase_price.setValue(1_000)
    dialog.selling_price.setValue(2_000)
    dialog.bulk_enabled_input.setChecked(True)
    dialog.bulk_tier_rows[0].threshold_input.setValue(6)
    dialog.bulk_tier_rows[0].price_input.setValue(1_500)
    dialog.bulk_tier_rows[1].active_checkbox.setChecked(False)

    assert dialog.bulk_tier_rows[0].discount_input.value() == 25
    monkeypatch.setattr(QMessageBox, "information", lambda *_args: None)
    view._save_form(dialog)

    product = session.scalar(
        select(Product).where(Product.sku == "FORM-BULK")
    )
    assert product is not None
    rule = session.scalar(
        select(BulkPriceRule).where(BulkPriceRule.product_id == product.id)
    )
    assert rule is not None
    assert rule.quantity_threshold == 6
    assert rule.special_price == 1_500
    assert rule.discount_percent == Decimal("25.00")
    assert rule.pricing_mode == "PRICE"
    view.close()


def test_product_form_saves_three_bulk_tiers(
    master_session,
    qt_app,
    monkeypatch,
):
    session, owner, _cashier, category, unit = master_session
    view = MasterDataView(owner, session)
    dialog = view._create_product_dialog()
    assert dialog is not None

    dialog.sku_input.setText("FORM-TIER3")
    dialog.name_input.setText("Produk Tiga Tingkat")
    dialog.category_input.setCurrentIndex(
        dialog.category_input.findData(category.id)
    )
    dialog.unit_input.setCurrentIndex(dialog.unit_input.findData(unit.id))
    dialog.purchase_price.setValue(1_000)
    dialog.selling_price.setValue(2_000)
    dialog.bulk_enabled_input.setChecked(True)
    dialog.bulk_tier_rows[0].price_input.setValue(1_900)
    dialog.bulk_tier_rows[1].price_input.setValue(1_800)
    dialog.bulk_tier_rows[2].active_checkbox.setChecked(True)
    dialog.bulk_tier_rows[2].threshold_input.setValue(5)
    dialog.bulk_tier_rows[2].price_input.setValue(1_700)

    monkeypatch.setattr(QMessageBox, "information", lambda *_args: None)
    view._save_form(dialog)

    product = session.scalar(
        select(Product).where(Product.sku == "FORM-TIER3")
    )
    assert product is not None
    service = BulkPricingService(session)
    rules = service.rules_for_product(product.id)
    assert [
        (rule.quantity_threshold, rule.special_price) for rule in rules
    ] == [(2, 1_900), (3, 1_800), (5, 1_700)]
    assert service.unit_price(product, 1) == 2_000
    assert service.unit_price(product, 2) == 1_900
    assert service.unit_price(product, 3) == 1_800
    assert service.unit_price(product, 4) == 1_800
    assert service.unit_price(product, 5) == 1_700
    assert service.unit_price(product, 9) == 1_700
    view.close()


def test_bulk_pricing_service_replaces_stale_tiers(master_session):
    session, owner, _cashier, category, unit = master_session
    product = MasterDataService(session).save_product(
        owner,
        product_id=None,
        sku="TIER-STALE",
        barcode="",
        name="Produk Ganti Tingkat",
        category_id=category.id,
        unit_id=unit.id,
        purchase_price=1_000,
        selling_price=2_000,
        stock_qty=10,
        min_stock=0,
        is_active=True,
    )
    service = BulkPricingService(session)
    service.save_rules(
        owner,
        product.id,
        [
            {
                "quantity_threshold": 2,
                "discount_percent": Decimal("5"),
                "special_price": 1_900,
                "pricing_mode": "PERCENT",
            },
            {
                "quantity_threshold": 5,
                "discount_percent": Decimal("15"),
                "special_price": 1_700,
                "pricing_mode": "PERCENT",
            },
        ],
    )
    assert len(service.rules_for_product(product.id)) == 2

    service.save_rules(
        owner,
        product.id,
        [
            {
                "quantity_threshold": 3,
                "discount_percent": Decimal("10"),
                "special_price": 1_800,
                "pricing_mode": "PERCENT",
            }
        ],
    )
    rules = service.rules_for_product(product.id)
    assert len(rules) == 1
    assert rules[0].quantity_threshold == 3
    assert rules[0].special_price == 1_800
