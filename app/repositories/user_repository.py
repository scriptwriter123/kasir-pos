from sqlalchemy import select

from app.models import User
from app.repositories.base import BaseRepository


class UserRepository(BaseRepository[User]):
    model = User

    def get_by_username(self, username: str):
        return self.session.scalar(
            select(User).where(
                User.username == username,
                User.deleted_at.is_(None),
            )
        )

    def list_active(self) -> list[User]:
        statement = (
            select(User)
            .where(User.deleted_at.is_(None))
            .order_by(User.full_name, User.username)
        )
        return list(self.session.scalars(statement))

    def username_exists(self, username: str) -> bool:
        statement = select(User.id).where(User.username == username)
        return self.session.scalar(statement) is not None
