import sys
import time

from pywinauto import Application

pid = int(sys.argv[1]) if len(sys.argv) > 1 else 15516
app = Application(backend="uia").connect(process=pid, timeout=10)
win = app.top_window()
win.set_focus()
time.sleep(0.5)
print("window:", win.window_text())
print("wrapper type:", type(win).__name__)
try:
    win.print_control_identifiers(depth=8)
except Exception as exc:
    print("print_control_identifiers failed:", exc)
    # manual dump
    def dump(el, depth=0, max_depth=6):
        if depth > max_depth:
            return
        try:
            info = el.element_info
            print(
                "  " * depth
                + f"ctl_type={info.control_type!r} name={info.name!r} "
                f"auto_id={info.automation_id!r} class={info.class_name!r}"
            )
        except Exception as e:
            print("  " * depth + f"ERR {e}")
            return
        try:
            kids = el.children()
        except Exception:
            kids = []
        for k in kids:
            dump(k, depth + 1, max_depth)

    dump(win)
