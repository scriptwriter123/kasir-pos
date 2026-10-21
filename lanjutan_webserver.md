## 1. Keputusan arsitektur untuk versi Anda

Kita akan menggunakan konfigurasi berikut:

| Bagian          | Keputusan                                                     |
| --------------- | ------------------------------------------------------------- |
| Desktop         | Python + PySide6                                              |
| Packaging       | PyInstaller, lalu installer Windows                           |
| Backend website | FastAPI                                                       |
| Database server | PostgreSQL untuk produksi                                     |
| Database kasir  | Tetap menggunakan database lokal POS Anda                     |
| Trial           | 7 × 24 jam sejak aktivasi pertama                             |
| Setelah trial   | Transaksi baru terkunci; data tetap dapat dibaca dan diekspor |
| Pembayaran      | Midtrans, dengan verifikasi server                            |
| Lisensi         | File lisensi Ed25519, diimpor tanpa instal ulang              |
| Operasi offline | Kasir tetap bekerja selama lisensi atau trial lokal masih sah |

Ada satu penyesuaian penting: karena komputer kasir harus bisa sepenuhnya offline, lisensi yang sudah diunduh perlu menyimpan masa berlaku yang jelas. Perpanjangan, pembatalan, dan refund baru dapat diketahui desktop setelah lisensi baru diimpor. Lisensi offline tidak bisa sekaligus menjamin pencabutan akses secara langsung.

Integrasi dengan proyek POS Anda yang sebenarnya juga perlu mengikuti struktur folder, modul database, dan fungsi checkout yang sudah ada. Karena source code POS belum tersedia di percakapan ini, implementasi di bawah akan berbentuk paket integrasi lengkap beserta titik sambung yang perlu disesuaikan, bukan mengklaim sudah terpasang di aplikasi Anda.

It seems like I can’t do more advanced data analysis right now. Please try again later.

Saya belum berhasil membuat paket ZIP implementasi lanjutan pada percobaan ini. Jadi, saya tidak akan memberikan tautan unduhan baru yang belum terverifikasi.

Namun, dokumentasi resmi Midtrans sudah mengonfirmasi dua hal penting untuk rancangan Anda:

- Webhook pembayaran harus memverifikasi `signature_key`, yang dihitung menggunakan SHA-512 dari `order_id + status_code + gross_amount + ServerKey`. Status transaksi juga perlu diverifikasi, termasuk `settlement` atau `capture` yang memenuhi pemeriksaan fraud.&#x20;

  [image](https://www.google.com/s2/favicons?domain=https://docs.midtrans.com\&sz=32)

  Midtrans Documentation

  +1

- PyInstaller dapat mengemas aplikasi Python beserta dependensinya menjadi folder distribusi atau satu file `.exe`. Sebaiknya uji mode folder terlebih dahulu sebelum beralih ke satu file.&#x20;

  [image](https://www.google.com/s2/favicons?domain=https://www.pyinstaller.org\&sz=32)

  PyInstaller 6.22.3 documentation

  +1



Untuk melanjutkan integrasi ke aplikasi Anda dengan benar, unggah folder proyek POS Anda dalam bentuk ZIP. Sertakan file utama, modul database, fungsi penyimpanan transaksi, dan `requirements.txt`; jangan sertakan password, token, atau kunci API rahasia.

Dengan source code tersebut, integrasi bisa disesuaikan langsung pada struktur aplikasi Anda, terutama agar masa Trial tujuh hari benar-benar membatasi transaksi baru tanpa menghilangkan akses baca, laporan historis, dan ekspor data.