Kita akan membuat MCP Python khusus untuk membantu OpenCode mengembangkan aplikasi kasir di `E:\POS\KASIR`. MCP ini akan menjadi asisten diagnostik proyek, bukan pengganti OpenCode atau model AI.

Saya akan menggunakan Python dari virtual environment proyek, sesuai setup kamu yang menggunakan Windows, VS Code, Python, dan OpenCode CLI `1.19.0`.

Fitur yang akan kita buat:

- Membaca struktur folder proyek dan file kode yang diizinkan.
- Mencari teks atau nama fungsi dalam kode Python.
- Mendeteksi kesalahan sintaks Python.
- Memeriksa interpreter dan dependency proyek.
- Menjalankan `pytest` secara terbatas, dengan batas waktu.
- Memeriksa status Git jika Git tersedia.
- Membatasi akses ke file proyek agar MCP tidak menjadi alat eksekusi perintah bebas.

Keamanan: versi pertama tidak akan menyediakan tool untuk menghapus file, mengubah database POS, menjalankan perintah shell arbitrer, atau mengeksekusi kode hasil buatan AI. OpenCode tetap dapat mengedit kode melalui kemampuannya sendiri sesuai izin yang kamu berikan.

## 1. Struktur folder yang akan dibuat

Kita gunakan folder proyek kamu yang sudah ada. Tambahkan tiga file baru dan jangan mengubah modul kasir yang sudah berjalan.

```
E:\POS\KASIR\
│
├── app\                     # Kode aplikasi POS yang sudah ada
├── tests\                   # Pengujian proyek
├── venv\                    # Virtual environment Python
│
├── mcp_server\
│   ├── __init__.py
│   ├── server.py
│   └── requirements.txt
│
├── opencode.json            # Konfigurasi MCP untuk OpenCode
└── start_opencode_pos.bat   # Peluncur dengan database OpenCode
```

Kita menggunakan MCP Python SDK dengan seri versi `1.x` agar implementasi di bawah konsisten dengan API `FastMCP` yang digunakan. Dokumentasi SDK terbaru sudah memiliki seri `2.x` dengan perubahan API, jadi kita sengaja membatasi versi untuk menghindari perubahan yang tidak diperlukan.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://py.sdk.modelcontextprotocol.io\&sz=32)

MCP Python SDK

+1



## 2. File `mcp_server\requirements.txt`

Buat file ini dan isi dengan:

```

mcp[cli]>=1.9,<2

```

Ini membatasi dependency MCP ke versi di bawah 2. Kita tidak perlu menginstal paket MCP secara global dan tidak perlu membuat virtual environment baru.

## 3. File `mcp_server\__init__.py`

Buat file kosong berikut:

```
"""MCP tools for the POS project."""
```

## 4. File `mcp_server\server.py`

Ini merupakan implementasi utama. Server menyediakan tools untuk membaca kode, mencari fungsi, memeriksa sintaks, memeriksa environment, menjalankan pengujian, dan melihat status Git.

```
from __future__ import annotationsimport importlib.metadataimport osimport subprocessimport sysfrom pathlib import Pathfrom typing import Anyfrom mcp.server.fastmcp import FastMCP# Root proyek: E:\POS\KASIRPROJECT_ROOT = Path(    os.environ.get(        "POS_PROJECT_ROOT",        str(Path(__file__).resolve().parent.parent),    )).resolve()mcp = FastMCP("POS Project Diagnostics")# Folder yang tidak perlu dibaca atau dipindai.EXCLUDED_DIRS = {    ".git",    ".venv",    "venv",    "__pycache__",    ".pytest_cache",    ".mypy_cache",    ".ruff_cache",    "node_modules",    "dist",    "build",    ".tox",
```

Catatan teknis: kode di atas menggunakan `shutil.which()` pada tool Git. Tambahkan import `shutil` bersama import lain di bagian atas file, seperti yang sudah tercantum dalam kode. Pastikan baris `import importlib.util` juga ditambahkan agar pemeriksaan ketersediaan `pytest` eksplisit. Keduanya diperlukan untuk menjalankan seluruh tools tersebut.

## 5. Pastikan dua import tersedia

Sebelum menjalankan server, pastikan bagian import di awal `mcp_server\server.py` mencakup kedua modul berikut:

```
import importlib.utilimport shutil
```

Letakkan bersama import standar Python lainnya. `importlib.util` digunakan untuk memeriksa apakah `pytest` tersedia, sedangkan `shutil` digunakan untuk menemukan executable Git.

## 6. Instal dependency di virtual environment

Buka terminal CMD di VS Code. Jalankan:

```
cd /d E:\POS\KASIR
venv\Scripts\activate
python -m pip install -r mcp_server\requirements.txt
```

Pastikan instalasi berhasil:

```
python -c "import mcp; print('MCP SDK berhasil diimpor')"
```

Kemudian periksa sintaks server:

```
python -m py_compile mcp_server\server.py
```

Jika perintah terakhir selesai tanpa pesan error, sintaks file berhasil diperiksa. File hasil kompilasi hanya merupakan cache Python; tidak ada kode aplikasi yang dijalankan.

Jika environment kamu ternyata menggunakan folder `.venv`, bukan `venv`, sesuaikan path interpreter dan perintah aktivasi di bawah.

## 7. File `opencode.json`

OpenCode mendukung server MCP lokal melalui konfigurasi `mcp`, dengan `type: "local"` dan daftar `command`.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://docs.opencode.ai\&sz=32)

OpenCode

+1



Buat `E:\POS\KASIR\opencode.json` dengan isi berikut hanya jika file tersebut belum ada:

```

{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "pos-python": {
      "type": "local",
      "command": [
        "E:\\POS\\KASIR\\venv\\Scripts\\python.exe",
        "E:\\POS\\KASIR\\mcp_server\\server.py"
      ],
      "cwd": "E:\\POS\\KASIR",
      "enabled": true,
      "timeout": 10000
    }
  }
}

```

Jika kamu sudah memiliki `opencode.json` berisi konfigurasi provider AI, model, atau pengaturan lain, jangan menimpa file itu. Tambahkan hanya entri `"pos-python"` ke objek `"mcp"` yang sudah ada. Jika objek `"mcp"` sudah berisi server lain, pertahankan semuanya.

Server ini menggunakan interpreter Python dari `venv`, sedangkan OpenCode tetap berjalan melalui Node.js.

## 8. File `start_opencode_pos.bat`

Karena sebelumnya OpenCode kamu mengalami masalah database dan berhasil berjalan setelah menggunakan variabel `OPENCODE_DB`, kita buat peluncur khusus agar pengaturannya konsisten.

Simpan kode berikut sebagai `E:\POS\KASIR\start_opencode_pos.bat`:

```

@echo off
setlocal

set "PROJECT_ROOT=E:\POS\KASIR"
set "POS_PROJECT_ROOT=E:\POS\KASIR"
set "OPENCODE_DB=%USERPROFILE%\.opencode-data\opencode.db"

if not exist "%USERPROFILE%\.opencode-data" (
    mkdir "%USERPROFILE%\.opencode-data"
)

if not exist "%PROJECT_ROOT%\venv\Scripts\python.exe" (
    echo ERROR: Python venv tidak ditemukan.
    echo Periksa folder %PROJECT_ROOT%\venv
    pause
    exit /b 1
)

if not exist "%PROJECT_ROOT%\mcp_server\server.py" (
    echo ERROR: MCP server tidak ditemukan.
    pause
    exit /b 1
)

cd /d "%PROJECT_ROOT%"

echo Memulai OpenCode untuk proyek POS...
echo Project: %PROJECT_ROOT%
echo MCP Python menggunakan venv proyek.
echo.

opencode

echo.
echo OpenCode telah berhenti.
pause

endlocal

```

Setelah menyimpan file ini, kamu bisa memulai OpenCode khusus proyek POS dengan menjalankan:

```
E:\POS\KASIR\start_opencode_pos.bat
```

Peluncur tersebut mempertahankan pengaturan database OpenCode pada lokasi yang sudah kamu gunakan dan tidak menghapus database lama.

## 9. Aktifkan dan verifikasi MCP

Ikuti urutan ini setelah semua file tersimpan.

1. Jalankan `start_opencode_pos.bat` dari CMD atau klik dua kali file tersebut.
2. Setelah OpenCode terbuka, periksa server MCP. Jika ingin mengecek dari CMD terpisah, jalankan:

   `bat     set "OPENCODE_DB=%USERPROFILE%\.opencode-data\opencode.db"     cd /d E:\POS\KASIR     opencode mcp list     `
3. Pastikan `pos-python` terdaftar dan aktif. Jika gagal tersambung, periksa path interpreter, nama file konfigurasi, serta log OpenCode.
4. Minta model menjalankan pemeriksaan menggunakan tool MCP, bukan hanya menjawab berdasarkan perkiraan.

Gunakan prompt pengujian berikut:

Gunakan MCP server `pos-python` untuk memeriksa proyek POS ini.

1. Panggil `project_info` untuk memastikan root proyek dan interpreter Python benar.
2. Panggil `list_project_files` untuk memeriksa struktur folder `app` dan `tests`.
3. Panggil `environment_report` untuk memeriksa dependency.
4. Panggil `search_project` untuk mencari `get_session` dan `test_inventory`.
5. Panggil `check_python_syntax` untuk memeriksa kesalahan sintaks.

Jangan mengedit file atau menjalankan test terlebih dahulu. Laporkan hasil setiap tool dan rekomendasikan langkah perbaikan berikutnya.

## 10. Menjalankan test setelah pemeriksaan

Jika MCP sudah berfungsi dan kamu siap menguji, minta OpenCode menggunakan tool `run_pytest` dengan target:

```
tests
```

Perlu diperhatikan bahwa test Python dapat mengubah database atau file jika kode test memang melakukannya. Sebelum pengujian integrasi, pastikan konfigurasi test menggunakan database khusus test, bukan database transaksi toko yang sebenarnya.

MCP versi ini hanya menjalankan perintah `pytest` yang sudah ditentukan oleh kode server. Tidak ada tool untuk mengeksekusi shell bebas.

## Jika MCP belum muncul

Periksa tiga hal berikut:

- `E:\POS\KASIR\mcp_server\server.py` benar-benar ada.
- Interpreter `E:\POS\KASIR\venv\Scripts\python.exe` dapat mengimpor paket `mcp`.
- OpenCode dimulai dari root `E:\POS\KASIR` sehingga konfigurasi proyek ditemukan.

Dokumentasi resmi konfigurasi MCP: [OpenCode MCP Servers](https://docs.opencode.ai/docs/mcp-servers/).

Target akhir kita: OpenCode bisa memeriksa struktur proyek POS, menemukan masalah import, mendiagnosis sintaks, dan menjalankan test melalui MCP Python—tanpa perlu kamu menyalin isi setiap file secara manual ke percakapan AI.