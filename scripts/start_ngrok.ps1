<#
.SYNOPSIS
    Tunnel ngrok agar webserver billing POS bisa diakses dari luar jaringan lokal.

.DESCRIPTION
    1. Menyalakan tunnel https ke webserver billing (default 127.0.0.1:8001).
    2. Menulis URL publik ke:
         - billing_server_url di .env POS (root)
         - BASE_URL, MIDTRANS_NOTIFICATION_URL di server/.env (billing server)
    3. Menyinkronkan MIDTRANS_SERVER_KEY dari .env root ke server/.env.
    Semua nilai lama dicadangkan dan dikembalikan saat -Stop.

    ngrok v3 WAJIB punya authtoken (akun gratis):
      1. Daftar      : https://dashboard.ngrok.com/signup
      2. Salin token : https://dashboard.ngrok.com/get-started/your-authtoken
      3. Simpan      : ngrok config add-authtoken <token>
         (atau jalankan script ini dengan -AuthToken <token> sekali saja)

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\start_ngrok.ps1 -AuthToken 2AbCdEf...

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\start_ngrok.ps1

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\start_ngrok.ps1 -StartServer

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\start_ngrok.ps1 -Stop
#>
[CmdletBinding()]
param(
    # Port webserver billing POS yang dipublikasikan.
    [int]$Port = 8001,
    # Authtoken ngrok sekali pakai: disimpan ke konfigurasi ngrok.
    [string]$AuthToken = "",
    # Hanya tampilkan URL publik; jangan menyentuh file .env manapun.
    [switch]$NoUpdateEnv,
    # Nyalakan uvicorn server billing bila port belum mendengarkan.
    [switch]$StartServer,
    # Hentikan tunnel dan kembalikan semua .env ke nilai sebelum tunnel.
    [switch]$Stop,
    # Berapa lama menunggu tunnel naik (detik).
    [int]$TimeoutSec = 60,
    # Path ngrok.exe bila tidak ada di PATH.
    [string]$NgrokExe = "",
    # Domain custom (ngrok Pro): misal https://billing.anjaysoftware.id
    [string]$Domain = ""
)

$ErrorActionPreference = "Stop"
$repoRoot       = Split-Path -Parent $PSScriptRoot
$envFile        = Join-Path $repoRoot ".env"
$envBackup      = Join-Path $repoRoot ".env.ngrok-backup"
$serverEnvFile  = Join-Path $repoRoot "server\.env"
$serverEnvBackup = Join-Path $repoRoot "server\.env.ngrok-backup"
$ngrokConfig    = Join-Path $env:LOCALAPPDATA "ngrok\ngrok.yml"
$ngrokLog       = Join-Path $repoRoot "ngrok.log"
$ngrokStdout    = Join-Path $repoRoot "ngrok.stdout.log"
$ngrokStderr    = Join-Path $repoRoot "ngrok.stderr.log"
$tunnelsUrl     = "http://127.0.0.1:4040/api/tunnels"
$localUrl       = "http://127.0.0.1:$Port"
$utf8NoBom      = New-Object System.Text.UTF8Encoding($false)

function Write-Step([string]$msg) { Write-Host "==> $msg" -ForegroundColor Cyan }
function Write-Note([string]$msg) { Write-Host "    $msg" }
function Write-Ok([string]$msg)   { Write-Host "    $msg" -ForegroundColor Green }
function Write-Warn([string]$msg) { Write-Host "    $msg" -ForegroundColor Yellow }

# -----------------------------------------------------------------------------
# generic env helpers
# -----------------------------------------------------------------------------

function Get-FileEnvValue([string]$file, [string]$key) {
    if (-not (Test-Path $file)) { return $null }
    $pattern = '^\s*' + [regex]::Escape($key) + '\s*=(.*)$'
    foreach ($line in [System.IO.File]::ReadAllLines($file)) {
        if ($line -match $pattern) { return $Matches[1].Trim().Trim('"').Trim("'") }
    }
    return $null
}

function Set-FileEnvValue([string]$file, [string]$key, [string]$value) {
    $lines = @()
    if (Test-Path $file) { $lines = @([System.IO.File]::ReadAllLines($file)) }
    $keyPattern = '^\s*' + [regex]::Escape($key) + '\s*='
    $found = $false
    $updated = @()
    foreach ($line in $lines) {
        if ($line -match $keyPattern) {
            $found = $true
            $updated += "$key=$value"
        } else {
            $updated += $line
        }
    }
    if (-not $found) {
        $updated += ""
        $updated += "$key=$value"
    }
    [System.IO.File]::WriteAllLines($file, $updated, $utf8NoBom)
}

# Shortcut helpers targeting the root .env (backwards-compat)
function Get-EnvValue([string]$key) { Get-FileEnvValue $envFile $key }
function Set-EnvValue([string]$key, [string]$value) { Set-FileEnvValue $envFile $key $value }

# -----------------------------------------------------------------------------
# other helpers
# -----------------------------------------------------------------------------

function Find-Ngrok {
    param([string]$explicit)
    if ($explicit) {
        if (Test-Path $explicit) { return (Resolve-Path $explicit).Path }
        throw "NgrokExe tidak ditemukan: $explicit"
    }
    $command = Get-Command ngrok -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }
    $fallback = Join-Path $env:LOCALAPPDATA "Programs\ngrok\ngrok.exe"
    if (Test-Path $fallback) { return $fallback }
    return $null
}

function Test-NgrokToken {
    if (-not (Test-Path $ngrokConfig)) { return $false }
    foreach ($line in [System.IO.File]::ReadAllLines($ngrokConfig)) {
        if ($line -match '^\s*authtoken\s*:\s*\S+') { return $true }
    }
    return $false
}

function Test-PortListening([int]$port) {
    try {
        $client = New-Object System.Net.Sockets.TcpClient
        $client.Connect("127.0.0.1", $port)
        $client.Close()
        return $true
    } catch { return $false }
}

function Get-Tunnels {
    try { return Invoke-RestMethod -Uri $tunnelsUrl -TimeoutSec 4 -ErrorAction Stop }
    catch { return $null }
}

function Select-PublicUrl($payload, [int]$port) {
    if ($null -eq $payload -or $null -eq $payload.tunnels) { return $null }
    $fallback = $null
    foreach ($tunnel in $payload.tunnels) {
        $addr = ""
        if ($tunnel.config) { $addr = [string]$tunnel.config.addr }
        if ($addr -notmatch [string]$port) { continue }
        $url = [string]$tunnel.public_url
        if ($url -like "https://*") { return $url }
        if (-not $fallback -and $url -like "http://*") { $fallback = $url }
    }
    return $fallback
}

function Show-LogTail([string]$path) {
    if (-not (Test-Path $path)) { return }
    Write-Host "    --- $($path) ---" -ForegroundColor DarkGray
    Get-Content $path -Tail 15 | ForEach-Object { Write-Host "    $_" -ForegroundColor DarkGray }
}

# -----------------------------------------------------------------------------
# -Stop: hentikan tunnel dan kembalikan semua .env
# -----------------------------------------------------------------------------
if ($Stop) {
    Write-Step "Menghentikan tunnel ngrok..."
    $running = @(Get-Process -Name "ngrok" -ErrorAction SilentlyContinue)
    foreach ($process in $running) {
        Stop-Process -Id $process.Id -Force
        Write-Note "ngrok PID $($process.Id) dihentikan"
    }
    if ($running.Count -eq 0) { Write-Note "tidak ada proses ngrok yang berjalan" }

    if (-not $NoUpdateEnv) {
        # root .env
        if (Test-Path $envBackup) {
            Copy-Item $envBackup $envFile -Force
            Remove-Item $envBackup -Force
            Write-Step ".env root dikembalikan dari cadangan"
        } elseif (Test-Path $envFile) {
            Set-EnvValue "billing_server_url" $localUrl
            Write-Step "billing_server_url dikembalikan ke $localUrl"
        }

        # server/.env
        if (Test-Path $serverEnvBackup) {
            Copy-Item $serverEnvBackup $serverEnvFile -Force
            Remove-Item $serverEnvBackup -Force
            Write-Step "server/.env dikembalikan dari cadangan"
        } elseif (Test-Path $serverEnvFile) {
            Set-FileEnvValue $serverEnvFile "BASE_URL" $localUrl
            Set-FileEnvValue $serverEnvFile "MIDTRANS_NOTIFICATION_URL" ""
            Write-Step "server/.env BASE_URL dikembalikan ke $localUrl"
            Write-Step "server/.env MIDTRANS_NOTIFICATION_URL dikosongkan"
        }
    }

    Write-Host ""
    Write-Host "Selesai." -ForegroundColor Green
    Write-Warn "Restart server billing agar membaca nilai .env yang sudah dikembalikan."
    return
}

# -----------------------------------------------------------------------------
# Persiapan
# -----------------------------------------------------------------------------
$ngrok = Find-Ngrok $NgrokExe
if (-not $ngrok) {
    Write-Host "ngrok tidak ditemukan di sistem." -ForegroundColor Red
    Write-Host "  Install : winget install --id Ngrok.Ngrok -e"
    Write-Host "  Atau    : https://ngrok.com/download"
    exit 1
}
Write-Note "ngrok: $ngrok"

if ($AuthToken) {
    Write-Step "Menyimpan authtoken ngrok..."
    & $ngrok config add-authtoken $AuthToken 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Gagal menyimpan authtoken." -ForegroundColor Red
        exit 1
    }
    Write-Ok "Authtoken tersimpan."
}

if (-not (Test-NgrokToken)) {
    Write-Host "Authtoken ngrok belum dikonfigurasi (ngrok v3 wajib autentikasi)." -ForegroundColor Yellow
    Write-Host "  1. Daftar gratis  : https://dashboard.ngrok.com/signup"
    Write-Host "  2. Salin token    : https://dashboard.ngrok.com/get-started/your-authtoken"
    Write-Host "  3. Jalankan ulang : powershell -ExecutionPolicy Bypass -File scripts\start_ngrok.ps1 -AuthToken <token>"
    exit 2
}

# -----------------------------------------------------------------------------
# Webserver billing
# -----------------------------------------------------------------------------
if (-not (Test-PortListening $Port)) {
    if ($StartServer) {
        Write-Step "Menyalakan webserver billing di port $Port..."
        $python = Join-Path $repoRoot "venv\Scripts\python.exe"
        if (-not (Test-Path $python)) { $python = "python" }
        Start-Process -FilePath $python `
            -ArgumentList @("-m", "uvicorn", "server.app.main:app", "--host", "127.0.0.1", "--port", "$Port") `
            -WorkingDirectory $repoRoot -WindowStyle Minimized
        for ($attempt = 0; $attempt -lt 40 -and -not (Test-PortListening $Port); $attempt++) {
            Start-Sleep -Milliseconds 500
        }
        if (Test-PortListening $Port) {
            Write-Ok "Webserver billing hidup di port $Port."
        } else {
            Write-Warn "Webserver belum merespons di port $Port (lanjut)."
        }
    }
}

# -----------------------------------------------------------------------------
# Mulai tunnel (atau reuse yang sudah ada)
# -----------------------------------------------------------------------------
if (-not (Test-PortListening $Port)) {
    Write-Host "Webserver billing port $Port belum aktif - tunnel akan membalas 502." -ForegroundColor Yellow
    Write-Host "  Nyalakan dulu, atau ulangi dengan -StartServer." -ForegroundColor Yellow
}

$url = $null
$existing = Get-Tunnels
if ($existing) {
    $url = Select-PublicUrl $existing $Port
    if (-not $url) {
        Write-Host "ngrok sudah berjalan untuk port lain." -ForegroundColor Yellow
        Write-Host "  Hentikan dulu: powershell -File scripts\start_ngrok.ps1 -Stop"
        exit 1
    }
    Write-Step "Memakai tunnel yang sudah berjalan"
} else {
    Write-Step "Menyalakan tunnel ngrok -> $localUrl"
    foreach ($logFile in @($ngrokLog, $ngrokStdout, $ngrokStderr)) {
        if (Test-Path $logFile) { Remove-Item $logFile -Force -ErrorAction SilentlyContinue }
    }
    $ngrokArgs = @("http", "127.0.0.1:$Port", "--log=`"$ngrokLog`"", "--log-level=warn")
    if ($Domain) { $ngrokArgs += "--domain=$Domain" }
    Start-Process -FilePath $ngrok `
        -ArgumentList $ngrokArgs `
        -RedirectStandardOutput $ngrokStdout `
        -RedirectStandardError  $ngrokStderr `
        -WindowStyle Hidden
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline -and -not $url) {
        Start-Sleep -Milliseconds 700
        $url = Select-PublicUrl (Get-Tunnels) $Port
    }
}

if (-not $url) {
    Write-Host "Tunnel gagal naik dalam $TimeoutSec detik." -ForegroundColor Red
    Show-LogTail $ngrokStderr
    Show-LogTail $ngrokLog
    exit 1
}

$webhookUrl = $url.TrimEnd("/") + "/webhooks/payment/midtrans"

# -----------------------------------------------------------------------------
# Perbarui semua .env
# -----------------------------------------------------------------------------
if (-not $NoUpdateEnv) {

    # root .env: billing_server_url
    Write-Step "Memperbarui .env root..."
    if (-not (Test-Path $envFile)) {
        Write-Warn "File .env tidak ada di $repoRoot - dilewati."
    } else {
        $current = Get-EnvValue "billing_server_url"
        if ($current -ne $url) {
            if (-not (Test-Path $envBackup)) {
                Copy-Item $envFile $envBackup
                Write-Note "cadangan .env -> .env.ngrok-backup"
            }
            Set-EnvValue "billing_server_url" $url
        }
        Write-Ok "billing_server_url = $url"
    }

    # server/.env
    Write-Step "Memperbarui server/.env..."
    if (-not (Test-Path $serverEnvFile)) {
        Write-Warn "File server/.env tidak ada - dilewati."
    } else {
        # Cadangkan sekali saja (sebelum nilai berubah)
        if (-not (Test-Path $serverEnvBackup)) {
            Copy-Item $serverEnvFile $serverEnvBackup
            Write-Note "cadangan server/.env -> server/.env.ngrok-backup"
        }

        # BASE_URL
        $oldBase = Get-FileEnvValue $serverEnvFile "BASE_URL"
        Set-FileEnvValue $serverEnvFile "BASE_URL" $url
        $prevBase = if ($oldBase) { $oldBase } else { "(kosong)" }
        Write-Ok "BASE_URL = $url  (sebelumnya: $prevBase)"

        # MIDTRANS_NOTIFICATION_URL
        $oldNotif = Get-FileEnvValue $serverEnvFile "MIDTRANS_NOTIFICATION_URL"
        Set-FileEnvValue $serverEnvFile "MIDTRANS_NOTIFICATION_URL" $webhookUrl
        Write-Ok "MIDTRANS_NOTIFICATION_URL = $webhookUrl"
        if ($oldNotif -and $oldNotif -ne $webhookUrl) {
            Write-Note "  (sebelumnya: $oldNotif)"
        }

        # MIDTRANS_SERVER_KEY - sinkronkan dari root .env jika ada
        $rootKey = Get-EnvValue "MIDTRANS_SERVER_KEY"
        if ($rootKey) {
            $serverKey = Get-FileEnvValue $serverEnvFile "MIDTRANS_SERVER_KEY"
            if ($serverKey -ne $rootKey) {
                Set-FileEnvValue $serverEnvFile "MIDTRANS_SERVER_KEY" $rootKey
                Write-Ok "MIDTRANS_SERVER_KEY disinkronkan dari root .env"
            } else {
                Write-Ok "MIDTRANS_SERVER_KEY sudah sinkron"
            }
        } else {
            Write-Warn "MIDTRANS_SERVER_KEY tidak ditemukan di root .env - dilewati."
        }
    }
}

# -----------------------------------------------------------------------------
# Ringkasan
# -----------------------------------------------------------------------------
Write-Host ""
Write-Host "========================================================" -ForegroundColor Green
Write-Host "               TUNNEL NGROK AKTIF                       " -ForegroundColor Green
Write-Host "========================================================" -ForegroundColor Green
Write-Host "  URL publik     : $url" -ForegroundColor White
Write-Host "  Webhook URL    : $webhookUrl" -ForegroundColor White
Write-Host "  Lokal          : $localUrl"
Write-Host "  Inspektor      : http://127.0.0.1:4040"
Write-Host "  Log            : $ngrokLog"
Write-Host ""
Write-Host "  Berhenti       : powershell -ExecutionPolicy Bypass -File scripts\start_ngrok.ps1 -Stop" -ForegroundColor DarkGray
Write-Host ""

if (-not $NoUpdateEnv) {
    Write-Host "LANGKAH BERIKUTNYA:" -ForegroundColor Yellow
    Write-Host "  Restart webserver billing agar membaca .env yang baru:" -ForegroundColor Yellow
    Write-Host "    powershell -ExecutionPolicy Bypass -File scripts\start_ngrok.ps1 -Stop" -ForegroundColor DarkGray
    Write-Host "    powershell -ExecutionPolicy Bypass -File scripts\start_ngrok.ps1 -StartServer" -ForegroundColor DarkGray
    Write-Host ""
}

Write-Host "Catatan paket gratis: URL berubah tiap tunnel restart." -ForegroundColor DarkGray
Write-Host "  Jalankan script ini lagi setelah restart untuk memperbarui .env." -ForegroundColor DarkGray
exit 0
