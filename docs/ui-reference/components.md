# Spesifikasi Komponen — OmniRoute (Referensi UI)

Sumber: file HTML referensi `https://www.omniroute.online/id/` + rendering markdown dari
situs live. Semua salinan teks dalam bahasa Indonesia.

---

## 1. Navbar (`site-header`)

### Struktur
```
header.site-header[data-scrolled="false"]
  div.container.site-header__inner
    a.brand-lockup[href="/id/"]
      img[src="/brand/ci-mark-icon.svg"] (32×32)
      span.brand-lockup__name
        span.brand-lockup__product  "OmniRoute"
        span.brand-lockup__company  "by Cheaper Inference"
    nav (menu items)
    a.button "Coba Cheaper Inference"
    language switcher "ID"
    skip-link: "Langsung ke konten" [href="#main-content"]
```

### Menu Item (Desktop)
| Item | Link | Keterangan |
|------|------|------------|
| Provider | `#providers` | Daftar provider AI |
| Fitur | `#features` | Halaman fitur |
| Lainnya (dropdown) | — | Integrasi, Bandingkan, Routing, Galeri, Dokumentasi |
| Star 77.9k | GitHub (tab baru) | Repositori GitHub |
| ID | — | Pemilih bahasa |
| Coba Cheaper Inference | `platform.cheaperinference.com/signup` | CTA utama (external) |

### Spesifikasi Visual
- Tinggi header: `var(--header-height)` = `3.75rem` (60px)
- `scroll-padding-top`: `calc(var(--header-height) + 1rem)`
- Brand lockup: logo SVG 32×32 + teks "OmniRoute" + "by Cheaper Inference"
- Background: `var(--canvas)` (`#fbfbf8` light / `#071013` dark)

### Rekomendasi untuk POS Kasir
- Logo POS di kiri, nama aplikasi "POS Kasir"
- Menu: Dashboard, Transaksi, Produk, Pelanggan, Laporan, Pengaturan
- CTA: "Mulai Gratis" / "Masuk"
- User profile / toggler tema di kanan

---

## 2. Hero Section

### Konten
- **Judul (h1):** "#1 Router AI Open Source"
- **Subjudul:** "Rutekan ke 352 provider lewat satu endpoint yang kompatibel dengan OpenAI, dengan fallback otomatis."
- **Badges / Keterangan:**
  - "Kompatibel dengan OpenAI"
  - "Gratis dan open source"
  - "77.9k star" (GitHub)
- **CTA Tombol (2):**
  1. "Coba Cheaper Inference" → `platform.cheaperinference.com/signup` (external, utama)
  2. "Host OmniRoute sendiri (membuka tab baru)" → GitHub repo (secondary)

### Spesifikasi Visual
- Judul menggunakan font display: `--font-display` (Instrument Serif)
- Subjudul menggunakan font UI: `--font-ui` (Inter)
- Tombol utama: background accent `#d8ff00`, teks `#040d10`, radius `0.25rem`
- Layout: judul di kiri, CTA di kanan atau stacked di bawah di mobile

### Rekomendasi untuk POS Kasir
- **Judul:** "POS Kasir — Aplikasi Kasir Modern untuk Toko Anda"
- **Subjudul:** "Transaksi cepat, laporan akurat, dan manajemen stok otomatis untuk toko kecil dan menengah."
- **CTA Utama:** "Coba Gratis" (akcent `#d8ff00`)
- **CTA Sekunder:** "Lihat Demo" atau "Dokumentasi"
- Badge kepercayaan: "Terpercaya oleh 1000+ toko", "Open Source", "Gratis untuk mulai"

---

## 3. Feature Cards

OmniRoute menampilkan 6 fitur utama dengan nomor 01–06:

| No | Judul | Deskripsi |
|----|-------|-----------|
| 01 | Fallback otomatis | Saat target tidak tersedia atau kuota habis, memilih target sehat berikutnya. |
| 02 | Kompresi konteks | Pipeline 12 engine mengurangi konteks 15–95%. |
| 03 | Mulai dari $0 | 90+ tier gratis dan 56 provider gratis selamanya, tanpa kartu kredit. |
| 04 | 35 integrasi | Claude Code, Codex, Cursor, Cline, Copilot, Antigravity via satu endpoint. |
| 05 | Satu endpoint | Menerima OpenAI, Claude, Gemini, Responses API di `/v1`. |
| 06 | Kontrol operasional | Circuit breaker, kredensial terenkripsi, MCP, A2A, memori, guardrail, eval. |

### Struktur Komponen
```
section.section.section--compact
  div.container
    div.section-head.section-head--split
      p.eyebrow          Label section
      h2.section-title   Judul section
      p.section-copy     Deskripsi singkat
    div.grid-3
      article.card
        span.card__icon  (svg lucide-icon)
        h3               Judul fitur
        p                Deskripsi fitur
```

### Spesifikasi Visual
- Card: background `var(--surface)`, border `var(--line)`, radius `0.25rem`, shadow `var(--shadow)`
- Icon: SVG Lucide, warna `currentColor`, ukuran 19×19
- Judul card: `h3`, font UI, berat menengah
- Deskripsi: `p`, font UI, warna `--muted` atau `--faint`

### Rekomendasi untuk POS Kasir
1. **Transaksi Cepat** — Scan barcode, tambah item, bayar dalam hitungan detik
2. **Stok Otomatis** — Stok terupdate otomatis setelah setiap transaksi
3. **Laporan Real-time** — Lihat penjualan harian, bulanan, tahunan kapan saja
4. **Multi-user** — Akses kasir dan admin dengan role berbeda
5. **Offline Mode** — Transaksi tetap berjalan tanpa internet
6. **Integrasi Printer** — Cetak struk langsung dari printer termal

---

## 4. Pricing / Subscription Info

### Model Comparison Table
- Tabel perbandingan harga model AI (input/output per 1M token)
- Kolom: Model, Harga input, Harga output, Penghematan, Konteks, Detail

### Gratis Tier
- 56 provider gratis selamanya, berulang, atau tanpa key

### Deployment Options (9 cara)
npm, Docker, Desktop (Electron), ARM, Android · Termux, PWA, OpenCode plugin, VS Code, From source

### Rekomendasi untuk POS Kasir

| Tier | Harga | Fitur |
|------|-------|-------|
| Gratis | Rp 0 / bln | 1 pengguna, transaksi terbatas, laporan dasar |
| Usaha Kecil | Rp 99.000 / bln | Pengguna tak terbatas, laporan lengkap, support email |
| Usaha Menengah | Rp 249.000 / bln | Semua fitur, multi-cabang, API integrasi, support prioritas |

Tombol CTA: "Mulai Gratis", "Upgrade", "Hubungi Sales"

---

## 5. CTA Section

### Konten
- **Judul:** "OmniRoute bekerja lebih baik dengan Cheaper Inference."
- **Deskripsi:** Gabungkan fallback otomatis dan tool developer OmniRoute dengan marketplace Cheaper Inference.
- **Highlight:** "**Kredit bonus $10** — Isi akun baru Anda dengan $5 dan kami tambahkan bonusnya secara otomatis."
- **Tombol:** "Buat akun + klaim $10"

### Spesifikasi Visual
- Section terpisah dengan background `var(--canvas-alt)` (`#f7f7f2`)
- Judul menggunakan font display
- Card/info box dengan border dan radius

### Rekomendasi untuk POS Kasir
- Judul: "Kelola Toko Anda dengan Lebih Baik Bersama POS Kasir"
- Deskripsi singkat nilai proposisi
- CTA: "Daftar Gratis Sekarang" (accent `#d8ff00`)
- Info bonus: "Gratis untuk 1 cabang pertama", "Tanpa kartu kredit"

---

## 6. Footer

### Struktur
```
footer
  div.container
    div.footer-grid
      div.footer-brand
        logo + tagline
        "Open source di bawah Lisensi MIT."
      div.footer-section[Produk]
        Dashboard, Transaksi, Produk, Pelanggan, Laporan
      div.footer-section[Perusahaan]
        Tentang, Kontak, Karir, Kebijakan Privasi, Syarat Layanan
      div.footer-section[Dokumentasi]
        Panduan Mulai, API Referensi, FAQ, Changelog
      div.footer-section[Komunitas]
        Discord, Email Support, Twitter/X
    div.footer-bottom
      "© 2026 POS Kasir · Lisensi MIT"
```

### Link Footer (Produk)
- Dashboard, Transaksi, Produk, Pelanggan, Laporan

### Link Footer (Perusahaan)
- Tentang, Kontak, Karir, Kebijakan Privasi, Syarat Layanan

### Link Footer (Dokumentasi)
- Panduan Mulai, API Referensi, FAQ, Changelog

### Link Footer (Komunitas)
- Discord, Email Support, Twitter/X

---

## 7. Mobile Responsiveness

| Elemen | Desktop | Mobile (estimasi < 640px) |
|--------|---------|---------------------------|
| Navbar | Menu horizontal penuh | Hamburger menu, logo di tengah/kiri, CTA tersembunyi di menu |
| Hero | 2 kolom | 1 kolom, judul menumpuk di atas, CTA full-width |
| Feature Grid | 3–4 kolom | 1 kolom, card menumpuk vertikal |
| Pricing Table | 3 kolom | 1 kolom, card stacking |
| CTA Section | 2 kolom | 1 kolom |
| Footer | 4–5 kolom | 1–2 kolom, link disatukan |
| Container | `max-width: 75rem` (1200px) | `padding: 0 1rem`, lebar penuh |

### Breakpoint Estimasi
- `640px` (sm): Navbar ke hamburger, grid ke 1 kolom
- `768px` (md): Grid 2 kolom untuk beberapa section
- `1024px` (lg): Layout desktop penuh

---

## 8. Catatan Teknis Implementasi

- **Tema:** Gunakan `data-theme="light"` / `data-theme="dark"` pada `<html>`, deteksi awal via `localStorage` atau `matchMedia('(prefers-color-scheme: dark)')`.
- **Font:** Muat Inter, Instrument Serif, dan IBM Plex Mono sebagai `.woff2` dengan `font-display: swap`.
- **Variabel CSS:** Definisikan semua design token di `:root` dan override di `:root[data-theme=dark]`.
- **Icon:** Gunakan SVG inline dengan `stroke="currentColor"` untuk warna yang mengikuti tema.
- **Card:** Background `var(--surface)`, border `var(--line)`, radius `0.25rem`, shadow `var(--shadow)`.
- **Tombol utama:** Background `var(--accent)` (`#d8ff00`), teks `var(--ink)` (`#040d10`), radius `0.25rem`, hover ke `var(--accent-strong)`.
- **Input/form:** Radius `0.5rem` (`var(--radius-control)`), border `var(--line)`.
