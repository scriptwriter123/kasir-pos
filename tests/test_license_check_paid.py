import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QPushButton

from app.core.config import settings
from app.services.license_service import LicenseService
from app.ui.views.license_view import LicenseView


@pytest.fixture
def qt_app():
    app = QApplication.instance() or QApplication([])
    yield app
    for widget in app.topLevelWidgets():
        widget.close()
        widget.deleteLater()
    app.processEvents()


@pytest.fixture
def online_view(qt_app, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "billing_server_url", "http://127.0.0.1:8001")
    license_service = LicenseService(tmp_path)
    view = LicenseView(license_service)
    view.show()
    qt_app.processEvents()
    yield view
    view.close()


def _check_button(view):
    buttons = [
        b
        for b in view.findChildren(QPushButton)
        if "Sudah Bayar" in b.text()
    ]
    assert buttons, "tombol 'Saya Sudah Bayar' harus ada"
    return buttons[0]


def test_check_paid_button_exists(online_view):
    assert _check_button(online_view).isVisible()


def test_check_paid_without_credentials_shows_hint(online_view, qt_app):
    _check_button(online_view).click()
    qt_app.processEvents()
    assert "Isi email" in online_view.online_status.text()


def test_check_paid_with_saved_token_starts_worker(
    online_view, qt_app, monkeypatch
):
    (online_view.license_service.data_dir / "billing-device-token.txt").write_text(
        "tokentest123\n", encoding="utf-8"
    )
    (online_view.license_service.data_dir / "billing-device-email.txt").write_text(
        "toko@example.com\n", encoding="utf-8"
    )
    calls = []
    monkeypatch.setattr(
        online_view, "_start_worker", lambda **kwargs: calls.append(kwargs)
    )
    _check_button(online_view).click()
    qt_app.processEvents()
    assert calls == [{"device_token": "tokentest123"}]
    assert online_view._pending_online_auth["email"] == "toko@example.com"
    assert "Memeriksa" in online_view.online_status.text()


def test_check_paid_with_login_form_starts_activation(
    online_view, qt_app, monkeypatch
):
    online_view.email_input.setText("toko@example.com")
    online_view.password_input.setText("rahasia123")
    calls = []
    monkeypatch.setattr(
        online_view,
        "_start_online_activation",
        lambda: calls.append(True),
    )
    _check_button(online_view).click()
    qt_app.processEvents()
    assert calls == [True]
