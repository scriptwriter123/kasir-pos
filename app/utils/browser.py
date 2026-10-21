import webbrowser

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices


def open_external_url(url: str) -> bool:
    """Membuka URL di browser sistem default pengguna.

    Tidak pernah menampilkan kredensial ke aplikasi; hanya membuka halaman
    resmi penyedia. Aman dipanggil dari thread GUI.
    """
    if not url or not url.strip():
        return False
    target = url.strip()
    try:
        if QDesktopServices.openUrl(QUrl(target)):
            return True
    except Exception:
        pass
    try:
        return bool(webbrowser.open(target))
    except Exception:
        return False
