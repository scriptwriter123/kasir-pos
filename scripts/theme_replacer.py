import re
from pathlib import Path

PALETTE = {
    "window": "#121214",
    "panel": "#1a1a1e",
    "panel_alt": "#222226",
    "panel_hover": "#2a2a30",
    "panel_row": "#1e1e24",
    "text": "#ffffff",
    "text_soft": "#e4e4e7",
    "text_muted": "#a1a1aa",
    "text_disabled": "#71717a",
    "accent": "#007acc",
    "accent_hover": "#0098ff",
    "accent_pressed": "#005995",
    "accent_soft": "#89b4fa",
    "border": "#2d2d34",
    "border_hover": "#3f3f4a",
    "danger": "#dc2626",
    "danger_hover": "#ef4444",
    "success": "#16a34a",
    "success_hover": "#15803d",
    "warning": "#facc15",
}

# Map based on CSS property context
COLOR_MAP = {
    "#1d4ed8": PALETTE["accent_soft"],
    "#2563eb": PALETTE["accent_soft"],
    "#3b82f6": PALETTE["accent_soft"],
    "#1e3a8a": "#93c5fd",
    "#172554": PALETTE["text"],
    "#0f172a": PALETTE["text"],
    "#334155": PALETTE["text_soft"],
    "#475569": PALETTE["text_soft"],
    "#64748b": PALETTE["text_muted"],
    "#9a3412": "#fdba74",
    "#166534": "#86efac",
}

BG_MAP = {
    "#1d4ed8": PALETTE["accent"],
    "#1e40af": PALETTE["accent_hover"],
    "#1e3a8a": PALETTE["accent_pressed"],
    "#dc2626": PALETTE["danger"],
    "#b91c1c": PALETTE["danger_hover"],
    "#15803d": PALETTE["success"],
    "#166534": PALETTE["success_hover"],
    "#facc15": PALETTE["warning"],
    "#f1f5f9": PALETTE["panel_alt"],
    "#f8fafc": PALETTE["panel"],
    "#eff6ff": "#12263a",
    "#dbeafe": "#0e2f4a",
    "#fff7ed": "#3a2410",
    "#f0fdf4": "#12291b",
    "#e2e8f0": PALETTE["border"],
}

BORDER_MAP = {
    "#e2e8f0": PALETTE["border"],
    "#94a3b8": PALETTE["border_hover"],
}

def replace_in_line(line: str) -> str:
    # Replace background: / background-color:
    def bg_repl(m):
        prefix, color = m.group(1), m.group(2).lower()
        new = BG_MAP.get(color, color)
        return f"{prefix}{new}"
    line = re.sub(
        r"((?:background|background-color)\s*:\s*)(#[0-9a-fA-F]{6}|white)",
        bg_repl,
        line,
    )

    # Replace color: (not background-color)
    def color_repl(m):
        prefix, color = m.group(1), m.group(2).lower()
        new = COLOR_MAP.get(color, color)
        return f"{prefix}{new}"
    line = re.sub(
        r"(?<!background-)(color\s*:\s*)(#[0-9a-fA-F]{6})",
        color_repl,
        line,
    )

    # Replace border colors
    def border_repl(m):
        prefix, color = m.group(1), m.group(2).lower()
        new = BORDER_MAP.get(color, color)
        return f"{prefix}{new}"
    line = re.sub(
        r"((?:border(?:-[a-z]+)?\s*(?:\d+px\s*)?(?:solid|dashed|dotted)\s*))(#[0-9a-fA-F]{6})",
        border_repl,
        line,
    )

    return line

base = Path("app/ui")
for py in base.rglob("*.py"):
    if py.name == "theme.py":
        continue
    text = py.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    new_lines = [replace_in_line(l) for l in lines]
    new_text = "".join(new_lines)
    if new_text != text:
        py.write_text(new_text, encoding="utf-8")
        print(f"Updated {py}")
