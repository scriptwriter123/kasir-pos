import os
from datetime import date
from decimal import Decimal

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialog, QLabel, QMessageBox
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.core.exceptions import AuthorizationError, ValidationError
from app.models import (
    Account,
    FinancialPayment,
    Product,
    PurchaseOrder,
    PurchaseOrderItem,
    Role,
    StockMovement,
    Store,
    Supplier,
    User,
)
from app.services.financial_service import FinancialService
from app.services.bulk_pricing_service import BulkPricingService
from app.services.master_data_service import MasterDataService
from app.services.purchase_service import PurchaseService
from app.ui.views.purchase_view import NewProductDialog, PurchaseView


@pytest.fixture
def purchase_session():
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
            store = Store(code="MAIN", name="Toko Contoh")
            supplier = Supplier(code="SUP-001", name="Pemasok Contoh")
            product = Product(
                sku="SKU-001",
                name="Beras",
                purchase_price=10_000,
                selling_price=12_000,
                stock_qty=8,
                is_active=True,
            )
            session.add_all([owner_role, cashier_role, store, supplier, product])
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
            accounts = [
                Account(
                    code=code,
                    name=name,
                    account_type=account_type,
                    is_active=True,
                    is_system=True,
                )
                for code, name, account_type in (
                    ("1000", "Kas", "ASSET"),
                    ("1010", "Bank", "ASSET"),
                    ("1200", "Persediaan", "ASSET"),
                    ("2000", "Hutang Usaha", "LIABILITY"),
                    ("3000", "Modal Pemilik", "EQUITY"),
                    ("3100", "Saldo Awal", "EQUITY"),
                    ("4000", "Penjualan", "REVENUE"),
                    ("5000", "Harga Pokok Penjualan", "EXPENSE"),
                )
            ]
            session.add_all([owner, cashier, *accounts])
            session.flush()
            account_ids = {account.code: account.id for account in accounts}
            opening_inventory = product.stock_qty * product.purchase_price
            FinancialService(session).initialize(
                owner,
                date.today(),
                {
                    account_ids["1000"]: 1_000_000,
                    account_ids["1200"]: opening_inventory,
                    account_ids["3000"]: 1_000_000 + opening_inventory,
                },
            )
            yield session, owner, cashier, supplier, product
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


@pytest.fixture
def qt_app():
    return QApplication.instance() or QApplication([])


def test_record_tempo_purchase_tracks_debt_due_date_and_stock(
    purchase_session,
):
    session, owner, _cashier, supplier, product = purchase_session
    service = PurchaseService(session)
    due_date = date(2026, 11, 1)

    purchase = service.record_purchase(
        owner,
        supplier_id=supplier.id,
        product_id=product.id,
        quantity=5,
        unit_cost=11_000,
        payment_status="TEMPO",
        due_date=due_date,
    )

    item = session.scalar(
        select(PurchaseOrderItem).where(
            PurchaseOrderItem.purchase_order_id == purchase.id
        )
    )
    movement = session.scalar(
        select(StockMovement).where(
            StockMovement.reference_id == purchase.id,
            StockMovement.reference_type == "PURCHASE_ORDER",
        )
    )
    assert purchase.status == "RECEIVED"
    assert purchase.payment_status == "TEMPO"
    assert purchase.subtotal == 55_000
    assert purchase.paid_amount == 0
    assert purchase.due_date.date() == due_date
    assert product.stock_qty == 13
    assert product.purchase_price == 11_000
    assert item is not None and item.received_qty == 5
    assert movement is not None
    assert movement.stock_before == 8
    assert movement.stock_after == 13
    listed = service.list_purchases(owner)
    assert listed[0]["supplier_name"] == supplier.name
    assert listed[0]["product_name"] == product.name


def test_record_paid_purchase_is_fully_settled(
    purchase_session,
):
    session, owner, _cashier, supplier, product = purchase_session
    purchase = PurchaseService(session).record_purchase(
        owner,
        supplier_id=supplier.id,
        product_id=product.id,
        quantity=2,
        unit_cost=9_000,
        payment_status="PAID",
        due_date=date(2026, 11, 1),
    )

    assert purchase.payment_status == "PAID"
    assert purchase.paid_amount == purchase.subtotal == 18_000
    assert purchase.due_date is None


def test_purchase_price_rise_raises_selling_price_keeping_margin(
    purchase_session,
):
    session, owner, _cashier, supplier, product = purchase_session
    assert product.purchase_price == 10_000
    assert product.selling_price == 12_000

    PurchaseService(session).record_purchase(
        owner,
        supplier_id=supplier.id,
        product_id=product.id,
        quantity=5,
        unit_cost=12_000,
        payment_status="PAID",
        due_date=None,
    )

    assert product.purchase_price == 12_000
    assert product.selling_price == 14_400


def test_purchase_price_drop_keeps_selling_price(purchase_session):
    session, owner, _cashier, supplier, product = purchase_session

    PurchaseService(session).record_purchase(
        owner,
        supplier_id=supplier.id,
        product_id=product.id,
        quantity=5,
        unit_cost=9_000,
        payment_status="PAID",
        due_date=None,
    )

    assert product.purchase_price == 9_000
    assert product.selling_price == 12_000


def test_price_rise_updates_fixed_and_percent_special_prices(
    purchase_session,
):
    session, owner, _cashier, supplier, product = purchase_session
    bulk = BulkPricingService(session)
    bulk.save_rules(
        owner,
        product.id,
        [
            {
                "quantity_threshold": 2,
                "discount_percent": Decimal("10"),
                "special_price": 10_800,
                "pricing_mode": "PRICE",
            },
            {
                "quantity_threshold": 5,
                "discount_percent": Decimal("10"),
                "special_price": 0,
                "pricing_mode": "PERCENT",
            },
        ],
    )

    PurchaseService(session).record_purchase(
        owner,
        supplier_id=supplier.id,
        product_id=product.id,
        quantity=5,
        unit_cost=12_000,
        payment_status="PAID",
        due_date=None,
    )

    assert product.selling_price == 14_400
    fixed, percent = bulk.rules_for_product(product.id)
    assert fixed.pricing_mode == "PRICE"
    assert fixed.special_price == 12_960
    assert fixed.discount_percent == Decimal("10.00")
    assert percent.pricing_mode == "PERCENT"
    assert percent.discount_percent == Decimal("10")
    assert percent.special_price == 12_960
    assert bulk.unit_price(product, 2) == 12_960
    assert bulk.unit_price(product, 1) == 14_400


def test_tempo_purchase_can_be_marked_paid_and_no_longer_counts_as_debt(
    purchase_session,
):
    session, owner, _cashier, supplier, product = purchase_session
    service = PurchaseService(session)
    purchase = service.record_purchase(
        owner,
        supplier_id=supplier.id,
        product_id=product.id,
        quantity=3,
        unit_cost=10_000,
        payment_status="TEMPO",
        due_date=date(2026, 11, 10),
    )

    settled = service.mark_paid(owner, purchase.id)

    assert settled.payment_status == "PAID"
    assert settled.paid_amount == settled.subtotal == 30_000
    assert settled.due_date.date() == date(2026, 11, 10)


def test_tempo_requires_due_date_and_only_owner_can_record(
    purchase_session,
):
    _session, owner, cashier, supplier, product = purchase_session
    service = PurchaseService(_session)
    with pytest.raises(ValidationError, match="jatuh tempo wajib"):
        service.record_purchase(
            owner,
            supplier_id=supplier.id,
            product_id=product.id,
            quantity=1,
            unit_cost=10_000,
            payment_status="TEMPO",
            due_date=None,
        )
    with pytest.raises(AuthorizationError):
        service.record_purchase(
            cashier,
            supplier_id=supplier.id,
            product_id=product.id,
            quantity=1,
            unit_cost=10_000,
            payment_status="PAID",
            due_date=None,
        )


def test_purchase_window_lists_demo_purchase_and_debt_summary(
    purchase_session,
    qt_app,
):
    session, owner, _cashier, supplier, product = purchase_session
    PurchaseService(session).record_purchase(
        owner,
        supplier_id=supplier.id,
        product_id=product.id,
        quantity=2,
        unit_cost=10_000,
        payment_status="TEMPO",
        due_date=date(2026, 10, 30),
    )
    view = PurchaseView(owner, session)

    assert view.windowTitle() == "Belanja dan Supplier"
    assert view.tabs.count() == 4
    assert view.tabs.tabText(0) == "Belanja"
    assert view.tabs.tabText(1) == "Daftar Pembelian"
    assert view.tabs.tabText(2) == "Kelola Supplier"
    assert view.tabs.tabText(3) == "Bayar Hutang"
    label_texts = [label.text() for label in view.findChildren(QLabel)]
    assert "QTY *" in label_texts
    assert "Jumlah DP (Rp)" in label_texts
    assert "Jumlah diterima *" not in label_texts
    assert "Tabel Hutang" in label_texts
    assert view.supplier_input.count() == 1
    assert view.product_input.count() == 1
    assert view.quantity_input.minimum() == 1
    assert view.payment_status_input.count() == 3
    assert view.payment_status_input.itemData(2) == "DP"
    assert view.due_date_input.isEnabled() is False
    assert view.dp_amount_input.isEnabled() is False
    assert view.low_stock_checkbox.isEnabled() is False
    assert view.purchase_table.rowCount() == 1
    assert view.purchase_table.item(0, 2).text() == supplier.name
    assert view.purchase_table.item(0, 5).text() == "Tempo"
    assert "Rp 20.000,00" in view.debt_summary.text()
    assert view.debt_table.rowCount() == 1
    assert view.debt_table.item(0, 2).text() == supplier.name
    assert view.debt_table.item(0, 7).text() == "Rp 20.000,00"
    view.close()


def test_belanja_quick_creates_product_with_auto_defaults(
    purchase_session,
    qt_app,
    monkeypatch,
):
    session, owner, _cashier, supplier, _product = purchase_session
    monkeypatch.setattr(QMessageBox, "information", lambda *_a, **_k: None)
    view = PurchaseView(owner, session)

    assert view.new_product_button.text() == "Produk Baru"

    dialog = NewProductDialog(
        MasterDataService(session),
        purchase_price=5_000,
        parent=view,
    )
    assert dialog.purchase_price_input.value() == 5_000
    assert dialog.selling_price_input.value() == 6_500
    # Belum ada kategori/satuan di fixture -> pilihan otomatis (None).
    assert dialog.category_input.currentData() is None
    assert dialog.unit_input.currentData() is None

    dialog.name_input.setText("Kopi Sachet")
    assert view._save_new_product(dialog) is True

    created = session.scalar(
        select(Product).where(Product.name == "Kopi Sachet")
    )
    assert created is not None
    assert created.sku
    assert created.stock_qty == 0
    assert created.is_active is True
    assert created.supplier_id == supplier.id
    assert created.category.name == "Umum"
    assert created.unit.symbol == "pcs"
    # Produk baru langsung terpilih di form Belanja.
    assert view.product_input.currentData() == created.id
    view.close()


def test_belanja_quick_create_rejects_blank_name(
    purchase_session,
    qt_app,
    monkeypatch,
):
    session, owner, _cashier, _supplier, _product = purchase_session
    warnings = []
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda _parent, _title, message, *a, **k: warnings.append(message),
    )
    dialog = NewProductDialog(MasterDataService(session), parent=None)
    dialog._validate_and_accept()
    assert warnings == ["Isi nama produk."]
    assert dialog.result() != QDialog.DialogCode.Accepted
    dialog.close()


def test_record_dp_purchase_records_down_payment_and_keeps_debt(
    purchase_session,
):
    session, owner, _cashier, supplier, product = purchase_session
    service = PurchaseService(session)

    purchase = service.record_purchase(
        owner,
        supplier_id=supplier.id,
        product_id=product.id,
        quantity=5,
        unit_cost=10_000,
        payment_status="DP",
        due_date=date(2026, 12, 1),
        dp_amount=20_000,
    )

    assert purchase.payment_status == "DP"
    assert purchase.subtotal == 50_000
    assert purchase.paid_amount == 20_000
    assert purchase.due_date.date() == date(2026, 12, 1)
    assert product.stock_qty == 13

    payment = session.scalar(
        select(FinancialPayment).where(
            FinancialPayment.purchase_order_id == purchase.id
        )
    )
    assert payment is not None
    assert payment.amount == 20_000

    listed = service.list_purchases(owner)
    assert listed[0]["purchase"].payment_status == "DP"


def test_dp_validation_requires_amount_range_and_due_date(
    purchase_session,
):
    session, owner, _cashier, supplier, product = purchase_session
    service = PurchaseService(session)

    with pytest.raises(ValidationError, match="jatuh tempo wajib"):
        service.record_purchase(
            owner,
            supplier_id=supplier.id,
            product_id=product.id,
            quantity=1,
            unit_cost=10_000,
            payment_status="DP",
            due_date=None,
            dp_amount=5_000,
        )
    with pytest.raises(ValidationError, match="Jumlah DP"):
        service.record_purchase(
            owner,
            supplier_id=supplier.id,
            product_id=product.id,
            quantity=1,
            unit_cost=10_000,
            payment_status="DP",
            due_date=date(2026, 12, 1),
            dp_amount=0,
        )
    with pytest.raises(ValidationError, match="lebih kecil dari total"):
        service.record_purchase(
            owner,
            supplier_id=supplier.id,
            product_id=product.id,
            quantity=1,
            unit_cost=10_000,
            payment_status="DP",
            due_date=date(2026, 12, 1),
            dp_amount=10_000,
        )
    with pytest.raises(ValidationError, match="hanya diisi pada status DP"):
        service.record_purchase(
            owner,
            supplier_id=supplier.id,
            product_id=product.id,
            quantity=1,
            unit_cost=10_000,
            payment_status="TEMPO",
            due_date=date(2026, 12, 1),
            dp_amount=5_000,
        )


def test_partial_payments_keep_dp_status_until_fully_paid(
    purchase_session,
):
    session, owner, _cashier, supplier, product = purchase_session
    service = PurchaseService(session)
    purchase = service.record_purchase(
        owner,
        supplier_id=supplier.id,
        product_id=product.id,
        quantity=4,
        unit_cost=10_000,
        payment_status="DP",
        due_date=date(2026, 12, 5),
        dp_amount=10_000,
    )
    cash = session.scalar(select(Account).where(Account.code == "1000"))

    partial = service.record_payment(
        owner, purchase.id, 15_000, cash.id, "CASH"
    )
    assert partial.payment_status == "DP"
    assert partial.paid_amount == 25_000

    settled = service.record_payment(
        owner, purchase.id, 15_000, cash.id, "CASH"
    )
    assert settled.payment_status == "PAID"
    assert settled.paid_amount == settled.subtotal == 40_000


def test_purchase_form_status_block_has_three_rows_and_dp_state(
    purchase_session,
    qt_app,
):
    session, owner, _cashier, _supplier, _product = purchase_session
    view = PurchaseView(owner, session)

    assert view.payment_status_input.itemText(2) == "DP (uang muka)"
    assert view.dp_amount_input.isEnabled() is False
    assert view.due_date_input.isEnabled() is False

    view.payment_status_input.setCurrentIndex(1)
    assert view.due_date_input.isEnabled() is True
    assert view.dp_amount_input.isEnabled() is False

    view.payment_status_input.setCurrentIndex(2)
    assert view.due_date_input.isEnabled() is True
    assert view.dp_amount_input.isEnabled() is True

    view.payment_status_input.setCurrentIndex(0)
    assert view.due_date_input.isEnabled() is False
    assert view.dp_amount_input.isEnabled() is False
    view.close()


def test_daftar_pembelian_tab_lists_lunas_tempo_and_dp(
    purchase_session,
    qt_app,
):
    session, owner, _cashier, supplier, product = purchase_session
    service = PurchaseService(session)
    service.record_purchase(
        owner,
        supplier_id=supplier.id,
        product_id=product.id,
        quantity=1,
        unit_cost=10_000,
        payment_status="PAID",
        due_date=None,
    )
    service.record_purchase(
        owner,
        supplier_id=supplier.id,
        product_id=product.id,
        quantity=1,
        unit_cost=10_000,
        payment_status="TEMPO",
        due_date=date(2026, 11, 1),
    )
    service.record_purchase(
        owner,
        supplier_id=supplier.id,
        product_id=product.id,
        quantity=1,
        unit_cost=10_000,
        payment_status="DP",
        due_date=date(2026, 11, 2),
        dp_amount=4_000,
    )
    view = PurchaseView(owner, session)

    table = view.purchase_table
    assert table.rowCount() == 3
    statuses = {table.item(row, 5).text() for row in range(3)}
    assert statuses == {"Lunas", "Tempo", "DP (uang muka)"}
    sisa_values = {table.item(row, 7).text() for row in range(3)}
    assert "Rp 6.000,00" in sisa_values

    debt_rows = view.debt_table.rowCount()
    assert debt_rows == 2
    assert "Rp 16.000,00" in view.debt_summary.text()

    # Sel status DP menyimpan hint jumlah DP yang sudah dibayarkan.
    dp_row = next(
        row
        for row in range(table.rowCount())
        if table.item(row, 5).text() == "DP (uang muka)"
    )
    assert (
        "yang telah dibayarkan: Rp 4.000,00"
        in table.item(dp_row, 5).toolTip()
    )
    debt_dp_row = next(
        row
        for row in range(view.debt_table.rowCount())
        if view.debt_table.item(row, 5).text() == "DP (uang muka)"
    )
    assert (
        "yang telah dibayarkan: Rp 4.000,00"
        in view.debt_table.item(debt_dp_row, 5).toolTip()
    )

    # Input + tombol Cari menyaring baris daftar pembelian.
    view.purchase_search.input.setText("DP (uang muka)")
    view.purchase_search.button.click()
    assert not table.isRowHidden(dp_row)
    assert all(
        table.isRowHidden(row)
        for row in range(table.rowCount())
        if row != dp_row
    )
    view.purchase_search.input.setText("")
    view.purchase_search.button.click()
    assert not table.isRowHidden(0)
    view.close()


def test_low_stock_checkbox_filters_product_dropdown(purchase_session, qt_app):
    session, owner, _cashier, _supplier, product = purchase_session
    low = Product(
        sku="SKU-LOW-001",
        name="Gula Merah Kecil",
        purchase_price=2_000,
        selling_price=2_500,
        stock_qty=3,
        is_active=True,
    )
    empty = Product(
        sku="SKU-LOW-002",
        name="Kopi Batang",
        purchase_price=1_000,
        selling_price=1_500,
        stock_qty=0,
        is_active=True,
    )
    session.add_all([low, empty])
    session.flush()
    view = PurchaseView(owner, session)

    assert view.low_stock_checkbox.isEnabled() is True
    tooltip = view.low_stock_checkbox.toolTip()
    assert "Gula Merah Kecil (SKU-LOW-001): stok 3" in tooltip
    assert "Kopi Batang (SKU-LOW-002): stok 0" in tooltip
    assert view.product_input.count() == 3

    view.low_stock_checkbox.setChecked(True)
    filtered = {
        view.product_input.itemText(index)
        for index in range(view.product_input.count())
    }
    assert len(filtered) == 2
    assert any("Gula Merah Kecil" in text for text in filtered)
    assert any("Kopi Batang" in text for text in filtered)
    assert all("Beras" not in text for text in filtered)

    view.low_stock_checkbox.setChecked(False)
    assert view.product_input.count() == 3
    view.close()


def test_product_dropdown_shows_stock_hint_on_hover_and_focus(
    purchase_session,
    qt_app,
):
    session, owner, _cashier, _supplier, product = purchase_session
    low = Product(
        sku="SKU-LOW-010",
        name="Teh Poci Kecil",
        purchase_price=1_000,
        selling_price=1_500,
        stock_qty=2,
        is_active=True,
    )
    session.add(low)
    session.flush()
    view = PurchaseView(owner, session)

    for index in range(view.product_input.count()):
        hint = view.product_input.itemData(index, Qt.ToolTipRole)
        assert hint and "Jumlah stok" in hint
    assert f"Jumlah stok: {product.stock_qty} (stok aman)" in (
        view.product_input.toolTip()
    )

    view.low_stock_checkbox.setChecked(True)
    assert view.product_input.count() == 1
    item_hint = view.product_input.itemData(0, Qt.ToolTipRole)
    assert "Teh Poci Kecil" in item_hint
    assert "Jumlah stok: 2 (stok menipis)" in item_hint
    assert "Jumlah stok: 2 (stok menipis)" in view.product_input.toolTip()
    view.close()
