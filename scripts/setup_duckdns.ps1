# File: scripts\setup_duckdns.ps1 - Setup DuckDNS + Cloudflared Tunnel untuk POS

# ============================================================
# KONFIGURASI
# ============================================================
$Domain = "anjaysoftware.duckdns.org"       # Domain DuckDNS yang sudah dibuat
$TunnelName = "anjay-pos"                    # Nama tunnel cloudflared
$LocalPort = 8001                            # Port server lokal (FastAPI)
$DuckDNS_Token = Read-Host "Masukkan DuckDNS Token (dari dashboard duckdns.org)"  # ATAU kosongkan dan setup CNAME manual

Write-Host "`n=== SETUP DUCKDNS + CLOUDFLARED (Otomatis/Manual) ===" -ForegroundColor Cyan
Write-Host "-------------------------------------------------------" -ForegroundColor White

# ============================================================
# 1. Pastikan cloudflared sudah terinstall
# ============================================================
$CloudflaredExe = "${env:LOCALAPPDATA}\Programs\cloudflared\cloudflared.exe"
if (-not (Test-Path $CloudflaredExe)) {
    Write-Host "[ERROR] cloudflared tidak ditemukan di $CloudflaredExe" -ForegroundColor Red
    Write-Host "Jalankan manual: winget install Cloudflare.cloudflared" -ForegroundColor Yellow
    return
}
Write-Host "[OK] cloudflared terinstall" -ForegroundColor Green

# ============================================================
# 2. Login Cloudflare Tunnel (wajib sekali, terbuka browser)
# ============================================================
Write-Host "[INFO] cloudflared tunnel login membuka browser..." -ForegroundColor Yellow
& $CloudflaredExe tunnel login

# Catatan: Langkah ini MEMERlukan browser. Di CLI headless ini mungkin gagal/terus.
# Jika login gagal, login manual di https://dash.cloudflare.com/profile/api-tokens
# dan gunakan Cloudflare API token untuk langkah berikutnya.

# ============================================================
# 3. Buat/Ambil Tunnel
# ============================================================
Write-Host "[INFO] Membuat tunnel: $TunnelName" -ForegroundColor Cyan
$tunnelInfo = & $CloudflaredExe tunnel create $TunnelName 2>&1
Write-Host "Output tunnel: $tunnelInfo" -ForegroundColor Gray

# Extract tunnel UUID (parse output untuk dapat UUID)
# Contoh output: "Created tunnel: anjay-pos with uuid: abc123..."
$TunnelUUID = if ($tunnelInfo -match "Created tunnel: .* with uuid: (.*)") { $Matches[1] } else { Write-Warning "Gagal parse UUID tunnel, cek output di atas"; $null }

if (-not $TunnelUUID) {
    Write-Host "! Gagal membuat tunnel. Silakan cek manual." -ForegroundColor Red
    return
}
Write-Host "[OK] Tunnel dibuat: $TunnelName (UUID: $TunnelUUID)" -ForegroundColor Green

# ============================================================
# 4. Setup Route ke DuckDNS domain
# ============================================================
Write-Host "[INFO] Setup route domain: $Domain -> tunnel $TunnelUUID" -ForegroundColor Cyan

# Bisa pakai Cloudflare API atau manual DNS CNAME
if ($DuckDNS_Token) {
    # Opsi A: Update DuckDNS via API (CNAME ke cloudflared tunnel endpoint)
    # DuckDNS API endpoint: https://www.duckdns.org/update?domains=...&token=...
    # DuckDNS mendukung A record, tapi untuk CNAME cloudflared perlu pakai Cloudflare
    Write-Host "  -> Opsi A: Update DNS DuckDNS via API (mendukung A record saja)" -ForegroundColor White
    $apiUrl = "https://www.duckdns.org/update?domains=$Domain&token=$DuckDNS_Token&ip=auto"
    $result = Invoke-RestMethod -Uri $apiUrl -Method Get
    Write-Host "  DuckDNS API Result: $($result.status)" -ForegroundColor Gray
    Write-Host "  -> Untuk CNAME ke cloudflared, gunakan Cloudflare Dashboard atau setup manual CNAME di DuckDNS" -ForegroundColor Yellow
    
    # Opsi alternatif: gunakan Cloudflare API jika domain sudah di Cloudflare
    Write-Host "  -> Jika domain anjaysoftware berada di Cloudflare, bisa gunakan Cloudflare API" -ForegroundColor Gray
} else {
    # Opsi B: Setup DNS CNAME manual
    Write-Host "  -> Opsi B: Setup CNAME manual di Dashboard DuckDNS" -ForegroundColor White
    Write-Host "      Type: CNAME" -ForegroundColor White
    Write-Host "      Name: anjay-pos (atau subdomain bebas)" -ForegroundColor White
    Write-Host "      Target: $TunnelUUID.cfargotunnel.com" -ForegroundColor White
    Write-Host "      1. Login duckdns.org" -ForegroundColor White
    Write-Host "      2. Tambah subdomain: $Domain" -ForegroundColor White
    Write-Host "      3. CNAME ke: $TunnelUUID.cfargotunnel.com" -ForegroundColor White
}

# ============================================================
# 5. Buat config cloudflared
# ============================================================
Write-Host "[INFO] Membuat config cloudflared" -ForegroundColor Cyan
$ConfigPath = "${env:APPDATA}\cloudflared\config.yml"
$ConfigDir = Split-Path $ConfigPath
if (-not (Test-Path $ConfigDir)) { New-Item -ItemType Directory -Path $ConfigDir | Out-Null }
Set-Content -Path $ConfigPath -Value @"
tunnel: $TunnelName
credentials-file: ${env:APPDATA}\cloudflared\${TunnelName}.json

ingress:
  - hostname: $Domain
    service: http://localhost:$LocalPort
  - service: http_status:404
"@ -Encoding UTF8
Write-Host "[OK] Config: $ConfigPath" -ForegroundColor Green

# ============================================================
# 6. Jalankan tunnel cloudflared
# ============================================================
Write-Host "[INFO] Memulai tunnel..." -ForegroundColor Cyan
# Jalankan di background
$tunnelProcess = Start-Process -FilePath $CloudflaredExe -ArgumentList @("tunnel", "run", "-config", $ConfigPath, $TunnelName) -PassThru -WindowStyle Hidden
Write-Host "[OK] Tunnel berjalan di background (PID: $($tunnelProcess.Id))" -ForegroundColor Green

# Tunggu sebentar agar tunnel bisa register
Start-Sleep -Seconds 5

# ============================================================
# 7. Cek status dan update .env POS
# ============================================================
Write-Host "[INFO] Update file .env POS..." -ForegroundColor Cyan
$EnvPath = "C:\Users\ANJAY SOLUTION\Desktop\KASIR\.env"
if (Test-Path $EnvPath) {
    $envContent = Get-Content $EnvPath -Raw
    if ($envContent -match "billing_server_url=(.*)") {
        $newContent = $envContent -replace "billing_server_url=.*", "billing_server_url=https://$Domain"
        Set-Content -Path $EnvPath -Value $newContent -Encoding UTF8
        Write-Host "[OK] .env diperbarui: billing_server_url=https://$Domain" -ForegroundColor Green
    } else {
        Add-Content $EnvPath "`nbilling_server_url=https://$Domain"
        Write-Host "[OK] .env ditambahkan: billing_server_url=https://$Domain" -ForegroundColor Green
    }
} else {
    Write-Host "! .env tidak ditemukan di $EnvPath" -ForegroundColor Yellow
    Write-Host "Salurkan manual: billing_server_url=https://$Domain" -ForegroundColor White
}

# ============================================================
# 8. Selesai - Cara akses
# ============================================================
Write-Host "`n=== SETUP SELESAI ===" -ForegroundColor Green
Write-Host "Domain: https://$Domain" -ForegroundColor Cyan
Write-Host "Cara akses: buka browser lalu https://$Domain" -ForegroundColor White
Write-Host "Cara stop tunnel: Stop-Process -Name cloudflared -Force" -ForegroundColor Yellow
Write-Host "Lihat tunnel di: https://dash.cloudflare.com/tunnels" -ForegroundColor Gray

# Konfigurasi nanti: Task Scheduler untuk auto-reconnect jika perlu
Write-Host "`nPENTING: Konfigurasi Task Scheduler (opsional) untuk auto-start cloudflared di boot Windows" -ForegroundColor DarkYellow

pause