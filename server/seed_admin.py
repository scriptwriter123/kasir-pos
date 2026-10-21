"""Buat/promosi akun admin dashboard webserver.

Pakai:
    python -m server.seed_admin
    python -m server.seed_admin --email admin@pos.local --password rahasia123
    python -m server.seed_admin --reset-password   # setel ulang password admin

Tanpa argumen, memakai ADMIN_EMAIL / ADMIN_PASSWORD dari server/.env
(default: admin@pos.local / admin12345). Bila email sudah terdaftar
sebagai customer biasa, akun tersebut dipromosikan menjadi admin.
"""

from __future__ import annotations

import argparse
import getpass
import sys

from server.app.config import settings
from server.app.database import make_session_factory, seed_admin


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Buat akun admin webserver.")
    parser.add_argument("--email", default=None, help="Email admin")
    parser.add_argument("--password", default=None, help="Password admin (min. 8 karakter)")
    parser.add_argument(
        "--reset-password",
        action="store_true",
        help="Setel ulang password admin yang sudah ada.",
    )
    args = parser.parse_args(argv)

    email = (args.email or settings.admin_email).strip().lower()
    password = args.password or settings.admin_password
    if not password and sys.stdin.isatty():
        password = getpass.getpass(f"Password untuk {email} (min. 8 karakter): ")
    if not password:
        print("Password admin wajib diisi (argumen --password atau ADMIN_PASSWORD).")
        return 1

    session_factory = make_session_factory(settings)
    from server.app.database import init_db

    init_db(session_factory)

    if args.reset_password:
        from sqlalchemy import select

        from server.app.models import Customer
        from server.app.security import hash_password

        with session_factory() as session:
            customer = session.scalar(
                select(Customer).where(Customer.email == email)
            )
            if customer is None:
                print(f"Akun {email} belum ada; buat baru tanpa --reset-password.")
                return 1
            customer.password_hash = hash_password(password)
            customer.is_admin = True
            customer.is_active = True
            session.commit()
        print(f"Password admin {email} berhasil disetel ulang.")
        return 0

    seed_admin(session_factory, email=email, password=password)
    print(f"Akun admin siap: {email}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
