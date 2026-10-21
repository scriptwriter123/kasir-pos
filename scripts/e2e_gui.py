"""Otomatisasi GUI nyata: klik + ketik beneran di jendela aplikasi via QTest.

Bukan koordinat mouse / screenshot — driver menekan QPushButton asli dan
mengetik di QLineEdit asli (QTest.mouseClick / QTest.keyClicks), lalu
menunggu sinyal Qt yang sesungguhnya (license_activated, login_success).

Alur yang dijalankan (tanpa sentuhan tangan):
  1. Trial diset HABIS -> aplikasi membuka JENDELA AKTIVASI (skenario nyata:
     PC yang trial-nya berakhir)
  2. Klik "Belum punya akun? Daftar di sini"
  3. Ketik nama toko, email, password, ulangi password (QTest beneran)
  4. Klik "Daftar & Aktivasi" -> worker daftar + polling (HTTP asli)
  5. (Di balik layar: checkout paket + webhook settlement Midtrans)
  6. Lisensi aktif -> jendela login muncul
  7. Ketik username + password OWNER -> klik "Login"
  8. MainWindow terbuka -> PASS

Contoh:
    .\\venv\\Scripts\\python.exe scripts\\e2e_gui.py --toko "Toko GUI"
    # headless: QT_QPA_PLATFORM=offscreen (tak terlihat, tapi diklik beneran)

CATATAN:
- Akun OWNER di-seed via service sebagai persiapan lingkungan.
- Verifikasi Ed25519 memakai kunci publik app yang DITUKAR SEMENTARA dengan
  kunci tes (backup + restore otomatis di finally — repo tidak berubah).
- Tidak ada dialog file yang dibuka, jadi tidak ada popup manual.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import socket
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

# PENTING: jangan import app.* sebelum SEMUA env diset (settings singleton
# dikonstruksi sekali saat import pertama; nilai .env menang bila env kosong).
import httpx  # noqa: E402
import uvicorn  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from server.app.config import Settings as ServerSettings  # noqa: E402
from server.app.main import create_app  # noqa: E402
from server.app.models import Customer, Device  # noqa: E402

SERVER_KEY = "e2e-gui-server-key"
SERVER_PASSPHRASE = "e2e-gui-pass-12345"


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
        "transaction_id": "TX-E2E-GUI",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Otomatisasi GUI POS (klik+ketik asli)")
    parser.add_argument("--base", default=str(PROJECT_ROOT / ".e2e-gui"))
    parser.add_argument("--toko", default="Toko GUI Otomatis")
    parser.add_argument("--paket", default="monthly",
                        choices=["monthly", "yearly", "lifetime"])
    parser.add_argument("--owner-user", default="guiowner")
    parser.add_argument("--owner-pass", default="gui-owner-123")
    parser.add_argument("--timeout", type=int, default=240,
                        help="Batas total detik")
    args = parser.parse_args()

    base = Path(args.base)
    pos_data = base / "pos-data"
    srv_data = base / "server-data"
    email = f"gui-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}@toko.example.com"
    web_password = "gui-web-123"

    # Env duluan, sebelum import app.* apa pun.
    os.environ["POS_DATA_DIR"] = str(pos_data)
    port = free_port()
    base_url = f"http://127.0.0.1:{port}"
    os.environ["billing_server_url"] = base_url
    shutil.rmtree(base, ignore_errors=True)
    pos_data.mkdir(parents=True, exist_ok=True)
    srv_data.mkdir(parents=True, exist_ok=True)

    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QPushButton

    from app.services.license_service import generate_license_keypair

    def log(msg: str) -> None:
        print(f"[GUI] {msg}", flush=True)

    priv, pub = srv_data / "billing-private.pem", srv_data / "billing-public.pem"
    generate_license_keypair(priv, pub, SERVER_PASSPHRASE)
    installer = base / "AnjayRetailSoft.exe"
    installer.write_bytes(b"MZ-fake-installer-payload-e2e-gui")

    srv_settings = ServerSettings(
        _env_file=None, app_env="test",
        database_url=f"sqlite:///{srv_data / 'billing.db'}",
        license_private_key_path=priv,
        license_private_key_passphrase=SERVER_PASSPHRASE,
        midtrans_server_key=SERVER_KEY,
        admin_api_key="e2e-admin",
        installer_path=installer,
    )
    srv_app = create_app(srv_settings)
    session_factory = srv_app.state.session_factory
    server = uvicorn.Server(uvicorn.Config(
        srv_app, host="127.0.0.1", port=port, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 15
    while time.time() < deadline:
        try:
            httpx.get(f"{base_url}/health", timeout=1)
            break
        except httpx.HTTPError:
            time.sleep(0.1)
    else:
        log("GAGAL: server tidak start dalam 15 detik.")
        server.should_exit = True
        thread.join(timeout=5)
        return 1
    log(f"server billing: {base_url}")

    from app.core.config import settings as pos_settings
    from app.core.database import get_session
    from app.core.migrations import upgrade_database
    from app.repositories.user_repository import UserRepository
    from app.services.owner_setup_service import OwnerSetupService
    from server.app.services import (
        license_service as srv_lic,
        payment_service as srv_pay,
    )
    from main import Application

    log(f"billing_server_url efektif: {pos_settings.billing_server_url}")
    assert str(pos_settings.billing_server_url) == base_url, (
        f"settings memakai URL basi {pos_settings.billing_server_url}; "
        "cek urutan env vs import!"
    )

    # Tukar kunci publik app sementara dengan kunci tes (restore di finally).
    bundled_key = PROJECT_ROOT / "app" / "core" / "license_public_key.pem"
    key_backup = base / "license_public_key.pem.bak"
    shutil.copy2(bundled_key, key_backup)
    shutil.copy2(pub, bundled_key)
    log("kunci publik app ditukar sementara dengan kunci tes")

    try:
        upgrade_database()
        session = get_session()
        OwnerSetupService(session, UserRepository(session)).create_owner(
            username=args.owner_user, full_name="Owner GUI",
            password=args.owner_pass)
        session.close()
        log(f"owner di-seed: {args.owner_user}")

        # Trial HABIS (8 hari lalu) -> layar aktivasi muncul.
        past = datetime.now(timezone.utc) - timedelta(days=8)
        (pos_data / "trial-state.json").write_text(
            json.dumps({"started_at": past.isoformat(),
                        "last_seen_at": past.isoformat()}),
            encoding="utf-8")

        # ---- boot aplikasi SUNGGUHAN ----
        app_obj = Application()
        lv = app_obj.license_view
        assert lv is not None and lv.isVisible(), "jendela aktivasi tidak muncul!"
        assert hasattr(lv, "online_button"), "bagian Aktivasi Online tidak ada!"
        log("jendela aktivasi tampil (belum berlisensi)")

        activated: list[bool] = []
        lv.license_activated.connect(lambda: activated.append(True))
        state: dict[str, object] = {"fail": None}

        def find_button(parent, text: str):
            for btn in parent.findChildren(QPushButton):
                if btn.text() == text:
                    return btn
            raise AssertionError(f"Tombol '{text}' tidak ketemu!")

        def type_text(widget, text: str, label: str) -> None:
            widget.clear()
            QTest.keyClicks(widget, text)
            if widget.text() != text:
                widget.setText(text)
                log(f"ketik {label}: fallback setText (layout keyboard)")
            else:
                log(f"ketik {label}: '{text}' (QTest)")

        def fail(msg: str) -> None:
            if state["fail"] is None:
                state["fail"] = msg
                print(f"[GUI] GAGAL: {msg}", flush=True)
                app_obj.qt.quit()

        def later(ms: int, fn) -> None:
            QTimer.singleShot(ms, fn)

        def watch(label_text: str, tag: str) -> None:
            if label_text != watch.last.get(tag):
                watch.last[tag] = label_text
                log(f"status [{tag}]: '{label_text}'")
        watch.last = {}  # type: ignore[attr-defined]

        def wait_until(cond, timeout_ms: int, ok, label: str,
                       poll_ms: int = 500) -> None:
            end = time.time() + timeout_ms / 1000

            def check():
                if state["fail"] is not None:
                    return
                try:
                    done = cond()
                except Exception as exc:
                    fail(f"{label}: {exc}")
                    return
                if done:
                    ok()
                elif time.time() > end:
                    fail(f"batas waktu: {label}")
                else:
                    later(poll_ms, check)

            later(poll_ms, check)

        def server_device_count() -> int:
            sess = session_factory()
            try:
                return sess.query(Device).count()
            finally:
                sess.close()

        def step_register_mode():
            log("klik 'Belum punya akun? Daftar di sini'")
            QTest.mouseClick(lv.mode_toggle, Qt.LeftButton)
            if not lv.confirm_input.isVisible():
                fail("mode daftar tidak terbuka")
                return
            step_fill_form()

        def step_fill_form():
            type_text(lv.store_name_input, args.toko, "nama toko")
            type_text(lv.email_input, email, "email")
            type_text(lv.password_input, web_password, "password web")
            type_text(lv.confirm_input, web_password, "ulangi password")
            log("klik 'Daftar & Aktivasi'")
            assert lv.online_button.text() == "Daftar & Aktivasi"
            QTest.mouseClick(lv.online_button, Qt.LeftButton)
            wait_until(lambda: poll_device_ready(), 30000,
                       step_checkout, "perangkat terdaftar di server")

        def poll_device_ready() -> bool:
            watch(lv.online_status.text(), "worker")
            return server_device_count() >= 1

        def step_checkout():
            log("checkout paket + webhook settlement (simulasi kasir bayar)")
            sess = session_factory()
            try:
                customer = sess.query(Customer).filter(
                    Customer.email == email).one()
                device = sess.query(Device).order_by(Device.id).first()
                order, _ = srv_lic.create_checkout(
                    sess, customer, device_pk=device.id,
                    plan_code=args.paket, settings=srv_settings)
                result = srv_pay.apply_midtrans_notification(
                    sess, srv_settings,
                    settle_payload(order.order_code, order.amount_idr))
                assert result["status"] == "paid", result
                log(f"order {order.order_code} lunas Rp{order.amount_idr:,}")
            finally:
                sess.close()
            wait_until(poll_activated, 60000,
                       step_login, "aktivasi via polling worker")

        def poll_activated() -> bool:
            if activated:
                return True
            try:
                watch(lv.online_status.text(), "worker")
            except Exception:
                pass  # jendela aktivasi sudah ditutup = hampir aktif
            return False

        def step_login():
            login = app_obj.login
            assert login.isVisible(), "jendela login tidak muncul!"
            assert login.login_panel.isVisible(), "panel login tidak tampil!"
            log("jendela login tampil -> ketik kredensial OWNER")
            type_text(login.username, args.owner_user, "username")
            type_text(login.password, args.owner_pass, "password")
            log("klik 'Login'")
            QTest.mouseClick(find_button(login, "Login"), Qt.LeftButton)
            wait_until(
                lambda: (app_obj.window is not None
                         and app_obj.window.isVisible()),
                30000, step_done, "MainWindow terbuka")

        def step_done():
            w = app_obj.window
            name = type(w).__name__
            user = getattr(getattr(w, "user", None), "username", "?")
            log(f"MainWindow terbuka: {name} (user: {user})")
            print("[GUI] PASS — aktivasi + login + main window "
                  "tanpa sentuhan tangan", flush=True)
            app_obj.qt.quit()

        QTimer.singleShot(int(args.timeout * 1000),
                          lambda: fail("batas total waktu habis"))
        later(500, step_register_mode)
        app_obj.run()
        return 1 if state["fail"] is not None else 0
    finally:
        shutil.copy2(key_backup, bundled_key)
        print("[GUI] kunci publik app dikembalikan.", flush=True)
        server.should_exit = True
        thread.join(timeout=5)
        print(f"[GUI] jejak: {base}", flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
