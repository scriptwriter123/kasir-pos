import re
import shutil
import uuid
from pathlib import Path

from PySide6.QtGui import QImageReader
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import AuthorizationError, ValidationError
from app.models import Store, User


class StoreSettingsService:
    MAX_LOGO_BYTES = 5 * 1024 * 1024

    def __init__(self, session: Session):
        self.session = session

    def get_store(self) -> Store | None:
        return self.session.scalar(
            select(Store)
            .where(Store.deleted_at.is_(None))
            .order_by(Store.id)
            .limit(1)
        )

    def save(
        self,
        actor: User,
        *,
        name: str,
        address: str,
        whatsapp: str,
        slogan: str = "",
        logo_source: str | None,
        remove_logo: bool = False,
    ) -> Store:
        self._require_owner(actor)
        normalized_name = name.strip()
        normalized_slogan = slogan.strip() or None
        normalized_address = address.strip() or None
        normalized_whatsapp = self._normalize_whatsapp(whatsapp)
        if not normalized_name:
            raise ValidationError("Nama toko wajib diisi.")
        if len(normalized_name) > 150:
            raise ValidationError("Nama toko maksimal 150 karakter.")
        if len(normalized_slogan or "") > 200:
            raise ValidationError("Slogan toko maksimal 200 karakter.")
        if len(normalized_address or "") > 2000:
            raise ValidationError("Alamat toko maksimal 2.000 karakter.")

        copied_logo: Path | None = None
        if logo_source:
            copied_logo = self._copy_logo(logo_source)

        store = self.get_store()
        is_new = store is None
        if store is None:
            store = Store(code="MAIN", name=normalized_name)

        store.name = normalized_name
        store.slogan = normalized_slogan
        store.address = normalized_address
        store.whatsapp = normalized_whatsapp
        if remove_logo:
            store.logo_path = None
        elif copied_logo is not None:
            store.logo_path = str(copied_logo)

        if is_new:
            self.session.add(store)
        try:
            self.session.commit()
            self.session.refresh(store)
        except IntegrityError as exc:
            self.session.rollback()
            if copied_logo is not None:
                copied_logo.unlink(missing_ok=True)
            raise ValidationError(
                "Pengaturan toko tidak dapat disimpan karena kode toko sudah digunakan."
            ) from exc
        except Exception:
            self.session.rollback()
            if copied_logo is not None:
                copied_logo.unlink(missing_ok=True)
            raise
        return store

    @classmethod
    def _normalize_whatsapp(cls, value: str) -> str | None:
        normalized = value.strip()
        if not normalized:
            return None
        if not re.fullmatch(r"\+?[0-9\s()\-]+", normalized):
            raise ValidationError("Nomor WhatsApp hanya boleh berisi angka dan +()-.")
        digit_count = sum(character.isdigit() for character in normalized)
        if not 7 <= digit_count <= 20:
            raise ValidationError(
                "Nomor WhatsApp harus berisi 7 sampai 20 digit."
            )
        return normalized

    @classmethod
    def _copy_logo(cls, source: str) -> Path:
        source_path = Path(source).expanduser()
        if not source_path.is_file():
            raise ValidationError("File logo tidak ditemukan.")
        if source_path.stat().st_size > cls.MAX_LOGO_BYTES:
            raise ValidationError("Ukuran file logo maksimal 5 MB.")

        reader = QImageReader(str(source_path))
        if not reader.canRead():
            raise ValidationError("File logo harus berupa gambar yang valid.")

        extension = source_path.suffix.lower()
        if extension not in {".png", ".jpg", ".jpeg", ".bmp", ".webp"}:
            extension = ".png" if reader.format().lower() == b"png" else ".jpg"
        logo_dir = settings.data_dir / "store-logo"
        logo_dir.mkdir(parents=True, exist_ok=True)
        destination = logo_dir / f"{uuid.uuid4().hex}{extension}"
        try:
            shutil.copy2(source_path, destination)
        except OSError as exc:
            raise ValidationError(f"Logo tidak dapat disalin: {exc}") from exc
        return destination

    @staticmethod
    def _require_owner(actor: User):
        if actor.role.name.upper() != "OWNER":
            raise AuthorizationError(
                "Hanya OWNER yang dapat mengubah pengaturan toko."
            )
