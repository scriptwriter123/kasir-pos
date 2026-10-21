import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from cryptography.hazmat.primitives import serialization

from app.services.license_service import (
    LicenseError,
    LicenseService,
    canonical_json,
    generate_license_keypair,
    issue_license,
)


@pytest.fixture
def signing_keys(tmp_path):
    private_key = tmp_path / "publisher-private.pem"
    public_key = tmp_path / "license_public_key.pem"
    generate_license_keypair(private_key, public_key, "safe-test-passphrase")
    return private_key, public_key


def test_license_request_reuses_installation_id_and_contains_store_name(
    tmp_path,
):
    service = LicenseService(tmp_path / "data", device_id="a" * 64)
    first_request = tmp_path / "first.posreq"
    second_request = tmp_path / "second.posreq"

    service.create_request("Toko Contoh", first_request)
    service.create_request("Toko Contoh", second_request)

    first = json.loads(first_request.read_text(encoding="utf-8"))
    second = json.loads(second_request.read_text(encoding="utf-8"))
    assert first["installation_id"] == second["installation_id"]
    assert str(uuid.UUID(first["installation_id"])) == first["installation_id"]
    assert first["store_name"] == "Toko Contoh"


def test_issued_license_verifies_for_requesting_installation(
    tmp_path,
    signing_keys,
):
    private_key, public_key = signing_keys
    service = LicenseService(tmp_path / "data", device_id="a" * 64)
    request_path = tmp_path / "request.posreq"
    license_path = tmp_path / "license.poslic"
    service.create_request("Toko Contoh", request_path)
    request = json.loads(request_path.read_text(encoding="utf-8"))

    issue_license(
        request_path,
        license_path,
        store_name="Toko Contoh",
        private_key_path=private_key,
        passphrase="safe-test-passphrase",
    )

    payload = LicenseService.verify_license_file(
        license_path,
        expected_installation_id=request["installation_id"],
        expected_device_id="a" * 64,
        public_key_path=public_key,
    )
    assert payload["store_name"] == "Toko Contoh"
    assert payload["installation_id"] == request["installation_id"]
    assert payload["expires_at"] is None


def test_activation_persists_a_valid_license_for_later_offline_startup(
    tmp_path,
    signing_keys,
):
    private_key, public_key = signing_keys
    service = LicenseService(
        tmp_path / "data",
        device_id="a" * 64,
        public_key_path=public_key,
    )
    request_path = tmp_path / "request.posreq"
    license_path = tmp_path / "license.poslic"
    service.create_request("Toko Contoh", request_path)
    issue_license(
        request_path,
        license_path,
        store_name="Toko Contoh",
        private_key_path=private_key,
        passphrase="safe-test-passphrase",
    )

    assert service.license_status() == (False, "Lisensi belum dipasang.")
    assert service.activate(license_path) == "Toko Contoh"
    assert service.license_path.is_file()
    assert service.license_status() == (
        True,
        "Lisensi aktif untuk Toko Contoh.",
    )


def test_license_cannot_be_used_for_another_installation(
    tmp_path,
    signing_keys,
):
    private_key, public_key = signing_keys
    service = LicenseService(tmp_path / "data", device_id="a" * 64)
    request_path = tmp_path / "request.posreq"
    license_path = tmp_path / "license.poslic"
    service.create_request("Toko Contoh", request_path)
    issue_license(
        request_path,
        license_path,
        store_name="Toko Contoh",
        private_key_path=private_key,
        passphrase="safe-test-passphrase",
    )

    with pytest.raises(LicenseError, match="instalasi POS lain"):
        LicenseService.verify_license_file(
            license_path,
            expected_installation_id=str(uuid.uuid4()),
            expected_device_id="a" * 64,
            public_key_path=public_key,
        )


def test_modified_license_payload_fails_signature_validation(
    tmp_path,
    signing_keys,
):
    private_key, public_key = signing_keys
    service = LicenseService(tmp_path / "data", device_id="a" * 64)
    request_path = tmp_path / "request.posreq"
    license_path = tmp_path / "license.poslic"
    service.create_request("Toko Contoh", request_path)
    request = json.loads(request_path.read_text(encoding="utf-8"))
    issue_license(
        request_path,
        license_path,
        store_name="Toko Contoh",
        private_key_path=private_key,
        passphrase="safe-test-passphrase",
    )
    license_document = json.loads(license_path.read_text(encoding="utf-8"))
    license_document["payload"]["store_name"] = "Toko Diubah"
    license_path.write_text(json.dumps(license_document), encoding="utf-8")

    with pytest.raises(LicenseError, match="Tanda tangan lisensi"):
        LicenseService.verify_license_file(
            license_path,
            expected_installation_id=request["installation_id"],
            expected_device_id="a" * 64,
            public_key_path=public_key,
        )


def test_private_key_cannot_be_overwritten(tmp_path, signing_keys):
    private_key, public_key = signing_keys

    assert private_key.read_bytes().startswith(
        b"-----BEGIN ENCRYPTED PRIVATE KEY-----"
    )
    with pytest.raises(LicenseError, match="tidak ditimpa"):
        generate_license_keypair(private_key, public_key, "another-test-pass")


def test_short_private_key_passphrase_does_not_create_key_files(tmp_path):
    private_key = tmp_path / "publisher-private.pem"
    public_key = tmp_path / "license_public_key.pem"

    with pytest.raises(LicenseError, match="minimal 12 karakter"):
        generate_license_keypair(private_key, public_key, "too-short")

    assert not private_key.exists()
    assert not public_key.exists()


def _write_dated_license(
    tmp_path,
    private_key_path,
    *,
    expires_at,
    installation_id,
    device_id="a" * 64,
):
    private_key = serialization.load_pem_private_key(
        private_key_path.read_bytes(),
        password=b"safe-test-passphrase",
    )
    payload = {
        "schema_version": 1,
        "product": "POS Retail",
        "license_id": "AB" * 32,
        "store_name": "Toko Contoh",
        "installation_id": installation_id,
        "device_id": device_id,
        "issued_at": datetime.now(timezone.utc).isoformat(),
        "expires_at": expires_at.isoformat() if expires_at else None,
    }
    signature = private_key.sign(canonical_json(payload))
    import base64

    document = {
        "payload": payload,
        "signature": base64.b64encode(signature).decode("ascii"),
    }
    path = tmp_path / "dated.poslic"
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def test_dated_license_verifies_and_reports_active_until_expiry(
    tmp_path, signing_keys
):
    private_key, public_key = signing_keys
    installation_id = str(uuid.uuid4())
    expires_at = datetime.now(timezone.utc) + timedelta(days=30)
    license_path = _write_dated_license(
        tmp_path, private_key, expires_at=expires_at, installation_id=installation_id
    )

    payload = LicenseService.verify_license_file(
        license_path,
        expected_installation_id=installation_id,
        expected_device_id="a" * 64,
        public_key_path=public_key,
    )
    assert payload["expires_at"] == expires_at.isoformat()

    service = LicenseService(
        tmp_path / "data", device_id="a" * 64, public_key_path=public_key
    )
    service.license_path.parent.mkdir(parents=True, exist_ok=True)
    service.license_path.write_text(
        license_path.read_text(encoding="utf-8"), encoding="utf-8"
    )
    # installation_id file must match the license payload
    service.installation_id_path.write_text(installation_id, encoding="utf-8")
    licensed, status = service.license_status()
    assert licensed is True
    assert "Lisensi aktif" in status


def test_expired_license_reports_not_licensed(tmp_path, signing_keys):
    private_key, public_key = signing_keys
    installation_id = str(uuid.uuid4())
    expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
    license_path = _write_dated_license(
        tmp_path, private_key, expires_at=expires_at, installation_id=installation_id
    )

    payload = LicenseService.verify_license_file(
        license_path,
        expected_installation_id=installation_id,
        expected_device_id="a" * 64,
        public_key_path=public_key,
    )
    assert payload["expires_at"] == expires_at.isoformat()

    service = LicenseService(
        tmp_path / "data", device_id="a" * 64, public_key_path=public_key
    )
    service.license_path.parent.mkdir(parents=True, exist_ok=True)
    service.license_path.write_text(
        license_path.read_text(encoding="utf-8"), encoding="utf-8"
    )
    service.installation_id_path.write_text(installation_id, encoding="utf-8")
    licensed, status = service.license_status()
    assert licensed is False
    assert "berakhir" in status


def test_license_with_invalid_expiry_format_is_rejected(tmp_path, signing_keys):
    private_key, public_key = signing_keys
    installation_id = str(uuid.uuid4())
    license_path = _write_dated_license(
        tmp_path,
        private_key,
        expires_at=datetime.now(timezone.utc) + timedelta(days=1),
        installation_id=installation_id,
    )
    document = json.loads(license_path.read_text(encoding="utf-8"))
    document["payload"]["expires_at"] = "bukan-tanggal"
    # signature no longer matches payload -> fails at signature check first
    # unless we re-sign; instead change expires_at to a non-string type
    document["payload"]["expires_at"] = 12345
    private_key_obj = serialization.load_pem_private_key(
        private_key.read_bytes(), password=b"safe-test-passphrase"
    )
    import base64

    document["signature"] = base64.b64encode(
        private_key_obj.sign(canonical_json(document["payload"]))
    ).decode("ascii")
    license_path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(LicenseError, match="Format masa berlaku"):
        LicenseService.verify_license_file(
            license_path,
            expected_installation_id=installation_id,
            expected_device_id="a" * 64,
            public_key_path=public_key,
        )
