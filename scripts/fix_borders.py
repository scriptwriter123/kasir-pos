import re
from pathlib import Path

border_map = {"#e2e8f0": "#2d2d34", "#94a3b8": "#3f3f4a"}

for py in Path("app/ui").rglob("*.py"):
    if py.name == "theme.py":
        continue
    text = py.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    new_lines = []
    for line in lines:
        def border_repl(m):
            prop, color = m.group(1), m.group(2).lower()
            new = border_map.get(color, color)
            return f"{prop}{new}"
        line = re.sub(
            r"(border[a-zA-Z-]*\s*:\s*[^;]*?)(#[0-9a-fA-F]{6})",
            border_repl,
            line,
        )
        new_lines.append(line)
    new_text = "".join(new_lines)
    if new_text != text:
        py.write_text(new_text, encoding="utf-8")
        print(f"Fixed borders in {py}")
