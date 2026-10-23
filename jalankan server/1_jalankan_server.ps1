<#
.SYNOPSIS
    1_jalankan_server.ps1 - Menjalankan Server Billing POS dan Tunnel ngrok.
.DESCRIPTION
    Script ini akan:
    1. Memulai tunnel ngrok ke port 8001 (atau menggunakan tunnel yang aktif).
    2. Menghubungkan dan menyinkronkan URL publik ke .env dan server/.env.
    3. Memulai / me-restart webserver billing (Uvicorn) agar membaca konfigurasi terbaru.
    4. Menampilkan ringkasan URL publik dan endpoint webhook yang aktif.
#>
[CmdletBinding()]
param(
    [int]$Port = 8001
)

$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot  = Split-Path -Parent $scriptDir

Write-Host "========================================================" -ForegroundColor Cyan
Write-Host "       MENJALANKAN SERVER BILLING & NGROK TUNNEL        " -ForegroundColor Cyan
Write-Host "========================================================" -ForegroundColor Cyan

# 1. Jalankan script start_ngrok.ps1
$ngrokScript = Join-Path $repoRoot "scripts\start_ngrok.ps1"
if (-not (Test-Path $ngrokScript)) {
    Write-Host "Error: scripts\start_ngrok.ps1 tidak ditemukan di $repoRoot" -ForegroundColor Red
    Read-Host "Tekan Enter untuk keluar..."
    exit 1
}

Write-Host "`n[1/3] Menyiapkan tunnel ngrok dan konfigurasi .env..." -ForegroundColor Yellow
& powershell.exe -ExecutionPolicy Bypass -File $ngrokScript -Port $Port

if ($LASTEXITCODE -ne 0) {
    Write-Host "`n[!] Gagal menjalankan ngrok tunnel." -ForegroundColor Red
    Read-Host "Tekan Enter untuk keluar..."
    exit $LASTEXITCODE
}

# 2. Restart uvicorn server agar membaca perubahan .env terbaru
Write-Host "`n[2/3] Memastikan server billing membaca konfigurasi terbaru..." -ForegroundColor Yellow

# Hentikan proses python yang mendengarkan di port 8001 jika ada
$netstat = netstat -ano | findstr ":$Port" | findstr "LISTENING"
if ($netstat) {
    foreach ($line in $netstat) {
        $parts = $line.Trim() -split '\s+'
        $pidToKill = $parts[-1]
        if ($pidToKill -match '^\d+$' -and $pidToKill -ne "0") {
            try {
                Stop-Process -Id [int]$pidToKill -Force -ErrorAction SilentlyContinue
                Write-Host "      Proses lama (PID $pidToKill) dihentikan untuk restart." -ForegroundColor Gray
            } catch {}
        }
    }
}
Start-Sleep -Milliseconds 800

# Jalankan server uvicorn
$python = Join-Path $repoRoot "venv\Scripts\python.exe"
if (-not (Test-Path $python)) { $python = "python" }

$serverStdout = Join-Path $repoRoot "server_stdout.log"
$serverStderr = Join-Path $repoRoot "server_stderr.log"

Start-Process -FilePath $python `
    -ArgumentList @("-m", "uvicorn", "server.app.main:app", "--host", "127.0.0.1", "--port", "$Port") `
    -WorkingDirectory $repoRoot `
    -RedirectStandardOutput $serverStdout `
    -RedirectStandardError $serverStderr `
    -WindowStyle Minimized

# Tunggu sampai port siap
$isReady = $false
for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Milliseconds 500
    try {
        $client = New-Object System.Net.Sockets.TcpClient
        $client.Connect("127.0.0.1", $Port)
        $client.Close()
        $isReady = $true
        break
    } catch {}
}

Write-Host "`n[3/3] Memeriksa status kesehatan server..." -ForegroundColor Yellow
if ($isReady) {
    Write-Host "      Webserver billing aktif di http://127.0.0.1:$Port" -ForegroundColor Green
    try {
        $health = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/health" -TimeoutSec 5
        Write-Host "      Health check: OK (Status: $($health.status), Env: $($health.environment))" -ForegroundColor Green
    } catch {
        Write-Host "      Health check warning: $_" -ForegroundColor Yellow
    }
} else {
    Write-Host "      [!] Server belum merespons di port $Port. Cek server_stderr.log." -ForegroundColor Yellow
}

# Dapatkan URL publik dari ngrok API jika tersedia
try {
    $tunnels = (Invoke-RestMethod -Uri "http://127.0.0.1:4040/api/tunnels" -TimeoutSec 3).tunnels
    $publicUrl = ($tunnels | Where-Object { $_.public_url -like "https://*" }).public_url
    if ($publicUrl) {
        Write-Host "`n========================================================" -ForegroundColor Green
        Write-Host "              SERVER & NGROK SIAP DIGUNAKAN            " -ForegroundColor Green
        Write-Host "========================================================" -ForegroundColor Green
        Write-Host "  URL Web Publik : $publicUrl" -ForegroundColor White
        Write-Host "  Webhook URL    : $publicUrl/webhooks/payment/midtrans" -ForegroundColor White
        Write-Host "  Lokal Server   : http://127.0.0.1:$Port"
        Write-Host "  Ngrok Web UI   : http://127.0.0.1:4040"
        Write-Host "========================================================" -ForegroundColor Green
    }
} catch {}

Write-Host "`nUntuk menguji webhook, jalankan: 3_uji_endpoint.ps1" -ForegroundColor Cyan
Write-Host "Untuk menghentikan server, jalankan: 2_hentikan_server.ps1" -ForegroundColor Gray
Write-Host ""
Read-Host "Tekan Enter untuk menutup jendela ini (server tetap berjalan di latar belakang)..."
