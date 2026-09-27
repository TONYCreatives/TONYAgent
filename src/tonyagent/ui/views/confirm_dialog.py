"""Confirmation dialog for destructive tool operations."""

from __future__ import annotations

import customtkinter as ctk
from typing import Callable, Optional

from tonyagent.ui.widgets import (
    PrimaryPillButton,
    DangerPillButton,
    SecondaryPillButton,
    PillFrame,
    PillLabel,
    PillTextbox,
)
from tonyagent.tools.orchestrator import ConfirmationRequest


class ConfirmationDialog(ctk.CTkToplevel):
    """Modal dialog for tool confirmation."""

    def __init__(
        self,
        parent: ctk.CTk,
        confirmation: ConfirmationRequest,
        on_confirm: Callable[[bool], None],
    ):
        super().__init__(parent)
        self.confirmation = confirmation
        self.on_confirm = on_confirm
        self._result = False

        self.title("Confirm Tool Execution")
        self.geometry("500x400")
        self.minsize(450, 350)
        self.resizable(False, False)

        # Make modal
        self.transient(parent)
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self._on_cancel)

        self._create_widgets()
        self._center_window()

    def _create_widgets(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        # Header
        header = PillFrame(self, fg_color=("red50", "red900"), corner_radius=12)
        header.grid(row=0, column=0, sticky="ew", padx=16, pady=16)
        header.grid_columnconfigure(0, weight=1)

        warning_label = PillLabel(
            header,
            text="⚠️  Destructive Operation",
            font=("Segoe UI", 16, "bold"),
            text_color=("red", "lightcoral"),
        )
        warning_label.grid(row=0, column=0, padx=16, pady=12)

        # Tool info
        info_frame = PillFrame(self, corner_radius=12)
        info_frame.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 16))
        info_frame.grid_columnconfigure(0, weight=1)

        tool = self.confirmation.tool
        call = self.confirmation.tool_call

        PillLabel(
            info_frame,
            text=f"Tool: {tool.name}",
            font=("Segoe UI", 13, "bold"),
        ).grid(row=0, column=0, padx=16, pady=(12, 4), sticky="w")

        PillLabel(
            info_frame,
            text=f"Description: {tool.description}",
            font=("Segoe UI", 12),
            wraplength=450,
        ).grid(row=1, column=0, padx=16, pady=4, sticky="w")

        # Arguments display
        args_text = PillTextbox(info_frame, height=150, font=("Consolas", 11))
        args_text.grid(row=2, column=0, padx=16, pady=12, sticky="ew")
        import json
        args_text.insert("1.0", json.dumps(call.arguments, indent=2))
        args_text.configure(state="disabled")

        # Warning text
        warn_label = PillLabel(
            info_frame,
            text="This operation cannot be undone. Please review carefully.",
            font=("Segoe UI", 11),
            text_color=("orange", "gold"),
        )
        warn_label.grid(row=3, column=0, padx=16, pady=(0, 12), sticky="w")

        # Buttons
        btn_frame = PillFrame(self, fg_color="transparent")
        btn_frame.grid(row=2, column=0, sticky="ew", padx=16, pady=(0, 16))
        btn_frame.grid_columnconfigure(0, weight=1)
        btn_frame.grid_columnconfigure(1, weight=1)
        btn_frame.grid_columnconfigure(2, weight=1)

        DangerPillButton(
            btn_frame,
            text="Cancel",
            width=120,
            command=self._on_cancel,
        ).grid(row=0, column=0, padx=4)

        SecondaryPillButton(
            btn_frame,
            text="View Diff",
            width=120,
            command=self._view_diff,
        ).grid(row=0, column=1, padx=4)

        PrimaryPillButton(
            btn_frame,
            text="Confirm",
            width=120,
            command=self._on_confirm,
        ).grid(row=0, column=2, padx=4)

    def _center_window(self) -> None:
        self.update_idletasks()
        x = self.winfo_parent().winfo_rootx() + (self.winfo_parent().winfo_width() // 2) - (self.winfo_width() // 2)
        y = self.winfo_parent().winfo_rooty() + (self.winfo_parent().winfo_height() // 2) - (self.winfo_height() // 2)
        self.geometry(f"+{x}+{y}")

    def _on_confirm(self) -> None:
        self._result = True
        self.on_confirm(True)
        self.destroy()

    def _on_cancel(self) -> None:
        self._result = False
        self.on_confirm(False)
        self.destroy()

    def _view_diff(self) -> None:
        """Show diff for edit_file operations (placeholder)."""
        # Could expand to show actual diff
        pass