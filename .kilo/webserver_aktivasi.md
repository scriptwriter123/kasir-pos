# Rancangan produksi: POS Desktop Trial 7 Hari + Langganan Offline

Untuk aplikasi POS berbasis Python + PySide6, saya menyarankan sistem offline-first dengan lisensi digital bertanda tangan. Aplikasi tetap berjalan tanpa internet, pengguna tidak perlu menginstal ulang setelah membayar, dan website Anda mengelola akun, pembayaran, serta penerbitan lisensi.

Ada satu konsekuensi penting dari pilihan Anda: aplikasi yang sepenuhnya offline tidak dapat mengetahui secara langsung apakah langganan sudah dibatalkan atau diperpanjang di server. Karena itu, kita perlu menentukan kebijakan lisensi lokal.

## 1. Mekanisme yang akan digunakan

Website FastAPI

Registrasi akun, checkout pembayaran, manajemen paket dan penerbitan lisensi

Unduh lisensi digital setelah pembayaran

File lisensi bertanda tangan

Memuat ID lisensi, paket, masa berlaku, dan identitas instalasi

POS Desktop PySide6

Mengimpor lisensi, memverifikasi tanda tangan secara lokal, lalu membuka fitur berbayar

Trial 7 hari

Dimulai saat pertama kali diaktifkan.

Operasi offline

Kasir dan database lokal tidak memerlukan koneksi internet.

### Batas keamanan yang perlu dipahami

Tanda tangan digital mencegah pengguna membuat atau mengubah lisensi secara sembarangan. Namun, pada komputer milik pengguna, tidak ada cara yang sepenuhnya andal untuk mencegah pemalsuan waktu sistem, modifikasi executable, atau pemulihan backup pada aplikasi yang benar-benar offline.

Desain ini akan menggunakan:

- Ed25519: server menyimpan private key, aplikasi hanya membawa public key.
- Trial lokal 7 hari: dicatat dalam database lokal, disertai deteksi perubahan waktu yang mencurigakan.
- Lisensi berbayar: berlaku berdasarkan tanggal mulai dan berakhir yang ditandatangani server.
- Aktivasi tanpa instal ulang: pengguna mengimpor file lisensi melalui menu Aktivasi.
- Data toko tetap lokal: berakhirnya langganan tidak menghapus transaksi maupun stok.

Untuk langganan bulanan atau tahunan, pembaruan lisensi harus diunduh dan diimpor secara manual ketika komputer tersambung ke internet. Jika tidak ada koneksi sama sekali, aplikasi tidak bisa mengetahui status pembayaran terbaru.

## 2. Starter project dan kode implementasi

Saya sudah menyiapkan paket proyek Python yang dapat Anda unduh dan kembangkan.

POS Offline License Starter

ZIP · 13 file · Python + PySide6 + FastAPI

Berisi kerangka server lisensi, database, penandatangan lisensi, trial lokal, dan jendela aktivasi.

Unduh paket proyek ZIP

Saya juga sudah memeriksa sintaks seluruh berkas Python dalam paket. Pemeriksaan tersebut berhasil, tetapi belum berarti semua fungsi telah diuji secara integrasi.

### Isi proyek

server/

FastAPI, SQLAlchemy, database pelanggan, lisensi, pembayaran, dan penandatangan lisensi.

desktop/

Manajemen trial 7 hari, identitas instalasi, verifikasi tanda tangan, dan GUI impor lisensi PySide6.

scripts/

Pembuatan pasangan kunci Ed25519.

docs/

Checklist pengamanan dan persiapan produksi.

Catatan: paket ini adalah fondasi implementasi, belum merupakan sistem produksi siap jual. Pembayaran gateway, login pelanggan, penerbitan lisensi otomatis setelah pembayaran, dan penguncian setiap fitur premium pada aplikasi POS Anda masih perlu diintegrasikan.

## 3. Struktur database

Database server menggunakan SQLAlchemy sehingga Anda dapat memulai dengan SQLite untuk pengujian dan beralih ke PostgreSQL untuk produksi.

| Tabel       | Kolom penting                                                                 | Fungsi                          |
| ----------- | ----------------------------------------------------------------------------- | ------------------------------- |
| `customers` | `id`, `email`                                                                 | Data pelanggan                  |
| `licenses`  | `id`, `customer_id`, `device_id`, `plan`, `starts_at`, `expires_at`, `status` | Status dan masa berlaku lisensi |
| `payments`  | `gateway_event_id`, `order_id`, `amount_minor`, `currency`, `status`          | Catatan transaksi pembayaran    |

Untuk produksi, tambahkan tabel `orders`, `devices`, `license_events`, dan `subscription_history`. Dengan demikian, Anda dapat mengelola pergantian perangkat, riwayat perpanjangan, refund, dan audit aktivasi.

## 4. API lisensi

Endpoint awal yang sudah tersedia:

| Endpoint                            | Kegunaan                                            |
| ----------------------------------- | --------------------------------------------------- |
| `GET /health`                       | Memeriksa server                                    |
| `POST /admin/licenses/issue`        | Menerbitkan lisensi bertanda tangan untuk pengujian |
| `POST /webhooks/payment/{provider}` | Placeholder webhook pembayaran; belum aktif         |

Untuk alur produksi, tambahkan endpoint berikut:

- `POST /auth/register` dan `POST /auth/login`
- `POST /checkout/create` untuk membuat pesanan pembayaran.
- `GET /licenses/me` untuk mengambil lisensi milik pelanggan.
- `POST /licenses/renew` untuk penerbitan lisensi perpanjangan setelah pembayaran diverifikasi.
- `POST /devices/deactivate` untuk memindahkan lisensi ke perangkat lain.

Jangan membuat endpoint penerbitan lisensi publik tanpa autentikasi. Endpoint admin dalam starter hanya untuk pengembangan.

## 5. Integrasi pembayaran

Karena Anda belum menentukan gateway pembayaran yang akan dipakai, integrasi otomatis belum saya ikat ke penyedia tertentu. Alur yang benar adalah:

1. Website membuat pesanan dengan ID unik.
2. Pelanggan membayar melalui gateway.
3. Server memverifikasi tanda tangan webhook dan status transaksi melalui mekanisme resmi penyedia.
4. Server mencatat pembayaran secara idempoten agar webhook berulang tidak menerbitkan lisensi ganda.
5. Server membuat file lisensi baru yang ditandatangani.
6. Pelanggan mengunduh file lisensi lalu mengimpornya ke POS, tanpa instal ulang.

Untuk pilihan awal, Anda bisa mempertimbangkan Midtrans atau Xendit. Pilih satu dahulu agar integrasi dan pengujian lebih sederhana.

## 6. Tahap berikutnya untuk mengintegrasikan ke POS Anda

Agar implementasinya benar-benar sesuai aplikasi yang sudah Anda miliki, ada dua hal yang perlu ditentukan.

Gateway pembayaran utama

Midtrans (QRIS dan metode pembayaran lain sesuai akun)

Xendit

Transfer bank manual dengan verifikasi admin

Perilaku setelah Trial 7 hari

Fitur kasir terkunci, data tetap dapat dibaca dan diekspor

Fitur dasar tetap gratis, fitur premium terkunci

Format distribusi Windows

Installer `.exe` dengan PyInstaller

Folder portable tanpa installer

Lanjutkan implementasi lengkap

Setelah itu, kita bisa menghubungkan lisensi ke modul kasir, inventaris, laporan, dan pembayaran pada proyek Anda, bukan hanya membuat jendela aktivasi yang berdiri sendiri.