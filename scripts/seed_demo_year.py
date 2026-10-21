"""Seed data demo: simulasi operasional toko selama ±1 tahun.

Menyiapkan database LIVE (pos.db) dengan data dummy realistis agar
pengujian end-to-end bisa langsung jalan:

  * Pembukuan & jurnal saldo awal digeser mundur 1 tahun.
  * Transaksi penjualan harian (kasir, shift, item, pembayaran, jurnal).
  * Pembelian supplier bulanan (Lunas/Tempo/DP) + stok masuk.
  * Pengeluaran bulanan (sewa, listrik, gaji, ...) termasuk Hutang/DP.
  * Absensi (riwayat login) + laporan kasir harian.
  * Jurnal penyetoran modal bila kas proyeksi jatuh terlalu rendah.

Jalankan dengan aplikasi TERTUTUP:

    python scripts/seed_demo_year.py

Skrip ini gagal (abort) bila database sudah berisi penjualan/demo marker,
sehingga aman dijalankan ulang.
"""

from __future__ import annotations

import random
import sys
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import func, select, text

from app.core.database import SessionLocal
from app.core.security import hash_password
from app.models import (
    Account,
    AuditLog,
    CashierDailyReport,
    Expense,
    FinancialSettings,
    JournalEntry,
    LoginHistory,
    Payment,
    Product,
    PurchaseOrder,
    PurchaseOrderItem,
    Role,
    Sale,
    SaleItem,
    Shift,
    StockMovement,
    Store,
    Supplier,
    User,
)
from app.services.financial_service import FinancialService
from app.utils.formatters import rupiah

SEED = 20261018
TARGET_END_CASH = 60_000_000
FLOOR_CASH = 2_000_000
DEMO_MARKER = "Setoran modal pemilik (data demo)"

# Produk laris tiap hari; SKU-LOW-* sengaja TIDAK dijual agar tetap
# tampil di tab "Stok Tipis" (stok menipis).
POPULAR = {
    "SKU-MIE-001", "SKU-MIE-002", "SKU-KOP-001", "SKU-AIR-001",
    "SKU-TEL-001", "SKU-BRS-001", "SKU-GUL-001", "SKU-MNY-001",
    "SKU-TEH-001", "SKU-SGL-001",
}
MIDMOVE = {
    "SKU-KCP-001", "SKU-GRM-001", "SKU-TEP-001", "SKU-SUS-001",
    "SKU-SAB-001", "SKU-DET-001", "SKU-PST-001", "SKU-TIS-001",
}


def _utc(dt: datetime) -> datetime:
    return dt.astimezone(timezone.utc)


def main() -> None:
    rng = random.Random(SEED)
    local_tz = datetime.now().astimezone().tzinfo
    today = date.today()
    seed_start = today - timedelta(days=364)
    days = [
        seed_start + timedelta(days=i)
        for i in range((today - seed_start).days + 1)
    ]
    days_set = set(days)

    session = SessionLocal()
    try:
        existing_sales = (
            session.scalar(select(func.count()).select_from(Sale)) or 0
        )
        if existing_sales:
            print(
                f"ABORT: database sudah berisi {existing_sales} penjualan. "
                "Seed demo tidak dijalankan dua kali."
            )
            return
        marker = session.scalar(
            select(func.count())
            .select_from(JournalEntry)
            .where(JournalEntry.memo == DEMO_MARKER)
        )
        if marker:
            print("ABORT: penyetoran modal demo sudah pernah dibuat.")
            return

        fin = FinancialService(session)
        settings = session.get(FinancialSettings, 1)
        if settings is None or settings.effective_from is None:
            print("ABORT: pembukuan belum diaktifkan (tab Modal Awal).")
            return

        # 1) Geser pembukuan mundur 1 tahun + jurnal saldo awal.
        settings.effective_from = seed_start
        for entry in session.scalars(
            select(JournalEntry).where(JournalEntry.source_type == "OPENING")
        ):
            if entry.entry_date > seed_start:
                entry.entry_date = seed_start
        session.flush()
        print(f"Pembukuan digeser ke {seed_start} (hari ini {today}).")

        # 2) Master: toko, owner, kasir, akun.
        store = session.scalar(select(Store).order_by(Store.id))
        if store is None:
            raise RuntimeError("Data toko belum ada.")
        owner = session.scalar(
            select(User).join(Role).where(Role.name == "OWNER").limit(1)
        )
        if owner is None:
            raise RuntimeError("Akun OWNER belum ada.")
        cashier_role = session.scalar(select(Role).where(Role.name == "CASHIER"))
        if cashier_role is None:
            cashier_role = Role(name="CASHIER", description="Role CASHIER")
            session.add(cashier_role)
            session.flush()
        for username, full_name in (
            ("kasir1", "Kasir Satu"),
            ("kasir2", "Kasir Dua"),
        ):
            if (
                session.scalar(select(User).where(User.username == username))
                is None
            ):
                session.add(
                    User(
                        username=username,
                        full_name=full_name,
                        password_hash=hash_password("kasir123"),
                        role_id=cashier_role.id,
                    )
                )
        session.flush()

        cashiers = list(
            session.scalars(
                select(User)
                .join(Role)
                .where(
                    Role.name.in_(("CASHIER", "kasir")),
                    User.is_active.is_(True),
                    User.deleted_at.is_(None),
                )
                .order_by(User.id)
            )
        )
        if not cashiers:
            raise RuntimeError("Tidak ada akun kasir.")
        print(
            "Kasir: "
            + ", ".join(f"{u.username} ({u.full_name})" for u in cashiers)
        )

        accounts = {
            account.code: account
            for account in session.scalars(
                select(Account).order_by(Account.code)
            )
        }
        for code in ("1000", "1010", "2000", "3000", "4000", "5000"):
            if code not in accounts:
                raise RuntimeError(f"Akun wajib {code} belum ada.")
        payables = accounts["2000"]

        # 3) Produk yang boleh dijual.
        products = list(
            session.scalars(
                select(Product)
                .where(
                    Product.is_active.is_(True),
                    Product.deleted_at.is_(None),
                )
                .order_by(Product.id)
            )
        )
        sellable = [
            p
            for p in products
            if not p.sku.startswith("SKU-LOW") and p.purchase_price > 0
        ]
        if not sellable:
            raise RuntimeError("Tidak ada produk jual yang valid.")
        for product in products:
            if product.stock_qty < 0:
                raise RuntimeError(f"Stok negatif pada {product.sku}.")
        weights = [
            6 if p.sku in POPULAR else 3 if p.sku in MIDMOVE else 1
            for p in sellable
        ]
        any_supplier = session.scalar(select(Supplier.id).order_by(Supplier.id))
        if any_supplier is None:
            raise RuntimeError("Data supplier belum ada.")

        # Lengkapi supplier produk yang belum terhubung (agar pembelian
        # terdistribusi ke pemasok yang sesuai kategori).
        supplier_by_category = {
            "Sembako": 1,
            "Minuman": 2,
            "Makanan Instan": 3,
            "Bumbu": 3,
            "Produk Segar": 4,
            "Perawatan Rumah": 5,
        }
        for product in products:
            if product.supplier_id is None:
                category_name = (
                    product.category.name if product.category else None
                )
                product.supplier_id = (
                    supplier_by_category.get(category_name, any_supplier)
                )
        session.flush()

        # 4) Rencana penjualan seluruh periode.
        plan_sales: dict[date, list[dict]] = defaultdict(list)
        bucket_qty: dict[date, dict[int, int]] = defaultdict(
            lambda: defaultdict(int)
        )
        invoice_seq: dict[date, int] = defaultdict(int)

        for day in days:
            count = rng.randint(6, 12)
            if day.weekday() in (5, 6):
                count += rng.randint(2, 5)
            for _ in range(count):
                n_lines = rng.choices((1, 2, 3, 4), (0.25, 0.35, 0.28, 0.12))[0]
                chosen = rng.choices(sellable, weights=weights, k=n_lines)
                lines = []
                for product in chosen:
                    qty = rng.choices((1, 2, 3), (0.55, 0.3, 0.15))[0]
                    lines.append((product, qty))
                invoice_seq[day] += 1
                method = rng.choices(("CASH", "QRIS", "BANK"), (0.7, 0.2, 0.1))[0]
                plan_sales[day].append(
                    {
                        "lines": lines,
                        "method": method,
                        "hour": rng.randint(8, 20),
                        "minute": rng.randint(0, 59),
                        "invoice": f"INV-{day:%Y%m%d}-{invoice_seq[day]:03d}",
                    }
                )

        # Total terjual per kelompok pembelian (tanggal yang sama).
        # Pembelian kelompok dilakukan di awal hari SEBELUM penjualan hari
        # itu, sehingga stok tidak pernah jatuh di bawah stok hari ini.
        for day, sales in plan_sales.items():
            purchase_day = max(day.replace(day=1), seed_start)
            for sale in sales:
                for product, qty in sale["lines"]:
                    bucket_qty[purchase_day][product.id] += qty

        # 5) Rencana pengeluaran bulanan.
        months = sorted({d.replace(day=1) for d in days})
        plan_expenses: dict[date, list[dict]] = defaultdict(list)
        for month_idx, month in enumerate(months):
            templates = [
                (1, "6100", 1_500_000, "Pemilik Ruko", "Sewa ruko", "CASH", True),
                (
                    8, "6200", rng.randint(550_000, 750_000),
                    "PLN & PDAM", "Listrik dan air", "CASH", True,
                ),
                (12, "6300", 250_000, "ISP Nusantara", "Internet toko", "CASH", True),
                (
                    18, "6500", rng.randint(250_000, 400_000),
                    "Kasir Harian", "Transportasi operasional", "CASH", True,
                ),
                (
                    20, "6600", rng.randint(150_000, 300_000),
                    "Toko ATK", "Perlengkapan toko", "CASH", False,
                ),
                (25, "6400", 3_000_000, "Karyawan Toko", "Gaji karyawan", None, True),
                (
                    22, "6900", rng.randint(100_000, 250_000),
                    "Berbagai Pihak", "Beban lain-lain", None, True,
                ),
            ]
            for day_of_month, code, amount, payee, desc, status, always in templates:
                if not always and rng.random() < 0.33:
                    continue
                try:
                    day = date(month.year, month.month, day_of_month)
                except ValueError:
                    continue
                if day not in days_set:
                    continue
                if status is None:
                    if code == "6400":
                        if month_idx % 6 == 3:
                            status = "HUTANG"
                        elif month_idx % 9 == 7:
                            status = "DP"
                        else:
                            status = "CASH"
                    else:
                        status = "HUTANG" if month_idx % 4 == 1 else "CASH"
                plan_expenses[day].append(
                    {
                        "code": code,
                        "amount": amount,
                        "payee": payee,
                        "description": f"{desc} {month:%Y-%m}",
                        "status": status,
                    }
                )

        # 6) Saldo kas jurnal lama, dikelompokkan per tanggal.
        pre_cash_rows = session.execute(
            text(
                "SELECT je.entry_date, "
                "SUM(CASE WHEN jl.debit > 0 THEN jl.debit "
                "ELSE -jl.credit END) "
                "FROM journal_lines jl "
                "JOIN journal_entries je ON je.id = jl.journal_entry_id "
                "JOIN accounts a ON a.id = jl.account_id "
                "WHERE a.code = '1000' GROUP BY je.entry_date"
            )
        ).all()
        pre_cash_by_day: dict[date, int] = defaultdict(int)
        for entry_date, amount in pre_cash_rows:
            day = date.fromisoformat(str(entry_date)[:10])
            pre_cash_by_day[max(day, seed_start)] += int(amount)

        running = 0
        min_running = 0

        def bump(delta: int) -> None:
            nonlocal running, min_running
            running += delta
            if running < min_running:
                min_running = running

        # Pembelian pra-seed yang terjadi DI DALAM periode menambah stok
        # fisik; saldo awal persediaan harus dikurangi agar Neraca cocok
        # dengan Nilai Inventaris.
        preseed_po_value = 0
        for po in session.scalars(select(PurchaseOrder)):
            if po.ordered_at is None:
                continue
            if fin._local_date(po.ordered_at) >= seed_start:
                preseed_po_value += int(po.subtotal)

        original_stock = {p.id: p.stock_qty for p in products}
        counts: dict[str, int] = defaultdict(int)
        cashier_report: dict[tuple[int, date], dict[str, int]] = {}
        by_id = {p.id: p for p in products}
        cash_account_id = accounts["1000"].id

        # 7) Rekam per hari.
        for day in days:
            bump(pre_cash_by_day.get(day, 0))

            # --- pembelian supplier (stok masuk) ---
            if day in bucket_qty:
                grouped: dict[int, list[tuple[Product, int]]] = defaultdict(list)
                for product_id, qty in bucket_qty[day].items():
                    if qty <= 0:
                        continue
                    product = by_id[product_id]
                    supplier_id = product.supplier_id or any_supplier
                    grouped[int(supplier_id)].append((product, qty))
                po_seq = 0
                for supplier_id in sorted(grouped):
                    rows = grouped[supplier_id]
                    total = sum(qty * p.purchase_price for p, qty in rows)
                    if total <= 0:
                        continue
                    po_seq += 1
                    roll = rng.random()
                    status = (
                        "PAID" if roll < 0.7 else "TEMPO" if roll < 0.85 else "DP"
                    )
                    due_day = day + timedelta(days=30 if status == "TEMPO" else 14)
                    po = PurchaseOrder(
                        order_no=f"PO-{day:%Y%m%d}-{po_seq:03d}",
                        supplier_id=supplier_id,
                        store_id=store.id,
                        created_by=owner.id,
                        status="RECEIVED",
                        ordered_at=_utc(
                            datetime.combine(day, time(9, 0), tzinfo=local_tz)
                        ),
                        subtotal=total,
                        payment_status="TEMPO",
                        due_date=datetime.combine(
                            due_day, time.min, tzinfo=local_tz
                        ),
                        paid_amount=0,
                    )
                    session.add(po)
                    session.flush()
                    for product, qty in rows:
                        before = product.stock_qty
                        product.stock_qty = before + qty
                        session.add(
                            PurchaseOrderItem(
                                purchase_order_id=po.id,
                                product_id=product.id,
                                ordered_qty=qty,
                                received_qty=qty,
                                unit_cost=product.purchase_price,
                            )
                        )
                        session.add(
                            StockMovement(
                                product_id=product.id,
                                movement_type="PURCHASE",
                                stock_before=before,
                                qty=qty,
                                stock_after=product.stock_qty,
                                reference_type="PURCHASE_ORDER",
                                reference_id=po.id,
                                note=f"Pembelian {po.order_no} (data demo).",
                            )
                        )
                    fin.post_purchase(owner.id, po)
                    counts["purchase"] += 1
                    counts["purchase_item"] += len(rows)
                    if status == "PAID":
                        fin._record_document_payment(
                            actor=owner,
                            purchase=po,
                            amount=total,
                            payment_account_id=cash_account_id,
                            payment_method="CASH",
                            paid_at=_utc(
                                datetime.combine(day, time(9, 30), tzinfo=local_tz)
                            ),
                        )
                        po.due_date = None
                        bump(-total)
                    elif status == "DP":
                        dp = (total * 4) // 10 // 5000 * 5000
                        if dp <= 0:
                            dp = total // 2
                        if dp <= 0 or dp >= total:
                            dp = max(1, total // 2)
                        fin._record_document_payment(
                            actor=owner,
                            purchase=po,
                            amount=dp,
                            payment_account_id=cash_account_id,
                            payment_method="CASH",
                            paid_at=_utc(
                                datetime.combine(day, time(9, 30), tzinfo=local_tz)
                            ),
                        )
                        po.payment_status = "DP"
                        bump(-dp)
                    session.flush()

            # --- pengeluaran operasional ---
            for item in plan_expenses.get(day, ()):
                account = accounts.get(item["code"])
                if account is None:
                    continue
                amount = item["amount"]
                status = item["status"]
                due = None
                if status == "HUTANG":
                    due = day + timedelta(days=30)
                elif status == "DP":
                    due = day + timedelta(days=14)
                expense = Expense(
                    recorded_by=owner.id,
                    category=account.name,
                    account_id=account.id,
                    amount=amount,
                    paid_amount=0,
                    payment_status=status,
                    incurred_at=_utc(
                        datetime.combine(day, time(10, 0), tzinfo=local_tz)
                    ),
                    due_date=due,
                    payee=item["payee"],
                    description=item["description"],
                )
                session.add(expense)
                session.flush()
                fin._create_entry(
                    entry_date=day,
                    source_type="EXPENSE",
                    source_id=expense.id,
                    memo=f"Pengeluaran: {account.name}",
                    posted_by=owner.id,
                    lines=[
                        (account.id, amount, 0, item["description"]),
                        (payables.id, 0, amount, "Hutang pengeluaran"),
                    ],
                )
                session.add(
                    AuditLog(
                        user_id=owner.id,
                        action="EXPENSE_RECORDED",
                        entity_type="Expense",
                        entity_id=expense.id,
                        detail=f"Pengeluaran {account.name}; nominal {amount}",
                    )
                )
                if status in {"CASH", "DP"}:
                    paid = amount if status == "CASH" else amount // 2
                    fin._record_document_payment(
                        actor=owner,
                        expense=expense,
                        amount=paid,
                        payment_account_id=cash_account_id,
                        payment_method="CASH",
                        paid_at=_utc(
                            datetime.combine(day, time(10, 15), tzinfo=local_tz)
                        ),
                    )
                    if status == "DP":
                        expense.payment_status = "DP"
                    bump(-paid)
                counts["expense"] += 1
                session.flush()

            # --- shift, absensi, penjualan ---
            sales_today = plan_sales.get(day, ())
            cashier = rng.choice(cashiers)
            shift = Shift(
                store_id=store.id,
                cashier_id=cashier.id,
                opened_at=_utc(datetime.combine(day, time(7, 50), tzinfo=local_tz)),
                closed_at=_utc(datetime.combine(day, time(21, 5), tzinfo=local_tz)),
                opening_cash=300_000,
                status="CLOSED",
            )
            session.add(shift)
            session.flush()
            session.add(
                LoginHistory(
                    user_id=cashier.id,
                    login_at=_utc(
                        datetime.combine(
                            day, time(8, rng.randint(40, 55)), tzinfo=local_tz
                        )
                    ),
                )
            )
            if rng.random() < 0.35:
                session.add(
                    LoginHistory(
                        user_id=owner.id,
                        login_at=_utc(
                            datetime.combine(
                                day, time(9, rng.randint(0, 25)), tzinfo=local_tz
                            )
                        ),
                    )
                )
            counts["login"] += 1

            day_count = 0
            day_total = 0
            for sale_plan in sales_today:
                lines = []
                for product, planned_qty in sale_plan["lines"]:
                    qty = min(planned_qty, product.stock_qty)
                    if qty <= 0:
                        continue
                    lines.append((product, qty))
                if not lines:
                    continue
                total = sum(p.selling_price * qty for p, qty in lines)
                sale = Sale(
                    invoice_no=sale_plan["invoice"],
                    store_id=store.id,
                    shift_id=shift.id,
                    cashier_id=cashier.id,
                    subtotal=total,
                    discount=0,
                    tax=0,
                    grand_total=total,
                    status="PAID",
                    created_at=_utc(
                        datetime.combine(
                            day,
                            time(sale_plan["hour"], sale_plan["minute"]),
                            tzinfo=local_tz,
                        )
                    ),
                )
                session.add(sale)
                session.flush()
                sale_items = []
                for product, qty in lines:
                    before = product.stock_qty
                    product.stock_qty = before - qty
                    item = SaleItem(
                        sale_id=sale.id,
                        product_id=product.id,
                        qty=qty,
                        unit_price=product.selling_price,
                        unit_cost=product.purchase_price,
                        discount=0,
                        line_total=qty * product.selling_price,
                    )
                    session.add(item)
                    sale_items.append(item)
                    session.add(
                        StockMovement(
                            product_id=product.id,
                            movement_type="SALE",
                            stock_before=before,
                            qty=-qty,
                            stock_after=product.stock_qty,
                            reference_type="SALE",
                            reference_id=sale.id,
                        )
                    )
                method = sale_plan["method"]
                reference = None
                if method != "CASH":
                    reference = f"{method}-{day:%y%m%d}-{day_count:04d}"
                session.add(
                    Payment(
                        sale_id=sale.id,
                        method=method,
                        amount=total,
                        reference=reference,
                    )
                )
                fin.post_sale(
                    cashier.id,
                    sale,
                    [{"method": method, "amount": total}],
                    sale_items,
                )
                session.add(
                    AuditLog(
                        user_id=cashier.id,
                        action="SALE_COMPLETED",
                        entity_type="Sale",
                        entity_id=sale.id,
                        detail=f"Invoice {sale.invoice_no}; total {total}",
                    )
                )
                if method == "CASH":
                    bump(total)
                day_count += 1
                day_total += total
                counts["sale"] += 1
                counts["sale_item"] += len(lines)

            key = (cashier.id, day)
            report = cashier_report.get(key)
            if report is None:
                cashier_report[key] = {"count": day_count, "total": day_total}
            else:
                report["count"] += day_count
                report["total"] += day_total

            if day.day in (1, 15) or day == today:
                session.flush()

        # 8) Laporan kasir harian.
        for (cashier_id, day), data in cashier_report.items():
            session.add(
                CashierDailyReport(
                    cashier_id=cashier_id,
                    report_date=day,
                    sales_count=data["count"],
                    sales_total=data["total"],
                    notes="",
                )
            )
            counts["daily_report"] += 1

        # 9) Penyetoran modal bila kas proyeksi terlalu rendah.
        final_cash = running
        required = max(
            0,
            TARGET_END_CASH - final_cash,
            FLOOR_CASH - min_running,
        )
        if required > 0:
            fin._create_entry(
                entry_date=seed_start,
                source_type="OPENING",
                source_id=2,
                memo=DEMO_MARKER,
                posted_by=owner.id,
                lines=[
                    (accounts["1000"].id, required, 0, DEMO_MARKER),
                    (accounts["3000"].id, 0, required, DEMO_MARKER),
                ],
            )
            running += required

        # 9b) Saldo awal persediaan: stok fisik hari pertama dinilai agar
        # akun Persediaan di Neraca konsisten dengan tab Nilai Inventaris.
        stock_value = sum(
            p.stock_qty * p.purchase_price
            for p in products
            if p.stock_qty > 0 and p.purchase_price > 0
        ) - preseed_po_value
        if stock_value > 0:
            fin._create_entry(
                entry_date=seed_start,
                source_type="OPENING",
                source_id=3,
                memo="Saldo awal persediaan (data demo)",
                posted_by=owner.id,
                lines=[
                    (accounts["1200"].id, stock_value, 0, "Stok barang awal"),
                    (accounts["3000"].id, 0, stock_value, "Modal persediaan"),
                ],
            )
        session.flush()

        # 10) Verifikasi.
        db_cash = int(
            session.scalar(
                text(
                    "SELECT COALESCE(SUM(CASE WHEN jl.debit > 0 "
                    "THEN jl.debit ELSE -jl.credit END), 0) "
                    "FROM journal_lines jl JOIN accounts a "
                    "ON a.id = jl.account_id WHERE a.code = '1000'"
                )
            )
        )
        if db_cash != running:
            raise RuntimeError(
                f"Saldo kas tidak cocok: db={db_cash} hitungan={running}"
            )
        drift = [
            (p.sku, original_stock[p.id], p.stock_qty)
            for p in products
            if p.stock_qty != original_stock[p.id]
        ]
        if drift:
            raise RuntimeError(f"Stok produk berubah: {drift}")

        session.commit()

        print("\n=== SEED DEMO 1 TAHUN SELESAI ===")
        print(f"Periode      : {seed_start} .. {today} ({len(days)} hari)")
        print(
            f"Penjualan    : {counts['sale']} transaksi, "
            f"{counts['sale_item']} item"
        )
        print(
            f"Pembelian    : {counts['purchase']} PO, "
            f"{counts['purchase_item']} baris"
        )
        print(f"Pengeluaran  : {counts['expense']} dokumen")
        print(f"Absensi      : {counts['login']} riwayat login")
        print(f"Laporan kasir: {counts['daily_report']} baris")
        if required:
            print(f"Penyetoran   : {rupiah(required)}")
        else:
            print("Penyetoran   : -")
        print(
            f"Akhir kas    : {rupiah(db_cash)} "
            f"(minimal {rupiah(min_running + required)})"
        )
        print("Selesai. Buka aplikasi untuk memeriksa laporan.")
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


if __name__ == "__main__":
    main()
