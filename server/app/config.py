from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parents[1]

# Semua kredensial Midtrans harus satu environment. Server key menjadi
# acuan: berawalan "SB-" berarti sandbox, selain itu production.
SANDBOX_PREFIX = "SB-"


class Settings(BaseSettings):
    app_name: str = "POS Billing"
    app_env: str = "development"
    database_url: str = f"sqlite:///{BASE_DIR / 'data' / 'billing.db'}"
    base_url: str = "http://localhost:80"
    session_cookie_name: str = "billing_session"
    session_ttl_days: int = 30
    license_private_key_path: Path | None = None
    license_private_key_passphrase: str | None = None
    midtrans_server_key: str | None = None
    midtrans_api_url: str = "https://api.sandbox.midtrans.com/v2"
    midtrans_snap_api_url: str = "https://api.sandbox.midtrans.com/snap/v1"
    midtrans_snap_client_key: str | None = None
    # URL publik yang bisa dijangkau Midtrans untuk mengirim notifikasi.
    # Di development, isi dengan URL ngrok, mis: https://xxxx.ngrok.io
    # Di production, isi dengan BASE_URL server Anda.
    # Bila kosong, Midtrans memakai URL yang dikonfigurasi di MAP dashboard.
    midtrans_notification_url: str | None = None
    admin_api_key: str | None = None
    # Akun admin dashboard webserver. Dibuat otomatis saat startup
    # (lihat seed_admin) dan bisa dibuat manual via
    # `python -m server.seed_admin`. Ganti di server/.env untuk produksi.
    admin_email: str = "admin@pos.local"
    admin_password: str = "admin12345"
    installer_path: Path = BASE_DIR.parent / "build" / "installer_v3" / "AnjayRetailSoft.exe"
    # Nomor WhatsApp admin untuk bantuan / hotline aktivasi lisensi offline
    admin_whatsapp: str = "6281234567890"
    # Nama bank yang ditampilkan pada panel ATM/transfer simulasi.
    simulated_va_bank: str = "BANK SIMULASI"
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None

    @property
    def telegram_enabled(self) -> bool:
        return bool(self.telegram_bot_token and self.telegram_chat_id)

    @property
    def telegram_webhook_url(self) -> str | None:
        if not self.telegram_enabled:
            return None
        base_url = self.base_url.rstrip("/")
        return f"{base_url}/webhooks/telegram"

    @property
    def telegram_api_base(self) -> str:
        if not self.telegram_bot_token:
            return ""
        return f"https://api.telegram.org/bot{self.telegram_bot_token}"

    @property
    def telegram_send_message_url(self) -> str:
        if not self.telegram_bot_token or not self.telegram_chat_id:
            return ""
        return f"{self.telegram_api_base}/sendMessage"

    @property
    def telegram_get_updates_url(self) -> str:
        if not self.telegram_bot_token:
            return ""
        return f"{self.telegram_api_base}/getUpdates"

    @property
    def telegram_set_webhook_url(self) -> str:
        if not self.telegram_bot_token:
            return ""
        return f"{self.telegram_api_base}/setWebhook?url="

    @property
    def telegram_delete_webhook_url(self) -> str:
        if not self.telegram_bot_token:
            return ""
        return f"{self.telegram_api_base}/deleteWebhook"

    @property
    def telegram_get_me_url(self) -> str:
        if not self.telegram_bot_token:
            return ""
        return f"{self.telegram_api_base}/getMe"

    @property
    def telegram_set_my_commands_url(self) -> str:
        if not self.telegram_bot_token:
            return ""
        return f"{self.telegram_api_base}/setMyCommands"

    @property
    def telegram_commands(self) -> list[dict]:
        if not self.telegram_bot_token:
            return []
        return [
            {"command": "start", "description": "Mulai bot & lihat bantuan"},
            {"command": "status", "description": "Cek status langganan Anda"},
        ]

    @property
    def telegram_help_text(self) -> str:
        if not self.telegram_bot_token:
            return ""
        return (
            "Bot Telegram Aktif. Perintah tersedia:\n"
            "/start - Memulai bot\n"
            "/status - Cek status langganan dan hari expires\n"
        )

    @property
    def midtrans_environment(self) -> str:
        key = self.midtrans_server_key or SANDBOX_PREFIX
        return "sandbox" if key.startswith(SANDBOX_PREFIX) else "production"

    @property
    def midtrans_snap_js_url(self) -> str:
        """URL Snap.js wajib mengikuti environment, agar popup tidak
        dimuat dengan client key milik env lain."""
        if self.midtrans_environment == "sandbox":
            return "https://app.sandbox.midtrans.com/snap/snap.js"
        return "https://app.midtrans.com/snap/snap.js"

    @property
    def midtrans_snap_client_key_is_suspect(self) -> bool:
        """True bila baris client key berisi apa pun selain client key.

        Kesalahan paling umum: menempel Server Key ke kolom Client Key.
        Jangan ditebak dari awalan "SB-" — sejak perubahan format Midtrans,
        client key sandbox sah pun bisa berawalan "Mid-client-".
        """
        client = (self.midtrans_snap_client_key or "").strip()
        return client.startswith("SB-Mid-server-") or client.startswith(
            "Mid-server-"
        )

    @property
    def resolved_installer_path(self) -> Path:
        path = Path(self.installer_path).expanduser()
        if not path.is_absolute():
            path = BASE_DIR.parent / path
        return path

    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        extra="ignore",
    )


settings = Settings()
