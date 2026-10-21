"""E2E NYATA di PC: server sungguhan + unduh installer + registrasi + bayar
+ aktivasi. Setiap langkah dicatat untuk diduplikasi manual.

Jalankan:
    .\\venv\\Scripts\\python.exe scripts\\e2e_real.py

Prasyarat:
    - Server billing MATI (script akan menjalankannya sendiri).
    - Port 8001 bebas.
"""

import hashlib
import json
import os
import socket
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

SERVER_KEY = "SB-Mid-server-0LPpsNDisRJhbqmpHYWxcLkp"
BASE_URL = "http://127.0.0.1:8001"

# Direktori data POS yang akan dipakai ( simulasi instalasi bersih )
POS_DATA = Path(os.getenv("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "POSApp" / "data"


def log(step: int, title: str, detail: str = ""):
    print(f"\n{'='*70}")
    print(f"  LANGKAH {step}: {title}")
    print(f"{'='*70}")
    if detail:
        print(detail)


def sub(text: str):
    print(f"  -> {text}")


def wait_for_server(url: str, timeout: float = 15) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with httpx.Client(timeout=2) as c:
                r = c.get(f"{url}/health")
                if r.status_code == 200:
                    return True
        except httpx.HTTPError:
            time.sleep(0.3)
    return False


def main():
    start_time = datetime.now(timezone.utc)

    # ═══════════════════════════════════════════════════════════════════════
    log(0, "PERSIAPAN — Hapus data lama supaya mulai dari nol", f"""
  direktori POS data : {POS_DATA}
  database server    : {PROJECT_ROOT}\\server\\data\\billing.db
  port               : 8001
""")

    # Matikan server lama SEBELUM hapus DB.
    # Hanya matikan proses uvicorn, JANGAN python.exe (bisa matikan script ini).
    sub("Mematikan server uvicorn lama (jika ada)...")
    current_pid = os.getpid()
    result = subprocess.run(
        ["wmic", "process", "where",
         "name='python.exe' and commandline like '%uvicorn%'",
         "get", "processid"],
        capture_output=True, text=True,
    )
    for line in result.stdout.splitlines():
        line = line.strip()
        if line.isdigit() and int(line) != current_pid:
            try:
                os.kill(int(line), 9)
                sub(f"  Server lama (PID {line}) dimatikan.")
            except OSError:
                pass
    time.sleep(1)

    # Hapus database server
    db_path = PROJECT_ROOT / "server" / "data" / "billing.db"
    if db_path.exists():
        db_path.unlink()
        sub(f"Database server lama dihapus: {db_path}")
    else:
        sub("Database server belum ada (akan dibuat baru).")

    # Hapus data POS
    if POS_DATA.exists():
        import shutil
        shutil.rmtree(POS_DATA, ignore_errors=True)
        sub(f"Data POS lama dihapus: {POS_DATA}")
    POS_DATA.mkdir(parents=True, exist_ok=True)
    sub(f"Data POS bersih dibuat: {POS_DATA}")

    # ═══════════════════════════════════════════════════════════════════════
    log(1, "JALANKAN SERVER BILLING (uvicorn di background)", f"""
  Perintah manual:
    cd {PROJECT_ROOT}
    .\\venv\\Scripts\\python.exe -m uvicorn server.app.main:app --host 127.0.0.1 --port 8001

  atau:
    Start-Process -FilePath ".\\venv\\Scripts\\python.exe" `
      -ArgumentList "-m","uvicorn","server.app.main:app","--host","127.0.0.1","--port","8001" `
      -WorkingDirectory "{PROJECT_ROOT}" -WindowStyle Hidden
""")

    # Baca .env server untuk tahu path private key
    server_env = {}
    env_file = PROJECT_ROOT / "server" / ".env"
    if env_file.is_file():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                server_env[k.strip()] = v.strip().strip('"').strip("'")

    private_key_path = server_env.get(
        "LICENSE_PRIVATE_KEY_PATH",
        r"C:\Users\ANJAY SOLUTION\AppData\Local\POSPublisher\license-signing-private.pem",
    )
    passphrase = server_env.get("LICENSE_PRIVATE_KEY_PASSPHRASE", "")
    midtrans_key = server_env.get("MIDTRANS_SERVER_KEY", SERVER_KEY)

    sub(f"Private key   : {private_key_path}")
    sub(f"Passphrase    : {'(isi)' if passphrase else '(KOSONG — aktivasi gagal!)'}")
    sub(f"Midtrans key  : {midtrans_key[:20]}...")

    server_proc = subprocess.Popen(
        [
            str(PROJECT_ROOT / "venv" / "Scripts" / "python.exe"),
            "-m", "uvicorn", "server.app.main:app",
            "--host", "127.0.0.1", "--port", "8001",
        ],
        cwd=str(PROJECT_ROOT),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    sub(f"Server PID: {server_proc.pid}")

    if not wait_for_server(BASE_URL):
        print("\n  [X] Server gagal start dalam 15 detik!")
        server_proc.terminate()
        sys.exit(1)
    sub("[OK] Server aktif di http://127.0.0.1:8001")

    try:
        run_flow(start_time, midtrans_key, passphrase, private_key_path)
    finally:
        sub("\nMenutup server...")
        server_proc.terminate()
        server_proc.wait(timeout=5)
        sub("Server dihentikan.")


def run_flow(start_time, midtrans_key, passphrase, private_key_path):
    from app.services.billing_client import BillingClient
    from app.services.license_service import LicenseService, generate_license_keypair
    from app.services.trial_service import TrialService

    email = f"owner{start_time.strftime('%H%M%S')}@tokoe2e.com"
    password = "rahasia-e2e-123"
    store_name = "Toko E2E Nyata"

    # ═══════════════════════════════════════════════════════════════════════
    log(2, "UNDUH INSTALLER dari webserver", f"""
  Perintah manual (browser):
    buka {BASE_URL}/download/installer
    -> simpan sebagai AnjayRetailSoft.exe

  Perintah manual (PowerShell):
    Invoke-WebRequest -Uri "{BASE_URL}/download/installer" `
      -OutFile "$env:USERPROFILE\\Downloads\\AnjayRetailSoft.exe"
""")

    with httpx.Client(timeout=30) as http:
        r = http.get(f"{BASE_URL}/download/installer")
    if r.status_code != 200:
        print(f"  [X] Gagal unduh: HTTP {r.status_code}")
        sys.exit(1)

    installer_path = POS_DATA.parent / "AnjayRetailSoft.exe"
    installer_path.write_bytes(r.content)
    sub(f"[OK] Installer diunduh: {installer_path} ({len(r.content):,} bytes)")
    sub("-> Untuk install manual: jalankan AnjayRetailSoft.exe (butuh admin)")
    sub("-> Script ini mensimulasikan POS yang sudah terinstall.")

    # ═══════════════════════════════════════════════════════════════════════
    log(3, "POS PERTAMA DIJALANKAN — trial aktif, belum berlisensi", f"""
  (Setelah install, buka aplikasi POS dari Start Menu.)
""")

    # Generate kunci lisensi sementara (untuk verifikasi lokal).
    # Di produksi, kunci publik sudah dibundel di installer.
    pub_key = POS_DATA / "test-public.pem"
    priv_key = POS_DATA / "test-private.pem"
    if not pub_key.exists():
        generate_license_keypair(priv_key, pub_key, "e2e-test-pass-12345")

    license_service = LicenseService(POS_DATA, device_id="e" * 64, public_key_path=pub_key)
    trial = TrialService(POS_DATA)

    licensed, status_msg = license_service.license_status()
    sub(f"Lisensi status : {'AKTIF' if licensed else 'BELUM ADA'} — {status_msg}")

    trial_active, trial_msg = trial.status()
    sub(f"Trial status   : {'AKTIF' if trial_active else 'HABIS'} — {trial_msg}")

    installation_id = license_service.installation_id()
    sub(f"Installation ID: {installation_id}")

    # ═══════════════════════════════════════════════════════════════════════
    log(4, "BUAT FILE .posreq (permintaan lisensi dari POS)", f"""
  Di aplikasi POS (manual):
    Menu Aktivasi -> "Buat Permintaan Lisensi" -> simpan permintaan.posreq
    atau otomatis saat aktivasi online.

  Isi .posreq:
    {json.dumps(license_service.request_document(store_name), indent=2)}
""")

    posreq_doc = license_service.request_document(store_name)
    posreq_content = json.dumps(posreq_doc)
    posreq_path = POS_DATA / "permintaan.posreq"
    posreq_path.write_text(posreq_content, encoding="utf-8")
    sub(f"[OK] File .posreq dibuat: {posreq_path}")

    # ═══════════════════════════════════════════════════════════════════════
    log(5, "DAFTAR AKUN di webserver (dari POS / browser)", f"""
  Dari POS (Menu Aktivasi -> Masuk / Daftar):
    Email    : {email}
    Password : {password}
    Toko     : {store_name}

  Atau dari browser:
    buka {BASE_URL}/register
""")

    billing = BillingClient(BASE_URL)
    billing.register(email, password, store_name)
    sub("[OK] Akun webserver dibuat.")

    customer_token = billing.login(email, password)
    sub(f"[OK] Login berhasil. Customer token: {customer_token[:20]}...")

    # ═══════════════════════════════════════════════════════════════════════
    log(6, "DAFTARKAN PERANGKAT (kirim .posreq ke server)", f"""
  Dari POS (otomatis saat aktivasi online):
    POST {BASE_URL}/api/pos/register
    Body: {{"posreq": "<isi .posreq>"}}
    Header: Authorization: Bearer <customer_token>
""")

    device_token = billing.register_device(posreq_content, customer_token)
    sub(f"[OK] Perangkat terdaftar. Device token: {device_token[:20]}...")

    poll = billing.poll_license(device_token)
    sub(f"Poll status sebelum bayar: {poll['status']} (document={poll['document']})")

    # ═══════════════════════════════════════════════════════════════════════
    log(7, "CHECKOUT PAKET BULANAN (owner order di webserver)", f"""
  Dari browser (setelah login):
    Buka {BASE_URL}/dashboard
    Pilih perangkat -> Paket Bulanan (Rp 99.000) -> "Aktifkan"

  Atau via API:
    POST {BASE_URL}/api/checkout/create
    Body: {{"device_pk": 1, "plan_code": "monthly"}}
    Cookie: billing_session=<customer_token>
""")

    cookie = {"Cookie": f"billing_session={customer_token}"}
    with httpx.Client(timeout=10) as http:
        order_resp = http.post(
            f"{BASE_URL}/api/checkout/create",
            json={"device_pk": 1, "plan_code": "monthly"},
            headers=cookie,
        )
    if order_resp.status_code != 200:
        print(f"  [X] Checkout gagal: {order_resp.text}")
        sys.exit(1)
    order = order_resp.json()
    sub(f"[OK] Order dibuat: {order['order_code']}")
    sub(f"  Status : {order['status']}")
    sub(f"  Nominal: Rp {order['amount_idr']:,}")
    sub(f"  Snap token: {order.get('snap_token', '(tidak ada)')}")

    # ═══════════════════════════════════════════════════════════════════════
    log(8, "PEMBAYARAN — webhook Midtrans settlement", f"""
  Di produksi nyata:
    - Buka {BASE_URL}/orders/{order['order_code']}
    - Klik "Bayar Sekarang" -> popup Snap muncul (QRIS/VA/e-wallet)
    - Bayar -> Midtrans kirim webhook otomatis ke server

  Untuk testing lokal (webhook publik tidak bisa diakses dari localhost),
  kirim notifikasi manual via API:
    POST {BASE_URL}/webhooks/payment/midtrans
    Body: (lihat di bawah)
""")

    status_code = "200"
    gross = str(order["amount_idr"])
    sig = hashlib.sha512(
        f"{order['order_code']}{status_code}{gross}{midtrans_key}".encode()
    ).hexdigest()
    notification = {
        "order_id": order["order_code"],
        "status_code": status_code,
        "gross_amount": gross,
        "signature_key": sig,
        "transaction_status": "settlement",
        "fraud_status": "accept",
        "transaction_id": f"TX-{start_time.strftime('%H%M%S')}",
    }
    sub(f"Payload webhook:\n    {json.dumps(notification, indent=4)}")

    with httpx.Client(timeout=10) as http:
        webhook_resp = http.post(
            f"{BASE_URL}/webhooks/payment/midtrans",
            json=notification,
        )
    if webhook_resp.status_code != 200:
        print(f"\n  [X] Webhook gagal: {webhook_resp.status_code} {webhook_resp.text}")
        print(f"  -> Cek LICENSE_PRIVATE_KEY_PASSPHRASE di server/.env")
        print(f"  -> Jika kosong, lisensi tidak bisa ditandatangani.")
    else:
        result = webhook_resp.json()
        sub(f"[OK] Webhook diterima: status={result['status']}")

    # ═══════════════════════════════════════════════════════════════════════
    log(9, "POS POLLING — terima dokumen lisensi", f"""
  Dari POS (otomatis setiap 10 detik):
    GET {BASE_URL}/api/pos/license
    Header: Authorization: Bearer <device_token>
""")

    poll = billing.poll_license(device_token)
    sub(f"Poll status: {poll['status']}")
    document = poll["document"]
    if document:
        payload = document["payload"]
        sub(f"  Product      : {payload['product']}")
        sub(f"  Store        : {payload['store_name']}")
        sub(f"  Expires at   : {payload['expires_at']}")
        sub(f"  Installation : {payload['installation_id']}")
    else:
        sub("  Document: None (lisensi belum terbit)")
        sub("  -> Kemungkinan LICENSE_PRIVATE_KEY_PASSPHRASE kosong.")
        sub("  -> Isi passphrase di server/.env lalu restart server & ulangi.")

    # ═══════════════════════════════════════════════════════════════════════
    log(10, "AKTIVASI — pasang lisensi di POS", f"""
  Dari POS (otomatis saat polling berhasil):
    LicenseService.activate_from_document(document)

  Atau manual:
    Simpan document sebagai license.poslic di {POS_DATA}
""")

    if document:
        try:
            store = license_service.activate_from_document(document)
            sub(f"[OK] Lisensi terpasang untuk: {store}")

            licensed, status_msg = license_service.license_status()
            sub(f"Status lisensi: {'AKTIF [OK]' if licensed else 'GAGAL'}")
            sub(f"Pesan: {status_msg}")

            saved = json.loads(license_service.license_path.read_text(encoding="utf-8"))
            sub(f"File license.poslic: {license_service.license_path}")
            sub(f"  Payload store_name: {saved['payload']['store_name']}")
        except Exception as exc:
            sub(f"[X] Aktivasi gagal: {exc}")
    else:
        sub("[X] Tidak ada dokumen untuk diaktivasi.")

    # ═══════════════════════════════════════════════════════════════════════
    log(11, "VERIFIKASI AKHIR", "")

    licensed, status_msg = license_service.license_status()
    sub(f"Lisensi aktif : {licensed}")
    sub(f"Status        : {status_msg}")

    trial_active, trial_msg = trial.status()
    sub(f"Trial (tidak relevan jika sudah berlisensi): {trial_active}")

    sub(f"\nDatabase server: {PROJECT_ROOT / 'server' / 'data' / 'billing.db'}")
    sub(f"Data POS       : {POS_DATA}")
    sub(f"Installer      : {POS_DATA.parent / 'AnjayRetailSoft.exe'}")

    print(f"\n{'='*70}")
    if licensed:
        print("  [OK] E2E SELESAI — APLIKASI AKTIF")
    else:
        print("  [!] E2E SELESAI — lisensi belum aktif (cek passphrase)")
    print(f"{'='*70}\n")


if __name__ == "__main__":
    main()
