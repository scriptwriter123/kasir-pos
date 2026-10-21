from typing import Generic, TypeVar
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import Base

T = TypeVar("T", bound=Base)


class BaseRepository(Generic[T]):
    model = None

    def __init__(self, session: Session):
        self.session = session

    def get(self, entity_id: int):
        return self.session.get(self.model, entity_id)

    def add(self, entity: T) -> T:
        self.session.add(entity)
        self.session.flush()
        return entity

    def list(self, limit=100, offset=0):
        stmt = select(self.model).offset(offset).limit(limit)
        return list(self.session.scalars(stmt))
