import pytest
from PySide6.QtWidgets import QApplication
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.core.exceptions import ValidationError
from app.core.security import verify_password
from app.models import Category, Product, Role, Store, User
from app.repositories.user_repository import UserRepository
from app.services.owner_setup_service import OwnerSetupService
from app.ui.views.login_view import LoginView


@pytest.fixture
def owner_setup_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as session:
            yield session
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_first_run_creates_owner_and_required_roles_without_demo_data(
    owner_setup_session,
):
    session = owner_setup_session
    service = OwnerSetupService(session, UserRepository(session))

    assert service.setup_required()
    owner = service.create_owner(
        username="  pemilik  ",
        full_name="  Pemilik Toko  ",
        password="password-rahasia",
    )

    assert owner.username == "pemilik"
    assert owner.full_name == "Pemilik Toko"
    assert owner.role.name == "OWNER"
    assert verify_password("password-rahasia", owner.password_hash)
    assert set(session.scalars(select(Role.name))) == set(
        OwnerSetupService.INITIAL_ROLES
    )
    assert session.scalars(select(Product)).all() == []
    assert session.scalars(select(Category)).all() == []
    assert session.scalars(select(Store)).all() == []
    assert not service.setup_required()

    with pytest.raises(ValidationError, match="sudah pernah dibuat"):
        service.create_owner(
            username="owner-lain",
            full_name="Pemilik Lain",
            password="password-rahasia",
        )


def test_first_run_validates_owner_inputs(owner_setup_session):
    session = owner_setup_session
    service = OwnerSetupService(session, UserRepository(session))

    with pytest.raises(ValidationError, match="Username wajib"):
        service.create_owner(username=" ", full_name="Owner", password="password123")
    with pytest.raises(ValidationError, match="minimal 8 karakter"):
        service.create_owner(username="owner", full_name="Owner", password="short")
    assert session.scalars(select(User)).all() == []


def test_login_view_shows_owner_setup_for_an_empty_database(owner_setup_session):
    session = owner_setup_session
    service = OwnerSetupService(session, UserRepository(session))
    qt_app = QApplication.instance() or QApplication([])

    view = LoginView(auth_service=None, setup_service=service)

    assert view.setup_panel.isVisibleTo(view)
    assert view.login_panel.isHidden()
    view.close()
