import base64
import hashlib
import json
import os
import re
import secrets
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from app.core.config import settings


PRODUCT_NAME = "POS Retail"
LICENSE_SCHEMA_VERSION = 1
PUBLIC_KEY_PATH = (
    Path(__file__).resolve().parents[1]
    / "core"
    / "license_public_key.pem"
)
PRIVATE_KEY_PATH = (
    Path(os.getenv("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    / "POSPublisher"
    / "license-signing-private.pem"
)


class LicenseError(ValueError):
    pass


def canonical_json(value: dict[str, Any]) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(path.suffix + ".tmp")
    temporary_path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary_path.replace(path)


class LicenseService:
    def __init__(
        self,
        data_dir: Path | None = None,
        *,
        device_id: str | None = None,
        public_key_path: Path = PUBLIC_KEY_PATH,
    ):
        self.data_dir = data_dir or settings.data_dir
        self._device_id = device_id
        self.public_key_path = public_key_path
        self.installation_id_path = self.data_dir / "installation-id.txt"
        self.license_path = self.data_dir / "license.poslic"

    def device_id(self) -> str:
        if self._device_id is not None:
            return self._device_id
        if os.name != "nt":
            raise LicenseError(
                "Aktivasi lisensi hanya didukung pada Windows."
            )
        try:
            import winreg

            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SOFTWARE\Microsoft\Cryptography",
            ) as machine_key:
                machine_guid, _ = winreg.QueryValueEx(machine_key, "MachineGuid")
        except (ImportError, OSError) as exc:
            raise LicenseError(
                "ID komputer Windows tidak dapat dibaca. Hubungi dukungan."
            ) from exc
        return hashlib.sha256(
            f"{PRODUCT_NAME}:{machine_guid}".encode("utf-8")
        ).hexdigest()

    def installation_id(self) -> str:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        if self.installation_id_path.is_file():
            installation_id = self.installation_id_path.read_text(
                encoding="utf-8"
            ).strip()
            try:
                return str(uuid.UUID(installation_id))
            except (ValueError, UnicodeError) as exc:
                raise LicenseError(
                    "ID instalasi rusak. Hubungi penerbit lisensi untuk bantuan."
                ) from exc

        installation_id = str(uuid.uuid4())
        temporary_path = self.installation_id_path.with_suffix(".tmp")
        temporary_path.write_text(installation_id + "\n", encoding="utf-8")
        temporary_path.replace(self.installation_id_path)
        return installation_id

    def create_request(self, store_name: str, output_path: Path) -> Path:
        _write_json(output_path, self.request_document(store_name))
        return output_path

    def request_document(self, store_name: str) -> dict[str, Any]:
        normalized_name = store_name.strip()
        if not normalized_name:
            raise LicenseError("Nama toko wajib diisi pada permintaan lisensi.")
        if len(normalized_name) > 150:
            raise LicenseError("Nama toko maksimal 150 karakter.")

        return {
            "schema_version": LICENSE_SCHEMA_VERSION,
            "product": PRODUCT_NAME,
            "installation_id": self.installation_id(),
            "device_id": self.device_id(),
            "store_name": normalized_name,
            "requested_at": datetime.now(timezone.utc).isoformat(),
        }

    def license_status(self) -> tuple[bool, str]:
        if not self.license_path.is_file():
            return False, "Lisensi belum dipasang."
        try:
            payload = self.verify_license_file(
                self.license_path,
                expected_installation_id=self.installation_id(),
                expected_device_id=self.device_id(),
                public_key_path=self.public_key_path,
            )
        except (OSError, json.JSONDecodeError, LicenseError):
            return False, "Lisensi tidak valid untuk instalasi ini."
        expires_at = payload.get("expires_at")
        if expires_at is not None:
            expiry = datetime.fromisoformat(expires_at)
            if expiry <= datetime.now(timezone.utc):
                return (
                    False,
                    f"Lisensi berakhir pada {expiry.date().isoformat()}. "
                    "Perpanjang langganan melalui website penerbit.",
                )
        return True, f"Lisensi aktif untuk {payload['store_name']}."

    def license_payload(self) -> dict[str, Any] | None:
        """Payload lisensi terpasang bila valid; None bila tiada/rusak.

        Dipakai kartu info langganan untuk menghitung sisa masa berlaku
        secara lokal ketika webserver tidak terjangkau.
        """
        if not self.license_path.is_file():
            return None
        try:
            return self.verify_license_file(
                self.license_path,
                expected_installation_id=self.installation_id(),
                expected_device_id=self.device_id(),
                public_key_path=self.public_key_path,
            )
        except (OSError, json.JSONDecodeError, LicenseError):
            return None

    def activate(self, source_path: Path) -> str:
        document = self._read_json(source_path)
        payload = self.verify_license_document(
            document,
            expected_installation_id=self.installation_id(),
            expected_device_id=self.device_id(),
            public_key_path=self.public_key_path,
        )
        _write_json(self.license_path, document)
        return payload["store_name"]

    def activate_from_document(self, document: dict[str, Any]) -> str:
        """Verifikasi & pasang lisensi dari dokumen (hasil unduh otomatis)."""
        payload = self.verify_license_document(
            document,
            expected_installation_id=self.installation_id(),
            expected_device_id=self.device_id(),
            public_key_path=self.public_key_path,
        )
        _write_json(self.license_path, document)
        return payload["store_name"]

    @classmethod
    def verify_license_file(
        cls,
        license_path: Path,
        *,
        expected_installation_id: str,
        expected_device_id: str,
        public_key_path: Path = PUBLIC_KEY_PATH,
    ) -> dict[str, Any]:
        document = cls._read_json(license_path)
        return cls.verify_license_document(
            document,
            expected_installation_id=expected_installation_id,
            expected_device_id=expected_device_id,
            public_key_path=public_key_path,
        )

    @staticmethod
    def verify_license_document(
        license_document: dict[str, Any],
        *,
        expected_installation_id: str,
        expected_device_id: str,
        public_key_path: Path = PUBLIC_KEY_PATH,
    ) -> dict[str, Any]:
        payload = license_document.get("payload")
        signature_text = license_document.get("signature")
        if not isinstance(payload, dict) or not isinstance(signature_text, str):
            raise LicenseError("Format file lisensi tidak valid.")

        if payload.get("schema_version") != LICENSE_SCHEMA_VERSION:
            raise LicenseError("Versi file lisensi tidak didukung.")
        if payload.get("product") != PRODUCT_NAME:
            raise LicenseError("Lisensi ini bukan untuk POS Retail.")
        if payload.get("installation_id") != expected_installation_id:
            raise LicenseError("Lisensi diterbitkan untuk instalasi POS lain.")
        if payload.get("device_id") != expected_device_id:
            raise LicenseError("Lisensi diterbitkan untuk komputer lain.")
        if not isinstance(payload.get("license_id"), str):
            raise LicenseError("ID lisensi tidak valid.")
        if (
            not isinstance(payload.get("store_name"), str)
            or not payload["store_name"].strip()
        ):
            raise LicenseError("Nama toko pada lisensi tidak valid.")
        if not isinstance(payload.get("issued_at"), str):
            raise LicenseError("Tanggal penerbitan lisensi tidak valid.")
        expires_at = payload.get("expires_at")
        if expires_at is not None:
            if not isinstance(expires_at, str):
                raise LicenseError("Format masa berlaku lisensi tidak didukung.")
            try:
                parsed_expiry = datetime.fromisoformat(expires_at)
            except ValueError as exc:
                raise LicenseError(
                    "Format masa berlaku lisensi tidak didukung."
                ) from exc
            if parsed_expiry.tzinfo is None:
                raise LicenseError(
                    "Format masa berlaku lisensi tidak didukung."
                )

        try:
            signature = base64.b64decode(signature_text, validate=True)
            public_key = serialization.load_pem_public_key(
                public_key_path.read_bytes()
            )
        except (ValueError, OSError) as exc:
            raise LicenseError(
                "Data tanda tangan atau kunci publik tidak valid."
            ) from exc
        if not isinstance(public_key, Ed25519PublicKey):
            raise LicenseError("Kunci publik lisensi tidak didukung.")
        try:
            public_key.verify(signature, canonical_json(payload))
        except InvalidSignature as exc:
            raise LicenseError(
                "Tanda tangan lisensi tidak cocok atau file telah diubah."
            ) from exc
        return payload

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise LicenseError("File lisensi/permintaan tidak dapat dibaca.") from exc
        if not isinstance(data, dict):
            raise LicenseError("Isi file lisensi/permintaan tidak valid.")
        return data


def generate_license_keypair(
    private_key_path: Path,
    public_key_path: Path,
    passphrase: str,
) -> None:
    if len(passphrase) < 12:
        raise LicenseError("Kata sandi kunci privat minimal 12 karakter.")
    if private_key_path.exists() or public_key_path.exists():
        raise LicenseError(
            "File kunci sudah ada. Kunci tidak ditimpa untuk mencegah "
            "lisensi lama menjadi tidak dapat diverifikasi."
        )

    private_key_path.parent.mkdir(parents=True, exist_ok=True)
    public_key_path.parent.mkdir(parents=True, exist_ok=True)
    private_key = Ed25519PrivateKey.generate()
    encryption = serialization.BestAvailableEncryption(passphrase.encode("utf-8"))
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=encryption,
    )
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    _write_private_key(private_key_path, private_pem)
    public_key_path.write_bytes(public_pem)


def _write_private_key(path: Path, contents: bytes) -> None:
    path.write_bytes(contents)
    if os.name != "nt":
        os.chmod(path, 0o600)


def issue_license(
    request_path: Path,
    output_path: Path,
    *,
    store_name: str,
    private_key_path: Path,
    passphrase: str,
) -> Path:
    request = LicenseService._read_json(request_path)
    if request.get("schema_version") != LICENSE_SCHEMA_VERSION:
        raise LicenseError("Versi permintaan lisensi tidak didukung.")
    if request.get("product") != PRODUCT_NAME:
        raise LicenseError("Permintaan ini bukan untuk POS Retail.")
    try:
        installation_id = str(uuid.UUID(request["installation_id"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise LicenseError("ID instalasi pada permintaan tidak valid.") from exc
    device_id = request.get("device_id")
    if not isinstance(device_id, str) or not re.fullmatch(
        r"[0-9a-f]{64}",
        device_id,
    ):
        raise LicenseError("ID komputer pada permintaan tidak valid.")

    normalized_name = store_name.strip()
    if not normalized_name:
        raise LicenseError("Nama toko wajib diisi.")
    if len(normalized_name) > 150:
        raise LicenseError("Nama toko maksimal 150 karakter.")

    try:
        private_key = serialization.load_pem_private_key(
            private_key_path.read_bytes(),
            password=passphrase.encode("utf-8"),
        )
    except (OSError, ValueError, TypeError) as exc:
        raise LicenseError(
            "Kunci privat tidak dapat dibuka. Periksa file dan kata sandinya."
        ) from exc
    if not isinstance(private_key, Ed25519PrivateKey):
        raise LicenseError("Kunci privat bukan kunci Ed25519.")

    payload = {
        "schema_version": LICENSE_SCHEMA_VERSION,
        "product": PRODUCT_NAME,
        "license_id": secrets.token_hex(16).upper(),
        "store_name": normalized_name,
        "installation_id": installation_id,
        "device_id": device_id,
        "issued_at": datetime.now(timezone.utc).isoformat(),
        "expires_at": None,
    }
    signed_license = {
        "payload": payload,
        "signature": base64.b64encode(
            private_key.sign(canonical_json(payload))
        ).decode("ascii"),
    }
    _write_json(output_path, signed_license)
    return output_path
