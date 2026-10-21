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
    base_url: str = "http://localhost:8001"
    session_cookie_name: str = "billing_session"
    session_ttl_days: int = 30
    license_private_key_path: Path | None = None
    license_private_key_passphrase: str | None = None
    midtrans_server_key: str | None = None
    midtrans_api_url: str = "https://api.sandbox.midtrans.com/v2"
    midtrans_snap_api_url: str = "https://api.sandbox.midtrans.com/snap/v1"
    midtrans_snap_client_key: str | None = None
    admin_api_key: str | None = None
    # Akun admin dashboard webserver. Dibuat otomatis saat startup
    # (lihat seed_admin) dan bisa dibuat manual via
    # `python -m server.seed_admin`. Ganti di server/.env untuk produksi.
    admin_email: str = "admin@pos.local"
    admin_password: str = "admin12345"
    installer_path: Path = BASE_DIR.parent / "build" / "installer_v3" / "AnjayRetailSoft.exe"
    # Nama bank yang ditampilkan pada panel ATM/transfer simulasi.
    simulated_va_bank: str = "BANK SIMULASI"

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
