"""End-to-end: unduh installer → aktivasi trial → daftar akun → registrasi
perangkat → checkout bulanan → bayar → lisensi terbit → aktivasi otomatis.

Alur nyata yang disimulasikan:
  1. Pelanggan mengunduh installer dari webserver.
  2. POS dijalankan (trial aktif), owner menyiapkan akun lokal.
  3. POS mendaftar & masuk ke akun webserver.
  4. POS mengirim .posreq → server mendaftarkan perangkat.
  5. Owner checkout paket bulanan di webserver.
  6. Pembayaran Midtrans (webhook settlement) diterima server.
  7. POS mempolling → menerima dokumen .poslic.
  8. POS memverifikasi & memasang lisensi → aplikasi aktif, trial berakhir.

Server billing dijalankan sungguhan (uvicorn) di background thread supaya
BillingClient (httpx) bisa benar-benar berbicara HTTP dengannya.
"""

import hashlib
import json
import socket
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
import uvicorn

from app.services.billing_client import BillingClient, BillingError
from app.services.license_service import (
    LicenseService,
    generate_license_keypair,
)
from app.services.trial_service import TrialService
from server.app.config import Settings
from server.app.main import create_app

SERVER_KEY = "test-server-key"
MONTHLY_PRICE = 99_000


# --------------------------------------------------------------- helpers


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


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
        "transaction_id": "TX-E2E-001",
    }


# ------------------------------------------------------------- fixtures


@pytest.fixture
def signing_keys(tmp_path):
    private_key = tmp_path / "billing-private.pem"
    public_key = tmp_path / "billing-public.pem"
    generate_license_keypair(private_key, public_key, "billing-test-pass")
    return private_key, public_key


@pytest.fixture
def live_server(tmp_path, signing_keys):
    """Jalankan uvicorn sungguhan di port bebas, yield (base_url, public_key)."""
    private_key, public_key = signing_keys
    installer = tmp_path / "AnjayRetailSoft.exe"
    installer.write_bytes(b"MZ-fake-installer-payload")
    settings = Settings(
        _env_file=None,
        app_env="test",
        database_url=f"sqlite:///{tmp_path / 'billing.db'}",
        license_private_key_path=private_key,
        license_private_key_passphrase="billing-test-pass",
        midtrans_server_key=SERVER_KEY,
        admin_api_key="test-admin-key",
        installer_path=installer,
    )
    app = create_app(settings)
    port = _free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    base_url = f"http://127.0.0.1:{port}"
    # Tunggu server siap menerima koneksi.
    deadline = time.time() + 10
    while time.time() < deadline:
        try:
            with httpx.Client(timeout=1) as probe:
                probe.get(f"{base_url}/health")
            break
        except httpx.HTTPError:
            time.sleep(0.1)
    else:
        raise RuntimeError("Server billing gagal start dalam 10 detik.")

    yield base_url, public_key

    server.should_exit = True
    thread.join(timeout=5)


@pytest.fixture
def pos_env(live_server):
    """Lingkungan POS: LicenseService + TrialService di direktori sementara."""
    _, public_key = live_server
    # data_dir dibuat unik per test lewat monkeypatch tmp_path dari live_server.
    # live_server memakai tmp_path yang sama; gunakan subdirektori.
    data_dir = public_key.parent / "pos-data"
    license_service = LicenseService(
        data_dir,
        device_id="a" * 64,
        public_key_path=public_key,
    )
    trial = TrialService(data_dir, duration=timedelta(minutes=2))
    return license_service, trial


# --------------------------------------------------------------- tests


def test_full_lifecycle_trial_to_paid_activation(live_server, pos_env):
    base_url, public_key = live_server
    license_service, trial = pos_env

    # ── 1. Unduh installer dari webserver ────────────────────────────────
    with httpx.Client(timeout=10) as http:
        download = http.get(f"{base_url}/download/installer")
    assert download.status_code == 200
    assert download.content == b"MZ-fake-installer-payload"

    # Simulasi file instalasi tersimpan di mesin pelanggan.
    installer_path = license_service.data_dir.parent / "AnjayRetailSoft.exe"
    installer_path.write_bytes(download.content)
    assert installer_path.stat().st_size > 0

    # ── 2. POS pertama kali dijalankan: lisensi belum ada, trial aktif ──
    licensed, _ = license_service.license_status()
    assert licensed is False

    trial_active, trial_msg = trial.status()
    assert trial_active is True
    assert "trial" in trial_msg.lower()

    # ── 3. Buat .posreq dari POS ─────────────────────────────────────────
    posreq_doc = license_service.request_document("Toko E2E")
    posreq_content = json.dumps(posreq_doc)
    assert posreq_doc["product"] == "POS Retail"
    assert posreq_doc["installation_id"]

    # ── 4. Daftar akun webserver + login + daftarkan perangkat ──────────
    billing = BillingClient(base_url)
    email = "owner@tokoe2e.example.com"
    password = "rahasia-e2e-123"
    billing.register(email, password, "Toko E2E")
    customer_token = billing.login(email, password)
    assert customer_token

    device_token = billing.register_device(posreq_content, customer_token)
    assert device_token

    # Server mengembalikan status "none" — belum ada lisensi terikat.
    poll = billing.poll_license(device_token)
    assert poll["status"] == "none"
    assert poll["document"] is None

    # ── 5. Owner checkout paket bulanan di webserver ────────────────────
    # /api/checkout/create memakai cookie session, bukan Bearer.
    cookie_headers = {"Cookie": f"billing_session={customer_token}"}
    with httpx.Client(timeout=10) as http:
        order_resp = http.post(
            f"{base_url}/api/checkout/create",
            json={"device_pk": 1, "plan_code": "monthly"},
            headers=cookie_headers,
        )
    assert order_resp.status_code == 200, order_resp.text
    order = order_resp.json()
    assert order["status"] == "pending"
    assert order["amount_idr"] == MONTHLY_PRICE

    # ── 6. Pembayaran Midtrans → webhook settlement ─────────────────────
    with httpx.Client(timeout=10) as http:
        webhook = http.post(
            f"{base_url}/webhooks/payment/midtrans",
            json=settle_notification(order["order_code"], MONTHLY_PRICE),
        )
    assert webhook.status_code == 200, webhook.text
    assert webhook.json()["status"] == "paid"

    # ── 7. POS polling → menerima dokumen lisensi aktif ─────────────────
    poll = billing.poll_license(device_token)
    assert poll["status"] == "active"
    document = poll["document"]
    assert document is not None
    assert document["payload"]["product"] == "POS Retail"
    assert document["payload"]["installation_id"] == (
        posreq_doc["installation_id"]
    )
    assert document["payload"]["device_id"] == "a" * 64
    assert document["payload"]["expires_at"] is not None

    # ── 8. POS verifikasi & pasang lisensi ──────────────────────────────
    store_name = license_service.activate_from_document(document)
    assert store_name == "Toko E2E"

    licensed, status_msg = license_service.license_status()
    assert licensed is True
    assert "Toko E2E" in status_msg

    # File .poslic benar-benar tersimpan di disk.
    assert license_service.license_path.is_file()
    saved = json.loads(
        license_service.license_path.read_text(encoding="utf-8")
    )
    assert saved["payload"]["store_name"] == "Toko E2E"

    # ── 9. Banner trial disembunyikan karena sudah berlisensi ───────────
    # UI hanya menampilkan banner trial bila NOT licensed.
    licensed, _ = license_service.license_status()
    assert licensed is True

    # ── 10. Webhook idempoten: notifikasi ulang tidak merusak ───────────
    with httpx.Client(timeout=10) as http:
        again = http.post(
            f"{base_url}/webhooks/payment/midtrans",
            json=settle_notification(order["order_code"], MONTHLY_PRICE),
        )
    assert again.status_code == 200
    assert again.json()["status"] == "duplicate"


def test_trial_expires_and_blocks_until_activated(pos_env):
    """Setelah trial habis, status berubah & aplikasi menolak masuk."""
    import json as _json

    license_service, trial = pos_env

    # Tulis state trial langsung: started_at 2 jam lalu (duration 2 menit).
    two_hours_ago = datetime.now(timezone.utc) - timedelta(hours=2)
    trial.data_dir.mkdir(parents=True, exist_ok=True)
    trial.state_path.write_text(
        _json.dumps(
            {
                "started_at": two_hours_ago.isoformat(),
                "last_seen_at": two_hours_ago.isoformat(),
            }
        ),
        encoding="utf-8",
    )

    trial_active, msg = trial.status()
    assert trial_active is False
    assert "berakhir" in msg.lower()

    licensed, _ = license_service.license_status()
    assert licensed is False


def test_activation_from_wrong_device_rejected(live_server, pos_env):
    """Lisensi untuk perangkat lain tidak bisa dipasang."""
    base_url, public_key = live_server
    license_service, _ = pos_env

    other_license = LicenseService(
        public_key.parent / "other-pos",
        device_id="b" * 64,
        public_key_path=public_key,
    )
    posreq = other_license.request_document("Toko Lain")
    billing = BillingClient(base_url)
    billing.register("lain@example.com", "password-lain-99", "Toko Lain")
    token = billing.login("lain@example.com", "password-lain-99")
    device_token = billing.register_device(json.dumps(posreq), token)

    with httpx.Client(timeout=10) as http:
        order = http.post(
            f"{base_url}/api/checkout/create",
            json={"device_pk": 1, "plan_code": "monthly"},
            headers={"Cookie": f"billing_session={token}"},
        ).json()
        http.post(
            f"{base_url}/webhooks/payment/midtrans",
            json=settle_notification(order["order_code"], MONTHLY_PRICE),
        )
    document = billing.poll_license(device_token)["document"]
    assert document is not None

    # Perangkat asli (device_id="a"*64, installation_id berbeda) mencoba
    # memasang lisensi milik perangkat lain → harus ditolak.
    with pytest.raises(Exception, match="POS lain|komputer lain"):
        license_service.activate_from_document(document)
