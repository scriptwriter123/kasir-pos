"""Driver E2E otomatis (dipanggil oleh scripts/e2e-otomatis.ps1).

Menjalankan sendiri, tanpa input manual:
  server billing live (uvicorn thread) -> unduh installer -> .posreq ->
  register/login -> daftarkan perangkat -> checkout -> webhook settlement
  Midtrans -> polling lisensi -> aktivasi Ed25519 di POS.

Contoh:
    .\\venv\\Scripts\\python.exe scripts\\e2e_otomatis.py --toko "Toko Saya"
    .\\venv\\Scripts\\python.exe scripts\\e2e_otomatis.py --paket yearly
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import socket
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
import uvicorn

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.services.billing_client import BillingClient  # noqa: E402
from app.services.license_service import (  # noqa: E402
    LicenseService,
    generate_license_keypair,
)
from app.services.trial_service import TrialService  # noqa: E402
from server.app.config import Settings  # noqa: E402
from server.app.main import create_app  # noqa: E402

SERVER_KEY = "e2e-otomatis-server-key"


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def settle_payload(order_code: str, amount_idr: int) -> dict:
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
        "transaction_id": "TX-E2E-OTOMATIS",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="E2E otomatis POS: server -> aktivasi")
    parser.add_argument("--base", default=str(PROJECT_ROOT / ".e2e-real"),
                        help="Folder jejak di PC (dihapus lalu dibuat baru)")
    parser.add_argument("--toko", default="Toko E2E Otomatis")
    parser.add_argument("--paket", default="monthly",
                        choices=["monthly", "yearly", "lifetime"])
    args = parser.parse_args()

    base = Path(args.base)
    pos_data = base / "pos-data"
    srv_data = base / "server-data"

    print("[1/8] Bersihkan jejak lama...", flush=True)
    shutil.rmtree(base, ignore_errors=True)
    pos_data.mkdir(parents=True, exist_ok=True)
    srv_data.mkdir(parents=True, exist_ok=True)

    print("[2/8] Siapkan kunci Ed25519 + server billing live...", flush=True)
    priv, pub = srv_data / "billing-private.pem", srv_data / "billing-public.pem"
    generate_license_keypair(priv, pub, "e2e-otomatis-pass-12345")

    installer = base / "AnjayRetailSoft.exe"
    installer.write_bytes(b"MZ-fake-installer-payload-e2e-otomatis")

    settings = Settings(
        _env_file=None, app_env="test",
        database_url=f"sqlite:///{srv_data / 'billing.db'}",
        license_private_key_path=priv,
        license_private_key_passphrase="e2e-otomatis-pass-12345",
        midtrans_server_key=SERVER_KEY,
        admin_api_key="e2e-admin",
        installer_path=installer,
    )
    port = free_port()
    server = uvicorn.Server(
        uvicorn.Config(create_app(settings), host="127.0.0.1",
                       port=port, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{port}"
    deadline = time.time() + 15
    while time.time() < deadline:
        try:
            httpx.get(f"{base_url}/health", timeout=1)
            break
        except httpx.HTTPError:
            time.sleep(0.1)
    else:
        print("GAGAL: server tidak start dalam 15 detik.")
        return 1
    print(f"        server: {base_url}", flush=True)

    try:
        print("[3/8] Unduh installer + buat .posreq...", flush=True)
        dl = httpx.get(f"{base_url}/download/installer", timeout=10)
        assert dl.status_code == 200, dl.text
        (base / "AnjayRetailSoft-downloaded.exe").write_bytes(dl.content)

        lic = LicenseService(pos_data, public_key_path=pub)
        trial = TrialService(pos_data)
        print(f"        trial: {trial.status()[1]}", flush=True)
        posreq = base / "permintaan-lisensi.posreq"
        posreq.write_text(
            json.dumps(lic.request_document(args.toko), ensure_ascii=False, indent=2),
            encoding="utf-8")

        print("[4/8] Daftar + login akun webserver...", flush=True)
        billing = BillingClient(base_url)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        email = f"owner-{stamp}@toko.example.com"
        billing.register(email, "rahasia-e2e-123", args.toko)
        customer_token = billing.login(email, "rahasia-e2e-123")

        print("[5/8] Daftarkan perangkat...", flush=True)
        device_token = billing.register_device(
            posreq.read_text(encoding="utf-8"), customer_token)
        (pos_data / "billing-device-token.txt").write_text(
            device_token + "\n", encoding="utf-8")

        print(f"[6/8] Checkout paket {args.paket} + webhook settlement...",
              flush=True)
        order = httpx.post(
            f"{base_url}/api/checkout/create",
            json={"device_pk": 1, "plan_code": args.paket},
            headers={"Cookie": f"billing_session={customer_token}"},
            timeout=10).json()
        print(f"        order {order['order_code']} Rp{order['amount_idr']:,}",
              flush=True)
        webhook = httpx.post(
            f"{base_url}/webhooks/payment/midtrans",
            json=settle_payload(order["order_code"], order["amount_idr"]),
            timeout=10).json()
        assert webhook["status"] == "paid", webhook
        print("        pembayaran: paid", flush=True)

        print("[7/8] Polling + aktivasi lisensi...", flush=True)
        poll = billing.poll_license(device_token)
        assert poll["status"] == "active" and poll["document"], poll
        doc = poll["document"]
        (base / f"{doc['payload']['license_id']}.poslic").write_text(
            json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
        store = lic.activate_from_document(doc)

        licensed, msg = lic.license_status()
        assert licensed, msg
        print(f"[8/8] AKTIF: {msg}", flush=True)
        print(f"      toko: {store} | paket: {args.paket}", flush=True)
    finally:
        server.should_exit = True
        thread.join(timeout=5)

    print(f"JEJAK: {base}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
