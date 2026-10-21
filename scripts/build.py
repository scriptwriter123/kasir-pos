import argparse
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the POS application.")
    parser.add_argument(
        "--debug-console",
        action="store_true",
        help="Build with a console window for application debug logs.",
    )
    options = parser.parse_args()

    migrations = PROJECT_ROOT / "migrations"
    alembic_config = PROJECT_ROOT / "alembic.ini"
    if not migrations.is_dir() or not alembic_config.is_file():
        raise FileNotFoundError("File migrasi database tidak ditemukan.")
    public_key = PROJECT_ROOT / "app" / "core" / "license_public_key.pem"
    if not public_key.is_file():
        raise SystemExit(
            "Kunci publik lisensi belum dibuat. Jalankan perintah berikut "
            "dengan passphrase minimal 12 karakter:\n"
            "  .\\venv\\Scripts\\python.exe "
            "scripts\\build_license_publisher.py --generate-key"
        )

    arguments = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--console" if options.debug_console else "--windowed",
        "--onedir",
        "--exclude-module",
        "anyio",
        "--hidden-import",
        "logging.config",
        "--name",
        "POS",
        "--distpath",
        str(PROJECT_ROOT / "dist"),
        "--workpath",
        str(PROJECT_ROOT / "build" / "pyinstaller"),
        "--specpath",
        str(PROJECT_ROOT / "build"),
        "--add-data",
        f"{alembic_config};.",
        "--add-data",
        f"{migrations};migrations",
        "--add-data",
        f"{public_key};app\\core",
        str(PROJECT_ROOT / "main.py"),
    ]
    subprocess.run(arguments, cwd=PROJECT_ROOT, check=True)
    print(f"Build selesai: {PROJECT_ROOT / 'dist' / 'POS' / 'POS.exe'}")
    print("Database runtime dibuat terpisah di %LOCALAPPDATA%\\POSApp\\data.")


if __name__ == "__main__":
    main()
