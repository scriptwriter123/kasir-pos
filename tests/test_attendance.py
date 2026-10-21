import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import date

import pytest
from PySide6.QtCore import QDate
from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QWidget
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.core.exceptions import AuthorizationError, ValidationError
from app.core.security import hash_password
from app.models import LoginHistory, Role, User
from app.repositories.user_repository import UserRepository
from app.services.attendance_service import AttendanceService
from app.services.auth_service import AuthService
from app.ui.views.attendance_view import AttendanceView
from app.ui.views.report_center_view import ReportCenterView


@pytest.fixture
def user_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = Session(engine)
    yield session
    session.close()
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


def test_range_for_period():
    anchor = date(2026, 10, 14)  # Rabu

    assert AttendanceService.range_for_period("Hari", anchor) == (
        anchor,
        anchor,
    )
    assert AttendanceService.range_for_period("Minggu", anchor) == (
        date(2026, 10, 12),
        date(2026, 10, 18),
    )
    assert AttendanceService.range_for_period("Bulan", anchor) == (
        date(2026, 10, 1),
        date(2026, 10, 31),
    )
    assert AttendanceService.range_for_period("Bulan", date(2026, 12, 15)) == (
        date(2026, 12, 1),
        date(2026, 12, 31),
    )
    assert AttendanceService.range_for_period("Tahun", anchor) == (
        date(2026, 1, 1),
        date(2026, 12, 31),
    )
    with pytest.raises(ValidationError):
        AttendanceService.range_for_period("Dekade", anchor)


def test_login_makes_attendance_report(user_session: Session):
    owner = make_user(user_session, "owner", "OWNER")
    staff = make_user(user_session, "kasir01", "CASHIER")
    staff.password_hash = hash_password("rahasia123")
    user_session.commit()

    # Login karyawan mencatat riwayat login (sumber absensi).
    AuthService(UserRepository(user_session)).login("kasir01", "rahasia123")
    user_session.commit()
    records = list(user_session.scalars(select(LoginHistory)))
    assert len(records) == 1
    assert records[0].user_id == staff.id

    service = AttendanceService(user_session)
    today = date.today()
    rows = service.list_attendance(owner, today, today)
    names = {row["nama"]: row for row in rows}
    assert owner.full_name in names and staff.full_name in names

    for row in rows:
        if row["user_id"] == staff.id:
            assert row["status"] == "Hadir"
            assert row["waktu_masuk"]
        else:
            assert row["status"] == "Absen"
            assert row["waktu_masuk"] == ""

    # Hari tanpa login sama sekali: semua Absen.
    empty_day = date(2020, 1, 7)
    rows = service.list_attendance(owner, empty_day, empty_day)
    assert rows and all(row["status"] == "Absen" for row in rows)


def test_attendance_validation(user_session: Session):
    owner = make_user(user_session, "owner", "OWNER")
    service = AttendanceService(user_session)

    with pytest.raises(ValidationError, match="sebelum tanggal mulai"):
        service.list_attendance(owner, date(2026, 10, 2), date(2026, 10, 1))
    with pytest.raises(ValidationError, match="5 tahun"):
        service.list_attendance(owner, date(2010, 1, 1), date(2026, 1, 1))
    with pytest.raises(AuthorizationError, match="Hanya OWNER"):
        service.list_attendance(
            make_user(user_session, "kasir", "CASHIER"),
            date.today(),
            date.today(),
        )


class _StubSales(QWidget):
    def __init__(self):
        super().__init__()
        self.back_button = QPushButton("back")
        self.heading_label = QLabel("Penjualan")
        self.refresh_count = 0

    def refresh_report(self):
        self.refresh_count += 1


class _StubAttendance(QWidget):
    def __init__(self):
        super().__init__()
        self.refresh_count = 0

    def refresh(self):
        self.refresh_count += 1


def test_report_center_tabs(qt_app):
    sales = _StubSales()
    attendance = _StubAttendance()
    center = ReportCenterView(
        sales_view=sales,
        attendance_view=attendance,
    )
    center.resize(1000, 700)
    center.show()
    qt_app.processEvents()

    assert [center.tabs.tabText(i) for i in range(center.tabs.count())] == [
        "Penjualan",
        "Absensi Karyawan",
    ]
    assert center.back_button is not None

    # Header anak view disembunyikan di dalam tab.
    assert not sales.back_button.isVisible()
    assert not sales.heading_label.isVisible()

    center.show_tab("Absensi Karyawan")
    qt_app.processEvents()
    assert center.tabs.currentIndex() == center.TAB_ATTENDANCE
    assert attendance.refresh_count == 1

    center.show_tab("Penjualan")
    qt_app.processEvents()
    assert sales.refresh_count >= 1

    center.close()


def test_attendance_view_refresh(user_session: Session, qt_app):
    owner = make_user(user_session, "owner", "OWNER")
    make_user(user_session, "kasir01", "CASHIER")
    view = AttendanceView(owner, user_session)
    view.resize(900, 600)
    view.show()
    qt_app.processEvents()

    view.refresh()
    # Dua pengguna aktif × 1 hari.
    assert view.table.rowCount() == 2
    assert view.table.item(0, 4).text() in {"Hadir", "Absen"}
    assert "Hadir:" in view.summary_label.text()

    view.period_input.setCurrentText("Minggu")
    qt_app.processEvents()
    assert view.table.rowCount() == 14

    # Ubah tanggal acuan tetap memuat ulang.
    view.date_input.setDate(QDate(2026, 10, 14))
    qt_app.processEvents()
    assert view.table.rowCount() == 14
    assert "12-10-2026" in view.summary_label.text()
    view.close()
