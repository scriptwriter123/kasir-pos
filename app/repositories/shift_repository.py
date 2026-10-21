from datetime import datetime, timezone

from sqlalchemy import select

from app.models import Shift, Store, User
from app.repositories.base import BaseRepository


class ShiftRepository(BaseRepository[Shift]):
    model = Shift

    def get_open_for_cashier(self, cashier_id: int) -> Shift | None:
        return self.session.scalar(
            select(Shift)
            .where(
                Shift.cashier_id == cashier_id,
                Shift.status == "OPEN",
                Shift.closed_at.is_(None),
            )
            .order_by(Shift.opened_at.desc(), Shift.id.desc())
        )

    def create_for_user(
        self,
        user: User,
        store: Store,
        opening_cash: int,
    ) -> Shift:
        shift = Shift(
            store_id=store.id,
            cashier_id=user.id,
            opened_at=datetime.now(timezone.utc),
            opening_cash=opening_cash,
            status="OPEN",
        )
        self.session.add(shift)
        self.session.flush()
        return shift
