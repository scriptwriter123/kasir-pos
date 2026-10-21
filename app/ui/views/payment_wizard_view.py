from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy.exc import SQLAlchemyError

from app.core.exceptions import AuthorizationError, ValidationError
from app.services.payment_wizard_service import (
    STATUS_ACTIVE,
    STATUS_IN_PROGRESS,
    STATUS_NOT_STARTED,
    STATUS_PENDING_VERIFICATION,
    STATUS_READY_TO_TEST,
    STATUSES,
    PaymentWizardService,
)
from app.ui.theme import PALETTE
from app.utils.browser import open_external_url

DANA_PORTAL_URL = "https://dashboard.dana.id"
DANA_GUIDE_URL = (
    "https://dashboard.dana.id/api-docs-v2/guide/"
    "getting-started/getting-started-onboarding"
)
DANA_DEVELOPER_URL = "https://dashboard.dana.id"

MIDTRANS_REGISTER_URL = "https://midtrans.com/id/passport"
MIDTRANS_DASHBOARD_URL = "https://dashboard.sandbox.midtrans.com"
MIDTRANS_ACCESS_KEYS_URL = "https://dashboard.sandbox.midtrans.com/settings"
MIDTRANS_DOCS_ACCOUNT_URL = "https://docs.midtrans.com/docs/midtrans-account"
MIDTRANS_DOCS_PRODUCTION_URL = "https://docs.midtrans.com/docs/switching-to-production-mode"
MIDTRANS_DOCS_NOTIFICATION_URL = "https://docs.midtrans.com/docs/notification-post"

METHOD_TITLES = {
    "QRIS_DANA": "QRIS DANA",
    "QRIS_MIDTRANS": "QRIS Midtrans",
    "BANK": "TF (m Banking)",
}


class PaymentWizardDialog(QDialog):
    """Wizard pengaturan pembayaran dalam satu halaman yang bisa di-scroll.

    Setiap metode punya sekumpulan langkah yang ditampilkan sebagai section
    di satu halaman, lengkap dengan input, tombol buka browser, dan penanda
    "langkah ini selesai" yang menggerakkan progress bar.
    """

    state_saved = Signal(str, str)

    def __init__(self, method: str, actor, service: PaymentWizardService, parent=None):
        super().__init__(parent)
        self.method = method
        self.actor = actor
        self.service = service
        self.fields: dict[str, QWidget] = {}
        self.check_groups: dict[str, list[QCheckBox]] = {}
        self.mode_manual: QRadioButton | None = None
        self.mode_va: QRadioButton | None = None
        self.manual_container: QWidget | None = None
        self.va_container: QWidget | None = None
        self.integration_direct: QRadioButton | None = None
        self.integration_qris: QRadioButton | None = None

        self.setWindowTitle(f"Wizard {self._method_title()}")
        self.setModal(True)
        self.setMinimumSize(780, 640)

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 16)
        root.setSpacing(12)
        root.addLayout(self._build_header())

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        content = QWidget()
        content.setObjectName("wizardContent")
        content.setStyleSheet(
            f"QWidget#wizardContent {{ background-color: {PALETTE['window']}; }}"
        )
        self.content_layout = QVBoxLayout(content)
        self.content_layout.setContentsMargins(4, 4, 4, 4)
        self.content_layout.setSpacing(12)
        scroll.setWidget(content)
        root.addWidget(scroll, 1)

        self._build_steps(self.content_layout)
        self.content_layout.addStretch(1)

        root.addLayout(self._build_footer())

        self._load()
        self._update_progress()

    # ---------- chrome ----------

    def _build_header(self) -> QVBoxLayout:
        box = QVBoxLayout()
        box.setSpacing(6)

        row = QHBoxLayout()
        title = QLabel(f"Wizard {self._method_title()}")
        title.setStyleSheet("font-size:20px; font-weight:700; color:#ffffff;")
        row.addWidget(title)
        row.addStretch(1)
        row.addWidget(QLabel("Status:"))
        self.status_combo = QComboBox()
        for code, label in STATUSES:
            self.status_combo.addItem(label, code)
        row.addWidget(self.status_combo)
        box.addLayout(row)

        prow = QHBoxLayout()
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setFixedHeight(8)
        self.progress.setTextVisible(False)
        self.progress_label = QLabel("0/0")
        self.progress_label.setStyleSheet(f"color:{PALETTE['text_muted']};")
        prow.addWidget(self.progress, 1)
        prow.addWidget(self.progress_label)
        box.addLayout(prow)
        return box

    def _build_footer(self) -> QHBoxLayout:
        row = QHBoxLayout()
        self.save_later_btn = QPushButton("Simpan & Lanjut Nanti")
        self.save_btn = QPushButton("Simpan")
        cancel_btn = QPushButton("Batal")
        self.save_later_btn.clicked.connect(lambda: self._save(closing=True))
        self.save_btn.clicked.connect(lambda: self._save(closing=False))
        cancel_btn.clicked.connect(self.reject)
        row.addWidget(self.save_later_btn)
        row.addWidget(self.save_btn)
        row.addStretch(1)
        row.addWidget(cancel_btn)
        return row

    # ---------- step scaffolding ----------

    def _step_frame(self, number: int, title: str, desc: str, key: str = ""):
        frame = QFrame()
        frame.setObjectName(f"wizardStep{number}{key}")
        frame.setStyleSheet(
            f"QFrame#wizardStep{number}{key} {{ background-color: {PALETTE['panel']};"
            f" border:1px solid {PALETTE['border']}; border-radius:10px; }}"
        )
        body = QVBoxLayout(frame)
        body.setContentsMargins(18, 14, 18, 16)
        body.setSpacing(10)

        top = QHBoxLayout()
        badge = QLabel(str(number))
        badge.setFixedSize(28, 28)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setStyleSheet(
            f"background-color:{PALETTE['accent']}; color:#ffffff;"
            " border-radius:14px; font-weight:700;"
        )
        heading = QLabel(title)
        heading.setStyleSheet("font-size:15px; font-weight:700; color:#ffffff;")
        top.addWidget(badge)
        top.addWidget(heading)
        top.addStretch(1)
        body.addLayout(top)

        detail = QLabel(desc)
        detail.setWordWrap(True)
        detail.setStyleSheet(f"color:{PALETTE['text_muted']};")
        body.addWidget(detail)
        return frame, body

    def _form(self, body: QVBoxLayout) -> QFormLayout:
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(10)
        body.addLayout(form)
        return form

    def _add_done(self, body: QVBoxLayout, group: str = "steps_done") -> QCheckBox:
        box = QCheckBox("Langkah ini selesai")
        box.toggled.connect(self._update_progress)
        self.check_groups.setdefault(group, []).append(box)
        body.addWidget(box, 0, Qt.AlignmentFlag.AlignRight)
        return box

    # ---------- field factories ----------

    def _line(self, key: str, placeholder: str = "") -> QLineEdit:
        widget = QLineEdit()
        widget.setPlaceholderText(placeholder)
        self.fields[key] = widget
        return widget

    def _secret_line(self, key: str, placeholder: str = "") -> QLineEdit:
        widget = QLineEdit()
        widget.setEchoMode(QLineEdit.EchoMode.Password)
        widget.setPlaceholderText(placeholder)
        self.fields[key] = widget
        return widget

    def _combo(self, key: str, options: list[str]) -> QComboBox:
        widget = QComboBox()
        for option in options:
            widget.addItem(option, option)
        self.fields[key] = widget
        return widget

    def _check(self, key: str, label: str) -> QCheckBox:
        widget = QCheckBox(label)
        self.fields[key] = widget
        return widget

    def _link_button(self, label: str, url: str) -> QPushButton:
        button = QPushButton(label)
        button.clicked.connect(lambda _=False, target=url: open_external_url(target))
        return button

    def _url_caption(self, url: str) -> QLabel:
        caption = QLabel(url)
        caption.setStyleSheet(f"color:{PALETTE['text_muted']};")
        return caption

    # ---------- QRIS DANA steps ----------

    def _build_steps(self, layout: QVBoxLayout) -> None:
        if self.method == "QRIS_DANA":
            self._build_qris_dana_steps(layout)
        elif self.method == "QRIS_MIDTRANS":
            self._build_qris_midtrans_steps(layout)
        elif self.method == "BANK":
            self._build_bank_steps(layout)
        else:
            pending = QLabel(
                "Wizard untuk metode ini sedang disiapkan. "
                "Wizard QRIS DANA dan QRIS Midtrans sudah dapat digunakan."
            )
            pending.setWordWrap(True)
            pending.setStyleSheet(f"color:{PALETTE['text_muted']};")
            layout.addWidget(pending)

    def _build_qris_dana_steps(self, layout: QVBoxLayout) -> None:
        # 1 — jenis integrasi
        frame, body = self._step_frame(
            1,
            "Pilih jenis integrasi",
            "Tentukan produk DANA yang dipakai POS: pembayaran langsung DANA atau "
            "QRIS melalui DANA, sesuai produk yang disetujui akun merchant Anda.",
        )
        group = QButtonGroup(self)
        self.integration_direct = QRadioButton("DANA sebagai pembayaran langsung")
        self.integration_qris = QRadioButton("QRIS melalui DANA")
        group.addButton(self.integration_direct)
        group.addButton(self.integration_qris)
        body.addWidget(self.integration_direct)
        body.addWidget(self.integration_qris)
        self._add_done(body)
        layout.addWidget(frame)

        # 2 — portal merchant
        frame, body = self._step_frame(
            2,
            "Buka portal merchant",
            "Buka situs resmi DANA untuk mendaftar atau login. Aplikasi POS tidak "
            "pernah meminta kata sandi Anda; pendaftaran dilakukan langsung di portal.",
        )
        body.addWidget(self._link_button("Buka Portal DANA", DANA_PORTAL_URL))
        body.addWidget(self._url_caption(DANA_PORTAL_URL))
        self._add_done(body)
        layout.addWidget(frame)

        # 3 — daftarkan akun
        frame, body = self._step_frame(
            3,
            "Daftarkan akun",
            "Isi email, nomor HP, dan nama akun bisnis sesuai yang diminta saat "
            "pendaftaran di portal DANA.",
        )
        form = self._form(body)
        form.addRow("Email", self._line("register_email", "nama@usaha.com"))
        form.addRow("Nomor HP", self._line("register_phone", "0812xxxxxxx"))
        form.addRow(
            "Nama akun bisnis", self._line("register_account", "Nama usaha Anda")
        )
        self._add_done(body)
        layout.addWidget(frame)

        # 4 — profil bisnis
        frame, body = self._step_frame(
            4,
            "Lengkapi profil bisnis",
            "Isi nama usaha, alamat, kategori bisnis, dan status legalitas sesuai "
            "dokumen perusahaan Anda.",
        )
        form = self._form(body)
        form.addRow("Nama usaha", self._line("business_name", "Contoh: Toko Maju"))
        form.addRow("Alamat", self._line("business_address", "Alamat lengkap"))
        form.addRow(
            "Kategori bisnis",
            self._combo(
                "business_category",
                [
                    "Makanan & Minuman",
                    "Retail / Toko",
                    "Jasa",
                    "Transportasi",
                    "Lainnya",
                ],
            ),
        )
        form.addRow(
            "Legalitas",
            self._combo(
                "business_legality", ["Perorangan", "CV", "PT", "Koperasi"]
            ),
        )
        self._add_done(body)
        layout.addWidget(frame)

        # 5 — unggah dokumen
        frame, body = self._step_frame(
            5,
            "Unggah dokumen",
            "Kirim dokumen yang diminta melalui portal DANA, lalu pantau hasil "
            "verifikasinya. Posisi dokumen dicatat di sini.",
        )
        form = self._form(body)
        form.addRow(
            "Status dokumen",
            self._combo(
                "doc_status",
                ["Belum diunggah", "Sedang direview", "Disetujui", "Ditolak"],
            ),
        )
        form.addRow("Catatan", self._line("doc_note", "Nomor/riwayat verifikasi"))
        self._add_done(body)
        layout.addWidget(frame)

        # 6 — produk pembayaran
        frame, body = self._step_frame(
            6,
            "Pilih produk pembayaran",
            "Pastikan produk QRIS / pembayaran yang dibutuhkan POS sudah tersedia "
            "dan disetujui untuk akun merchant Anda.",
        )
        body.addWidget(
            self._check(
                "product_confirmed",
                "Produk pembayaran yang saya butuhkan sudah tersedia dan disetujui",
            )
        )
        self._add_done(body)
        layout.addWidget(frame)

        # 7 — integrasi developer
        frame, body = self._step_frame(
            7,
            "Mulai integrasi developer",
            "Buka dashboard developer DANA untuk memulai integrasi, lalu salin URL "
            "endpoint notifikasi bila Anda ingin menerima callback pembayaran.",
        )
        body.addWidget(
            self._link_button("Buka Dashboard Developer", DANA_DEVELOPER_URL)
        )
        body.addWidget(self._url_caption(DANA_GUIDE_URL))
        form = self._form(body)
        form.addRow(
            "URL notifikasi",
            self._line("notification_url", "https://domain-anda/callback-dana"),
        )
        self._add_done(body)
        layout.addWidget(frame)

        # 8 — konfigurasi API
        frame, body = self._step_frame(
            8,
            "Konfigurasi API",
            "Masukkan kredensial yang diberikan DANA. Client Secret dan Private Key "
            "disimpan terenkripsi dan tidak ditampilkan kembali penuh di layar.",
        )
        form = self._form(body)
        form.addRow(
            "Partner ID / Client ID", self._line("api_partner_id", "Partner ID")
        )
        form.addRow("Merchant ID", self._line("api_merchant_id", "Merchant ID"))
        form.addRow(
            "Client Secret", self._secret_line("api_client_secret", "Client secret")
        )

        key_container = QWidget()
        key_inner = QHBoxLayout(key_container)
        key_inner.setContentsMargins(0, 0, 0, 0)
        key_inner.setSpacing(8)
        key_field = self._secret_line("api_private_key", "Private key PEM")
        pick_button = QPushButton("Pilih file .pem")
        pick_button.clicked.connect(self._pick_private_key_file)
        key_inner.addWidget(key_field, 1)
        key_inner.addWidget(pick_button)
        form.addRow("Private key", key_container)

        form.addRow(
            "Environment", self._combo("api_environment", ["Sandbox", "Produksi"])
        )
        self._add_done(body)
        layout.addWidget(frame)

        # 9 — uji pembayaran
        frame, body = self._step_frame(
            9,
            "Uji pembayaran",
            "Periksa apakah kredensial valid dan POS dapat menghubungi gateway DANA. "
            "Tes transaksi lengkap (notifikasi & status lunas) dilakukan terpisah.",
        )
        test_button = QPushButton("Tes Koneksi")
        test_button.clicked.connect(self._run_connection_test)
        body.addWidget(test_button)
        form = self._form(body)
        result = self._line("test_result", "Hasil tes akan muncul di sini")
        result.setReadOnly(True)
        form.addRow("Hasil", result)
        self._add_done(body)
        layout.addWidget(frame)

        # 10 — aktivasi produksi
        frame, body = self._step_frame(
            10,
            "Aktivasi produksi",
            "Setelah persetujuan dan pengujian selesai, aktifkan mode produksi lalu "
            "ubah Status di atas menjadi Aktif untuk menandai metode siap dipakai.",
        )
        body.addWidget(
            self._check(
                "activation_confirmed",
                "Persetujuan dan uji produksi selesai, siap diaktifkan",
            )
        )
        self._add_done(body)
        layout.addWidget(frame)

    # ---------- QRIS Midtrans steps ----------

    def _build_qris_midtrans_steps(self, layout: QVBoxLayout) -> None:
        # 1 — mulai pendaftaran
        frame, body = self._step_frame(
            1,
            "Mulai pendaftaran",
            "Buka situs Midtrans dan daftarkan akun merchant. Pendaftaran dilakukan "
            "langsung di situs Midtrans, aplikasi POS tidak pernah meminta kata sandi.",
        )
        body.addWidget(self._link_button("Daftar / Login Midtrans", MIDTRANS_REGISTER_URL))
        body.addWidget(self._url_caption(MIDTRANS_DOCS_ACCOUNT_URL))
        form = self._form(body)
        form.addRow("Email akun", self._line("reg_email", "nama@usaha.com"))
        form.addRow("Nama pendaftar", self._line("reg_name", "Nama Anda"))
        form.addRow(
            "Tipe bisnis",
            self._combo(
                "business_type", ["Perorangan", "CV", "PT", "Koperasi", "Usaha Kecil"]
            ),
        )
        self._add_done(body)
        layout.addWidget(frame)

        # 2 — isi data usaha
        frame, body = self._step_frame(
            2,
            "Isi data usaha",
            "Lengkapi identitas pemilik, alamat, kontak, informasi usaha, serta "
            "situs atau media sosial / katalog bila diminta.",
        )
        form = self._form(body)
        form.addRow("Nama usaha", self._line("business_name", "Contoh: Toko Maju"))
        form.addRow("Alamat", self._line("business_address", "Alamat lengkap"))
        form.addRow("Kontak", self._line("business_contact", "0812xxxxxxx"))
        form.addRow(
            "Situs / katalog", self._line("business_site", "https://tokoanda.id")
        )
        self._add_done(body)
        layout.addWidget(frame)

        # 3 — dokumen verifikasi
        frame, body = self._step_frame(
            3,
            "Kirim dokumen verifikasi",
            "Unggah dokumen sesuai jenis usaha melalui dashboard Midtrans, lalu "
            "pantau hasil persetujuannya.",
        )
        form = self._form(body)
        form.addRow(
            "Status dokumen",
            self._combo(
                "doc_status",
                ["Belum diunggah", "Sedang direview", "Disetujui", "Ditolak"],
            ),
        )
        form.addRow("Catatan", self._line("doc_note", "Nomor/riwayat verifikasi"))
        self._add_done(body)
        layout.addWidget(frame)

        # 4 — login dashboard
        frame, body = self._step_frame(
            4,
            "Login ke dashboard",
            "Masuk ke dashboard Midtrans untuk mengelola akun, metode pembayaran, "
            "dan kredensial API.",
        )
        body.addWidget(self._link_button("Buka Dashboard Midtrans", MIDTRANS_DASHBOARD_URL))
        body.addWidget(self._url_caption(MIDTRANS_DASHBOARD_URL))
        self._add_done(body)
        layout.addWidget(frame)

        # 5 — aktifkan QRIS
        frame, body = self._step_frame(
            5,
            "Aktifkan QRIS",
            "Buka pengaturan metode pembayaran di dashboard dan ajukan aktivasi "
            "QRIS apabila belum aktif.",
        )
        body.addWidget(
            self._check(
                "qris_activated",
                "QRIS sudah aktif untuk akun merchant ini",
            )
        )
        self._add_done(body)
        layout.addWidget(frame)

        # 6 — ambil API key
        frame, body = self._step_frame(
            6,
            "Ambil API key",
            "Buka Settings → Access Keys, salin Server Key dan Client Key. "
            "Server Key wajib disimpan rahasia dan ditampilkan tertutup di sini.",
        )
        body.addWidget(self._link_button("Buka Access Keys", MIDTRANS_ACCESS_KEYS_URL))
        body.addWidget(self._url_caption(MIDTRANS_ACCESS_KEYS_URL))
        form = self._form(body)
        form.addRow("Server Key", self._secret_line("server_key", "SB-Mid-server-..."))
        form.addRow("Client Key", self._secret_line("client_key", "SB-Mid-client-..."))
        form.addRow(
            "Environment", self._combo("api_environment", ["Sandbox", "Produksi"])
        )
        self._add_done(body)
        layout.addWidget(frame)

        # 7 — hubungkan POS
        frame, body = self._step_frame(
            7,
            "Hubungkan POS",
            "Uji apakah POS dapat menghubungi Midtrans dengan Server Key yang "
            "dimasukkan. Transaksi QRIS percobaan dibuat pada uji berikutnya.",
        )
        test_button = QPushButton("Tes Koneksi")
        test_button.clicked.connect(self._run_connection_test)
        body.addWidget(test_button)
        form = self._form(body)
        result = self._line("test_result", "Hasil tes akan muncul di sini")
        result.setReadOnly(True)
        form.addRow("Hasil", result)
        self._add_done(body)
        layout.addWidget(frame)

        # 8 — uji notifikasi
        frame, body = self._step_frame(
            8,
            "Uji notifikasi",
            "Isi URL notifikasi (callback) bila digunakan, lalu pastikan perubahan "
            "status pembayaran diterima POS dari Midtrans.",
        )
        body.addWidget(self._link_button("Panduan Notifikasi", MIDTRANS_DOCS_NOTIFICATION_URL))
        form = self._form(body)
        form.addRow(
            "URL notifikasi",
            self._line("notification_url", "https://domain-anda/webhooks/midtrans"),
        )
        body.addWidget(
            self._check(
                "notification_confirmed",
                "Notifikasi pembayaran diterima oleh POS",
            )
        )
        self._add_done(body)
        layout.addWidget(frame)

        # 9 — uji transaksi
        frame, body = self._step_frame(
            9,
            "Uji transaksi QRIS",
            "Buat transaksi QRIS dari kasir, pindai dengan aplikasi pembayaran, dan "
            "pastikan transaksi berubah lunas hanya setelah status tervalidasi.",
        )
        body.addWidget(
            self._check(
                "test_transaction_confirmed",
                "Transaksi QRIS percobaan berhasil dan status lunas terverifikasi",
            )
        )
        self._add_done(body)
        layout.addWidget(frame)

        # 10 — ajukan produksi
        frame, body = self._step_frame(
            10,
            "Ajukan produksi",
            "Masukkan kredensial produksi yang terpisah dari Sandbox, jalankan uji "
            "transaksi produksi, lalu ubah Status di atas menjadi Aktif.",
        )
        body.addWidget(
            self._link_button("Panduan Produksi", MIDTRANS_DOCS_PRODUCTION_URL)
        )
        body.addWidget(
            self._check(
                "production_confirmed",
                "Kredensial produksi terpasang dan uji produksi selesai",
            )
        )
        self._add_done(body)
        layout.addWidget(frame)

    # ---------- TF / m Banking steps ----------

    def _build_bank_steps(self, layout: QVBoxLayout) -> None:
        # 1 — pilih jalur
        frame, body = self._step_frame(
            1,
            "Pilih jalur transfer",
            "Tentukan cara menerima transfer: manual ke rekening toko, atau "
            "otomatis melalui Virtual Account dari penyedia API.",
        )
        group = QButtonGroup(self)
        self.mode_manual = QRadioButton("Transfer Bank Manual (rekening toko)")
        self.mode_va = QRadioButton("Virtual Account / API (otomatis)")
        group.addButton(self.mode_manual)
        group.addButton(self.mode_va)
        self.mode_manual.setChecked(True)
        body.addWidget(self.mode_manual)
        body.addWidget(self.mode_va)
        self.mode_manual.toggled.connect(self._apply_transfer_mode)
        self._add_done(body, "steps_done")
        layout.addWidget(frame)

        self.manual_container = QWidget()
        manual_layout = QVBoxLayout(self.manual_container)
        manual_layout.setContentsMargins(0, 0, 0, 0)
        manual_layout.setSpacing(12)
        self._build_manual_steps(manual_layout)
        layout.addWidget(self.manual_container)

        self.va_container = QWidget()
        va_layout = QVBoxLayout(self.va_container)
        va_layout.setContentsMargins(0, 0, 0, 0)
        va_layout.setSpacing(12)
        self._build_va_steps(va_layout)
        layout.addWidget(self.va_container)

        self._apply_transfer_mode()

    def _build_manual_steps(self, layout: QVBoxLayout) -> None:
        # 2 — rekening tujuan
        frame, body = self._step_frame(
            2,
            "Isi rekening tujuan",
            "Masukkan rekening toko yang akan menerima transfer pelanggan.",
            key="_a",
        )
        form = self._form(body)
        form.addRow(
            "Nama bank",
            self._combo(
                "bank_name",
                ["BCA", "Mandiri", "BRI", "BNI", "BSI", "CIMB Niaga", "Lainnya"],
            ),
        )
        form.addRow("Nomor rekening", self._line("account_number", "1234567890"))
        form.addRow("Nama pemilik", self._line("account_name", "Nama pemilik rekening"))
        form.addRow(
            "Instruksi bayar",
            self._line("payment_instruction", "Transfer tepat hingga Rp1.000"),
        )
        self._add_done(body, "steps_done_manual")
        layout.addWidget(frame)

        # 3 — tampilan pembayaran
        frame, body = self._step_frame(
            3,
            "Tentukan tampilan pembayaran",
            "Pilih apakah kasir menampilkan QR pembayaran statis atau hanya "
            "informasi rekening.",
            key="_a",
        )
        form = self._form(body)
        form.addRow(
            "Tampilan",
            self._combo(
                "display_mode",
                [
                    "QR statis + informasi rekening",
                    "Hanya informasi rekening",
                ],
            ),
        )
        body.addWidget(
            self._check("show_static_qr", "Tampilkan QR pembayaran statis di kasir")
        )
        self._add_done(body, "steps_done_manual")
        layout.addWidget(frame)

        # 4 — konfirmasi
        frame, body = self._step_frame(
            4,
            "Atur cara konfirmasi",
            "Tentukan bagaimana kasir memastikan transfer benar-benar masuk "
            "sebelum menandai pembayaran lunas.",
            key="_a",
        )
        form = self._form(body)
        form.addRow(
            "Konfirmasi",
            self._combo(
                "confirmation_method",
                [
                    "Kasir memeriksa mutasi bank",
                    "Kasir menerima bukti transfer",
                    "Mutasi bank dan bukti transfer",
                ],
            ),
        )
        form.addRow(
            "Catatan",
            self._line("confirmation_note", "Contoh: cocokkan nominal persis"),
        )
        self._add_done(body, "steps_done_manual")
        layout.addWidget(frame)

        # 5 — simulasi
        frame, body = self._step_frame(
            5,
            "Simulasi transaksi",
            "Jalankan tes agar kasir terbiasa menandai pembayaran transfer "
            "sebagai lunas setelah verifikasi.",
            key="_a",
        )
        test_button = QPushButton("Tes Pengaturan")
        test_button.clicked.connect(self._run_connection_test)
        body.addWidget(test_button)
        form = self._form(body)
        result = self._line("manual_test_result", "Hasil tes akan muncul di sini")
        result.setReadOnly(True)
        form.addRow("Hasil", result)
        body.addWidget(
            self._check(
                "simulation_confirmed",
                "Simulasi berhasil dan kasir dapat menandai lunas",
            )
        )
        self._add_done(body, "steps_done_manual")
        layout.addWidget(frame)

        # 6 — simpan & aktifkan
        frame, body = self._step_frame(
            6,
            "Simpan dan aktifkan",
            "Simpan pengaturan, lalu aktifkan metode TF (m Banking) pada "
            "Pengaturan Pembayaran dan ubah Status di atas menjadi Aktif.",
            key="_a",
        )
        body.addWidget(
            self._check(
                "manual_ready",
                "Pengaturan transfer manual siap dipakai kasir",
            )
        )
        self._add_done(body, "steps_done_manual")
        layout.addWidget(frame)

    def _build_va_steps(self, layout: QVBoxLayout) -> None:
        # 2 — pilih penyedia
        frame, body = self._step_frame(
            2,
            "Pilih penyedia Virtual Account",
            "Tentukan penyedia: bank langsung atau payment gateway yang "
            "mendukung Virtual Account (VA).",
            key="_b",
        )
        body.addWidget(self._link_button("Buka Portal Pendaftaran", MIDTRANS_REGISTER_URL))
        body.addWidget(self._url_caption(MIDTRANS_DOCS_ACCOUNT_URL))
        form = self._form(body)
        form.addRow(
            "Penyedia",
            self._combo(
                "va_provider",
                [
                    "Midtrans Virtual Account",
                    "Bank langsung",
                    "Penyedia lain",
                ],
            ),
        )
        self._add_done(body, "steps_done_va")
        layout.addWidget(frame)

        # 3 — data usaha & settlement
        frame, body = self._step_frame(
            3,
            "Data usaha dan rekening settlement",
            "Isi data usaha, rekening penerima dana (settlement), dan dokumen "
            "yang dipersyaratkan penyedia.",
            key="_b",
        )
        form = self._form(body)
        form.addRow("Nama usaha", self._line("va_business_name", "Contoh: Toko Maju"))
        form.addRow(
            "Rekening settlement",
            self._line("va_settlement_account", "Bank / nomor rekening penerima"),
        )
        form.addRow("Kontak", self._line("va_contact", "0812xxxxxxx"))
        self._add_done(body, "steps_done_va")
        layout.addWidget(frame)

        # 4 — ajukan aktivasi
        frame, body = self._step_frame(
            4,
            "Ajukan aktivasi VA",
            "Ajukan aktivasi transfer bank / Virtual Account dan tunggu "
            "persetujuan penyedia.",
            key="_b",
        )
        form = self._form(body)
        form.addRow(
            "Status aktivasi",
            self._combo(
                "va_activation_status",
                ["Belum diajukan", "Sedang direview", "Disetujui", "Ditolak"],
            ),
        )
        form.addRow(
            "Catatan", self._line("va_activation_note", "Nomor/riwayat pengajuan")
        )
        self._add_done(body, "steps_done_va")
        layout.addWidget(frame)

        # 5 — kredensial sandbox
        frame, body = self._step_frame(
            5,
            "Ambil kredensial API Sandbox",
            "Salin kredensial dari dashboard penyedia. Server Key disimpan "
            "terenkripsi dan ditampilkan tertutup.",
            key="_b",
        )
        body.addWidget(self._link_button("Buka Access Keys", MIDTRANS_ACCESS_KEYS_URL))
        body.addWidget(self._url_caption(MIDTRANS_ACCESS_KEYS_URL))
        form = self._form(body)
        form.addRow("Server Key", self._secret_line("va_server_key", "SB-Mid-server-..."))
        form.addRow("Client Key", self._secret_line("va_client_key", "SB-Mid-client-..."))
        form.addRow(
            "Environment", self._combo("api_environment", ["Sandbox", "Produksi"])
        )
        self._add_done(body, "steps_done_va")
        layout.addWidget(frame)

        # 6 — uji pembuatan VA
        frame, body = self._step_frame(
            6,
            "Uji pembuatan nomor VA",
            "POS menguji pembuatan nomor VA atau instruksi transfer untuk "
            "transaksi contoh.",
            key="_b",
        )
        test_button = QPushButton("Tes Koneksi")
        test_button.clicked.connect(self._run_connection_test)
        body.addWidget(test_button)
        form = self._form(body)
        result = self._line("va_test_result", "Hasil tes akan muncul di sini")
        result.setReadOnly(True)
        form.addRow("Hasil", result)
        self._add_done(body, "steps_done_va")
        layout.addWidget(frame)

        # 7 — webhook
        frame, body = self._step_frame(
            7,
            "Uji callback / webhook",
            "Pastikan transaksi baru dinyatakan lunas hanya setelah status "
            "terverifikasi diterima dari penyedia.",
            key="_b",
        )
        body.addWidget(self._link_button("Panduan Notifikasi", MIDTRANS_DOCS_NOTIFICATION_URL))
        form = self._form(body)
        form.addRow(
            "URL webhook",
            self._line("notification_url", "https://domain-anda/webhooks/va"),
        )
        body.addWidget(
            self._check("webhook_confirmed", "Webhook diterima dan status lunas terverifikasi")
        )
        self._add_done(body, "steps_done_va")
        layout.addWidget(frame)

        # 8 — produksi
        frame, body = self._step_frame(
            8,
            "Kredensial produksi dan aktivasi",
            "Setelah lolos uji, masukkan kredensial produksi yang terpisah dari "
            "Sandbox lalu aktifkan integrasi.",
            key="_b",
        )
        body.addWidget(
            self._link_button("Panduan Produksi", MIDTRANS_DOCS_PRODUCTION_URL)
        )
        body.addWidget(
            self._check(
                "va_production_confirmed",
                "Kredensial produksi terpasang dan integrasi diaktifkan",
            )
        )
        self._add_done(body, "steps_done_va")
        layout.addWidget(frame)

    def _apply_transfer_mode(self, *_args) -> None:
        mode = self.transfer_mode
        if self.manual_container is not None:
            self.manual_container.setVisible(mode == "manual")
        if self.va_container is not None:
            self.va_container.setVisible(mode == "va")
        self._update_progress()

    def _test_result_key(self) -> str:
        if self.method != "BANK":
            return "test_result"
        return "manual_test_result" if self.transfer_mode == "manual" else "va_test_result"

    # ---------- actions ----------

    def _pick_private_key_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Pilih file Private Key (PEM)",
            "",
            "PEM / Key (*.pem *.key);;Semua file (*)",
        )
        if not path:
            return
        try:
            content = Path(path).read_text(encoding="utf-8")
        except OSError as exc:
            QMessageBox.warning(self, "Gagal membaca file", str(exc))
            return
        self.fields["api_private_key"].setText(content)

    def _run_connection_test(self) -> None:
        data = self._gather()
        ok, message = self.service.test_connection(data, method=self.method)
        result_key = self._test_result_key()
        if result_key in self.fields:
            self.fields[result_key].setText(message)
        if ok and self.status_combo.currentData() != STATUS_ACTIVE:
            self._set_status(STATUS_READY_TO_TEST)
        self._update_progress()

    # ---------- gather / populate ----------

    def _gather(self) -> dict:
        data: dict = {}
        for key, widget in self.fields.items():
            if isinstance(widget, QLineEdit):
                data[key] = widget.text()
            elif isinstance(widget, QComboBox):
                data[key] = widget.currentText()
            elif isinstance(widget, QCheckBox):
                data[key] = widget.isChecked()
        if self.integration_direct is not None:
            data["integration_type"] = (
                "qris" if self.integration_qris.isChecked() else "direct"
            )
        if self.method == "BANK":
            data["transfer_mode"] = self.transfer_mode
        for group, boxes in self.check_groups.items():
            data[group] = [index for index, box in enumerate(boxes) if box.isChecked()]
        return data

    def _populate(self, data: dict) -> None:
        for key, widget in self.fields.items():
            if key not in data:
                continue
            value = data[key]
            if isinstance(widget, QLineEdit):
                widget.setText("" if value is None else str(value))
            elif isinstance(widget, QComboBox):
                index = widget.findText(str(value))
                if index >= 0:
                    widget.setCurrentIndex(index)
            elif isinstance(widget, QCheckBox):
                widget.setChecked(bool(value))
        if self.integration_direct is not None:
            if data.get("integration_type") == "qris":
                self.integration_qris.setChecked(True)
            elif data.get("integration_type") == "direct":
                self.integration_direct.setChecked(True)
        for group, boxes in self.check_groups.items():
            done = data.get(group) or []
            for index, box in enumerate(boxes):
                box.setChecked(index in done)
        if self.method == "BANK" and self.mode_va is not None:
            self.mode_va.setChecked(data.get("transfer_mode") == "va")
            self._apply_transfer_mode()

    def _load(self) -> None:
        try:
            state = self.service.get_state(self.method)
            payload = self.service.load_payload(self.method)
        except (ValueError, SQLAlchemyError) as exc:
            QMessageBox.warning(self, "Gagal memuat wizard", str(exc))
            return
        self._populate(payload)
        self._set_status(state.status)

    def _save(self, closing: bool) -> None:
        data = self._gather()
        status = self.status_combo.currentData()
        try:
            self.service.save(
                self.actor, method=self.method, status=status, payload=data
            )
        except (AuthorizationError, ValidationError, ValueError, SQLAlchemyError) as exc:
            QMessageBox.warning(self, "Tidak tersimpan", str(exc))
            return
        self.state_saved.emit(self.method, status)
        if closing:
            self.accept()
        else:
            QMessageBox.information(
                self, "Tersimpan", "Pengaturan wizard pembayaran tersimpan."
            )

    def _set_status(self, code: str) -> None:
        for index in range(self.status_combo.count()):
            if self.status_combo.itemData(index) == code:
                self.status_combo.setCurrentIndex(index)
                return

    def _update_progress(self, *_args) -> None:
        total = len(self.step_checks)
        done = sum(1 for box in self.step_checks if box.isChecked())
        percent = int(done * 100 / total) if total else 0
        self.progress.setValue(percent)
        self.progress_label.setText(f"{done}/{total}")

    def _method_title(self) -> str:
        return METHOD_TITLES.get(self.method, self.method)

    @property
    def transfer_mode(self) -> str:
        if self.mode_va is None or not self.mode_va.isChecked():
            return "manual"
        return "va"

    @property
    def step_checks(self) -> list[QCheckBox]:
        groups = ["steps_done"]
        if self.method == "BANK":
            groups.append(f"steps_done_{self.transfer_mode}")
        boxes: list[QCheckBox] = []
        for group in groups:
            boxes.extend(self.check_groups.get(group, []))
        return boxes

