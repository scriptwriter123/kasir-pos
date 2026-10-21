from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.core.exceptions import AuthenticationError, PasswordChangeRequired, ValidationError
from app.core.security import hash_password, verify_password
from app.models import Store
from app.services.owner_setup_service import OwnerSetupService
from app.ui.theme import PALETTE, add_card_shadow, apply_theme
from app.ui.widgets import create_copyright_label


class LoginView(QWidget):
    login_success = Signal(object)

    def __init__(
        self,
        auth_service,
        store: Store | None = None,
        parent=None,
        setup_service: OwnerSetupService | None = None,
    ):
        super().__init__(parent)
        self.setObjectName("loginRoot")
        apply_theme(self)
        self.auth_service = auth_service
        self.setup_service = setup_service
        self.store = store
        self._apply_store_branding()

        root = QVBoxLayout(self)
        root.setContentsMargins(32, 24, 32, 20)
        root.setSpacing(12)

        self.store_logo_label = QLabel()
        self.store_logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.store_logo_label.setFixedSize(120, 80)
        self.store_name_label = QLabel()
        self.store_name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.store_name_label.setStyleSheet(
            f"font-size: 25px; font-weight: 700; color: {PALETTE['text']};"
            " background: transparent;"
        )
        self.store_slogan_label = QLabel()
        self.store_slogan_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.store_slogan_label.setStyleSheet(
            f"font-size: 18px; font-weight: 600; color: {PALETTE['accent_soft']};"
            " background: transparent;"
        )
        self.store_address_label = QLabel()
        self.store_address_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.store_address_label.setWordWrap(True)
        self.store_address_label.setStyleSheet(
            f"font-size: 14px; color: {PALETTE['text_muted']};"
            " background: transparent;"
        )
        self.store_whatsapp_label = QLabel()
        self.store_whatsapp_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.store_whatsapp_label.setStyleSheet(
            f"font-size: 14px; color: {PALETTE['text_muted']};"
            " background: transparent;"
        )
        self.store_profile = QWidget(self)
        self.store_profile.setObjectName("headerPanel")
        store_profile_layout = QVBoxLayout(self.store_profile)
        store_profile_layout.setContentsMargins(18, 16, 18, 16)
        store_profile_layout.setSpacing(3)
        store_profile_layout.addWidget(
            self.store_logo_label,
            alignment=Qt.AlignmentFlag.AlignHCenter,
        )
        store_profile_layout.addWidget(self.store_name_label)
        store_profile_layout.addWidget(self.store_slogan_label)
        store_profile_layout.addWidget(self.store_address_label)
        store_profile_layout.addWidget(self.store_whatsapp_label)
        root.addWidget(self.store_profile)
        self.update_store_profile(store)
        add_card_shadow(self.store_profile, offset=6, blur=24)

        self.username = QLineEdit()
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.Password)
        login_button = QPushButton("Login")
        login_button.clicked.connect(self._login)
        self.username.returnPressed.connect(self.password.setFocus)
        self.password.returnPressed.connect(self._login)

        self.login_panel = QWidget(self)
        self.login_panel.setObjectName("cardPanel")
        form = QFormLayout()
        form.setContentsMargins(20, 20, 20, 20)
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(12)
        form.addRow("Username", self.username)
        form.addRow("Password", self.password)
        form.addRow(login_button)
        self.login_panel.setLayout(form)
        root.addWidget(self.login_panel)
        add_card_shadow(self.login_panel)

        self.setup_panel = QWidget(self)
        self.setup_panel.setObjectName("cardPanel")
        setup_layout = QVBoxLayout(self.setup_panel)
        setup_layout.setContentsMargins(20, 20, 20, 20)
        setup_layout.setSpacing(12)
        setup_layout.addWidget(QLabel("Buat akun OWNER untuk memulai aplikasi."))
        setup_form = QFormLayout()
        setup_form.setHorizontalSpacing(14)
        setup_form.setVerticalSpacing(12)
        self.setup_username = QLineEdit()
        self.setup_username.setMaxLength(80)
        self.setup_username.setPlaceholderText("Contoh: owner")
        self.setup_full_name = QLineEdit()
        self.setup_full_name.setMaxLength(150)
        self.setup_full_name.setPlaceholderText("Nama pemilik")
        self.setup_password = QLineEdit()
        self.setup_password.setEchoMode(QLineEdit.EchoMode.Password)
        self.setup_password.setPlaceholderText("Minimal 8 karakter")
        self.setup_confirm_password = QLineEdit()
        self.setup_confirm_password.setEchoMode(QLineEdit.EchoMode.Password)
        self.setup_username.returnPressed.connect(self.setup_full_name.setFocus)
        self.setup_full_name.returnPressed.connect(self.setup_password.setFocus)
        self.setup_password.returnPressed.connect(
            self.setup_confirm_password.setFocus
        )
        self.setup_confirm_password.returnPressed.connect(self._create_owner)
        setup_form.addRow("Username", self.setup_username)
        setup_form.addRow("Nama lengkap", self.setup_full_name)
        setup_form.addRow("Password", self.setup_password)
        setup_form.addRow("Ulangi password", self.setup_confirm_password)
        setup_layout.addLayout(setup_form)
        setup_button = QPushButton("Buat Akun OWNER")
        setup_button.clicked.connect(self._create_owner)
        setup_layout.addWidget(setup_button)
        root.addWidget(self.setup_panel)
        add_card_shadow(self.setup_panel)

        setup_required = bool(
            setup_service is not None and setup_service.setup_required()
        )
        self.login_panel.setVisible(not setup_required)
        self.setup_panel.setVisible(setup_required)

        root.addStretch(1)
        footer = QHBoxLayout()
        footer.addStretch(1)
        copyright_label = create_copyright_label(self)
        copyright_label.setStyleSheet(
            f"color: {PALETTE['text_muted']}; font-size: 10px;"
            " font-weight: 600; padding: 3px 8px; background: transparent;"
        )
        footer.addWidget(copyright_label)
        root.addLayout(footer)
        self.resize(600, 680)

    def _apply_store_branding(self):
        store_name = self.store.name if self.store else "POS Retail"
        self.setWindowTitle(f"{store_name} — Login")
        if self.store and self.store.logo_path:
            icon = QIcon(self.store.logo_path)
            if not icon.isNull():
                self.setWindowIcon(icon)
                return
        self.setWindowIcon(QIcon())

    def update_store_branding(self, store: Store):
        self.store = store
        self._apply_store_branding()
        self.update_store_profile(store)

    def update_store_profile(self, store: Store | None) -> None:
        self.store = store
        self.store_name_label.setText(store.name if store else "POS Retail")
        self.store_slogan_label.setText(
            (store.slogan or "") if store else ""
        )
        self.store_address_label.setText(
            (store.address or "") if store else ""
        )
        self.store_whatsapp_label.setText(
            f"WhatsApp: {store.whatsapp}" if store and store.whatsapp else ""
        )
        self.store_slogan_label.setVisible(bool(store and store.slogan))
        self.store_address_label.setVisible(bool(store and store.address))
        self.store_whatsapp_label.setVisible(bool(store and store.whatsapp))

        self.store_logo_label.clear()
        self.store_logo_label.setVisible(False)
        if store and store.logo_path and Path(store.logo_path).is_file():
            pixmap = QPixmap(store.logo_path)
            if not pixmap.isNull():
                self.store_logo_label.setPixmap(
                    pixmap.scaled(
                        self.store_logo_label.size(),
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
                self.store_logo_label.setVisible(True)

    def reset(self):
        self.username.clear()
        self.password.clear()
        self.username.setFocus()

    def _create_owner(self):
        if self.setup_service is None:
            return
        if self.setup_password.text() != self.setup_confirm_password.text():
            QMessageBox.warning(
                self,
                "Password tidak cocok",
                "Password dan konfirmasi password harus sama.",
            )
            return

        try:
            self.setup_service.create_owner(
                username=self.setup_username.text(),
                full_name=self.setup_full_name.text(),
                password=self.setup_password.text(),
            )
        except ValidationError as exc:
            QMessageBox.warning(self, "Tidak dapat membuat OWNER", str(exc))
            return

        self.setup_panel.hide()
        self.login_panel.show()
        self.username.setText(self.setup_username.text().strip())
        self.password.clear()
        self.password.setFocus()
        QMessageBox.information(
            self,
            "Akun OWNER dibuat",
            "Akun berhasil dibuat. Silakan login dengan username dan password "
            "yang sudah didaftarkan.",
        )

    def _login(self):
        try:
            user = self.auth_service.login(
                self.username.text().strip(),
                self.password.text(),
            )
        except PasswordChangeRequired as exc:
            dialog = PasswordChangeDialog(exc.user, self)
            if dialog.exec():
                self.login_success.emit(exc.user)
            return
        except Exception as exc:
            QMessageBox.warning(self, "Login gagal", str(exc))
            return
        self.login_success.emit(user)


class PasswordChangeDialog(QDialog):
    """Dialog untuk mengganti password sementara saat login pertama kali."""

    def __init__(self, user, parent=None):
        super().__init__(parent)
        self.user = user
        self.setWindowTitle("Ubah Password")
        self.setModal(True)
        self.resize(400, 320)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        title = QLabel("Password Sementara")
        title.setStyleSheet("font-size: 14px; color: #a1a1aa;")
        layout.addWidget(title)

        self.temp_password = QLineEdit()
        self.temp_password.setEchoMode(QLineEdit.Password)
        self.temp_password.setPlaceholderText("Masukkan password sementara")
        layout.addWidget(self.temp_password)

        new_label = QLabel("Password Baru")
        new_label.setStyleSheet("font-size: 14px; color: #a1a1aa;")
        layout.addWidget(new_label)

        self.new_password = QLineEdit()
        self.new_password.setEchoMode(QLineEdit.Password)
        self.new_password.setPlaceholderText("Minimal 8 karakter")
        layout.addWidget(self.new_password)

        confirm_label = QLabel("Konfirmasi Password Baru")
        confirm_label.setStyleSheet("font-size: 14px; color: #a1a1aa;")
        layout.addWidget(confirm_label)

        self.confirm_password = QLineEdit()
        self.confirm_password.setEchoMode(QLineEdit.Password)
        self.confirm_password.setPlaceholderText("Masukkan ulang password baru")
        layout.addWidget(self.confirm_password)

        self.error_label = QLabel()
        self.error_label.setStyleSheet("color: #f87171; font-size: 12px;")
        self.error_label.hide()
        layout.addWidget(self.error_label)

        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)
        cancel_btn = QPushButton("Batal")
        cancel_btn.setStyleSheet(
            "QPushButton { background: #4b5563; color: white; border: none; "
            "border-radius: 6px; padding: 8px 24px; font-weight: 600; }"
            "QPushButton:hover { background: #6b7280; }"
        )
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)

        save_btn = QPushButton("Simpan")
        save_btn.setStyleSheet(
            "QPushButton { background: #007acc; color: white; border: none; "
            "border-radius: 6px; padding: 8px 24px; font-weight: 600; }"
            "QPushButton:hover { background: #0098ff; }"
        )
        save_btn.clicked.connect(self._save)
        btn_layout.addWidget(save_btn)
        layout.addLayout(btn_layout)

    def _save(self):
        temp = self.temp_password.text()
        new_pw = self.new_password.text()
        confirm = self.confirm_password.text()

        if not temp:
            self._show_error("Password sementara wajib diisi.")
            return
        if not verify_password(temp, self.user.password_hash):
            self._show_error("Password sementara tidak sesuai.")
            return
        if len(new_pw) < 8:
            self._show_error("Password baru minimal 8 karakter.")
            return
        if new_pw != confirm:
            self._show_error("Konfirmasi password tidak cocok.")
            return

        self.user.password_hash = hash_password(new_pw)
        self.user.must_change_password = False
        self.user.failed_login_count = 0
        self.user.locked_until = None

        from app.models import User as _User
        from sqlalchemy.orm import Session as _Session

        try:
            self.user.session.commit()
        except Exception:
            self.user.session.rollback()
            self._show_error("Gagal menyimpan password baru.")
            return

        self.accept()

    def _show_error(self, message: str):
        self.error_label.setText(message)
        self.error_label.show()
