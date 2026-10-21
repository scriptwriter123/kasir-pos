import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.database import session_scope
from app.core.security import hash_password
from app.models import (
    Category,
    PaymentMethod,
    Product,
    Role,
    Store,
    Supplier,
    Unit,
    User,
)

ROLES = ["OWNER", "ADMIN", "SUPERVISOR", "CASHIER"]

CATEGORIES = [
    "Sembako",
    "Minuman",
    "Makanan Instan",
    "Bumbu",
    "Produk Segar",
    "Perawatan Rumah",
]

UNITS = [
    ("Piece", "pcs"),
    ("Kilogram", "kg"),
    ("Liter", "L"),
    ("Pack", "pack"),
]

SAMPLE_SUPPLIERS = [
    (
        "SUP-SEMBAKO",
        "Mitra Sembako Demo",
        "0800-000-1001",
        "Jl. Niaga Contoh No. 1",
    ),
    (
        "SUP-MINUMAN",
        "Distributor Minuman Demo",
        "0800-000-1002",
        "Jl. Distribusi Contoh No. 2",
    ),
    (
        "SUP-PANGAN",
        "Pemasok Pangan Demo",
        "0800-000-1003",
        "Jl. Pasar Contoh No. 3",
    ),
    (
        "SUP-SEGAR",
        "Pemasok Produk Segar Demo",
        "0800-000-1004",
        "Jl. Tani Contoh No. 4",
    ),
    (
        "SUP-RUMAH",
        "Distributor Perawatan Rumah Demo",
        "0800-000-1005",
        "Jl. Grosir Contoh No. 5",
    ),
]

SUPPLIER_BY_CATEGORY = {
    "Sembako": "SUP-SEMBAKO",
    "Minuman": "SUP-MINUMAN",
    "Makanan Instan": "SUP-PANGAN",
    "Bumbu": "SUP-PANGAN",
    "Produk Segar": "SUP-SEGAR",
    "Perawatan Rumah": "SUP-RUMAH",
}

# Barcode contoh bersifat fiktif dan ditujukan untuk uji pencarian/scan.
SAMPLE_PRODUCTS = [
    ("SKU-BRS-001", "2000000000001", "Beras Premium 5 kg", "Sembako", "Pack", 65000, 72000, 20, 3),
    ("SKU-GUL-001", "2000000000002", "Gula Pasir 1 kg", "Sembako", "Kilogram", 15500, 18000, 30, 5),
    ("SKU-MNY-001", "2000000000003", "Minyak Goreng 1 L", "Sembako", "Liter", 16500, 19000, 24, 5),
    ("SKU-TEP-001", "2000000000004", "Tepung Terigu 1 kg", "Sembako", "Kilogram", 10500, 12500, 20, 4),
    ("SKU-TEL-001", "2000000000005", "Telur Ayam 1 kg", "Produk Segar", "Kilogram", 27000, 31000, 15, 3),
    ("SKU-GRM-001", "2000000000006", "Garam Meja 500 g", "Bumbu", "Piece", 3500, 5000, 25, 5),
    ("SKU-KCP-001", "2000000000007", "Kecap Manis 135 ml", "Bumbu", "Piece", 6500, 8500, 18, 4),
    ("SKU-MIE-001", "2000000000008", "Mi Instan Goreng", "Makanan Instan", "Piece", 2500, 3500, 60, 12),
    ("SKU-MIE-002", "2000000000009", "Mi Instan Kuah", "Makanan Instan", "Piece", 2400, 3500, 60, 12),
    ("SKU-KOP-001", "2000000000010", "Kopi Sachet", "Minuman", "Piece", 1200, 2000, 50, 10),
    ("SKU-TEH-001", "2000000000011", "Teh Celup 25 kantong", "Minuman", "Pack", 8500, 11000, 15, 3),
    ("SKU-AIR-001", "2000000000012", "Air Mineral 600 ml", "Minuman", "Piece", 2500, 4000, 36, 8),
    ("SKU-SUS-001", "2000000000013", "Susu UHT 1 L", "Minuman", "Liter", 17500, 21000, 12, 3),
    ("SKU-SAB-001", "2000000000014", "Sabun Mandi Batang", "Perawatan Rumah", "Piece", 3500, 5000, 24, 5),
    ("SKU-DET-001", "2000000000015", "Deterjen Bubuk 800 g", "Perawatan Rumah", "Pack", 17000, 21000, 12, 3),
    ("SKU-PST-001", "2000000000016", "Pasta Gigi 120 g", "Perawatan Rumah", "Piece", 11500, 14000, 15, 3),
    ("SKU-TIS-001", "2000000000017", "Tisu Wajah 250 lembar", "Perawatan Rumah", "Pack", 9000, 12000, 15, 3),
    ("SKU-SGL-001", "2000000000018", "Air Galon Isi Ulang", "Minuman", "Piece", 6000, 8000, 10, 2),
]


def seed_data(
    session, *, include_users: bool = True, include_products: bool = True
) -> int:
    roles = {}
    for name in ROLES:
        role = session.query(Role).filter_by(name=name).first()
        if role is None:
            role = Role(name=name, description=f"Role {name}")
            session.add(role)
            session.flush()
        roles[name] = role

    if (
        include_users
        and session.query(User).filter_by(username="owner").first() is None
    ):
        session.add(
            User(
                username="owner",
                full_name="Owner",
                password_hash=hash_password("owner123"),
                role_id=roles["OWNER"].id,
            )
        )

    if session.query(Store).filter_by(code="MAIN").first() is None:
        session.add(Store(code="MAIN", name="Toko Utama"))

    categories = {}
    for name in CATEGORIES:
        category = session.query(Category).filter_by(name=name).first()
        if category is None:
            category = Category(name=name)
            session.add(category)
            session.flush()
        categories[name] = category

    units = {}
    for name, symbol in UNITS:
        unit = session.query(Unit).filter_by(name=name).first()
        if unit is None:
            unit = Unit(name=name, symbol=symbol)
            session.add(unit)
            session.flush()
        units[name] = unit

    suppliers = {}
    for code, name, phone, address in SAMPLE_SUPPLIERS:
        supplier = session.query(Supplier).filter_by(code=code).first()
        if supplier is None:
            supplier = Supplier(
                code=code,
                name=name,
                phone=phone,
                address=address,
            )
            session.add(supplier)
            session.flush()
        suppliers[code] = supplier

    if session.query(Category).filter_by(name="Umum").first() is None:
        session.add(Category(name="Umum"))

    for code, name in [
        ("CASH", "Tunai"),
        ("QRIS", "QRIS"),
        ("BANK", "Transfer Bank"),
        ("EWALLET", "E-Wallet"),
    ]:
        if session.query(PaymentMethod).filter_by(code=code).first() is None:
            session.add(PaymentMethod(code=code, name=name))

    added_products = 0
    if include_products:
        for (
            sku,
            barcode,
            name,
            category_name,
            unit_name,
            purchase_price,
            selling_price,
            stock_qty,
            min_stock,
        ) in SAMPLE_PRODUCTS:
            product = session.query(Product).filter_by(sku=sku).first()
            supplier = suppliers[SUPPLIER_BY_CATEGORY[category_name]]
            if product is not None:
                if product.supplier_id is None:
                    product.supplier_id = supplier.id
                continue
            session.add(
                Product(
                    sku=sku,
                    barcode=barcode,
                    name=name,
                    category_id=categories[category_name].id,
                    unit_id=units[unit_name].id,
                    supplier_id=supplier.id,
                    purchase_price=purchase_price,
                    selling_price=selling_price,
                    stock_qty=stock_qty,
                    min_stock=min_stock,
                )
            )
            added_products += 1

    return added_products


def main(argv: list[str] | None = None) -> None:
    argv = list(sys.argv[1:] if argv is None else argv)
    include_users = "--no-users" not in argv
    include_products = "--no-products" not in argv
    with session_scope() as session:
        added_products = seed_data(
            session,
            include_users=include_users,
            include_products=include_products,
        )
    if include_products:
        print(
            f"Seed selesai. {added_products} produk contoh ditambahkan "
            f"(tersedia {len(SAMPLE_PRODUCTS)} SKU contoh)."
        )
    else:
        print("Seed selesai (tanpa produk contoh).")
    if include_users:
        print(
            "Login awal: owner / owner123 (jika akun owner belum pernah dibuat)."
        )


if __name__ == "__main__":
    main()
