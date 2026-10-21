from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.core.exceptions import AuthenticationError
from app.core.security import hash_password
from app.models import Role, User
from app.repositories.user_repository import UserRepository
from app.services.auth_service import AuthService


@pytest.fixture
def auth_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as session:
            role = Role(name="CASHIER")
            session.add(role)
            session.flush()
            user = User(
                username="kasir1",
                full_name="Kasir Satu",
                password_hash=hash_password("password123"),
                role_id=role.id,
            )
            session.add(user)
            session.commit()
            yield session
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_auth_service_successful_login(auth_session: Session):
    repo = UserRepository(auth_session)
    service = AuthService(repo)

    user = service.login("kasir1", "password123")
    assert user.username == "kasir1"
    assert user.failed_login_count == 0
    assert user.last_login_at is not None
    assert user.locked_until is None


def test_auth_service_wrong_password_increments_failed_count(auth_session: Session):
    repo = UserRepository(auth_session)
    service = AuthService(repo)

    with pytest.raises(AuthenticationError, match="Username atau password salah"):
        service.login("kasir1", "wrong_password")

    user = repo.get_by_username("kasir1")
    assert user.failed_login_count == 1
    assert user.locked_until is None


def test_auth_service_locks_account_after_max_failed_attempts(auth_session: Session):
    repo = UserRepository(auth_session)
    service = AuthService(repo)

    for _ in range(service.MAX_FAILED_ATTEMPTS):
        with pytest.raises(AuthenticationError, match="Username atau password salah"):
            service.login("kasir1", "wrong_password")

    user = repo.get_by_username("kasir1")
    assert user.failed_login_count == service.MAX_FAILED_ATTEMPTS
    assert user.locked_until is not None
    assert user.locked_until > datetime.now(timezone.utc)

    # Next attempt must raise "Akun sedang terkunci" even if password is correct
    with pytest.raises(AuthenticationError, match="Akun sedang terkunci"):
        service.login("kasir1", "password123")


def test_auth_service_inactive_user_cannot_login(auth_session: Session):
    repo = UserRepository(auth_session)
    user = repo.get_by_username("kasir1")
    user.is_active = False
    auth_session.commit()

    service = AuthService(repo)
    with pytest.raises(AuthenticationError, match="Username atau password salah"):
        service.login("kasir1", "password123")

