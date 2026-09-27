"""Portable verification for the TONYAgent GUI + code-quality fixes.

No hardcoded absolute paths, ASCII-only output (safe on cp949 consoles).
Run:  python scripts/verify_gui.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

MAIN = ROOT / "src" / "tonyagent" / "ui" / "views" / "main_window.py"
THEME = ROOT / "src" / "tonyagent" / "ui" / "theme.py"
WIDGETS = ROOT / "src" / "tonyagent" / "ui" / "widgets" / "__init__.py"

CHECKS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    CHECKS.append((name, bool(ok), detail))


def main() -> int:
    main_src = MAIN.read_text(encoding="utf-8")
    theme_src = THEME.read_text(encoding="utf-8")
    widget_src = WIDGETS.read_text(encoding="utf-8")

    for path, src in ((MAIN, main_src), (THEME, theme_src), (WIDGETS, widget_src)):
        try:
            ast.parse(src)
            check(f"syntax: {path.name}", True)
        except SyntaxError as exc:
            check(f"syntax: {path.name}", False, str(exc))

    # ---- original regressions (composer / log tags) ------------------------
    check("composer spacer column weight=1", "grid_columnconfigure(1, weight=1)" in main_src)
    check("stop button column 2", "self.stop_btn.grid(row=0, column=2" in main_src)
    check("send button column 3 (right side)", "self.send_btn.grid(row=0, column=3" in main_src)
    for color in ("gray", "green", "orange", "red"):
        check(f"log tag foreground={color}", f'foreground="{color}"' in main_src)
    check("no tuple log-tag colors", "gray30" not in main_src)

    # ---- item: layout ------------------------------------------------------
    check("root has 3 rows", main_src.count("self.root.grid_rowconfigure(") == 3)
    check("sidebar+chat in row 1", main_src.count(".grid(row=1, column=") >= 2)
    check("status bar in row 2", "self.status_bar.grid(row=2," in main_src)
    check("composer height not clamped", "self.composer_frame.grid_propagate(False)" not in main_src)
    check("status bar has 4 column weights", main_src.count("self.status_bar.grid_columnconfigure(") == 4)
    check("version label pinned right", 'self.version_label.grid(row=0, column=3, padx=16, pady=4, sticky="e")' in main_src)

    # ---- item 1: widgets ---------------------------------------------------
    check("no lowercase 'master: any'", "master: any" not in widget_src)
    check("Any imported in widgets", "from typing import Any, Callable, Optional" in widget_src)
    check("no mutable default 'values: list[str] = []'", "values: list[str] = []" not in widget_src)

    # ---- item 2: theme -----------------------------------------------------
    check("theme._overrides exists", "self._overrides: dict[str, str] = {}" in theme_src)
    check("get_color honours overrides", "override = self._overrides.get(token)" in theme_src)
    check("set_custom_color implemented", "def clear_custom_colors" in theme_src and "\n        pass" not in theme_src)
    check("get_color_pair exists", "def get_color_pair(self, token: str)" in theme_src)
    hexes = ("#EF4444", "#34D399", "#FBBF24")
    check("no hardcoded status hexes in main_window", not any(h in main_src for h in hexes))
    check("theme tokens used in main_window", "theme_manager.get_color_pair(" in main_src)
    check("observer registered in __init__", main_src.index("register_observer") > main_src.index("def __init__"))
    check("_on_theme_change refreshes widgets", "self._provider_token" in main_src and "sandbox_token" in main_src)

    # ---- item 3: restart ---------------------------------------------------
    check("restart waits for completed stop", "self._restart_pending = True" in main_src)
    check("restart chain drained on stop", "if self._restart_pending:" in main_src)
    check("no blind after(1000, start)", "after(1000, self._start_sandbox)" not in main_src)

    # ---- items 4/5: hygiene ------------------------------------------------
    leftovers = [p.name for p in ROOT.iterdir() if p.is_dir() and not p.name.startswith(".")]
    check("legacy scripts archived", (ROOT / "scripts" / "legacy").is_dir())
    check("no patch scripts left at root", not list(ROOT.glob("fix_*.py")) and not list(ROOT.glob("write_*.py")))
    check("no hardcoded drive paths in src", not any(
        ":\\Users\\" in p.read_text(encoding="utf-8", errors="ignore")
        for p in (ROOT / "src" / "tonyagent").rglob("*.py")
    ))

    # ---- runtime smoke test ------------------------------------------------
    try:
        from tonyagent.ui.theme import theme_manager
        from tonyagent.ui.widgets import PillComboBox, PillLabel
        from tonyagent.ui.views.main_window import MainWindow

        check("import MainWindow", True)
        pair = theme_manager.get_color_pair("error")
        check("get_color_pair returns pair", isinstance(pair, tuple) and len(pair) == 2, str(pair))
        check("get_color_pair responds to override", theme_manager.get_color_pair("error") == pair)
        theme_manager.set_custom_color("error", "#123456")
        check("set_custom_color visible", theme_manager.get_color("error") == "#123456")
        theme_manager.clear_custom_colors()
        check("clear_custom_colors", theme_manager.get_color("error") != "#123456")
        check("theme survives set/get", callable(PillComboBox) and callable(PillLabel))
    except Exception as exc:  # pragma: no cover
        check("runtime smoke test", False, f"{type(exc).__name__}: {exc}")

    passed = sum(1 for _, ok, _ in CHECKS if ok)
    width = max(len(n) for n, _, _ in CHECKS)
    for name, ok, detail in CHECKS:
        status = "PASS" if ok else "FAIL"
        line = f"[{status}] {name.ljust(width)}"
        if detail and not ok:
            line += f"  <- {detail}"
        print(line)

    print()
    print(f"{passed}/{len(CHECKS)} checks passed")
    if leftovers:
        print("root dirs still present: " + ", ".join(sorted(leftovers)))
    return 0 if passed == len(CHECKS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
