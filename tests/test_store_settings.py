import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.config import settings as app_settings
from app.core.database import Base
from app.core.exceptions import AuthorizationError, ValidationError
from app.models import Role, Store, User
from app.repositories.user_repository import UserRepository
from app.services.store_settings_service import StoreSettingsService
from app.services.user_management_service import UserManagementService
from app.ui.main_window import MainWindow
from app.ui.views.login_view import LoginView
from app.ui.views.store_settings_view import StoreSettingsView


@pytest.fixture
def settings_session():
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


def test_owner_can_save_store_profile_and_logo_is_copied(
    settings_session,
    tmp_path,
    monkeypatch,
):
    session, owner, _cashier = settings_session
    monkeypatch.setattr(app_settings, "pos_data_dir", None)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    logo_source = tmp_path / "shop-logo.png"
    image = QImage(24, 24, QImage.Format.Format_ARGB32)
    image.fill(0xFF336699)
    assert image.save(str(logo_source))

    store = StoreSettingsService(session).save(
        owner,
        name="  Toko Sejahtera  ",
        slogan="  Belanja hemat setiap hari  ",
        address="  Jl. Contoh No. 1 ",
        whatsapp="+62 812-3456-7890",
        logo_source=str(logo_source),
    )

    assert store.code == "MAIN"
    assert store.name == "Toko Sejahtera"
    assert store.slogan == "Belanja hemat setiap hari"
    assert store.address == "Jl. Contoh No. 1"
    assert store.whatsapp == "+62 812-3456-7890"
    assert store.logo_path is not None
    assert str(tmp_path) in store.logo_path
    assert os.path.isfile(store.logo_path)
    assert session.scalar(select(Store).where(Store.code == "MAIN")) is store


def test_store_settings_validate_inputs_and_require_owner(
    settings_session,
    tmp_path,
):
    session, owner, cashier = settings_session
    service = StoreSettingsService(session)

    with pytest.raises(AuthorizationError):
        service.save(
            cashier,
            name="Toko",
            address="",
            whatsapp="",
            logo_source=None,
        )
    with pytest.raises(ValidationError, match="Nama toko wajib"):
        service.save(
            owner,
            name=" ",
            address="",
            whatsapp="",
            logo_source=None,
        )
    with pytest.raises(ValidationError, match="7 sampai 20 digit"):
        service.save(
            owner,
            name="Toko",
            address="",
            whatsapp="1234",
            logo_source=None,
        )
    with pytest.raises(ValidationError, match="Slogan toko maksimal 200"):
        service.save(
            owner,
            name="Toko",
            slogan="x" * 201,
            address="",
            whatsapp="",
            logo_source=None,
        )


def test_cancel_discards_unsaved_store_settings_changes(
    settings_session,
    qt_app,
):
    session, owner, _cashier = settings_session
    service = StoreSettingsService(session)
    service.save(
        owner,
        name="Nama Tersimpan",
        address="Alamat",
        whatsapp="081234567890",
        logo_source=None,
    )

    view = StoreSettingsView(owner, service)
    view._begin_edit()
    view.name_input.setText("Nama Belum Disimpan")
    view._cancel_edit()

    assert view.name_input.text() == "Nama Tersimpan"
    assert view.name_input.isReadOnly()
    assert not view.edit_button.isHidden()
    assert view.save_button.isHidden()
    view.close()


def test_store_name_and_logo_update_main_and_login_window_branding(
    settings_session,
    tmp_path,
    monkeypatch,
    qt_app,
):
    session, owner, _cashier = settings_session
    monkeypatch.setattr(app_settings, "pos_data_dir", None)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    service = StoreSettingsService(session)
    user_management = UserManagementService(session, UserRepository(session))
    window = MainWindow(owner, user_management)
    login = LoginView(auth_service=None)
    window.store_branding_changed.connect(login.update_store_branding)
    changed = []
    window.store_branding_changed.connect(changed.append)

    logo_source = tmp_path / "new-logo.png"
    image = QImage(16, 16, QImage.Format.Format_ARGB32)
    image.fill(0xFF123456)
    assert image.save(str(logo_source))
    store = service.save(
        owner,
        name="Toko Baru",
        slogan="Melayani dengan sepenuh hati",
        address="Alamat",
        whatsapp="081234567890",
        logo_source=str(logo_source),
    )
    window._store_settings_saved(store)

    assert window.windowTitle() == "Toko Baru — Dashboard"
    assert window.dashboard.store_name_label.text() == "Toko Baru"
    assert window.dashboard.store_slogan_label.text() == "Melayani dengan sepenuh hati"
    assert window.dashboard.store_address_label.text() == "Alamat"
    assert window.dashboard.store_whatsapp_label.text() == "WhatsApp: 081234567890"
    assert window.dashboard.store_name_label.alignment() == Qt.AlignmentFlag.AlignCenter
    assert window.dashboard.store_slogan_label.alignment() == Qt.AlignmentFlag.AlignCenter
    assert window.dashboard.store_address_label.alignment() == Qt.AlignmentFlag.AlignCenter
    from app.ui.theme import PALETTE

    assert PALETTE["accent_soft"] in window.dashboard.store_name_label.styleSheet()
    assert PALETTE["accent_soft"] in window.dashboard.store_slogan_label.styleSheet()
    assert PALETTE["accent_soft"] in window.dashboard.store_address_label.styleSheet()
    assert not window.windowIcon().isNull()
    assert login.windowTitle() == "Toko Baru — Login"
    assert not login.windowIcon().isNull()
    assert login.width() >= 600
    assert login.store_name_label.text() == "Toko Baru"
    assert login.store_slogan_label.text() == "Melayani dengan sepenuh hati"
    assert login.store_address_label.text() == "Alamat"
    assert login.store_whatsapp_label.text() == "WhatsApp: 081234567890"
    assert login.store_name_label.alignment() == Qt.AlignmentFlag.AlignCenter
    assert login.store_slogan_label.alignment() == Qt.AlignmentFlag.AlignCenter
    assert not login.store_logo_label.pixmap().isNull()
    assert changed == [store]
    window.close()
    login.close()


def test_login_enter_moves_to_password_and_submits(qt_app):
    class FakeAuthService:
        def login(self, username, password):
            return (username, password)

    login = LoginView(auth_service=FakeAuthService())
    results = []
    login.login_success.connect(results.append)
    login.show()
    qt_app.processEvents()
    login.username.setText("cashier")
    login.password.setText("secret")

    QTest.keyClick(login.username, Qt.Key.Key_Return)
    assert qt_app.focusWidget() is login.password

    QTest.keyClick(login.password, Qt.Key.Key_Return)

    assert results == [("cashier", "secret")]
    login.close()


def test_payment_settings_section_shows_wizard_status_and_opens_wizard(
    settings_session, qt_app, monkeypatch
):
    from app.models import PaymentWizardState
    from app.services.payment_settings_service import PaymentSettingsService
    from app.ui.views import payment_wizard_view
    from PySide6.QtWidgets import QMessageBox

    session, owner, _cashier = settings_session
    view = StoreSettingsView(
        owner,
        StoreSettingsService(session),
        payment_service=PaymentSettingsService(session),
    )

    assert view.payment_cash.text() == "Tunai (Offline)"
    assert len(view._payment_setting_buttons) == 4
    assert (
        view._payment_status_labels["QRIS_DANA"].text() == "Status: Belum dimulai"
    )

    session.add(PaymentWizardState(method="QRIS_DANA", status="active", payload=""))
    session.flush()
    view._refresh_payment_status_labels()
    assert "Aktif" in view._payment_status_labels["QRIS_DANA"].text()
    assert "Belum dimulai" in view._payment_status_labels["BANK"].text()

    opened: list[str] = []

    class FakeDialog:
        def __init__(self, method, actor, service, parent):
            opened.append(method)

        def exec(self):
            return None

    monkeypatch.setattr(payment_wizard_view, "PaymentWizardDialog", FakeDialog)
    monkeypatch.setattr(
        QMessageBox, "information", staticmethod(lambda *args, **kwargs: None)
    )

    view._begin_edit()
    for button in view._payment_setting_buttons:
        button.click()

    assert opened == ["QRIS_DANA", "QRIS_MIDTRANS", "BANK"]
    view.close()
