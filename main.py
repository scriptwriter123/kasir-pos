import logging

from PySide6.QtWidgets import QApplication, QMessageBox

from app.core.config import settings
from app.core.database import get_session
from app.core.logging_config import configure_logging
from app.core.migrations import upgrade_database
from app.repositories.user_repository import UserRepository
from app.services.auth_service import AuthService
from app.services.license_service import LicenseService
from app.services.owner_setup_service import OwnerSetupService
from app.services.store_settings_service import StoreSettingsService
from app.services.trial_service import TrialService, default_trial_duration
from app.services.user_management_service import UserManagementService
from app.ui.main_window import MainWindow
from app.ui.theme import STYLE_SHEET
from app.ui.views.license_view import LicenseView
from app.ui.views.login_view import LoginView

logger = logging.getLogger("pos")


class Application:
    def __init__(self):
        configure_logging(debug=settings.app_debug)
        logger.info("Starting POS application")
        self.qt = QApplication([])
        self.qt.setQuitOnLastWindowClosed(True)
        self.qt.setStyleSheet(STYLE_SHEET)
        try:
            upgrade_database()
        except Exception as exc:
            logger.exception("Database startup/migration failed")
            error_message = f"Aplikasi tidak dapat menyiapkan database:\n{exc}"
            try:
                log_path = settings.data_dir / "startup-error.log"
                log_path.write_text(
                    f"{type(exc).__name__}: {exc}\n",
                    encoding="utf-8",
                )
                error_message += f"\nDetail tersimpan di:\n{log_path}"
            except OSError as log_error:
                error_message += f"\nLog error: {log_error}"
            QMessageBox.critical(
                None,
                "Database tidak dapat disiapkan",
                error_message,
            )
            raise SystemExit(1) from exc

        logger.info("Database migrations are up to date")
        self.session = get_session()
        self.user_repository = UserRepository(self.session)
        self.auth = AuthService(self.user_repository)
        self.owner_setup = OwnerSetupService(self.session, self.user_repository)
        self.user_management = UserManagementService(
            self.session,
            self.user_repository,
        )
        self.store_settings = StoreSettingsService(self.session)
        self.license_service = LicenseService(settings.data_dir)
        from datetime import timedelta

        trial_duration = default_trial_duration()
        if settings.trial_minutes:
            trial_duration = timedelta(minutes=settings.trial_minutes)
        self.trial_service = TrialService(
            settings.data_dir, duration=trial_duration
        )
        self.login = LoginView(
            self.auth,
            self.store_settings.get_store(),
            setup_service=self.owner_setup,
        )
        self.window = None
        self.license_view = None
        self.read_only = False
        self.login.login_success.connect(self.on_login)
        licensed, status = self.license_service.license_status()
        if licensed:
            logger.info(status)
            self.login.show()
        else:
            trial_active, trial_message = self.trial_service.status()
            if trial_active:
                logger.info("POS running in trial mode: %s", trial_message)
                self.login.show()
            else:
                logger.info("POS license required: %s %s", status, trial_message)
                self.license_view = LicenseView(
                    self.license_service,
                    status_message=f"{status} {trial_message}",
                    allow_read_only=True,
                )
                self.license_view.license_activated.connect(
                    self.on_license_activated
                )
                self.license_view.read_only_requested.connect(
                    self.on_read_only_requested
                )
                self.license_view.show()

    def _close_license_view(self):
        if self.license_view is not None:
            try:
                view = self.license_view
                if getattr(view, "_worker", None) is not None:
                    try:
                        if view._worker.isRunning():
                            view._worker.stop()
                    except Exception:
                        pass
            except Exception:
                pass
            self.license_view.hide()
            self.license_view.deleteLater()
            self.license_view = None

    @staticmethod
    def _username_from_email(email: str) -> str:
        local = (email or "").strip().split("@")[0].strip()
        cleaned = "".join(
            ch if (ch.isalnum() or ch in ("_", "-", ".")) else "_"
            for ch in local
        ).strip("._-") or "owner"
        return cleaned[:80]

    def _open_dashboard_for_online_user(self, payload: dict | None) -> bool:
        """Direct ke dashboard user bersangkutan setelah Daftar/Masuk.

        Tanpa menutup jendela aktivasi secara manual: dipanggil dari
        on_license_activated sebelum jendela dihancurkan. Return True
        jika berhasil login otomatis dan dashboard dibuka.
        """
        if not payload or not isinstance(payload, dict):
            return False
        email = str(payload.get("email") or "").strip()
        password = str(payload.get("password") or "")
        store_name = str(payload.get("store_name") or "").strip()
        if email and not password:
            # Aktivasi via "Saya Sudah Bayar" tanpa kredensial lengkap:
            # email diketahui dari file pendamping perangkat, jadi isi
            # username di layar login agar user tinggal mengetik password.
            try:
                self.login.username.setText(self._username_from_email(email))
            except Exception:
                pass
            return False
        if not email or not password:
            return False
        username = self._username_from_email(email)
        try:
            if self.owner_setup.setup_required():
                full_name = store_name or username
                user = self.owner_setup.create_owner(
                    username=username,
                    full_name=full_name,
                    password=password,
                )
            else:
                try:
                    user = self.auth.login(username, password)
                except Exception:
                    # User lokal belum ada / password beda: jangan paksa,
                    # fallback ke layar login dengan username terisi.
                    self.login.username.setText(username)
                    return False
            self.on_login(user)
            return True
        except Exception as exc:
            logger.warning("Auto-login aktivasi online gagal: %s", exc)
            try:
                self.login.username.setText(username)
            except Exception:
                pass
            return False

    def on_license_activated(self):
        logger.info("POS license activated")
        online_user = getattr(
            self.license_view, "activated_online_user", None
        )
        self._close_license_view()
        self.read_only = False
        if self.window is not None:
            # Aktivasi dari dalam aplikasi: kembali ke window utama.
            self.window.dismiss_trial_banner()
            self.window.update_activation_state(True)
            self.window.show()
            return
        # Aktivasi online (Daftar/Masuk): langsung ke dashboard user
        # bersangkutan tanpa aksi tutup jendela / login manual.
        if isinstance(online_user, dict) and online_user:
            if self._open_dashboard_for_online_user(online_user):
                return
        self.login.show()

    def on_read_only_requested(self):
        logger.info("POS entering read-only mode: license/trial expired")
        self._close_license_view()
        self.read_only = True
        self.login.show()

    def _trial_banner_message(self) -> str | None:
        """Pesan trial untuk banner, hanya saat belum berlisensi."""
        licensed, _ = self.license_service.license_status()
        if licensed:
            return None
        trial_active, trial_message = self.trial_service.status()
        return trial_message if trial_active else None

    def on_login(self, user):
        logger.info("Login succeeded (read_only=%s)", self.read_only)
        trial_message = self._trial_banner_message()
        licensed, _ = self.license_service.license_status()
        self.window = MainWindow(
            user,
            self.user_management,
            read_only=self.read_only,
            trial_message=trial_message,
            licensed=licensed,
            license_service=self.license_service,
        )
        self.window.logout_requested.connect(self.on_logout)
        self.window.activation_requested.connect(self.on_activation_requested)
        self.window.store_branding_changed.connect(
            self.login.update_store_branding
        )
        self.window.show()
        self.login.hide()

    def on_activation_requested(self):
        logger.info("User requested license activation from main window")
        licensed, status = self.license_service.license_status()
        if licensed:
            if self.window is not None:
                self.window.dismiss_trial_banner()
                # Sinkronkan kartu dashboard: lisensi bisa saja terpasang
                # dari luar (impor .poslic) sejak jendela dibuat.
                self.window.update_activation_state(True)
            QMessageBox.information(
                self.window or None,
                "Lisensi Aktif",
                status,
            )
            return
        self.window.hide()
        self.login.hide()
        self.license_view = LicenseView(
            self.license_service,
            status_message=status,
            allow_read_only=False,
            show_back=True,
        )
        self.license_view.license_activated.connect(self.on_license_activated)
        self.license_view.back_requested.connect(self.on_activation_back)
        self.license_view.show()

    def on_activation_back(self):
        if self.license_view is not None:
            self.license_view.hide()
            self.license_view.deleteLater()
            self.license_view = None
        if self.window is not None:
            self.window.show()

    def on_logout(self):
        logger.info("User logged out")
        if self.window is not None:
            self.window.hide()
            self.window.deleteLater()
            self.window = None
        self.session.rollback()
        self.session.expire_all()
        self.login.reset()
        self.login.show()

    def run(self):
        try:
            return self.qt.exec()
        finally:
            self.session.close()
            logger.info("POS application stopped")


if __name__ == "__main__":
    raise SystemExit(Application().run())
