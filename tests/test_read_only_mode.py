import os
from datetime import date

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

from app.core.exceptions import LicenseExpiredError
from app.models import Sale
from app.services.financial_service import FinancialService
from app.services.purchase_service import PurchaseService
from app.services.sales_service import SalesService
from app.ui.views.cashier_view import CashierView
from app.ui.views.license_view import LicenseView
from tests.test_cashier_view import cashier_session  # noqa: F401
from tests.test_purchase import purchase_session  # noqa: F401


@pytest.fixture
def qt_app():
    app = QApplication.instance() or QApplication([])
    yield app
    for widget in app.topLevelWidgets():
        widget.close()
        widget.deleteLater()
    app.processEvents()


def test_locked_sales_service_rejects_checkout(cashier_session):
    session, _user, _product = cashier_session
    service = SalesService(session, transaction_locked=True)

    with pytest.raises(LicenseExpiredError) as exc_info:
        service.checkout(Sale(), [], [])

    assert "Transaksi baru terkunci" in str(exc_info.value)


def test_unlocked_sales_service_is_not_blocked(cashier_session):
    session, _user, _product = cashier_session
    service = SalesService(session)

    assert service.transaction_locked is False


def test_read_only_cashier_view_disables_payment(
    cashier_session,
    qt_app,
    monkeypatch,
):
    session, user, product = cashier_session
    view = CashierView(user, session, read_only=True)
    view.show()
    qt_app.processEvents()

    assert view.sales.transaction_locked is True
    assert not view.pay_button.isEnabled()
    assert not view.open_shift_button.isEnabled()

    view.current_shift = view.shift_service.open_shift(user, 100_000)
    view.cart[product.id] = {"product": product, "qty": 1}
    view._update_cart_view()

    warnings = []
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda *_args, **_kwargs: warnings.append(True),
    )
    view._checkout()
    qt_app.processEvents()

    assert warnings
    assert view.cart
    view.close()


def test_read_only_is_off_by_default(cashier_session, qt_app):
    session, user, product = cashier_session
    view = CashierView(user, session)

    assert view.read_only is False
    assert view.sales.transaction_locked is False
    assert view.open_shift_button.isEnabled()
    view.current_shift = view.shift_service.open_shift(user, 100_000)
    view.cart[product.id] = {"product": product, "qty": 1}
    view._update_cart_view()
    assert view.pay_button.isEnabled()
    view.close()


def test_license_view_read_only_button_emits_signal(qt_app, tmp_path):
    from PySide6.QtWidgets import QPushButton

    from app.services.license_service import LicenseService

    license_service = LicenseService(tmp_path)
    view = LicenseView(license_service, allow_read_only=True)
    signals = []
    view.read_only_requested.connect(lambda: signals.append(True))

    buttons = [
        b
        for b in view.findChildren(QPushButton)
        if b.text() == "Lanjutkan dalam Mode Baca-Saja"
    ]
    assert buttons, "tombol mode baca-saja harus ada"
    buttons[0].click()

    assert signals == [True]
    view.close()


def test_license_view_hides_read_only_button_by_default(qt_app, tmp_path):
    from PySide6.QtWidgets import QPushButton

    from app.services.license_service import LicenseService

    license_service = LicenseService(tmp_path)
    view = LicenseView(license_service)

    labels = [b.text() for b in view.findChildren(QPushButton)]
    assert "Lanjutkan dalam Mode Baca-Saja" not in labels
    view.close()


def test_locked_purchase_service_rejects_new_purchase(purchase_session):
    from datetime import date

    session, owner, _cashier, supplier, product = purchase_session
    service = PurchaseService(session, transaction_locked=True)

    with pytest.raises(LicenseExpiredError) as exc_info:
        service.record_purchase(
            owner,
            supplier_id=supplier.id,
            product_id=product.id,
            quantity=1,
            unit_cost=1_000,
            payment_status="PAID",
            due_date=None,
            payment_account_id=None,
        )

    assert "terkunci" in str(exc_info.value)


def test_locked_financial_service_rejects_initialize(purchase_session):
    session, owner, _cashier, _supplier, _product = purchase_session
    service = FinancialService(session, transaction_locked=True)

    with pytest.raises(LicenseExpiredError):
        service.initialize(owner, date.today(), {})


def test_locked_financial_service_rejects_expense(purchase_session):
    from datetime import datetime, timezone

    session, owner, _cashier, _supplier, _product = purchase_session
    service = FinancialService(session, transaction_locked=True)

    with pytest.raises(LicenseExpiredError):
        service.create_expense(
            owner,
            account_id=1,
            amount=1_000,
            incurred_at=datetime.now(timezone.utc),
            payee="x",
            description="x",
            due_date=None,
            initial_payment=0,
            payment_account_id=None,
            payment_method="CASH",
        )
