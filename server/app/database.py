from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from server.app.config import Settings


class Base(DeclarativeBase):
    pass


def make_session_factory(settings: Settings) -> sessionmaker[Session]:
    prefix = "sqlite:///"
    if settings.database_url.startswith(prefix):
        raw = settings.database_url[len(prefix):]
        if raw and raw != ":memory:":
            Path(raw).parent.mkdir(parents=True, exist_ok=True)
    connect_args = (
        {"check_same_thread": False}
        if settings.database_url.startswith("sqlite")
        else {}
    )
    engine = create_engine(settings.database_url, connect_args=connect_args)
    return sessionmaker(bind=engine, expire_on_commit=False)


def init_db(session_factory: sessionmaker[Session]) -> None:
    from server.app import models  # noqa: F401

    Base.metadata.create_all(bind=session_factory.kw["bind"])
    _run_light_migrations(session_factory)


def _run_light_migrations(session_factory: sessionmaker[Session]) -> None:
    """Tambah kolom baru ke tabel yang sudah ada (server tidak pakai alembic)."""
    from sqlalchemy import inspect, text

    bind = session_factory.kw["bind"]
    inspector = inspect(bind)
    with bind.begin() as conn:
        if "devices" in inspector.get_table_names():
            columns = {col["name"] for col in inspector.get_columns("devices")}
            if "token_hash" not in columns:
                conn.execute(
                    text(
                        "ALTER TABLE devices ADD COLUMN token_hash VARCHAR(64)"
                    )
                )
                conn.execute(
                    text(
                        "CREATE UNIQUE INDEX IF NOT EXISTS ix_devices_token_hash "
                        "ON devices (token_hash)"
                    )
                )
        if "customers" in inspector.get_table_names():
            columns = {col["name"] for col in inspector.get_columns("customers")}
            if "is_admin" not in columns:
                conn.execute(
                    text(
                        "ALTER TABLE customers ADD COLUMN "
                        "is_admin BOOLEAN NOT NULL DEFAULT 0"
                    )
                )


def seed_admin(
    session_factory: sessionmaker[Session],
    *,
    email: str,
    password: str,
) -> None:
    """Buat akun admin dashboard jika belum ada.

    Aman dipanggil berulang: bila email sudah terdaftar, akun tersebut
    dipromosikan menjadi admin (tanpa mengubah password-nya).
    """
    from sqlalchemy import select

    from server.app.models import Customer
    from server.app.security import hash_password

    normalized = email.strip().lower()
    if "@" not in normalized or len(password) < 8:
        raise ValueError("Email admin tidak valid / password minimal 8 karakter.")
    with session_factory() as session:
        customer = session.scalar(
            select(Customer).where(Customer.email == normalized)
        )
        if customer is None:
            customer = Customer(
                email=normalized,
                password_hash=hash_password(password),
                store_name="Administrator",
                is_active=True,
                is_admin=True,
            )
            session.add(customer)
        else:
            customer.is_admin = True
            customer.is_active = True
        session.commit()


def seed_plans(session_factory: sessionmaker[Session]) -> None:
    from server.app.models import Plan

    with session_factory() as session:
        if session.query(Plan).count() > 0:
            return
        session.add_all(
            [
                Plan(code="monthly", name="Bulanan", duration_days=30, price_idr=99_000),
                Plan(code="yearly", name="Tahunan", duration_days=365, price_idr=990_000),
                Plan(code="lifetime", name="Selamanya", duration_days=None, price_idr=2_990_000),
            ]
        )
        session.commit()
