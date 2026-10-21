from sqlalchemy import or_, select

from app.models import Category, Product
from app.repositories.base import BaseRepository


class ProductRepository(BaseRepository[Product]):
    model = Product

    def find_by_barcode_or_sku(self, value: str):
        return self.session.scalar(
            select(Product).where(
                Product.deleted_at.is_(None),
                or_(Product.barcode == value, Product.sku == value),
            )
        )

    def search_active(self, query: str, limit: int = 50) -> list[Product]:
        statement = select(Product).where(
            Product.deleted_at.is_(None),
            Product.is_active.is_(True),
        )
        query = query.strip()
        if query:
            pattern = f"%{query}%"
            statement = statement.where(
                or_(
                    Product.name.ilike(pattern),
                    Product.sku.ilike(pattern),
                    Product.barcode.ilike(pattern),
                    Product.category_id.in_(
                        select(Category.id).where(
                            Category.deleted_at.is_(None),
                            Category.name.ilike(pattern),
                        )
                    ),
                )
            )
        statement = statement.order_by(Product.name, Product.sku).limit(limit)
        return list(self.session.scalars(statement))
