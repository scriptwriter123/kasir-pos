"""Seed 5 produk dummy stok rendah untuk clue "Catat Belanja".

Menambahkan produk dengan stok < 5 (termasuk 0) sehingga label
"Clue stok menipis" di tab Belanja menampilkan contoh data.
Idempoten: SKU yang sudah ada dilewati.
"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.database import session_scope
from app.models import Category, Product, Supplier, Unit

# (sku, nama, kategori, satuan, harga beli, harga jual, stok)
LOW_STOCK_PRODUCTS = [
    ("SKU-LOW-001", "Roti Tawar Gandum", "Sembako", "Piece", 14_000, 17_500, 4),
    ("SKU-LOW-002", "Sirup Cokelat 600 ml", "Minuman", "Liter", 18_000, 22_000, 3),
    ("SKU-LOW-003", "Cokelat Bubuk 200 g", "Minuman", "Piece", 21_000, 26_000, 2),
    ("SKU-LOW-004", "Sarden Kaleng 155 g", "Makanan Instan", "Piece", 9_500, 12_500, 1),
    ("SKU-LOW-005", "Kecap Asin 275 ml", "Bumbu", "Piece", 8_000, 10_500, 0),
]

SUPPLIER_CODE_BY_CATEGORY = {
    "Sembako": "SUP-SEMBAKO",
    "Minuman": "SUP-MINUMAN",
    "Makanan Instan": "SUP-PANGAN",
    "Bumbu": "SUP-PANGAN",
}


def seed_low_stock_products(session) -> tuple[int, int]:
    added = 0
    skipped = 0
    for sku, name, category_name, unit_name, cost, price, stock_qty in (
        LOW_STOCK_PRODUCTS
    ):
        if session.query(Product).filter_by(sku=sku).first() is not None:
            skipped += 1
            continue
        category = session.query(Category).filter_by(name=category_name).first()
        unit = session.query(Unit).filter_by(name=unit_name).first()
        supplier = (
            session.query(Supplier)
            .filter_by(code=SUPPLIER_CODE_BY_CATEGORY[category_name])
            .first()
        )
        session.add(
            Product(
                sku=sku,
                name=name,
                category_id=category.id if category else None,
                unit_id=unit.id if unit else None,
                supplier_id=supplier.id if supplier else None,
                purchase_price=cost,
                selling_price=price,
                stock_qty=stock_qty,
                min_stock=5,
                is_active=True,
            )
        )
        added += 1
    return added, skipped


def main() -> None:
    with session_scope() as session:
        added, skipped = seed_low_stock_products(session)
    print(
        f"Seed stok rendah selesai: {added} produk ditambahkan, "
        f"{skipped} sudah ada sebelumnya."
    )


if __name__ == "__main__":
    main()
