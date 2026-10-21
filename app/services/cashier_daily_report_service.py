from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import CashierDailyReport, Sale, User


class CashierDailyReportService:
    MAX_NOTE_LENGTH = 4000

    def __init__(self, session: Session):
        self.session = session

    def get_for_cashier(
        self,
        cashier_id: int,
        report_date: date,
    ) -> CashierDailyReport | None:
        return self.session.scalar(
            select(CashierDailyReport).where(
                CashierDailyReport.cashier_id == cashier_id,
                CashierDailyReport.report_date == report_date,
            )
        )

    def save(
        self,
        cashier: User,
        report_date: date,
        notes: str,
    ) -> CashierDailyReport:
        notes = notes.strip()
        if len(notes) > self.MAX_NOTE_LENGTH:
            raise ValueError(
                f"Catatan maksimal {self.MAX_NOTE_LENGTH} karakter."
            )

        count, total = self.daily_totals(cashier.id, report_date)
        report = self.get_for_cashier(cashier.id, report_date)
        if report is None:
            report = CashierDailyReport(
                cashier_id=cashier.id,
                report_date=report_date,
            )
            self.session.add(report)
        report.sales_count = count
        report.sales_total = total
        report.notes = notes
        try:
            self.session.commit()
            self.session.refresh(report)
        except Exception:
            self.session.rollback()
            raise
        return report

    def daily_totals(self, cashier_id: int, report_date: date) -> tuple[int, int]:
        start = datetime.combine(report_date, time.min).astimezone(timezone.utc)
        end = datetime.combine(
            report_date + timedelta(days=1),
            time.min,
        ).astimezone(timezone.utc)
        return self.session.execute(
            select(
                func.count(Sale.id),
                func.coalesce(func.sum(Sale.grand_total), 0),
            ).where(
                Sale.cashier_id == cashier_id,
                Sale.status == "PAID",
                Sale.created_at >= start.replace(tzinfo=None),
                Sale.created_at < end.replace(tzinfo=None),
            )
        ).one()

    def reports(self, start: datetime, end: datetime) -> list[CashierDailyReport]:
        if start >= end:
            raise ValueError("Waktu awal laporan harus sebelum waktu akhir.")

        local_start = start.astimezone()
        local_end = end.astimezone()
        first_date = local_start.date()
        last_date = local_end.date()
        if local_end.time() == time.min:
            last_date -= timedelta(days=1)
        if last_date < first_date:
            return []

        statement = (
            select(CashierDailyReport)
            .join(User, User.id == CashierDailyReport.cashier_id)
            .where(
                CashierDailyReport.report_date >= first_date,
                CashierDailyReport.report_date <= last_date,
            )
            .order_by(
                CashierDailyReport.report_date.desc(),
                User.full_name,
            )
        )
        return list(self.session.scalars(statement))

    def reports_all(self) -> list[CashierDailyReport]:
        """Semua laporan kasir harian, urut tanggal desc."""
        statement = (
            select(CashierDailyReport)
            .join(User, User.id == CashierDailyReport.cashier_id)
            .order_by(
                CashierDailyReport.report_date.desc(),
                User.full_name,
            )
        )
        return list(self.session.scalars(statement))
