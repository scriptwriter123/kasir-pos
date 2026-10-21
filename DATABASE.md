# Database Foundation

SQLite PRAGMA wajib:
- foreign_keys=ON
- journal_mode=WAL
- busy_timeout=5000

Semua nilai uang memakai INTEGER Rupiah.
Timestamp memakai UTC.
Entity operasional memakai soft delete bila relevan.

Runtime database produksi dirancang berada di:
`%LOCALAPPDATA%\POSApp\data\pos.db`
Database dibuat dari migrasi saat aplikasi pertama kali dijalankan. Installer
tidak memuat atau menyalin file database; pengguna membuat akun OWNER pertama
kali dari layar aplikasi.

## Alembic

Migrasikan database ke revisi terbaru dengan:
```powershell
python scripts\init_db.py
```

Tutup aplikasi POS sebelum menjalankan migrasi agar SQLite tidak mengunci
database. Jangan menghapus database atau menandai revisi secara manual untuk
memperbaiki error kolom yang belum ada; jalankan migrasi agar skema diperbarui
tanpa menghilangkan data.

Setelah mengubah model, buat dan jalankan revisi:
```powershell
python -m alembic revision --autogenerate -m "deskripsi perubahan"
python -m alembic upgrade head
```

Database lama yang skemanya sudah dibuat melalui `create_all()` perlu diperiksa
kesesuaiannya dengan migrasi awal sebelum dicatat tanpa menjalankan DDL:
```powershell
python -m alembic stamp head
```

Catatan: PDF menetapkan 37 tabel dalam 7 domain, tetapi tidak menentukan seluruh field setiap tabel.
Fondasi ini membuat tabel inti terlebih dahulu. Detail tabel tambahan akan dikembangkan pada Phase 3
tanpa mengubah boundary layer.

Skema saat ini memiliki 27 tabel. Selain 16 tabel inti, model mencakup permission
beserta relasi role, price list beserta item, promotion, purchase order beserta
item, stock opname beserta item, expense, dan laporan kasir harian. Definisi
tabel lain yang tidak dijabarkan dalam roadmap belum dibuat agar struktur
database tidak diisi dengan asumsi yang tidak memiliki dasar kebutuhan.
