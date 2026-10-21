import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = PROJECT_ROOT / "build" / "owner-password-tool"


def main() -> None:
    script = PROJECT_ROOT / "scripts" / "owner_password_generator.py"
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
            "POS-Owner-Password-Generator",
            "--distpath",
            str(OUTPUT_DIR),
            "--workpath",
            str(PROJECT_ROOT / "build" / "pyinstaller-owner-password-tool"),
            "--specpath",
            str(PROJECT_ROOT / "build" / "owner-password-tool-spec"),
            str(script),
        ],
        cwd=PROJECT_ROOT,
        check=True,
    )
    print(
        "Tool selesai dibuat: "
        f"{OUTPUT_DIR / 'POS-Owner-Password-Generator.exe'}"
    )
    print("Executable ini terpisah dan tidak dimasukkan ke installer POS.")


if __name__ == "__main__":
    main()
