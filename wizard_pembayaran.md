Untuk aplikasi POS Python yang sedang Anda kembangkan, saya sarankan membuat fitur Wizard Pengaturan Pembayaran. Tujuannya agar pemilik toko dapat mengaktifkan metode pembayaran sendiri tanpa harus memahami pemrograman, mengedit file `.env`, atau mengubah kode aplikasi.

Wizard dibagi menjadi tiga jalur utama:

- DANA Merchant — pendaftaran merchant, aktivasi produk pembayaran, dan konfigurasi integrasi yang memang tersedia untuk akun merchant tersebut.
- QRIS Midtrans — pendaftaran akun Midtrans, verifikasi bisnis, aktivasi QRIS, pengambilan kredensial API, dan pengujian pembayaran.
- Transfer bank / m-banking — pengaturan rekening penerima dan, jika diperlukan, integrasi API bank atau penyedia layanan pembayaran untuk verifikasi transaksi otomatis.

Hal penting: memiliki akun merchant atau QRIS tidak otomatis berarti memiliki akses API. Alur wizard perlu menyesuaikan produk yang disetujui penyedia, status verifikasi akun, dan metode integrasi yang tersedia.

## 1. Struktur utama wizard POS

Langkah 1 — Profil toko

Nama toko, alamat, nama pemilik, nomor HP, dan email.

Langkah 2 — Pilih metode pembayaran

DANA Merchant, QRIS Midtrans, transfer bank manual, atau transfer bank otomatis.

Langkah 3 — Jalankan wizard sesuai pilihan

Panduan pendaftaran, verifikasi, konfigurasi, dan pengujian.

Langkah 4 — Aktivasi pembayaran

Simpan pengaturan, verifikasi koneksi, lalu aktifkan metode yang sudah siap.

## 2. Wizard A — DANA Merchant

Alur ini menggunakan pendaftaran merchant dan integrasi API DANA jika produk API yang diperlukan tersedia untuk akun pengguna. Dokumentasi resmi DANA menjelaskan proses registrasi, verifikasi bisnis, dan integrasi developer.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://gateway-mp-sit.dana.id\&sz=32)

Integrate Payments, Disbursements & Billers

+1



[Dana Indonesia Digital Wallet Logo Vector - iconLogoVector](https://images.openai.com/static-rsc-4/BKmwqGpQFyzV-LnEILmpRv8fot19lBrUWVxluM5KONq89WdzQzUKxupAsWHPN5FDc1hSw9XU6YCf8H5JR9iPDjPctyp5PwF2rIKCfQ-PCxrLhB-8TByz6MXTGFvMcOJH2rEaBJxNJTvxjEj8Z8aZFnZ2sSY9_Xnde4feshfyMEQ?purpose=inline)

## DANA Merchant

Pendaftaran → API → uji transaksi → aktivasi

1. Pilih jenis integrasi. Pengguna memilih DANA sebagai pembayaran langsung atau QRIS melalui DANA, sesuai produk yang tersedia.
2. Buka portal merchant. Tombol `Buka Portal DANA` mengarahkan pengguna ke situs resmi untuk mendaftar atau login.
3. Daftarkan akun. Pengguna mengisi email, nomor HP, dan informasi akun bisnis.
4. Lengkapi profil bisnis. Isi nama usaha, alamat, kategori bisnis, serta informasi legalitas yang diminta.
5. Unggah dokumen. Pengguna mengirim dokumen yang diminta dan menunggu hasil verifikasi.
6. Pilih produk pembayaran. Pengguna memastikan produk yang sesuai dengan POS telah tersedia dan disetujui.
7. Mulai integrasi developer. Pengguna membuka dashboard developer, memulai integrasi, dan mengatur endpoint notifikasi bila diperlukan.
8. Konfigurasi API. Masukkan kredensial dan konfigurasi yang diberikan DANA, misalnya Client ID, informasi kunci, serta environment yang sesuai dengan jenis integrasi.
9. Uji pembayaran. Uji pembuatan transaksi, QRIS jika dipilih, penerimaan notifikasi, dan pemeriksaan status pembayaran.
10. Aktivasi produksi. Setelah persetujuan dan pengujian selesai, pengguna mengaktifkan mode produksi.

Referensi: [Panduan onboarding DANA](https://dashboard.dana.id/api-docs-v2/guide/getting-started/getting-started-onboarding) dan [Dokumentasi QRIS DANA](https://dashboard.dana.id/api-docs-v2/api/qris-acquirer/overview).

## 3. Wizard B — QRIS Midtrans

Untuk POS, jalur ini cocok jika pengguna ingin membuat QRIS dari transaksi kasir dan memperoleh status pembayaran secara terintegrasi. Midtrans menyediakan API QRIS dan lingkungan Sandbox untuk pengujian.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://docs.midtrans.com\&sz=32)

Midtrans Documentation

+1



[Midtrans Logo PNG,  Vector (AI, EPS, CDR, PDF, SVG) - iconLogoVector](https://images.openai.com/static-rsc-4/1MyUB-eFNxoKElxXIBq99uSkJHs8qhNEDyvMt4oLWS_Rz_UuOM8FbTGMkA4IY0V8emJmON9PpP5oqPvmwYrhcf2ibJaTaux-ayqlnfNWOVeCLtNjxxTkI8CcqLj6n8yCIH9aObvxz6--UGnwADq65RZRPR1F9oR9grH88ihs4J8?purpose=inline)

## QRIS Midtrans

Registrasi → aktivasi QRIS → kredensial → tes

1. Mulai pendaftaran. Buka situs Midtrans dan pilih registrasi akun merchant.
2. Pilih tipe bisnis. Pengguna menentukan apakah bisnis perorangan atau badan usaha.
3. Isi data usaha. Lengkapi identitas pemilik, alamat, kontak, informasi usaha, dan situs atau media sosial/katalog jika diminta.
4. Kirim dokumen verifikasi. Pengguna mengunggah dokumen sesuai jenis usaha dan menunggu persetujuan.
5. Login ke dashboard. Wizard memberikan petunjuk menuju dashboard Midtrans.
6. Aktifkan QRIS. Buka pengaturan metode pembayaran dan ajukan aktivasi QRIS apabila belum aktif.
7. Ambil API key Sandbox. Pengguna membuka `Settings → Access Keys` dan memasukkan Server Key serta Client Key yang sesuai. Server Key harus disimpan secara rahasia.
8. Hubungkan POS. POS menguji pembuatan transaksi QRIS dan menampilkan kode QR untuk dipindai.
9. Uji notifikasi. Periksa apakah perubahan status pembayaran diterima dan transaksi POS berubah menjadi lunas hanya setelah statusnya tervalidasi.
10. Ajukan produksi. Setelah akun dan metode pembayaran siap, masukkan kredensial produksi yang terpisah dari Sandbox dan lakukan transaksi uji sesuai prosedur penyedia.

Referensi: [Registrasi Midtrans](https://midtrans.com/id/passport), [Panduan dashboard dan kredensial](https://docs.midtrans.com/docs/midtrans-account), dan [Aktivasi produksi](https://docs.midtrans.com/docs/switching-to-production-mode).

## 4. Wizard C — Transfer bank / m-banking

Bagian ini sebaiknya memiliki dua pilihan yang jelas. Keduanya berbeda dari sisi otomatisasi dan kebutuhan integrasi.

## C1. Transfer manual ke rekening toko

Paling mudah untuk versi awal POS

1. Pengguna memilih `Transfer Bank Manual`.
2. Memasukkan nama bank, nama pemilik rekening, nomor rekening, dan instruksi pembayaran.
3. Memilih apakah ingin menampilkan QR pembayaran statis atau hanya informasi rekening.
4. Mengatur cara konfirmasi: kasir memeriksa mutasi atau bukti pembayaran secara manual.
5. Melakukan simulasi transaksi dan memastikan kasir dapat menandai pembayaran sebagai lunas setelah verifikasi.
6. Menyimpan pengaturan dan mengaktifkan metode transfer manual.

## C2. Transfer bank otomatis melalui API / Virtual Account

Memerlukan penyedia API

1. Pengguna memilih penyedia layanan: bank langsung atau payment gateway yang mendukung Virtual Account (VA).
2. Wizard membuka portal penyedia untuk pendaftaran dan login.
3. Pengguna mengisi data usaha, rekening settlement, dan dokumen yang dipersyaratkan.
4. Pengguna mengajukan aktivasi transfer bank atau VA dan menunggu persetujuan.
5. Pengguna memperoleh kredensial API Sandbox, lalu memasukkannya ke pengaturan POS.
6. POS menguji pembuatan nomor VA atau instruksi transfer untuk transaksi contoh.
7. Pengguna menguji callback/webhook dan memastikan transaksi baru dinyatakan lunas setelah status terverifikasi dari penyedia.
8. Setelah lolos pengujian, pengguna memasukkan kredensial produksi dan mengaktifkan integrasi.

Transfer otomatis memerlukan API atau mekanisme notifikasi dari penyedia. Menyimpan nomor rekening saja tidak memungkinkan POS memverifikasi mutasi bank secara otomatis. Midtrans, misalnya, menyediakan API Virtual Account untuk transfer bank.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://docs.midtrans.com\&sz=32)

Midtrans Documentation

+1



## 5. Bentuk wizard yang dilihat pengguna

Berikut contoh alur antarmuka yang dapat digunakan sebagai acuan desain.

## Simulasi wizard

Pilih metode untuk melihat urutan langkahnya.

DANA Merchant / QRIS DANA

QRIS Midtrans

Transfer bank manual

Transfer bank otomatis / VA

LANGKAH 5 DARI 5

100%

## Aktivasi produksi

Masukkan key produksi setelah persetujuan dan pengujian.

KembaliLanjut ke spesifikasi teknis

## 6. Fitur pendukung yang wajib ada

Agar wizard benar-benar mudah digunakan oleh pemilik toko, setiap jalur sebaiknya memiliki:

- Simpan dan lanjutkan nanti: pengguna tidak perlu mengulang pendaftaran jika belum mendapat persetujuan.
- Status proses: `Belum dimulai`, `Sedang diisi`, `Menunggu verifikasi`, `Siap diuji`, `Aktif`, atau `Gagal`.
- Tombol buka portal resmi: membuka halaman penyedia tanpa meminta pengguna memberikan kata sandi kepada aplikasi POS.
- Panduan sesuai kondisi: langkah berikutnya baru terbuka setelah persyaratan sebelumnya terpenuhi.
- Tes koneksi dan transaksi: membedakan koneksi API berhasil dari pembayaran nyata yang sudah terverifikasi.
- Keamanan kredensial: Server Key, private key, dan secret disimpan terenkripsi; tidak ditampilkan kembali penuh di layar dan tidak dicatat dalam log.
- Pemisahan Sandbox dan produksi: kredensial pengujian tidak boleh tertukar dengan kredensial transaksi nyata.
- Validasi notifikasi: status pembayaran harus divalidasi melalui mekanisme autentikasi penyedia, bukan hanya berdasarkan screenshot atau pesan dari pengguna.

Rekomendasi urutan pengembangan: mulai dari transfer bank manual, lanjutkan QRIS Midtrans, kemudian DANA API, dan terakhir integrasi API bank langsung. Urutan ini memberi Anda versi awal yang lebih mudah diuji, sambil menjaga arsitektur wizard tetap seragam untuk semua metode.