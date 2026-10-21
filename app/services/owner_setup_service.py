from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import ValidationError
from app.core.security import hash_password
from app.models import Role, User
from app.repositories.user_repository import UserRepository


class OwnerSetupService:
    INITIAL_ROLES = ("OWNER", "ADMIN", "SUPERVISOR", "CASHIER")
    MIN_PASSWORD_LENGTH = 8

    def __init__(self, session: Session, users: UserRepository):
        self.session = session
        self.users = users

    def setup_required(self) -> bool:
        return self.session.scalar(select(User.id).limit(1)) is None

    def create_owner(
        self,
        *,
        username: str,
        full_name: str,
        password: str,
    ) -> User:
        username = username.strip()
        full_name = full_name.strip()

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
        if not self.setup_required():
            raise ValidationError("Akun OWNER sudah pernah dibuat.")
        if self.users.username_exists(username):
            raise ValidationError("Username sudah digunakan.")

        roles = {
            role.name: role
            for role in self.session.scalars(
                select(Role).where(Role.name.in_(self.INITIAL_ROLES))
            )
        }
        for role_name in self.INITIAL_ROLES:
            if role_name not in roles:
                role = Role(name=role_name, description=f"Role {role_name}")
                self.session.add(role)
                roles[role_name] = role
        self.session.flush()

        owner = User(
            username=username,
            full_name=full_name,
            password_hash=hash_password(password),
            role=roles["OWNER"],
        )
        self.session.add(owner)
        try:
            self.session.commit()
        except IntegrityError as exc:
            self.session.rollback()
            raise ValidationError(
                "Akun OWNER tidak dapat dibuat. Pastikan username belum digunakan."
            ) from exc
        self.session.refresh(owner)
        return owner
