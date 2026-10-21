import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
APP_VERSION = "0.5.0"


def find_inno_setup_compiler() -> Path:
    configured_path = os.environ.get("ISCC")
    if configured_path:
        compiler = Path(configured_path)
        if compiler.is_file():
            return compiler
        raise FileNotFoundError(f"ISCC yang ditentukan tidak ditemukan: {compiler}")

    path_compiler = shutil.which("ISCC.exe")
    if path_compiler:
        return Path(path_compiler)

    install_roots = [
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")),
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")),
    ]
    for root in install_roots:
        for version in ("7", "6"):
            compiler = root / f"Inno Setup {version}" / "ISCC.exe"
            if compiler.is_file():
                return compiler

    raise FileNotFoundError(
        "Inno Setup tidak ditemukan. Instal Inno Setup 6/7 atau atur "
        "environment variable ISCC ke lokasi ISCC.exe."
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build POS Retail and package it as a Windows installer."
    )
    parser.add_argument(
        "--debug-console",
        action="store_true",
        help="Build the installed application with a console for debug logs.",
    )
    options = parser.parse_args()

    public_key = PROJECT_ROOT / "app" / "core" / "license_public_key.pem"
    if not public_key.is_file():
        raise SystemExit(
            "Kunci publik lisensi belum tersedia. Buat dahulu dengan "
            "passphrase minimal 12 karakter:\n"
            "  .\\venv\\Scripts\\python.exe "
            "scripts\\build_license_publisher.py --generate-key"
        )

    compiler = find_inno_setup_compiler()
    build_script = PROJECT_ROOT / "scripts" / "build.py"
    build_arguments = [sys.executable, str(build_script)]
    if options.debug_console:
        build_arguments.append("--debug-console")
    subprocess.run(build_arguments, cwd=PROJECT_ROOT, check=True)

    distribution = PROJECT_ROOT / "dist" / "POS"
    executable = distribution / "POS.exe"
    if not executable.is_file():
        raise FileNotFoundError(f"Hasil build aplikasi tidak ditemukan: {executable}")

    installer_script = PROJECT_ROOT / "scripts" / "installer.iss"
    output_dir = PROJECT_ROOT / "build" / "installer_v3"
    output_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            str(compiler),
            "/Qp",
            f"/DAppVersion={APP_VERSION}",
            f"/DSourceDir={distribution}",
            f"/DOutputDir={output_dir}",
            str(installer_script),
        ],
        cwd=PROJECT_ROOT,
        check=True,
    )
    installer = output_dir / "AnjayRetailSoft.exe"
    if not installer.is_file():
        raise FileNotFoundError(f"Hasil build installer tidak ditemukan: {installer}")
    print(f"Installer selesai: {installer}")
    print("Database pengguna tetap disimpan di %LOCALAPPDATA%\\POSApp\\data.")


if __name__ == "__main__":
    main()
