from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.core.config import settings
from app.services.billing_client import BillingError
from app.services.license_service import LicenseError, LicenseService
from app.services.online_activation import OnlineActivationWorker
from app.ui.theme import PALETTE
from app.ui.widgets import create_copyright_label


class LicenseView(QWidget):
    license_activated = Signal()
    read_only_requested = Signal()
    back_requested = Signal()
    # Dipancarkan saat aktivasi online (daftar/masuk) berhasil.
    # Berisi {"email": str, "store_name": str} agar Application bisa
    # langsung mengarahkan ke dashboard user bersangkutan tanpa
    # menutup jendela secara manual.
    online_activated = Signal(dict)

    def __init__(
        self,
        license_service: LicenseService,
        parent=None,
        *,
        status_message: str | None = None,
        allow_read_only: bool = False,
        show_back: bool = False,
    ):
        super().__init__(parent)
        self.setObjectName("licenseRoot")
        self.license_service = license_service
        self._show_back = show_back
        self._closing = False
        self._worker: OnlineActivationWorker | None = None
        # Kredensial online terakhir (untuk auto-login ke dashboard).
        # password disimpan hanya di memori selama proses aktivasi.
        self._pending_online_auth: dict | None = None
        self.activated_online_user: dict | None = None
        self._online_form: QFormLayout | None = None
        self._confirm_label: QWidget | None = None
        self.setWindowTitle("Aktivasi Lisensi — POS Retail")
        self.resize(640, 720)
        self.setMinimumSize(600, 640)

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 16)
        root.setSpacing(12)

        heading = QLabel("Aktivasi Lisensi POS Retail")
        heading.setStyleSheet(
            f"font-size: 24px; font-weight: 700; color: {PALETTE['text']};"
        )
        root.addWidget(heading)

        if status_message:
            status_label = QLabel(status_message.strip())
            status_label.setWordWrap(True)
            status_label.setStyleSheet(
                f"font-size: 14px; font-weight: 600; color: {PALETTE['accent']};"
            )
            root.addWidget(status_label)

        description = QLabel(
            "Lisensi POS Retail diterbitkan untuk satu instalasi komputer. "
            "Beli atau perpanjang langganan melalui website penerbit, lalu "
            "unduh file lisensi (.poslic) dan impor melalui jendela ini. "
            "Setelah lisensi terpasang, POS dapat digunakan tanpa koneksi "
            "internet. Data toko tetap tersimpan di komputer ini."
        )
        description.setWordWrap(True)
        root.addWidget(description)

        form = QFormLayout()
        form.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow
        )
        self.store_name_input = QLineEdit()
        self.store_name_input.setMaxLength(150)
        self.store_name_input.setPlaceholderText("Nama toko")
        self.installation_id_input = QLineEdit(
            self.license_service.installation_id()
        )
        self.installation_id_input.setReadOnly(True)
        form.addRow("Nama toko", self.store_name_input)
        form.addRow("ID instalasi", self.installation_id_input)
        root.addLayout(form)

        # "Simpan Permintaan Lisensi" berdiri sendiri di tengah.
        request_row = QHBoxLayout()
        request_row.addStretch(1)
        request_button = QPushButton("Simpan Permintaan Lisensi")
        request_button.clicked.connect(self._save_request)
        request_row.addWidget(request_button)
        request_row.addStretch(1)
        root.addLayout(request_row)

        # Tab aktivasi: offline (impor file .poslic) & online (billing).
        tabs = QTabWidget()
        tabs.setStyleSheet(
            "QTabWidget::pane { border: 1px solid #3f3f46; "
            "border-radius: 8px; top: -1px; }"
            "QTabBar::tab { background: transparent; color: #a1a1aa; "
            "padding: 8px 16px; font-weight: 600; "
            "border-bottom: 2px solid transparent; }"
            f"QTabBar::tab:selected {{ color: {PALETTE['accent']}; "
            f"border-bottom: 2px solid {PALETTE['accent']}; }}"
        )
        offline_page = QWidget()
        offline_layout = QVBoxLayout(offline_page)
        offline_layout.setContentsMargins(12, 14, 12, 12)
        offline_layout.setSpacing(10)
        offline_hint = QLabel(
            "Aktivasi offline: pilih file lisensi (.poslic) yang sudah Anda "
            "terima dari penerbit lisensi. Setelah terpasang, POS dapat "
            "digunakan tanpa koneksi internet."
        )
        offline_hint.setWordWrap(True)
        offline_layout.addWidget(offline_hint)
        import_button = QPushButton("Pilih Lisensi Baru")
        import_button.setStyleSheet(
            f"QPushButton {{ background: {PALETTE['accent']}; color: white; border: none; "
            f"border-radius: 8px; padding: 10px 16px; font-weight: 600; }}"
            f"QPushButton:hover {{ background: {PALETTE['accent_hover']}; }}"
        )
        import_button.clicked.connect(self._import_license)
        import_button_row = QHBoxLayout()
        import_button_row.addStretch(1)
        import_button_row.addWidget(import_button)
        import_button_row.addStretch(1)
        offline_layout.addLayout(import_button_row)
        offline_layout.addStretch(1)
        tabs.addTab(offline_page, "Aktivasi Offline")

        self._online_widgets: list[QWidget] = []
        if settings.billing_server_url:
            self._build_online_section(tabs)
        root.addWidget(tabs)

        # "Saya Sudah Bayar — Cek & Aktifkan" tetap di bawah tab,
        # tidak ikut halaman aktivasi online.
        if settings.billing_server_url:
            self.check_paid_button = QPushButton(
                "Saya Sudah Bayar \u2014 Cek & Aktifkan"
            )
            self.check_paid_button.setStyleSheet(
                "QPushButton { background: #15803d; color: white; border: none; "
                "border-radius: 8px; padding: 10px 16px; font-weight: 600; }"
                "QPushButton:hover { background: #16a34a; }"
                "QPushButton:disabled { background: #3f3f46; color: #a1a1aa; }"
            )
            self.check_paid_button.setToolTip(
                "Sudah membayar langganan lewat website? Klik untuk memeriksa "
                "status pembayaran ke webserver sekarang dan mengaktifkan POS "
                "bila lisensi sudah terbit. Data customer tercatat di dashboard "
                "admin webserver."
            )
            self.check_paid_button.clicked.connect(self._check_paid_now)
            root.addWidget(self.check_paid_button)

        if allow_read_only:
            read_only_button = QPushButton("Lanjutkan dalam Mode Baca-Saja")
            read_only_button.setStyleSheet(
                "QPushButton { background: #3f3f46; color: #e4e4e7; "
                "border: none; border-radius: 8px; padding: 10px 16px; "
                "font-weight: 600; }"
                "QPushButton:hover { background: #52525b; }"
            )
            read_only_button.setToolTip(
                "Masuk tanpa transaksi baru. Data tetap dapat dibaca "
                "dan diekspor sampai lisensi diaktifkan."
            )
            read_only_button.clicked.connect(self.read_only_requested.emit)
            root.addWidget(read_only_button)

        if show_back:
            back_button = QPushButton("Kembali ke Aplikasi")
            back_button.setStyleSheet(
                "QPushButton { background: #3f3f46; color: #e4e4e7; "
                "border: none; border-radius: 8px; padding: 10px 16px; "
                "font-weight: 600; }"
                "QPushButton:hover { background: #52525b; }"
            )
            back_button.setToolTip(
                "Kembali tanpa mengubah lisensi. Anda tetap dalam mode trial."
            )
            back_button.clicked.connect(self.back_requested.emit)
            root.addWidget(back_button)

        root.addStretch(1)
        root.addWidget(
            create_copyright_label(self),
            alignment=Qt.AlignmentFlag.AlignRight,
        )

        if settings.billing_server_url:
            self._maybe_resume_polling()

    # ------------------------------------------------------------ online

    @property
    def _device_token_file(self) -> Path:
        return self.license_service.data_dir / "billing-device-token.txt"

    @property
    def _device_email_file(self) -> Path:
        """Email akun webserver pemilik device_token (tanpa password)."""
        return self.license_service.data_dir / "billing-device-email.txt"

    def _build_online_section(self, tabs: QTabWidget) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 14, 12, 12)
        layout.setSpacing(10)

        hint = QLabel(
            "Masuk atau buat akun di Server aplikasi. Permintaan lisensi terkirim "
            "otomatis dan POS akan mengaktifkan diri setelah pembayaran "
            "terdeteksi. Sudah bayar lewat website? Klik "
            "\u201cSaya Sudah Bayar \u2014 Cek & Aktifkan\u201d di bawah."
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self._online_widgets.append(hint)

        self._register_mode = False

        form = QFormLayout()
        form.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow
        )
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(12)
        self.email_input = QLineEdit()
        self.email_input.setPlaceholderText("Email akun webserver")
        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_input.setPlaceholderText("Password (min. 8 karakter)")
        self.confirm_input = QLineEdit()
        self.confirm_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.confirm_input.setPlaceholderText("Ulangi password")
        form.addRow("Email", self.email_input)
        form.addRow("Password", self.password_input)
        self.confirm_row_index = form.rowCount()
        form.addRow("Ulangi Password", self.confirm_input)
        self._online_form = form
        # Label baris konfirmasi: disembunyikan bersama field-nya agar
        # tidak overlapping dengan tombol "Sudah punya akun? ...".
        try:
            self._confirm_label = form.labelForField(self.confirm_input)  # type: ignore[attr-defined]
        except Exception:
            self._confirm_label = None
        self._set_confirm_row_visible(False)
        layout.addLayout(form)
        self._online_widgets.extend(
            [self.email_input, self.password_input, self.confirm_input]
        )

        self.mode_toggle = QPushButton("Belum punya akun? Daftar di sini")
        self.mode_toggle.setFlat(True)
        self.mode_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.mode_toggle.setStyleSheet(
            "QPushButton { color: white; border: none; "
            "text-align: left; padding: 2px 0; font-size: 13px; }"
            "QPushButton:hover { color: #cfe9ff; }"
        )
        self.mode_toggle.clicked.connect(self._toggle_mode)
        layout.addWidget(self.mode_toggle)
        self._online_widgets.append(self.mode_toggle)

        self.online_status = QLabel("")
        self.online_status.setWordWrap(True)
        self.online_status.setStyleSheet(
            f"font-size: 13px; color: {PALETTE['accent']};"
        )
        layout.addWidget(self.online_status)
        self._online_widgets.append(self.online_status)

        self.online_button = QPushButton("Masuk & Aktivasi")
        self.online_button.setStyleSheet(
            f"QPushButton {{ background: {PALETTE['accent']}; color: white; border: none; "
            f"border-radius: 8px; padding: 10px 16px; font-weight: 600; }}"
            f"QPushButton:hover {{ background: {PALETTE['accent_hover']}; }}"
            f"QPushButton:disabled {{ background: {PALETTE['accent_hover']}; color: white; }}"
        )
        self.online_button.clicked.connect(self._start_online_activation)
        layout.addWidget(self.online_button)
        self._online_widgets.append(self.online_button)
        layout.addStretch(1)

        tabs.addTab(page, "Aktivasi Online")

    def _set_confirm_row_visible(self, visible: bool) -> None:
        """Tampilkan/sembunyikan baris 'Ulangi Password' seutuhnya.

        QFormLayout tidak otomatis menyembunyikan label saat field-nya
        disembunyikan, sehingga label 'Ulangi Password' tertinggal dan
        terlihat overlapping dengan caption 'Sudah punya akun? ...'.
        """
        self.confirm_input.setVisible(visible)
        label = self._confirm_label
        if label is not None:
            label.setVisible(visible)
        form = self._online_form
        if form is not None:
            try:
                # Qt >= 5: sembunyikan baris seutuhnya tanpa sisa gap.
                form.setRowVisible(self.confirm_row_index, visible)  # type: ignore[attr-defined]
            except Exception:
                pass
        self.updateGeometry()

    def _toggle_mode(self) -> None:
        self._register_mode = not self._register_mode
        self._set_confirm_row_visible(self._register_mode)
        if self._register_mode:
            self.online_button.setText("Daftar & Aktivasi")
            self.mode_toggle.setText("Sudah punya akun? Masuk di sini")
            self.online_status.setText("")
        else:
            self.online_button.setText("Masuk & Aktivasi")
            self.mode_toggle.setText("Belum punya akun? Daftar di sini")
            self.online_status.setText("")
            self.confirm_input.clear()

    def _set_online_enabled(self, enabled: bool) -> None:
        self.email_input.setEnabled(enabled)
        self.password_input.setEnabled(enabled)
        self.confirm_input.setEnabled(enabled)
        self.mode_toggle.setEnabled(enabled)
        self.online_button.setEnabled(enabled)
        self.check_paid_button.setEnabled(enabled)

    def _read_saved_device_token(self) -> str:
        try:
            return self._device_token_file.read_text(
                encoding="utf-8"
            ).strip()
        except OSError:
            return ""

    def _read_saved_device_email(self) -> str:
        try:
            return self._device_email_file.read_text(
                encoding="utf-8"
            ).strip()
        except OSError:
            return ""

    def _check_paid_now(self) -> None:
        """Tombol eksplisit: cek pembayaran sekarang lalu aktifkan.

        Dipakai ketika customer sudah membayar lewat website (misalnya
        setelah klik bayar di dashboard web) lalu kembali ke jendela ini
        yang dibuka dari tombol "Aktivasi Sekarang" / "Buka Aktivasi".
        Perangkat sudah terdaftar atas akun customer sehingga datanya
        tercatat di dashboard admin webserver; tinggal tarik lisensinya.
        """
        if self._worker is not None and self._worker.isRunning():
            self.online_status.setText(
                "Masih memeriksa status pembayaran\u2026 tunggu sebentar."
            )
            return
        token = self._read_saved_device_token()
        if token:
            email = self._read_saved_device_email() or self.email_input.text().strip()
            store_name = self.store_name_input.text().strip() or "Toko Saya"
            self._pending_online_auth = {
                "email": email,
                "password": self.password_input.text() if self.password_input.text() else "",
                "store_name": store_name,
                "register": False,
            }
            self.activated_online_user = None
            self.online_status.setText("Memeriksa status pembayaran\u2026")
            self._start_worker(device_token=token)
            return
        if self.email_input.text().strip() and self.password_input.text():
            # Belum ada perangkat tersimpan: login/daftar dulu (otomatis
            # mendaftarkan perangkat ke akun customer tersebut).
            self._start_online_activation()
            return
        self.online_status.setText(
            "Isi email & password lalu klik Masuk/Daftar, atau masuk sekali "
            "agar POS mengingat perangkat ini. Setelah membayar di website, "
            "klik tombol ini lagi untuk mengaktifkan."
        )

    def _start_online_activation(self) -> None:
        email = self.email_input.text().strip()
        password = self.password_input.text()
        if not email or not password:
            self.online_status.setText("Email dan password wajib diisi.")
            return
        if self._register_mode:
            if len(password) < 8:
                self.online_status.setText("Password minimal 8 karakter.")
                return
            if password != self.confirm_input.text():
                self.online_status.setText("Password dan ulangan tidak sama.")
                return
        store_name = self.store_name_input.text().strip() or "Toko Saya"
        try:
            document = self.license_service.request_document(store_name)
        except (LicenseError, OSError) as exc:
            self.online_status.setText(str(exc))
            return
        import json

        posreq_content = json.dumps(document, ensure_ascii=False, indent=2)
        self._device_token_file.unlink(missing_ok=True)
        self._device_email_file.unlink(missing_ok=True)
        # Simpan kredensial untuk auto-login ke dashboard setelah sukses,
        # sehingga jendela aktivasi tertutup otomatis tanpa aksi manual.
        self._pending_online_auth = {
            "email": email,
            "password": password,
            "store_name": store_name,
            "register": bool(self._register_mode),
        }
        self.activated_online_user = None
        self._start_worker(
            email=email,
            password=password,
            posreq_content=posreq_content,
            register_first=self._register_mode,
            store_name=store_name,
        )

    def _maybe_resume_polling(self) -> None:
        """Lanjutkan polling memakai device_token tersimpan (tanpa login)."""
        token = self._read_saved_device_token()
        if not token:
            return
        email = self._read_saved_device_email()
        if email:
            self._pending_online_auth = {
                "email": email,
                "password": "",
                "store_name": self.store_name_input.text().strip() or "Toko Saya",
                "register": False,
            }
        self._start_worker(device_token=token)

    def _start_worker(
        self,
        *,
        email: str | None = None,
        password: str | None = None,
        posreq_content: str | None = None,
        device_token: str | None = None,
        register_first: bool = False,
        store_name: str = "",
    ) -> None:
        if self._worker is not None and self._worker.isRunning():
            return
        self._set_online_enabled(False)
        if email:
            # Ingat email pemilik perangkat agar layar login bisa terisi
            # otomatis setelah aktivasi berhasil (password tidak disimpan).
            try:
                self._device_email_file.parent.mkdir(
                    parents=True, exist_ok=True
                )
                self._device_email_file.write_text(
                    email.strip() + "\n", encoding="utf-8"
                )
            except OSError:
                pass
        worker = OnlineActivationWorker(
            settings.billing_server_url or "",
            email=email,
            password=password,
            posreq_content=posreq_content,
            device_token=device_token,
            token_file=self._device_token_file,
            register_first=register_first,
            store_name=store_name,
            parent=self,
        )
        worker.status.connect(self._on_worker_status)
        worker.succeeded.connect(self._on_worker_succeeded)
        worker.failed.connect(self._on_worker_failed)
        self._worker = worker
        worker.start()

    def _on_worker_status(self, message: str) -> None:
        self.online_status.setText(message)

    def _on_worker_succeeded(self, document: object) -> None:
        try:
            store_name = self.license_service.activate_from_document(document)
        except (LicenseError, OSError) as exc:
            self.online_status.setText(f"Lisensi tidak valid: {exc}")
            self._pending_online_auth = None
            self._set_online_enabled(True)
            return
        self.online_status.setText(f"Lisensi untuk {store_name} diaktifkan.")
        # Siapkan payload auto-login: jendela ditutup otomatis oleh
        # Application.on_license_activated lalu direct ke dashboard.
        pending = dict(self._pending_online_auth or {})
        pending["store_name"] = store_name or pending.get("store_name", "")
        self.activated_online_user = pending or None
        self._pending_online_auth = None
        if self.activated_online_user:
            try:
                self.online_activated.emit(dict(self.activated_online_user))
            except Exception:
                pass
        self.license_activated.emit()

    def _on_worker_failed(self, message: str) -> None:
        self.online_status.setText(message)
        self._pending_online_auth = None
        self._set_online_enabled(True)

    def closeEvent(self, event) -> None:  # noqa: N802
        if self._worker is not None and self._worker.isRunning():
            self._worker.stop()
            self._worker.wait(3000)
        # Tutup jendela (X) harus berperilaku sama dengan tombol
        # "Kembali ke Aplikasi" saat dibuka dari dashboard owner,
        # supaya tidak keluar dari aplikasi.
        if self._show_back and not self._closing:
            self._closing = True
            self.back_requested.emit()
        super().closeEvent(event)

    def _save_request(self) -> None:
        output_path, _ = QFileDialog.getSaveFileName(
            self,
            "Simpan Permintaan Lisensi",
            "permintaan-lisensi.posreq",
            "Permintaan lisensi (*.posreq)",
        )
        if not output_path:
            return
        try:
            self.license_service.create_request(
                self.store_name_input.text(),
                Path(output_path),
            )
        except (LicenseError, OSError) as exc:
            QMessageBox.warning(self, "Permintaan gagal disimpan", str(exc))
            return
        QMessageBox.information(
            self,
            "Permintaan tersimpan",
            "Kirim file permintaan tersebut kepada penerbit lisensi. "
            "Setelah menerima file lisensi, impor melalui jendela ini.",
        )

    def _import_license(self) -> None:
        source_path, _ = QFileDialog.getOpenFileName(
            self,
            "Pilih File Lisensi",
            "",
            "Lisensi POS Retail (*.poslic)",
        )
        if not source_path:
            return
        try:
            store_name = self.license_service.activate(Path(source_path))
        except (LicenseError, OSError) as exc:
            QMessageBox.warning(self, "Lisensi tidak valid", str(exc))
            return
        QMessageBox.information(
            self,
            "POS berhasil diaktifkan",
            f"Lisensi untuk {store_name} berhasil diaktifkan.",
        )
        self.license_activated.emit()
