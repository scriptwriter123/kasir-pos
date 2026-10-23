from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from server.app.models import AuthSession, Customer
from server.app.security import (
    hash_password,
    hash_token,
    new_session_token,
    verify_password,
)


class AuthError(ValueError):
    pass


def register_customer(
    session: Session,
    *,
    email: str,
    password: str,
    store_name: str = "",
    phone: str = "",
) -> Customer:
    normalized_email = email.strip().lower()
    if "@" not in normalized_email or normalized_email.startswith("@"):
        raise AuthError("Format email tidak valid.")
    if len(password) < 8:
        raise AuthError("Password minimal 8 karakter.")
    existing = session.scalar(
        select(Customer).where(Customer.email == normalized_email)
    )
    if existing is not None:
        raise AuthError("Email sudah terdaftar.")
    customer = Customer(
        email=normalized_email,
        password_hash=hash_password(password),
        store_name=store_name.strip()[:150],
        phone=phone.strip()[:30],
    )
    session.add(customer)
    session.commit()
    return customer


def login_customer(
    session: Session,
    *,
    email: str,
    password: str,
    ttl_days: int = 30,
) -> tuple[Customer, str]:
    normalized_email = email.strip().lower()
    customer = session.scalar(
        select(Customer).where(Customer.email == normalized_email)
    )
    if customer is None or not customer.is_active:
        raise AuthError("Email atau password salah.")
    if not verify_password(password, customer.password_hash):
        raise AuthError("Email atau password salah.")

    token = new_session_token()
    now = datetime.now(timezone.utc)
    session.add(
        AuthSession(
            token_hash=hash_token(token),
            customer_id=customer.id,
            expires_at=now + timedelta(days=ttl_days),
        )
    )
    session.commit()
    return customer, token


def customer_for_token(session: Session, token: str | None) -> Customer | None:
    if not token:
        return None
    record = session.scalar(
        select(AuthSession).where(AuthSession.token_hash == hash_token(token))
    )
    if record is None or record.revoked_at is not None:
        return None
    expires_at = record.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at <= datetime.now(timezone.utc):
        return None
    if not record.customer.is_active:
        return None
    return record.customer


def logout_token(session: Session, token: str | None) -> None:
    if not token:
        return
    record = session.scalar(
        select(AuthSession).where(AuthSession.token_hash == hash_token(token))
    )
    if record is not None and record.revoked_at is None:
        record.revoked_at = datetime.now(timezone.utc)
        session.commit()
