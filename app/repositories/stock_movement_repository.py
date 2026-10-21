from sqlalchemy import select

from app.models import StockMovement
from app.repositories.base import BaseRepository


class StockMovementRepository(BaseRepository[StockMovement]):
    model = StockMovement

    def list_for_product(
        self, product_id: int, limit: int = 100, offset: int = 0
    ) -> list[StockMovement]:
        statement = (
            select(StockMovement)
            .where(StockMovement.product_id == product_id)
            .order_by(StockMovement.created_at.desc(), StockMovement.id.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(self.session.scalars(statement))
