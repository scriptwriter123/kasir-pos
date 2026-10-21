import hashlib
import json
import uuid

import httpx
import pytest
from fastapi.testclient import TestClient

from app.services.license_service import (
    LicenseService,
    generate_license_keypair,
)
from server.app.config import Settings
from server.app.main import create_app
from server.app.services import license_service as server_license_service
from server.app.services.payment_service import (
    format_va_display,
    simulated_va_number,
)

SERVER_KEY = "test-server-key"


@pytest.fixture(autouse=True)
def _reset_verify_throttle():
    """Cache throttle bersifat modul-level; DB tiap test baru tapi id order
    sama (autoincrement), jadi harus dikosongkan agar tidak saling tabrak."""
    server_license_service._LAST_VERIFY.clear()
    yield
    server_license_service._LAST_VERIFY.clear()


@pytest.fixture
def signing_keys(tmp_path):
    private_key = tmp_path / "billing-private.pem"
    public_key = tmp_path / "billing-public.pem"
    generate_license_keypair(private_key, public_key, "billing-test-pass")
    return private_key, public_key


@pytest.fixture
def client(tmp_path, signing_keys):
    private_key, public_key = signing_keys
    settings = Settings(
        _env_file=None,
        app_env="test",
        database_url=f"sqlite:///{tmp_path / 'billing.db'}",
        license_private_key_path=private_key,
        license_private_key_passphrase="billing-test-pass",
        midtrans_server_key=SERVER_KEY,
        admin_api_key="test-admin-key",
    )
    app = create_app(settings)
    with TestClient(app, follow_redirects=False) as test_client:
        test_client.public_key_path = public_key
        yield test_client


def register_and_login(client: TestClient) -> str:
    response = client.post(
        "/api/auth/register",
        json={
            "email": "toko@example.com",
            "password": "rahasia123",
            "store_name": "Toko Contoh",
        },
    )
    assert response.status_code == 200, response.text
    response = client.post(
        "/api/auth/login",
        json={"email": "toko@example.com", "password": "rahasia123"},
    )
    assert response.status_code == 200, response.text
    return response.json()["token"]


def make_posreq(store_name: str = "Toko Contoh") -> str:
    return json.dumps(
        {
            "schema_version": 1,
            "product": "POS Retail",
            "installation_id": str(uuid.uuid4()),
            "device_id": "b" * 64,
            "store_name": store_name,
            "requested_at": "2026-01-01T00:00:00+00:00",
        }
    )


def auth_headers(token: str) -> dict:
    return {"Cookie": f"billing_session={token}"}


def settle_notification(order_code: str, amount_idr: int) -> dict:
    status_code = "200"
    signature = hashlib.sha512(
        f"{order_code}{status_code}{amount_idr}{SERVER_KEY}".encode()
    ).hexdigest()
    return {
        "order_id": order_code,
        "status_code": status_code,
        "gross_amount": str(amount_idr),
        "signature_key": signature,
        "transaction_status": "settlement",
        "fraud_status": "accept",
        "transaction_id": "TX-123",
    }


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "environment": "test"}


def test_register_login_and_duplicate_email(client):
    token = register_and_login(client)
    assert token
    response = client.post(
        "/api/auth/register",
        json={"email": "toko@example.com", "password": "rahasia123"},
    )
    assert response.status_code == 400
    assert "sudah terdaftar" in response.json()["detail"]


def test_login_with_wrong_password_is_rejected(client):
    register_and_login(client)
    response = client.post(
        "/api/auth/login",
        json={"email": "toko@example.com", "password": "salah-banget"},
    )
    assert response.status_code == 401


def test_licenses_endpoint_requires_auth(client):
    assert client.get("/api/licenses/me").status_code == 401


def test_full_checkout_flow_issues_verifiable_license(client, tmp_path):
    token = register_and_login(client)
    headers = auth_headers(token)

    response = client.post(
        "/devices",
        files={"posreq": ("permintaan.posreq", make_posreq(), "application/json")},
        headers=headers,
    )
    assert response.status_code == 303, response.text

    devices = client.get("/dashboard", headers=headers)
    assert devices.status_code == 200

    response = client.post(
        "/api/checkout/create",
        json={"device_pk": 1, "plan_code": "monthly"},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    order = response.json()
    assert order["amount_idr"] == 99_000

    response = client.post(
        "/webhooks/payment/midtrans",
        json=settle_notification(order["order_code"], 99_000),
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "paid"

    licenses = client.get("/api/licenses/me", headers=headers)
    assert licenses.status_code == 200
    record = licenses.json()[0]
    assert record["status"] == "active"
    assert record["expires_at"] is not None

    download = client.get("/licenses/1/download", headers=headers)
    assert download.status_code == 200
    document = json.loads(download.text)
    assert document["payload"]["product"] == "POS Retail"
    assert document["payload"]["expires_at"] is not None

    license_path = tmp_path / "downloaded.poslic"
    license_path.write_text(download.text, encoding="utf-8")
    payload = LicenseService.verify_license_file(
        license_path,
        expected_installation_id=document["payload"]["installation_id"],
        expected_device_id=document["payload"]["device_id"],
        public_key_path=client.public_key_path,
    )
    assert payload["store_name"] == "Toko Contoh"


def test_webhook_rejects_invalid_signature(client):
    token = register_and_login(client)
    headers = auth_headers(token)
    client.post(
        "/devices",
        files={"posreq": ("permintaan.posreq", make_posreq(), "application/json")},
        headers=headers,
    )
    order = client.post(
        "/api/checkout/create",
        json={"device_pk": 1, "plan_code": "monthly"},
        headers=headers,
    ).json()

    notification = settle_notification(order["order_code"], 99_000)
    notification["signature_key"] = "0" * 128
    response = client.post("/webhooks/payment/midtrans", json=notification)
    assert response.status_code == 401

    licenses = client.get("/api/licenses/me", headers=headers).json()
    assert licenses[0]["status"] == "pending"


def test_webhook_rejects_amount_mismatch(client):
    token = register_and_login(client)
    headers = auth_headers(token)
    client.post(
        "/devices",
        files={"posreq": ("permintaan.posreq", make_posreq(), "application/json")},
        headers=headers,
    )
    order = client.post(
        "/api/checkout/create",
        json={"device_pk": 1, "plan_code": "monthly"},
        headers=headers,
    ).json()

    response = client.post(
        "/webhooks/payment/midtrans",
        json=settle_notification(order["order_code"], 1),
    )
    assert response.status_code == 400


def test_webhook_is_idempotent(client):
    token = register_and_login(client)
    headers = auth_headers(token)
    client.post(
        "/devices",
        files={"posreq": ("permintaan.posreq", make_posreq(), "application/json")},
        headers=headers,
    )
    order = client.post(
        "/api/checkout/create",
        json={"device_pk": 1, "plan_code": "monthly"},
        headers=headers,
    ).json()
    notification = settle_notification(order["order_code"], 99_000)

    first = client.post("/webhooks/payment/midtrans", json=notification)
    second = client.post("/webhooks/payment/midtrans", json=notification)
    assert first.status_code == 200
    assert first.json()["status"] == "paid"
    assert second.status_code == 200
    assert second.json()["status"] == "duplicate"

    licenses = client.get("/api/licenses/me", headers=headers).json()
    assert len(licenses) == 1
    assert licenses[0]["status"] == "active"


def test_renewal_extends_expiry_from_previous_period(client):
    token = register_and_login(client)
    headers = auth_headers(token)
    client.post(
        "/devices",
        files={"posreq": ("permintaan.posreq", make_posreq(), "application/json")},
        headers=headers,
    )
    order = client.post(
        "/api/checkout/create",
        json={"device_pk": 1, "plan_code": "monthly"},
        headers=headers,
    ).json()
    client.post(
        "/webhooks/payment/midtrans",
        json=settle_notification(order["order_code"], 99_000),
    )
    first_expiry = client.get("/api/licenses/me", headers=headers).json()[0][
        "expires_at"
    ]

    renewal = client.post(
        "/api/licenses/1/renew",
        json={"plan_code": "monthly"},
        headers=headers,
    )
    assert renewal.status_code == 200
    client.post(
        "/webhooks/payment/midtrans",
        json=settle_notification(renewal.json()["order_code"], 99_000),
    )

    licenses = client.get("/api/licenses/me", headers=headers).json()
    assert len(licenses) == 1
    assert licenses[0]["expires_at"] > first_expiry


def test_deactivate_license(client):
    token = register_and_login(client)
    headers = auth_headers(token)
    client.post(
        "/devices",
        files={"posreq": ("permintaan.posreq", make_posreq(), "application/json")},
        headers=headers,
    )
    order = client.post(
        "/api/checkout/create",
        json={"device_pk": 1, "plan_code": "monthly"},
        headers=headers,
    ).json()
    client.post(
        "/webhooks/payment/midtrans",
        json=settle_notification(order["order_code"], 99_000),
    )

    response = client.post("/api/licenses/1/deactivate", headers=headers)
    assert response.status_code == 200
    licenses = client.get("/api/licenses/me", headers=headers).json()
    assert licenses[0]["status"] == "revoked"


def test_lifetime_license_has_no_expiry_and_verifies(client, tmp_path):
    token = register_and_login(client)
    headers = auth_headers(token)
    client.post(
        "/devices",
        files={"posreq": ("permintaan.posreq", make_posreq(), "application/json")},
        headers=headers,
    )
    order = client.post(
        "/api/checkout/create",
        json={"device_pk": 1, "plan_code": "lifetime"},
        headers=headers,
    ).json()
    assert order["amount_idr"] == 2_990_000
    client.post(
        "/webhooks/payment/midtrans",
        json=settle_notification(order["order_code"], 2_990_000),
    )

    licenses = client.get("/api/licenses/me", headers=headers).json()
    assert licenses[0]["status"] == "active"
    assert licenses[0]["expires_at"] is None

    download = client.get("/licenses/1/download", headers=headers)
    document = json.loads(download.text)
    assert document["payload"]["expires_at"] is None
    license_path = tmp_path / "lifetime.poslic"
    license_path.write_text(download.text, encoding="utf-8")
    payload = LicenseService.verify_license_file(
        license_path,
        expected_installation_id=document["payload"]["installation_id"],
        expected_device_id=document["payload"]["device_id"],
        public_key_path=client.public_key_path,
    )
    assert payload["expires_at"] is None


def test_posreq_from_other_product_rejected(client):
    token = register_and_login(client)
    headers = auth_headers(token)
    bad_request = json.dumps(
        {
            "schema_version": 1,
            "product": "Aplikasi Lain",
            "installation_id": str(uuid.uuid4()),
            "device_id": "c" * 64,
            "store_name": "Toko",
        }
    )
    response = client.post(
        "/devices",
        files={"posreq": ("permintaan.posreq", bad_request, "application/json")},
        headers=headers,
    )
    assert response.status_code == 303
    assert "error=" in response.headers["location"]


def test_admin_issue_requires_admin_key(client):
    response = client.post(
        "/admin/licenses/issue",
        json={"admin_key": "wrong", "email": "x@example.com"},
    )
    assert response.status_code == 403


# ------------------------------------------------------ pos auto-activation


def bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_pos_register_returns_device_token(client):
    token = register_and_login(client)
    response = client.post(
        "/api/pos/register",
        json={"posreq": make_posreq()},
        headers=bearer(token),
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["device_token"]
    assert data["installation_id"]
    assert data["store_name"] == "Toko Contoh"


def test_pos_register_requires_auth(client):
    response = client.post("/api/pos/register", json={"posreq": make_posreq()})
    assert response.status_code == 401


def test_pos_license_poll_before_and_after_payment(client):
    token = register_and_login(client)
    device = client.post(
        "/api/pos/register",
        json={"posreq": make_posreq()},
        headers=bearer(token),
    ).json()
    device_headers = bearer(device["device_token"])

    # Sebelum device terikat lisensi: status none
    poll = client.get("/api/pos/license", headers=device_headers)
    assert poll.status_code == 200
    assert poll.json()["status"] == "none"
    assert poll.json()["document"] is None

    # Buat order + bayar memakai session cookie pelanggan
    cookie = auth_headers(token)
    order = client.post(
        "/api/checkout/create",
        json={"device_pk": device["device_pk"], "plan_code": "monthly"},
        headers=cookie,
    ).json()
    client.post(
        "/webhooks/payment/midtrans",
        json=settle_notification(order["order_code"], 99_000),
    )

    # Sekarang POS mendapat dokumen aktif
    poll = client.get("/api/pos/license", headers=device_headers)
    assert poll.status_code == 200
    body = poll.json()
    assert body["status"] == "active"
    assert body["document"]["payload"]["product"] == "POS Retail"
    assert body["document"]["payload"]["installation_id"] == (
        device["installation_id"]
    )


def test_pos_license_rejects_bad_device_token(client):
    response = client.get(
        "/api/pos/license", headers=bearer("token-yang-salah")
    )
    assert response.status_code == 401


def test_pos_license_document_is_verifiable(client, tmp_path):
    token = register_and_login(client)
    device = client.post(
        "/api/pos/register",
        json={"posreq": make_posreq()},
        headers=bearer(token),
    ).json()
    cookie = auth_headers(token)
    order = client.post(
        "/api/checkout/create",
        json={"device_pk": device["device_pk"], "plan_code": "monthly"},
        headers=cookie,
    ).json()
    client.post(
        "/webhooks/payment/midtrans",
        json=settle_notification(order["order_code"], 99_000),
    )

    document = client.get(
        "/api/pos/license", headers=bearer(device["device_token"])
    ).json()["document"]
    license_path = tmp_path / "auto.poslic"
    license_path.write_text(json.dumps(document), encoding="utf-8")
    payload = LicenseService.verify_license_file(
        license_path,
        expected_installation_id=document["payload"]["installation_id"],
        expected_device_id=document["payload"]["device_id"],
        public_key_path=client.public_key_path,
    )
    assert payload["store_name"] == "Toko Contoh"


def test_download_installer_missing_file_404(tmp_path, signing_keys):
    private_key, public_key = signing_keys
    settings = Settings(
        _env_file=None,
        app_env="test",
        database_url=f"sqlite:///{tmp_path / 'billing.db'}",
        license_private_key_path=private_key,
        license_private_key_passphrase="billing-test-pass",
        installer_path=tmp_path / "tidak-ada.exe",
    )
    app = create_app(settings)
    with TestClient(app, follow_redirects=False) as test_client:
        response = test_client.get("/download/installer")
    assert response.status_code == 404


def test_download_installer_serves_file(tmp_path, signing_keys):
    private_key, public_key = signing_keys
    installer = tmp_path / "POS-Setup.exe"
    installer.write_bytes(b"MZ-fake-installer")
    settings = Settings(
        _env_file=None,
        app_env="test",
        database_url=f"sqlite:///{tmp_path / 'billing.db'}",
        license_private_key_path=private_key,
        license_private_key_passphrase="billing-test-pass",
        installer_path=installer,
    )
    app = create_app(settings)
    with TestClient(app, follow_redirects=False) as test_client:
        response = test_client.get("/download/installer")
    assert response.status_code == 200
    assert response.content == b"MZ-fake-installer"
    assert "POS-Setup.exe" in response.headers["content-disposition"]

def _setup_pending_order(client):
    token = register_and_login(client)
    device = client.post(
        "/api/pos/register",
        json={"posreq": make_posreq()},
        headers=bearer(token),
    ).json()
    order = client.post(
        "/api/checkout/create",
        json={"device_pk": device["device_pk"], "plan_code": "monthly"},
        headers=auth_headers(token),
    ).json()
    assert order["status"] == "pending", order
    return token, device, order


def _gateway_status(order_code, *, transaction_status="settlement", gross_amount="99000", transaction_id="TX-POLL-1"):
    return {
        "order_id": order_code,
        "transaction_status": transaction_status,
        "transaction_id": transaction_id,
        "gross_amount": gross_amount,
        "status_code": "200",
    }


def test_pos_license_poll_triggers_gateway_verification(client, monkeypatch):
    """Polling POS menjadi pemicu: server tanya Midtrans, lisensi terbit."""
    _token, device, order = _setup_pending_order(client)

    calls = []

    def fake_get(url, **kwargs):
        calls.append(url)
        return httpx.Response(200, json=_gateway_status(order["order_code"]))

    monkeypatch.setattr(httpx, "get", fake_get)

    poll = client.get("/api/pos/license", headers=bearer(device["device_token"]))
    assert poll.status_code == 200
    body = poll.json()
    assert body["status"] == "active"
    assert body["document"]["payload"]["installation_id"] == (
        device["installation_id"]
    )
    assert len(calls) == 1
    assert order["order_code"] in calls[0]


def test_pos_license_poll_still_pending_when_gateway_fails(client, monkeypatch):
    """Gateway tidak terjangkau: polling tetap 200 dan tidak pernah 500."""
    _token, device, order = _setup_pending_order(client)

    def fake_get(url, **kwargs):
        raise httpx.ConnectError("gateway down")

    monkeypatch.setattr(httpx, "get", fake_get)

    poll = client.get("/api/pos/license", headers=bearer(device["device_token"]))
    assert poll.status_code == 200
    assert poll.json()["status"] == "pending"
    assert poll.json()["document"] is None


def test_pos_license_poll_throttles_gateway_calls(client, monkeypatch):
    """Lebih dari satu poll beruntun hanya menghasilkan satu panggilan gateway."""
    _token, device, order = _setup_pending_order(client)

    calls = []

    def fake_get(url, **kwargs):
        calls.append(url)
        return httpx.Response(
            200, json=_gateway_status(order["order_code"], transaction_status="pending")
        )

    monkeypatch.setattr(httpx, "get", fake_get)

    for _ in range(3):
        poll = client.get("/api/pos/license", headers=bearer(device["device_token"]))
        assert poll.status_code == 200
        assert poll.json()["status"] == "pending"

    assert len(calls) == 1


def test_order_page_shows_check_button_while_pending(client, monkeypatch):
    """Cabang pending + snap_token kini memuat tombol Periksa Status."""
    monkeypatch.setattr(
        server_license_service,
        "create_snap_transaction",
        lambda *args, **kwargs: {
            "token": "snap-token-abc",
            "redirect_url": "https://example.test/pay",
        },
    )
    token, _device, order = _setup_pending_order(client)

    page = client.get(
        f"/orders/{order['order_code']}", headers=auth_headers(token)
    )
    assert page.status_code == 200
    assert "Periksa Status Pembayaran" in page.text
    assert "snap-token-abc" in page.text


def test_order_page_renders_flash_message_from_query(client, monkeypatch):
    """Query status/message kini ditampilkan, bukan dibuang."""
    monkeypatch.setattr(
        server_license_service,
        "create_snap_transaction",
        lambda *args, **kwargs: {
            "token": "snap-token-abc",
            "redirect_url": "https://example.test/pay",
        },
    )
    token, _device, order = _setup_pending_order(client)

    page = client.get(
        f"/orders/{order['order_code']}?status=error&message=Nominal+tidak+cocok",
        headers=auth_headers(token),
    )
    assert page.status_code == 200
    assert "Nominal tidak cocok" in page.text


def test_order_check_url_encodes_error_message(client, monkeypatch):
    """Pesan error harus ter-encode; spasi mentah mematahkan Location header."""
    _token, _device, order = _setup_pending_order(client)

    def fake_get(url, **kwargs):
        return httpx.Response(
            200, json=_gateway_status(order["order_code"], gross_amount="1")
        )

    monkeypatch.setattr(httpx, "get", fake_get)

    response = client.post(
        f"/orders/{order['order_code']}/check", headers=auth_headers(_token)
    )
    assert response.status_code == 303
    location = response.headers["location"]
    assert location.startswith(
        f"/orders/{order['order_code']}?status=error&message="
    )
    assert " " not in location
    assert "%20" in location


def test_order_check_reports_paid(client, monkeypatch):
    """Tombol manual ikut memakai jalur verifikasi yang sama."""
    _token, _device, order = _setup_pending_order(client)

    monkeypatch.setattr(
        httpx,
        "get",
        lambda url, **kwargs: httpx.Response(
            200, json=_gateway_status(order["order_code"])
        ),
    )

    response = client.post(
        f"/orders/{order['order_code']}/check", headers=auth_headers(_token)
    )
    assert response.status_code == 303
    assert response.headers["location"].endswith("?status=paid")

    page = client.get(
        f"/orders/{order['order_code']}", headers=auth_headers(_token)
    )
    assert page.status_code == 200
    assert "Pembayaran diterima" in page.text


def test_midtrans_snap_js_url_follows_environment():
    """Snap.js harus selalu se-env dengan server key, bukan hardcoded."""
    sandbox = Settings(
        _env_file=None,
        midtrans_server_key="SB-Mid-server-x",
        midtrans_snap_client_key="Mid-client-y",
    )
    assert sandbox.midtrans_environment == "sandbox"
    assert sandbox.midtrans_snap_js_url.startswith("https://app.sandbox.")
    assert not sandbox.midtrans_snap_client_key_is_suspect

    production = Settings(
        _env_file=None,
        midtrans_server_key="Mid-server-x",
        midtrans_snap_client_key="Mid-client-y",
    )
    assert production.midtrans_environment == "production"
    assert production.midtrans_snap_js_url == "https://app.midtrans.com/snap/snap.js"


def test_client_key_with_mid_prefix_is_not_flagged():
    """Client key sandbox sah kini berawalan Mid-client-, tanpa SB-.

    Midtrans mengganti format key; menebak environment dari awalan
    client key menghasilkan peringatan palsu.
    """
    settings = Settings(
        _env_file=None,
        midtrans_server_key="SB-Mid-server-0LPpsNDisRJhbqmpHYWxcLkp",
        midtrans_snap_client_key="Mid-client-VjAcjTJvKMlj89rZ",
    )
    assert settings.midtrans_environment == "sandbox"
    assert not settings.midtrans_snap_client_key_is_suspect


def test_server_key_pasted_into_client_key_is_flagged():
    """Kesalahan paling umum: menempel Server Key ke kolom Client Key."""
    for bad in ("SB-Mid-server-0LPps", "Mid-server-abcdef"):
        settings = Settings(
            _env_file=None,
            midtrans_server_key="SB-Mid-server-x",
            midtrans_snap_client_key=bad,
        )
        assert settings.midtrans_snap_client_key_is_suspect, bad


def test_order_page_uses_environment_snap_js_url(client, monkeypatch):
    """Halaman order memuat Snap.js sesuai environment, bukan hardcoded."""
    monkeypatch.setattr(
        server_license_service,
        "create_snap_transaction",
        lambda *args, **kwargs: {
            "token": "snap-token-abc",
            "redirect_url": "https://example.test/pay",
        },
    )
    token, _device, order = _setup_pending_order(client)

    # Fixture memakai server key non-sandbox → environment production,
    # sehingga Snap.js production yang harus muncul (bukan sandbox).
    expected = client.app.state.settings.midtrans_snap_js_url
    assert expected == "https://app.midtrans.com/snap/snap.js"

    page = client.get(
        f"/orders/{order['order_code']}", headers=auth_headers(token)
    )
    assert page.status_code == 200
    assert expected in page.text
    assert "app.sandbox.midtrans.com" not in page.text


def test_simulated_va_number_is_stable_and_formatted():
    """VA simulasi 16 digit, deterministik per order, tampil per-4-digit."""
    va = simulated_va_number("POS-ABCDEF123456")
    assert len(va) == 16 and va.startswith("9876")
    assert va == simulated_va_number("POS-ABCDEF123456")
    assert va != simulated_va_number("POS-FFFFF123456")
    assert format_va_display(va) == " ".join(
        va[index : index + 4] for index in range(0, 16, 4)
    )


def test_order_page_shows_atm_simulasi_panel(client):
    """Halaman order pending menampilkan VA + tombol Saya Sudah Bayar."""
    token, _device, order = _setup_pending_order(client)

    page = client.get(
        f"/orders/{order['order_code']}", headers=auth_headers(token)
    )
    assert page.status_code == 200
    va = simulated_va_number(order["order_code"])
    assert format_va_display(va) in page.text
    assert "Saya Sudah Bayar" in page.text
    assert "simulasi-bayar" in page.text


def test_atm_simulasi_payment_issues_license(client):
    """Konfirmasi 'Saya Sudah Bayar' menerbitkan lisensi aktif."""
    token, device, order = _setup_pending_order(client)

    response = client.post(
        f"/orders/{order['order_code']}/simulasi-bayar",
        headers=auth_headers(token),
    )
    assert response.status_code == 303
    assert response.headers["location"].endswith("?status=paid")

    licenses = client.get("/api/licenses/me", headers=auth_headers(token))
    assert licenses.status_code == 200
    record = licenses.json()[0]
    assert record["status"] == "active"

    # POS polling ikut melihat lisensi aktif tanpa webhook gateway.
    poll = client.get("/api/pos/license", headers=bearer(device["device_token"]))
    assert poll.status_code == 200
    body = poll.json()
    assert body["status"] == "active"
    assert body["document"]["payload"]["installation_id"] == (
        device["installation_id"]
    )

    # Dokumen yang diunduh lolos verifikasi Ed25519 POS.
    download = client.get("/licenses/1/download", headers=auth_headers(token))
    assert download.status_code == 200
    document = json.loads(download.text)
    payload = LicenseService.verify_license_file(
        _write_poslic(client, download.text),
        expected_installation_id=document["payload"]["installation_id"],
        expected_device_id=document["payload"]["device_id"],
        public_key_path=client.public_key_path,
    )
    assert payload["store_name"] == "Toko Contoh"


def _write_poslic(client, text: str):
    path = client.public_key_path.parent / "atm-simulasi.poslic"
    path.write_text(text, encoding="utf-8")
    return path


def test_atm_simulasi_payment_is_idempotent(client):
    """Konfirmasi dua kali tetap sukses dan tidak menerbitkan lisensi ganda."""
    token, _device, order = _setup_pending_order(client)

    for _ in range(2):
        response = client.post(
            f"/orders/{order['order_code']}/simulasi-bayar",
            headers=auth_headers(token),
        )
        assert response.status_code == 303
        assert response.headers["location"].endswith("?status=paid")

    licenses = client.get("/api/licenses/me", headers=auth_headers(token))
    assert len(licenses.json()) == 1
    assert licenses.json()[0]["status"] == "active"


# --------------------------------------------- status dashboard POS (kartu)


def test_pos_status_public_returns_roadmap_and_plans(client):
    """Tanpa token: POS tetap menerima roadmap + daftar paket bulanan/tahunan."""
    response = client.get("/api/pos/status")
    assert response.status_code == 200
    data = response.json()
    assert data["subscription"] is None
    assert data["roadmap"], "roadmap tidak boleh kosong"
    assert {"title", "description", "eta"} <= set(data["roadmap"][0])
    codes = {plan["code"] for plan in data["plans"]}
    assert {"monthly", "yearly", "lifetime"} <= codes
    monthly = next(p for p in data["plans"] if p["code"] == "monthly")
    assert monthly["cycle"] == "monthly"
    assert monthly["duration_days"] == 30
    assert monthly["price_idr"] == 99_000
    yearly = next(p for p in data["plans"] if p["code"] == "yearly")
    assert yearly["cycle"] == "yearly"
    assert yearly["duration_days"] == 365


def test_pos_status_reports_subscription_after_payment(client):
    """Token device yang sah mengembalikan sisa masa berlaku langganan."""
    token = register_and_login(client)
    device = client.post(
        "/api/pos/register",
        json={"posreq": make_posreq()},
        headers=bearer(token),
    ).json()
    order = client.post(
        "/api/checkout/create",
        json={"device_pk": device["device_pk"], "plan_code": "monthly"},
        headers=auth_headers(token),
    ).json()
    client.post(
        "/webhooks/payment/midtrans",
        json=settle_notification(order["order_code"], 99_000),
    )

    data = client.get(
        "/api/pos/status", headers=bearer(device["device_token"])
    ).json()
    subscription = data["subscription"]
    assert subscription is not None
    assert subscription["activated"] is True
    assert subscription["plan"]["code"] == "monthly"
    assert subscription["plan"]["cycle"] == "monthly"
    assert subscription["plan"]["remaining_days"] in (29, 30)
    assert subscription["plan"]["remaining_text"].startswith("Sisa ")
    assert subscription["plan"]["expires_at"]
    assert data["roadmap"]


def test_pos_status_subscription_is_none_before_license_exists(client):
    token = register_and_login(client)
    device = client.post(
        "/api/pos/register",
        json={"posreq": make_posreq()},
        headers=bearer(token),
    ).json()

    data = client.get(
        "/api/pos/status", headers=bearer(device["device_token"])
    ).json()
    assert data["subscription"] is None
    assert data["roadmap"]


def test_pos_status_with_invalid_token_keeps_roadmap(client):
    data = client.get("/api/pos/status", headers=bearer("token-salah")).json()
    assert data["subscription"] is None
    assert data["roadmap"]
    assert data["plans"]


def test_roadmap_json_file_overrides_default(tmp_path, monkeypatch):
    """Daftar fitur berikutnya bisa diperbarui lewat roadmap.json tanpa kode."""
    from server.app import roadmap as roadmap_module

    override = tmp_path / "roadmap.json"
    override.write_text(
        json.dumps([{"title": "Fitur Baru", "description": "Dari file", "eta": "Q3"}]),
        encoding="utf-8",
    )
    monkeypatch.setattr(roadmap_module, "ROADMAP_FILE", override)
    items = roadmap_module.load_roadmap()
    assert [item["title"] for item in items] == ["Fitur Baru"]
    assert items[0]["eta"] == "Q3"

    override.write_text("bukan-json", encoding="utf-8")
    assert roadmap_module.load_roadmap() == roadmap_module.DEFAULT_ROADMAP
