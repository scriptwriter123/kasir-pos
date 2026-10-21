import os
from datetime import date, datetime, timedelta
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox, QWidget
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.core.security import hash_password
from app.hardware.printer import ReceiptPrinter
from app.models import (
    Account,
    Category,
    Product,
    Role,
    Sale,
    Shift,
    Store,
    Supplier,
    Unit,
    User,
)
from app.repositories.user_repository import UserRepository
from app.services.auth_service import AuthService
from app.services.financial_service import FinancialService
from app.services.license_service import LicenseService
from app.services.owner_setup_service import OwnerSetupService
from app.services.store_settings_service import StoreSettingsService
from app.services.user_management_service import UserManagementService
from app.ui.main_window import MainWindow
from app.ui.views.cashier_view import CashierView
from app.ui.views.dashboard_view import DashboardView
from app.ui.views.report_center_view import ReportCenterView
from app.ui.views.license_view import LicenseView
from app.ui.views.login_view import LoginView
from app.ui.views.master_data_view import MasterDataView
from app.ui.views.purchase_view import PurchaseView
from app.ui.views.user_management_view import UserManagementView
from app.utils.formatters import rupiah


@pytest.fixture
def qt_application():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def full_app_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as session:
            # Seed basic roles
            roles = {}
            for role_name in ("OWNER", "ADMIN", "SUPERVISOR", "CASHIER"):
                r = Role(name=role_name, description=f"Role {role_name}")
                session.add(r)
                roles[role_name] = r
            session.flush()

            # Seed Store
            store = Store(code="MAIN", name="Toko Super Mart", slogan="Murah Lengkap")
            session.add(store)

            # Seed Users
            owner = User(
                username="owner",
                full_name="Owner Toko",
                password_hash=hash_password("owner123"),
                role=roles["OWNER"],
            )
            cashier = User(
                username="kasir1",
                full_name="Kasir Utama",
                password_hash=hash_password("kasir123"),
                role=roles["CASHIER"],
            )
            session.add_all([owner, cashier])
            session.flush()

            # Seed Accounts
            accounts = [
                Account(code="1000", name="Kas", account_type="ASSET", is_active=True, is_system=True),
                Account(code="1010", name="Bank", account_type="ASSET", is_active=True, is_system=True),
                Account(code="1200", name="Persediaan", account_type="ASSET", is_active=True, is_system=True),
                Account(code="2000", name="Hutang Usaha", account_type="LIABILITY", is_active=True, is_system=True),
                Account(code="3000", name="Modal Pemilik", account_type="EQUITY", is_active=True, is_system=True),
                Account(code="3100", name="Saldo Awal", account_type="EQUITY", is_active=True, is_system=True),
                Account(code="4000", name="Penjualan", account_type="REVENUE", is_active=True, is_system=True),
                Account(code="5000", name="HPP", account_type="EXPENSE", is_active=True, is_system=True),
                Account(code="6000", name="Beban Listrik", account_type="EXPENSE", is_active=True, is_system=False),
            ]
            session.add_all(accounts)
            session.flush()

            # Initialize Financial Service
            fin_service = FinancialService(session)
            cash_acc = next(a for a in accounts if a.code == "1000")
            fin_service.initialize(
                owner,
                date.today(),
                {cash_acc.id: 5_000_000},
            )

            # Seed Category, Unit, Supplier
            cat = Category(name="Makanan")
            unit = Unit(name="Piece", symbol="pcs")
            sup = Supplier(code="SUP-01", name="Pemasok Maju", phone="08123456789")
            session.add_all([cat, unit, sup])
            session.flush()

            # Seed Products
            prod1 = Product(
                sku="SKU-ROTI-01",
                barcode="899123456001",
                name="Roti Tawar",
                category_id=cat.id,
                unit_id=unit.id,
                supplier_id=sup.id,
                purchase_price=8_000,
                selling_price=12_000,
                stock_qty=50,
                min_stock=5,
            )
            prod2 = Product(
                sku="SKU-SUSU-01",
                barcode="899123456002",
                name="Susu Cokelat",
                category_id=cat.id,
                unit_id=unit.id,
                supplier_id=sup.id,
                purchase_price=5_000,
                selling_price=8_000,
                stock_qty=30,
                min_stock=5,
            )
            session.add_all([prod1, prod2])
            session.commit()

            yield session
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_full_owner_navigation_and_all_views(qt_application: QApplication, full_app_session: Session):
    owner = full_app_session.query(User).filter_by(username="owner").one()
    user_mgmt = UserManagementService(full_app_session, UserRepository(full_app_session))
    
    window = MainWindow(owner, user_mgmt)
    window.show()
    assert isinstance(window.stack.currentWidget(), DashboardView)
    assert "Toko Super Mart" in window.windowTitle()

    # 1. Dashboard -> User Management View
    window.show_user_management()
    assert isinstance(window.stack.currentWidget(), UserManagementView)
    window.user_management_view.refresh_users()
    assert window.user_management_view.user_table.rowCount() >= 2

    # 2. Dashboard -> Sales Report View
    window.show_sales_report()
    assert isinstance(window.stack.currentWidget(), ReportCenterView)
    assert window.sales_report_view.report_type == "sales"
    window.sales_report_view.refresh_report()

    # 3. Financial report (Modal Awal di jendela Manajemen Toko)
    window.show_financial_report()
    assert isinstance(window.stack.currentWidget(), UserManagementView)
    assert window.user_management_view.tabs.currentWidget() is (
        window.financial_view
    )
    assert window.financial_view.service.is_initialized()

    # 4. Dashboard -> Master Data View
    window.show_master_data()
    assert isinstance(window.stack.currentWidget(), MasterDataView)
    window.master_data_view.refresh_products()
    assert window.master_data_view.product_table.rowCount() >= 2

    # 5. Dashboard -> Manajemen Toko (tab Pengaturan Toko)
    window.show_store_settings()
    assert isinstance(window.stack.currentWidget(), UserManagementView)
    assert window.store_settings_view.name_input.text() == "Toko Super Mart"
    assert window.user_management_view.tabs.currentWidget() is (
        window.store_settings_view.store_tab
    )

    # 6. Dashboard -> Suppliers (tab Kelola Supplier dalam jendela Belanja)
    window.show_suppliers()
    assert isinstance(window.stack.currentWidget(), PurchaseView)
    assert (
        window.stack.currentWidget().tabs.currentWidget()
        is window.supplier_view
    )
    assert window.supplier_view.supplier_table.rowCount() >= 1

    # 7. Dashboard -> Purchases (tab Belanja)
    window.show_purchases()
    assert isinstance(window.stack.currentWidget(), PurchaseView)
    assert window.purchase_view.tabs.currentIndex() == 0
    assert window.purchase_view.product_input.count() >= 2

    # Return to Dashboard
    window.show_dashboard()
    assert isinstance(window.stack.currentWidget(), DashboardView)
    window.close()


def test_modal_awal_checkbox_activates_financial_books(
    qt_application: QApplication, monkeypatch
):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        roles = {
            name: Role(name=name, description=name)
            for name in ("OWNER", "CASHIER")
        }
        session.add_all(roles.values())
        session.flush()
        owner = User(
            username="owner",
            full_name="Owner Toko",
            password_hash=hash_password("owner123"),
            role=roles["OWNER"],
        )
        session.add(owner)
        session.flush()
        session.add_all(
            [
                Account(
                    code="1000",
                    name="Kas",
                    account_type="ASSET",
                    is_active=True,
                    is_system=True,
                ),
                Account(
                    code="3000",
                    name="Modal Pemilik",
                    account_type="EQUITY",
                    is_active=True,
                    is_system=True,
                ),
                Account(
                    code="3100",
                    name="Saldo Awal",
                    account_type="EQUITY",
                    is_active=True,
                    is_system=True,
                ),
            ]
        )
        session.flush()

        user_mgmt = UserManagementService(session, UserRepository(session))
        view = UserManagementView(owner, user_mgmt)
        financial = view.financial_view

        # Sebelum diisi: checkbox nonaktif, pembukuan belum jalan.
        assert not financial.service.is_initialized()
        assert not financial.activate_checkbox.isEnabled()

        # Isi Modal -> checkbox "Aktifkan Laporan Keuangan" bisa dicentang.
        financial.modal_input.setValue(2_500_000)
        assert financial.activate_checkbox.isEnabled()

        messages: list[tuple[str, str]] = []
        monkeypatch.setattr(
            QMessageBox,
            "information",
            lambda *args, **kwargs: messages.append(("info", str(args[2])))
            or QMessageBox.StandardButton.Ok,
        )
        monkeypatch.setattr(
            QMessageBox,
            "warning",
            lambda *args, **kwargs: messages.append(("warn", str(args[2])))
            or QMessageBox.StandardButton.Ok,
        )

        financial.activate_checkbox.setChecked(True)

        assert not [text for kind, text in messages if kind == "warn"]
        assert [text for kind, text in messages if kind == "info"]
        assert financial.service.is_initialized()
        # Setelah aktif: checkbox tercentang lalu terkunci, input Modal mati.
        assert financial.activate_checkbox.isChecked()
        assert not financial.activate_checkbox.isEnabled()
        assert not financial.modal_input.isEnabled()
        # Tab pengeluaran ikut hidup: form & tabelnya menyala.
        assert view.expense_entry_view.save_button.isEnabled()
        assert view.expense_payment_view.expense_table.isEnabled()
        view.close()


def test_expense_payment_tab_pays_from_cash(
    qt_application: QApplication, full_app_session: Session
):
    owner = full_app_session.query(User).filter_by(username="owner").one()
    fin_service = FinancialService(full_app_session)
    expense_account = next(
        account
        for account in fin_service.accounts("EXPENSE")
        if account.code != "5000"
    )
    expense = fin_service.create_expense(
        owner,
        account_id=expense_account.id,
        amount=50_000,
        incurred_at=datetime.now().astimezone(),
        payee="Vendor Listrik",
        description="Tagihan listrik",
        due_date=date.today() + timedelta(days=7),
        initial_payment=0,
        payment_account_id=None,
        payment_method="CASH",
        payment_status="HUTANG",
    )

    user_mgmt = UserManagementService(
        full_app_session, UserRepository(full_app_session)
    )
    view = UserManagementView(owner, user_mgmt)
    view.show()
    qt_application.processEvents()

    payment = view.expense_payment_view
    # Tabel memuat hutang & tombol "Bayar Sekarang" langsung hidup.
    assert payment.expense_table.rowCount() == 1
    assert payment.pay_button.isEnabled()

    payment.pay_button.click()
    qt_application.processEvents()

    full_app_session.refresh(expense)
    # Lunas penuh otomatis dari akun Kas, status berubah Tunai.
    assert expense.paid_amount == expense.amount == 50_000
    assert expense.payment_status == "CASH"
    assert payment.expense_table.rowCount() == 0
    assert not payment.pay_button.isEnabled()
    view.close()


def test_expense_payment_dp_status_hint_and_search(
    qt_application: QApplication, full_app_session: Session
):
    owner = full_app_session.query(User).filter_by(username="owner").one()
    fin_service = FinancialService(full_app_session)
    expense_account = next(
        account
        for account in fin_service.accounts("EXPENSE")
        if account.code != "5000"
    )
    kas = next(
        account
        for account in fin_service.accounts("ASSET")
        if account.code == "1000"
    )
    fin_service.create_expense(
        owner,
        account_id=expense_account.id,
        amount=90_000,
        incurred_at=datetime.now().astimezone(),
        payee="Vendor Sembako",
        description="DP bahan baku",
        due_date=date.today() + timedelta(days=10),
        initial_payment=30_000,
        payment_account_id=kas.id,
        payment_method="CASH",
        payment_status="DP",
    )

    user_mgmt = UserManagementService(
        full_app_session, UserRepository(full_app_session)
    )
    view = UserManagementView(owner, user_mgmt)
    view.show()
    qt_application.processEvents()

    payment = view.expense_payment_view
    assert payment.expense_table.rowCount() == 1
    status_item = payment.expense_table.item(0, 7)
    assert status_item.text() == "DP"
    # Hint jumlah DP yang sudah dibayarkan tampil saat hover/fokus.
    assert (
        "yang telah dibayarkan: Rp 30.000,00" in status_item.toolTip()
    )

    payment.expense_search.input.setText("Vendor Sembako")
    payment.expense_search.button.click()
    assert not payment.expense_table.isRowHidden(0)
    payment.expense_search.input.setText("tidak-ada")
    payment.expense_search.button.click()
    assert payment.expense_table.isRowHidden(0)
    view.close()


def test_report_center_finance_tabs(
    qt_application: QApplication, full_app_session: Session
):
    class _SalesStub(QWidget):
        def __init__(self):
            super().__init__()
            self.refreshed = 0

        def refresh_report(self):
            self.refreshed += 1

    class _AttendanceStub(QWidget):
        def __init__(self):
            super().__init__()
            self.refreshed = 0

        def refresh(self):
            self.refreshed += 1

    owner = full_app_session.query(User).filter_by(username="owner").one()
    store = full_app_session.query(Store).filter_by(code="MAIN").one()
    fin_service = FinancialService(full_app_session)
    kas = next(
        account
        for account in fin_service.accounts("ASSET")
        if account.code == "1000"
    )
    expense_account = next(
        account
        for account in fin_service.accounts("EXPENSE")
        if account.code != "5000"
    )

    fin_service.create_expense(
        owner,
        account_id=expense_account.id,
        amount=60_000,
        incurred_at=datetime.now().astimezone(),
        payee="Operator Listrik",
        description="Token listrik",
        due_date=None,
        initial_payment=60_000,
        payment_account_id=kas.id,
        payment_method="CASH",
        payment_status="CASH",
    )
    fin_service.create_expense(
        owner,
        account_id=expense_account.id,
        amount=45_000,
        incurred_at=datetime.now().astimezone(),
        payee="Vendor Air",
        description="Tagihan air",
        due_date=date.today() + timedelta(days=5),
        initial_payment=0,
        payment_account_id=None,
        payment_method="CASH",
        payment_status="HUTANG",
    )

    shift = Shift(
        store_id=store.id,
        cashier_id=owner.id,
        opened_at=datetime.now(),
    )
    full_app_session.add(shift)
    full_app_session.flush()
    sale_moment = datetime(2026, 10, 9, 12)
    full_app_session.add_all(
        [
            Sale(
                invoice_no="INV-RPT-1",
                store_id=store.id,
                shift_id=shift.id,
                cashier_id=owner.id,
                subtotal=90_000,
                grand_total=90_000,
                status="PAID",
                created_at=sale_moment,
            ),
            Sale(
                invoice_no="INV-RPT-2",
                store_id=store.id,
                shift_id=shift.id,
                cashier_id=owner.id,
                subtotal=35_000,
                grand_total=35_000,
                status="PAID",
                created_at=sale_moment + timedelta(hours=1),
            ),
        ]
    )
    full_app_session.flush()

    # Stok tipis: turunkan stok Susu Cokelat di bawah batas 5.
    prod_susu = (
        full_app_session.query(Product).filter_by(sku="SKU-SUSU-01").one()
    )
    prod_susu.stock_qty = 4
    full_app_session.flush()

    center = ReportCenterView(
        sales_view=_SalesStub(),
        attendance_view=_AttendanceStub(),
        session=full_app_session,
        actor=owner,
    )
    center.resize(1200, 800)
    center.show()
    qt_application.processEvents()

    assert [
        center.tabs.tabText(i) for i in range(center.tabs.count())
    ] == [
        "Penjualan",
        "Pendapatan",
        "Pengeluaran",
        "Jumlah Hutang",
        "Stok Tipis",
        "Nilai Inventaris",
        "Absensi Karyawan",
        "Laporan Keuangan",
        "Progress",
    ]
    assert center.tabs.currentIndex() == 0

    # Pendapatan: opsi harian/bulanan/tahunan dengan rekap penjualan.
    center.show_tab("Pendapatan")
    qt_application.processEvents()
    income = center.income_view
    assert income.period_mode.currentData() == "day"
    assert income.table.rowCount() == 1
    assert income.table.item(0, 1).text() == "2"
    assert income.table.item(0, 2).text() == rupiah(125_000)
    income.period_mode.setCurrentIndex(1)
    assert income.table.rowCount() == 1
    assert income.table.item(0, 0).text() == "10-2026"
    income.period_mode.setCurrentIndex(2)
    assert income.table.item(0, 0).text() == "2026"
    income.period_mode.setCurrentIndex(0)

    # Pengeluaran: hanya pengeluaran kas berstatus Tunai.
    center.show_tab("Pengeluaran")
    qt_application.processEvents()
    cash_view = center.cash_expense_view
    assert cash_view.table.rowCount() == 1
    assert cash_view.table.item(0, 2).text() == "Operator Listrik"
    assert cash_view.table.item(0, 4).text() == rupiah(60_000)

    # Jumlah Hutang: pengeluaran berstatus Hutang/DP.
    center.show_tab("Jumlah Hutang")
    qt_application.processEvents()
    debt = center.debt_view
    assert debt.table.rowCount() == 1
    assert debt.table.item(0, 0).text() == "Pengeluaran"
    assert debt.table.item(0, 6).text() == rupiah(45_000)
    assert rupiah(45_000) in debt.summary_label.text()

    # Stok Tipis: barang dengan stok di bawah batas 5.
    center.show_tab("Stok Tipis")
    qt_application.processEvents()
    low_stock = center.low_stock_view
    assert low_stock.table.rowCount() == 1
    assert low_stock.table.item(0, 0).text() == "SKU-SUSU-01"
    assert low_stock.table.item(0, 3).text() == "5"
    assert low_stock.table.item(0, 4).text() == "RENDAH"
    assert low_stock.table.item(0, 5).text() == rupiah(4 * 5_000)

    # Nilai Inventaris: stok x harga beli semua barang.
    center.show_tab("Nilai Inventaris")
    qt_application.processEvents()
    inventory = center.inventory_value_view
    assert inventory.table.rowCount() == 2
    expected_value = (50 * 8_000) + (4 * 5_000)
    assert rupiah(expected_value) in inventory.summary_label.text()

    # Laporan Keuangan: empat pernyataan standar, buku sudah aktif.
    center.show_tab("Laporan Keuangan")
    qt_application.processEvents()
    statement = center.financial_statement_view
    assert statement.tabs.count() == 4
    assert not statement.status_label.text()
    assert statement.panes["profit_loss"].table.rowCount() > 0
    assert statement.panes["balance_sheet"].table.rowCount() > 0
    assert statement.panes["cash_flow"].table.rowCount() > 0
    assert statement.panes["trial_balance"].table.rowCount() > 0

    # Progress: placeholder isi menyusul.
    center.show_tab("Progress")
    qt_application.processEvents()
    assert center.progress_view is not None
    assert center.tabs.currentIndex() == center.TAB_PROGRESS
    center.close()


def test_full_cashier_flow_and_checkout(qt_application: QApplication, full_app_session: Session, tmp_path: Path):
    cashier = full_app_session.query(User).filter_by(username="kasir1").one()
    cashier_view = CashierView(cashier, full_app_session)
    cashier_view.show()

    # 1. Open Shift
    cashier_view.shift_service.open_shift(cashier, opening_cash=100_000)
    cashier_view._refresh_shift_status()
    assert cashier_view.current_shift is not None
    assert cashier_view.current_shift.status == "OPEN"

    # 2. Search Product
    cashier_view.search_input.setText("Roti")
    cashier_view._search_products()
    assert cashier_view.product_table.rowCount() >= 1

    # 3. Add Product to Cart directly
    prod = full_app_session.query(Product).filter_by(sku="SKU-ROTI-01").one()
    cashier_view._add_product(prod, 2)
    assert prod.id in cashier_view.cart
    assert cashier_view.cart[prod.id]["qty"] == 2
    assert cashier_view.cart_table.rowCount() == 1

    # 4. Modify Cart Qty
    cashier_view._set_cart_quantity(0, 3)
    assert cashier_view.cart[prod.id]["qty"] == 3

    # 5. Checkout with Cash
    sale = cashier_view._save_sale(36_000, "CASH", 50_000)
    assert sale.invoice_no.startswith("POS-")
    assert sale.grand_total == 36_000

    # 6. Verify Receipt Data
    receipt_data = cashier_view._build_receipt_data(sale, "CASH", 50_000, 14_000)
    assert receipt_data["total"] == 36_000
    assert receipt_data["paid"] == 50_000
    assert receipt_data["change"] == 14_000

    # 7. Generate PDF receipt
    printer = ReceiptPrinter()
    pdf_path = printer.save_pdf(receipt_data, tmp_path / "test_struk.pdf")
    assert pdf_path.exists()
    assert pdf_path.stat().st_size > 0

    # 8. Check stock reduction
    full_app_session.refresh(prod)
    assert prod.stock_qty == 47  # 50 - 3

    # 9. Save Cashier Daily Report
    report = cashier_view.daily_reports.save(cashier, date.today(), "Lancar aman")
    assert report.sales_count == 1
    assert report.sales_total == 36_000
    assert report.notes == "Lancar aman"

    cashier_view.close()


def test_license_view_and_service(qt_application: QApplication, tmp_path: Path):
    lic_service = LicenseService(tmp_path, device_id="test-device-id-12345")
    view = LicenseView(lic_service)
    view.show()
    assert view.installation_id_input.text() != ""
    view.close()


def test_main_window_trial_banner(qt_application: QApplication, full_app_session: Session):
    owner = full_app_session.query(User).filter_by(username="owner").one()
    user_mgmt = UserManagementService(
        full_app_session, UserRepository(full_app_session)
    )

    window = MainWindow(owner, user_mgmt, trial_message="Sisa 2 menit.")
    window.show()
    assert window.trial_banner is not None
    assert window.trial_banner.isVisible()
    window.dismiss_trial_banner()
    assert window.trial_banner is None
    window.close()

    window_no_trial = MainWindow(owner, user_mgmt, trial_message=None)
    window_no_trial.show()
    assert window_no_trial.trial_banner is None
    window_no_trial.close()


def test_license_view_back_button(qt_application: QApplication, tmp_path: Path):
    from PySide6.QtWidgets import QPushButton

    lic_service = LicenseService(tmp_path, device_id="test-device-id-12345")

    # Tanpa show_back: tidak ada tombol kembali.
    view = LicenseView(lic_service, show_back=False)
    assert not any(
        b.text() == "Kembali ke Aplikasi" for b in view.findChildren(QPushButton)
    )
    view.close()

    # Dengan show_back: tombol kembali muncul dan memancarkan sinyal.
    view_back = LicenseView(lic_service, show_back=True)
    buttons = [
        b for b in view_back.findChildren(QPushButton)
        if b.text() == "Kembali ke Aplikasi"
    ]
    assert len(buttons) == 1
    received = []
    view_back.back_requested.connect(lambda: received.append(True))
    buttons[0].click()
    assert received == [True]
    view_back.close()


def test_login_view_setup_and_branding(qt_application: QApplication, full_app_session: Session):
    repo = UserRepository(full_app_session)
    auth = AuthService(repo)
    setup = OwnerSetupService(full_app_session, repo)
    store = full_app_session.query(Store).first()

    login = LoginView(auth, store, setup_service=setup)
    login.show()
    assert login.store_name_label.text() == "Toko Super Mart"
    assert login.login_panel.isVisible()
    assert not login.setup_panel.isVisible()
    login.close()

