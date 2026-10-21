from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QCloseEvent, QIcon
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app.models import Store
from app.services.store_settings_service import StoreSettingsService
from app.services.user_management_service import UserManagementService
from app.ui.views.attendance_view import AttendanceView
from app.ui.views.cashier_view import CashierView
from app.ui.views.dashboard_view import DashboardView
from app.ui.views.master_data_view import MasterDataView
from app.ui.views.purchase_view import PurchaseView
from app.ui.views.report_center_view import ReportCenterView
from app.ui.views.report_view import ReportView
from app.ui.views.user_management_view import UserManagementView
from app.ui.widgets import create_copyright_label


class MainWindow(QMainWindow):
    logout_requested = Signal()
    store_branding_changed = Signal(object)
    activation_requested = Signal()

    def __init__(
        self,
        user,
        user_management: UserManagementService,
        parent=None,
        *,
        read_only: bool = False,
        trial_message: str | None = None,
        licensed: bool = False,
        license_service=None,
    ):
        super().__init__(parent)
        self.user = user
        self.user_management = user_management
        self.read_only = bool(read_only)
        self.licensed = bool(licensed)
        self.license_service = license_service
        self.store_settings = StoreSettingsService(self.user_management.session)
        self.store: Store | None = self.store_settings.get_store()
        self.stack = QStackedWidget()

        container = QWidget()
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(0)
        self.trial_banner: QFrame | None = None
        if trial_message:
            self.trial_banner = self._build_trial_banner(trial_message)
            container_layout.addWidget(self.trial_banner)
        container_layout.addWidget(self.stack)
        self.setCentralWidget(container)

        self.statusBar().addPermanentWidget(create_copyright_label(self))
        if self.read_only:
            self.statusBar().showMessage(
                "MODE BACA-SAJA — lisensi berakhir; transaksi baru terkunci."
            )
        self.resize(1100, 700)
        self.stack.currentChanged.connect(self._update_window_branding)

        role = user.role.name.upper()
        if role != "OWNER":
            # Semua bagian/tugas selain OWNER (termasuk input bebas owner)
            # memakai tampilan operasional kasir.
            self.dashboard = None
            cashier_view = CashierView(
                user,
                self.user_management.session,
                read_only=self.read_only,
            )
            cashier_view.logout_requested.connect(self.logout_requested.emit)
            self.stack.addWidget(cashier_view)
            self._update_window_branding(0)
            return

        self.dashboard = DashboardView(
            user,
            store=self.store,
            licensed=self.licensed,
            license_service=self.license_service,
        )
        self.dashboard.logout_requested.connect(self._dashboard_logout)
        self.stack.addWidget(self.dashboard)
        if role == "OWNER":
            self.dashboard.manage_users_requested.connect(
                self.show_user_management
            )
            self.user_management_view = UserManagementView(
                user,
                self.user_management,
                read_only=self.read_only,
            )
            self.user_management_view.back_requested.connect(
                self.show_dashboard
            )
            # Pengaturan toko & pembayaran kasir menempel sebagai tab
            # pertama & terakhir di dalam jendela Manajemen Toko; tab
            # "Modal Awal" (aktivasi pembukuan) menempel sebagai tab
            # kedua. Alias agar akses langsung dari MainWindow tetap ada.
            self.financial_view = self.user_management_view.financial_view
            self.store_settings_view = self.user_management_view.store_settings
            self.store_settings_view.settings_saved.connect(
                self._store_settings_saved
            )
            self.stack.addWidget(self.user_management_view)
            self.sales_report_view = ReportView(
                self.user_management.session,
                "sales",
            )
            self.sales_report_view.back_requested.connect(self.show_dashboard)
            self.attendance_view = AttendanceView(
                user,
                self.user_management.session,
            )
            # Jendela "Laporan" gabungan: Penjualan, Absensi Karyawan,
            # dan tab laporan keuangan (Pendapatan, Pengeluaran, Hutang,
            # Inventaris, Keuangan, Progress); tiap view memakai
            # instance yang sama. Tab Keuangan (Modal Awal) pindah ke
            # jendela Manajemen Toko.
            self.report_center = ReportCenterView(
                sales_view=self.sales_report_view,
                attendance_view=self.attendance_view,
                session=self.user_management.session,
                actor=user,
            )
            self.report_center.back_requested.connect(self.show_dashboard)
            self.stack.addWidget(self.report_center)
            self.master_data_view = MasterDataView(
                user,
                self.user_management.session,
            )
            self.master_data_view.back_requested.connect(self.show_dashboard)
            self.stack.addWidget(self.master_data_view)
            self.purchase_view = PurchaseView(
                user,
                self.user_management.session,
                read_only=self.read_only,
            )
            self.purchase_view.back_requested.connect(self.show_dashboard)
            self.stack.addWidget(self.purchase_view)
            self.supplier_view = self.purchase_view.supplier_view
            self.dashboard.sales_report_requested.connect(
                self.show_sales_report
            )
            self.dashboard.report_requested.connect(self.show_report_center)
            self.dashboard.activation_requested.connect(
                self.activation_requested.emit
            )
            self.dashboard.financial_report_requested.connect(
                self.show_financial_report
            )
            self.dashboard.master_data_requested.connect(self.show_master_data)
            self.dashboard.store_settings_requested.connect(
                self.show_store_settings
            )
            self.dashboard.suppliers_requested.connect(self.show_purchases)
            self.supplier_view.purchases_requested.connect(
                self.show_purchases
            )
            self._update_window_branding(self.stack.currentIndex())

    def closeEvent(self, event: QCloseEvent) -> None:
        # X saat halaman kartu dashboard terbuka: kembali ke dashboard
        # owner, jangan keluar/keluar-akun. Di dashboard, X tetap keluar.
        if (
            self.dashboard is not None
            and self.stack.currentWidget() is not self.dashboard
        ):
            self.show_dashboard()
            event.ignore()
            return
        self._shutdown_background_work()
        self.logout_requested.emit()
        event.accept()

    def _dashboard_logout(self) -> None:
        self._shutdown_background_work()
        self.logout_requested.emit()

    def _shutdown_background_work(self) -> None:
        # Worker info langganan tidak boleh masih jalan saat dashboard
        # dihancurkan (QThread: Destroyed while running).
        if self.dashboard is not None:
            self.dashboard.shutdown()

    def _build_trial_banner(self, message: str) -> QFrame:
        banner = QFrame()
        banner.setObjectName("trialBanner")
        banner.setStyleSheet(
            "#trialBanner {"
            " background: #b45309;"
            " border-bottom: 1px solid #92400e;"
            "}"
            "#trialBanner QLabel {"
            " background: transparent;"
            " color: #ffffff;"
            " font-size: 13px;"
            " font-weight: 600;"
            "}"
            "#trialBanner QPushButton {"
            " background: #ffffff;"
            " color: #b45309;"
            " border: none;"
            " border-radius: 6px;"
            " padding: 6px 12px;"
            " font-weight: 700;"
            "}"
            "#trialBanner QPushButton:hover { background: #fde68a; }"
        )
        layout = QHBoxLayout(banner)
        layout.setContentsMargins(16, 8, 16, 8)
        layout.setSpacing(12)
        label = QLabel(f"TRIAL — {message}")
        label.setWordWrap(True)
        layout.addWidget(label, 1)
        button = QPushButton("Aktivasi Sekarang")
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.clicked.connect(self.activation_requested.emit)
        layout.addWidget(button)
        return banner

    def dismiss_trial_banner(self) -> None:
        if self.trial_banner is not None:
            self.trial_banner.hide()
            self.trial_banner.deleteLater()
            self.trial_banner = None

    def update_activation_state(self, licensed: bool) -> None:
        """Sembunyikan kartu Aktivasi setelah lisensi terpasang (dst.).

        Dipanggil setelah aktivasi berhasil di dalam aplikasi agar kartu
        "Aktivasi Lisensi" langsung berganti info langganan + roadmap.
        """
        self.licensed = bool(licensed)
        if self.dashboard is None:
            return
        self.dashboard.set_licensed(self.licensed)

    def show_user_management(self):
        if self.user.role.name.upper() != "OWNER":
            return
        self.user_management_view.refresh_users()
        self.user_management_view.refresh_inventory()
        self.user_management_view.store_settings.reload_settings()
        # Jendela terbuka saat tab keuangan (Modal Awal / Catat / Bayar
        # Pengeluaran) masih terbuka: sinyal currentChanged tidak akan
        # menyala, jadi refresh manual.
        current_tab = self.user_management_view.tabs.currentWidget()
        if current_tab in (
            self.user_management_view.financial_view,
            self.user_management_view.expense_entry_view,
            self.user_management_view.expense_payment_view,
        ):
            self.user_management_view.refresh_financial()
        self.stack.setCurrentWidget(self.user_management_view)

    def show_dashboard(self):
        if self.dashboard is not None:
            self.stack.setCurrentWidget(self.dashboard)

    def show_sales_report(self):
        if self.user.role.name.upper() == "OWNER":
            self.report_center.show_tab("Penjualan")
            self.stack.setCurrentWidget(self.report_center)

    def show_financial_report(self):
        # Tab Keuangan sudah pindah ke jendela Manajemen Toko sebagai
        # tab "Modal Awal". Saat pindah tab, refresh terpicu sinyal
        # currentChanged; saat sudah di tab yang sama, refresh dilakukan
        # show_user_management di atas.
        if self.user.role.name.upper() == "OWNER":
            self.show_user_management()
            self.user_management_view.tabs.setCurrentWidget(
                self.user_management_view.financial_view
            )

    def show_report_center(self):
        if self.user.role.name.upper() == "OWNER":
            self.report_center.show_tab("Penjualan")
            self.stack.setCurrentWidget(self.report_center)

    def show_master_data(self):
        if self.user.role.name.upper() == "OWNER":
            self.master_data_view.refresh_products()
            self.stack.setCurrentWidget(self.master_data_view)

    def show_store_settings(self):
        if self.user.role.name.upper() == "OWNER":
            self.show_user_management()
            self.user_management_view.tabs.setCurrentWidget(
                self.user_management_view.store_settings.store_tab
            )

    def show_suppliers(self):
        if self.user.role.name.upper() == "OWNER":
            self.stack.setCurrentWidget(self.purchase_view)
            self.purchase_view.supplier_view.refresh_suppliers()
            self.purchase_view.tabs.setCurrentWidget(
                self.purchase_view.supplier_view
            )

    def show_purchases(self):
        if self.user.role.name.upper() == "OWNER":
            self.purchase_view.refresh_data()
            self.purchase_view.tabs.setCurrentIndex(0)
            self.stack.setCurrentWidget(self.purchase_view)

    def _store_settings_saved(self, store: Store):
        self.store = store
        self.dashboard.update_store_profile(store)
        self._update_window_branding(self.stack.currentIndex())
        self.store_branding_changed.emit(store)

    def _update_window_branding(self, page_index: int):
        widget = self.stack.widget(page_index)
        page_title = "Penjualan Harian"
        if self.dashboard is not None:
            page_titles = {
                self.dashboard: "Dashboard",
                getattr(self, "user_management_view", None): "Manajemen Toko",
                getattr(self, "report_center", None): "Laporan",
                getattr(self, "master_data_view", None): "Master Data",
                getattr(self, "purchase_view", None): "Belanja dan Supplier",
            }
            page_title = page_titles.get(widget, "POS Retail")

        store_name = self.store.name if self.store else "POS Retail"
        self.setWindowTitle(f"{store_name} — {page_title}")
        logo_path = self.store.logo_path if self.store else None
        if logo_path:
            icon = QIcon(logo_path)
            if not icon.isNull():
                self.setWindowIcon(icon)
                return
        self.setWindowIcon(QIcon())
