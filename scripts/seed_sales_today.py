import random
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from sqlalchemy.orm import joinedload

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.database import session_scope
from app.core.security import hash_password
from app.models import Product, Role, Sale, SaleItem, Shift, StockMovement, Store, User
from app.services.sales_service import SalesService


PRODUCTS_TO_SELL = [
    ("SKU-BRS-001", 72000, 65000),
    ("SKU-GUL-001", 18000, 15500),
    ("SKU-MNY-001", 19000, 16500),
    ("SKU-TEP-001", 12500, 10500),
    ("SKU-TEL-001", 31000, 27000),
    ("SKU-GRM-001", 5000, 3500),
    ("SKU-KCP-001", 8500, 6500),
    ("SKU-MIE-001", 3500, 2500),
    ("SKU-MIE-002", 3500, 2400),
    ("SKU-KOP-001", 2000, 1200),
    ("SKU-TEH-001", 11000, 8500),
    ("SKU-AIR-001", 4000, 2500),
    ("SKU-SUS-001", 21000, 17500),
    ("SKU-SAB-001", 5000, 3500),
    ("SKU-DET-001", 21000, 17000),
    ("SKU-PST-001", 14000, 11500),
    ("SKU-TIS-001", 12000, 9000),
    ("SKU-SGL-001", 8000, 6000),
]

PAYMENT_METHODS = ["CASH", "QRIS", "BANK", "EWALLET"]


def main() -> None:
    random.seed(42)
    added = 0

    with session_scope() as session:
        # Ambil cashier (USER dengan role CASHIER) atau buat jika belum ada
        from sqlalchemy.orm import joinedload

        cashier = (
            session.query(User)
            .options(joinedload(User.role))
            .join(User.role)
            .filter(Role.name == "CASHIER")
            .first()
        )
        if cashier is None:
            role = session.query(Role).filter_by(name="CASHIER").first()
            if role is None:
                role = Role(name="CASHIER", description="Kasir")
                session.add(role)
                session.flush()
            cashier = User(
                username="kasir_demo",
                full_name="Kasir Demo",
                password_hash=hash_password("kasir123"),
                role_id=role.id,
            )
            session.add(cashier)
            session.flush()

        # Ambil store utama
        store = session.query(Store).filter_by(code="MAIN").first()
        if store is None:
            store = Store(code="MAIN", name="Toko Utama")
            session.add(store)
            session.flush()

        # Buka shift untuk cashier jika belum ada
        shift = (
            session.query(Shift)
            .filter_by(cashier_id=cashier.id, store_id=store.id)
            .filter(Shift.status == "OPEN")
            .order_by(Shift.opened_at.desc())
            .first()
        )
        if shift is None:
            shift = Shift(
                store_id=store.id,
                cashier_id=cashier.id,
                opened_at=datetime.now(timezone.utc),
                opening_cash=500000,
                status="OPEN",
            )
            session.add(shift)
            session.flush()

        # Ambil produk yang tersedia
        products = {}
        for sku, selling_price, purchase_price in PRODUCTS_TO_SELL:
            product = session.query(Product).filter_by(sku=sku).first()
            if product is not None and product.is_active:
                products[sku] = product

        if not products:
            print("Tidak ada produk aktif. Jalankan scripts\\seed.py terlebih dahulu.")
            return

        service = SalesService(session)
        now = datetime.now(timezone.utc)

        for i in range(100):
            # Pilih 1-3 produk acak per transaksi
            chosen = random.sample(list(products.items()), k=random.randint(1, 3))
            items = []
            grand_total = 0

            for sku, product in chosen:
                qty = random.randint(1, 5)
                unit_price = product.selling_price
                line_total = qty * unit_price
                grand_total += line_total
                items.append(
                    {
                        "product_id": product.id,
                        "qty": qty,
                        "unit_price": unit_price,
                        "discount": 0,
                        "line_total": line_total,
                    }
                )

            # Waktu transaksi acak dalam rentang hari ini (08:00 - 21:00)
            hour = random.randint(8, 20)
            minute = random.randint(0, 59)
            second = random.randint(0, 59)
            created_at = now.replace(
                hour=hour, minute=minute, second=second, microsecond=0
            )

            sale = Sale(
                invoice_no=f"POS-{now:%Y%m%d}-{uuid4().hex[:6].upper()}-{i:03d}",
                store_id=store.id,
                shift_id=shift.id,
                cashier_id=cashier.id,
                subtotal=grand_total,
                discount=0,
                tax=0,
                grand_total=grand_total,
                status="PAID",
                created_at=created_at,
                updated_at=created_at,
            )

            # Panggil service checkout untuk memastikan stok dan journal tercatat
            payments = [
                {"method": random.choice(PAYMENT_METHODS), "amount": grand_total}
            ]
            try:
                service.checkout(sale, items, payments)
                added += 1
            except Exception as exc:
                print(f"Transaksi {i+1} gagal: {exc}")
                session.rollback()

    print(f"Seed selesai. {added} transaksi dummy untuk hari ini telah dibuat.")


if __name__ == "__main__":
    main()
