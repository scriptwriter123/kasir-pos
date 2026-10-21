import re
from pathlib import Path

files = [
    Path("app/ui/views/cashier_view.py"),
    Path("app/ui/views/dashboard_view.py"),
    Path("app/ui/views/user_management_view.py"),
    Path("app/ui/main_window.py"),
]
pat = re.compile(
    r'(?:QPushButton|QLabel|setWindowTitle|addAction|'
    r'QMessageBox\.(?:information|warning|question)|'
    r'setPlaceholderText|setText)\(\s*["\']([^"\']{2,90})["\']'
)
for p in files:
    if not p.exists():
        print(f"MISSING {p}")
        continue
    text = p.read_text(encoding="utf-8")
    print(f"=== {p} ===")
    seen = []
    for m in pat.finditer(text):
        t = m.group(1)
        if t not in seen:
            seen.append(t)
            print(" ", t)
