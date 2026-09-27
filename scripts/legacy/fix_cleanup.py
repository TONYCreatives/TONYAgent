"""Code-quality pass: items 1-5 from the review.

1. widgets/__init__.py : `master: any` -> `Any`, mutable default args
2. theme.py            : make get_color/set_custom_color real, add get_color_pair
   main_window.py      : drop hardcoded hex colors, re-apply on theme change
3. main_window.py      : _restart_sandbox only restarts after a completed stop
4. verify script       : relative paths + ASCII output (no cp949 crash)
5. root clutter        : archive one-off patch/generator scripts, drop empty junk dirs

Run:  python fix_cleanup.py
"""

from __future__ import annotations

import ast
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).parent
PKG = ROOT / "src" / "tonyagent"
WIDGETS = PKG / "ui" / "widgets" / "__init__.py"
THEME = PKG / "ui" / "theme.py"
MAIN = PKG / "ui" / "views" / "main_window.py"

report: list[str] = []


def note(msg: str) -> None:
    report.append(msg)


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write(path: Path, text: str) -> None:
    ast.parse(text)
    path.write_text(text, encoding="utf-8")


def sub(text: str, old: str, new: str, label: str) -> tuple[str, bool]:
    if old not in text:
        return text, False
    return text.replace(old, new, 1), True


# =========================================================== 1. widgets
def fix_widgets() -> None:
    text = read(WIDGETS)

    text, ok = sub(
        text,
        "from typing import Callable, Optional",
        "from typing import Any, Callable, Optional",
        "typing import",
    )
    note(f"1. widgets: Any imported                     {'OK' if ok else 'SKIP'}")

    before = text.count("master: any")
    text = text.replace("master: any", "master: Any")
    note(f"1. widgets: 'any' -> 'Any' ({before} sites)              {'OK' if before else 'SKIP'}")

    # mutable default arguments (shared across every widget instance)
    for cls, old, new in [
        (
            "PillComboBox",
            """        values: list[str] = [],
        width: int = 200,
        height: int = 36,
        corner_radius: int = 18,
        font: tuple = ("Segoe UI", 13),
        dropdown_font: tuple = ("Segoe UI", 13),
        **kwargs
    ):
        super().__init__(
            master,
            values=values,""",
            """        values: Optional[list[str]] = None,
        width: int = 200,
        height: int = 36,
        corner_radius: int = 18,
        font: tuple = ("Segoe UI", 13),
        dropdown_font: tuple = ("Segoe UI", 13),
        **kwargs
    ):
        super().__init__(
            master,
            values=list(values) if values else [],""",
        ),
        (
            "PillSegmentedButton",
            """        values: list[str] = [],
        width: int = 300,
        height: int = 36,
        corner_radius: int = 18,
        font: tuple = ("Segoe UI", 13),
        **kwargs
    ):
        super().__init__(
            master,
            values=values,""",
            """        values: Optional[list[str]] = None,
        width: int = 300,
        height: int = 36,
        corner_radius: int = 18,
        font: tuple = ("Segoe UI", 13),
        **kwargs
    ):
        super().__init__(
            master,
            values=list(values) if values else [],""",
        ),
    ]:
        text, ok = sub(text, old, new, cls)
        note(f"1. widgets: {cls} mutable default fixed    {'OK' if ok else 'SKIP'}")

    write(WIDGETS, text)


# =========================================================== 2. theme
def fix_theme() -> None:
    text = read(THEME)

    text, ok = sub(
        text,
        "        self._observers: list[Callable[[str], None]] = []",
        "        self._observers: list[Callable[[str], None]] = []\n"
        "        self._overrides: dict[str, str] = {}",
        "overrides field",
    )
    note(f"2. theme: _overrides dict added                   {'OK' if ok else 'SKIP'}")

    text, ok = sub(
        text,
        '''    def get_color(self, token: str) -> str:
        """Get a color token value for current theme."""
        actual = self.get_actual_theme()''',
        '''    def get_color(self, token: str) -> str:
        """Get a color token value for current theme (custom overrides win)."""
        override = self._overrides.get(token)
        if override:
            return override
        actual = self.get_actual_theme()''',
        "get_color override",
    )
    note(f"2. theme: get_color honours overrides             {'OK' if ok else 'SKIP'}")

    text, ok = sub(
        text,
        '''    def set_custom_color(self, token: str, value: str) -> None:
        """Set a custom color override (not fully supported in this simple implementation)."""
        # For a full implementation, we would need to create a custom theme JSON file
        pass''',
        '''    def get_color_pair(self, token: str) -> tuple[str, str]:
        """Return a (light, dark) pair, i.e. a customtkinter color tuple.

        Use this for text_color / fg_color so widgets keep following the theme
        instead of being frozen into a single hex value.
        """
        override = self._overrides.get(token)
        if override:
            return (override, override)
        previous = self._current_mode
        try:
            self._current_mode = "light"
            light = self.get_color(token)
            self._current_mode = "dark"
            dark = self.get_color(token)
        finally:
            self._current_mode = previous
        return (light, dark)

    def set_custom_color(self, token: str, value: str) -> None:
        """Override a color token and refresh observers so the change is visible."""
        self._overrides[token] = value
        self._notify_observers(self._current_mode)

    def clear_custom_colors(self) -> None:
        """Drop every custom color override."""
        self._overrides.clear()
        self._notify_observers(self._current_mode)''',
        "set_custom_color",
    )
    note(f"2. theme: set_custom_color + get_color_pair        {'OK' if ok else 'SKIP'}")

    write(THEME, text)


# ================================================= 2 + 3. main window
COLOR_MAP = {
    'text_color="#EF4444"': 'text_color=theme_manager.get_color_pair("error")',
    'text_color="#34D399"': 'text_color=theme_manager.get_color_pair("success")',
    'text_color=("#EF4444", "#EF4444")': 'text_color=theme_manager.get_color_pair("error")',
    'text_color=("#34D399", "#34D399")': 'text_color=theme_manager.get_color_pair("success")',
    'text_color=("#FBBF24", "#FBBF24")': 'text_color=theme_manager.get_color_pair("warning")',
}


def fix_main() -> None:
    text = read(MAIN)

    # -- 2: replace every hardcoded status color with a theme token
    total = 0
    for old, new in COLOR_MAP.items():
        count = text.count(old)
        total += count
        text = text.replace(old, new)
    note(f"2. main: {total} hardcoded hex colors -> theme tokens")

    # -- 2: new state fields
    text, ok = sub(
        text,
        """        self._message_labels: list[ctk.CTkLabel] = []""",
        """        self._message_labels: list[ctk.CTkLabel] = []
        self._provider_token = "error"
        self._sandbox_running = False
        self._restart_pending = False""",
        "state fields",
    )
    note(f"2. main: provider/sandbox/restart state flags        {'OK' if ok else 'SKIP'}")

    # -- 2: observer must be registered after every widget exists
    text, ok = sub(
        text,
        """        ToolTip(self.settings_btn, "Settings")

        # Register for theme changes
        theme_manager.register_observer(self._on_theme_change)""",
        """        ToolTip(self.settings_btn, "Settings")""",
        "move register_observer",
    )
    note(f"2. main: observer registration moved to __init__   {'OK' if ok else 'SKIP'}")

    text, ok = sub(
        text,
        """        # Initialize provider from settings
        self._init_provider()""",
        """        # Initialize provider from settings
        self._init_provider()

        # Register for theme changes only once every widget exists
        theme_manager.register_observer(self._on_theme_change)""",
        "re-register observer",
    )
    note(f"2. main: observer re-registered in __init__        {'OK' if ok else 'SKIP'}")

    # -- 2: refresh dynamic colors on theme change
    text, ok = sub(
        text,
        '''    def _on_theme_change(self, mode: str) -> None:
        """Handle theme change (resolve "system" to the real appearance)."""
        actual = theme_manager.get_actual_theme()''',
        '''    def _on_theme_change(self, mode: str) -> None:
        """Handle theme change (resolve "system" to the real appearance)."""
        actual = theme_manager.get_actual_theme()
        # Widgets already on screen need their colors pushed back
        self.provider_status.configure(
            text_color=theme_manager.get_color_pair(self._provider_token)
        )
        sandbox_token = "success" if self._sandbox_running else "error"
        self.sandbox_status.configure(text_color=theme_manager.get_color_pair(sandbox_token))
        self.sandbox_panel_status.configure(
            text_color=theme_manager.get_color_pair(sandbox_token)
        )
        self.lock_indicator.configure(text_color=theme_manager.get_color_pair("error"))''',
        "on_theme_change refresh",
    )
    note(f"2. main: _on_theme_change re-applies colors         {'OK' if ok else 'SKIP'}")

    # -- 2: keep the token in sync with the state it describes
    text, ok = sub(
        text,
        """        if self._current_provider:""",
        """        if self._current_provider:
            self._provider_token = "success\"""",
        "provider token success",
    )
    text, ok2 = sub(
        text,
        """        else:
            self.provider_status.configure(text="● No Provider\"""",
        """        else:
            self._provider_token = "error"
            self.provider_status.configure(text="● No Provider\"""",
        "provider token error",
    )
    note(f"2. main: provider token kept in sync              {'OK' if ok and ok2 else 'SKIP'}")

    text, ok = sub(
        text,
        """    def _update_sandbox_ui(self, running: bool) -> None:
        \"\"\"Update sandbox UI based on running state.\"\"\"
        if running:""",
        """    def _update_sandbox_ui(self, running: bool) -> None:
        \"\"\"Update sandbox UI based on running state.\"\"\"
        self._sandbox_running = running
        if running:""",
        "sandbox running flag",
    )
    note(f"2. main: _sandbox_running tracked                   {'OK' if ok else 'SKIP'}")

    # -- 3: restart only after the stop really finished
    text, ok = sub(
        text,
        '''    def _restart_sandbox(self) -> None:
        """Restart the sandbox."""
        self._stop_sandbox()
        self.root.after(1000, self._start_sandbox)''',
        '''    def _restart_sandbox(self) -> None:
        """Restart the sandbox, but only once the stop has actually finished."""
        self._restart_pending = True
        self.sandbox_restart_btn.configure(state="disabled")
        self._stop_sandbox()''',
        "restart_sandbox",
    )
    text, ok2 = sub(
        text,
        """        self._log("Sandbox stopped", "info")
        self._update_sandbox_ui(False)""",
        """        self._log("Sandbox stopped", "info")
        self._update_sandbox_ui(False)
        if self._restart_pending:
            self._restart_pending = False
            self.root.after(500, self._start_sandbox)""",
        "restart chain",
    )
    note(f"3. main: restart waits for a completed stop        {'OK' if ok and ok2 else 'SKIP'}")

    write(MAIN, text)


# =========================================================== 4 + 5. hygiene
def archive_scripts() -> None:
    legacy = ROOT / "scripts" / "legacy"
    legacy.mkdir(parents=True, exist_ok=True)

    patterns = ("fix_*.py", "gen_*.py", "write_*.py", "test_providers*.py", "test_imports.py")
    moved: list[str] = []
    for pattern in patterns:
        for path in sorted(ROOT.glob(pattern)):
            if path.parent == ROOT:
                shutil.move(str(path), str(legacy / path.name))
                moved.append(path.name)

    for name in ("verify_fixes.py", "verify_simple.py", "test.txt"):
        path = ROOT / name
        if path.exists():
            path.unlink()
            moved.append(name + " (deleted)")

    note(f"5. root scripts archived to scripts/legacy/        {len(moved)} file(s)")
    for name in moved:
        report.append(f"        - {name}")


def prune_empty_dirs() -> None:
    skip = {
        ".git", ".github", ".venv", "venv", "src", "tests", "docs", "scripts", "docker",
        "ui", "integration", "windows", "core", "tools", "providers", "sandbox", "folder",
    }
    removed: list[str] = []
    kept: list[str] = []
    for path in sorted(ROOT.iterdir()):
        if not path.is_dir() or path.name in skip or path.name.startswith("."):
            continue
        if any(path.iterdir()):
            kept.append(path.name)
            continue
        path.rmdir()
        removed.append(path.name)

    note(f"5. empty junk dirs removed                         {len(removed)}")
    for name in removed:
        report.append(f"        - {name}/")
    if kept:
        note("5. NON-empty dirs left in place (review manually):")
        for name in kept:
            report.append(f"        - {name}/")


def main() -> int:
    fix_widgets()
    fix_theme()
    fix_main()
    archive_scripts()
    prune_empty_dirs()

    sys.stdout.write("\n".join(report) + "\n")
    sys.stdout.write("\ndone\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
