from sqlalchemy import select

from app.models import Sale, SaleItem
from app.repositories.base import BaseRepository


class SaleRepository(BaseRepository[Sale]):
    model = Sale

    def get_by_invoice_no(self, invoice_no: str) -> Sale | None:
        return self.session.scalar(
            select(Sale).where(Sale.invoice_no == invoice_no)
        )

    def list_for_cashier(
        self, cashier_id: int, limit: int = 100, offset: int = 0
    ) -> list[Sale]:
        statement = (
            select(Sale)
            .where(Sale.cashier_id == cashier_id)
            .order_by(Sale.created_at.desc(), Sale.id.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(self.session.scalars(statement))

    def list_items(self, sale_id: int) -> list[SaleItem]:
        statement = (
            select(SaleItem)
            .where(SaleItem.sale_id == sale_id)
            .order_by(SaleItem.id)
        )
        return list(self.session.scalars(statement))
