# Architecture

Pipeline:
`PySide6 UI → Service Layer → Repository Layer → SQLAlchemy ORM → SQLite DB`

### Dependency rules
- UI hanya mengurus tampilan/input.
- UI tidak boleh melakukan query SQLAlchemy.
- Service mengelola aturan bisnis dan transaction scope.
- Repository mengisolasi CRUD/query.
- Model hanya mendefinisikan struktur data.

### Role routing
- OWNER → Dashboard
- ADMIN/SUPERVISOR → Operational Dashboard
- CASHIER → CashierView

### Checkout transaction
BEGIN → Sale → Sale Items → Payments → Update Stock → Stock Movement → Audit Log → COMMIT.
Jika gagal → ROLLBACK.
