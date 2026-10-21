---
title: Kasir POS Billing
emoji: 🧾
colorFrom: blue
colorTo: indigo
sdk: docker
pinned: false
---

# Webserver Billing POS (Hugging Face Space)

FastAPI + SQLite untuk aktivasi lisensi, langganan, dan roadmap POS.
Sumber: folder `server/` di https://github.com/scriptwriter123/kasir-pos

## Variabel/Secret yang perlu diisi (Settings → Variables and secrets)

| Key | Jenis | Nilai |
| --- | --- | --- |
| `BASE_URL` | Variable | `https://<user>-<space>.hf.space` (URL Space ini sendiri) |
| `ADMIN_PASSWORD` | Secret | password admin dashboard `/admin` |
| `LICENSE_PRIVATE_KEY_PEM` | Secret | isi utuh file private key Ed25519 (`.pem`) |
| `LICENSE_PRIVATE_KEY_PASSPHRASE` | Secret | passphrase key (bila ada) |
| `MIDTRANS_SERVER_KEY` | Secret | opsional; tanpa ini pakai ATM/transfer simulasi |
| `MIDTRANS_SNAP_CLIENT_KEY` | Secret | opsional, untuk Snap.js |

Tanpa `LICENSE_PRIVATE_KEY_PEM`, server jalan tetapi penerbitan lisensi
gagal (`SigningError`) — isi secret ini agar aktivasi otomatis berfungsi.

## Catatan paket gratis

- Space tidur setelah ~48 jam tanpa akses; bangunkan dengan membuka URL-nya
  (cold start 1–2 menit).
- Disk bersifat sementara: `billing.db` hilang saat restart/sleep. Aktifkan
  **Persistent Storage** (berbayar) bila ingin data langganan bertahan.
- Setelah perubahan konfigurasi secret/variable, restart Space
  (Settings → Restart Space).
