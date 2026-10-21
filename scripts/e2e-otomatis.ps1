<#
.SYNOPSIS
  E2E otomatis POS: PC jalan sendiri dari server -> download -> aktivasi -> buka aplikasi.

.DESCRIPTION
  Mode default (sandbox, aman): semua jejak di .e2e-real\ (tidak menyentuh data asli).
    1. Server billing live (uvicorn, otomatis oleh driver)
    2. Unduh installer dari server
    3. Buat .posreq + daftar/login + daftarkan perangkat
    4. Checkout paket + simulasi webhook settlement Midtrans
    5. Aktivasi lisensi Ed25519 + migrasi pos.db
    6. Buka aplikasi sungguhan (python main.py) yang sudah aktif

  Mode -DataAsli: memakai data/lokasi asli (%LOCALAPPDATA%\POSApp\data dan
  server\data\billing.db) via scripts\e2e_real.py. DATA LAMA DIHAPUS. Minta konfirmasi.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\scripts\e2e-otomatis.ps1
  .\scripts\e2e-otomatis.ps1 -Toko "Toko Berkah" -Paket yearly
  .\scripts\e2e-otomatis.ps1 -TanpaBukaApp
  .\scripts\e2e-otomatis.ps1 -Gui       # klik + ketik asli di jendela app
  .\scripts\e2e-otomatis.ps1 -DataAsli   # Awas: hapus data asli!
#>
param(
  [string]$Toko = "Toko E2E Otomatis",
  [ValidateSet("monthly", "yearly", "lifetime")]
  [string]$Paket = "monthly",
  [switch]$DataAsli,
  [switch]$TanpaBukaApp,
  [switch]$Gui
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $Root "venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $Python)) {
  Write-Host "[X] venv tidak ditemukan: $Python" -ForegroundColor Red
  Write-Host "    Buat dulu: py -3.12 -m venv venv; .\venv\Scripts\python.exe -m pip install -r requirements.txt"
  exit 1
}

if ($DataAsli) {
  Write-Host "PERINGATAN: mode -DataAsli menghapus:" -ForegroundColor Yellow
  Write-Host "  - %LOCALAPPDATA%\POSApp\data  (data POS asli!)"
  Write-Host "  - server\data\billing.db      (database billing!)"
  $jawab = Read-Host "Lanjut? ketik YA untuk setuju"
  if ($jawab -ne "YA") { Write-Host "Dibatalkan."; exit 0 }

  & $Python (Join-Path $Root "scripts\e2e_real.py")
  if ($LASTEXITCODE -ne 0) { Write-Host "[X] e2e_real.py gagal." -ForegroundColor Red; exit 1 }

  Write-Host "[migrasi] pos.db (lokasi asli)..." -ForegroundColor Cyan
  & $Python (Join-Path $Root "scripts\init_db.py")
  if ($LASTEXITCODE -ne 0) { Write-Host "[X] init_db gagal." -ForegroundColor Red; exit 1 }

  if (-not $TanpaBukaApp) {
    Write-Host "[buka] aplikasi POS asli..." -ForegroundColor Green
    Start-Process -FilePath $Python -ArgumentList "main.py" -WorkingDirectory $Root
  }
  Write-Host "SELESAI (data asli)." -ForegroundColor Green
  exit 0
}

# ---- Mode GUI: klik + ketik beneran di jendela aplikasi (QTest) ----
# Membuka aplikasi sungguhan dan mengemudikan jendela aktivasi + login.
# (Di PC tanpa layar, jalankan dengan QT_QPA_PLATFORM=offscreen.)
if ($Gui) {
  Write-Host "== E2E GUI OTOMATIS (klik + ketik asli) ==" -ForegroundColor Cyan
  $env:PYTHONPATH = $Root
  & $Python (Join-Path $Root "scripts\e2e_gui.py") --toko $Toko --paket $Paket
  if ($LASTEXITCODE -ne 0) { Write-Host "[X] Otomatisasi GUI gagal." -ForegroundColor Red; exit 1 }
  Write-Host "SELESAI (mode GUI)." -ForegroundColor Green
  exit 0
}

# ---- Mode sandbox (API-level, tanpa GUI) ----
$Base = Join-Path $Root ".e2e-real"
$env:POS_DATA_DIR = Join-Path $Base "pos-data"
$env:PYTHONPATH = $Root

Write-Host "== E2E OTOMATIS (sandbox: $Base) ==" -ForegroundColor Cyan
& $Python (Join-Path $Root "scripts\e2e_otomatis.py") --toko $Toko --paket $Paket --base $Base
if ($LASTEXITCODE -ne 0) { Write-Host "[X] Driver E2E gagal." -ForegroundColor Red; exit 1 }

Write-Host "[migrasi] pos.db sandbox..." -ForegroundColor Cyan
& $Python (Join-Path $Root "scripts\init_db.py")
if ($LASTEXITCODE -ne 0) { Write-Host "[X] init_db gagal." -ForegroundColor Red; exit 1 }

Write-Host ""
Write-Host "Jejak di PC:" -ForegroundColor Cyan
Get-ChildItem -LiteralPath $Base -Recurse -File |
  Select-Object @{n="File";e={$_.FullName.Replace($Root, ".")}} |
  Format-Table -AutoSize | Out-String | Write-Host

if (-not $TanpaBukaApp) {
  Write-Host "[buka] aplikasi POS (sudah teraktivasi)..." -ForegroundColor Green
  Start-Process -FilePath $Python -ArgumentList "main.py" -WorkingDirectory $Root
  Write-Host "Aplikasi dibuka. Login dengan akun OWNER yang sudah dibuat / dibuat saat pertama buka." -ForegroundColor Green
}
Write-Host "SELESAI." -ForegroundColor Green
