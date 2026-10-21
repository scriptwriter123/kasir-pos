import base64
import json
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

PRODUCT_NAME = "POS Retail"
LICENSE_SCHEMA_VERSION = 1


class SigningError(RuntimeError):
    pass


def canonical_json(value: dict[str, Any]) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def load_private_key(
    key_path: Path | None,
    passphrase: str | None,
) -> Ed25519PrivateKey:
    if key_path is None:
        raise SigningError(
            "LICENSE_PRIVATE_KEY_PATH belum dikonfigurasi. "
            "Buat pasangan kunci Ed25519 sebelum menerbitkan lisensi."
        )
    try:
        private_key = serialization.load_pem_private_key(
            key_path.read_bytes(),
            password=passphrase.encode("utf-8") if passphrase else None,
        )
    except (OSError, ValueError, TypeError) as exc:
        raise SigningError(
            "Kunci privat lisensi tidak dapat dibuka. Periksa path dan kata sandinya."
        ) from exc
    if not isinstance(private_key, Ed25519PrivateKey):
        raise SigningError("Kunci privat bukan kunci Ed25519.")
    return private_key


def build_payload(
    *,
    store_name: str,
    installation_id: str,
    device_id: str,
    expires_at: datetime | None,
    license_id: str | None = None,
    issued_at: datetime | None = None,
) -> dict[str, Any]:
    now = issued_at or datetime.now(timezone.utc)
    return {
        "schema_version": LICENSE_SCHEMA_VERSION,
        "product": PRODUCT_NAME,
        "license_id": license_id or secrets.token_hex(16).upper(),
        "store_name": store_name,
        "installation_id": installation_id,
        "device_id": device_id,
        "issued_at": now.isoformat(),
        "expires_at": expires_at.isoformat() if expires_at is not None else None,
    }


def sign_payload(
    payload: dict[str, Any],
    private_key: Ed25519PrivateKey,
) -> dict[str, Any]:
    signature = private_key.sign(canonical_json(payload))
    return {
        "payload": payload,
        "signature": base64.b64encode(signature).decode("ascii"),
    }


def verify_document(
    document: dict[str, Any],
    public_key_path: Path,
) -> dict[str, Any]:
    payload = document.get("payload")
    signature_text = document.get("signature")
    if not isinstance(payload, dict) or not isinstance(signature_text, str):
        raise SigningError("Format dokumen lisensi tidak valid.")
    try:
        signature = base64.b64decode(signature_text, validate=True)
        public_key = serialization.load_pem_public_key(public_key_path.read_bytes())
    except (ValueError, OSError) as exc:
        raise SigningError("Data tanda tangan atau kunci publik tidak valid.") from exc
    if not isinstance(public_key, Ed25519PublicKey):
        raise SigningError("Kunci publik lisensi tidak didukung.")
    try:
        public_key.verify(signature, canonical_json(payload))
    except InvalidSignature as exc:
        raise SigningError("Tanda tangan lisensi tidak cocok.") from exc
    return payload
