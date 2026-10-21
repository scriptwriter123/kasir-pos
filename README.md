# KASIR — POS Retail Offline-First

Fondasi Phase 1–2 untuk aplikasi POS desktop Windows berdasarkan dua spesifikasi PDF yang diberikan.

## Status implementasi
- Fase 1: dokumentasi arsitektur tersedia.
- Fase 2: SQLite, Alembic, migrasi, dan seed tersedia; skema saat ini mencakup
  33 tabel: 16 tabel inti, 10 tabel roadmap, laporan kasir harian, aturan harga
  spesial partai, dan ledger keuangan double-entry.
  Dokumen tidak merinci 37 definisi tabel lengkap, sehingga tabel sisanya perlu
  ditambahkan saat kebutuhan tiap domain ditetapkan.
- Fase 3: model dan repository dasar User, Product, Sale, Stock Movement, dan
  Shift tersedia.
- Fase 4–5: autentikasi dan checkout dasar tersedia, tetapi layanan bisnis dan
  pengujian transaksi belum lengkap.
- Fase 6–7: aplikasi desktop POS mencakup manajemen pengguna, alur kasir,
  aktivasi lisensi offline bertanda tangan, dan packaging Windows.

## Stack
Python 3.12+ / PySide6 / SQLAlchemy 2.x / SQLite / Alembic / Argon2 /
cryptography (Ed25519) / pydantic-settings / pytest

## Arsitektur
UI → Service → Repository → SQLAlchemy Models → SQLite

## Setup di Windows
```powershell
cd E:\POS\kasir
py -3.12 -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt

pytest -q
python main.py
```

Saat pertama dibuka, aplikasi meminta aktivasi lisensi offline, lalu meminta
pembuatan akun OWNER jika database masih kosong. Installer tidak menyertakan
akun demo, data contoh, atau database milik komputer pembuat. Schema dibuat
saat aplikasi dijalankan; data disimpan terpisah di
`%LOCALAPPDATA%\POSApp\data\`.

Lokasi data dapat dipindah ke satu folder bersama dengan environment variable
`POS_DATA_DIR` (atau entri `POS_DATA_DIR=` pada file `.env`), misalnya saat POS
dijalankan di server Remote Desktop Services (RDS) agar semua sesi memakai
database, file lisensi, dan logo toko yang sama:

```powershell
setx POS_DATA_DIR "D:\POSData"
```

Folder dibuat otomatis bila belum ada; bila tidak ditentukan, perilaku lama
tetap berlaku. Migrasi database, aktivasi lisensi, `installation-id.txt`, dan
logo toko semuanya mengikuti lokasi ini. Gunakan disk lokal server, bukan folder
berbagi jaringan, karena SQLite membutuhkan filesystem lokal.

Untuk membuat folder aplikasi Windows:
```powershell
python scripts\build.py
```

Hasilnya ada di `dist\POS\POS.exe`. Distribusikan seluruh folder `dist\POS`,
bukan EXE-nya saja. Jalankan `python scripts\seed.py` hanya jika ingin
menambahkan data demo untuk pengembangan.

Sebelum membuat installer, siapkan pasangan kunci penerbit lisensi satu kali
dari komputer Anda sendiri:
```powershell
.\venv\Scripts\python.exe scripts\build_license_publisher.py --generate-key
```

Saat diminta, masukkan kata sandi penerbit lisensi minimal 12 karakter lalu
ketik ulang persis sama. Ini adalah kata sandi untuk mengenkripsi kunci privat
penerbit—bukan password OWNER. Kunci privat disimpan terenkripsi di
`%LOCALAPPDATA%\POSPublisher`; kata sandi ini diminta setiap kali lisensi
diterbitkan. Simpan cadangan kunci privat dan kata sandinya dengan aman.
Jangan menaruh atau membagikannya bersama installer. Kunci publik di
`app\core\license_public_key.pem` menjadi bagian POS untuk memeriksa tanda
tangan. Jangan mengganti pasangan kunci setelah distribusi kecuali Anda
memahami bahwa aplikasi lama tidak akan memverifikasi kunci baru.

Buat tool penerbit lisensi terpisah dengan:
```powershell
.\venv\Scripts\python.exe scripts\build_license_publisher.py
```

Untuk membuat installer Windows, instal Inno Setup 6 atau 7, lalu jalankan:
```powershell
.\venv\Scripts\python.exe scripts\build_installer.py
```

Skrip membangun ulang aplikasi dan menghasilkan
`build\installer\AnjayRetailSoft.exe`. Installer memasang aplikasi untuk
pengguna Windows saat ini, membuat shortcut Start Menu, dan menawarkan shortcut
Desktop untuk aplikasi. Shortcut **Folder Data POS** juga dibuat di Desktop dan
Start Menu untuk membuka `%LOCALAPPDATA%\POSApp\data`. Folder database tidak
dihapus saat aplikasi di-uninstall. Untuk installer aplikasi dengan konsol log,
gunakan `python scripts\build_installer.py --debug-console`.

### Tautan unduhan dan QR

Rilis installer dipublikasikan di repo publik
[`scriptwriter123/pos-downloads`](https://github.com/scriptwriter123/pos-downloads)
(hanya berisi rilis, tanpa source code). Tautan berikut selalu menunjuk ke
installer terbaru, berapapun versinya:

```
https://github.com/scriptwriter123/pos-downloads/releases/latest/download/AnjayRetailSoft.exe
```

QR code untuk tautan itu ada di `docs/qr-download.png`, dengan versi vektor
`docs/qr-download.svg` untuk keperluan cetak. Buat ulang keduanya dengan:

```powershell
python scripts\make_download_qr.py
```

![QR Unduhan Installer POS](docs/qr-download.png)

Pada komputer pelanggan, POS menampilkan ID instalasi. Simpan permintaan
lisensi `.posreq` dari layar aktivasi dan kirimkan kepada penerbit. Penerbit
membuka tool terpisah, memilih permintaan, mengisi nama toko, lalu menerbitkan
file `.poslic` yang ditandatangani. Pelanggan mengimpor file tersebut pada layar
aktivasi. Lisensi saat ini permanen dan offline, serta terikat pada ID
instalasi dan fingerprint Windows komputer; pemasangan pada komputer Windows
lain memerlukan lisensi baru. Setelah aktivasi, pemilik membuat akun OWNER jika
database kosong, lalu memasukkan produk dan pengaturan toko dari aplikasi.

Lisensi ditandatangani dengan Ed25519. POS hanya membawa kunci publik; kunci
privat penerbit tidak pernah masuk ke installer atau tool publisher. Tool
penerbit meminta kata sandi kunci untuk setiap penerbitan.

### Trial 7 hari dan mode baca-saja

POS dapat dicoba lebih dulu selama 7×24 jam tanpa lisensi (`trial_service`
menyimpan high-water mark waktu lokal agar jam sistem yang dimundurkan tidak
memperpanjang trial). Setelah trial berakhir dan belum ada lisensi aktif,
layar aktivasi menawarkan tombol **Lanjutkan dalam Mode Baca-Saja**:

- Aplikasi tetap bisa dibuka dan login; laporan, master data, serta ekspor
  tetap dapat dibaca.
- Transaksi baru terkunci: tombol **Bayar**, buka shift, simpan pembelian,
  pembayaran, dan pengeluaran dinonaktifkan, dan layer service menolak dengan
  `LicenseExpiredError` — `SalesService.checkout`, `PurchaseService.record_purchase`
  /`record_payment`, serta `FinancialService.initialize`/`create_expense`/
  `record_expense_payment` (pengaman di service, bukan hanya UI).
- Impor `.poslic` dari layar aktivasi mengembalikan mode normal.

Pelanggan membeli/memperpanjang lisensi melalui website penerbit
(`server/README.md`), mengunduh `.poslic`, lalu mengimpor tanpa instal ulang;
perpanjangan menambah masa berlaku mulai dari `expires_at` yang masih berlaku.

## Pembukuan dan laporan keuangan

Menu **Laporan Keuangan** memakai pembukuan double-entry. Pada pemakaian
pertama, OWNER perlu menetapkan tanggal mulai pembukuan dan mengisi saldo awal
kas, bank, persediaan, kewajiban, serta modal. Aplikasi membuat jurnal
pembukaan seimbang; selisihnya masuk ke akun **Saldo Awal**. Transaksi sebelum
tanggal aktivasi tidak direkonstruksi dan laporan tidak menampilkan transaksi
historis tersebut sebagai data akuntansi.

Setelah pembukuan aktif, penjualan membukukan penerimaan dan harga pokok
persediaan, sedangkan pembelian supplier membukukan persediaan dan hutang.
Gunakan tombol **Catat Pengeluaran** untuk beban operasional toko; transaksi
stok supplier tidak boleh dicatat ulang sebagai pengeluaran. Pengeluaran
memiliki tanggal, kategori akun beban, penerima/keterangan, nominal dibayar,
dan jatuh tempo jika masih terhutang. Pembayaran dapat dilakukan bertahap
melalui **Bayar Pengeluaran** atau alur pembayaran pembelian supplier, dengan
akun Kas/Bank yang dipilih.

Laporan menyediakan Laba Rugi, Neraca, Arus Kas, Neraca Saldo, dan Jurnal Umum
untuk tanggal yang dipilih. Laporan dapat dicetak atau disimpan sebagai PDF
dan DOCX. Jurnal transaksi disimpan bersama transaksi sumber dan harus
seimbang; data sebelum tanggal mulai memerlukan saldo awal yang dimasukkan
OWNER agar hasil laporan mencerminkan posisi pembukuan mulai tanggal tersebut.

Untuk menyiapkan password OWNER sebelum instalasi, buat tool generator terpisah:
```powershell
python scripts\build_owner_password_tool.py
```

Executable `build\owner-password-tool\POS-Owner-Password-Generator.exe` hanya
untuk pembuat/distributor dan tidak masuk ke installer POS. Tool membuat
password acak yang kuat dan menyalinnya ke clipboard atas permintaan. Berikan
password itu kepada pemilik agar dimasukkan ke form setup OWNER saat pertama
kali membuka POS. Tool tidak membuka atau mengubah database dan tidak
menyimpan password.

Untuk menjalankan aplikasi dari CMD dengan log debug, jalankan
`python main.py`. Log bertimestamp tampil di CMD dan mencakup pesan Qt serta
exception yang tidak tertangani. Untuk membuat executable debug yang membuka
konsol saat berjalan, gunakan `python scripts\build.py --debug-console`.
Build biasa tetap tanpa konsol.

Untuk membuat migrasi setelah mengubah model:
```powershell
python -m alembic revision --autogenerate -m "deskripsi perubahan"
python -m alembic upgrade head
```

`python scripts\init_db.py` juga menjalankan migrasi sampai `head`.
Jika database lama sudah dibuat dengan `create_all()`, jangan jalankan `upgrade`
langsung: periksa dahulu bahwa skemanya cocok dengan migrasi awal, lalu adopsi
dengan `python -m alembic stamp head`.

Skrip seed pengembangan membuat login demo `owner / owner123` dan menambahkan
produk contoh toko kelontong beserta kategori,
satuan, harga, stok awal, dan barcode uji. Jalankan ulang
`python scripts\seed.py` untuk menambahkan produk yang belum ada; data produk
dengan SKU yang sudah terdaftar tidak ditimpa.

Setelah login sebagai OWNER, kartu **Manajemen Pengguna** di dashboard membuka
form untuk membuat akun ADMIN, SUPERVISOR, atau CASHIER. Username harus unik,
password minimal 8 karakter, dan password disimpan dengan hash Argon2. CASHIER
langsung diarahkan ke layar kasir; ADMIN dan SUPERVISOR juga masuk langsung ke
halaman Penjualan Harian. OWNER masuk ke dashboard.

Di halaman Penjualan Harian, buka shift sebelum pembayaran, cari atau scan
barcode/SKU, tambahkan produk ke keranjang, lalu tekan F4 untuk pembayaran.
F2 fokus ke pencarian/tambah produk, F5 menyimpan keranjang sementara selama
aplikasi berjalan, dan ESC mengosongkan keranjang. Memilih produk atau memindai
barcode/SKU meminta jumlah sebelum memasukkan barang ke keranjang. Qty pada
keranjang dapat diubah langsung: panah atas/bawah mengubah angka, Tab/Shift+Tab
berpindah ke produk sebelumnya/berikutnya, dan Enter pindah ke produk berikutnya.
Tombol **Laporan** menyimpan ringkasan transaksi kasir hari itu beserta catatan;
laporan untuk kasir dan tanggal yang sama dapat diperbarui. Tombol **Keluar**
berwarna merah.
Transaksi yang selesai mengurangi stok, mencatat mutasi stok dan audit log, lalu
muncul di daftar transaksi hari ini.

Tombol **Keluar** pada halaman kasir kembali ke form login tanpa menutup aplikasi.
Pilihan QRIS, transfer bank, dan e-wallet menampilkan gambar QR demo saja.
Gambar tersebut bukan QR pembayaran yang dapat dipindai; konfirmasi transaksi
non-tunai dinonaktifkan sampai integrasi gateway/QR merchant tersedia pada v1.2.

Setelah transaksi tersimpan, kasir dapat memilih **Cetak Thermal** melalui
printer yang terpasang di Windows, **Simpan PDF** (struk gulung 80 mm), atau
**Nanti**. Pembatalan dialog printer tidak membatalkan penjualan. Pastikan driver
thermal sudah terpasang dan lebar kertas diatur pada preferensi printer.

Dashboard OWNER menyediakan **Laporan Penjualan** dengan periode harian,
bulanan, tahunan, serta custom per jam, tanggal, bulan, atau tahun. Laporan
penjualan bisa dicetak ke printer dokumen default yang tersedia (printer thermal
dilewati) atau disimpan sebagai PDF A4/DOCX. **Laporan Keuangan** menyediakan
Laba Rugi, Neraca, Arus Kas, Neraca Saldo, dan Jurnal Umum serta alur aktivasi
pembukuan dan pencatatan pengeluaran toko seperti dijelaskan di atas.
Laporan Penjualan juga menampilkan laporan harian yang dikirim kasir, termasuk
jumlah transaksi, total penjualan, dan catatan kasir.

Kartu **Master Data** pada dashboard OWNER membuka form produk untuk mengelola
SKU, barcode, nama, kategori, satuan, harga modal/jual, stok awal, batas stok
minimum, dan status aktif. Kategori baru dapat ditambahkan dari jendela tersebut.
Stok awal dicatat sebagai mutasi stok; stok produk yang sudah ada tidak dapat
diubah melalui form produk agar perubahan persediaan tetap terlacak. Produk aktif
dengan SKU/barcode/nama (atau kategori) dapat langsung ditemukan di layar kasir
menggunakan pencarian atau pemindai barcode.
Tombol **Import Data** menyediakan import Excel (.xlsx), CSV UTF-8, serta
database SQLite POS (.db/.sqlite/.sqlite3) yang memiliki tabel produk, kategori,
dan satuan yang kompatibel. Import database menggabungkan kategori, produk,
serta satuan yang dibutuhkan produk; transaksi dan pengguna tidak disalin. SKU
yang sudah ada memperbarui informasi produk tanpa mengubah stok, sedangkan stok
produk baru dicatat sebagai mutasi awal. Menu **Edit Excel** mengekspor template
produk untuk diedit lalu diimpor kembali. Pertahankan judul kolom template,
termasuk SKU, barcode, nama, kategori, satuan, simbol satuan, kode supplier,
harga, stok awal, batas minimum, dan status aktif. Tombol **Harga Spesial**
OWNER mengatur satu aturan harga partai per produk: masukkan batas jumlah dan
pilih harga spesial atau persentase potongan dari harga jual normal. Kedua
kolom selalu ditampilkan dan saling menghitung otomatis; harga satuan normal
ditampilkan sebagai acuan. Harga spesial berlaku saat jumlah produk di
keranjang **sama dengan atau lebih besar** dari batas tersebut; kasir melihat
harga diskon di keranjang, checkout, dan struk.

Kartu **Pengaturan** OWNER memuat profil toko: nama wajib, slogan, alamat,
WhatsApp, dan logo opsional. Profil toko ditampilkan rata tengah di dashboard
dengan nama paling menonjol, diikuti slogan, alamat, WhatsApp, dan logo. Pilih
**Ubah** untuk membuka isian, **Simpan** untuk
memvalidasi dan menyimpan, atau **Batal** untuk membuang perubahan dan memuat
kembali data tersimpan. Logo disalin ke folder data aplikasi agar tidak bergantung
pada lokasi file sumber. Nama toko dan logo menjadi judul serta ikon jendela
login dan semua halaman aplikasi. Jalankan `python -m alembic upgrade head`
sebelum memakai versi yang memiliki kolom kontak/logo baru.

Kartu **Belanja dan Supplier** pada dashboard OWNER membuka form pencatatan
pembelian dengan pilihan supplier dan produk aktif, jumlah diterima, harga
modal per unit, status Lunas/Tempo, serta tanggal jatuh tempo untuk pembelian
Tempo. Halaman ini juga menampilkan riwayat pembelian dan total hutang yang
belum lunas. Tombol **Kelola Supplier** membuka daftar pemasok dan form tambah/
ubah berdasarkan kolom `code`, `name`, `phone`, dan `address`. Kode dan nama
wajib diisi, kode harus unik; nomor telepon dan alamat bersifat opsional.
Perubahan disimpan ke database dan tersedia kembali saat aplikasi dibuka.

Seed menambahkan supplier demo dan menghubungkan produk contoh berdasarkan
kategori. Jalankan `python scripts\seed.py` setelah migrasi agar data supplier
terisi. Master Data Produk menyediakan supplier pilihan/default, sedangkan
supplier aktual dicatat pada setiap transaksi pembelian.

Stok serta mutasi stok bertambah saat pembelian disimpan. Pemilik dapat memilih
transaksi Tempo lalu **Tandai Lunas** ketika dibayar. Notifikasi jatuh tempo
belum dibuat. Rekomendasi: tambahkan kartu **Hutang & Jatuh Tempo** pada
dashboard OWNER untuk daftar jatuh tempo/terlambat.

## Backend QRIS Midtrans (sandbox)

Backend QRIS tahap awal menggunakan Midtrans QRIS POS sandbox. Server Key hanya
dibaca backend dari environment atau file `.env` lokal; jangan memasukkannya
ke aplikasi desktop, Git, atau installer. Dependency yang digunakan adalah
FastAPI, HTTPX, dan Uvicorn. QR image diminta dari URL `generate-qr-code` yang
dikembalikan Midtrans, dan status pembayaran hanya dianggap lunas jika status
Midtrans `settlement` serta `fraud_status` bernilai `accept`.

QRIS yang dibuat Midtrans mengikuti standar QRIS, sehingga pelanggan dapat
memindainya dari aplikasi pembayaran yang mendukung QRIS, termasuk DANA.
Pembayaran tersebut diproses dan disettle melalui merchant Midtrans yang
terdaftar; QR ini bukan QR merchant yang dibuat oleh aplikasi DANA dan dana
tidak otomatis masuk ke saldo DANA.

Salin `.env.example` ke `.env` di root project dan masukkan Server Key sandbox
yang diperoleh dari akun Midtrans sandbox:

```dotenv
MIDTRANS_SERVER_KEY=isi_server_key_sandbox
MIDTRANS_NOTIFICATION_URL=
```

Jalankan backend pengembangan hanya pada loopback:

```powershell
.\venv\Scripts\python.exe -m uvicorn app.payments.midtrans_api:app --host 127.0.0.1 --port 8765
```

Endpoint `GET /health` memeriksa server, `POST /api/payments/qris` membuat
charge dan mengembalikan gambar QR dalam base64, `GET /api/payments/{order_id}`
meminta status terbaru langsung ke Midtrans, dan `POST /api/webhooks/midtrans`
memverifikasi signature notifikasi. Gunakan endpoint OpenAPI lokal
`http://127.0.0.1:8765/docs` hanya untuk tes development. Jangan mengekspos
server pengembangan ke internet. Callback Midtrans hanya diterima bila endpoint
webhook production nantinya memakai HTTPS publik dan `MIDTRANS_NOTIFICATION_URL`
yang sesuai; endpoint sandbox lokal ini belum merupakan backend production.

Fitur ini saat ini adalah backend sandbox dan belum disambungkan ke checkout
kasir. Checkout tetap tidak boleh mencatat QRIS sebagai penjualan sebelum
aplikasi menyimpan transaksi tertunda dengan aman dan memverifikasi status
provider. Jangan gunakan transaksi produksi atau anggap QR demo sebagai
pembayaran.

## Aturan fundamental
- SQLite: foreign_keys=ON, WAL, busy_timeout=5000
- Uang: INTEGER Rupiah
- Timestamp: UTC
- Soft delete: deleted_at
- Password: Argon2id
- UI tidak query DB langsung
- Service menjadi gerbang aturan bisnis
- Perubahan stok wajib dicatat sebagai stock_movements
- Checkout dirancang atomik
