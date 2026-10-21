from datetime import datetime, timezone
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QDateEdit,
    QDateTimeEdit,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy.exc import SQLAlchemyError

from app.hardware.report_exporter import ReportExporter
from app.services.cashier_daily_report_service import CashierDailyReportService
from app.services.report_periods import calculate_period_range
from app.services.report_service import ReportService
from app.utils.formatters import rupiah
from app.ui.widgets import (
    PRIMARY_BUTTON_STYLE,
    TableSearchBar,
    create_dashboard_back_button,
)


class ReportView(QWidget):
    back_requested = Signal()

    def __init__(
        self,
        session,
        report_type: str,
        exporter: ReportExporter | None = None,
        parent=None,
    ):
        super().__init__(parent)
        if report_type not in {"sales", "profit"}:
            raise ValueError(f"Jenis laporan tidak dikenal: {report_type}")
        self.session = session
        self.report_type = report_type
        self.report_service = ReportService(session)
        self.cashier_daily_reports = CashierDailyReportService(session)
        self.exporter = exporter or ReportExporter()
        self.report_data: dict | None = None
        self.title_text = (
            "Laporan Penjualan"
            if report_type == "sales"
            else "Laporan Keuntungan"
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 10)
        root.setSpacing(4)

        header = QHBoxLayout()
        self.back_button = create_dashboard_back_button(self)
        self.back_button.clicked.connect(self.back_requested.emit)
        self.heading_label = QLabel(self.title_text)
        self.heading_label.setStyleSheet(
            "font-size: 25px; font-weight: 700; color: #ffffff;"
        )
        header.addWidget(self.back_button)
        header.addWidget(self.heading_label)
        header.addStretch(1)
        root.addLayout(header)

        # Tombol aksi dipindahkan ke bawah dan ditengah
        btn_style = (
            "QPushButton { font-size: 12px; padding: 4px 14px; "
            "min-width: 90px; }"
        )
        self.show_button = QPushButton("Tampilkan Laporan")
        self.show_button.setStyleSheet(btn_style)
        self.show_button.clicked.connect(self.refresh_report)
        self.print_button = QPushButton("Cetak")
        self.print_button.setStyleSheet(btn_style)
        self.print_button.clicked.connect(self._print_report)
        self.save_button = QPushButton("Simpan")
        self.save_button.setStyleSheet(btn_style)
        self.save_button.clicked.connect(self._save_report)

        button_row = QHBoxLayout()
        button_row.setContentsMargins(0, 8, 0, 0)
        button_row.setSpacing(15)
        button_row.addStretch(1)
        button_row.addWidget(self.show_button)
        button_row.addWidget(self.print_button)
        button_row.addWidget(self.save_button)
        button_row.addStretch(1)
        root.addLayout(button_row)

        self.summary_label = QLabel()
        self.summary_label.setWordWrap(True)
        self.summary_label.setStyleSheet(
            "font-size: 15px; font-weight: 600; color: #ffffff;"
        )
        root.addWidget(self.summary_label)
        self.warning_label = QLabel()
        self.warning_label.setWordWrap(True)
        self.warning_label.setStyleSheet("color: #fdba74;")
        self.warning_label.hide()
        root.addWidget(self.warning_label)

        self.cashier_reports_heading = QLabel("Laporan Kasir Harian")
        self.cashier_reports_heading.setStyleSheet(
            "font-size: 17px; font-weight: 700; color: #ffffff;"
        )
        root.addWidget(self.cashier_reports_heading)
        self.cashier_reports_summary = QLabel()
        self.cashier_reports_summary.setStyleSheet("color: #a1a1aa;")
        root.addWidget(self.cashier_reports_summary)
        self.cashier_reports_table = QTableWidget(0, 6)
        self.cashier_reports_table.setHorizontalHeaderLabels(
            [
                "Tanggal",
                "Kasir",
                "Transaksi",
                "Total Penjualan",
                "Catatan",
                "",
            ]
        )
        self.cashier_reports_table.setEditTriggers(
            QTableWidget.EditTrigger.NoEditTriggers
        )
        self.cashier_reports_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self.cashier_reports_table.setWordWrap(True)
        self.cashier_reports_table.setMaximumHeight(200)
        self.cashier_reports_table.horizontalHeader().setStretchLastSection(True)
        self.cashier_reports_search = TableSearchBar(
            self.cashier_reports_table, "Cari laporan kasir..."
        )
        root.addWidget(self.cashier_reports_search)
        root.addWidget(self.cashier_reports_table)
        self.cashier_reports_heading.setVisible(report_type == "sales")
        self.cashier_reports_summary.setVisible(report_type == "sales")
        self.cashier_reports_search.setVisible(report_type == "sales")
        self.cashier_reports_table.setVisible(report_type == "sales")

        self.report_table = QTableWidget()
        self.report_table.setEditTriggers(
            QTableWidget.EditTrigger.NoEditTriggers
        )
        self.report_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self.report_table.horizontalHeader().setStretchLastSection(True)
        self.report_table.setVisible(report_type != "sales")
        self.report_search = TableSearchBar(
            self.report_table, "Cari data..."
        )
        root.addWidget(self.report_search)
        root.addWidget(self.report_table, 1)
        self.report_search.setVisible(report_type != "sales")
        self.refresh_report()

    def _populate_cashier_daily_reports_all(self):
        reports = self.cashier_daily_reports.reports_all()
        self.cashier_reports_table.setRowCount(len(reports))
        for row_index, report in enumerate(reports):
            values = (
                report.report_date.strftime("%d-%m-%Y"),
                report.cashier.full_name,
                str(report.sales_count),
                rupiah(report.sales_total),
                report.notes or "-",
            )
            for column_index, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.cashier_reports_table.setItem(row_index, column_index, item)
            details_button = QPushButton("Rincian Transaksi")
            details_button.setStyleSheet(PRIMARY_BUTTON_STYLE)
            details_button.clicked.connect(
                lambda _checked=False, cashier_report=report:
                    self._open_cashier_report_details(cashier_report)
            )
            self.cashier_reports_table.setCellWidget(
                row_index,
                5,
                details_button,
            )
        self.cashier_reports_table.resizeColumnsToContents()
        self.cashier_reports_table.setColumnWidth(5, 160)
        self.cashier_reports_summary.setText(
            f"{len(reports)} laporan kasir."
            if reports
            else "Belum ada laporan kasir."
        )

    def refresh_report(self):
        try:
            # Default ke hari ini
            now = datetime.now(timezone.utc).astimezone()
            if self.report_type == "sales":
                rows = self.report_service.sales_with_filter(
                    year=now.year,
                    month=now.month,
                    day=now.day,
                )
                self._populate_sales_report(rows, "Hari Ini")
                self._populate_cashier_daily_reports_all()
            else:
                rows = self.report_service.all_profits()
                self._populate_profit_report(rows, "Semua")
        except (SQLAlchemyError, ValueError, TypeError) as exc:
            self.report_data = None
            self.report_table.setRowCount(0)
            self.summary_label.clear()
            self.warning_label.clear()
            self.warning_label.hide()
            self.print_button.setEnabled(False)
            self.save_button.setEnabled(False)
            QMessageBox.warning(self, "Laporan gagal dimuat", str(exc))

    def _populate_cashier_daily_reports(self, start: datetime, end: datetime):
        reports = self.cashier_daily_reports.reports(start, end)
        self.cashier_reports_table.setRowCount(len(reports))
        for row_index, report in enumerate(reports):
            values = (
                report.report_date.strftime("%d-%m-%Y"),
                report.cashier.full_name,
                str(report.sales_count),
                rupiah(report.sales_total),
                report.notes or "-",
            )
            for column_index, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.cashier_reports_table.setItem(row_index, column_index, item)
            details_button = QPushButton("Rincian Transaksi")
            details_button.setStyleSheet(PRIMARY_BUTTON_STYLE)
            details_button.clicked.connect(
                lambda _checked=False, cashier_report=report:
                    self._open_cashier_report_details(cashier_report)
            )
            self.cashier_reports_table.setCellWidget(
                row_index,
                5,
                details_button,
            )
        self.cashier_reports_table.resizeColumnsToContents()
        self.cashier_reports_table.setColumnWidth(5, 160)
        self.cashier_reports_summary.setText(
            f"{len(reports)} laporan kasir untuk periode yang dipilih."
            if reports
            else "Belum ada laporan kasir untuk periode yang dipilih."
        )

    def _open_cashier_report_details(self, report):
        try:
            start, end, period_label = calculate_period_range(
                "day",
                report.report_date,
            )
            sales = self.report_service.sales(
                start,
                end,
                cashier_id=report.cashier_id,
            )
        except (SQLAlchemyError, ValueError, TypeError) as exc:
            QMessageBox.warning(
                self,
                "Rincian transaksi gagal dimuat",
                str(exc),
            )
            return

        dialog = CashierDailyReportDetailsDialog(
            report,
            sales,
            period_label,
            self.exporter,
            self,
        )
        dialog.exec()

    def _populate_sales_report(self, rows: list[dict], period_label: str):
        headers = [
            "No. Invoice",
            "Waktu",
            "Kasir",
            "Produk",
            "SKU",
            "Qty",
            "Harga Satuan",
            "Subtotal Item",
            "Total Penjualan",
        ]
        table_rows = []
        for row in rows:
            items = row["items"] or [
                {
                    "product_name": "-",
                    "product_sku": "-",
                    "quantity": 0,
                    "unit_price": 0,
                    "line_total": 0,
                }
            ]
            for item_index, item in enumerate(items):
                table_rows.append(
                    [
                        row["invoice_no"],
                        self._format_datetime(row["created_at"]),
                        row["cashier_name"],
                        item["product_name"],
                        item["product_sku"],
                        str(item["quantity"]),
                        rupiah(item["unit_price"]),
                        rupiah(item["line_total"]),
                        rupiah(row["revenue"]) if item_index == 0 else "",
                    ]
                )
        total = sum(row["revenue"] for row in rows)
        summary = (
            f"Jumlah transaksi: {len(rows)}    |    "
            f"Total pendapatan transaksi hari ini: {rupiah(total)}"
        )
        self._set_report(
            headers,
            table_rows,
            period_label,
            summary,
            warning="",
        )

    def _populate_profit_report(self, rows: list[dict], period_label: str):
        headers = [
            "No. Invoice",
            "Waktu",
            "Kasir",
            "Penjualan",
            "Modal tersimpan",
            "Laba kotor",
        ]
        table_rows = []
        revenue = 0
        cost = 0
        profit = 0
        missing_cost_count = 0
        for row in rows:
            revenue += row["revenue"]
            cost += row["known_cost"]
            profit += row["known_profit"]
            missing_cost_count += row["missing_cost_count"]
            incomplete = row["missing_cost_count"] > 0
            table_rows.append(
                [
                    row["invoice_no"],
                    self._format_datetime(row["created_at"]),
                    row["cashier_name"],
                    rupiah(row["revenue"]),
                    (
                        "Modal belum lengkap"
                        if incomplete
                        else rupiah(row["known_cost"])
                    ),
                    (
                        "Belum lengkap"
                        if incomplete
                        else rupiah(row["known_profit"])
                    ),
                ]
            )
        summary = (
            f"Penjualan: {rupiah(revenue)}    |    "
            f"Modal tersimpan: {rupiah(cost)}    |    "
            f"Laba kotor terhitung: {rupiah(profit)}"
        )
        warning = (
            f"{missing_cost_count} baris item belum memiliki snapshot modal. "
            "Laba kotor di atas hanya menjumlahkan item dengan data modal; "
            "transaksi lama tidak dapat dihitung akurat."
            if missing_cost_count
            else ""
        )
        self._set_report(headers, table_rows, period_label, summary, warning)

    def _set_report(
        self,
        headers: list[str],
        rows: list[list[str]],
        period_label: str,
        summary: str,
        warning: str,
    ):
        self.summary_label.setText(summary)
        if warning:
            self.warning_label.setText(warning)
            self.warning_label.show()
        else:
            self.warning_label.hide()
        self.report_table.setColumnCount(len(headers))
        self.report_table.setHorizontalHeaderLabels(headers)
        self.report_table.setRowCount(len(rows))
        for row_index, row_values in enumerate(rows):
            for column_index, value in enumerate(row_values):
                item = QTableWidgetItem(value)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.report_table.setItem(row_index, column_index, item)
        self.report_table.resizeColumnsToContents()
        self.report_data = {
            "title": self.title_text,
            "period": period_label,
            "generated_at": datetime.now().astimezone().strftime(
                "%d-%m-%Y %H:%M:%S"
            ),
            "summary": summary,
            "warning": warning,
            "headers": headers,
            "rows": rows,
        }
        self.print_button.setEnabled(True)
        self.save_button.setEnabled(True)

    def _print_report(self):
        if self.report_data is None:
            return
        try:
            printer_name = self.exporter.print_report(self.report_data)
        except OSError as exc:
            QMessageBox.warning(self, "Tidak dapat mencetak laporan", str(exc))
            return
        QMessageBox.information(
            self,
            "Laporan dicetak",
            f"Laporan dikirim ke printer {printer_name}.",
        )

    def _save_report(self):
        if self.report_data is None:
            return
        file_path, selected_filter = QFileDialog.getSaveFileName(
            self,
            "Simpan Laporan",
            f"{self.title_text.lower().replace(' ', '_')}.pdf",
            "PDF (*.pdf);;Word Document (*.docx)",
        )
        if not file_path:
            return

        extension = ".pdf" if "PDF" in selected_filter else ".docx"
        output_path = Path(file_path)
        if output_path.suffix.lower() != extension:
            output_path = output_path.with_suffix(extension)
        try:
            if extension == ".pdf":
                saved_path = self.exporter.save_pdf(self.report_data, output_path)
            else:
                saved_path = self.exporter.save_docx(
                    self.report_data,
                    output_path,
                )
        except (ImportError, OSError, ValueError) as exc:
            QMessageBox.warning(self, "Tidak dapat menyimpan laporan", str(exc))
            return
        QMessageBox.information(
            self,
            "Laporan tersimpan",
            f"Laporan disimpan ke:\n{saved_path}",
        )

    @staticmethod
    def _format_datetime(value: datetime) -> str:
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone().strftime("%d-%m-%Y %H:%M:%S")


class CashierDailyReportDetailsDialog(QDialog):
    def __init__(self, report, sales: list[dict], period_label: str, exporter, parent=None):
        super().__init__(parent)
        self.report = report
        self.sales = sales
        self.period_label = period_label
        self.exporter = exporter
        self.setWindowTitle("Rincian Transaksi Kasir Harian")
        self.resize(1000, 600)

        layout = QVBoxLayout(self)
        heading = QLabel(
            f"{report.cashier.full_name} — {period_label}"
        )
        heading.setStyleSheet("font-size: 20px; font-weight: 700; color: #ffffff;")
        layout.addWidget(heading)
        summary = QLabel(
            f"Jumlah transaksi: {len(sales)}    |    "
            f"Total penjualan: {rupiah(sum(sale['revenue'] for sale in sales))}"
        )
        layout.addWidget(summary)
        self.notes_label = QLabel(f"Catatan kasir: {report.notes or '-'}")
        self.notes_label.setWordWrap(True)
        self.notes_label.setStyleSheet(
            "background: #1a1a1e; padding: 8px; border-radius: 6px;"
        )
        layout.addWidget(self.notes_label)

        self.details_table = QTableWidget(0, 8)
        self.details_table.setHorizontalHeaderLabels(
            [
                "No. Invoice",
                "Waktu",
                "Produk",
                "SKU",
                "Qty",
                "Harga Satuan",
                "Subtotal Item",
                "Total Transaksi",
            ]
        )
        self.details_table.setEditTriggers(
            QTableWidget.EditTrigger.NoEditTriggers
        )
        self.details_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self.details_table.horizontalHeader().setStretchLastSection(True)
        self._populate_details()
        layout.addWidget(self.details_table, 1)

        actions = QHBoxLayout()
        actions.addStretch(1)
        self.print_button = QPushButton("Cetak")
        self.print_button.setStyleSheet(PRIMARY_BUTTON_STYLE)
        self.print_button.clicked.connect(self._print_report)
        self.back_button = QPushButton("Kembali")
        self.back_button.clicked.connect(self.reject)
        actions.addWidget(self.print_button)
        actions.addWidget(self.back_button)
        layout.addLayout(actions)

    def _populate_details(self):
        row_count = sum(max(len(sale["items"]), 1) for sale in self.sales)
        self.details_table.setRowCount(row_count)
        row_index = 0
        for sale in self.sales:
            items = sale["items"] or [
                {
                    "product_name": "-",
                    "product_sku": "-",
                    "quantity": 0,
                    "unit_price": 0,
                    "line_total": 0,
                }
            ]
            for item_index, item in enumerate(items):
                values = (
                    sale["invoice_no"],
                    ReportView._format_datetime(sale["created_at"]),
                    item["product_name"],
                    item["product_sku"],
                    str(item["quantity"]),
                    rupiah(item["unit_price"]),
                    rupiah(item["line_total"]),
                    rupiah(sale["revenue"]) if item_index == 0 else "",
                )
                for column, value in enumerate(values):
                    self.details_table.setItem(
                        row_index,
                        column,
                        QTableWidgetItem(value),
                    )
                row_index += 1
        self.details_table.resizeColumnsToContents()

    def _print_report(self):
        rows = [
            [
                self.details_table.item(row, column).text()
                for column in range(self.details_table.columnCount())
            ]
            for row in range(self.details_table.rowCount())
        ]
        report_data = {
            "title": f"Laporan Kasir Harian — {self.report.cashier.full_name}",
            "period": self.period_label,
            "generated_at": datetime.now().astimezone().strftime(
                "%d-%m-%Y %H:%M:%S"
            ),
            "summary": (
                f"Jumlah transaksi: {len(self.sales)}    |    "
                f"Total penjualan: "
                f"{rupiah(sum(sale['revenue'] for sale in self.sales))}"
            ),
            "warning": f"Catatan kasir: {self.report.notes or '-'}",
            "headers": [
                "No. Invoice",
                "Waktu",
                "Produk",
                "SKU",
                "Qty",
                "Harga Satuan",
                "Subtotal Item",
                "Total Transaksi",
            ],
            "rows": rows,
        }
        try:
            printer_name = self.exporter.print_report(report_data)
        except OSError as exc:
            QMessageBox.warning(self, "Tidak dapat mencetak laporan", str(exc))
            return
        QMessageBox.information(
            self,
            "Laporan dicetak",
            f"Laporan dikirim ke printer {printer_name}.",
        )
