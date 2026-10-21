"""E2E GUI Master Data: tambah kategori + produk via form OWNER.

Alur:
  1. Unduh installer dari webserver
  2. Install senyap (Inno Setup)
  3. Bersihkan data POS + seed Store/master data TANPA produk contoh
  4. Jalankan POS.exe, setup OWNER, login OWNER
  5. Buka Master Data (kartu "Kelola Data")
  6. Tambah kategori baru via GUI
  7. Tambah beberapa produk via form (SKU, kategori, satuan, supplier,
     harga modal/jual, stok, harga spesial partai)
  8. Lanjut: buat KASIR, transaksi kasir dengan produk GUI, logout,
     login OWNER lagi, aktivasi, web payment

Jalankan:
    .\\venv\\Scripts\\python.exe scripts\\e2e_master_products.py
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import httpx
from PIL import ImageGrab
from pywinauto import Application, Desktop, keyboard

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BASE_URL = "http://127.0.0.1:8001"
STAMP = datetime.now().strftime("%Y%m%d_%H%M%S")
SHOT_DIR = PROJECT_ROOT / "e2e_shots" / STAMP
VIDEO_DIR = PROJECT_ROOT / "e2e_videos" / STAMP
INSTALL_DIR = Path(os.environ.get("TEMP", ".")) / f"pos_e2e_prod_{STAMP}"
POS_DATA = Path(os.environ["LOCALAPPDATA"]) / "POSApp" / "data"
FFMPEG = (
    Path(os.environ["LOCALAPPDATA"])
    / "ms-playwright"
    / "ffmpeg-1013"
    / "ffmpeg-win64.exe"
)

OWNER_USER = "owner"
OWNER_PASS = "Owner12345"
OWNER_NAME = "Pemilik Toko"
CASHIER_USER = "kasir01"
CASHIER_PASS = "Kasir12345"
CASHIER_NAME = "Budi Kasir"

# Kategori baru + produk yang diisi lewat form GUI (bukan seed).
NEW_CATEGORIES = ["Elektronik", "Alat Tulis"]

NEW_PRODUCTS = [
    {
        "sku": "GUI-KOP-001",
        "barcode": "8991002101010",
        "name": "Kopi ABC Sachet",
        "category": "Minuman",
        "unit": "Piece (pcs)",
        "supplier": "Distributor Minuman Demo (SUP-MINUMAN)",
        "purchase_price": 1500,
        "selling_price": 2500,
        "stock": 48,
        "min_stock": 10,
        "bulk_enabled": True,
        "bulk_threshold": 10,
        "bulk_special_price": 2200,
        "bulk_discount": 12,
    },
    {
        "sku": "GUI-MIE-001",
        "barcode": "8991002101027",
        "name": "Mie Sedap Goreng",
        "category": "Makanan Instan",
        "unit": "Piece (pcs)",
        "supplier": "Pemasok Pangan Demo (SUP-PANGAN)",
        "purchase_price": 2800,
        "selling_price": 3500,
        "stock": 100,
        "min_stock": 20,
        "bulk_enabled": True,
        "bulk_threshold": 12,
        "bulk_special_price": 3200,
        "bulk_discount": 9,
    },
    {
        "sku": "GUI-ALP-001",
        "barcode": "8991002101034",
        "name": "Alpukat Mentah",
        "category": "Produk Segar",
        "unit": "Kilogram (kg)",
        "supplier": "Pemasok Produk Segar Demo (SUP-SEGAR)",
        "purchase_price": 18000,
        "selling_price": 24000,
        "stock": 15,
        "min_stock": 3,
        "bulk_enabled": True,
        "bulk_threshold": 5,
        "bulk_special_price": 21000,
        "bulk_discount": 13,
    },
    {
        "sku": "GUI-PEN-001",
        "barcode": "8991002101041",
        "name": "Pulpen Standard AE7",
        "category": "Alat Tulis",
        "unit": "Piece (pcs)",
        "supplier": "Mitra Sembako Demo (SUP-SEMBAKO)",
        "purchase_price": 2200,
        "selling_price": 3500,
        "stock": 120,
        "min_stock": 24,
        "bulk_enabled": False,
    },
    {
        "sku": "GUI-KIP-001",
        "barcode": "8991002101058",
        "name": "Kipas Angin Mini USB",
        "category": "Elektronik",
        "unit": "Piece (pcs)",
        "supplier": "Tidak ditentukan",
        "purchase_price": 42000,
        "selling_price": 58000,
        "stock": 8,
        "min_stock": 2,
        "bulk_enabled": True,
        "bulk_threshold": 3,
        "bulk_special_price": 54000,
        "bulk_discount": 7,
    },
]

_shot_n = 0


def shot(title: str) -> Path:
    global _shot_n
    _shot_n += 1
    SHOT_DIR.mkdir(parents=True, exist_ok=True)
    path = SHOT_DIR / f"{_shot_n:02d}_{title.replace(' ', '_')[:50]}.png"
    img = ImageGrab.grab(all_screens=True)
    img.save(path)
    print(f"  [shot] {path.name}")
    return path


def wait(sec: float = 1.0):
    time.sleep(sec)


class ScreenRecorder:
    def __init__(self, out: Path):
        self.out = out
        self.proc: subprocess.Popen | None = None

    def start(self):
        VIDEO_DIR.mkdir(parents=True, exist_ok=True)
        if not FFMPEG.exists():
            print("  [video] ffmpeg tidak ditemukan, rekaman dilewati")
            return
        self.proc = subprocess.Popen(
            [
                str(FFMPEG),
                "-y",
                "-f", "gdigrab",
                "-framerate", "10",
                "-i", "desktop",
                "-c:v", "libx264",
                "-preset", "ultrafast",
                "-pix_fmt", "yuv420p",
                str(self.out),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        print(f"  [video] rekam -> {self.out.name}")

    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
            print(f"  [video] selesai -> {self.out.name}")


def ensure_server() -> bool:
    try:
        r = httpx.get(f"{BASE_URL}/health", timeout=3)
        return r.status_code == 200
    except httpx.HTTPError:
        return False


def start_server() -> subprocess.Popen:
    print("  Menjalankan server billing...")
    proc = subprocess.Popen(
        [
            str(PROJECT_ROOT / "venv" / "Scripts" / "python.exe"),
            "-m", "uvicorn", "server.app.main:app",
            "--host", "127.0.0.1", "--port", "8001",
        ],
        cwd=str(PROJECT_ROOT),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    for _ in range(40):
        if ensure_server():
            return proc
        time.sleep(0.5)
    raise RuntimeError("Server billing gagal start")


def download_installer() -> Path:
    print("[1] Unduh installer dari webserver...")
    SHOT_DIR.mkdir(parents=True, exist_ok=True)
    dest = SHOT_DIR / "AnjayRetailSoft.exe"
    with httpx.stream("GET", f"{BASE_URL}/download/installer", timeout=120) as r:
        r.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in r.iter_bytes():
                f.write(chunk)
    size_mb = dest.stat().st_size / 1024 / 1024
    print(f"  Terunduh: {dest.name} ({size_mb:.1f} MB)")
    shot("01_installer_terunduh")
    return dest


def install_silent(installer: Path) -> Path:
    print("[2] Install aplikasi POS...")
    if INSTALL_DIR.exists():
        shutil.rmtree(INSTALL_DIR, ignore_errors=True)
    INSTALL_DIR.mkdir(parents=True)
    exe = INSTALL_DIR / "POS.exe"
    try:
        cmd = [
            str(installer),
            "/VERYSILENT",
            "/SUPPRESSMSGBOXES",
            "/NORESTART",
            f"/DIR={INSTALL_DIR}",
        ]
        print(f"  coba silent install -> {INSTALL_DIR}")
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        print(f"  installer exit={proc.returncode}")
        if exe.exists():
            print(f"  POS.exe: {exe}")
            shot("02_hasil_install")
            return exe
    except Exception as exc:
        print(f"  silent install gagal: {exc}")
    dist = PROJECT_ROOT / "dist" / "POS"
    if not (dist / "POS.exe").exists():
        raise FileNotFoundError(f"Build POS tidak ditemukan di {dist}")
    print(f"  fallback: salin {dist} -> {INSTALL_DIR}")
    shutil.copytree(dist, INSTALL_DIR, dirs_exist_ok=True)
    if not exe.exists():
        raise FileNotFoundError("POS.exe tidak ditemukan")
    shot("02_hasil_install_dist")
    return exe


def fresh_pos_data():
    print("[3] Bersihkan data POS (simulasi instalasi baru)...")
    if POS_DATA.exists():
        shutil.rmtree(POS_DATA, ignore_errors=True)
    POS_DATA.mkdir(parents=True, exist_ok=True)
    print(f"  {POS_DATA}")


def seed_installed_db(include_products: bool = False):
    """Seed Store + master data (kategori/satuan/supplier) tanpa produk contoh."""
    label = "dengan produk" if include_products else "tanpa produk contoh"
    print(f"[3b] Seed database POS (Store + master data {label}, tanpa user)...")
    env = os.environ.copy()
    env["POS_DATA_DIR"] = str(POS_DATA)
    py = str(PROJECT_ROOT / "venv" / "Scripts" / "python.exe")
    subprocess.run(
        [py, str(PROJECT_ROOT / "scripts" / "init_db.py")],
        cwd=str(PROJECT_ROOT),
        env=env,
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    )
    seed_cmd = [py, str(PROJECT_ROOT / "scripts" / "seed.py"), "--no-users"]
    if not include_products:
        seed_cmd.append("--no-products")
    proc = subprocess.run(
        seed_cmd,
        cwd=str(PROJECT_ROOT),
        env=env,
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    )
    print(f"  {proc.stdout.strip()}")


def launch_pos(exe: Path) -> Application:
    print("[4] Jalankan POS.exe...")
    env = os.environ.copy()
    env["BILLING_SERVER_URL"] = BASE_URL
    env["APP_ENV"] = "development"
    proc = subprocess.Popen([str(exe)], cwd=str(exe.parent), env=env)
    print(f"  POS pid={proc.pid}")
    app = Application(backend="uia").connect(process=proc.pid, timeout=30)
    wait(6)
    shot("03_pos_dijalankan")
    return app


def top_window(app: Application, timeout=15):
    win = app.top_window()
    win.wait("exists", timeout=timeout)
    try:
        win.wait("visible", timeout=2)
    except Exception:
        pass
    return win


def click_button(win, text: str, timeout=5):
    btn = win.child_window(title=text, control_type="Button")
    btn.wait("exists", timeout=timeout)
    try:
        btn.wait("visible", timeout=2)
    except Exception:
        pass
    btn.click_input()
    wait(0.5)


def find_edit(win, hint: str, timeout=5):
    try:
        el = win.child_window(best_match=hint, control_type="Edit")
        el.wait("exists", timeout=2)
        return el
    except Exception:
        pass
    try:
        el = win.child_window(best_match=hint)
        el.wait("exists", timeout=1)
        if el.element_info.control_type == "Edit":
            return el
    except Exception:
        pass
    edits = [
        e
        for e in win.descendants(control_type="Edit")
        if e.is_visible() and e.is_enabled()
    ]
    order = {
        "UsernameEdit": 0,
        "Nama lengkapEdit": 1,
        "PasswordEdit": 2,
        "Ulangi passwordEdit": 3,
        "EmailEdit": 0,
    }
    if hint in order and len(edits) > order[hint]:
        return edits[order[hint]]
    if edits:
        return edits[0]
    raise TimeoutError(f"Edit untuk {hint!r} tidak ditemukan")


def set_edit(win, label: str, value: str, timeout=5):
    edit = find_edit(win, f"{label}Edit", timeout=timeout)
    try:
        edit.set_edit_text(value)
    except Exception:
        edit.click_input()
        edit.type_keys("^a")
        edit.type_keys(value, with_spaces=True)
    wait(0.2)


def dismiss_msgboxes(app: Application, timeout=5) -> bool:
    """Tutup QMessageBox modal Qt (top-level atau child).

    Strategi cepat per iterasi:
      A) top-level app window berjudul msgbox
      B) satu pass descendants(control_type="Window") per top window
      C) scan Desktop (cadangan, hanya kalau sisa waktu cukup)
    Kalau msgbox terlihat tapi gagal ditutup, retry sampai deadline.
    """
    closed = False
    deadline = time.time() + timeout
    known = frozenset(
        (
            "Akun OWNER dibuat",
            "Login gagal",
            "Tidak dapat membuat OWNER",
            "Password tidak cocok",
            "Pengguna ditambahkan",
            "Pengguna tidak dapat ditambahkan",
            "Transaksi berhasil",
            "Transaksi gagal",
            "Transaksi tidak dapat diselesaikan",
            "Shift belum dibuka",
            "Shift tidak dapat dibuka",
            "Laporan kasir tersimpan",
            "Gagal mencetak struk",
            "Produk tidak ditemukan",
            "Produk tersimpan",
            "Produk tidak dapat disimpan",
            "Produk tersimpan, tetapi aturan harga spesial gagal",
            "Kategori tersimpan",
            "Kategori tidak dapat disimpan",
            "Kategori belum diisi",
            "SKU wajib",
            "Nama wajib",
            "Kategori wajib",
            "Satuan wajib",
            "Harga jual belum valid",
            "Harga spesial belum valid",
            "Harga spesial tersimpan",
            "Harga spesial dihapus",
            "Pilih produk",
            "Stok ditambahkan",
            "Stok tidak dapat ditambahkan",
        )
    )

    def _try_close(w) -> bool:
        try:
            w.set_focus()
            wait(0.12)
        except Exception:
            pass
        # 1) tombol OK/Yes/Ya di dalam msgbox
        try:
            for b in w.descendants(control_type="Button"):
                try:
                    txt = (b.window_text() or "").strip()
                except Exception:
                    continue
                if txt in ("OK", "Ok", "Yes", "Ya"):
                    try:
                        b.click_input()
                        wait(0.4)
                        return True
                    except Exception:
                        continue
        except Exception:
            pass
        # 2) tombol X judul (native close = reject)
        try:
            xbtn = w.child_window(
                title_re="^(Close|Tutup)$", control_type="Button"
            )
            if xbtn.exists(timeout=0.2):
                xbtn.click_input()
                wait(0.4)
                return True
        except Exception:
            pass
        # 3) Enter pada dialog (default button = OK)
        try:
            w.type_keys("{ENTER}")
            wait(0.4)
            return True
        except Exception:
            pass
        return False

    while time.time() < deadline:
        progressed = False
        saw = False
        try:
            tops = list(app.windows())
        except Exception:
            tops = []

        # A) top-level window app berjudul msgbox
        for w in tops:
            try:
                if (w.window_text() or "") in known:
                    saw = True
                    if _try_close(w):
                        closed = True
                        progressed = True
                        break
            except Exception:
                continue
        if progressed:
            wait(0.3)
            continue

        # B) satu pass descendants per top window (cepat)
        for top in tops:
            try:
                children = top.descendants(control_type="Window")
            except Exception:
                continue
            for d in children:
                try:
                    if (d.window_text() or "") in known:
                        saw = True
                        if _try_close(d):
                            closed = True
                            progressed = True
                            break
                except Exception:
                    continue
            if progressed:
                break
        if progressed:
            wait(0.3)
            continue

        # C) scan Desktop berbasis judul (hanya kalau waktu cukup)
        if time.time() + 2.0 <= deadline:
            try:
                for w in Desktop(backend="uia").windows():
                    try:
                        if (w.window_text() or "") in known:
                            saw = True
                            if _try_close(w):
                                closed = True
                                progressed = True
                                break
                    except Exception:
                        continue
            except Exception:
                pass
        if progressed:
            wait(0.3)
            continue
        if saw:
            # terlihat tapi belum tertutup: retry sampai deadline
            wait(0.3)
            continue
        break
    return closed


def clear_msgboxes(app: Application):
    for _ in range(15):
        if not dismiss_msgboxes(app, timeout=0.6):
            return
        wait(0.2)


def dismiss_save_as(app: Application, timeout=5) -> bool:
    closed = False
    deadline = time.time() + timeout
    while time.time() < deadline:
        found = False
        try:
            for w in app.windows():
                try:
                    title = w.window_text() or ""
                except Exception:
                    continue
                if title not in ("Save As", "Simpan Sebagai"):
                    continue
                try:
                    w.set_focus()
                    wait(0.2)
                except Exception:
                    pass
                try:
                    cancel = w.child_window(
                        title_re="^(Cancel|Batal)$", control_type="Button"
                    )
                    if cancel.exists(timeout=1):
                        cancel.click_input()
                    else:
                        w.type_keys("{ESC}")
                except Exception:
                    try:
                        w.type_keys("{ESC}")
                    except Exception:
                        pass
                closed = True
                found = True
                wait(0.8)
                break
        except Exception:
            pass
        if not found:
            break
    return closed


def dismiss_all_blocking(app: Application, timeout=5):
    for _ in range(10):
        did = dismiss_save_as(app, timeout=0.6)
        did = dismiss_msgboxes(app, timeout=0.6) or did
        if not did:
            return
        wait(0.2)


def fill_int_dialog(app: Application, title: str, value: str, timeout=8, parent=None) -> bool:
    deadline = time.time() + timeout
    dlg = None
    while time.time() < deadline:
        try:
            for w in app.windows():
                try:
                    if w.window_text() == title:
                        dlg = w
                        break
                except Exception:
                    continue
        except Exception:
            pass
        if dlg is None and parent is not None:
            try:
                cand = parent.child_window(title=title, control_type="Window")
                if cand.exists(timeout=0.2):
                    dlg = cand
            except Exception:
                pass
        if dlg is None and parent is not None:
            try:
                for d in parent.descendants(control_type="Window"):
                    try:
                        if d.window_text() == title:
                            dlg = d
                            break
                    except Exception:
                        continue
            except Exception:
                pass
        if dlg is not None:
            break
        time.sleep(0.3)
    if dlg is None:
        print(f"  ! dialog {title!r} tidak muncul")
        return False
    try:
        dlg.set_focus()
        wait(0.2)
    except Exception:
        pass
    set_ok = False
    try:
        edit = dlg.child_window(control_type="Edit")
        if edit.exists(timeout=2):
            edit.click_input()
            wait(0.15)
            edit.type_keys("^a")
            edit.type_keys(value, with_spaces=False)
            set_ok = True
    except Exception as exc:
        print(f"  ! isi Edit dialog {title!r}: {exc}")
    if not set_ok:
        try:
            spin = dlg.child_window(control_type="Spinner")
            if spin.exists(timeout=1):
                try:
                    spin.iface_value.Value = int(value)
                    set_ok = True
                except Exception:
                    spin.click_input()
                    spin.type_keys("^a")
                    spin.type_keys(value, with_spaces=False)
                    set_ok = True
        except Exception:
            pass
    wait(0.2)
    shot(f"dialog_{title.replace(' ', '_')}")
    try:
        ok = dlg.child_window(title="OK", control_type="Button")
        if ok.exists(timeout=2):
            ok.click_input()
        else:
            dlg.type_keys("{ENTER}")
    except Exception:
        try:
            dlg.type_keys("{ENTER}")
        except Exception as exc:
            print(f"  ! tutup dialog {title!r}: {exc}")
            return False
    for _ in range(20):
        try:
            if not dlg.exists(timeout=0.2):
                break
        except Exception:
            break
        wait(0.2)
    wait(0.5)
    print(f"  dialog {title!r}: nilai={value} OK")
    return True


def set_spin_value(spinner, value) -> bool:
    """Set nilai QDoubleSpinBox/QSpinBox — keyboard dulu, ValuePattern cadangan.

    Qt kadang menerima tulisan ValuePattern (UIA readback benar) tapi
    widget tidak benar-benar berubah; input keyboard pasti masuk ke
    QAbstractSpinBox. Verifikasi selalu via iface_value.
    """
    target = float(value)
    text = str(int(target)) if target == int(target) else str(target)

    def _read():
        try:
            return float(spinner.iface_value.Value)
        except Exception:
            return None

    # 1) keyboard: click -> select-all -> ketik -> TAB commit.
    #    JANGAN pakai ENTER: di QDialog Qt, Enter yang tidak di-consume
    #    QSpinBox memicu tombol default (Save) sehingga dialog tertutup
    #    di tengah pengisian. TAB membuat focus-out -> editingFinished.
    for attempt in (1, 2):
        try:
            spinner.set_focus()
            wait(0.1)
            spinner.click_input()
            wait(0.15)
            spinner.type_keys("^a")
            spinner.type_keys(text, with_spaces=False)
            wait(0.1)
            spinner.type_keys("{TAB}")
            wait(0.3)
            got = _read()
            if got is not None and abs(got - target) < 0.01:
                return True
            print(f"  ! spin {label_hint(spinner)} a{attempt}: got={got} target={target}")
        except Exception as exc:
            print(f"  ! spin keyboard a{attempt}: {exc}")
    # 2) ValuePattern fallback + konfirmasi ulang
    try:
        spinner.iface_value.Value = target
        wait(0.25)
        got = _read()
        if got is not None and abs(got - target) < 0.01:
            return True
    except Exception:
        pass
    print(
        f"  ! spinner tidak terkonfirmasi "
        f"(target={target}, got={_read()})"
    )
    return False


def label_hint(spinner) -> str:
    try:
        return spinner.element_info.name or "?"
    except Exception:
        return "?"


def select_combo_text(combo, text: str) -> None:
    try:
        combo.select(text)
        wait(0.2)
        return
    except Exception:
        pass
    try:
        combo.expand()
        wait(0.3)
        try:
            combo.select(text)
            wait(0.2)
            return
        except Exception:
            pass
        # fallback: klik item via descendants ListItem
        for item in combo.descendants(control_type="ListItem"):
            if text.lower() in (item.window_text() or "").lower():
                item.click_input()
                wait(0.2)
                return
    except Exception:
        pass
    # keyboard fallback — hanya kalau dropdown benar-benar terbuka,
    # supaya ENTER tidak bocor ke tombol default dialog
    try:
        combo.click_input()
        wait(0.3)
        items = combo.descendants(control_type="ListItem")
        if not items:
            print(f"  ! combo dropdown tidak terbuka untuk {text!r}")
            return
        keyboard.send_keys(text)
        wait(0.2)
        keyboard.send_keys("{ENTER}")
        wait(0.2)
    except Exception as exc:
        print(f"  ! combo keyboard fallback {text!r}: {exc}")


def fill_product_form(app: Application, parent, product: dict) -> bool:
    """Isi ProductFormDialog 'Tambah Produk' lalu klik Save.

    Urutan widget di form (creation order):
      Edits: SKU, Barcode, Nama
      Combos: Kategori, Satuan, Supplier
      Spinners: Harga modal, Harga jual, Stok awal, Batas minimum,
                (bulk) Threshold, Harga spesial, Potongan %
      Checkbox: Aktifkan harga spesial partai
      Buttons: Save, Cancel
    """
    dlg = None
    deadline = time.time() + 8
    while time.time() < deadline:
        try:
            for w in app.windows():
                try:
                    if w.window_text() == "Tambah Produk":
                        dlg = w
                        break
                except Exception:
                    continue
        except Exception:
            pass
        if dlg is None and parent is not None:
            try:
                cand = parent.child_window(
                    title="Tambah Produk", control_type="Window"
                )
                if cand.exists(timeout=0.2):
                    dlg = cand
            except Exception:
                pass
            if dlg is None:
                try:
                    for d in parent.descendants(control_type="Window"):
                        try:
                            if d.window_text() == "Tambah Produk":
                                dlg = d
                                break
                        except Exception:
                            continue
                except Exception:
                    pass
        if dlg is not None:
            break
        time.sleep(0.3)
    if dlg is None:
        print("  ! dialog Tambah Produk tidak muncul")
        return False
    try:
        dlg.set_focus()
        wait(0.3)
    except Exception:
        pass
    shot(f"dialog_{product['sku']}_buka")

    # ── Line edits (SKU, Barcode, Nama) ──────────────────────────
    edits = [
        e
        for e in dlg.descendants(control_type="Edit")
        if e.is_visible() and e.is_enabled()
    ]
    # Edit di dalam SpinBox juga muncul; 3 line edit form ada di awal
    # urutan creation. Filter: Edit yang bukan child Spinner.
    pure_edits = []
    for e in edits:
        try:
            # lewati 2 parent; kalau ketemu Spinner lewati edit ini
            p = e.element_info.parent()
            is_spinner_child = False
            for _ in range(2):
                if p is None:
                    break
                ct = getattr(p, "control_type", "") or ""
                if "Spinner" in str(ct):
                    is_spinner_child = True
                    break
                p = p.parent() if hasattr(p, "parent") else None
            if not is_spinner_child:
                pure_edits.append(e)
        except Exception:
            pure_edits.append(e)
    if len(pure_edits) < 3:
        pure_edits = edits[:3]
    for idx, key in enumerate(("sku", "barcode", "name")):
        if idx >= len(pure_edits):
            break
        try:
            pure_edits[idx].click_input()
            wait(0.1)
            pure_edits[idx].type_keys("^a")
            val = str(product.get(key, "") or "")
            if val:
                pure_edits[idx].type_keys(val, with_spaces=True)
            wait(0.1)
        except Exception as exc:
            print(f"  ! edit {key}: {exc}")

    # ── Combos (Kategori, Satuan, Supplier) ──────────────────────
    combos = [
        c
        for c in dlg.descendants(control_type="ComboBox")
        if c.is_visible() and c.is_enabled()
    ]
    combo_values = [
        product.get("category"),
        product.get("unit"),
        product.get("supplier"),
    ]
    for idx, val in enumerate(combo_values):
        if not val or idx >= len(combos):
            continue
        select_combo_text(combos[idx], val)

    # ── Spinners: harga modal, jual, stok, min ───────────────────
    # Qt/PySide6 tidak selalu mengekspos QDoubleSpinBox sebagai
    # control_type="Spinner" — fallback: Edit child SpinBox berurutan
    # (index 0-2 = SKU/barcode/nama, 3-6 = harga modal/jual/stok/min).
    def _fmt(v) -> str:
        f = float(v)
        return str(int(f)) if f == int(f) else str(f)

    def _digits(txt: str) -> str:
        return "".join(c for c in (txt or "") if c.isdigit())

    def _num_ok(txt, want) -> bool:
        """Cocokkan teks spinbox dengan target integer.

        "1,500"/"1.500"/"1500" == 1500;  "12.00" == 12 (desimal trailing).
        """
        d = _digits(str(txt or ""))
        if not d:
            return False
        t = str(abs(int(float(want))))
        if d == t:
            return True
        # trailing nol desimal: "12.00" -> "1200" untuk target 12
        return d.startswith(t) and set(d[len(t):]) <= {"0"}

    def _set_number(idx: int, value, label: str) -> bool:
        # a) Edit child SpinBox: urutan creation = index idx
        #    (0-2 SKU/barcode/nama, 3.. angka). KETIK + TAB — TAB
        #    memicu focus-out/editingFinished tanpa memicu tombol
        #    default dialog (ENTER bisa memicu Save di QDialog Qt).
        try:
            all_edits = [
                e
                for e in dlg.descendants(control_type="Edit")
                if e.is_visible()
            ]
            if idx < len(all_edits):
                ed = all_edits[idx]
                ed.set_focus()
                wait(0.1)
                ed.click_input()
                wait(0.1)
                ed.type_keys("^a")
                ed.type_keys(_fmt(value), with_spaces=False)
                wait(0.1)
                ed.type_keys("{TAB}")
                wait(0.25)
                # baca ulang segar (elemen bisa berubah setelah focus-out)
                all_edits = [
                    e
                    for e in dlg.descendants(control_type="Edit")
                    if e.is_visible()
                ]
                if idx < len(all_edits):
                    txt = all_edits[idx].window_text() or ""
                    if _num_ok(txt, value):
                        return True
                    print(f"  ! {label}: teks {txt!r} != {value}")
            else:
                print(f"  ! edit index {idx} tidak ada ({len(all_edits)} edit)")
        except Exception as exc:
            print(f"  ! edit {label}: {exc}")
            return False  # dialog kemungkinan sudah tertutup — hentikan
        # b) ValuePattern spinner cadangan (spin_i = idx-3), tanpa ENTER
        try:
            spins = [
                s
                for s in dlg.descendants(control_type="Spinner")
                if s.is_visible()
            ]
            spin_i = idx - 3
            if 0 <= spin_i < len(spins) and set_spin_value(spins[spin_i], value):
                return True
        except Exception:
            pass
        print(f"  ! {label} = {value} gagal diverifikasi")
        return False

    def _set_all_numbers() -> bool:
        ok = True
        for i, (key, val) in enumerate(
            (
                ("purchase_price", product["purchase_price"]),
                ("selling_price", product["selling_price"]),
                ("stock", product["stock"]),
                ("min_stock", product["min_stock"]),
            ),
            start=3,  # index Edit: 0=SKU,1=Barcode,2=Nama,3..=spinbox
        ):
            if not _set_number(i, val, key):
                ok = False
        if product.get("bulk_enabled"):
            try:
                cb = dlg.child_window(
                    title="Aktifkan harga spesial partai",
                    control_type="CheckBox",
                )
                cb.wait("exists", timeout=2)
                if not cb.get_toggle_state():
                    cb.toggle()
                    wait(0.5)
                # threshold -> discount -> harga spesial TERAKHIR:
                # edit harga spesial mengubah mode ke PRICE sehingga
                # nilai tidak dihitung ulang Qt dari persen.
                bulk_map = [
                    (7, product.get("bulk_threshold"), "bulk_threshold"),
                    (9, product.get("bulk_discount"), "bulk_discount"),
                    (8, product.get("bulk_special_price"), "bulk_special_price"),
                ]
                for idx, val, label in bulk_map:
                    if val is None:
                        continue
                    if not _set_number(idx, val, label):
                        ok = False
            except Exception as exc:
                print(f"  ! bulk pricing: {exc}")
                ok = False
        return ok

    def _spin_values():
        """Baca teks edit angka (index Edit 3..9 = modal,jual,stok,min,
        threshold,spesial,potongan). Teks lebih andal dari iface_value."""
        vals = []
        try:
            all_edits = [
                e
                for e in dlg.descendants(control_type="Edit")
                if e.is_visible()
            ]
            for e in all_edits[3:]:
                vals.append(e.window_text() or "")
        except Exception:
            pass
        return vals

    def _verify_numbers() -> bool:
        need = {
            3: float(product["purchase_price"]),
            4: float(product["selling_price"]),
            5: float(product["stock"]),
            6: float(product["min_stock"]),
        }
        if product.get("bulk_enabled"):
            need[7] = float(product["bulk_threshold"])
            need[8] = float(product.get("bulk_special_price") or 0)
            need[9] = None  # discount bisa di-recompute Qt — cukup > 0
        vals = _spin_values()
        print(f"  edit angka readback: {vals}")
        ok = True
        for i, want in need.items():
            pos = i - 3
            txt = vals[pos] if pos < len(vals) else None
            if txt is None:
                ok = False
                continue
            if want is None:
                if not _digits(txt) or int(_digits(txt)) <= 0:
                    ok = False
            elif not _num_ok(txt, want):
                ok = False
        return ok

    def _cancel_form():
        try:
            cancel = dlg.child_window(
                title_re="^(Cancel|Batal)$", control_type="Button"
            )
            if cancel.exists(timeout=1):
                cancel.click_input()
            else:
                dlg.type_keys("{ESC}")
        except Exception:
            pass
        wait(0.5)
        dismiss_msgboxes(app, timeout=2)

    if not _set_all_numbers():
        print("  ! sebagian angka gagal diset — verifikasi dulu")
    if not _verify_numbers():
        print("  ! readback spinner belum cocok — ulangi sekali")
        _set_all_numbers()
        if not _verify_numbers():
            print(f"  ! angka form tidak sesuai target untuk {product['sku']}")
            _cancel_form()
            return False

    shot(f"form_{product['sku']}")

    # ── Save + verifikasi: dialog tertutup ATAU msgbox "tersimpan"
    def _saved_msgbox() -> bool:
        try:
            for w in app.windows():
                try:
                    if w.window_text() == "Produk tersimpan":
                        return True
                except Exception:
                    continue
        except Exception:
            pass
        return False

    save_ok = False
    for attempt in (1, 2):
        try:
            dlg.set_focus()
            wait(0.2)
            save = dlg.child_window(
                title_re="^(Save|Simpan)$", control_type="Button"
            )
            save.wait("exists", timeout=3)
            save.set_focus()
            save.click_input()
        except Exception as exc:
            print(f"  ! tombol Save (attempt {attempt}): {exc}")
            try:
                dlg.set_focus()
                dlg.type_keys("{ENTER}")
            except Exception:
                return False
        # tunggu: dialog hilang ATAU msgbox "Produk tersimpan" muncul
        # (wrapper dialog kadang stale setelah accept -> msgbox jadi penanda)
        closed = False
        for _ in range(15):
            try:
                if not dlg.exists(timeout=0.2):
                    closed = True
                    break
            except Exception:
                closed = True
                break
            if _saved_msgbox():
                closed = True
                break
            wait(0.2)
        if closed:
            save_ok = True
            break
        # masih terbuka = validasi gagal: tutup warning, ulangi
        print(f"  ! Save attempt {attempt}: dialog masih terbuka (validasi?)")
        try:
            titles = [w.window_text() for w in app.windows()]
            print(f"    windows: {titles}")
        except Exception:
            pass
        shot(f"save_gagal_{product['sku']}_a{attempt}")
        dismiss_msgboxes(app, timeout=3)
        wait(0.5)
    if not save_ok:
        _cancel_form()
        print(f"  ! produk {product['sku']} TIDAK tersimpan")
        return False
    wait(0.8)
    # tutup msgbox "Produk tersimpan"
    dismiss_msgboxes(app, timeout=4)
    shot(f"tersimpan_{product['sku']}")
    print(f"  produk {product['sku']} tersimpan")
    return True


def add_categories_via_gui(app: Application, win, categories: list[str]):
    print("[7] Tambah kategori baru via Master Data...")
    click_button(win, "Tambah Kategori", timeout=5)
    wait(1.5)
    shot("09_dialog_tambah_kategori")
    dlg = None
    deadline = time.time() + 6
    while time.time() < deadline:
        try:
            for w in app.windows():
                try:
                    if w.window_text() == "Tambah Kategori":
                        dlg = w
                        break
                except Exception:
                    continue
        except Exception:
            pass
        if dlg is None:
            try:
                cand = win.child_window(
                    title="Tambah Kategori", control_type="Window"
                )
                if cand.exists(timeout=0.2):
                    dlg = cand
            except Exception:
                pass
        if dlg is not None:
            break
        time.sleep(0.3)
    if dlg is None:
        raise RuntimeError("Dialog Tambah Kategori tidak muncul")
    dlg.set_focus()
    wait(0.3)
    edits = [
        e
        for e in dlg.descendants(control_type="Edit")
        if e.is_visible() and e.is_enabled()
    ]
    for idx, name in enumerate(categories):
        if idx >= len(edits):
            break
        edits[idx].click_input()
        wait(0.1)
        edits[idx].type_keys("^a")
        edits[idx].type_keys(name, with_spaces=True)
        wait(0.1)
    shot("10_kategori_terisi")
    try:
        save = dlg.child_window(
            title_re="^(Save|Simpan)$", control_type="Button"
        )
        save.wait("exists", timeout=3)
        save.click_input()
    except Exception:
        dlg.type_keys("{ENTER}")
    for _ in range(20):
        try:
            if not dlg.exists(timeout=0.2):
                break
        except Exception:
            break
        wait(0.2)
    wait(0.8)
    dismiss_msgboxes(app, timeout=4)
    shot("11_kategori_tersimpan")
    print(f"  kategori ditambahkan: {', '.join(categories)}")


def add_products_via_gui(app: Application, win, products: list[dict]):
    for i, product in enumerate(products, 1):
        print(f"[8.{i}] Tambah produk {product['sku']}...")
        win = top_window(app)
        # pastikan di Master Data (tombol Tambah Produk ada)
        try:
            add_btn = win.child_window(
                title="Tambah Produk", control_type="Button"
            )
            if not add_btn.exists(timeout=2):
                raise RuntimeError("tidak di Master Data")
        except Exception:
            click_button(win, "Kelola Data", timeout=5)
            wait(2)
            win = top_window(app)
        click_button(win, "Tambah Produk", timeout=5)
        wait(1.5)
        if not fill_product_form(app, win, product):
            raise RuntimeError(f"Gagal isi form produk {product['sku']}")
        clear_msgboxes(app)
    shot("12_semua_produk_masuk")


def count_products_via_gui(win) -> int:
    try:
        tables = [
            t
            for t in win.descendants(control_type="Table")
            if t.is_visible()
        ]
        if not tables:
            return 0
        rows = max(
            (len(t.descendants(control_type="DataItem")) for t in tables),
            default=0,
        )
        return rows
    except Exception:
        return 0


def run_desktop_flow(app: Application):
    win = top_window(app)
    print(f"  Window: {win.window_text()}")

    # ── Setup OWNER ──────────────────────────────────────────────
    print("[5] Setup akun OWNER...")
    shot("04_form_setup_owner")
    set_edit(win, "Username", OWNER_USER)
    set_edit(win, "Nama lengkap", OWNER_NAME)
    set_edit(win, "Password", OWNER_PASS)
    set_edit(win, "Ulangi password", OWNER_PASS)
    shot("05_form_setup_owner_terisi")
    click_button(win, "Buat Akun OWNER")
    wait(2.5)
    dismiss_msgboxes(app, timeout=6)
    clear_msgboxes(app)
    shot("06_owner_dibuat_login_form")

    # ── Login OWNER ──────────────────────────────────────────────
    print("[6] Login OWNER...")
    win = top_window(app)
    set_edit(win, "Username", OWNER_USER)
    set_edit(win, "Password", OWNER_PASS)
    shot("07_login_owner_terisi")
    click_button(win, "Login")
    wait(3.5)
    clear_msgboxes(app)
    win = top_window(app)
    try:
        wp = win.child_window(title="Kelola Pengguna", control_type="Button")
        on_dash = wp.exists(timeout=3)
    except Exception:
        on_dash = False
    print(f"  di dashboard OWNER: {on_dash}")
    shot("08_dashboard_owner")
    if not on_dash:
        clear_msgboxes(app)
        raise RuntimeError("Login OWNER gagal — tidak di dashboard")

    # ── Master Data: kategori + produk via GUI ───────────────────
    print("[7] Buka Master Data (Kelola Data)...")
    win = top_window(app)
    click_button(win, "Kelola Data", timeout=5)
    wait(2.5)
    clear_msgboxes(app)
    shot("09_master_data_kosong")
    win = top_window(app)
    try:
        tambah = win.child_window(
            title="Tambah Produk", control_type="Button"
        )
        on_md = tambah.exists(timeout=3)
    except Exception:
        on_md = False
    print(f"  di Master Data: {on_md}")
    if not on_md:
        raise RuntimeError("Master Data tidak terbuka")
    rows_before = count_products_via_gui(win)
    print(f"  produk sebelum GUI: {rows_before} (harus 0 karena --no-products)")

    add_categories_via_gui(app, win, NEW_CATEGORIES)

    win = top_window(app)
    add_products_via_gui(app, win, NEW_PRODUCTS)

    win = top_window(app)
    rows_after = count_products_via_gui(win)
    print(f"  produk setelah GUI: {rows_after} (target {len(NEW_PRODUCTS)})")
    shot("master_data_setelah_produk")
    if rows_after < len(NEW_PRODUCTS):
        raise RuntimeError(
            f"Tabel master data hanya {rows_after}/{len(NEW_PRODUCTS)} produk"
        )

    # ── Kembali ke dashboard ─────────────────────────────────────
    print("[9] Kembali ke dashboard...")
    win = top_window(app)
    try:
        dash_btn = win.child_window(title="Dashboard", control_type="Button")
        if dash_btn.exists(timeout=3):
            dash_btn.click_input()
            wait(2)
    except Exception as exc:
        print(f"  ! kembali dashboard: {exc}")
    clear_msgboxes(app)
    shot("13_dashboard_setelah_produk")

    # ── Buat user KASIR ──────────────────────────────────────────
    print("[10] Buka Manajemen Pengguna, buat KASIR...")
    win = top_window(app)
    click_button(win, "Kelola Pengguna", timeout=5)
    wait(2.5)
    clear_msgboxes(app)
    win2 = top_window(app)
    set_edit(win2, "Username", CASHIER_USER)
    set_edit(win2, "Nama lengkap", CASHIER_NAME)
    try:
        combos = [
            c
            for c in win2.descendants(control_type="ComboBox")
            if c.is_visible() and c.is_enabled()
        ]
        if combos:
            combo = combos[0]
            try:
                combo.expand()
            except Exception:
                combo.click_input()
            wait(0.4)
            try:
                combo.select("Kasir")
            except Exception:
                try:
                    combo.select(2)
                except Exception:
                    combo.click_input()
                    combo.type_keys("{DOWN}{DOWN}{ENTER}")
            wait(0.3)
    except Exception as exc:
        print(f"  ! role combo: {exc}")
    set_edit(win2, "Password", CASHIER_PASS)
    set_edit(win2, "Ulangi password", CASHIER_PASS)
    shot("14_form_kasir_terisi")
    click_button(win2, "Tambah Pengguna")
    wait(2)
    dismiss_msgboxes(app, timeout=4)
    clear_msgboxes(app)
    shot("15_kasir_ditambahkan")

    # ── Logout ───────────────────────────────────────────────────
    print("[11] Kembali ke dashboard lalu Keluar...")
    win2 = top_window(app)
    try:
        dash_btn = win2.child_window(
            title_re=".*Dashboard.*", control_type="Button"
        )
        if dash_btn.exists(timeout=3):
            dash_btn.click_input()
            wait(2)
    except Exception as exc:
        print(f"  ! kembali dashboard: {exc}")
    clear_msgboxes(app)
    try:
        win3 = top_window(app)
        keluar = win3.child_window(title="Keluar", control_type="Button")
        keluar.wait("exists", timeout=5)
        keluar.click_input()
        wait(2.5)
        print("  logout OK")
    except Exception as exc:
        print(f"  ! logout gagal: {exc}")
        for b in win3.descendants(control_type="Button"):
            if (b.window_text() or "").strip() == "Keluar":
                b.click_input()
                wait(2.5)
                break
    clear_msgboxes(app)
    shot("16_setelah_logout")

    # ── Login KASIR ──────────────────────────────────────────────
    print("[12] Login KASIR...")
    win = top_window(app)
    set_edit(win, "Username", CASHIER_USER)
    set_edit(win, "Password", CASHIER_PASS)
    shot("17_login_kasir_terisi")
    click_button(win, "Login")
    wait(3)
    clear_msgboxes(app)
    shot("18_view_kasir")

    # ── Buka Shift ───────────────────────────────────────────────
    print("[13] Buka Shift...")
    win = top_window(app)
    click_button(win, "Buka Shift")
    if not fill_int_dialog(app, "Buka Shift", "500000", parent=win):
        clear_msgboxes(app)
        raise RuntimeError("Dialog Buka Shift gagal diisi/ditutup")
    clear_msgboxes(app)
    shot("19_shift_aktif")

    # ── Kasir: cari produk GUI → qty → F4 tunai ──────────────────
    print("[14] Cari produk GUI → pilih → qty...")
    win = top_window(app)
    win.set_focus()
    wait(0.3)
    click_button(win, "Cari Produk")
    wait(1.5)
    shot("20_hasil_cari_produk")

    def biggest_table(w):
        best = None
        best_n = -1
        for t in w.descendants(control_type="Table"):
            try:
                rows = t.descendants(control_type="DataItem")
            except Exception:
                rows = []
            if len(rows) > best_n:
                best_n = len(rows)
                best = (t, rows)
        return best

    found = biggest_table(win)
    if found is None or not found[1]:
        raise RuntimeError("Tabel produk kasir kosong — produk GUI gagal?")
    table, rows = found
    print(f"  {len(rows)} baris produk di tabel kasir")
    rows[0].click_input()
    wait(1)
    if not fill_int_dialog(app, "Jumlah Produk", "2", parent=win):
        clear_msgboxes(app)
        raise RuntimeError("Dialog Jumlah Produk gagal ditutup")
    shot("21_produk_masuk_keranjang")

    win = top_window(app)
    win.set_focus()
    wait(0.3)
    found = biggest_table(win)
    if found is not None and len(found[1]) > 1:
        found[1][1].click_input()
        wait(1)
        fill_int_dialog(app, "Jumlah Produk", "1", parent=win)
    shot("22_dua_produk_keranjang")

    print("[15] F4 → Konfirmasi Tunai...")
    win = top_window(app)
    win.set_focus()
    wait(0.3)
    win.type_keys("{F4}")
    wait(1.5)
    shot("23_dialog_pembayaran")
    pay_dlg = top_window(app, timeout=5)
    click_button(pay_dlg, "Konfirmasi Tunai", timeout=5)
    wait(3)
    dismiss_all_blocking(app, timeout=8)
    shot("24_transaksi_berhasil")

    print("[16] Keluar dari jendela kasir...")
    dismiss_all_blocking(app, timeout=5)
    win = top_window(app)
    clicked = False
    try:
        click_button(win, "Keluar", timeout=5)
        clicked = True
    except Exception as exc:
        print(f"  ! tombol Keluar via child_window: {exc}")
        try:
            for b in win.descendants(control_type="Button"):
                if (b.window_text() or "").strip() == "Keluar":
                    b.click_input()
                    clicked = True
                    break
        except Exception as exc2:
            print(f"  ! tombol Keluar via descendants: {exc2}")
    if not clicked:
        raise RuntimeError("Tombol Keluar kasir tidak ditemukan")
    wait(2.5)
    dismiss_all_blocking(app, timeout=5)
    shot("25_setelah_keluar_kasir")

    print("[17] Login OWNER lagi...")
    win = top_window(app)
    clear_msgboxes(app)
    set_edit(win, "Username", OWNER_USER)
    set_edit(win, "Password", OWNER_PASS)
    shot("26_login_owner_lagi")
    click_button(win, "Login")
    wait(3)
    clear_msgboxes(app)
    shot("27_dashboard_owner_lagi")

    print("[18] Buka jendela Aktivasi Lisensi...")
    win = top_window(app)
    clicked = False
    for label in ("Buka Aktivasi", "Aktivasi Sekarang", "Aktivasi Lisensi"):
        try:
            click_button(win, label, timeout=2)
            clicked = True
            break
        except Exception:
            continue
    if not clicked:
        try:
            for b in win.descendants(control_type="Button"):
                if "Aktivasi" in (b.window_text() or ""):
                    b.click_input()
                    clicked = True
                    break
        except Exception:
            pass
    wait(2)
    clear_msgboxes(app)
    shot("28_jendela_aktivasi")
    return win


def run_web_payment():
    print("[19] Buka webserver (Playwright headed + video) untuk pembayaran...")
    import asyncio

    from playwright.async_api import async_playwright

    async def main():
        VIDEO_DIR.mkdir(parents=True, exist_ok=True)
        video_path = VIDEO_DIR / "web_payment.webm"
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=False, slowMo=300)
            ctx = await browser.new_context(
                viewport={"width": 1280, "height": 800},
                record_video_dir=str(VIDEO_DIR),
                record_video_size={"width": 1280, "height": 800},
            )
            page = await ctx.new_page()

            await page.goto(BASE_URL, wait_until="networkidle")
            await page.wait_for_timeout(600)
            await page.screenshot(path=str(SHOT_DIR / "30_web_landing.png"))
            print("  [shot] 30_web_landing.png")

            email = f"e2eprod.{int(time.time())}@pos.test"
            await page.goto(f"{BASE_URL}/register", wait_until="networkidle")
            await page.fill('input[name="email"]', email)
            await page.fill('input[name="password"]', "E2eProd!2026")
            await page.fill('input[name="store_name"]', "Toko E2E Produk")
            await page.screenshot(path=str(SHOT_DIR / "31_web_register.png"))
            await page.click('button[type="submit"]')
            await page.wait_for_url("**/dashboard**", timeout=15000)
            await page.wait_for_timeout(800)
            await page.screenshot(path=str(SHOT_DIR / "32_web_dashboard.png"))
            print("  [shot] 32_web_dashboard.png")

            import uuid as _uuid
            from hashlib import sha256

            installation_id = str(_uuid.uuid4())
            device_id = sha256(
                f"POS Retail:e2eprod-{int(time.time())}".encode()
            ).hexdigest()
            posreq = {
                "schema_version": 1,
                "product": "POS Retail",
                "installation_id": installation_id,
                "device_id": device_id,
                "store_name": "Toko E2E Produk",
                "requested_at": datetime.now().isoformat(),
            }
            await page.set_input_files(
                'input[type="file"]',
                {
                    "name": "device.posreq",
                    "mimeType": "application/json",
                    "buffer": json.dumps(posreq).encode(),
                },
            )
            await page.click('form[action="/devices"] button[type="submit"]')
            await page.wait_for_url("**/dashboard**", timeout=15000)
            await page.wait_for_timeout(800)
            await page.screenshot(path=str(SHOT_DIR / "33_web_device.png"))
            print("  [shot] 33_web_device.png")

            await page.select_option('select[name="device_pk"]', index=0)
            await page.select_option('select[name="plan_code"]', index=0)
            await page.click('form[action="/checkout"] button[type="submit"]')
            await page.wait_for_url("**/orders/**", timeout=15000)
            await page.wait_for_timeout(800)
            await page.screenshot(path=str(SHOT_DIR / "34_web_order_va.png"))
            print("  [shot] 34_web_order_va.png")

            await page.click('form[action*="simulasi-bayar"] button')
            await page.wait_for_url("**/orders/**", timeout=15000)
            await page.wait_for_timeout(800)
            await page.screenshot(path=str(SHOT_DIR / "35_web_paid.png"))
            print("  [shot] 35_web_paid.png")

            await page.goto(f"{BASE_URL}/dashboard", wait_until="networkidle")
            await page.wait_for_timeout(800)
            await page.screenshot(path=str(SHOT_DIR / "36_web_lisensi_aktif.png"))
            print("  [shot] 36_web_lisensi_aktif.png")

            await page.wait_for_timeout(2000)
            await ctx.close()
            await browser.close()
            vids = list(VIDEO_DIR.glob("*.webm"))
            if vids:
                vids[0].rename(video_path)
                print(f"  [video] {video_path}")

    asyncio.run(main())


def main():
    print("=" * 70)
    print(f"  E2E MASTER DATA PRODUK GUI  ({STAMP})")
    print(f"  Shot dir : {SHOT_DIR}")
    print(f"  Video dir: {VIDEO_DIR}")
    print(f"  Produk target: {[p['sku'] for p in NEW_PRODUCTS]}")
    print("=" * 70)

    SHOT_DIR.mkdir(parents=True, exist_ok=True)
    VIDEO_DIR.mkdir(parents=True, exist_ok=True)

    server_proc = None
    if not ensure_server():
        server_proc = start_server()
        print("  Server billing aktif.")
    else:
        print("  Server billing sudah aktif.")

    recorder = ScreenRecorder(VIDEO_DIR / "desktop_products.mp4")
    recorder.start()

    try:
        installer = download_installer()
        exe = install_silent(installer)
        fresh_pos_data()
        seed_installed_db(include_products=False)
        app = launch_pos(exe)
        run_desktop_flow(app)
        shot("29_selesai_desktop")

        recorder.stop()
        run_web_payment()
    except Exception as exc:
        print(f"\nGAGAL: {type(exc).__name__}: {exc}")
        shot("ERROR")
        import traceback

        traceback.print_exc()
    finally:
        recorder.stop()
        if server_proc:
            print("  Server dibiarkan jalan (port 8001).")

    print("\n" + "=" * 70)
    print("  RINGKASAN")
    print(f"  Screenshot: {SHOT_DIR}  ({len(list(SHOT_DIR.glob('*.png')))} file)")
    print(f"  Video     : {VIDEO_DIR}  ({len(list(VIDEO_DIR.glob('*')))} file)")
    print("=" * 70)


if __name__ == "__main__":
    main()
