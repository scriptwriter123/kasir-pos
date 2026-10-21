from datetime import date

from PySide6.QtCore import QDate
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy.exc import SQLAlchemyError

from app.core.exceptions import AuthorizationError, ValidationError
from app.services.attendance_service import AttendanceService
from app.ui.widgets import TableSearchBar


class AttendanceView(QWidget):
    """Tab "Absensi Karyawan" — laporan kehadiran dari data login."""

    def __init__(self, actor, session, parent=None):
        super().__init__(parent)
        self.actor = actor
        self.attendance_service = AttendanceService(session)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)

        hint = QLabel(
            "Kehadiran dihitung dari login aplikasi: Hadir = login pada hari "
            "tersebut (waktu masuk = jam login pertama), Absen = tanpa login. "
            "Data diperbarui otomatis setiap hari."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #a1a1aa;")
        root.addWidget(hint)

        filters = QHBoxLayout()
        filters.setSpacing(10)
        filters.addWidget(QLabel("Tampilkan per"))
        self.period_input = QComboBox()
        self.period_input.addItems(
            list(AttendanceService.PERIODS)
        )
        self.period_input.setFixedWidth(120)
        filters.addWidget(self.period_input)
        filters.addWidget(QLabel("Tanggal acuan"))
        self.date_input = QDateEdit()
        self.date_input.setCalendarPopup(True)
        self.date_input.setDisplayFormat("dd-MM-yyyy")
        self.date_input.setDate(QDate.currentDate())
        filters.addWidget(self.date_input)
        self.show_button = QPushButton("Tampilkan")
        self.show_button.setStyleSheet(
            "QPushButton { background: #007acc; color: white; border: none; "
            "border-radius: 8px; padding: 9px 16px; font-weight: 600; }"
            "QPushButton:hover { background: #0098ff; }"
        )
        self.show_button.clicked.connect(self.refresh)
        filters.addWidget(self.show_button)
        filters.addStretch(1)
        root.addLayout(filters)

        self.summary_label = QLabel("")
        self.summary_label.setStyleSheet(
            "font-size: 13px; font-weight: 600; color: #89b4fa;"
        )
        root.addWidget(self.summary_label)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["Nama Pegawai", "Bagian", "Tanggal", "Waktu Masuk", "Status"]
        )
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self.table.horizontalHeader().setStretchLastSection(True)
        self.search_bar = TableSearchBar(
            self.table, "Cari nama / tanggal..."
        )
        root.addWidget(self.search_bar)
        root.addWidget(self.table, 1)

        self.period_input.currentIndexChanged.connect(self.refresh)
        self.date_input.dateChanged.connect(self.refresh)

    def refresh(self) -> None:
        period = self.period_input.currentText()
        anchor = self.date_input.date().toPython()
        try:
            start, end = AttendanceService.range_for_period(period, anchor)
            rows = self.attendance_service.list_attendance(
                self.actor, start, end
            )
        except (AuthorizationError, ValidationError, SQLAlchemyError) as exc:
            self.summary_label.setText(str(exc))
            return

        hadir = sum(1 for row in rows if row["status"] == "Hadir")
        absen = len(rows) - hadir
        self.summary_label.setText(
            f"Periode {start.strftime('%d-%m-%Y')} — "
            f"{end.strftime('%d-%m-%Y')} · Hadir: {hadir} · Absen: {absen}"
        )
        self.table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            values = (
                row["nama"],
                row["bagian"],
                row["tanggal"].strftime("%d-%m-%Y"),
                row["waktu_masuk"] or "-",
                row["status"],
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 4:
                    color = "#16a34a" if value == "Hadir" else "#dc2626"
                    item.setForeground(QColor(color))
                self.table.setItem(row_index, column, item)
        self.table.resizeColumnsToContents()

    def selected_date(self) -> date:
        return self.date_input.date().toPython()
