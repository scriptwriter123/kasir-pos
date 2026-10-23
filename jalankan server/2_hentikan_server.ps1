<#
.SYNOPSIS
    2_hentikan_server.ps1 - Menghentikan Server Billing POS dan Tunnel ngrok.
.DESCRIPTION
    Script ini akan:
    1. Menghentikan semua proses tunnel ngrok.
    2. Menghentikan webserver billing (Uvicorn / Python di port 8001).
    3. Mengembalikan file konfigurasi .env dan server/.env dari file cadangan (.ngrok-backup).
#>
[CmdletBinding()]
param(
    [int]$Port = 8001
)

$ErrorActionPreference = "SilentlyContinue"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot  = Split-Path -Parent $scriptDir

Write-Host "========================================================" -ForegroundColor Yellow
Write-Host "       MENGHENTIKAN SERVER BILLING & NGROK TUNNEL       " -ForegroundColor Yellow
Write-Host "========================================================" -ForegroundColor Yellow

# 1. Panggil start_ngrok.ps1 -Stop untuk mengembalikan .env
$ngrokScript = Join-Path $repoRoot "scripts\start_ngrok.ps1"
if (Test-Path $ngrokScript) {
    Write-Host "`n[1/3] Menghentikan tunnel ngrok dan memulihkan .env..." -ForegroundColor Cyan
    & powershell.exe -ExecutionPolicy Bypass -File $ngrokScript -Stop -Port $Port
}

# 2. Hentikan sisa proses ngrok bila ada
$ngrokProcs = Get-Process -Name "ngrok" -ErrorAction SilentlyContinue
if ($ngrokProcs) {
    foreach ($p in $ngrokProcs) {
        Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
    }
}

# 3. Hentikan proses yang mendengarkan di port 8001 (Webserver Billing)
Write-Host "`n[2/3] Menghentikan webserver billing di port $Port..." -ForegroundColor Cyan
$stoppedCount = 0
$netstat = netstat -ano | findstr ":$Port" | findstr "LISTENING"
if ($netstat) {
    foreach ($line in $netstat) {
        $parts = $line.Trim() -split '\s+'
        $pidToKill = $parts[-1]
        if ($pidToKill -match '^\d+$' -and $pidToKill -ne "0") {
            try {
                Stop-Process -Id [int]$pidToKill -Force -ErrorAction SilentlyContinue
                Write-Host "      Proses webserver (PID $pidToKill) berhasil dihentikan." -ForegroundColor Green
                $stoppedCount++
            } catch {}
        }
    }
}

if ($stoppedCount -eq 0) {
    Write-Host "      Tidak ada webserver yang sedang berjalan di port $Port." -ForegroundColor Gray
}

# 4. Pastikan file backup dipulihkan jika script start_ngrok belum sempat memulihkan
Write-Host "`n[3/3] Memeriksa status file cadangan (.env)..." -ForegroundColor Cyan
$envBackup = Join-Path $repoRoot ".env.ngrok-backup"
$envFile   = Join-Path $repoRoot ".env"
if (Test-Path $envBackup) {
    Copy-Item $envBackup $envFile -Force
    Remove-Item $envBackup -Force
    Write-Host "      .env root berhasil dipulihkan dari cadangan." -ForegroundColor Green
}

$serverBackup = Join-Path $repoRoot "server\.env.ngrok-backup"
$serverFile   = Join-Path $repoRoot "server\.env"
if (Test-Path $serverBackup) {
    Copy-Item $serverBackup $serverFile -Force
    Remove-Item $serverBackup -Force
    Write-Host "      server/.env berhasil dipulihkan dari cadangan." -ForegroundColor Green
}

Write-Host "`n========================================================" -ForegroundColor Green
Write-Host "     SEMUA LAYANAN TELAH BERHASIL DIHENTIKAN            " -ForegroundColor Green
Write-Host "========================================================" -ForegroundColor Green
Write-Host ""
Read-Host "Tekan Enter untuk menutup jendela ini..."
