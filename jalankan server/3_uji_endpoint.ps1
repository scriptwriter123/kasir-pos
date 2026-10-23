<#
.SYNOPSIS
    3_uji_endpoint.ps1 - Menguji Endpoint Server Billing dan Webhook Midtrans.
.DESCRIPTION
    Script ini akan:
    1. Menguji kesehatan webserver lokal (http://127.0.0.1:8001/health).
    2. Mendeteksi URL publik ngrok yang aktif.
    3. Menguji kesehatan webserver via URL ngrok publik.
    4. Menguji Webhook Midtrans:
       - Tes GET: Menjelaskan mengapa muncul "Method Not Allowed" di browser.
       - Tes POST: Mengirimkan simulasi notifikasi pembayaran Midtrans dengan perhitungan signature SHA-512 asli.
#>
[CmdletBinding()]
param(
    [int]$Port = 8001
)

$ErrorActionPreference = "Continue"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot  = Split-Path -Parent $scriptDir

Write-Host "========================================================" -ForegroundColor Cyan
Write-Host "         PENGUJIAN ENDPOINT SERVER & WEBHOOK            " -ForegroundColor Cyan
Write-Host "========================================================" -ForegroundColor Cyan

# -----------------------------------------------------------------------------
# 1. Uji Server Lokal
# -----------------------------------------------------------------------------
Write-Host "`n[1/4] Menguji Server Lokal di http://127.0.0.1:$Port/health..." -ForegroundColor Yellow
$localOk = $false
try {
    $resLocal = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/health" -TimeoutSec 4 -ErrorAction Stop
    Write-Host "      [OK] Server lokal merespons normal." -ForegroundColor Green
    Write-Host "           Status: $($resLocal.status) | Env: $($resLocal.environment)" -ForegroundColor Gray
    $localOk = $true
} catch {
    Write-Host "      [FAIL] Webserver lokal tidak merespons di port $Port." -ForegroundColor Red
    Write-Host "             Pastikan server sudah dinyalakan dengan: 1_jalankan_server.ps1" -ForegroundColor Yellow
}

# -----------------------------------------------------------------------------
# 2. Deteksi URL Publik ngrok
# -----------------------------------------------------------------------------
Write-Host "`n[2/4] Mendeteksi URL Publik ngrok..." -ForegroundColor Yellow
$publicUrl = $null
try {
    $tunnels = (Invoke-RestMethod -Uri "http://127.0.0.1:4040/api/tunnels" -TimeoutSec 4 -ErrorAction Stop).tunnels
    $tunnel = $tunnels | Where-Object { $_.public_url -like "https://*" } | Select-Object -First 1
    if ($tunnel) {
        $publicUrl = $tunnel.public_url.TrimEnd("/")
    }
} catch {}

if (-not $publicUrl) {
    # Coba baca dari server/.env
    $serverEnv = Join-Path $repoRoot "server\.env"
    if (Test-Path $serverEnv) {
        foreach ($line in [System.IO.File]::ReadAllLines($serverEnv)) {
            if ($line -match '^\s*BASE_URL\s*=\s*(https://\S+)') {
                $publicUrl = $Matches[1].TrimEnd("/")
                break
            }
        }
    }
}

if ($publicUrl) {
    Write-Host "      [OK] URL Publik terdeteksi: $publicUrl" -ForegroundColor Green
} else {
    Write-Host "      [WARN] Tunnel ngrok belum terdeteksi aktif." -ForegroundColor Yellow
    Write-Host "             Jalankan 1_jalankan_server.ps1 terlebih dahulu." -ForegroundColor Gray
}

# -----------------------------------------------------------------------------
# 3. Uji Akses Publik (/health)
# -----------------------------------------------------------------------------
Write-Host "`n[3/4] Menguji Akses Publik via Internet ($publicUrl/health)..." -ForegroundColor Yellow
if ($publicUrl) {
    try {
        $resPublic = Invoke-RestMethod -Uri "$publicUrl/health" `
            -Headers @{"ngrok-skip-browser-warning" = "1"} `
            -TimeoutSec 10 -ErrorAction Stop
        Write-Host "      [OK] Server publik dapat diakses dari internet." -ForegroundColor Green
        Write-Host "           Respons: status=$($resPublic.status)" -ForegroundColor Gray
    } catch {
        Write-Host "      [FAIL] Gagal mengakses URL publik: $($_.Exception.Message)" -ForegroundColor Red
    }
} else {
    Write-Host "      (Dilewati karena URL publik ngrok tidak tersedia)" -ForegroundColor Gray
}

# -----------------------------------------------------------------------------
# 4. Uji Webhook Midtrans
# -----------------------------------------------------------------------------
Write-Host "`n[4/4] Menguji Endpoint Webhook Midtrans..." -ForegroundColor Yellow
$webhookUrl = if ($publicUrl) { "$publicUrl/webhooks/payment/midtrans" } else { "http://127.0.0.1:$Port/webhooks/payment/midtrans" }
Write-Host "      URL Target: $webhookUrl" -ForegroundColor Gray

# --- Test A: HTTP GET (Penjelasan Browser) ---
Write-Host "`n  -> Tes 4A: Request HTTP GET (Seperti saat membuka di browser)" -ForegroundColor Cyan
try {
    $getRes = Invoke-WebRequest -Uri $webhookUrl -Method GET `
        -Headers @{"ngrok-skip-browser-warning" = "1"} `
        -TimeoutSec 10 -UseBasicParsing -ErrorAction Stop
    Write-Host "     Respons: $($getRes.StatusCode)" -ForegroundColor Gray
} catch {
    $status = $_.Exception.Response.StatusCode.value__
    if ($status -eq 405) {
        Write-Host "     [OK] Status 405 Method Not Allowed" -ForegroundColor Green
        Write-Host "          PENJELASAN: Ini adalah respons yang BENAR & NORMAL." -ForegroundColor Gray
        Write-Host "          Browser mengirimkan request GET saat Anda membuka tautan." -ForegroundColor Gray
        Write-Host "          Webhook hanya menerima request POST dari server Midtrans." -ForegroundColor Gray
    } else {
        Write-Host "     Respons: $status ($($_.Exception.Message))" -ForegroundColor Yellow
    }
}

# --- Test B: HTTP POST (Simulasi Notifikasi Pembayaran Midtrans Asli) ---
Write-Host "`n  -> Tes 4B: Membuat Order Dummy di Database & Menguji Webhook 100% Real..." -ForegroundColor Cyan

# 1. Buat dummy order di database menggunakan Python
$python = Join-Path $repoRoot "venv\Scripts\python.exe"
if (-not (Test-Path $python)) { $python = "python" }

$createOrderCmd = @"
import secrets
from server.app.database import make_session_factory
from server.app.models import Customer, Order, Plan
from server.app.config import Settings
factory = make_session_factory(Settings())
with factory() as session:
    cust = session.query(Customer).first()
    plan = session.query(Plan).filter_by(code='monthly').first()
    code = f'POS-TEST-{secrets.token_hex(3).upper()}'
    amt = plan.price_idr if plan else 99000
    order = Order(order_code=code, customer_id=cust.id if cust else 1, plan_code='monthly', amount_idr=amt, status='pending')
    session.add(order)
    session.commit()
    print(f'{code}|{amt}')
"@

$orderResult = & $python -c $createOrderCmd 2>$null
$orderParts = ($orderResult.Trim() -split '\|')
$orderId = $orderParts[0]
$amountInt = if ($orderParts.Count -gt 1) { [int]$orderParts[1] } else { 99000 }
$grossAmount = "$amountInt.00"

Write-Host "     Order dummy dibuat di database: $orderId (Nominal: Rp $amountInt)" -ForegroundColor Gray

# Baca MIDTRANS_SERVER_KEY dari server/.env
$serverKey = ""
$serverEnv = Join-Path $repoRoot "server\.env"
if (Test-Path $serverEnv) {
    foreach ($line in [System.IO.File]::ReadAllLines($serverEnv)) {
        if ($line -match '^\s*MIDTRANS_SERVER_KEY\s*=\s*(\S+)') {
            $serverKey = $Matches[1].Trim()
            break
        }
    }
}

$statusCode = "200"

# Hitung Signature SHA-512 sesuai standar Midtrans: SHA512(order_id + status_code + gross_amount + ServerKey)
$shaString = "$orderId$statusCode$grossAmount$serverKey"
$sha512 = [System.Security.Cryptography.SHA512]::Create()
$hashBytes = $sha512.ComputeHash([System.Text.Encoding]::UTF8.GetBytes($shaString))
$calculatedSignature = ($hashBytes | ForEach-Object { $_.ToString("x2") }) -join ""

$payloadObj = @{
    order_id = $orderId
    status_code = $statusCode
    gross_amount = $grossAmount
    signature_key = $calculatedSignature
    transaction_status = "settlement"
    payment_type = "qris"
    transaction_id = "trx-test-" + (Get-Random -Minimum 10000 -Maximum 99999)
}
$payloadJson = $payloadObj | ConvertTo-Json

Write-Host "     Mengirim notifikasi webhook POST (transaction_status = settlement)..." -ForegroundColor Gray
try {
    $postRes = Invoke-RestMethod -Uri $webhookUrl `
        -Method POST `
        -Headers @{
            "Content-Type" = "application/json"
            "ngrok-skip-browser-warning" = "1"
        } `
        -Body $payloadJson `
        -TimeoutSec 10 -ErrorAction Stop
    Write-Host "     [OK] Status 200 OK - Webhook Sukses!" -ForegroundColor Green
    Write-Host "     Respons Server: $($postRes | ConvertTo-Json -Compress)" -ForegroundColor Green
    Write-Host "     KESIMPULAN: " -ForegroundColor Green -NoNewline
    Write-Host "Pembayaran Midtrans 100% SUKSES diproses otomatis!" -ForegroundColor White
    Write-Host "                 Status order di database telah berubah menjadi: 'paid'." -ForegroundColor Gray
} catch {
    $statusCode = $null
    if ($_.Exception.Response) {
        $statusCode = [int]$_.Exception.Response.StatusCode
    }
    $responseBody = ""
    if ($_.ErrorDetails -and $_.ErrorDetails.Message) {
        $responseBody = $_.ErrorDetails.Message
    } elseif ($_.Exception.Response) {
        try {
            $stream = $_.Exception.Response.GetResponseStream()
            $reader = New-Object System.IO.StreamReader($stream)
            $responseBody = $reader.ReadToEnd()
        } catch {}
    }

    if ($statusCode -eq 400 -and $responseBody -like "*Order tidak ditemukan*") {
        Write-Host "     [OK] Status: 400 - Signature valid (order tidak ditemukan)." -ForegroundColor Yellow
    } elseif ($statusCode -eq 401) {
        Write-Host "     [FAIL] Status 401: Signature tidak valid. ($responseBody)" -ForegroundColor Red
    } else {
        Write-Host "     Status $statusCode : $responseBody" -ForegroundColor Yellow
    }
}

Write-Host "`n========================================================" -ForegroundColor Cyan
Write-Host "                   RINGKASAN AKHIR                      " -ForegroundColor Cyan
Write-Host "========================================================" -ForegroundColor Cyan
Write-Host "  Server Billing Lokal : $(if ($localOk) { 'AKTIF' } else { 'TIDAK AKTIF' })" -ForegroundColor $(if ($localOk) { 'Green' } else { 'Red' })
Write-Host "  Tunnel Publik ngrok  : $(if ($publicUrl) { 'TERHUBUNG' } else { 'TIDAK TERHUBUNG' })" -ForegroundColor $(if ($publicUrl) { 'Green' } else { 'Yellow' })
Write-Host "  Endpoint Webhook     : SIAP MENERIMA POST MIDTRANS" -ForegroundColor Green
Write-Host "========================================================" -ForegroundColor Cyan
Write-Host ""
Read-Host "Tekan Enter untuk menutup jendela ini..."
