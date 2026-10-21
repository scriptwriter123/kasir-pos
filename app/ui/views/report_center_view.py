from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.ui.views.report_tabs_view import (
    CashExpenseReportView,
    DebtReportView,
    FinancialStatementView,
    IncomeReportView,
    InventoryValueView,
    LowStockReportView,
    ProgressReportView,
)
from app.ui.widgets import create_dashboard_back_button


class ReportCenterView(QWidget):
    """Jendela "Laporan": tab Penjualan, Absensi, dan laporan keuangan.

    Membungkus ReportView (Penjualan) dan AttendanceView (Absensi) yang
    dibangun di luar — instance yang sama tetap dipegang MainWindow
    sehingga akses langsung ke view anak masih berfungsi. Tab Keuangan
    (Modal Awal) dipindahkan ke jendela Manajemen Toko.

    Jika session + actor diberikan, jendela ini menambahkan tab
    Pendapatan, Pengeluaran, Jumlah Hutang, Stok Tipis, Nilai
    Inventaris, Laporan Keuangan, dan Progress (dibangun di dalam).
    Absensi Karyawan selalu ditempatkan setelah tab Nilai Inventaris
    (atau setelah Penjualan bila tab keuangan tidak ada).

    Indeks tab dihitung ulang per instance (indexOf) sehingga konstanta
    TAB_* selalu cocok dengan layout yang sedang dipakai.
    """

    TAB_SALES = 0
    TAB_ATTENDANCE = 1
    TAB_INCOME = -1
    TAB_CASH_EXPENSE = -1
    TAB_DEBT = -1
    TAB_LOW_STOCK = -1
    TAB_INVENTORY_VALUE = -1
    TAB_FINANCIAL_STATEMENT = -1
    TAB_PROGRESS = -1

    back_requested = Signal()

    def __init__(
        self,
        *,
        sales_view: QWidget,
        attendance_view: QWidget,
        session=None,
        actor=None,
        parent=None,
    ):
        super().__init__(parent)
        if (session is None) != (actor is None):
            raise ValueError("session dan actor harus diisi bersamaan.")
        self.sales_view = sales_view
        self.attendance_view = attendance_view
        self.income_view: IncomeReportView | None = None
        self.cash_expense_view: CashExpenseReportView | None = None
        self.debt_view: DebtReportView | None = None
        self.low_stock_view: LowStockReportView | None = None
        self.inventory_value_view: InventoryValueView | None = None
        self.financial_statement_view: FinancialStatementView | None = None
        self.progress_view: ProgressReportView | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 16)
        root.setSpacing(12)

        header = QHBoxLayout()
        self.back_button = create_dashboard_back_button(self)
        self.back_button.clicked.connect(self.back_requested.emit)
        title = QLabel("Laporan")
        title.setStyleSheet("font-size: 25px; font-weight: 700; color: #ffffff;")
        header.addWidget(self.back_button)
        header.addWidget(title)
        header.addStretch(1)
        root.addLayout(header)

        # Header internal tiap view disembunyikan; jendela ini punya
        # judul dan tombol kembali sendiri.
        for view in (sales_view, attendance_view):
            back = getattr(view, "back_button", None)
            if back is not None:
                back.hide()
            heading = getattr(view, "heading_label", None)
            if heading is not None:
                heading.hide()

        self.tabs = QTabWidget()
        self.tabs.setStyleSheet(
            "QTabWidget::pane { border: 1px solid #3f3f46; "
            "border-radius: 8px; top: -1px; }"
            "QTabBar::tab { background: transparent; color: #a1a1aa; "
            "padding: 8px 16px; font-weight: 600; "
            "border-bottom: 2px solid transparent; }"
            "QTabBar::tab:selected { color: #007acc; "
            "border-bottom: 2px solid #007acc; }"
        )
        self.tabs.addTab(sales_view, "Penjualan")
        if session is not None:
            self._add_report_tabs(session, actor)
        # Absensi selalu setelah blok laporan (Nilai Inventaris bila ada).
        self.tabs.addTab(attendance_view, "Absensi Karyawan")
        if session is not None:
            self._add_closing_tabs(session)
        self._resolve_tab_indices()
        self.tabs.currentChanged.connect(self._on_tab_changed)
        root.addWidget(self.tabs, 1)

    def _add_report_tabs(self, session, actor) -> None:
        self.income_view = IncomeReportView(session)
        self.cash_expense_view = CashExpenseReportView(session, actor)
        self.debt_view = DebtReportView(session, actor)
        self.low_stock_view = LowStockReportView(session)
        self.inventory_value_view = InventoryValueView(session)
        self.tabs.addTab(self.income_view, "Pendapatan")
        self.tabs.addTab(self.cash_expense_view, "Pengeluaran")
        self.tabs.addTab(self.debt_view, "Jumlah Hutang")
        self.tabs.addTab(self.low_stock_view, "Stok Tipis")
        self.tabs.addTab(self.inventory_value_view, "Nilai Inventaris")

    def _add_closing_tabs(self, session) -> None:
        self.financial_statement_view = FinancialStatementView(session)
        self.progress_view = ProgressReportView()
        self.tabs.addTab(
            self.financial_statement_view, "Laporan Keuangan"
        )
        self.tabs.addTab(self.progress_view, "Progress")

    def _resolve_tab_indices(self) -> None:
        self.TAB_SALES = self.tabs.indexOf(self.sales_view)
        self.TAB_ATTENDANCE = self.tabs.indexOf(self.attendance_view)
        self.TAB_INCOME = self._tab_index(self.income_view)
        self.TAB_CASH_EXPENSE = self._tab_index(self.cash_expense_view)
        self.TAB_DEBT = self._tab_index(self.debt_view)
        self.TAB_LOW_STOCK = self._tab_index(self.low_stock_view)
        self.TAB_INVENTORY_VALUE = self._tab_index(self.inventory_value_view)
        self.TAB_FINANCIAL_STATEMENT = self._tab_index(
            self.financial_statement_view
        )
        self.TAB_PROGRESS = self._tab_index(self.progress_view)

    def _tab_index(self, view) -> int:
        return self.tabs.indexOf(view) if view is not None else -1

    def show_tab(self, name: str) -> None:
        """Pindah ke tab tertentu (selalu me-refresh isinya)."""
        index = next(
            (
                i
                for i in range(self.tabs.count())
                if self.tabs.tabText(i) == name
            ),
            -1,
        )
        if index < 0:
            return
        if self.tabs.currentIndex() == index:
            self._refresh_tab(index)
        else:
            self.tabs.setCurrentIndex(index)

    def _on_tab_changed(self, index: int) -> None:
        self._refresh_tab(index)

    def _refresh_tab(self, index: int) -> None:
        if index == self.TAB_SALES:
            self.sales_view.refresh_report()
        elif index == self.TAB_ATTENDANCE:
            self.attendance_view.refresh()
        else:
            view = self.tabs.widget(index)
            refresh = getattr(view, "refresh_report", None)
            if callable(refresh):
                refresh()
