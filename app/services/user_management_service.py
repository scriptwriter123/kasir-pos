from datetime import datetime, timezone
import re
import secrets
import string

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import AuthorizationError, ValidationError
from app.core.security import hash_password
from app.models import Role, User
from app.repositories.user_repository import UserRepository


class UserManagementService:
    MAX_ROLE_LENGTH = 50
    MIN_PASSWORD_LENGTH = 8

    def __init__(self, session: Session, users: UserRepository):
        self.session = session
        self.users = users

    def list_users(self, actor: User) -> list[User]:
        self._require_owner(actor)
        return self.users.list_active()

    def create_user(
        self,
        actor: User,
        *,
        username: str,
        full_name: str,
        password: str,
        role_name: str,
        whatsapp: str = "",
    ) -> User:
        self._require_owner(actor)

        username = username.strip()
        full_name = full_name.strip()
        role_name = role_name.strip()
        whatsapp = self._normalize_whatsapp(whatsapp)

        if not username:
            raise ValidationError("Username wajib diisi.")
        if len(username) > 80:
            raise ValidationError("Username maksimal 80 karakter.")
        if not full_name:
            raise ValidationError("Nama lengkap wajib diisi.")
        if len(full_name) > 150:
            raise ValidationError("Nama lengkap maksimal 150 karakter.")
        if len(password) < self.MIN_PASSWORD_LENGTH:
            raise ValidationError(
                f"Password minimal {self.MIN_PASSWORD_LENGTH} karakter."
            )
        if not role_name:
            raise ValidationError("Jabatan wajib diisi.")
        if len(role_name) > self.MAX_ROLE_LENGTH:
            raise ValidationError(
                f"Jabatan maksimal {self.MAX_ROLE_LENGTH} karakter."
            )
        if role_name.upper() == "OWNER":
            raise ValidationError("Role yang dapat dibuat tidak valid.")
        if self.users.username_exists(username):
            raise ValidationError("Username sudah digunakan.")

        role = self._get_or_create_role(role_name)

        user = User(
            username=username,
            full_name=full_name,
            whatsapp=whatsapp,
            password_hash=hash_password(password),
            role=role,
        )
        self.session.add(user)
        try:
            self.session.commit()
        except IntegrityError as exc:
            self.session.rollback()
            raise ValidationError("Username sudah digunakan.") from exc
        self.session.refresh(user)
        return user

    def update_user(
        self,
        actor: User,
        user_id: int,
        *,
        username: str,
        full_name: str,
        role_name: str,
        whatsapp: str | None = None,
    ) -> User:
        self._require_owner(actor)
        user = self.session.get(User, user_id)
        if user is None or user.deleted_at is not None:
            raise ValidationError("Pengguna tidak ditemukan.")

        username = username.strip()
        full_name = full_name.strip()
        role_name = role_name.strip()

        if not username:
            raise ValidationError("Username wajib diisi.")
        if len(username) > 80:
            raise ValidationError("Username maksimal 80 karakter.")
        if not full_name:
            raise ValidationError("Nama lengkap wajib diisi.")
        if len(full_name) > 150:
            raise ValidationError("Nama lengkap maksimal 150 karakter.")
        username_taken = self.session.scalar(
            select(User.id).where(User.username == username, User.id != user_id)
        )
        if username_taken is not None:
            raise ValidationError("Username sudah digunakan.")

        # Jabatan akun OWNER tidak dapat diubah agar hak akses
        # tetap terjaga; hanya username dan nama lengkap yang boleh edit.
        if user.role.name.upper() != "OWNER":
            if not role_name:
                raise ValidationError("Jabatan wajib diisi.")
            if len(role_name) > self.MAX_ROLE_LENGTH:
                raise ValidationError(
                    f"Jabatan maksimal {self.MAX_ROLE_LENGTH} karakter."
                )
            if role_name.upper() == "OWNER":
                raise ValidationError("Role yang dapat dibuat tidak valid.")
            user.role = self._get_or_create_role(role_name)

        user.username = username
        user.full_name = full_name
        if whatsapp is not None:
            user.whatsapp = self._normalize_whatsapp(whatsapp)
        try:
            self.session.commit()
        except IntegrityError as exc:
            self.session.rollback()
            raise ValidationError("Username sudah digunakan.") from exc
        self.session.refresh(user)
        return user

    def delete_user(self, actor: User, user_id: int) -> None:
        self._require_owner(actor)
        user = self.session.get(User, user_id)
        if user is None or user.deleted_at is not None:
            raise ValidationError("Pengguna yang akan dihapus tidak ditemukan.")
        if user.id == actor.id or user.role.name.upper() == "OWNER":
            raise ValidationError("Akun OWNER tidak dapat dihapus.")

        user.deleted_at = datetime.now(timezone.utc)
        user.is_active = False
        try:
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise

    def reset_password(self, actor: User, user_id: int) -> str:
        """Reset password karyawan yang lupa. Owner dapat mereset dan
        memberikan password sementara baru kepada karyawan.

        Mengembalikan password sementara (plain text) yang harus
        diberikan langsung ke karyawan. Setelah reset, karyawan wajib
        mengganti password pada login berikutnya.
        """
        self._require_owner(actor)
        user = self.session.get(User, user_id)
        if user is None or user.deleted_at is not None:
            raise ValidationError("Pengguna tidak ditemukan.")
        if user.role.name.upper() == "OWNER":
            raise ValidationError("Akun OWNER tidak dapat direset passwordnya.")

        # Generate password sementara acak 12 karakter
        alphabet = string.ascii_letters + string.digits
        new_password = "".join(secrets.choice(alphabet) for _ in range(12))

        user.password_hash = hash_password(new_password)
        user.must_change_password = True
        user.failed_login_count = 0
        user.locked_until = None
        try:
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise
        # Expire semua objek di session agar query berikutnya (mis. login)
        # selalu ambil data terbaru dari database, bukan dari identity map
        # yang mungkin masih bernilai lama karena expire_on_commit=False.
        self.session.expire_all()
        self.session.refresh(user)
        return new_password

    def _get_or_create_role(self, role_name: str) -> Role:
        role = self.session.scalar(
            select(Role).where(func.lower(Role.name) == role_name.lower())
        )
        if role is None:
            role = Role(name=role_name, description=f"Bagian {role_name}")
            self.session.add(role)
            try:
                self.session.flush()
            except IntegrityError as exc:
                self.session.rollback()
                raise ValidationError(
                    "Jabatan sudah digunakan oleh pengguna lain."
                ) from exc
        return role

    @staticmethod
    def _normalize_whatsapp(value: str | None) -> str | None:
        """Validasi No. WA (aturan sama dengan Nomor WhatsApp toko)."""
        normalized = (value or "").strip()
        if not normalized:
            return None
        if not re.fullmatch(r"\+?[0-9\s()\-]+", normalized):
            raise ValidationError(
                "No. WA hanya boleh berisi angka dan +()-."
            )
        digit_count = sum(character.isdigit() for character in normalized)
        if not 7 <= digit_count <= 20:
            raise ValidationError("No. WA harus berisi 7 sampai 20 digit.")
        if len(normalized) > 30:
            raise ValidationError("No. WA maksimal 30 karakter.")
        return normalized

    @staticmethod
    def _require_owner(actor: User) -> None:
        if actor.role.name.upper() != "OWNER":
            raise AuthorizationError(
                "Hanya OWNER yang dapat mengelola akun pengguna."
            )
