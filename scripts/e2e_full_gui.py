"""E2E penuh dengan screenshot + video.

Alur:
  1. Unduh installer dari webserver
  2. Install senyap (Inno Setup) ke folder sementara
  3. Bersihkan data POS + seed Store/produk (tanpa user)
  4. Jalankan POS.exe hasil install
  5. Setup akun OWNER
  6. Login OWNER
  7. Buat user KASIR
  8. Logout -> login KASIR
  9. Buka Shift -> klik Cari Produk -> pilih baris -> isi qty ->
     F4 -> Konfirmasi Tunai
  10. Keluar dari jendela kasir
  11. Login OWNER lagi -> buka aktivasi lisensi
  12. Buka webserver (Playwright headed + video) untuk proses pembayaran

Jalankan:
    .\\venv\\Scripts\\python.exe scripts\\e2e_full_gui.py
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

import httpx
from PIL import ImageGrab
from pywinauto import Desktop, Application

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BASE_URL = "http://127.0.0.1:8001"
STAMP = datetime.now().strftime("%Y%m%d_%H%M%S")
SHOT_DIR = PROJECT_ROOT / "e2e_shots" / STAMP
VIDEO_DIR = PROJECT_ROOT / "e2e_videos" / STAMP
INSTALL_DIR = Path(os.environ.get("TEMP", ".")) / f"pos_e2e_install_{STAMP}"
POS_DATA = Path(os.environ["LOCALAPPDATA"]) / "POSApp" / "data"
FFMPEG = Path(os.environ["LOCALAPPDATA"]) / "ms-playwright" / "ffmpeg-1013" / "ffmpeg-win64.exe"

OWNER_USER = "owner"
OWNER_PASS = "Owner12345"
OWNER_NAME = "Pemilik Toko"
CASHIER_USER = "kasir01"
CASHIER_PASS = "Kasir12345"
CASHIER_NAME = "Budi Kasir"

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
    """Rekam layar penuh via ffmpeg x11grab/gdigrab (Windows)."""

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

    # Coba Inno Setup silent (butuh admin). Kalau gagal, salin binary
    # dari build dist (isi sama dengan yang dibundel installer).
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
            shot("02_hasil_install_silent")
            return exe
    except Exception as exc:
        print(f"  silent install gagal: {exc}")

    # Fallback: salin dist\POS (build PyInstaller, isi sama dgn installer)
    dist = PROJECT_ROOT / "dist" / "POS"
    if not (dist / "POS.exe").exists():
        raise FileNotFoundError(f"Build POS tidak ditemukan di {dist}")
    print(f"  fallback: salin {dist} -> {INSTALL_DIR}")
    shutil.copytree(dist, INSTALL_DIR, dirs_exist_ok=True)
    if not exe.exists():
        raise FileNotFoundError(f"POS.exe tidak ditemukan di {INSTALL_DIR}")
    print(f"  POS.exe: {exe}")
    shot("02_hasil_install_dist")
    return exe


def fresh_pos_data():
    print("[3] Bersihkan data POS (simulasi instalasi baru)...")
    if POS_DATA.exists():
        shutil.rmtree(POS_DATA, ignore_errors=True)
    POS_DATA.mkdir(parents=True, exist_ok=True)
    print(f"  {POS_DATA}")


def seed_installed_db(include_products: bool = True):
    """Migrasi + seed Store/master data ke DB hasil install (tanpa user).

    Setup OWNER di aplikasi tidak membuat baris Store, padahal Buka Shift
    wajib punya Store. Seed --no-users menjaga form setup OWNER tetap muncul.
    include_products=False dipakai test Master Data (produk hanya dari GUI).
    """
    label = "Store + produk contoh" if include_products else "Store + master data"
    print(f"[3b] Seed database POS ({label}, tanpa user)...")
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
    proc = subprocess.Popen(
        [str(exe)],
        cwd=str(exe.parent),
        env=env,
    )
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
    """Cari Edit berdasarkan best_match identifier (mis. UsernameEdit)."""
    try:
        el = win.child_window(best_match=hint, control_type="Edit")
        el.wait("exists", timeout=2)
        return el
    except Exception:
        pass
    # fallback: child_window tanpa control_type
    try:
        el = win.child_window(best_match=hint)
        el.wait("exists", timeout=1)
        if el.element_info.control_type == "Edit":
            return el
    except Exception:
        pass
    # fallback: Edit berurutan
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
        # fallback: click lalu select-all + type_keys
        edit.click_input()
        edit.type_keys("^a")
        edit.type_keys(value, with_spaces=True)
    wait(0.2)


def dismiss_msgboxes(app: Application, timeout=5) -> bool:
    """Tutup QMessageBox modal Qt.

    Qt/UIA menaruh QMessageBox sebagai child window di window utama,
    bukan top-level — jadi cari dari top_window + descendants, lalu
    fallback klik koordinat pusat tombol OK.
    """
    closed = False
    deadline = time.time() + timeout
    known_titles = (
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
        "Pilih produk dari daftar terlebih dahulu.",
        "Keranjang kosong.",
        "Jumlah",
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
        "Harga spesial gagal disimpan",
        "Harga spesial gagal dihapus",
        "Pilih produk",
        "Stok ditambahkan",
        "Stok tidak dapat ditambahkan",
    )

    def _close_msgbox(w) -> bool:
        try:
            w.set_focus()
            wait(0.15)
        except Exception:
            pass
        try:
            for b in w.descendants(control_type="Button"):
                txt = (b.window_text() or "").strip()
                if txt in ("OK", "Ok", "Yes", "Ya"):
                    b.click_input()
                    wait(0.5)
                    return True
        except Exception:
            pass
        try:
            ok = w.child_window(title_re="^(OK|Yes|Ya)$", control_type="Button")
            if ok.exists(timeout=0.3):
                ok.click_input()
                wait(0.5)
                return True
        except Exception:
            pass
        try:
            w.type_keys("{ENTER}")
            wait(0.5)
            return True
        except Exception:
            return False

    while time.time() < deadline:
        found = False
        candidates: list = []
        try:
            candidates.extend(list(app.windows()))
        except Exception:
            pass
        # Qt kadang menaruh QMessageBox sebagai top-level window di luar
        # daftar app.windows(); scan Desktop berdasarkan judul yang dikenal.
        try:
            for w in Desktop(backend="uia").windows():
                try:
                    t = w.window_text() or ""
                except Exception:
                    continue
                if t in known_titles:
                    candidates.append(w)
        except Exception:
            pass
        for top in candidates:
            try:
                top_title = top.window_text() or ""
            except Exception:
                continue
            if top_title in known_titles:
                if _close_msgbox(top):
                    closed = True
                    found = True
                    break
                continue
            for title in known_titles:
                try:
                    mb = top.child_window(title=title)
                    if not mb.exists(timeout=0.1):
                        continue
                    if _close_msgbox(mb):
                        closed = True
                        found = True
                        break
                except Exception:
                    continue
            if found:
                break
        if not found:
            break
    return closed


def clear_msgboxes(app: Application):
    """Tutup semua message box sampai bersih."""
    for _ in range(15):
        if not dismiss_msgboxes(app, timeout=0.6):
            return
        wait(0.2)


def select_combo(win, label: str, item_text: str, timeout=5):
    combo = win.child_window(title=label, control_type="ComboBox")
    combo.wait("exists", timeout=timeout)
    try:
        combo.wait("visible", timeout=2)
    except Exception:
        pass
    combo.select(item_text)
    wait(0.3)


def fill_int_dialog(
    app: Application, title: str, value: str, timeout=8, parent=None
) -> bool:
    """Isi QInputDialog.getInt (modal Qt) lalu klik OK.

    Qt/QDialog bisa muncul sebagai top-level window ATAU child window
    dari window utama — cari di keduanya.
    """
    deadline = time.time() + timeout
    dlg = None
    while time.time() < deadline:
        # 1) top-level windows
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
        # 2) child window di parent (QDialog biasanya di sini)
        if dlg is None and parent is not None:
            try:
                cand = parent.child_window(
                    title=title, control_type="Window"
                )
                if cand.exists(timeout=0.2):
                    dlg = cand
            except Exception:
                pass
        # 3) descendants parent: cari Window dengan judul cocok
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
    # isi nilai: Edit di dalam SpinBox (QSpinBox punya child Edit)
    set_ok = False
    try:
        edit = dlg.child_window(control_type="Edit")
        if edit.exists(timeout=2):
            edit.click_input()
            wait(0.15)
            # select-all lalu ketik nilai baru (type_keys tanpa arg clear)
            edit.type_keys("^a")
            edit.type_keys(value, with_spaces=False)
            set_ok = True
    except Exception as exc:
        print(f"  ! isi Edit dialog {title!r}: {exc}")
    if not set_ok:
        try:
            spin = dlg.child_window(control_type="Spinner")
            if spin.exists(timeout=1):
                # coba ValuePattern UIA dulu
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
    # OK adalah default button: klik tombol OK, fallback Enter
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
    # tunggu dialog benar-benar tertutup
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


def dismiss_save_as(app: Application, timeout=5) -> bool:
    """Tutup dialog Save As native Windows (mis. dari Microsoft Print to PDF).

    Printer default di mesin uji bisa berupa virtual PDF printer sehingga
    cetak struk memunculkan dialog Save As yang memblokir.
    """
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
                # klik Cancel
                try:
                    cancel = w.child_window(
                        title_re="^(Cancel|Batal)$",
                        control_type="Button",
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
    """Tutup Save As + message box sampai bersih."""
    for _ in range(10):
        did = dismiss_save_as(app, timeout=0.6)
        did = dismiss_msgboxes(app, timeout=0.6) or did
        if not did:
            return
        wait(0.2)


def run_desktop_flow(app: Application):
    win = top_window(app)
    title = win.window_text()
    print(f"  Window: {title}")

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
    # QMessageBox modal: klik OK pakai beberapa strategi
    ok_closed = False
    try:
        mb = win.child_window(title="Akun OWNER dibuat", control_type="Window")
        if mb.exists(timeout=3):
            try:
                mb.set_focus()
                wait(0.2)
            except Exception:
                pass
            ok_btn = mb.child_window(title="OK", control_type="Button")
            if ok_btn.exists(timeout=2):
                ok_btn.click_input()
                ok_closed = True
                print("  msgbox OK via child_window")
            else:
                mb.type_keys("{ENTER}")
                ok_closed = True
                print("  msgbox OK via Enter")
    except Exception as exc:
        print(f"  msgbox child_window gagal: {exc}")
    if not ok_closed:
        # fallback: klik koordinat pusat tombol OK
        try:
            import pywinauto.mouse as mouse

            mb2 = win.child_window(
                title_re=".*OWNER dibuat.*", control_type="Window"
            )
            if mb2.exists(timeout=1):
                r = mb2.rectangle()
                x = r.left + int(r.width() * 0.82)
                y = r.top + int(r.height() * 0.75)
                mouse.click(coords=(x, y))
                ok_closed = True
                print(f"  msgbox OK via koordinat ({x},{y})")
        except Exception as exc:
            print(f"  msgbox koordinat gagal: {exc}")
    if not ok_closed:
        # terakhir: tekan Enter pada window utama
        try:
            win.type_keys("{ENTER}")
            ok_closed = True
            print("  msgbox OK via Enter window utama")
        except Exception as exc:
            print(f"  Enter window utama gagal: {exc}")
    wait(1)
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
    # verifikasi: dashboard OWNER punya tombol "Kelola Pengguna"
    win = top_window(app)
    try:
        wp = win.child_window(title="Kelola Pengguna", control_type="Button")
        on_dash = wp.exists(timeout=3)
    except Exception:
        on_dash = False
    print(f"  di dashboard OWNER: {on_dash}")
    shot("08_dashboard_owner")
    if not on_dash:
        # mungkin masih di login / ada msgbox tersembunyi
        clear_msgboxes(app)
        raise RuntimeError("Login OWNER gagal — tidak di dashboard")

    # ── Manajemen Pengguna → buat KASIR ──────────────────────────
    print("[7] Buka Manajemen Pengguna...")
    win = top_window(app)
    # tombol aksi kartu OWNER: "Kelola Pengguna"
    click_button(win, "Kelola Pengguna", timeout=5)
    wait(2.5)
    clear_msgboxes(app)
    shot("09_manajemen_pengguna")
    # verifikasi form user management
    win2 = top_window(app)
    try:
        tambah = win2.child_window(
            title="Tambah Pengguna", control_type="Button"
        )
        on_um = tambah.exists(timeout=3)
    except Exception:
        on_um = False
    print(f"  di Manajemen Pengguna: {on_um}")
    if not on_um:
        raise RuntimeError("Manajemen Pengguna tidak terbuka")

    print("[8] Buat user KASIR...")
    win2 = top_window(app)
    set_edit(win2, "Username", CASHIER_USER)
    set_edit(win2, "Nama lengkap", CASHIER_NAME)
    # Role combo: expand lalu pilih "Kasir" (index 2)
    try:
        combos = [
            c
            for c in win2.descendants(control_type="ComboBox")
            if c.is_visible() and c.is_enabled()
        ]
        if not combos:
            raise RuntimeError("combo Role tidak ditemukan")
        combo = combos[0]
        # expand combo dulu agar item bisa diakses UIA
        try:
            combo.expand()
        except Exception:
            combo.click_input()
        wait(0.4)
        # coba select by text dulu
        selected = False
        try:
            combo.select("Kasir")
            selected = True
        except Exception:
            pass
        if not selected:
            # fallback: select by index (Admin=0, Supervisor=1, Kasir=2)
            try:
                combo.select(2)
                selected = True
            except Exception:
                pass
        if not selected:
            # fallback terakhir: klik lalu tekan Down 2x + Enter
            combo.click_input()
            wait(0.3)
            combo.type_keys("{DOWN}{DOWN}{ENTER}")
            selected = True
        wait(0.3)
        print(f"  role combo selected={selected}")
    except Exception as exc:
        print(f"  ! role combo: {exc}")
    set_edit(win2, "Password", CASHIER_PASS)
    set_edit(win2, "Ulangi password", CASHIER_PASS)
    shot("10_form_kasir_terisi")
    click_button(win2, "Tambah Pengguna")
    wait(2)
    # tutup msgbox "Pengguna ditambahkan"
    try:
        mb = win2.child_window(
            title="Pengguna ditambahkan", control_type="Window"
        )
        if mb.exists(timeout=3):
            try:
                mb.set_focus()
                wait(0.2)
            except Exception:
                pass
            ok_btn = mb.child_window(title="OK", control_type="Button")
            if ok_btn.exists(timeout=2):
                ok_btn.click_input()
                print("  msgbox Pengguna ditambahkan OK")
            else:
                mb.type_keys("{ENTER}")
    except Exception as exc:
        print(f"  msgbox pengguna: {exc}")
    clear_msgboxes(app)
    shot("11_kasir_ditambahkan")

    # ── Kembali ke dashboard, logout ─────────────────────────────
    print("[9] Kembali ke dashboard lalu Keluar (logout)...")
    win2 = top_window(app)
    # tombol "← Dashboard" di header Manajemen Pengguna
    try:
        dash_btn = win2.child_window(
            title_re=".*Dashboard.*", control_type="Button"
        )
        if dash_btn.exists(timeout=3):
            dash_btn.click_input()
            wait(2)
            print("  kembali ke dashboard")
        else:
            print("  ! tombol Dashboard tidak ditemukan")
    except Exception as exc:
        print(f"  ! kembali dashboard: {exc}")
    clear_msgboxes(app)
    shot("12_dashboard_setelahTambah_kasir")

    # tombol Keluar (merah) di dashboard
    try:
        win3 = top_window(app)
        keluar = win3.child_window(title="Keluar", control_type="Button")
        keluar.wait("exists", timeout=5)
        keluar.click_input()
        wait(2.5)
        print("  logout OK")
    except Exception as exc:
        print(f"  ! logout gagal: {exc}")
        # fallback: cari button Keluar di descendants
        try:
            for b in win3.descendants(control_type="Button"):
                if (b.window_text() or "").strip() == "Keluar":
                    b.click_input()
                    wait(2.5)
                    print("  logout OK via descendants")
                    break
        except Exception:
            pass
    clear_msgboxes(app)
    shot("13_setelah_logout")

    # ── Login KASIR ──────────────────────────────────────────────
    print("[10] Login KASIR...")
    win = top_window(app)
    set_edit(win, "Username", CASHIER_USER)
    set_edit(win, "Password", CASHIER_PASS)
    shot("14_login_kasir_terisi")
    click_button(win, "Login")
    wait(3)
    clear_msgboxes(app)
    shot("15_view_kasir")

    # ── Buka Shift ───────────────────────────────────────────────
    print("[11] Buka Shift...")
    win = top_window(app)
    click_button(win, "Buka Shift")
    if not fill_int_dialog(app, "Buka Shift", "500000", parent=win):
        clear_msgboxes(app)
        raise RuntimeError("Dialog Buka Shift gagal diisi/ditutup")
    clear_msgboxes(app)
    shot("16_shift_aktif")

    # ── Kasir: klik Cari Produk → pilih baris → qty → F4 ────────
    # Sesuai alur manual: tombol "Cari Produk" (query kosong = semua
    # produk tampil), klik baris → dialog "Jumlah Produk" → isi qty →
    # Enter/OK → tekan F4 → "Konfirmasi Tunai".
    print("[12] Klik Cari Produk → pilih produk → isi qty...")
    win = top_window(app)
    win.set_focus()
    wait(0.3)
    click_button(win, "Cari Produk")
    wait(1.5)
    shot("17_hasil_cari_produk")

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
        raise RuntimeError("Tabel produk kosong — seed gagal?")
    table, rows = found
    print(f"  {len(rows)} baris produk di tabel")
    # klik baris pertama → cellClicked → dialog Jumlah Produk muncul
    rows[0].click_input()
    wait(1)
    if not fill_int_dialog(app, "Jumlah Produk", "2", parent=win):
        clear_msgboxes(app)
        raise RuntimeError("Dialog Jumlah Produk gagal ditutup")
    shot("18_produk_masuk_keranjang")

    # produk kedua (pilih baris berbeda, qty 1)
    win = top_window(app)
    win.set_focus()
    wait(0.3)
    found = biggest_table(win)
    if found is not None and len(found[1]) > 1:
        found[1][1].click_input()
        wait(1)
        fill_int_dialog(app, "Jumlah Produk", "1", parent=win)
    shot("19_dua_produk_keranjang")

    # ── F4 bayar tunai ──────────────────────────────────────────
    print("[13] Tekan F4 → Konfirmasi Tunai...")
    win = top_window(app)
    win.set_focus()
    wait(0.3)
    win.type_keys("{F4}")
    wait(1.5)
    shot("20_dialog_pembayaran")
    pay_dlg = top_window(app, timeout=5)
    click_button(pay_dlg, "Konfirmasi Tunai", timeout=5)
    wait(2.5)
    # Printer default bisa virtual PDF → dialog Save As native Windows;
    # tutup dulu, lalu "Transaksi berhasil"/warning cetak → OK.
    dismiss_all_blocking(app, timeout=8)
    shot("21_transaksi_berhasil")

    # ── Keluar dari jendela kasir ────────────────────────────────
    print("[14] Keluar dari jendela kasir...")
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
    shot("22_setelah_keluar_kasir")

    # ── Login OWNER lagi ─────────────────────────────────────────
    print("[15] Login OWNER lagi...")
    win = top_window(app)
    set_edit(win, "Username", OWNER_USER)
    set_edit(win, "Password", OWNER_PASS)
    shot("23_login_owner_lagi")
    click_button(win, "Login")
    wait(3)
    clear_msgboxes(app)
    shot("24_dashboard_owner_lagi")

    # ── Aktivasi lisensi ─────────────────────────────────────────
    print("[16] Buka jendela Aktivasi Lisensi...")
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
    shot("25_jendela_aktivasi")

    # jika LicenseView terbuka sebagai window terpisah
    try:
        act_win = None
        desktop = Desktop(backend="uia")
        for w in desktop.windows():
            if "Aktivasi" in w.window_text():
                act_win = w
                break
        if act_win:
            act_win.set_focus()
            wait(0.5)
            shot("26_aktivasi_fokus")
    except Exception:
        pass

    return win


def run_web_payment():
    print("[17] Buka webserver (Playwright headed + video) untuk pembayaran...")
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

            # landing
            await page.goto(BASE_URL, wait_until="networkidle")
            await page.wait_for_timeout(600)
            await page.screenshot(path=str(SHOT_DIR / "30_web_landing.png"))
            print("  [shot] 30_web_landing.png")

            # register akun billing baru
            email = f"e2efull.{int(time.time())}@pos.test"
            await page.goto(f"{BASE_URL}/register", wait_until="networkidle")
            await page.fill('input[name="email"]', email)
            await page.fill('input[name="password"]', "E2eFull!2026")
            await page.fill('input[name="store_name"]', "Toko E2E Full")
            await page.screenshot(path=str(SHOT_DIR / "31_web_register.png"))
            print("  [shot] 31_web_register.png")
            await page.click('button[type="submit"]')
            await page.wait_for_url("**/dashboard**", timeout=15000)
            await page.wait_for_timeout(800)
            await page.screenshot(path=str(SHOT_DIR / "32_web_dashboard.png"))
            print("  [shot] 32_web_dashboard.png")

            # unggah .posreq (format valid)
            import uuid as _uuid
            from hashlib import sha256

            installation_id = str(_uuid.uuid4())
            device_id = sha256(
                f"POS Retail:e2efull-{int(time.time())}".encode()
            ).hexdigest()
            posreq = {
                "schema_version": 1,
                "product": "POS Retail",
                "installation_id": installation_id,
                "device_id": device_id,
                "store_name": "Toko E2E Full",
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
            await page.screenshot(path=str(SHOT_DIR / "33_web_device_terdaftar.png"))
            print("  [shot] 33_web_device_terdaftar.png")

            # checkout paket
            await page.select_option('select[name="device_pk"]', index=0)
            await page.select_option('select[name="plan_code"]', index=0)
            await page.click('form[action="/checkout"] button[type="submit"]')
            await page.wait_for_url("**/orders/**", timeout=15000)
            await page.wait_for_timeout(800)
            await page.screenshot(path=str(SHOT_DIR / "34_web_order_va.png"))
            print("  [shot] 34_web_order_va.png")

            # bayar ATM simulasi
            await page.click('form[action*="simulasi-bayar"] button')
            await page.wait_for_url("**/orders/**", timeout=15000)
            await page.wait_for_timeout(800)
            await page.screenshot(path=str(SHOT_DIR / "35_web_paid.png"))
            print("  [shot] 35_web_paid.png")

            # dashboard -> lisensi active
            await page.goto(f"{BASE_URL}/dashboard", wait_until="networkidle")
            await page.wait_for_timeout(800)
            await page.screenshot(path=str(SHOT_DIR / "36_web_lisensi_aktif.png"))
            print("  [shot] 36_web_lisensi_aktif.png")

            await page.wait_for_timeout(2000)
            await ctx.close()
            await browser.close()
            # rename video
            vids = list(VIDEO_DIR.glob("*.webm"))
            if vids:
                vids[0].rename(video_path)
                print(f"  [video] {video_path}")

    asyncio.run(main())


def main():
    print("=" * 70)
    print(f"  E2E FULL GUI + SCREENSHOT/VIDEO  ({STAMP})")
    print(f"  Shot dir : {SHOT_DIR}")
    print(f"  Video dir: {VIDEO_DIR}")
    print("=" * 70)

    SHOT_DIR.mkdir(parents=True, exist_ok=True)
    VIDEO_DIR.mkdir(parents=True, exist_ok=True)

    # pastikan server jalan
    server_proc = None
    if not ensure_server():
        server_proc = start_server()
        print("  Server billing aktif.")
    else:
        print("  Server billing sudah aktif.")

    recorder = ScreenRecorder(VIDEO_DIR / "desktop_full.mp4")
    recorder.start()

    try:
        installer = download_installer()
        exe = install_silent(installer)
        fresh_pos_data()
        seed_installed_db()
        app = launch_pos(exe)
        run_desktop_flow(app)
        shot("27_selesai_desktop")

        # hentikan rekam desktop sebelum bagian web (web punya video sendiri)
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
