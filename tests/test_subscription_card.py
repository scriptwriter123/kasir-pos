import os
from datetime import datetime, timedelta, timezone

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QLabel, QPushButton
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.core.database import Base
from app.models import Role, User
from app.services.subscription_info import (
    local_subscription_info,
    merge_status,
    remaining_from_expiry,
)
from app.ui.views.dashboard_view import DashboardView


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
    app = QApplication.instance() or QApplication([])
    yield app
    for widget in app.topLevelWidgets():
        widget.close()
        widget.deleteLater()
    app.processEvents()


@pytest.fixture
def no_billing_url(monkeypatch):
    """Uji tidak boleh menyentuh jaringan: worker langsung jalur lokal."""
    monkeypatch.setattr(settings, "billing_server_url", None)


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


class StubLicenseService:
    """Pengganti LicenseService: payload lisensi sudah ditentukan tes."""

    def __init__(self, payload, data_dir):
        self.payload = payload
        self.data_dir = data_dir

    def license_payload(self):
        return self.payload


def make_payload(*, issued_days_ago=10, expires_in_days=20):
    now = datetime.now(timezone.utc)
    expires_at = None
    if expires_in_days is not None:
        expires_at = (now + timedelta(days=expires_in_days)).isoformat()
    return {
        "schema_version": 1,
        "product": "POS Retail",
        "license_id": "AABBCC",
        "store_name": "Toko Uji",
        "installation_id": "11111111-1111-1111-1111-111111111111",
        "device_id": "b" * 64,
        "issued_at": (now - timedelta(days=issued_days_ago)).isoformat(),
        "expires_at": expires_at,
    }


def stub_service(tmp_path, **payload_kwargs):
    return StubLicenseService(make_payload(**payload_kwargs), tmp_path)


def grid_button_texts(dashboard: DashboardView) -> list[str]:
    """Teks tombol hanya pada kartu yang benar-benar ada di grid."""
    texts = []
    for index in range(dashboard.menu_grid.count()):
        item = dashboard.menu_grid.itemAt(index)
        widget = item.widget() if item is not None else None
        if widget is None:
            continue
        texts.extend(button.text() for button in widget.findChildren(QPushButton))
    return texts


def close_dashboard(dashboard: DashboardView, qt_app) -> None:
    dashboard.shutdown()
    dashboard.close()
    qt_app.processEvents()


def test_unlicensed_dashboard_keeps_activation_card(
    user_session, qt_app, no_billing_url
):
    owner = make_user(user_session, "owner-aktivasikartu", "OWNER")
    dashboard = DashboardView(owner)
    dashboard.resize(1100, 680)
    dashboard.show()
    qt_app.processEvents()

    assert dashboard.menu_grid.count() == 5
    texts = grid_button_texts(dashboard)
    assert "Buka Aktivasi" in texts
    assert "Detail Langganan" not in texts
    assert dashboard.subscription_desc_label is None
    assert dashboard._subscription_card is None
    close_dashboard(dashboard, qt_app)


def test_licensed_dashboard_hides_activation_card_and_shows_info(
    user_session, qt_app, no_billing_url, tmp_path
):
    owner = make_user(user_session, "owner-lisensia", "OWNER")
    dashboard = DashboardView(
        owner,
        licensed=True,
        license_service=stub_service(tmp_path),
    )
    dashboard.resize(1100, 680)
    dashboard.show()
    qt_app.processEvents()

    assert dashboard.menu_grid.count() == 5
    texts = grid_button_texts(dashboard)
    assert "Buka Aktivasi" not in texts
    assert "Detail Langganan" in texts
    assert all(
        "Aktifkan atau perpanjang langganan" not in label.text()
        for label in dashboard.findChildren(QLabel)
    )

    worker = dashboard._subscription_worker
    if worker is not None:
        assert worker.wait(5000)
    qt_app.processEvents()

    info = dashboard.subscription_info
    assert info is not None and info["source"] == "local"
    assert info["activated"] is True
    description = dashboard.subscription_desc_label.text()
    assert "Bulanan" in description
    assert "Sisa 20 hari" in description
    assert "berakhir" in description
    assert "Fitur berikutnya" in dashboard.subscription_roadmap_label.text()
    close_dashboard(dashboard, qt_app)


def test_set_licensed_swaps_card_back_and_forth(
    user_session, qt_app, no_billing_url, tmp_path
):
    owner = make_user(user_session, "owner-tukarkartu", "OWNER")
    dashboard = DashboardView(owner, license_service=stub_service(tmp_path))
    dashboard.resize(1100, 680)
    dashboard.show()
    qt_app.processEvents()
    assert "Buka Aktivasi" in grid_button_texts(dashboard)

    dashboard.set_licensed(True)
    qt_app.processEvents()
    assert dashboard.menu_grid.count() == 5
    assert dashboard._subscription_card is not None
    assert dashboard._activation_card is None
    texts = grid_button_texts(dashboard)
    assert "Buka Aktivasi" not in texts
    assert "Detail Langganan" in texts

    worker = dashboard._subscription_worker
    if worker is not None:
        worker.wait(5000)

    dashboard.set_licensed(False)
    qt_app.processEvents()
    assert dashboard.menu_grid.count() == 5
    assert dashboard._activation_card is not None
    assert dashboard._subscription_card is None
    assert dashboard.subscription_desc_label is None
    texts = grid_button_texts(dashboard)
    assert "Buka Aktivasi" in texts
    assert "Detail Langganan" not in texts
    close_dashboard(dashboard, qt_app)


def test_local_subscription_info_reports_remaining_time(tmp_path):
    info = local_subscription_info(stub_service(tmp_path))
    assert info["source"] == "local"
    assert info["activated"] is True
    assert info["plan"]["cycle"] == "monthly"
    assert info["plan"]["name"] == "Bulanan"
    assert info["plan"]["remaining_days"] == 20
    assert info["plan"]["remaining_text"] == "Sisa 20 hari"


def test_local_subscription_info_detects_expired_license(tmp_path):
    info = local_subscription_info(stub_service(tmp_path, expires_in_days=-2))
    assert info["activated"] is False
    assert info["plan"]["remaining_text"] == "Masa berlaku berakhir"
    assert info["plan"]["remaining_days"] == 0


def test_local_subscription_info_supports_lifetime_license(tmp_path):
    info = local_subscription_info(
        stub_service(tmp_path, issued_days_ago=0, expires_in_days=None)
    )
    assert info["plan"]["cycle"] == "lifetime"
    assert info["plan"]["name"] == "Selamanya"
    assert info["plan"]["remaining_text"] == "Berlaku selamanya"


def test_local_subscription_info_without_license_has_note(tmp_path):
    info = local_subscription_info(StubLicenseService(None, tmp_path))
    assert info["plan"] is None
    assert info["activated"] is False
    assert info["note"]


def test_remaining_from_expiry_formats_days_and_hours():
    soon = (datetime.now(timezone.utc) + timedelta(hours=3)).isoformat()
    assert remaining_from_expiry(soon)["text"].startswith("Sisa ")
    assert remaining_from_expiry(None)["text"] == "Berlaku selamanya"
    past = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    assert remaining_from_expiry(past)["expired"] is True


def test_merge_status_prefers_server_subscription(tmp_path):
    expires = (datetime.now(timezone.utc) + timedelta(days=300)).isoformat()
    status = {
        "server_time": "2026-10-21T00:00:00+00:00",
        "roadmap": [{"title": "Fitur A", "description": "Deskripsi", "eta": "Q1"}],
        "plans": [
            {
                "code": "monthly",
                "name": "Bulanan",
                "cycle": "monthly",
                "duration_days": 30,
                "price_idr": 99_000,
            }
        ],
        "subscription": {
            "activated": True,
            "plan": {
                "code": "yearly",
                "name": "Tahunan",
                "cycle": "yearly",
                "expires_at": expires,
                "remaining_days": 300,
                "remaining_text": "Sisa 300 hari",
            },
        },
    }
    info = merge_status(status, stub_service(tmp_path))
    assert info["source"] == "server"
    assert info["activated"] is True
    assert info["plan"]["name"] == "Tahunan"
    assert info["plan"]["remaining_text"] == "Sisa 300 hari"
    assert info["roadmap"][0]["title"] == "Fitur A"
    assert info["plans"][0]["price_idr"] == 99_000


def test_merge_status_falls_back_to_local_plan(tmp_path):
    status = {
        "roadmap": [{"title": "Fitur A"}],
        "plans": [{"code": "monthly", "name": "Bulanan", "price_idr": 99_000}],
        "subscription": None,
    }
    info = merge_status(status, stub_service(tmp_path))
    assert info["source"] == "server"
    assert info["activated"] is True
    assert info["plan"]["cycle"] == "monthly"
    assert info["plan"]["remaining_days"] == 20
    assert info["roadmap"][0]["title"] == "Fitur A"


def test_subscription_detail_dialog_shows_plan_prices_and_roadmap(
    user_session, qt_app, no_billing_url, tmp_path
):
    owner = make_user(user_session, "owner-detaildialog", "OWNER")
    dashboard = DashboardView(
        owner,
        licensed=True,
        license_service=stub_service(tmp_path),
    )
    dashboard.apply_subscription_info(
        {
            "source": "server",
            "activated": True,
            "plan": {
                "code": "monthly",
                "name": "Bulanan",
                "cycle": "monthly",
                "expires_at": (
                    datetime.now(timezone.utc) + timedelta(days=20)
                ).isoformat(),
                "remaining_days": 20,
                "remaining_text": "Sisa 20 hari",
            },
            "plans": [
                {
                    "code": "monthly",
                    "name": "Bulanan",
                    "cycle": "monthly",
                    "duration_days": 30,
                    "price_idr": 99_000,
                },
                {
                    "code": "yearly",
                    "name": "Tahunan",
                    "cycle": "yearly",
                    "duration_days": 365,
                    "price_idr": 990_000,
                },
            ],
            "roadmap": [
                {
                    "title": "Aplikasi <script>Kasir</script>",
                    "description": "Kasir di ponsel.",
                    "eta": "Fase berikutnya",
                }
            ],
            "note": "Data uji.",
        }
    )
    dialog = dashboard._build_subscription_dialog(dashboard.subscription_info)
    body = dialog.findChild(QLabel, "subscriptionDetailBody")
    assert body is not None
    text = body.text()
    assert "Langganan Aktif" in text
    assert "Sisa 20 hari" in text
    assert "Bulanan" in text and "Rp 99.000,00" in text
    assert "Tahunan" in text and "Rp 990.000,00" in text
    assert "Fitur Berikutnya" in text
    assert "&lt;script&gt;" in text
    assert "<script>" not in text
    assert "Data uji." in text
    dialog.close()
    close_dashboard(dashboard, qt_app)
