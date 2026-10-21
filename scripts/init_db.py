from pathlib import Path

from alembic import command
from alembic.config import Config


PROJECT_ROOT = Path(__file__).resolve().parent.parent
config = Config(str(PROJECT_ROOT / "alembic.ini"))
config.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
command.upgrade(config, "head")
print("Database berhasil dimigrasikan.")
