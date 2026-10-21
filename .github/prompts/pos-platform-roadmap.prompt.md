---
name: POS Retail lintas platform sampai rilis
description: Rencanakan dan kembangkan POS Retail dari aplikasi Windows saat ini menjadi layanan POS lintas platform, pembayaran terintegrasi, WhatsApp, dan subscription licensing hingga paket rilis yang tervalidasi.
argument-hint: Bagian atau prioritas yang ingin dikerjakan sekarang (opsional)
agent: agent
---

# Misi

Kembangkan aplikasi POS Retail yang sudah ada di repository ini secara bertahap
sampai siap digunakan dan dirilis pada Windows, macOS, Android, dan iOS, dengan
backend/server terpusat. Tujuan akhirnya mencakup transaksi POS dan keuangan
yang akurat, seluruh metode pembayaran kasir yang benar-benar terintegrasi,
notifikasi laporan kasir melalui WhatsApp kepada penerima yang tepat,
manajemen akun teknisi, serta aktivasi dan paket langganan yang dikelola server.

Gunakan repository sebagai sumber kebenaran. Mulai dengan membaca
[README.md](../../README.md), [ARCHITECTURE.md](../../ARCHITECTURE.md),
[DATABASE.md](../../DATABASE.md), konfigurasi, migration, service, UI, dan tes
yang relevan. Repository saat ini berisi aplikasi Python/PySide6, SQLite,
Alembic, lisensi offline Ed25519, transaksi kasir, pembelian supplier, dan
ledger keuangan double-entry. Verifikasi fakta tersebut terhadap kode saat ini;
jangan menganggap dokumentasi atau ringkasan lama selalu mutakhir.

# Cara bekerja

1. Audit implementasi terkini, hasil tes, status branch, migration, integrasi,
   dan batasan build. Bedakan fitur yang sungguh berfungsi dari mock/demo,
   belum terhubung, atau belum diverifikasi.
2. Tulis ringkasan kondisi, target arsitektur, risiko, dependensi eksternal,
   serta roadmap berurutan dengan acceptance criteria yang dapat dites.
   Jangan membuat file perencanaan baru kecuali diminta; catat keputusan
   arsitektur penting pada dokumentasi ADR yang memang diperlukan.
3. Kerjakan satu fase bernilai jelas pada satu waktu. Implementasikan, tes,
   perbarui dokumentasi, dan laporkan hasil fase itu sebelum beralih ke fase
   berikutnya. Lanjutkan otomatis untuk keputusan teknis yang reversibel dan
   berisiko rendah.
4. Berhenti dan tanyakan pemilik produk sebelum keputusan yang mengubah biaya,
   vendor, alur pembayaran, data migrasi, perilaku offline, privasi, keamanan,
   atau kebijakan komersial. Berikan rekomendasi dan pilihan yang ringkas.
5. Jangan berhenti pada rencana apabila fase yang diminta sudah jelas dan dapat
   dikerjakan. Jangan mengklaim integrasi, kompatibilitas, keamanan, atau
   kesiapan rilis sebelum dibuktikan oleh tes, sandbox provider, atau build yang
   relevan.
6. Jangan menghapus, menulis ulang, atau memigrasikan data produksi tanpa
   persetujuan eksplisit dan rencana backup/rollback. Hormati perubahan lokal
   yang tidak dibuat dalam tugas ini.

# Sasaran produk

## Platform dan arsitektur

- Pertahankan aplikasi Windows yang ada selama transisi dan lindungi alur kasir,
  produk, harga spesial partai, supplier/pembelian, laporan, serta ledger.
- Rancang sistem client-server agar aturan transaksi, otorisasi, pembayaran,
  pembukuan, subscription, dan audit memiliki sumber kebenaran server.
- Dukung aplikasi kasir desktop Windows dan macOS serta aplikasi mobile Android
  dan iOS. Tentukan apakah UI desktop lama tetap dipakai sementara atau diganti
  bertahap; jangan melakukan rewrite besar tanpa perbandingan biaya, risiko,
  kemampuan offline, dukungan perangkat kasir, dan keputusan pemilik.
- Pisahkan API/domain dari UI dan penyimpanan lokal. Pertimbangkan backend
  modular yang memiliki kontrak API berversi, database server relasional,
  antrean tugas, observabilitas, backup, dan strategi deployment yang sesuai
  skala. Pilih stack setelah audit kompatibilitas dan diskusi; jelaskan opsi dan
  rekomendasi sebelum migrasi arsitektur yang sulit dibalik.
- Tentukan strategi online/offline per operasi: transaksi offline yang aman,
  sinkronisasi idempotent, konflik dan retry, serta perilaku yang jelas ketika
  status pembayaran atau lisensi tidak dapat diverifikasi. Jangan pernah
  menyatakan pembayaran non-tunai sukses hanya berdasarkan UI/client.
- Jaga data setiap toko/tenant terisolasi secara konsisten pada semua query,
  laporan, background jobs, ekspor, dan audit.

## Pengguna dan hak akses

- Pertahankan OWNER, ADMIN, SUPERVISOR, dan CASHIER sesuai kebutuhan yang sudah
  berjalan; tambahkan role **TEKNISI** dengan permission minimum dan teruji.
- OWNER mengelola user, toko, produk, konfigurasi, keuangan, subscription, dan
  penerima notifikasi sesuai kebijakan akses yang disepakati.
- Rancang secara spesifik pekerjaan TEKNISI—misalnya penanganan perangkat,
  maintenance, atau dukungan—dan jangan memberinya akses ke kas, harga modal,
  data pelanggan, atau fungsi administratif tanpa kebutuhan dan persetujuan.
- Lakukan authorization di server/service, bukan hanya menyembunyikan tombol di
  UI. Uji akses lintas role dan lintas tenant.

## Pembayaran kasir

- Inventarisasi metode yang terlihat di aplikasi dan temukan mana yang masih
  demo, manual, atau sudah punya integrasi provider.
- Sediakan alur yang sesuai untuk tunai, QRIS, transfer bank, e-wallet, kartu,
  atau metode lain yang benar-benar dibutuhkan. Tanyakan provider/acquirer,
  negara, merchant account, sandbox, dan metode yang akan diluncurkan sebelum
  memilih vendor atau mengaktifkan transaksi nyata.
- Integrasikan hanya API resmi provider. Implementasikan pembuatan transaksi,
  status pending/success/failed/expired/cancelled, callback/webhook terverifikasi,
  signature verification, idempotency, timeout/retry yang aman, reconciliation,
  void/refund jika didukung, audit, serta penutupan kas/settlement.
- Pisahkan status pembayaran provider dari status transaksi POS. Tampilkan
  instruksi pelanggan dan hasil yang eksplisit; jangan melakukan double-charge
  saat retry atau menggandakan pembayaran saat callback dikirim berulang.
- Rahasiakan API key dan webhook secret di server/secret manager. Jangan pernah
  menyimpan secret dalam source, mobile/desktop bundle, log, screenshot, atau
  file konfigurasi yang dikomit. Gunakan akun sandbox untuk pengujian; transaksi
  produksi hanya setelah pemilik memberikan persetujuan.
- Jika operasi offline tidak dapat mengonfirmasi provider, jelaskan bahwa
  transaksi non-tunai harus tetap pending/tidak tersedia dan sediakan fallback
  hanya bila alur bisnis serta kontrol rekonsiliasinya disetujui.

## Laporan kasir melalui WhatsApp

- Rancang pengiriman ringkasan tutup shift/laporan kasir ke user relevan,
  termasuk role TEKNISI bila ia memang penerima yang berwenang. Penerima harus
  dapat ditentukan per toko, tanggung jawab/shift, kategori laporan, atau
  assignment; jangan mengirim broadcast ke semua user secara default.
- Tanyakan jenis pesan, siapa yang menerima, nomor mana yang digunakan,
  persetujuan/consent, jadwal, serta isi data yang boleh dibagikan.
- Gunakan WhatsApp Business Platform atau BSP resmi yang dipilih pemilik.
  Bedakan pesan template dan pesan dalam service window sesuai kebijakan
  platform/provider saat implementasi. Jangan memakai otomasi WhatsApp personal
  yang melanggar ketentuan.
- Simpan status queued/sent/delivered/failed, provider message ID, retry dengan
  backoff dan idempotency, audit pengiriman, serta mekanisme kirim ulang yang
  tidak menduplikasi notifikasi. Lindungi nomor telepon dan minimalkan isi
  laporan; hindari mengirim data sensitif yang tidak diperlukan.
- Jika provider belum diputuskan atau kredensial sandbox belum tersedia,
  implementasikan interface, fake provider untuk tes, pengaturan penerima,
  status, dan dokumentasi, tetapi tandai integrasi nyata sebagai belum aktif.

## Subscription dan aktivasi server

- Ganti/lanjutkan aktivasi lisensi offline dengan layanan aktivasi server yang
  menjadi sumber kebenaran entitlement. Pertahankan kompatibilitas/verifikasi
  lisensi lama selama masa transisi; buat rencana migrasi dan rotasi key
  bertahap. Jangan mengganti kunci Ed25519 yang sudah didistribusikan tanpa
  strategi kompatibilitas dan persetujuan pemilik.
- Dukung plan bulanan dan tahunan; dukung opsi berbasis jam hanya setelah aturan
  produk, harga, pembulatan, zona waktu, awal/akhir masa aktif, pause, renewal,
  grace period, refund, dan expired behavior ditentukan pemilik.
- Modelkan tenant/toko, subscription, plan/version, entitlement, invoice,
  pembayaran langganan, lisensi/perangkat, aktivasi/deaktivasi, audit, dan
  status lifecycle. Tentukan batas perangkat/user/fitur hanya jika disetujui.
- Validasi entitlement di server dan definisikan cache/offline grace yang
  tahan manipulasi jam perangkat, gangguan jaringan, duplikasi aktivasi,
  reinstalasi, penggantian perangkat, dan pembatalan. Server tetap menghormati
  transaksi offline yang sudah tercatat sesuai kebijakan yang disepakati.
- Pisahkan signing key, API secrets, database credentials, dan data pelanggan.
  Gunakan secret manager/KMS bila tersedia; minimalkan akses; siapkan rotation,
  backup, recovery, rate limit, abuse detection, serta audit administratif.
- Jangan menaruh private key penerbit atau production credential di repository,
  aplikasi client, installer, CI artifact, atau log.

## Data, keuangan, dan operasional

- Pertahankan integritas transaksi atomik untuk penjualan, stok, pembayaran,
  pembelian, pengeluaran, audit, dan posting jurnal.
- Pertahankan ledger double-entry seimbang, idempotent, tanggal efektif,
  snapshot HPP, pembayaran hutang bertahap, dan laporan keuangan. Catat
  penyesuaian schema secara migration berversi serta rencana backup/restore.
- Rancang API, authorization, audit trail, data retention, privacy/export,
  observabilitas, health checks, alerting, backup teruji, dan prosedur recovery.
- Sediakan UX lokal yang mendukung barcode/scanner, printer struk, cash drawer,
  currency, zona waktu dan locale pasar target tanpa mengorbankan akurasi.

# Urutan fase dan gerbang penerimaan

Atur fase berdasarkan hasil audit; tahapan di bawah adalah batasan minimum,
bukan alasan untuk membangun semua sekaligus:

1. **Audit dan keputusan produk:** inventaris fitur/UI/service/test; daftar
   mock, risiko, dan gap; target tenant/offline/platform; matriks role;
   provider pembayaran/WhatsApp; paket langganan; keputusan hosting dan
   deployment. Catat hal yang belum diputuskan dan minta jawaban yang benar-benar
   memblokir.
2. **Fondasi arsitektur/backend:** spesifikasi domain/API, threat model,
   autentikasi/otorisasi, tenant isolation, database server, migration,
   observabilitas, local dev environment, CI, kontrak API, dan test harness.
   Migrasikan data hanya melalui proses preview, backup, validasi, serta
   rollback yang diuji.
3. **Sinkronisasi dan client:** kontrak API dan alur autentikasi lintas client;
   offline queue/conflict/idempotency; parity untuk checkout, katalog, stok,
   shift, supplier, dan laporan; accessibility serta ukuran layar target.
4. **Pembayaran provider:** integrasi sandbox end-to-end, webhook, failure/retry,
   duplicate callback, refund/void, reconciliation, dan tes tanpa uang nyata.
   Jangan menandai fase siap sebelum status akhir berasal dari verifikasi
   provider/server.
5. **Role TEKNISI dan WhatsApp:** permission server, pengaturan penerima,
   validasi consent, template, antrean, delivery/failure/retry, audit, privacy,
   dan end-to-end sandbox dengan penerima uji yang diizinkan.
6. **Subscription/activation:** plan dan entitlement versioned, checkout/renewal
   bila provider sudah dipilih, aktivasi/deaktivasi multi-perangkat,
   grace/expiry, jam sistem dimanipulasi, key rotation dan backward
   compatibility; uji keamanan serta kegagalan jaringan.
7. **Stabilisasi dan rilis:** regression dan migration tests, security/privacy
   review, load/reliability tests sesuai skala, backup-restore drill, crash
   reporting/monitoring, dokumentasi operator dan pengguna, support/runbook,
   release notes, SBOM/signing bila tersedia, CI build, dan smoke test paket.

Setiap fase wajib memiliki:

- Acceptance criteria terukur dan tes unit/integrasi/e2e yang relevan.
- Migrasi dan rollback yang aman; cek kompatibilitas data versi sebelumnya.
- Log/audit tanpa credential atau data pribadi berlebihan.
- Dokumentasi konfigurasi lokal/sandbox/produksi yang membedakan placeholder
  dari credential rahasia.
- Ringkasan fitur yang sudah, belum, dan tidak dapat diverifikasi.

# Paket dan persyaratan rilis akhir

- Pertahankan installer Windows yang sudah ada serta buat paket native sesuai
  platform yang dipilih: macOS installer/package, Android APK/AAB, dan iOS
  archive/App Store artifact. Buat juga deployment artifact/container untuk
  server bila arsitekturnya memerlukannya.
- Tentukan signing identity, keystore, Apple Developer account/certificate,
  provisioning profile, notarization, dan secret CI bersama pemilik. Jangan
  membuat, menebak, memasukkan, atau mengungkap secret. Jika environment saat
  ini tidak dapat membangun/menandatangani platform tertentu, buat pipeline dan
  instruksi yang dapat direproduksi, tandai artefak sebagai belum tersedia, dan
  jelaskan persyaratan yang masih dibutuhkan.
- Build release harus reproducible sebisa mungkin, memakai versi/dependency yang
  terkontrol, tanpa debug/test account, database contoh, sandbox endpoint,
  private key, credential, atau file lokal.
- Lakukan clean-install, upgrade install, first-run/onboarding, aktivasi,
  login/role, transaksi pembayaran sandbox, laporan, update, uninstaller, serta
  backup/restore smoke tests pada setiap platform yang benar-benar tersedia.
- Jangan mengklaim "production-ready" hanya karena compile/build berhasil.
  Catat platform, versi, checksum artefak, test/build result, batasan, dan
  persetujuan yang masih diperlukan.

# Aturan implementasi

- Ikuti pola repository, pertahankan type safety, buat perubahan yang fokus,
  hindari refactor tak terkait, dan dokumentasikan perubahan perilaku.
- Cari helper/service/pola yang sudah ada sebelum membuat yang baru. Gunakan
  operasi database transaksional, constraint, foreign key, idempotency key, dan
  otorisasi eksplisit.
- Jangan memakai fake success, silent catch, insecure fallback, credential
  hardcoded, atau test yang hanya memvalidasi implementasi palsu.
- Jalankan tes, formatter/linter/type check, migration check, serta build
  minimum yang relevan setelah perubahan. Perbaiki regresi yang disebabkan
  perubahan sebelum menyatakan selesai.
- Jangan membuat commit, push, release, migrasi production, pembelian produk,
  atau deployment cloud tanpa permintaan/persetujuan eksplisit.
- Dalam laporan akhir, cantumkan ringkasan, file/perubahan utama, tes dan hasil
  build, artefak release beserta lokasi jika tersedia, integrasi yang benar-benar
  aktif, dan blocker/keputusan pemilik yang masih diperlukan.
