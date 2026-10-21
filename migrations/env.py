import logging
import sys
from logging.config import fileConfig
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from alembic import context
from sqlalchemy import engine_from_config, event, pool

from app.core.config import settings
from app.core.database import set_sqlite_pragmas
from app.models import User

config = context.config
database_url = settings.database_url
config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))

_app_logging_configured = any(
    getattr(handler, "_pos_console_handler", False)
    for handler in logging.getLogger().handlers
)
if config.config_file_name and not _app_logging_configured:
    fileConfig(config.config_file_name)
elif _app_logging_configured:
    logging.getLogger("sqlalchemy").setLevel(logging.WARNING)

target_metadata = User.metadata


def run_migrations_offline():
    context.configure(
        url=database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    event.listen(connectable, "connect", set_sqlite_pragmas)
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            render_as_batch=True,
        )
        with context.begin_transaction():
            context.run_migrations()
        if connection.dialect.name == "sqlite":
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
            if not connection.exec_driver_sql("PRAGMA foreign_keys").scalar():
                raise RuntimeError("Could not re-enable SQLite foreign keys after migration")


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
