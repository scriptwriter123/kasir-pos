import argparse
from pathlib import Path

import segno


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_URL = (
    "https://github.com/scriptwriter123/aplikasi-POS/releases/latest/download/"
    "AnjayRetailSoft.exe"
)
DEFAULT_PNG = PROJECT_ROOT / "docs" / "qr-download.png"
DEFAULT_SVG = PROJECT_ROOT / "docs" / "qr-download.svg"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Membuat QR code untuk tautan unduhan installer POS."
    )
    parser.add_argument(
        "--url",
        default=DEFAULT_URL,
        help="URL yang dibuat menjadi QR (default: tautan rilis terbaru).",
    )
    parser.add_argument(
        "--png",
        default=str(DEFAULT_PNG),
        help=f"Path hasil PNG (default: {DEFAULT_PNG}).",
    )
    parser.add_argument(
        "--svg",
        default=str(DEFAULT_SVG),
        help=f"Path hasil SVG (default: {DEFAULT_SVG}).",
    )
    parser.add_argument(
        "--scale",
        type=int,
        default=12,
        help="Ukuran modul QR dalam piksel (default: 12).",
    )
    options = parser.parse_args()

    qr = segno.make(options.url, error="h")

    png_path = Path(options.png)
    svg_path = Path(options.svg)
    png_path.parent.mkdir(parents=True, exist_ok=True)
    svg_path.parent.mkdir(parents=True, exist_ok=True)

    qr.save(png_path, scale=options.scale, border=4)
    qr.save(svg_path, scale=options.scale, border=4)

    print(f"URL : {options.url}")
    print(f"PNG : {png_path} ({png_path.stat().st_size} bytes)")
    print(f"SVG : {svg_path} ({svg_path.stat().st_size} bytes)")
    print(f"Versi QR: {qr.version}, koreksi kesalahan: {qr.error}")


if __name__ == "__main__":
    main()
