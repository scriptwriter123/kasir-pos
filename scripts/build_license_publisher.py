import argparse
import getpass
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.services.license_service import (
    PRIVATE_KEY_PATH,
    PUBLIC_KEY_PATH,
    LicenseError,
    generate_license_keypair,
)

OUTPUT_DIR = PROJECT_ROOT / "build" / "license-publisher"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build the separate offline POS license publisher."
    )
    parser.add_argument(
        "--generate-key",
        action="store_true",
        help="Create the publisher keypair once before building the tool.",
    )
    options = parser.parse_args()

    if options.generate_key:
        while True:
            passphrase = getpass.getpass(
                "Buat kata sandi kunci privat (minimal 12 karakter): "
            )
            if len(passphrase) < 12:
                print(
                    f"Kata sandi baru {len(passphrase)} karakter; "
                    "masukkan minimal 12 karakter."
                )
                continue
            confirmation = getpass.getpass("Ulangi kata sandi kunci privat: ")
            if passphrase == confirmation:
                break
            print("Kata sandi tidak cocok. Silakan ulangi.")
        try:
            generate_license_keypair(
                PRIVATE_KEY_PATH,
                PUBLIC_KEY_PATH,
                passphrase,
            )
        except LicenseError as exc:
            raise SystemExit(str(exc)) from exc
        print(f"Kunci privat tersimpan di luar proyek: {PRIVATE_KEY_PATH}")
        print(f"Kunci publik untuk aplikasi POS: {PUBLIC_KEY_PATH}")
        print(
            "Simpan cadangan kunci privat dengan aman. Jangan kirim atau "
            "masukkan kunci privat ke installer POS."
        )
        return

    if not PRIVATE_KEY_PATH.is_file() or not PUBLIC_KEY_PATH.is_file():
        raise SystemExit(
            "Kunci penerbit belum dibuat. Jalankan perintah berikut, lalu "
            "masukkan kata sandi minimal 12 karakter:\n"
            "  .\\venv\\Scripts\\python.exe "
            "scripts\\build_license_publisher.py --generate-key"
        )

    script = PROJECT_ROOT / "scripts" / "license_publisher.py"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "--onefile",
            "--windowed",
            "--name",
            "AnjayLicensePublisher",
            "--distpath",
            str(OUTPUT_DIR),
            "--workpath",
            str(PROJECT_ROOT / "build" / "pyinstaller-license-publisher"),
            "--specpath",
            str(PROJECT_ROOT / "build" / "license-publisher-spec"),
            "--paths",
            str(PROJECT_ROOT),
            str(script),
        ],
        cwd=PROJECT_ROOT,
        check=True,
    )
    print(f"Tool penerbit lisensi: {OUTPUT_DIR / 'AnjayLicensePublisher.exe'}")
    print("Tool ini tidak disertakan dalam installer POS.")


if __name__ == "__main__":
    main()
