from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import AuthorizationError, ValidationError
from app.models import InventarisToko, User


class InventoryService:
    """CRUD inventaris toko: alat & peralatan yang tidak dijual. Hanya OWNER."""

    MAX_KODE_LENGTH = 50
    MAX_NAMA_LENGTH = 200
    MAX_SATUAN_LENGTH = 50
    MAX_LOKASI_LENGTH = 100
    MAX_KETERANGAN_LENGTH = 1000
    MAX_JUMLAH = 9_999_999
    MAX_HARGA = 2_000_000_000
    KONDISI_PILIHAN = ("Baik", "Rusak Ringan", "Rusak Berat")

    def __init__(self, session: Session):
        self.session = session

    def list_items(self, actor: User) -> list[InventarisToko]:
        self._require_owner(actor)
        statement = (
            select(InventarisToko)
            .where(InventarisToko.deleted_at.is_(None))
            .order_by(InventarisToko.nama_barang, InventarisToko.kode_inventaris)
        )
        return list(self.session.scalars(statement))

    def create_item(
        self,
        actor: User,
        *,
        kode_inventaris: str,
        nama_barang: str,
        jumlah: int = 0,
        satuan: str = "",
        tanggal_perolehan: date | str | None = None,
        harga_perolehan: int = 0,
        lokasi: str = "",
        kondisi: str = "Baik",
        keterangan: str = "",
    ) -> InventarisToko:
        self._require_owner(actor)
        data = self._validate(
            kode_inventaris=kode_inventaris,
            nama_barang=nama_barang,
            jumlah=jumlah,
            satuan=satuan,
            tanggal_perolehan=tanggal_perolehan,
            harga_perolehan=harga_perolehan,
            lokasi=lokasi,
            kondisi=kondisi,
            keterangan=keterangan,
        )
        item = InventarisToko(**data)
        self.session.add(item)
        try:
            self.session.commit()
        except IntegrityError as exc:
            self.session.rollback()
            raise ValidationError("Kode inventaris sudah digunakan.") from exc
        self.session.refresh(item)
        return item

    def update_item(
        self,
        actor: User,
        item_id: int,
        *,
        kode_inventaris: str,
        nama_barang: str,
        jumlah: int = 0,
        satuan: str = "",
        tanggal_perolehan: date | str | None = None,
        harga_perolehan: int = 0,
        lokasi: str = "",
        kondisi: str = "Baik",
        keterangan: str = "",
    ) -> InventarisToko:
        self._require_owner(actor)
        item = self.session.get(InventarisToko, item_id)
        if item is None or item.deleted_at is not None:
            raise ValidationError("Barang inventaris tidak ditemukan.")
        data = self._validate(
            kode_inventaris=kode_inventaris,
            nama_barang=nama_barang,
            jumlah=jumlah,
            satuan=satuan,
            tanggal_perolehan=tanggal_perolehan,
            harga_perolehan=harga_perolehan,
            lokasi=lokasi,
            kondisi=kondisi,
            keterangan=keterangan,
        )
        duplicate = self.session.scalar(
            select(InventarisToko.id).where(
                InventarisToko.kode_inventaris == data["kode_inventaris"],
                InventarisToko.id != item_id,
                InventarisToko.deleted_at.is_(None),
            )
        )
        if duplicate is not None:
            raise ValidationError("Kode inventaris sudah digunakan.")
        for field, value in data.items():
            setattr(item, field, value)
        try:
            self.session.commit()
        except IntegrityError as exc:
            self.session.rollback()
            raise ValidationError("Kode inventaris sudah digunakan.") from exc
        self.session.refresh(item)
        return item

    def delete_item(self, actor: User, item_id: int) -> None:
        self._require_owner(actor)
        item = self.session.get(InventarisToko, item_id)
        if item is None or item.deleted_at is not None:
            raise ValidationError("Barang inventaris tidak ditemukan.")
        item.deleted_at = datetime.now(timezone.utc)
        try:
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise

    def _validate(
        self,
        *,
        kode_inventaris: str,
        nama_barang: str,
        jumlah: int,
        satuan: str,
        tanggal_perolehan: date | str | None,
        harga_perolehan: int,
        lokasi: str,
        kondisi: str,
        keterangan: str,
    ) -> dict:
        kode_inventaris = (kode_inventaris or "").strip()
        nama_barang = (nama_barang or "").strip()
        satuan = (satuan or "").strip()
        lokasi = (lokasi or "").strip()
        kondisi = (kondisi or "").strip()
        keterangan = (keterangan or "").strip()

        if not kode_inventaris:
            raise ValidationError("Kode inventaris wajib diisi.")
        if len(kode_inventaris) > self.MAX_KODE_LENGTH:
            raise ValidationError(
                f"Kode inventaris maksimal {self.MAX_KODE_LENGTH} karakter."
            )
        if not nama_barang:
            raise ValidationError("Nama barang wajib diisi.")
        if len(nama_barang) > self.MAX_NAMA_LENGTH:
            raise ValidationError(
                f"Nama barang maksimal {self.MAX_NAMA_LENGTH} karakter."
            )
        if len(satuan) > self.MAX_SATUAN_LENGTH:
            raise ValidationError(
                f"Satuan maksimal {self.MAX_SATUAN_LENGTH} karakter."
            )
        if len(lokasi) > self.MAX_LOKASI_LENGTH:
            raise ValidationError(
                f"Lokasi maksimal {self.MAX_LOKASI_LENGTH} karakter."
            )
        if len(keterangan) > self.MAX_KETERANGAN_LENGTH:
            raise ValidationError(
                f"Keterangan maksimal {self.MAX_KETERANGAN_LENGTH} karakter."
            )
        jumlah = self._to_int(jumlah, "Jumlah")
        if jumlah < 0:
            raise ValidationError("Jumlah tidak boleh minus.")
        if jumlah > self.MAX_JUMLAH:
            raise ValidationError(f"Jumlah maksimal {self.MAX_JUMLAH}.")
        harga_perolehan = self._to_int(harga_perolehan, "Harga perolehan")
        if harga_perolehan < 0:
            raise ValidationError("Harga perolehan tidak boleh minus.")
        if harga_perolehan > self.MAX_HARGA:
            raise ValidationError(
                f"Harga perolehan maksimal Rp {self.MAX_HARGA:,}."
                .replace(",", ".")
            )
        if kondisi not in self.KONDISI_PILIHAN:
            raise ValidationError(
                "Kondisi harus Baik, Rusak Ringan, atau Rusak Berat."
            )
        tanggal_perolehan = self._to_date(tanggal_perolehan)
        if tanggal_perolehan is None:
            raise ValidationError("Tanggal perolehan wajib diisi.")

        return {
            "kode_inventaris": kode_inventaris,
            "nama_barang": nama_barang,
            "jumlah": jumlah,
            "satuan": satuan or None,
            "tanggal_perolehan": tanggal_perolehan,
            "harga_perolehan": harga_perolehan,
            "lokasi": lokasi or None,
            "kondisi": kondisi,
            "keterangan": keterangan or None,
        }

    @staticmethod
    def _to_int(value, label: str) -> int:
        try:
            return int(value)
        except (TypeError, ValueError) as exc:
            raise ValidationError(f"{label} harus berupa angka.") from exc

    @staticmethod
    def _to_date(value: date | str | None) -> date | None:
        if value is None or value == "":
            return None
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        try:
            return date.fromisoformat(str(value).strip())
        except ValueError as exc:
            raise ValidationError(
                "Tanggal perolehan tidak valid (format: YYYY-MM-DD)."
            ) from exc

    @staticmethod
    def _require_owner(actor: User) -> None:
        if actor.role.name.upper() != "OWNER":
            raise AuthorizationError(
                "Hanya OWNER yang dapat mengelola inventaris toko."
            )
