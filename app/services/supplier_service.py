from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import AuthorizationError, ValidationError
from app.models import Supplier, User


class SupplierService:
    def __init__(self, session: Session):
        self.session = session

    def list_suppliers(self, actor: User) -> list[Supplier]:
        self._require_owner(actor)
        return list(
            self.session.scalars(
                select(Supplier)
                .where(Supplier.deleted_at.is_(None))
                .order_by(Supplier.name, Supplier.code)
            )
        )

    def save_supplier(
        self,
        actor: User,
        *,
        supplier_id: int | None,
        code: str,
        name: str,
        phone: str,
        address: str,
    ) -> Supplier:
        self._require_owner(actor)
        normalized_code = code.strip()
        normalized_name = name.strip()
        normalized_phone = phone.strip() or None
        normalized_address = address.strip() or None
        if not normalized_code:
            raise ValidationError("Kode supplier wajib diisi.")
        if len(normalized_code) > 30:
            raise ValidationError("Kode supplier maksimal 30 karakter.")
        if not normalized_name:
            raise ValidationError("Nama supplier wajib diisi.")
        if len(normalized_name) > 150:
            raise ValidationError("Nama supplier maksimal 150 karakter.")
        if len(normalized_phone or "") > 30:
            raise ValidationError("Nomor telepon maksimal 30 karakter.")
        if len(normalized_address or "") > 2000:
            raise ValidationError("Alamat supplier maksimal 2.000 karakter.")

        supplier = (
            self.session.get(Supplier, supplier_id)
            if supplier_id is not None
            else Supplier()
        )
        if supplier is None:
            raise ValidationError("Supplier yang akan diubah tidak ditemukan.")
        if supplier.deleted_at is not None:
            raise ValidationError("Supplier yang akan diubah sudah tidak aktif.")

        duplicate_code = self.session.scalar(
            select(Supplier.id).where(
                func.lower(Supplier.code) == normalized_code.casefold(),
                Supplier.id != (supplier_id or -1),
            )
        )
        if duplicate_code is not None:
            raise ValidationError("Kode supplier sudah digunakan.")

        supplier.code = normalized_code
        supplier.name = normalized_name
        supplier.phone = normalized_phone
        supplier.address = normalized_address
        if supplier_id is None:
            self.session.add(supplier)
        try:
            self.session.commit()
            self.session.refresh(supplier)
        except IntegrityError as exc:
            self.session.rollback()
            raise ValidationError("Kode supplier sudah digunakan.") from exc
        return supplier

    def delete_supplier(self, actor: User, supplier_id: int) -> None:
        self._require_owner(actor)
        supplier = self.session.get(Supplier, supplier_id)
        if supplier is None or supplier.deleted_at is not None:
            raise ValidationError("Supplier yang akan dihapus tidak ditemukan.")

        supplier.deleted_at = datetime.now(timezone.utc)
        try:
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise

    @staticmethod
    def _require_owner(actor: User):
        if actor.role.name.upper() != "OWNER":
            raise AuthorizationError(
                "Hanya OWNER yang dapat mengelola data supplier."
            )
