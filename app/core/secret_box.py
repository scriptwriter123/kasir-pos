import json
import os
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings

KEY_FILENAME = "wizard_secret.key"


class SecretBox:
    """Menyimpan data sensitif wizard sebagai token Fernet (terenkripsi).

    Kunci enkripsi dibuat sekali dan disimpan di data_dir aplikasi.
    """

    def __init__(self, key_path: Path | None = None):
        self._key_path = key_path
        self._fernet: Fernet | None = None

    @property
    def key_path(self) -> Path:
        if self._key_path is None:
            self._key_path = settings.data_dir / KEY_FILENAME
        return self._key_path

    def _instance(self) -> Fernet:
        if self._fernet is None:
            path = self.key_path
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.is_file():
                key = path.read_bytes().strip()
            else:
                key = Fernet.generate_key()
                path.write_bytes(key)
                try:
                    os.chmod(path, 0o600)
                except OSError:
                    pass
            self._fernet = Fernet(key)
        return self._fernet

    def encrypt(self, data: dict[str, Any]) -> str:
        raw = json.dumps(data, ensure_ascii=False).encode("utf-8")
        return self._instance().encrypt(raw).decode("ascii")

    def decrypt(self, token: str) -> dict[str, Any]:
        if not token:
            return {}
        try:
            raw = self._instance().decrypt(token.encode("ascii"))
        except InvalidToken as exc:
            raise ValueError(
                "Data wizard tidak dapat dibuka karena kunci enkripsi berubah."
            ) from exc
        decoded = json.loads(raw.decode("utf-8"))
        return decoded if isinstance(decoded, dict) else {}
