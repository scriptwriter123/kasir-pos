# Design Tokens — OmniRoute (Referensi UI)

Sumber: file HTML referensi `https://www.omniroute.online/id/` + file CSS eksternal
`18894398c690ecd8.css` (variabel `:root`) dan `4142b10f37e818a9.css` (komponen).
Bahasa situs: Indonesia (`lang="id"`). Tema: light/dark melalui `data-theme` dan
`localStorage` kunci `omniroute-theme`.

---

## 1. Ringkasan Visual Website

| Aspek | Deskripsi |
|-------|-----------|
| **Gaya** | Modern, terang, teknis, developer-oriented. Nuansa "terminal/developer tool" dengan accent hijau cerah (lime). |
| **Suasana** | Profesional, efisien, terbuka (open source), terasa cepat dan ringan. |
| **Identitas** | OmniRoute oleh Cheaper Inference. Logo: `ci-mark-icon.svg`. Warna aksen utama: `#d8ff00` (lime neon). |
| **Tema** | Light (default) dan Dark, disimpan di `localStorage`, deteksi `prefers-color-scheme`. |
| **Tata letak** | Container maksimum `75rem` (1200px), header tinggi `3.75rem`, grid responsif. |

---

## 2. Design Tokens sebagai Variabel CSS

### 2.1 Typography (Font)

```css
--font-ui:      var(--font-inter), Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
--font-display: var(--font-instrument-serif), Georgia, serif;
--font-mono:    var(--font-ibm-plex-mono), "SFMono-Regular", Consolas, monospace;
```

Font dasar body: `font: 400 1rem/1.5 var(--font-ui)` → ukuran **16px**, line-height **1.5**, berat **400**.

### 2.2 Warna (Light Theme)

```css
--canvas:      #fbfbf8;   /* background utama */
--canvas-alt:  #f7f7f2;   /* background alternatif */
--surface:     #ffffff;   /* kertas / kartu */
--surface-raised:#eeeee8; /* surface yang sedikit terangkat */
--ink:         #040d10;   /* teks utama (prima) */
--body:        #040d10;   /* teks body */
--muted:       #575f5f;   /* teks sekunder */
--faint:       #737b78;   /* teks reduo / keterangan kecil */
--line-subtle: rgb(4 13 16 / 0.09);  /* border halus */
--line:        rgb(4 13 16 / 0.24);  /* border standar */
--line-strong: rgb(4 13 16 / 0.48);  /* border tebal/kuat */
--accent:      #d8ff00;   /* aksen prima (lime neon) */
--accent-strong: #9bb800; /* aksen gelap */
--accent-soft: rgb(216 255 0 / 0.18); /* background aksen transparan */
--success:     #5d7600;   /* sukses */
--danger:      #d94343;   /* bahaya / error */
```

### 2.3 Warna (Dark Theme — override)

```css
--canvas:      #071013;
--canvas-alt:  #111d20;
--surface:     #0d181b;
--surface-raised:#1a272a;
--ink:         #f2f6f4;
--body:        #f2f6f4;
--muted:       #a5afac;
--faint:       #8e9995;
--line-subtle: rgb(242 246 244 / 0.1);
--line:        rgb(242 246 244 / 0.24);
--line-strong: rgb(242 246 244 / 0.48);
--accent:      #d8ff00;
--accent-strong: #d8ff00;
--accent-soft: rgb(216 255 0 / 0.14);
--success:     #d8ff00;
--danger:      #ff7474;
```

### 2.4 Spacing dan Layout

```css
--container: 75rem;      /* 1200px — lebar maksimal konten */
--header-height: 3.75rem; /* 60px — tinggi header */
```

Ukuran font dasar: `1rem` (16px), line-height `1.5`.

### 2.5 Radius (Border Radius)

```css
--radius-sm:   0.25rem;   /* 4px */
--radius:      0.25rem;   /* 4px — standar */
--radius-lg:   0.25rem;   /* 4px */
--radius-control: 0.5rem; /* 8px — input / kontrol */
--radius-pill: 9999px;    /* piluh / fully rounded */
```

### 2.6 Shadow (Box Shadow)

```css
--shadow:      0 24px 58px rgb(4 13 16 / 0.07);   /* card besar / dropdown */
--shadow-sm:   0 1px 2px rgb(4 13 16 / 0.06);     /* elemen halus */
--shadow-hover:0 18px 38px rgb(4 13 16 / 0.12);   /* hover state */
```

Dark theme shadow:
- `--shadow: 0 24px 58px rgb(0 0 0 / 0.34)`
- `--shadow-sm: 0 1px 2px rgb(0 0 0 / 0.3)`
- `--shadow-hover: 0 20px 42px rgb(0 0 0 / 0.36)`

### 2.7 Transisi / Easing

```css
--ease:        cubic-bezier(0.22, 1, 0.36, 1);
--ease-draw:   cubic-bezier(0.42, 0.02, 0.24, 1);
--ease-reveal: cubic-bezier(0.16, 1, 0.3, 1);
```

---

## 3. Pemetaan Warna ke Peran Desain (POS Kasir)

| Peran Desain | Nilai OmniRoute (Light) | Nilai OmniRoute (Dark) | Keterangan |
|--------------|------------------------|------------------------|------------|
| `--color-background` | `#fbfbf8` | `#071013` | Latar utama halaman |
| `--color-surface` | `#ffffff` | `#0d181b` | Kartu, modal, panel |
| `--color-surface-raised` | `#eeeee8` | `#1a272a` | Surface yang terangkat |
| `--color-text-primary` | `#040d10` | `#f2f6f4` | Judul, teks utama |
| `--color-text-secondary` | `#575f5f` | `#a5afac` | Subtitel, keterangan |
| `--color-text-muted` | `#737b78` | `#8e9995` | Teks kecil, caption |
| `--color-border` | `rgb(4 13 16 / 0.24)` | `rgb(242 246 244 / 0.24)` | Garis pemisah |
| `--color-border-strong` | `rgb(4 13 16 / 0.48)` | `rgb(242 246 244 / 0.48)` | Border input/fokus |
| `--color-accent` | `#d8ff00` | `#d8ff00` | Tombol utama, aksi utama |
| `--color-accent-strong` | `#9bb800` | `#d8ff00` | Hover tombol utama |
| `--color-accent-soft` | `rgb(216 255 0 / 0.18)` | `rgb(216 255 0 / 0.14)` | Background aksen lembut |
| `--color-success` | `#5d7600` | `#d8ff00` | Status berhasil |
| `--color-danger` | `#d94343` | `#ff7474` | Error, hapus, peringatan |
| `--shadow-card` | `0 24px 58px rgb(4 13 16 / 0.07)` | `0 24px 58px rgb(0 0 0 / 0.34)` | Bayangan kartu |
| `--shadow-sm` | `0 1px 2px rgb(4 13 16 / 0.06)` | `0 1px 2px rgb(0 0 0 / 0.3)` | Bayangan halus |
| `--radius-button` | `0.25rem` | `0.25rem` | Radius tombol |
| `--radius-card` | `0.25rem` | `0.25rem` | Radius kartu |
| `--radius-input` | `0.5rem` | `0.5rem` | Radius input/form |
| `--radius-pill` | `9999px` | `9999px` | Badge, piluh |

---

## 4. Estimasi Breakpoint (Mobile Responsiveness)

| Breakpoint | Lepas (max-width) | Perubahan layout |
|------------|-------------------|------------------|
| Mobile (sm) | `640px` | Navbar menurun ke hamburger menu, kolom menjadi 1, padding dikurangi |
| Tablet (md) | `768px` | Grid 2 kolom, font judul sedikit mengecil |
| Desktop (lg) | `1024px` | Grid 3–4 kolom, layout penuh |
| Wide (xl) | `1280px` | Container terbatas pada `75rem` (1200px) |

> **Catatan:** Nilai breakpoint di atas adalah estimasi berdasarkan konvensi umum; nilai sebenarnya perlu diverifikasi dari CSS lengkap.

---

## 5. Catatan Implementasi

- Gunakan variabel CSS (CSS Custom Properties) agar switching tema light/dark mudah melalui atribut `data-theme` pada `<html>`.
- Font Inter sebagai utama untuk UI; Instrument Serif untuk judul besar; IBM Plex Mono untuk kode dan nomor.
- Accent `#d8ff00` digunakan sangat terang — cocok untuk tombol CTA utama, jangan gunakan untuk teks besar karena kontras terhadap background terang dapat rendah.
- Shadow menggunakan warna dengan opacity (`rgb(... / 0.07)`), sehingga otomatis menyesuaikan tema tanpa perlu override warna shadow di dark mode (kecuali nilai opacity yang disesuaikan).
- Container dibatasi pada `75rem` (1200px) dengan `margin: 0 auto` untuk sentralisasi.
