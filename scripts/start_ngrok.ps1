<#
.SYNOPSIS
    Tunnel ngrok agar webserver billing POS bisa diakses dari luar jaringan lokal.

.DESCRIPTION
    1. Menyalakan tunnel https ke webserver billing (default 127.0.0.1:8001).
    2. Menulis URL publik tersebut ke billing_server_url pada file .env POS
       (nilai lama dicadangkan ke .env.ngrok-backup, dikembalikan saat -Stop),
       sehingga POS memakai alamat publik setelah restart.

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
    # Hanya tampilkan URL publik; jangan menyentuh file .env POS.
    [switch]$NoUpdateEnv,
    # Nyalakan uvicorn server billing bila port belum mendengarkan.
    [switch]$StartServer,
    # Hentikan tunnel dan kembalikan .env ke nilai sebelum tunnel.
    [switch]$Stop,
    # Berapa lama menunggu tunnel naik (detik).
    [int]$TimeoutSec = 60,
    # Path ngrok.exe bila tidak ada di PATH.
    [string]$NgrokExe = ""
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$envFile = Join-Path $repoRoot ".env"
$envBackup = Join-Path $repoRoot ".env.ngrok-backup"
$ngrokConfig = Join-Path $env:LOCALAPPDATA "ngrok\ngrok.yml"
$ngrokLog = Join-Path $repoRoot "ngrok.log"
$ngrokStdout = Join-Path $repoRoot "ngrok.stdout.log"
$ngrokStderr = Join-Path $repoRoot "ngrok.stderr.log"
$tunnelsUrl = "http://127.0.0.1:4040/api/tunnels"
$localUrl = "http://127.0.0.1:$Port"

function Write-Step([string]$message) { Write-Host "==> $message" -ForegroundColor Cyan }
function Write-Note([string]$message) { Write-Host "    $message" }

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

function Get-EnvValue([string]$key) {
    if (-not (Test-Path $envFile)) { return $null }
    $pattern = '^\s*' + [regex]::Escape($key) + '\s*=(.*)$'
    foreach ($line in [System.IO.File]::ReadAllLines($envFile)) {
        if ($line -match $pattern) { return $Matches[1].Trim().Trim('"').Trim("'") }
    }
    return $null
}

function Set-EnvValue([string]$key, [string]$value) {
    $lines = @()
    if (Test-Path $envFile) { $lines = @([System.IO.File]::ReadAllLines($envFile)) }
    $pattern = '^\s*' + [regex]::Escape($key) + '\s*='
    $found = $false
    $updated = @()
    foreach ($line in $lines) {
        if ($line -match $pattern) {
            $found = $true
            $updated += "$key=$value"
        }
        else {
            $updated += $line
        }
    }
    if (-not $found) {
        $updated += ""
        $updated += "$key=$value"
    }
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllLines($envFile, $updated, $utf8NoBom)
}

function Test-PortListening([int]$port) {
    try {
        $client = New-Object System.Net.Sockets.TcpClient
        $client.Connect("127.0.0.1", $port)
        $client.Close()
        return $true
    }
    catch {
        return $false
    }
}

function Get-Tunnels {
    try {
        return Invoke-RestMethod -Uri $tunnelsUrl -TimeoutSec 4 -ErrorAction Stop
    }
    catch {
        return $null
    }
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

# ------------------------------------------------------------------ stop
if ($Stop) {
    Write-Step "Menghentikan tunnel ngrok..."
    $running = @(Get-Process -Name "ngrok" -ErrorAction SilentlyContinue)
    foreach ($process in $running) {
        Stop-Process -Id $process.Id -Force
        Write-Note "ngrok PID $($process.Id) dihentikan"
    }
    if ($running.Count -eq 0) { Write-Note "tidak ada proses ngrok yang berjalan" }
    if (-not $NoUpdateEnv) {
        if (Test-Path $envBackup) {
            Copy-Item $envBackup $envFile -Force
            Remove-Item $envBackup -Force
            Write-Step "billing_server_url dikembalikan dari .env.ngrok-backup"
        }
        elseif (Test-Path $envFile) {
            Set-EnvValue "billing_server_url" $localUrl
            Write-Step "billing_server_url dikembalikan ke $localUrl"
        }
    }
    Write-Host "Selesai." -ForegroundColor Green
    return
}

# --------------------------------------------------------------- persiapan
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
}

if (-not (Test-NgrokToken)) {
    Write-Host "Authtoken ngrok belum dikonfigurasi (ngrok v3 wajib autentikasi)." -ForegroundColor Yellow
    Write-Host "  1. Daftar gratis  : https://dashboard.ngrok.com/signup"
    Write-Host "  2. Salin token    : https://dashboard.ngrok.com/get-started/your-authtoken"
    Write-Host "  3. Jalankan ulang : powershell -ExecutionPolicy Bypass -File scripts\start_ngrok.ps1 -AuthToken <token>"
    exit 2
}

# --------------------------------------------------------- webserver billing
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
    }
}
if (-not (Test-PortListening $Port)) {
    Write-Host "Webserver billing port $Port belum aktif — tunnel akan membalas 502." -ForegroundColor Yellow
    Write-Host "  Nyalakan dulu, atau ulangi dengan -StartServer." -ForegroundColor Yellow
}

# ------------------------------------------------------------------ tunnel
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
}
else {
    Write-Step "Menyalakan tunnel ngrok -> $localUrl"
    foreach ($logFile in @($ngrokLog, $ngrokStdout, $ngrokStderr)) {
        if (Test-Path $logFile) { Remove-Item $logFile -Force -ErrorAction SilentlyContinue }
    }
    Start-Process -FilePath $ngrok `
        -ArgumentList @("http", "127.0.0.1:$Port", "--log=`"$ngrokLog`"", "--log=warn") `
        -RedirectStandardOutput $ngrokStdout `
        -RedirectStandardError $ngrokStderr `
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

# ------------------------------------------------- perbarui .env POS (opsional)
if (-not $NoUpdateEnv) {
    if (-not (Test-Path $envFile)) {
        Write-Host "File .env tidak ada di $repoRoot — billing_server_url tidak diperbarui." -ForegroundColor Yellow
    }
    else {
        $current = Get-EnvValue "billing_server_url"
        if ($current -eq $url) {
            Write-Step "billing_server_url sudah $url"
        }
        else {
            if (-not (Test-Path $envBackup)) {
                Copy-Item $envFile $envBackup
                Write-Note "cadangan .env -> .env.ngrok-backup"
            }
            Set-EnvValue "billing_server_url" $url
            Write-Step "billing_server_url: $(if ($current) { $current } else { '(kosong)' }) -> $url"
        }
    }
}

# ------------------------------------------------------------------ ringkasan
Write-Host ""
Write-Host "Tunnel publik aktif" -ForegroundColor Green
Write-Host "  URL publik : $url"
Write-Host "  Lokal      : $localUrl"
Write-Host "  Inspektor  : http://127.0.0.1:4040"
Write-Host "  Log        : $ngrokLog"
Write-Host "  Berhenti   : powershell -ExecutionPolicy Bypass -File scripts\start_ngrok.ps1 -Stop"
Write-Host ""
if (-not $NoUpdateEnv -and (Test-Path $envFile)) {
    Write-Host "Restart POS agar membaca billing_server_url yang baru." -ForegroundColor Yellow
}
Write-Host "Catatan paket gratis: URL https://... berlaku sampai proses ngrok berhenti." -ForegroundColor DarkGray
Write-Host "  Setelah tunnel berhenti/restart, jalankan script ini lagi untuk memperbarui .env." -ForegroundColor DarkGray
exit 0
