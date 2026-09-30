"""Settings dialog for TONYAgent.

Modal editor for the settings otherwise buried in ``config.toml``: appearance,
provider defaults, sandbox resources, and tool safety. Saves via ``settings.save()``.
"""

from __future__ import annotations

import customtkinter as ctk
from loguru import logger

from tonyagent.config.settings import settings
from tonyagent.ui.theme import theme_manager
from tonyagent.ui.widgets import (
    PillComboBox,
    PillEntry,
    PillFrame,
    PillLabel,
    PrimaryPillButton,
    SecondaryPillButton,
)

PAD = 12
LABEL_FONT = ("Segoe UI", 12)
TITLE_FONT = ("Segoe UI", 15, "bold")
MUTED_FONT = ("Segoe UI", 11)

SANDBOX_TYPES = ["auto", "docker", "windows"]
THEMES = ["system", "light", "dark"]


class SettingsDialog(ctk.CTkToplevel):
    """Tabbed settings editor. ``show()`` blocks until the user closes it."""

    def __init__(self, parent, on_saved=None):
        super().__init__(parent)
        self._on_saved = on_saved
        self.title("TONYAgent Settings")
        self.geometry("620x580")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self._close)

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        PillLabel(self, text="Settings", font=TITLE_FONT, anchor="w").grid(
            row=0, column=0, sticky="ew", padx=PAD, pady=(PAD, 4)
        )

        self.tabs = ctk.CTkTabview(self, corner_radius=10)
        self.tabs.grid(row=1, column=0, sticky="nsew", padx=PAD, pady=4)
        self.tab_appearance = self.tabs.add("Appearance")
        self.tab_provider = self.tabs.add("Provider")
        self.tab_sandbox = self.tabs.add("Sandbox")
        self.tab_tools = self.tabs.add("Tools & Safety")

        self._build_appearance()
        self._build_provider()
        self._build_sandbox()
        self._build_tools()
        self._build_footer()
        self.tabs.set("Appearance")

    def _field_label(self, parent, text, row):
        PillLabel(parent, text=text, font=LABEL_FONT).grid(
            row=row, column=0, sticky="w", padx=PAD, pady=8
        )

    def _hint(self, parent, text, row, token="text_muted"):
        PillLabel(
            parent,
            text=text,
            font=MUTED_FONT,
            text_color=theme_manager.get_color_pair(token),
            justify="left",
        ).grid(row=row, column=0, columnspan=2, sticky="w", padx=PAD, pady=(0, 8))

    def _build_appearance(self) -> None:
        tab = self.tab_appearance
        tab.grid_columnconfigure(1, weight=1)
        self._field_label(tab, "Theme:", 0)
        self.theme_combo = PillComboBox(tab, values=THEMES, width=200)
        self.theme_combo.grid(row=0, column=1, sticky="ew", padx=PAD, pady=8)
        self.theme_combo.set(settings.ui.theme or "system")
        self._hint(tab, "Light, Dark, or follow the Windows setting.", 1)

    def _build_sandbox(self) -> None:
        tab = self.tab_sandbox
        tab.grid_columnconfigure(1, weight=1)
        self._field_label(tab, "Backend:", 0)
        self.sandbox_type_combo = PillComboBox(tab, values=SANDBOX_TYPES, width=200)
        self.sandbox_type_combo.grid(row=0, column=1, sticky="ew", padx=PAD, pady=8)
        self.sandbox_type_combo.set(settings.sandbox.type or "auto")
        self._hint(
            tab,
            "'windows' is not implemented yet; use 'docker' or 'auto'.",
            1,
            token="warning",
        )

        fields = [
            ("Docker image:", "docker_image", "tonyagent/sandbox:latest"),
            ("Memory limit:", "memory_limit", "e.g. 2g"),
            ("CPU limit:", "cpu_limit", "cores, e.g. 1.0"),
            ("Command timeout (s):", "timeout", "30"),
        ]
        for row, (text, attr, placeholder) in enumerate(fields, start=2):
            self._field_label(tab, text, row)
            entry = PillEntry(tab, placeholder_text=placeholder)
            entry.grid(row=row, column=1, sticky="ew", padx=PAD, pady=8)
            entry.insert(0, str(getattr(settings.sandbox, attr, "") or ""))
            setattr(self, f"sandbox_{attr}_entry", entry)

        self.network_check = ctk.CTkCheckBox(
            tab, text="Allow network access inside the sandbox", font=LABEL_FONT
        )
        self.network_check.grid(row=6, column=0, columnspan=2, sticky="w", padx=PAD, pady=(4, 8))
        if settings.sandbox.enable_network:
            self.network_check.select()
        self._hint(
            tab,
            "Off by default. The browser_* tools need this; shell commands do not.",
            7,
        )

        PillLabel(tab, text="Isolation", font=("Segoe UI", 13, "bold")).grid(
            row=8, column=0, columnspan=2, sticky="w", padx=PAD, pady=(12, 4)
        )
        self.pids_check = self._iso_check(
            tab, 9, "Limit process count (fork-bomb protection)",
            settings.sandbox.pids_limit > 0, "pids_limit",
        )
        self.nnp_check = self._iso_check(
            tab, 10, "no-new-privileges (setuid gains nothing)",
            settings.sandbox.no_new_privileges, "no_new_privileges",
        )
        self.caps_check = self._iso_check(
            tab, 11, "Drop all Linux capabilities",
            settings.sandbox.drop_capabilities, "drop_capabilities",
        )
        self.ro_check = self._iso_check(
            tab, 12, "Mount /workspace read-only",
            settings.sandbox.workspace_read_only, "workspace_read_only",
        )
        self._hint(
            tab,
            "All four are on by default. Dropping capabilities occasionally breaks\n"
            "Chromium; if browser tools misbehave, turn that one off first.",
            13,
        )

    def _iso_check(self, parent, row, text, default, attr):
        var = ctk.BooleanVar(value=bool(default))
        box = ctk.CTkCheckBox(parent, text=text, font=MUTED_FONT, variable=var)
        box.grid(row=row, column=0, columnspan=2, sticky="w", padx=PAD, pady=2)
        setattr(self, f"iso_{attr}", var)
        return var

    def _build_tools(self) -> None:
        tab = self.tab_tools
        tab.grid_columnconfigure(0, weight=1)
        self.fallback_check = ctk.CTkCheckBox(
            tab,
            text="Run shell commands on the host when no sandbox is running",
            font=LABEL_FONT,
        )
        self.fallback_check.grid(row=0, column=0, sticky="w", padx=PAD, pady=8)
        if getattr(settings.tools, "fallback_to_local", False):
            self.fallback_check.select()
        self._hint(
            tab,
            "Off (recommended) means execute_command fails closed instead of running\n"
            "on your machine. The 'Trust this project' checkbox in the sidebar only\n"
            "relaxes confirmations - it never changes this.",
            1,
        )

        self.internal_http_check = ctk.CTkCheckBox(
            tab,
            text="Allow http_request to reach internal addresses",
            font=LABEL_FONT,
        )
        self.internal_http_check.grid(row=2, column=0, sticky="w", padx=PAD, pady=(12, 4))
        if getattr(settings.tools, "allow_internal_http", False):
            self.internal_http_check.select()
        self._hint(
            tab,
            "Off (recommended) blocks loopback, private, and link-local targets,\n"
            "including 169.254.169.254 cloud metadata. Independent of the sandbox\n"
            "network setting above - turning sandbox network on does NOT enable this.",
            3,
            token="warning",
        )

    def _build_footer(self) -> None:
        frame = PillFrame(self, fg_color="transparent")
        frame.grid(row=2, column=0, sticky="ew", padx=PAD, pady=(0, PAD))
        frame.grid_columnconfigure(0, weight=1)

        self.hint_label = PillLabel(
            frame,
            text="",
            font=MUTED_FONT,
            text_color=theme_manager.get_color_pair("success"),
        )
        self.hint_label.grid(row=0, column=0, sticky="w", padx=8)
        SecondaryPillButton(frame, text="Cancel", width=100, command=self._close).grid(
            row=0, column=1, padx=4
        )
        PrimaryPillButton(frame, text="Save", width=100, command=self._save).grid(
            row=0, column=2, padx=4
        )

    def _save(self) -> None:
        try:
            theme = self.theme_combo.get()
            if theme in THEMES:
                settings.ui.theme = theme
            settings.provider.name = self.provider_combo.get()
            settings.provider.model = self.model_entry.get().strip()

            settings.sandbox.type = self.sandbox_type_combo.get()
            settings.sandbox.docker_image = (
                self.sandbox_docker_image_entry.get().strip() or "tonyagent/sandbox:latest"
            )
            memory = self.sandbox_memory_limit_entry.get().strip()
            if memory:
                settings.sandbox.memory_limit = memory
            cpu = self.sandbox_cpu_limit_entry.get().strip()
            if cpu:
                settings.sandbox.cpu_limit = cpu
            timeout = self.sandbox_timeout_entry.get().strip()
            if timeout.isdigit() and int(timeout) > 0:
                settings.sandbox.timeout = int(timeout)
            settings.sandbox.enable_network = bool(self.network_check.get())

            settings.sandbox.no_new_privileges = bool(self.iso_no_new_privileges.get())
            settings.sandbox.drop_capabilities = bool(self.iso_drop_capabilities.get())
            settings.sandbox.workspace_read_only = bool(self.iso_workspace_read_only.get())
            settings.sandbox.pids_limit = (
                512 if self.iso_pids_limit.get() else 0
            )

            if not hasattr(settings.tools, "fallback_to_local"):
                settings.tools.fallback_to_local = False
            settings.tools.fallback_to_local = bool(self.fallback_check.get())
            if not hasattr(settings.tools, "allow_internal_http"):
                settings.tools.allow_internal_http = False
            settings.tools.allow_internal_http = bool(self.internal_http_check.get())

            settings.save()
        except Exception as e:  # stay open so the user can correct and retry
            logger.exception("Failed to save settings")
            self.hint_label.configure(text=f"Could not save: {e}")
            self.hint_label.configure(
                text_color=theme_manager.get_color_pair("error")
            )
            return

        try:  # apply live so the user sees the result immediately
            theme_manager.set_theme(theme)
        except Exception:
            logger.exception("Failed to apply theme")
        if self._on_saved:
            try:
                self._on_saved()
            except Exception:
                logger.exception("Settings on_saved callback failed")
        self._close()

    def _close(self) -> None:
        try:
            self.grab_release()
        except Exception:
            pass
        self.destroy()

    def show(self) -> None:
        """Block until the dialog is closed."""
        self.focus_force()
        self.wait_window()
