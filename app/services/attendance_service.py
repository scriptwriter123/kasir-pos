from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import AuthorizationError, ValidationError
from app.models import LoginHistory, User


class AttendanceService:
    """Laporan kehadiran karyawan. Sumber: riwayat login aplikasi.

    Karyawan dianggap Hadir bila login pada hari itu (waktu masuk =
    jam login pertama hari itu); tanpa login = Absen. Periode laporan
    dipilih per Hari, Minggu, Bulan, atau Tahun.
    """

    MAX_RANGE_DAYS = 366 * 5
    PERIODS = ("Hari", "Minggu", "Bulan", "Tahun")

    def __init__(self, session: Session):
        self.session = session

    @classmethod
    def range_for_period(cls, period: str, anchor: date) -> tuple[date, date]:
        """Hitung (mulai, akhir) periode dari tanggal acuan."""
        if period == "Hari":
            return anchor, anchor
        if period == "Minggu":
            start = anchor - timedelta(days=anchor.weekday())  # Senin
            return start, start + timedelta(days=6)
        if period == "Bulan":
            start = anchor.replace(day=1)
            if start.month == 12:
                end = start.replace(
                    year=start.year + 1, month=1, day=1
                ) - timedelta(days=1)
            else:
                end = start.replace(month=start.month + 1, day=1) - timedelta(
                    days=1
                )
            return start, end
        if period == "Tahun":
            return date(anchor.year, 1, 1), date(anchor.year, 12, 31)
        raise ValidationError("Periode tidak dikenal.")

    def list_attendance(
        self, actor: User, start: date, end: date
    ) -> list[dict]:
        self._require_owner(actor)
        if end < start:
            raise ValidationError("Tanggal akhir sebelum tanggal mulai.")
        if (end - start).days > self.MAX_RANGE_DAYS:
            raise ValidationError("Rentang laporan maksimal 5 tahun.")

        users = list(
            self.session.scalars(
                select(User)
                .where(User.deleted_at.is_(None))
                .order_by(User.full_name, User.username)
            )
        )
        lower = self._day_to_utc(start) - timedelta(days=1)
        upper = self._day_to_utc(end) + timedelta(days=1)
        records = self.session.scalars(
            select(LoginHistory).where(
                LoginHistory.login_at >= lower,
                LoginHistory.login_at <= upper,
            )
        )

        # Login pertama per (pengguna, tanggal lokal); SQLite mengembalikan
        # datetime naive yang disimpan sebagai UTC.
        first_login: dict[tuple[int, date], datetime] = {}
        for record in records:
            login_at = record.login_at
            if login_at.tzinfo is None:
                login_at = login_at.replace(tzinfo=timezone.utc)
            local_dt = login_at.astimezone()
            key = (record.user_id, local_dt.date())
            current = first_login.get(key)
            if current is None or local_dt < current:
                first_login[key] = local_dt

        rows: list[dict] = []
        day = end
        while day >= start:
            for user in users:
                login_dt = first_login.get((user.id, day))
                rows.append(
                    {
                        "user_id": user.id,
                        "nama": user.full_name,
                        "bagian": user.role.name if user.role else "",
                        "tanggal": day,
                        "waktu_masuk": (
                            login_dt.strftime("%H:%M") if login_dt else ""
                        ),
                        "status": "Hadir" if login_dt else "Absen",
                    }
                )
            day -= timedelta(days=1)
        return rows

    @staticmethod
    def _day_to_utc(day: date) -> datetime:
        return datetime.combine(day, time.min).astimezone(timezone.utc)

    @staticmethod
    def _require_owner(actor: User) -> None:
        if actor.role.name.upper() != "OWNER":
            raise AuthorizationError(
                "Hanya OWNER yang dapat melihat laporan absensi karyawan."
            )
