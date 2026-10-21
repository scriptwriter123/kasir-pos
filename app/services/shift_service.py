from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import ValidationError
from app.models import Shift, Store, User
from app.repositories.shift_repository import ShiftRepository


class ShiftService:
    def __init__(self, session: Session, shifts: ShiftRepository):
        self.session = session
        self.shifts = shifts

    def get_open_shift(self, user: User) -> Shift | None:
        return self.shifts.get_open_for_cashier(user.id)

    def open_shift(self, user: User, opening_cash: int) -> Shift:
        if opening_cash < 0:
            raise ValidationError("Modal awal tidak boleh negatif.")
        if self.get_open_shift(user) is not None:
            raise ValidationError("Shift pengguna ini sudah terbuka.")

        store = self.session.scalar(
            select(Store)
            .where(Store.deleted_at.is_(None))
            .order_by(Store.id)
        )
        if store is None:
            raise ValidationError("Data toko belum tersedia. Jalankan scripts\\seed.py.")

        try:
            shift = self.shifts.create_for_user(user, store, opening_cash)
            self.session.commit()
            self.session.refresh(shift)
            return shift
        except Exception:
            self.session.rollback()
            raise
