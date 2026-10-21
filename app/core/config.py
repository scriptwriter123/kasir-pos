import os
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "POSApp"
    app_env: str = "development"
    app_debug: bool = True
    session_timeout_minutes: int = 480
    midtrans_server_key: str | None = None
    midtrans_notification_url: str | None = None
    dana_partner_id: str | None = None
    dana_merchant_id: str | None = None
    dana_private_key: str | None = None
    dana_base_url: str = "https://gateway-mp-sit.dana.id"
    pos_data_dir: str | None = None
    product_export_dir: str | None = None
    billing_server_url: str | None = None
    trial_minutes: int | None = None

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
    )

    @property
    def data_dir(self) -> Path:
        if self.pos_data_dir:
            path = Path(self.pos_data_dir).expanduser()
            if not path.is_absolute():
                path = Path.cwd() / path
        else:
            base = Path(os.getenv("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
            path = base / self.app_name / "data"
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def database_url(self) -> str:
        return f"sqlite:///{self.data_dir / 'pos.db'}"


settings = Settings()


def persist_env_value(key: str, value: str) -> None:
    """Simpan satu pasang nilai key=value ke file .env (tanpa menghapus lain)."""
    env_path = Path.cwd() / ".env"
    lines: list[str] = []
    if env_path.is_file():
        lines = env_path.read_text(encoding="utf-8").splitlines()
    replaced = False
    for index, line in enumerate(lines):
        if line.strip().startswith(f"{key}="):
            lines[index] = f"{key}={value}"
            replaced = True
    if not replaced:
        lines.append(f"{key}={value}")
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
