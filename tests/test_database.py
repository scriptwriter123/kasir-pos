from sqlalchemy import text
from app.core.database import engine


def test_sqlite_pragmas():
    with engine.connect() as conn:
        assert conn.execute(text("PRAGMA foreign_keys")).scalar() == 1
        assert conn.execute(text("PRAGMA busy_timeout")).scalar() == 5000
        assert conn.execute(text("PRAGMA journal_mode")).scalar().lower() == "wal"
