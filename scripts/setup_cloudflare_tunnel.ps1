# File: scripts\setup_cloudflare_tunnel.ps1
# Setup Cloudflare Tunnel + DuckDNS untuk AnjaySoft POS

param(
    [Parameter(Mandatory=$true)]
    [string]$DuckDNSDomain = "anjaysoftware.duckdns.org",

    [Parameter(Mandatory=$true)]
    [string]$TunnelName = "anjay-pos",

    [int]$LocalPort = 8001
)

Write-Host "================================================================" -ForegroundColor Cyan
Write-Host "  CLOUDFLARE TUNNEL + DUCKDNS SETUP - ANJAYSOFT POS" -ForegroundColor Cyan
Write-Host "================================================================" -ForegroundColor White
Write-Host ""

$CloudflaredExe = "${env:LOCALAPPDATA}\Programs\cloudflared\cloudflared.exe"
if (-not (Test-Path $CloudflaredExe)) {
    Write-Host "[ERROR] cloudflared tidak ditemukan: $CloudflaredExe" -ForegroundColor Red
    Write-Host "Install: winget install Cloudflare.cloudflared" -ForegroundColor Yellow
    exit 1
}
Write-Host "[OK] cloudflared: $CloudflaredExe" -ForegroundColor Green

# ============================================================
# STEP 1: Login Cloudflare (WAJIB BROWSER - 1 kali saja)
# ============================================================
Write-Host "`n[STEP 1/5] Login Cloudflare Tunnel..." -ForegroundColor Yellow
Write-Host "  -> Akan membuka browser. Login ke Cloudflare, klik 'Allow'." -ForegroundColor Gray
Write-Host "  -> Tekan ENTER setelah selesai login di browser..." -ForegroundColor Gray
Read-Host "  Tekan ENTER untuk lanjutkan login"
& $CloudflaredExe tunnel login
if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERROR] Login gagal. Coba manual: $CloudflaredExe tunnel login" -ForegroundColor Red
    exit 1
}
Write-Host "[OK] Login berhasil" -ForegroundColor Green

# ============================================================
# STEP 2: Buat Tunnel Baru
# ============================================================
Write-Host "`n[STEP 2/5] Membuat tunnel: $TunnelName..." -ForegroundColor Yellow
$tunnelOutput = & $CloudflaredExe tunnel create $TunnelName 2>&1
Write-Host "  Output: $tunnelOutput" -ForegroundColor Gray

if ($tunnelOutput -match "Created tunnel: .* with uuid: (.+)") {
    $TunnelUUID = $Matches[1].Trim()
    Write-Host "[OK] Tunnel UUID: $TunnelUUID" -ForegroundColor Green
} else {
    Write-Host "[ERROR] Gagal parse UUID tunnel. Output:" -ForegroundColor Red
    Write-Host $tunnelOutput
    exit 1
}

# ============================================================
# STEP 3: Buat Config.yml
# ============================================================
Write-Host "`n[STEP 3/5] Membuat config.yml..." -ForegroundColor Yellow
$ConfigPath = "${env:APPDATA}\cloudflared\config.yml"
$ConfigDir = Split-Path $ConfigPath
if (-not (Test-Path $ConfigDir)) { New-Item -ItemType Directory -Path $ConfigDir | Out-Null }

$configContent = @"
tunnel: $TunnelUUID
credentials-file: ${env:APPDATA}\cloudflared\${TunnelUUID}.json

ingress:
  - hostname: $DuckDNSDomain
    service: http://localhost:$LocalPort
  - service: http_status:404
"@

Set-Content -Path $ConfigPath -Value $configContent -Encoding UTF8
Write-Host "[OK] Config: $ConfigPath" -ForegroundColor Green

# ============================================================
# STEP 4: Setup CNAME di DuckDNS
# ============================================================
Write-Host "`n[STEP 4/5] Setup CNAME di DuckDNS Dashboard..." -ForegroundColor Yellow
Write-Host "  ---------------------------------------------------" -ForegroundColor White
Write-Host "  BUKA BROWSER: https://www.duckdns.org" -ForegroundColor Cyan
Write-Host "  LOGIN -> Tambah/Edit subdomain:" -ForegroundColor White
Write-Host "    Subdomain: anjaysoftware" -ForegroundColor White
Write-Host "    Type: CNAME" -ForegroundColor White
Write-Host "    Target: $TunnelUUID.cfargotunnel.com" -ForegroundColor White
Write-Host "  Klik 'Update' / 'Save'" -ForegroundColor White
Write-Host "  ---------------------------------------------------" -ForegroundColor White
Write-Host "  Tekan ENTER setelah selesai setup CNAME di DuckDNS..." -ForegroundColor Gray
Read-Host ""

# ============================================================
# STEP 5: Jalankan Tunnel
# ============================================================
Write-Host "`n[STEP 5/5] Menjalankan tunnel..." -ForegroundColor Yellow
Write-Host "  Perintah: cloudflared tunnel run --config $ConfigPath $TunnelName" -ForegroundColor Gray
Write-Host "  Tekan Ctrl+C untuk stop." -ForegroundColor Gray
Write-Host ""

# Jalankan tunnel (foreground, bukan background)
& $CloudflaredExe tunnel run --config $ConfigPath $TunnelName

# ============================================================
# SELESAI
# ============================================================
Write-Host "`n[SELESAI] Tunnel berhenti." -ForegroundColor Green
Write-Host "Akses: https://$DuckDNSDomain" -ForegroundColor Cyan