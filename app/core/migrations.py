import sys
import os
from pathlib import Path
from alembic import command
from alembic.config import Config

def upgrade_database() -> None:
    frozen = getattr(sys, 'frozen', False)
    if frozen:
        meipass = getattr(sys, '_MEIPASS', None)
        project_root = Path(meipass) if meipass is not None else Path('.')
        print(f'[MIGRATION DEBUG] frozen=True, _MEIPASS={meipass}, project_root={project_root}', file=sys.stderr)
    else:
        project_root = Path(__file__).resolve().parents[2]
        print(f'[MIGRATION DEBUG] frozen=False, project_root={project_root}', file=sys.stderr)
    
    config = project_root / 'alembic.ini'
    migrations_path = project_root / 'migrations'
    print(f'[MIGRATION DEBUG] config path: {config}, exists: {config.is_file()}', file=sys.stderr)
    print(f'[MIGRATION DEBUG] migrations path: {migrations_path}, exists: {migrations_path.is_dir()}', file=sys.stderr)
    
    if not config.is_file() or not migrations_path.is_dir():
        # Try to list what's in project_root
        try:
            contents = list(project_root.iterdir())
            print(f'[MIGRATION DEBUG] Contents of project_root: {[p.name for p in contents]}', file=sys.stderr)
        except Exception as e:
            print(f'[MIGRATION DEBUG] Could not list project_root: {e}', file=sys.stderr)
        raise FileNotFoundError(
            'File konfigurasi migrasi database tidak ditemukan.'
        )
    
    config_path = project_root / 'alembic.ini'
    print(f'[MIGRATION DEBUG] Creating Config from {config_path}', file=sys.stderr)
    config = Config(str(config_path))
    print(f'[MIGRATION DEBUG] Config created, calling upgrade...', file=sys.stderr)
    try:
        command.upgrade(config, 'head')
        print(f'[MIGRATION DEBUG] Upgrade completed successfully', file=sys.stderr)
    except Exception as e:
        print(f'[MIGRATION DEBUG] Error during upgrade: {e}', file=sys.stderr)
        raise
