import os
from datetime import date

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QLabel, QInputDialog, QMessageBox
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models import (
    Account,
    AuditLog,
    BulkPriceRule,
    CashierDailyReport,
    Product,
    Role,
    Sale,
    SaleItem,
    Store,
    User,
)
from app.services.financial_service import FinancialService
from app.ui.views.cashier_view import (
    CashierDailyReportDialog,
    CashierView,
    PaymentDialog,
)
from app.ui.widgets import COPYRIGHT_CAPTION
from app.utils.formatters import rupiah


@pytest.fixture
def cashier_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as session:
            role = Role(name="CASHIER")
            owner_role = Role(name="OWNER")
            store = Store(code="MAIN", name="Test Store")
            session.add_all([role, owner_role, store])
            session.flush()
            user = User(
                username="cashier",
                full_name="Test Cashier",
                password_hash="not-used-in-this-test",
                role=role,
            )
            product = Product(
                sku="SKU-001",
                barcode="1234567890",
                name="Test Product",
                purchase_price=1_000,
                selling_price=2500,
                stock_qty=4,
            )
            owner = User(
                username="owner",
                full_name="Test Owner",
                password_hash="not-used-in-this-test",
                role=owner_role,
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
            session.add_all([user, owner, product, *accounts])
            session.flush()
            account_ids = {
                account.code: account.id
                for account in accounts
            }
            FinancialService(session).initialize(
                owner,
                date.today(),
                {
                    account_ids["1000"]: 100_000,
                    account_ids["1200"]: product.stock_qty * product.purchase_price,
                    account_ids["3000"]: (
                        100_000 + product.stock_qty * product.purchase_price
                    ),
                },
            )
            yield session, user, product
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


def test_cashier_can_search_and_scan_product_with_quantity_prompt(
    cashier_session,
    qt_app,
    monkeypatch,
):
    session, user, product = cashier_session
    view = CashierView(user, session)
    prompts = []

    def choose_quantity(parent, title, label, value, minimum, maximum):
        prompts.append((label, minimum, maximum))
        return 2, True

    monkeypatch.setattr(QInputDialog, "getInt", choose_quantity)
    view.search_input.setText(product.barcode)
    view._search_products()

    assert view.cart[product.id]["qty"] == 2
    assert prompts[0][0].startswith(product.name)

    view.search_input.setText("Test")
    view._search_products()
    assert view.product_table.rowCount() == 1
    view._on_product_selected(0, 0)
    assert view.cart[product.id]["qty"] == 4
    assert view.total_label.text() == rupiah(product.selling_price * 4)
    assert len(prompts) == 2
    view.close()


def test_enter_on_search_result_opens_quantity_prompt_and_adds_product(
    cashier_session,
    qt_app,
    monkeypatch,
):
    session, user, product = cashier_session
    view = CashierView(user, session)
    view.show()
    qt_app.processEvents()
    prompts = []

    def choose_quantity(parent, title, label, value, minimum, maximum):
        prompts.append((label, minimum, maximum))
        return 3, True

    monkeypatch.setattr(QInputDialog, "getInt", choose_quantity)
    view.search_input.setText("Test")
    view._search_products()
    view.product_table.setCurrentCell(0, 0)
    view.product_table.setFocus()
    QTest.keyClick(view.product_table, Qt.Key.Key_Return)
    qt_app.processEvents()

    assert prompts and prompts[0][0].startswith(product.name)
    assert view.cart[product.id]["qty"] == 3
    assert view.cart_table.item(0, 1).text() == product.name
    assert view.cart_table.item(0, 3).text() == "3"
    assert view.product_table.currentRow() == 0
    assert qt_app.focusWidget() is view.product_table
    view.close()


def test_cashier_search_results_show_bulk_special_price(
    cashier_session,
    qt_app,
):
    session, user, product = cashier_session
    session.add(
        BulkPriceRule(
            product_id=product.id,
            quantity_threshold=2,
            discount_percent=10,
            special_price=2_250,
            pricing_mode="PRICE",
        )
    )
    session.commit()
    view = CashierView(user, session)
    view.search_input.setText("Test")
    view._search_products()

    assert view.product_table.columnCount() == 7
    assert view.product_table.horizontalHeaderItem(5).text() == (
        "Harga Spesial Partai"
    )
    assert view.product_table.item(0, 4).text() == rupiah(2_500)
    assert view.product_table.item(0, 5).text() == (
        f"{rupiah(2_250)} (qty ≥ 2)"
    )
    assert view.product_table.item(0, 6).text() == str(product.id)
    view.close()


def test_cashier_focuses_scanner_when_window_opens(cashier_session, qt_app):
    session, user, _product = cashier_session
    view = CashierView(user, session)

    view.show()
    qt_app.processEvents()

    assert qt_app.focusWidget() is view.search_input
    view.close()


def test_cashier_can_save_daily_report_from_report_button(
    cashier_session,
    qt_app,
    monkeypatch,
):
    session, user, _product = cashier_session
    view = CashierView(user, session)

    def accept_report(dialog):
        dialog.notes_input.setPlainText("Toko ramai pada sore hari.")
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(CashierDailyReportDialog, "exec", accept_report)
    monkeypatch.setattr(QMessageBox, "information", lambda *_args: None)

    view.daily_report_button.click()

    report = session.query(CashierDailyReport).one()
    assert report.cashier_id == user.id
    assert report.report_date == date.today()
    assert report.notes == "Toko ramai pada sore hari."
    assert report.sales_count == 0
    assert report.sales_total == 0
    assert "#dc2626" in view.logout_button.styleSheet()
    view.close()


def test_cashier_can_open_shift_and_complete_daily_sale(cashier_session, qt_app):
    session, user, product = cashier_session
    view = CashierView(user, session)
    view.current_shift = view.shift_service.open_shift(user, 100_000)
    view._refresh_shift_status()
    view.cart[product.id] = {"product": product, "qty": 2}
    view._update_cart_view()

    sale = view._save_sale(
        total=product.selling_price * 2,
        method="CASH",
        amount=10_000,
    )

    assert sale.grand_total == 5_000
    assert session.get(Product, product.id).stock_qty == 2
    sale_item = session.scalar(select(SaleItem).where(SaleItem.sale_id == sale.id))
    assert sale_item is not None
    assert sale_item.unit_cost == 1_000
    assert view.sales.daily_sales()[0].id == sale.id
    receipt = view._build_receipt_data(sale, "CASH", 10_000, 5_000)
    assert receipt["store_name"] == "Test Store"
    assert receipt["invoice_no"] == sale.invoice_no
    assert receipt["items"] == [
        {
            "sku": product.sku,
            "name": product.name,
            "qty": 2,
            "unit_price": product.selling_price,
            "line_total": 5_000,
        }
    ]
    assert receipt["paid"] == 10_000
    assert receipt["change"] == 5_000
    audit = session.scalar(
        select(AuditLog).where(AuditLog.entity_id == sale.id)
    )
    assert audit is not None
    view.close()


def test_cashier_applies_bulk_price_to_cart_checkout_and_receipt(
    cashier_session,
    qt_app,
):
    session, user, product = cashier_session
    session.add(
        BulkPriceRule(
            product_id=product.id,
            quantity_threshold=2,
            discount_percent=10,
        )
    )
    session.commit()
    view = CashierView(user, session)
    view.current_shift = view.shift_service.open_shift(user, 100_000)
    view.cart[product.id] = {"product": product, "qty": 3}
    view._update_cart_view()

    assert view.total_label.text() == rupiah(6_750)
    assert view.cart_table.item(0, 2).text() == rupiah(2_250)
    sale = view._save_sale(total=6_750, method="CASH", amount=10_000)
    sale_item = session.scalar(select(SaleItem).where(SaleItem.sale_id == sale.id))
    assert sale.grand_total == 6_750
    assert sale_item is not None
    assert sale_item.unit_price == 2_250
    receipt = view._build_receipt_data(sale, "CASH", 10_000, 3_250)
    assert receipt["items"][0]["unit_price"] == 2_250
    assert receipt["items"][0]["line_total"] == 6_750
    view.close()


def test_bulk_price_applies_at_threshold(cashier_session, qt_app):
    session, user, product = cashier_session
    session.add(
        BulkPriceRule(
            product_id=product.id,
            quantity_threshold=2,
            discount_percent=10,
        )
    )
    session.commit()
    view = CashierView(user, session)
    view.cart[product.id] = {"product": product, "qty": 2}
    view._update_cart_view()

    assert view.total_label.text() == rupiah(4_500)
    assert view.cart_table.item(0, 2).text() == rupiah(2_250)
    view.close()


def test_bulk_price_does_not_apply_below_threshold(cashier_session, qt_app):
    session, user, product = cashier_session
    session.add(
        BulkPriceRule(
            product_id=product.id,
            quantity_threshold=2,
            discount_percent=10,
        )
    )
    session.commit()
    view = CashierView(user, session)
    view.cart[product.id] = {"product": product, "qty": 1}
    view._update_cart_view()

    assert view.total_label.text() == rupiah(2_500)
    assert view.cart_table.item(0, 2).text() == rupiah(2_500)
    view.close()


def test_cashier_uses_saved_manual_bulk_price(cashier_session, qt_app):
    session, user, product = cashier_session
    session.add(
        BulkPriceRule(
            product_id=product.id,
            quantity_threshold=2,
            discount_percent=12,
            special_price=2_200,
            pricing_mode="PRICE",
        )
    )
    session.commit()
    view = CashierView(user, session)
    view.current_shift = view.shift_service.open_shift(user, 100_000)
    view.cart[product.id] = {"product": product, "qty": 2}
    view._update_cart_view()

    assert view.total_label.text() == rupiah(4_400)
    sale = view._save_sale(total=4_400, method="CASH", amount=5_000)
    sale_item = session.scalar(select(SaleItem).where(SaleItem.sale_id == sale.id))
    assert sale_item is not None
    assert sale_item.unit_price == 2_200
    view.close()


def test_cashier_refocuses_scanner_after_checkout(
    cashier_session,
    qt_app,
    monkeypatch,
):
    session, user, product = cashier_session
    view = CashierView(user, session)
    view.show()
    qt_app.processEvents()
    view.current_shift = view.shift_service.open_shift(user, 100_000)
    view.cart[product.id] = {"product": product, "qty": 1}
    view._update_cart_view()

    monkeypatch.setattr(
        PaymentDialog,
        "exec",
        lambda _self: QDialog.DialogCode.Accepted,
    )
    monkeypatch.setattr(PaymentDialog, "payment", lambda _self: ("CASH", 2_500))
    monkeypatch.setattr(view, "_print_receipt_direct", lambda _receipt: None)
    monkeypatch.setattr(QMessageBox, "information", lambda *_args: None)
    view.pay_button.setFocus()

    view._checkout()
    qt_app.processEvents()

    assert qt_app.focusWidget() is view.search_input
    assert not view.cart
    view.close()


def test_cashier_logout_button_emits_logout_request(cashier_session, qt_app):
    session, user, _product = cashier_session
    view = CashierView(user, session)
    logout_requests = []
    view.logout_requested.connect(lambda: logout_requests.append(True))

    view.logout_button.click()

    assert logout_requests == [True]
    view.close()


def test_cart_quantity_is_editable_via_buttons_and_double_click(
    cashier_session,
    qt_app,
    monkeypatch,
):
    session, user, product = cashier_session
    second_product = Product(
        sku="SKU-002",
        name="Another Product",
        selling_price=1_000,
        stock_qty=5,
    )
    session.add(second_product)
    session.flush()

    view = CashierView(user, session)
    view.cart = {
        product.id: {"product": product, "qty": 1},
        second_product.id: {"product": second_product, "qty": 1},
    }
    view._update_cart_view()

    assert view.cart_table.item(0, 3).text() == "1"
    assert view.cart_table.item(1, 3).text() == "1"

    view.cart_table.setCurrentCell(0, 1)
    view._change_selected_qty(1)
    qt_app.processEvents()

    assert view.cart[product.id]["qty"] == 2
    assert view.cart_table.item(0, 3).text() == "2"
    assert view.cart_table.item(0, 4).text() == rupiah(5_000)
    assert view.total_label.text() == rupiah(6_000)

    def choose_quantity(parent, title, label, value, minimum, maximum):
        return 4, True

    monkeypatch.setattr(QInputDialog, "getInt", choose_quantity)
    view._edit_cart_qty(0)
    qt_app.processEvents()

    assert view.cart[product.id]["qty"] == 4
    assert view.cart_table.item(0, 3).text() == "4"
    view.close()


def test_pressing_enter_on_qty_column_opens_edit_dialog(
    cashier_session,
    qt_app,
    monkeypatch,
):
    session, user, product = cashier_session
    view = CashierView(user, session)
    view.cart = {product.id: {"product": product, "qty": 1}}
    view._update_cart_view()

    view.cart_table.setCurrentCell(0, 3)

    prompts = []

    def choose_quantity(parent, title, label, value, minimum, maximum):
        prompts.append((label, value, minimum, maximum))
        return 7, True

    monkeypatch.setattr(QInputDialog, "getInt", choose_quantity)
    QTest.keyClick(view.cart_table, Qt.Key.Key_Return)
    qt_app.processEvents()

    assert prompts and prompts[0][1] == 1
    assert view.cart[product.id]["qty"] == 7
    assert view.cart_table.item(0, 3).text() == "7"
    view.close()


@pytest.mark.parametrize(
    ("method_index", "method_name", "expect_demo"),
    [
        (1, "QRIS DANA", True),
        (2, "QRIS MIDTRANS", False),
        (3, "TF (m BANKING)", True),
    ],
)
def test_non_cash_payment_shows_demo_qr_and_cannot_be_confirmed(
    method_index: int,
    method_name: str,
    expect_demo: bool,
    qt_app,
):
    dialog = PaymentDialog(25_000)
    dialog.show()
    qt_app.processEvents()

    credit = dialog.findChild(QLabel, "copyrightCredit")
    assert credit is not None
    assert credit.text() == COPYRIGHT_CAPTION
    assert not dialog.qr_panel.isVisible()
    dialog.method_input.setCurrentIndex(method_index)
    qt_app.processEvents()

    assert dialog.qr_panel.isVisible()
    if expect_demo:
        assert dialog.qr_title.text() == f"QR {method_name} · DEMO"
        assert "Belum dapat dipindai" in dialog.qr_notice.text()
        assert not dialog.confirm_button.isEnabled()
    else:
        assert dialog.qr_title.text() == "QRIS"
        assert "Lanjutkan ke QRIS" in dialog.confirm_button.text()
        assert dialog.confirm_button.isEnabled()

    dialog.method_input.setCurrentIndex(0)
    assert not dialog.qr_panel.isVisible()
    assert dialog.confirm_button.isEnabled()
    dialog.close()


def test_cash_checkout_prints_thermal_directly(
    cashier_session,
    qt_app,
    monkeypatch,
):
    session, user, product = cashier_session
    view = CashierView(user, session)
    view.show()
    qt_app.processEvents()
    view.current_shift = view.shift_service.open_shift(user, 100_000)
    view.cart[product.id] = {"product": product, "qty": 1}
    view._update_cart_view()

    monkeypatch.setattr(
        PaymentDialog,
        "exec",
        lambda _self: QDialog.DialogCode.Accepted,
    )
    monkeypatch.setattr(PaymentDialog, "payment", lambda _self: ("CASH", 2_500))

    printed = []
    monkeypatch.setattr(
        view,
        "_print_receipt_direct",
        lambda _receipt: printed.append(_receipt),
    )
    offered = []
    monkeypatch.setattr(
        view,
        "_offer_receipt_output",
        lambda _receipt: offered.append(_receipt),
    )
    monkeypatch.setattr(QMessageBox, "information", lambda *_args: None)

    view._checkout()
    qt_app.processEvents()

    assert len(printed) == 1
    assert printed[0]["payment_method"] == "Tunai"
    assert printed[0]["paid"] == 2_500
    assert printed[0]["change"] == 0
    assert offered == []
    view.close()


def test_cash_enter_on_amount_triggers_confirm(qt_app, monkeypatch):
    dialog = PaymentDialog(10_000)
    dialog.show()
    qt_app.processEvents()

    accepted = []
    monkeypatch.setattr(
        PaymentDialog,
        "accept",
        lambda _self: accepted.append(True),
    )
    dialog.amount_input.setText("15000")
    QTest.keyClick(dialog.amount_input, Qt.Key.Key_Return)
    qt_app.processEvents()

    assert accepted == [True]
    dialog.close()


def test_payment_methods_require_setting_and_active_wizard(
    cashier_session, qt_app
):
    from app.models import PaymentSettings, PaymentWizardState

    session, user, _product = cashier_session
    view = CashierView(user, session)

    assert view._enabled_payment_methods() == list(PaymentDialog.ALL_METHODS)

    session.add(
        PaymentSettings(
            cash_enabled=True,
            qris_dana_enabled=True,
            qris_midtrans_enabled=False,
            transfer_enabled=True,
        )
    )
    session.flush()
    assert view._enabled_payment_methods() == ["CASH"]

    session.add(
        PaymentWizardState(method="QRIS_DANA", status="active", payload="")
    )
    session.add(
        PaymentWizardState(method="BANK", status="in_progress", payload="")
    )
    session.flush()
    assert view._enabled_payment_methods() == ["CASH", "QRIS_DANA"]

    session.query(PaymentWizardState).filter_by(method="QRIS_DANA").one().status = (
        "ready_to_test"
    )
    session.flush()
    assert view._enabled_payment_methods() == ["CASH"]
