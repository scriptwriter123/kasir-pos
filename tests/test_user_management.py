import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QLabel, QLineEdit, QMessageBox
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.core.exceptions import AuthorizationError, ValidationError
from app.core.security import verify_password
from main import Application
from app.models import Role, User
from app.repositories.user_repository import UserRepository
from app.services.user_management_service import UserManagementService
from app.ui.main_window import MainWindow
from app.ui.views.cashier_view import CashierView
from app.ui.views.dashboard_view import DashboardView
from app.ui.views.report_center_view import ReportCenterView
from app.ui.views.login_view import LoginView
from app.ui.views.master_data_view import MasterDataView
from app.ui.views.purchase_view import PurchaseView
from app.ui.widgets import COPYRIGHT_CAPTION
from app.ui.views.user_management_view import UserManagementView


@pytest.fixture
def user_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as session:
            yield session
    finally:
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


def make_service(session: Session) -> UserManagementService:
    return UserManagementService(session, UserRepository(session))


def test_owner_can_create_staff_account_with_hashed_password(
    user_session: Session,
):
    owner = make_user(user_session, "owner", "OWNER")
    role = Role(name="CASHIER")
    user_session.add(role)
    user_session.flush()
    service = make_service(user_session)

    created = service.create_user(
        owner,
        username="  cashier01  ",
        full_name="  Cashier One  ",
        password="secure-pass-1",
        role_name="cashier",
    )

    assert created.username == "cashier01"
    assert created.full_name == "Cashier One"
    assert created.role.name == "CASHIER"
    assert verify_password("secure-pass-1", created.password_hash)
    assert created.password_hash != "secure-pass-1"
    assert created in service.list_users(owner)


def test_owner_can_create_user_with_free_text_bagian(user_session: Session):
    owner = make_user(user_session, "owner", "OWNER")
    service = make_service(user_session)

    created = service.create_user(
        owner,
        username="teknisi01",
        full_name="Teknisi Satu",
        password="secure-pass-1",
        role_name="Teknisi",
    )
    assert created.role.name == "Teknisi"

    # Ejaan berbeda kapital memakai bagian/tugas yang sama.
    same_role = service.create_user(
        owner,
        username="teknisi02",
        full_name="Teknisi Dua",
        password="secure-pass-1",
        role_name="teknisi",
    )
    assert same_role.role.id == created.role.id

    with pytest.raises(ValidationError, match="Jabatan wajib diisi"):
        service.create_user(
            owner,
            username="tanpa-bagian",
            full_name="Tanpa Bagian",
            password="secure-pass-1",
            role_name="   ",
        )
    with pytest.raises(ValidationError, match="Role yang dapat dibuat"):
        service.create_user(
            owner,
            username="pemalsu-owner",
            full_name="Pemalsu Owner",
            password="secure-pass-1",
            role_name="OWNER",
        )


def test_user_management_view_shows_free_text_bagian_input(
    user_session: Session,
    qt_app,
):
    owner = make_user(user_session, "owner", "OWNER")
    view = UserManagementView(owner, make_service(user_session))

    assert isinstance(view.role_input, QLineEdit)
    labels = [
        label.text()
        for label in view.findChildren(QLabel)
        if label.text() == "Jabatan"
    ]
    assert labels, "Label Jabatan harus tampil pada form"
    wa_labels = [
        label.text()
        for label in view.findChildren(QLabel)
        if label.text() == "No. WA"
    ]
    assert wa_labels, "Label No. WA harus tampil pada form"
    assert isinstance(view.wa_input, QLineEdit)
    assert view.user_table.horizontalHeaderItem(2).text() == "Jabatan"
    assert view.user_table.horizontalHeaderItem(3).text() == "No. WA"
    view.close()


def test_store_settings_controller_hidden_and_click_through(
    user_session: Session,
    qt_app,
):
    owner = make_user(user_session, "owner-overlay", "OWNER")
    view = UserManagementView(owner, make_service(user_session))

    assert view.store_settings.isHidden()
    assert view.store_settings.testAttribute(Qt.WA_TransparentForMouseEvents)
    view.close()


def test_owner_can_update_user(user_session: Session):
    owner = make_user(user_session, "owner", "OWNER")
    staff = make_user(user_session, "kasir01", "CASHIER")
    service = make_service(user_session)

    updated = service.update_user(
        owner,
        staff.id,
        username="kasir02",
        full_name="Kasir Dua",
        role_name="Kasir Sore",
    )
    assert updated.username == "kasir02"
    assert updated.full_name == "Kasir Dua"
    assert updated.role.name == "Kasir Sore"

    # Akun OWNER: bagian/tugas tidak boleh berubah walau teks diganti.
    updated_owner = service.update_user(
        owner,
        owner.id,
        username="owner-baru",
        full_name="Owner Baru",
        role_name="Manajer",
    )
    assert updated_owner.username == "owner-baru"
    assert updated_owner.role.name == "OWNER"

    with pytest.raises(ValidationError, match="Username sudah digunakan"):
        service.update_user(
            owner,
            staff.id,
            username="owner-baru",
            full_name="Kasir Dua",
            role_name="Kasir Sore",
        )
    with pytest.raises(ValidationError, match="Jabatan wajib diisi"):
        service.update_user(
            owner,
            staff.id,
            username="kasir02",
            full_name="Kasir Dua",
            role_name="   ",
        )


def test_user_management_view_inline_edit(
    user_session: Session,
    qt_app,
    monkeypatch,
):
    monkeypatch.setattr(
        QMessageBox,
        "information",
        lambda *args, **kwargs: QMessageBox.StandardButton.Ok,
    )
    owner = make_user(user_session, "owner", "OWNER")
    staff = make_user(user_session, "kasir01", "CASHIER")
    service = make_service(user_session)
    view = UserManagementView(owner, service)
    view.resize(1100, 700)
    view.show()
    qt_app.processEvents()

    staff_row = view.user_ids.index(staff.id)
    view.user_table.selectRow(staff_row)
    view._toggle_edit_user()
    assert view._editing_row == staff_row
    assert view.edit_button.text() == "Simpan Edit"
    assert view.cancel_edit_button.isVisible()
    assert not view.delete_button.isEnabled()
    assert view.user_table.item(staff_row, 0).flags() & Qt.ItemFlag.ItemIsEditable

    view.user_table.item(staff_row, 0).setText("Nama Baru")
    view.user_table.item(staff_row, 2).setText("Teknisi")
    view.user_table.item(staff_row, 3).setText("0812 3456 7890")
    view._toggle_edit_user()

    assert view._editing_row is None
    assert view.edit_button.text() == "Edit Pengguna Terpilih"
    assert view.delete_button.isEnabled()
    user_session.refresh(staff)
    assert staff.full_name == "Nama Baru"
    assert staff.role.name == "Teknisi"
    assert staff.whatsapp == "0812 3456 7890"

    view.close()


def test_user_whatsapp_validation_and_persistence(user_session: Session):
    owner = make_user(user_session, "owner", "OWNER")
    service = make_service(user_session)

    created = service.create_user(
        owner,
        username="wa01",
        full_name="WA Satu",
        password="secure-pass-1",
        role_name="Kasir",
        whatsapp="+62 812-3456-7890",
    )
    assert created.whatsapp == "+62 812-3456-7890"

    no_wa_empty = service.create_user(
        owner,
        username="wa02",
        full_name="WA Dua",
        password="secure-pass-1",
        role_name="Kasir",
    )
    assert no_wa_empty.whatsapp is None

    with pytest.raises(ValidationError, match="No. WA hanya boleh"):
        service.create_user(
            owner,
            username="wa03",
            full_name="WA Tiga",
            password="secure-pass-1",
            role_name="Kasir",
            whatsapp="bukan-nomor",
        )
    with pytest.raises(ValidationError, match="7 sampai 20 digit"):
        service.create_user(
            owner,
            username="wa04",
            full_name="WA Empat",
            password="secure-pass-1",
            role_name="Kasir",
            whatsapp="123",
        )

    service.update_user(
        owner,
        created.id,
        username="wa01",
        full_name="WA Satu",
        role_name="Kasir",
        whatsapp="0812 9999 8888",
    )
    assert created.whatsapp == "0812 9999 8888"

    # Tanpa parameter whatsapp: nomor lama tidak berubah.
    service.update_user(
        owner,
        created.id,
        username="wa01",
        full_name="WA Satu Baru",
        role_name="Kasir",
    )
    assert created.whatsapp == "0812 9999 8888"
    assert created.full_name == "WA Satu Baru"


def test_non_owner_cannot_list_or_create_users(user_session: Session):
    cashier = make_user(user_session, "cashier", "CASHIER")
    service = make_service(user_session)

    with pytest.raises(AuthorizationError):
        service.list_users(cashier)
    with pytest.raises(AuthorizationError):
        service.create_user(
            cashier,
            username="another",
            full_name="Another User",
            password="secure-pass-1",
            role_name="CASHIER",
        )


def test_owner_can_soft_delete_staff_but_not_owner(user_session: Session):
    owner = make_user(user_session, "owner", "OWNER")
    cashier = make_user(user_session, "cashier", "CASHIER")
    service = make_service(user_session)

    with pytest.raises(ValidationError, match="Akun OWNER"):
        service.delete_user(owner, owner.id)
    service.delete_user(owner, cashier.id)

    assert cashier.deleted_at is not None
    assert cashier.is_active is False
    assert service.list_users(owner) == [owner]


@pytest.mark.parametrize(
    ("username", "full_name", "password", "role_name", "message"),
    [
        ("", "Name", "secure-pass-1", "CASHIER", "Username wajib"),
        ("new-user", "", "secure-pass-1", "CASHIER", "Nama lengkap wajib"),
        ("new-user", "Name", "short", "CASHIER", "minimal 8 karakter"),
        ("new-user", "Name", "secure-pass-1", "OWNER", "Role yang dapat dibuat"),
    ],
)
def test_invalid_user_data_is_rejected(
    user_session: Session,
    username: str,
    full_name: str,
    password: str,
    role_name: str,
    message: str,
):
    owner = make_user(user_session, "owner", "OWNER")

    with pytest.raises(ValidationError, match=message):
        make_service(user_session).create_user(
            owner,
            username=username,
            full_name=full_name,
            password=password,
            role_name=role_name,
        )


@pytest.mark.parametrize("role_name", ["ADMIN", "SUPERVISOR", "CASHIER"])
def test_owner_dashboard_and_staff_sales_routing(
    user_session: Session,
    qt_app: QApplication,
    role_name: str,
):
    owner = make_user(user_session, "owner", "OWNER")
    service = make_service(user_session)
    owner_window = MainWindow(owner, service)
    owner_application = Application.__new__(Application)
    owner_application.session = user_session
    owner_application.login = LoginView(auth_service=None)
    owner_application.login.show()
    owner_application.window = owner_window
    owner_window.logout_requested.connect(owner_application.on_logout)

    assert isinstance(owner_window.stack.currentWidget(), DashboardView)
    credit = owner_window.statusBar().findChild(
        QLabel,
        "copyrightCredit",
    )
    assert credit is not None
    assert credit.text() == COPYRIGHT_CAPTION
    owner_window.dashboard.manage_users_requested.emit()
    assert isinstance(owner_window.stack.currentWidget(), UserManagementView)
    owner_window.dashboard.sales_report_requested.emit()
    assert isinstance(owner_window.stack.currentWidget(), ReportCenterView)
    owner_window.stack.currentWidget().back_button.click()
    assert owner_window.stack.currentWidget() is owner_window.dashboard
    owner_window.dashboard.suppliers_requested.emit()
    assert isinstance(owner_window.stack.currentWidget(), PurchaseView)
    assert owner_window.windowTitle() == "POS Retail — Belanja dan Supplier"
    assert owner_window.stack.currentWidget().supplier_input is not None
    assert owner_window.stack.currentWidget().product_input is not None
    owner_window.purchase_view.tabs.setCurrentWidget(
        owner_window.supplier_view
    )
    assert (
        owner_window.purchase_view.tabs.currentWidget()
        is owner_window.supplier_view
    )
    assert owner_window.windowTitle() == "POS Retail — Belanja dan Supplier"
    owner_window.purchase_view.supplier_view.purchases_requested.emit()
    assert isinstance(owner_window.stack.currentWidget(), PurchaseView)
    assert owner_window.purchase_view.tabs.currentIndex() == 0
    owner_window.stack.currentWidget().back_button.click()
    assert owner_window.stack.currentWidget() is owner_window.dashboard
    owner_window.dashboard.financial_report_requested.emit()
    assert isinstance(owner_window.stack.currentWidget(), UserManagementView)
    assert owner_window.windowTitle() == "POS Retail — Manajemen Toko"
    assert owner_window.user_management_view.tabs.currentWidget() is (
        owner_window.financial_view
    )
    owner_window.stack.currentWidget().back_button.click()
    assert owner_window.stack.currentWidget() is owner_window.dashboard
    owner_window.dashboard.master_data_requested.emit()
    assert isinstance(owner_window.stack.currentWidget(), MasterDataView)
    owner_window.stack.currentWidget().back_requested.emit()
    assert owner_window.stack.currentWidget() is owner_window.dashboard
    owner_window.dashboard.store_settings_requested.emit()
    assert isinstance(owner_window.stack.currentWidget(), UserManagementView)
    assert owner_window.windowTitle() == "POS Retail — Manajemen Toko"
    assert owner_window.user_management_view.tabs.currentWidget() is (
        owner_window.store_settings_view.store_tab
    )
    owner_window.stack.currentWidget().back_button.click()
    assert owner_window.stack.currentWidget() is owner_window.dashboard
    owner_window.dashboard.logout_button.click()
    assert owner_application.window is None
    assert owner_application.login.isVisible()
    assert owner_application.login.username.text() == ""
    assert owner_application.login.password.text() == ""
    owner_window.close()
    owner_application.login.close()

    staff_user = make_user(user_session, role_name.lower(), role_name)
    staff_window = MainWindow(staff_user, service)
    assert isinstance(staff_window.stack.currentWidget(), CashierView)
    application = Application.__new__(Application)
    application.session = user_session
    application.login = LoginView(auth_service=None)
    login_credit = application.login.findChild(QLabel, "copyrightCredit")
    assert login_credit is not None
    assert login_credit.text() == COPYRIGHT_CAPTION
    application.login.show()
    application.window = staff_window
    staff_window.logout_requested.connect(application.on_logout)
    staff_window.stack.currentWidget().logout_button.click()
    assert application.window is None
    assert application.login.isVisible()
    assert application.login.username.text() == ""
    assert application.login.password.text() == ""
    application.login.close()


def test_login_view_reset_clears_credentials_and_focuses_username(
    qt_app: QApplication,
):
    login = LoginView(auth_service=None)
    login.username.setText("staff")
    login.password.setText("password")

    login.reset()

    assert login.username.text() == ""
    assert login.password.text() == ""
    login.close()


def test_closing_main_window_returns_to_login(user_session, qt_app):
    owner = make_user(user_session, "owner-close", "OWNER")
    service = make_service(user_session)
    application = Application.__new__(Application)
    application.session = user_session
    application.login = LoginView(auth_service=None)
    application.window = MainWindow(owner, service)
    application.window.logout_requested.connect(application.on_logout)
    application.login.show()
    application.window.show()
    application.login.hide()

    application.window.close()
    qt_app.processEvents()

    assert application.window is None
    assert application.login.isVisible()
    assert application.login.username.text() == ""
    assert qt_app.quitOnLastWindowClosed()
    application.login.close()


def test_owner_dashboard_fits_all_menu_cards_without_dashboard_heading(
    user_session: Session,
    qt_app: QApplication,
):
    owner = make_user(user_session, "owner-dashboard-layout", "OWNER")
    dashboard = DashboardView(owner)
    dashboard.resize(1100, 680)
    dashboard.show()
    qt_app.processEvents()

    assert dashboard.menu_grid.count() == 5
    assert dashboard.menu_grid.columnCount() == 3
    assert all(
        dashboard.menu_grid.itemAt(index).widget().minimumHeight() == 125
        for index in range(dashboard.menu_grid.count())
    )
    assert all(
        label.text() != "Dashboard"
        for label in dashboard.findChildren(QLabel)
    )
    card_bottom = max(
        dashboard.menu_grid.itemAt(index).geometry().bottom()
        for index in range(dashboard.menu_grid.count())
    )
    assert card_bottom <= dashboard.menu_grid.geometry().bottom()
    dashboard.close()
