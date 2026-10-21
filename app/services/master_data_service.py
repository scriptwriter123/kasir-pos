from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import AuthorizationError, ValidationError
from app.models import Category, Product, StockMovement, Supplier, Unit, User


class MasterDataService:
    def __init__(self, session: Session):
        self.session = session

    def list_categories(self) -> list[Category]:
        return list(
            self.session.scalars(
                select(Category)
                .where(Category.deleted_at.is_(None))
                .order_by(Category.name)
            )
        )

    def list_units(self) -> list[Unit]:
        return list(
            self.session.scalars(
                select(Unit)
                .where(Unit.deleted_at.is_(None))
                .order_by(Unit.name)
            )
        )

    def list_suppliers(self) -> list[Supplier]:
        return list(
            self.session.scalars(
                select(Supplier)
                .where(Supplier.deleted_at.is_(None))
                .order_by(Supplier.name)
            )
        )

    def list_products(self) -> list[Product]:
        return list(
            self.session.scalars(
                select(Product)
                .where(Product.deleted_at.is_(None))
                .order_by(Product.name, Product.sku)
            )
        )

    def create_category(self, actor: User, name: str) -> Category:
        return self.create_categories(actor, [name])[0]

    def ensure_default_category(self, actor: User) -> Category:
        """Kembalikan kategori 'Umum'; buat bila belum ada."""
        self._require_owner(actor)
        existing = self.session.scalar(
            select(Category).where(
                func.lower(Category.name) == "umum",
                Category.deleted_at.is_(None),
            )
        )
        if existing is not None:
            return existing
        return self.create_categories(actor, ["Umum"])[0]

    def create_categories(self, actor: User, names: list[str]) -> list[Category]:
        self._require_owner(actor)
        normalized_names = [name.strip() for name in names if name.strip()]
        if not normalized_names:
            raise ValidationError("Isi minimal satu nama kategori.")
        if any(len(name) > 100 for name in normalized_names):
            raise ValidationError("Nama kategori maksimal 100 karakter.")

        folded_names = [name.casefold() for name in normalized_names]
        if len(set(folded_names)) != len(folded_names):
            raise ValidationError("Nama kategori yang diisi tidak boleh duplikat.")

        categories = []
        try:
            for normalized_name in normalized_names:
                existing = self.session.scalar(
                    select(Category).where(
                        func.lower(Category.name) == normalized_name.casefold()
                    )
                )
                if existing is not None:
                    if existing.deleted_at is not None:
                        existing.deleted_at = None
                        categories.append(existing)
                        continue
                    raise ValidationError(
                        f"Kategori dengan nama {normalized_name} sudah ada."
                    )

                category = Category(name=normalized_name)
                self.session.add(category)
                categories.append(category)

            self.session.commit()
        except IntegrityError as exc:
            self.session.rollback()
            raise ValidationError(
                "Salah satu nama kategori sudah digunakan."
            ) from exc
        except Exception:
            self.session.rollback()
            raise

        for category in categories:
            self.session.refresh(category)
        return categories

    def ensure_default_unit(self, actor: User) -> Unit:
        """Kembalikan satuan aktif pertama; buat 'Pcs' bila belum ada."""
        self._require_owner(actor)
        unit = self.session.scalar(
            select(Unit)
            .where(Unit.deleted_at.is_(None))
            .order_by(Unit.id)
            .limit(1)
        )
        if unit is not None:
            return unit
        unit = Unit(name="Pcs", symbol="pcs")
        self.session.add(unit)
        try:
            self.session.flush()
            self.session.refresh(unit)
        except IntegrityError as exc:
            self.session.rollback()
            raise ValidationError("Satuan sudah digunakan.") from exc
        return unit

    def save_product(
        self,
        actor: User,
        *,
        product_id: int | None,
        sku: str,
        barcode: str,
        name: str,
        category_id: int,
        unit_id: int,
        purchase_price: int,
        selling_price: int,
        stock_qty: int,
        min_stock: int,
        is_active: bool,
        supplier_id: int | None = None,
    ) -> Product:
        self._require_owner(actor)
        normalized_sku = sku.strip()
        normalized_barcode = barcode.strip() or None
        normalized_name = name.strip()
        if not normalized_sku:
            raise ValidationError("SKU wajib diisi.")
        if len(normalized_sku) > 80:
            raise ValidationError("SKU maksimal 80 karakter.")
        if len(normalized_barcode or "") > 80:
            raise ValidationError("Barcode maksimal 80 karakter.")
        if not normalized_name:
            raise ValidationError("Nama produk wajib diisi.")
        if len(normalized_name) > 200:
            raise ValidationError("Nama produk maksimal 200 karakter.")
        if any(
            value < 0
            for value in (
                purchase_price,
                selling_price,
                stock_qty,
                min_stock,
            )
        ):
            raise ValidationError("Harga dan stok tidak boleh bernilai negatif.")

        category = self.session.get(Category, category_id)
        unit = self.session.get(Unit, unit_id)
        if category is None or category.deleted_at is not None:
            raise ValidationError("Pilih kategori produk yang masih aktif.")
        if unit is None or unit.deleted_at is not None:
            raise ValidationError("Pilih satuan produk yang masih aktif.")
        supplier = (
            self.session.get(Supplier, supplier_id)
            if supplier_id is not None
            else None
        )
        if supplier_id is not None and (
            supplier is None or supplier.deleted_at is not None
        ):
            raise ValidationError("Pilih supplier yang masih aktif.")

        product = (
            self.session.get(Product, product_id)
            if product_id is not None
            else Product()
        )
        if product is None or product.deleted_at is not None:
            raise ValidationError("Produk yang akan diubah tidak ditemukan.")

        duplicate_sku = self.session.scalar(
            select(Product.id).where(
                func.lower(Product.sku) == normalized_sku.casefold(),
                Product.id != (product_id or -1),
            )
        )
        if duplicate_sku is not None:
            raise ValidationError("SKU sudah digunakan produk lain.")
        if normalized_barcode:
            duplicate_barcode = self.session.scalar(
                select(Product.id).where(
                    Product.barcode == normalized_barcode,
                    Product.id != (product_id or -1),
                )
            )
            if duplicate_barcode is not None:
                raise ValidationError("Barcode sudah digunakan produk lain.")

        is_new = product_id is None
        product.sku = normalized_sku
        product.barcode = normalized_barcode
        product.name = normalized_name
        product.category_id = category.id
        product.unit_id = unit.id
        product.supplier_id = supplier.id if supplier else None
        product.purchase_price = purchase_price
        product.selling_price = selling_price
        product.min_stock = min_stock
        product.is_active = is_active
        if is_new:
            product.stock_qty = stock_qty
            self.session.add(product)

        try:
            self.session.flush()
            if is_new and stock_qty > 0:
                self.session.add(
                    StockMovement(
                        product_id=product.id,
                        movement_type="INITIAL_STOCK",
                        stock_before=0,
                        qty=stock_qty,
                        stock_after=stock_qty,
                        reference_type="PRODUCT",
                        reference_id=product.id,
                        note="Stok awal saat membuat produk.",
                    )
                )
            self.session.commit()
            self.session.refresh(product)
        except IntegrityError as exc:
            self.session.rollback()
            raise ValidationError(
                "SKU atau barcode sudah digunakan oleh produk lain."
            ) from exc
        return product

    def delete_product(self, actor: User, product_id: int) -> None:
        self._require_owner(actor)
        product = self.session.get(Product, product_id)
        if product is None or product.deleted_at is not None:
            raise ValidationError("Produk yang akan dihapus tidak ditemukan.")

        product.deleted_at = datetime.now(timezone.utc)
        product.is_active = False
        try:
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise

    def add_stock(self, actor: User, product_id: int, quantity: int) -> Product:
        self._require_owner(actor)
        if quantity <= 0:
            raise ValidationError("Jumlah stok tambahan harus lebih dari 0.")

        product = self.session.get(Product, product_id)
        if product is None or product.deleted_at is not None:
            raise ValidationError("Produk yang akan ditambah stoknya tidak ditemukan.")

        stock_before = product.stock_qty
        stock_after = stock_before + quantity
        if stock_after > 2_000_000_000:
            raise ValidationError("Jumlah stok melebihi batas maksimum.")

        product.stock_qty = stock_after
        self.session.add(
            StockMovement(
                product_id=product.id,
                movement_type="STOCK_ADDITION",
                stock_before=stock_before,
                qty=quantity,
                stock_after=stock_after,
                reference_type="MANUAL",
                note="Penambahan stok manual dari Master Data.",
            )
        )
        try:
            self.session.commit()
            self.session.refresh(product)
        except Exception:
            self.session.rollback()
            raise
        return product

    @staticmethod
    def _require_owner(actor: User):
        if actor.role.name.upper() != "OWNER":
            raise AuthorizationError("Hanya OWNER yang dapat mengelola master data.")
