"""Main window for TONYAgent."""

from __future__ import annotations

import asyncio
import json
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

import customtkinter as ctk
from tkinter import filedialog
from loguru import logger

from tonyagent.ui.theme import theme_manager
from tonyagent.ui.widgets import themed
from tonyagent.ui.widgets import (
    GhostPillButton,
    PillButton,
    PrimaryPillButton,
    SecondaryPillButton,
    DangerPillButton,
    PillEntry,
    PillComboBox,
    PillFrame,
    PillScrollableFrame,
    PillLabel,
    PillTextbox,
    ToolTip,
)
from tonyagent.folder.manager import folder_manager
from tonyagent.config.settings import settings
from tonyagent.providers import (
    ProviderFactory,
    ChatMessage,
    ToolSchema,
    ToolChoice,
    ChatCompletionChunk,
)
from tonyagent.tools import tool_orchestrator, ToolCall, ConfirmationRequest, ALL_SCHEMAS
from tonyagent.ui.views.confirm_dialog import ConfirmationDialog
from tonyagent.utils.threading import schedule_on_ui
from tonyagent.sandbox import SandboxConfig, SandboxStatus, get_shared_sandbox_manager
from tonyagent.ui.views.settings_dialog import SettingsDialog

# --- Layout tokens (Stage A) -------------------------------------------------
SIDEBAR_WIDTH = 340        # single source of truth; the root grid uses this too
# One spacing scale for the whole sidebar. The panels previously mixed 4/8/10/12
# by hand, so titles, fields and buttons lined up on different columns
# depending on which panel you looked at.
PAD_SM, PAD_MD, PAD_LG = 6, 12, 18
PAD_INNER = 14             # horizontal inset inside a panel
SECTION_TITLE_FONT = ("Segoe UI", 13, "bold")
BODY_FONT = ("Segoe UI", 12)
MUTED_FONT = ("Segoe UI", 11)


class MainWindow:
    """Main application window."""

    #: Class-level defaults for the session wiring.
    #:
    #: Tests build windows with ``MainWindow.__new__(MainWindow)``, which skips
    #: ``__init__``, and several call sites legitimately run before the session
    #: is bound. Declaring the attributes here means those paths see ``None``
    #: instead of raising ``AttributeError`` - the difference between a UI that
    #: degrades and one that crashes.
    _session = None
    _loop = None
    _pending_text = ""
    _cancel_token = None
    #: Mutable defaults must never live on the class: every window would share
    #: one list and leak conversation state between them. Bound per instance in
    #: ``__init__``; declared here only so the name exists.
    _message_history = None

    def __init__(self, root: ctk.CTk):
        self.root = root
        self._generating = False
        self._cancel_token = None
        self._current_provider = None
        self._message_history: list[ChatMessage] = []
        self._current_ai_message_frame = None
        self._current_ai_label = None
        self._message_labels: list[ctk.CTkLabel] = []
        self._provider_token = "error"
        self._sandbox_running = False
        self._restart_pending = False
        self._sandbox_poll_id: str | None = None
        self._docker_client = None
        self._sandbox_manager = get_shared_sandbox_manager()
        self._key_replace_mode = False
        self._stored_key_present = False
        self._session = None
        self._loop = None
        self._pending_text = ""
        self._setup_layout()
        self._create_header()
        self._create_sidebar()
        self._create_chat_area()
        self._create_status_bar()

        # Register for folder lock updates
        folder_manager.register_lock_callback(self._on_folder_lock_change)

        # The turn loop lives in AgentSession; this window only renders it.
        self._init_agent_session()

        # Initialize tool orchestrator
        tool_orchestrator.set_log_callback(self._on_tool_log)
        tool_orchestrator.set_confirmation_callback(self._show_tool_confirmation)

        # Initialize provider from settings
        self._init_provider()

        # Register for theme changes only once every widget exists
        theme_manager.register_observer(self._on_theme_change)
        self._apply_theme_tokens()

    def _setup_layout(self) -> None:
        """Setup main window grid layout."""
        # 3 rows: 0 = header (fixed), 1 = sidebar + chat (expanding), 2 = status bar
        self.root.grid_columnconfigure(0, weight=0, minsize=SIDEBAR_WIDTH)  # Sidebar
        self.root.grid_columnconfigure(1, weight=1)  # Chat area
        self.root.grid_rowconfigure(0, weight=0)  # Header
        self.root.grid_rowconfigure(1, weight=1)  # Sidebar + chat area
        self.root.grid_rowconfigure(2, weight=0)  # Status bar

    def _create_header(self) -> None:
        """Create header bar."""
        self.header = PillFrame(self.root, corner_radius=0, height=50)
        self.header.grid(row=0, column=0, columnspan=2, sticky="ew", padx=0, pady=0)
        self.header.grid_propagate(False)
        self.header.grid_columnconfigure(1, weight=1)

        # App title
        self.title_label = PillLabel(
            self.header,
            text="TONYAgent",
            font=("Segoe UI", 18, "bold"),
        )
        self.title_label.grid(row=0, column=0, padx=20, pady=10, sticky="w")

        # Theme toggle
        self.theme_btn = PillButton(
            self.header,
            text="🌙" if theme_manager.get_actual_theme() == "light" else "☀️",
            width=40,
            height=36,
            command=self._toggle_theme,
        )
        self.theme_btn.grid(row=0, column=2, padx=10, pady=7, sticky="e")
        ToolTip(self.theme_btn, "Toggle theme (Light/Dark/System)")

        # Settings button
        self.settings_btn = PillButton(
            self.header,
            text="⚙",
            width=40,
            height=36,
            command=self._open_settings,
        )
        self.settings_btn.grid(row=0, column=3, padx=20, pady=7, sticky="e")
        ToolTip(self.settings_btn, "Settings")

    def _create_sidebar(self) -> None:
        """Create left sidebar with provider config, folder picker, tool log, and sandbox control."""
        self.sidebar = PillScrollableFrame(self.root, width=SIDEBAR_WIDTH, corner_radius=0)
        self.sidebar.grid(row=1, column=0, sticky="nsew", padx=0, pady=0)
        self.sidebar.grid_columnconfigure(0, weight=1)

        # Priority order: what you touch every session comes first, setup and
        # diagnostics collapse below.
        self._create_folder_panel()      # row 0 - Project
        self._create_sandbox_panel()     # row 1 - Sandbox
        self._create_provider_panel()    # row 2 - Provider   (collapsible)
        self._create_tool_log_panel()    # row 3 - Activity   (collapsible, expands)

        # Only the activity panel expands; everything above keeps natural height.
        self.sidebar.grid_rowconfigure(3, weight=1)

    def _create_provider_panel(self) -> None:
        """Create provider configuration panel."""
        panel = PillFrame(self.sidebar)
        panel.grid(row=2, column=0, sticky="ew", padx=PAD_MD, pady=(PAD_SM, PAD_MD))
        panel.grid_columnconfigure(1, weight=1)
        self._provider_panel = panel

        # Title (columnspan=1 leaves room for the collapse chevron in column 1)
        self._provider_title = PillLabel(panel, text="API Provider", font=SECTION_TITLE_FONT)
        self._provider_title.grid(
            row=0, column=0, sticky="w", padx=PAD_INNER, pady=(PAD_INNER, PAD_SM)
        )

        # Provider dropdown
        PillLabel(panel, text="Provider:", font=BODY_FONT).grid(
            row=1, column=0, sticky="w", padx=PAD_INNER, pady=PAD_SM
        )
        self.provider_combo = PillComboBox(
            panel,
            values=["openai", "anthropic", "gemini", "mistral", "groq", "openrouter", "ollama", "custom"],
        )
        # No right padx on the field: it already carries the panel inset, and a
        # second inset made the fields sit visibly left of the panel edge.
        self.provider_combo.grid(row=1, column=1, sticky="ew", padx=(0, PAD_INNER), pady=PAD_SM)
        self.provider_combo.set(settings.provider.name or "openai")

        # API Key entry
        PillLabel(panel, text="API Key:", font=BODY_FONT).grid(
            row=2, column=0, sticky="w", padx=PAD_INNER, pady=PAD_SM
        )
        self.api_key_entry = PillEntry(
            panel,
            placeholder_text="Enter API key...",
            show="*",
        )
        self.api_key_entry.grid(row=2, column=1, sticky="ew", padx=(0, PAD_INNER), pady=PAD_SM)
        self.api_key_saved_hint = PillLabel(
            panel,
            text="",
            font=MUTED_FONT,
            text_color=theme_manager.get_color_pair("text_muted"),
            justify="left",
            wraplength=270,
        )
        self.api_key_saved_hint.grid(
            row=3, column=0, columnspan=2, sticky="ew", padx=PAD_INNER, pady=(0, 0)
        )
        self.forget_key_btn = GhostPillButton(
            panel, text="Forget saved key", command=self._on_forget_key
        )
        self.forget_key_btn.grid(
            row=4, column=0, columnspan=2, sticky="w", padx=PAD_INNER - 4, pady=(0, 0)
        )
        self.forget_key_btn.grid_remove()

        # Model selector (row 5: rows 3-4 hold the key hint and Forget button)
        PillLabel(panel, text="Model:", font=BODY_FONT).grid(
            row=5, column=0, sticky="w", padx=PAD_INNER, pady=PAD_SM
        )
        self.model_combo = PillComboBox(panel, values=[], state="normal")
        self.model_combo.grid(row=5, column=1, sticky="ew", padx=(0, PAD_INNER), pady=PAD_SM)
        self._update_models()

        # Custom endpoint expander
        self.custom_frame = PillFrame(panel)
        self.custom_frame.grid(row=6, column=0, columnspan=2, sticky="ew", padx=12, pady=8)
        self.custom_frame.grid_columnconfigure(1, weight=1)
        self.custom_frame.grid_remove()  # Hidden by default

        PillLabel(self.custom_frame, text="Base URL:", font=("Segoe UI", 11)).grid(
            row=0, column=0, sticky="w", padx=8, pady=4
        )
        self.custom_url_entry = PillEntry(
            self.custom_frame, placeholder_text="https://api.example.com/v1"
        )
        self.custom_url_entry.grid(row=0, column=1, sticky="ew", padx=8, pady=4)

        # Test connection button
        self.test_btn = SecondaryPillButton(
            panel,
            text="Test Connection",
            width=130,
            command=self._test_connection,
        )
        self.test_btn.grid(
            row=7, column=0, sticky="w", padx=PAD_INNER, pady=(10, 0)
        )

        # Save to keyring button
        self.save_key_btn = PrimaryPillButton(
            panel,
            text="Save to Keyring",
            width=130,
            command=self._save_api_key,
        )
        self.save_key_btn.grid(
            row=7, column=1, sticky="e", padx=PAD_INNER, pady=(10, PAD_MD)
        )

        # Bind provider change to update models and custom frame visibility
        self.provider_combo.configure(command=self._on_provider_change)
        self._set_provider_expanded, self._provider_expanded = self._make_collapsible(
            panel, expanded=True, title_label=self._provider_title
        )

    def _create_folder_panel(self) -> None:
        """Create folder picker panel."""
        panel = PillFrame(self.sidebar)
        panel.grid(row=0, column=0, sticky="ew", padx=PAD_MD, pady=(PAD_SM, PAD_MD))
        panel.grid_columnconfigure(0, weight=1)

        # Title with lock indicator
        title_frame = PillFrame(panel, fg_color="transparent")
        title_frame.grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 8))
        title_frame.grid_columnconfigure(0, weight=1)

        PillLabel(title_frame, text="Project", font=SECTION_TITLE_FONT).grid(
            row=0, column=0, sticky="w"
        )

        self.lock_indicator = PillLabel(
            title_frame,
            text="🔒 Locked",
            font=("Segoe UI", 11),
            text_color=theme_manager.get_color_pair("error"),
        )
        self.lock_indicator.grid(row=0, column=1, sticky="e", padx=8)
        self.lock_indicator.grid_remove()

        # Current folder display
        self.folder_label = PillLabel(
            panel,
            text=folder_manager.current_folder.name if folder_manager.current_folder else "No folder selected",
            font=("Segoe UI", 11),
            text_color=theme_manager.get_color_pair("text_muted"),
        )
        self.folder_label.grid(
            row=1, column=0, sticky="ew", padx=PAD_INNER, pady=(0, PAD_SM)
        )

        # Folder picker button
        self.folder_btn = PrimaryPillButton(
            panel,
            text="Choose Folder",
            command=self._pick_folder,
        )
        self.folder_btn.grid(
            row=2, column=0, padx=PAD_INNER, pady=(0, PAD_MD), sticky="ew"
        )

    def _create_tool_log_panel(self) -> None:
        """Create tool execution log panel."""
        panel = PillFrame(self.sidebar)
        panel.grid(row=3, column=0, sticky="nsew", padx=PAD_MD, pady=(0, PAD_MD))
        panel.grid_columnconfigure(0, weight=1)
        panel.grid_rowconfigure(2, weight=1)

        # Title
        self._log_panel = panel
        self._log_title = PillLabel(panel, text="Activity", font=SECTION_TITLE_FONT)
        self._log_title.grid(
            row=0, column=0, sticky="w", padx=PAD_MD, pady=(PAD_MD, 8)
        )

        # Filter
        self.log_filter = PillComboBox(
            panel,
            values=["All", "File", "Shell", "Browser", "Error"],
        )
        self.log_filter.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 8))
        self.log_filter.set("All")
        self.log_filter.configure(command=self._on_log_filter)
        self._log_entries = []
        self._log_enabled = True

        # Log display
        self.log_textbox = PillTextbox(
            panel,
            height=200,
            corner_radius=8,
            font=("Consolas", 11),
        )
        self.log_textbox.grid(row=2, column=0, sticky="nsew", padx=12, pady=(0, 8))
        self.log_textbox.configure(state="disabled")
        # Level colors: single theme-agnostic strings (tuples are invalid for tk tags)
        self.log_textbox.tag_config("info", foreground="gray")
        self.log_textbox.tag_config("success", foreground="green")
        self.log_textbox.tag_config("warning", foreground="orange")
        self.log_textbox.tag_config("error", foreground="red")

        # Clear/Export buttons
        btn_frame = PillFrame(panel, fg_color="transparent")
        btn_frame.grid(row=3, column=0, sticky="ew", padx=12, pady=(0, 12))
        btn_frame.grid_columnconfigure(0, weight=1)
        btn_frame.grid_columnconfigure(1, weight=1)

        SecondaryPillButton(btn_frame, text="Clear", width=130, command=self._clear_log).grid(
            row=0, column=0, padx=(0, 4)
        )
        SecondaryPillButton(btn_frame, text="Export", width=130, command=self._export_log).grid(
            row=0, column=1, padx=(4, 0)
        )
        self._set_log_expanded, self._log_expanded = self._make_collapsible(
            panel, expanded=False, title_label=self._log_title
        )

    def _create_sandbox_panel(self) -> None:
        """Create sandbox control panel."""
        panel = PillFrame(self.sidebar)
        panel.grid(row=1, column=0, sticky="ew", padx=PAD_MD, pady=(0, PAD_MD))
        panel.grid_columnconfigure(0, weight=1)
        panel.grid_columnconfigure(1, weight=1)

        # Title
        PillLabel(panel, text="Sandbox", font=SECTION_TITLE_FONT).grid(
            row=0, column=0, columnspan=2, sticky="w", padx=PAD_INNER, pady=(PAD_INNER, PAD_SM)
        )

        # Status label
        self.sandbox_panel_status = PillLabel(
            panel,
            text="Status: Stopped",
            font=("Segoe UI", 11),
            text_color=theme_manager.get_color_pair("error"),
        )
        self.sandbox_panel_status.grid(
            row=1, column=0, columnspan=2, sticky="w", padx=PAD_INNER, pady=(0, PAD_SM)
        )

        # Resource usage labels. The second column starts at the midpoint with no
        # left inset, so "CPU" and "Memory" share one baseline instead of being
        # offset by their own padding.
        self.sandbox_cpu_label = PillLabel(
            panel,
            text="CPU: --",
            font=("Segoe UI", 11),
            text_color=theme_manager.get_color_pair("text_muted"),
        )
        self.sandbox_cpu_label.grid(row=2, column=0, sticky="w", padx=(PAD_INNER, 0), pady=2)

        self.sandbox_mem_label = PillLabel(
            panel,
            text="Memory: --",
            font=("Segoe UI", 11),
            text_color=theme_manager.get_color_pair("text_muted"),
        )
        self.sandbox_mem_label.grid(row=2, column=1, sticky="w", padx=(4, 0), pady=2)

        # Control buttons
        btn_frame = PillFrame(panel, fg_color="transparent", corner_radius=0)
        btn_frame.grid(
            row=3, column=0, columnspan=2, sticky="ew",
            padx=PAD_INNER, pady=(PAD_MD, PAD_INNER),
        )
        btn_frame.grid_columnconfigure(0, weight=1)
        btn_frame.grid_columnconfigure(1, weight=1)
        btn_frame.grid_columnconfigure(2, weight=1)

        self.sandbox_start_btn = PrimaryPillButton(
            btn_frame,
            text="Start",

            command=self._start_sandbox,
        )
        self.sandbox_start_btn.grid(row=0, column=0, padx=2)

        self.sandbox_stop_btn = DangerPillButton(
            btn_frame,
            text="Stop",

            command=self._stop_sandbox,
        )
        self.sandbox_stop_btn.grid(row=0, column=1, padx=2)

        self.sandbox_restart_btn = SecondaryPillButton(
            btn_frame,
            text="Restart",

            command=self._restart_sandbox,
        )
        self.sandbox_restart_btn.grid(row=0, column=2, padx=2)

        # Trust toggle (per-session): skip per-command confirmations for the
        # current project. Allowlisted shell commands still auto-approve;
        # non-allowlisted ones always ask. Resets when the folder changes.
        self._trust_var = ctk.BooleanVar(value=False)
        self.trust_check = ctk.CTkCheckBox(
            panel,
            text="Trust this project (skip confirmations)",
            variable=self._trust_var,
            font=("Segoe UI", 11),
            command=self._on_trust_toggle,
        )
        self.trust_check.grid(row=4, column=0, columnspan=2, sticky="w", padx=12, pady=(0, 12))
        ToolTip(self.trust_check, "Session-only. Non-allowlisted shell commands still ask.")

    def _create_chat_area(self) -> None:
        """Create main chat area."""
        self.chat_frame = PillFrame(self.root, corner_radius=0)
        self.chat_frame.grid(row=1, column=1, sticky="nsew", padx=0, pady=0)
        self.chat_frame.grid_columnconfigure(0, weight=1)
        self.chat_frame.grid_rowconfigure(0, weight=1)
        self.chat_frame.grid_rowconfigure(1, weight=0)

        # Conversation history
        self.chat_scroll = PillScrollableFrame(self.chat_frame)
        self.chat_scroll.grid(row=0, column=0, sticky="nsew", padx=16, pady=16)
        self.chat_scroll.grid_columnconfigure(0, weight=1)
        self.chat_scroll.bind("<Configure>", self._on_chat_resize)

        # Input composer - height must follow its children, never be clamped,
        # otherwise the button row below the input box gets cropped.
        self.composer_frame = PillFrame(self.chat_frame)
        self.composer_frame.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 16))
        self.composer_frame.grid_columnconfigure(0, weight=1)

        # Input textbox
        self.input_text = PillTextbox(
            self.composer_frame,
            height=80,
            corner_radius=12,
            font=("Segoe UI", 13),
        )
        self.input_text.grid(row=0, column=0, sticky="nsew", padx=12, pady=(12, 6))
        # Enter sends; Shift+Enter falls through to Tk's default newline binding
        self.input_text.bind("<Return>", self._on_send)
        self.input_text.bind("<Shift-Return>", lambda e: None)  # Allow newline

        # Send/Stop buttons
        btn_frame = PillFrame(self.composer_frame, fg_color="transparent")
        btn_frame.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 12))
        # Configure columns: 0=token label (left), 1=spacer (expand), 2=stop, 3=send
        btn_frame.grid_columnconfigure(0, weight=0)
        btn_frame.grid_columnconfigure(1, weight=1)  # Spacer expands to push buttons right
        btn_frame.grid_columnconfigure(2, weight=0)
        btn_frame.grid_columnconfigure(3, weight=0)

        # Token count label (left side)
        self.token_label = PillLabel(
            btn_frame,
            text="Tokens: 0",
            font=("Segoe UI", 11),
            text_color=("gray50", "gray60"),
        )
        self.token_label.grid(row=0, column=0, sticky="w", padx=12)

        self.stop_btn = DangerPillButton(
            btn_frame,
            text="Stop",
            width=100,
            command=self._on_stop,
        )
        self.stop_btn.grid(row=0, column=2, padx=4)
        self.stop_btn.grid_remove()  # Hidden by default

        self.send_btn = PrimaryPillButton(
            btn_frame,
            text="Send",
            width=100,
            command=self._on_send,
        )
        self.send_btn.grid(row=0, column=3, padx=4)

    def _create_status_bar(self) -> None:
        """Create status bar at bottom."""
        self.status_bar = PillFrame(self.root, corner_radius=0, height=30)
        self.status_bar.grid(row=2, column=0, columnspan=2, sticky="ew", padx=0, pady=0)
        self.status_bar.grid_propagate(False)
        # Let column 2 soak up the spare width so the version label stays pinned right
        self.status_bar.grid_columnconfigure(0, weight=0)
        self.status_bar.grid_columnconfigure(1, weight=0)
        self.status_bar.grid_columnconfigure(2, weight=1)
        self.status_bar.grid_columnconfigure(3, weight=0)

        # Provider status
        self.provider_status = PillLabel(
            self.status_bar,
            text="● Disconnected",
            font=("Segoe UI", 11),
            text_color=theme_manager.get_color_pair("error"),
        )
        self.provider_status.grid(row=0, column=0, padx=16, pady=4)

        # Model info
        self.model_label = PillLabel(
            self.status_bar,
            text="No model selected",
            font=("Segoe UI", 11),
            text_color=("gray50", "gray60"),
        )
        self.model_label.grid(row=0, column=1, padx=16, pady=4, sticky="w")

        # Sandbox status
        self.sandbox_status = PillLabel(
            self.status_bar,
            text="Sandbox: Stopped",
            font=("Segoe UI", 11),
            text_color=("gray50", "gray60"),
        )
        self.sandbox_status.grid(row=0, column=2, padx=16, pady=4, sticky="w")

        # Version
        self.version_label = PillLabel(
            self.status_bar,
            text="TONYAgent v0.1.0",
            font=("Segoe UI", 11),
            text_color=("gray50", "gray60"),
        )
        self.version_label.grid(row=0, column=3, padx=16, pady=4, sticky="e")
# Event handlers
    def _toggle_theme(self) -> None:
        """Toggle theme."""
        theme_manager.toggle_theme()

    def _on_theme_change(self, mode: str) -> None:
        self._apply_theme_tokens()
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
        self.lock_indicator.configure(text_color=theme_manager.get_color_pair("error"))
        self.theme_btn.configure(text="🌙" if actual == "light" else "☀️")

    def _on_provider_change(self, value: str) -> None:
        """Handle provider selection change."""
        self._update_models()
        self._update_custom_frame_visibility()
        # Reinitialize provider
        self._init_provider()
        # Remember the choice so a restart does not silently revert it.
        self._persist_provider_choice()

    def _update_models(self) -> None:
        """Update model dropdown based on selected provider.

        The combo is editable: OpenRouter and most gateways expose far more
        models than any hardcoded list, so keep whatever the user typed if it
        belongs to the newly selected provider.
        """
        provider = self.provider_combo.get()
        previous = (self.model_combo.get() or "").strip()
        models = {
            "openai": ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "gpt-4", "gpt-3.5-turbo"],
            "anthropic": ["claude-3-5-sonnet-20241022", "claude-3-5-haiku-20241022", "claude-3-opus-20240229"],
            "gemini": ["gemini-1.5-pro", "gemini-1.5-flash", "gemini-1.0-pro"],
            "mistral": ["mistral-large-latest", "mistral-medium-latest", "mistral-small-latest"],
            "groq": ["llama-3.1-70b-versatile", "llama-3.1-8b-instant", "mixtral-8x7b-32768"],
            "openrouter": ["openrouter/auto", "anthropic/claude-3.5-sonnet", "openai/gpt-4o"],
            "ollama": ["llama3.1", "llama3.2", "codellama", "mistral"],
            "custom": [],
        }
        model_list = models.get(provider, [])
        self.model_combo.configure(values=model_list)
        # Restore the saved model, else keep what the user typed, else fall back
        # to the first suggestion. This used to force model_list[0], silently
        # discarding the user's choice on every provider change.
        saved = (settings.provider.model or "").strip()
        if saved and (not model_list or saved in model_list or provider == "openrouter"):
            self.model_combo.set(saved)
        elif previous:
            self.model_combo.set(previous)
        elif model_list:
            self.model_combo.set(model_list[0])

    def _update_custom_frame_visibility(self) -> None:
        """Show/hide custom endpoint frame."""
        if self.provider_combo.get() == "custom":
            self.custom_frame.grid()
        else:
            self.custom_frame.grid_remove()

    def _test_connection(self) -> None:
        """Verify the key with a real network round-trip.

        The old check only did ``str.startswith()``, so the status bar showed
        "Connected" while every request came back 401.
        """
        provider = self.provider_combo.get()
        typed = self.api_key_entry.get().strip()
        if typed and "*" not in typed:
            try:
                from tonyagent.config.keyring import save_api_key

                save_api_key(provider, typed)
                self._log(f"Saved key for {provider}; testing...", "info")
            except Exception as e:
                self._log(f"Failed to save key: {e}", "error")
                return
        self._init_provider()
        self._log(f"Checking {provider} connection...", "info")
        self._set_connection_state("checking", "Checking...")

        def run() -> None:
            import asyncio

            async def probe():
                try:
                    health = await self._current_provider.check_connection()
                except Exception as e:
                    from tonyagent.api import LLMError

                    health = LLMError.network(e, provider)
                return health

            try:
                loop = asyncio.new_event_loop()
                health = loop.run_until_complete(probe())
                loop.close()
            except Exception as e:
                schedule_on_ui(self._set_connection_state, "error", f"Check failed: {e}")
                return
            schedule_on_ui(self._on_connection_result, health)

        threading.Thread(target=run, daemon=True).start()

    def _on_connection_result(self, health) -> None:
        """Render a real health-check result."""
        if health.ok:
            self._log(health.message, "success")
            self._set_connection_state("success", "● Connected")
            if health.models:
                self._set_model_choices(health.models)
        else:
            self._log(health.message, "error")
            self._set_connection_state("error", "● Rejected")
            self._show_error(health.message)

    def _set_connection_state(self, token: str, text: str) -> None:
        self._provider_token = token
        self.provider_status.configure(
            text=text, text_color=theme_manager.get_color_pair(
                "success" if token == "success" else ("warning" if token == "checking" else "error")
            )
        )

    def _set_model_choices(self, models: list[str]) -> None:
        """Populate the model dropdown from the provider's live list."""
        current = self.model_combo.get()
        self.model_combo.configure(values=models)
        if current and current in models:
            self.model_combo.set(current)
        elif models:
            self.model_combo.set(models[0])

    def _show_error(self, message: str) -> None:
        """Surface a provider error in the chat area, where it cannot be missed."""
        self._add_ai_message(message, error=True)

    def _save_api_key(self) -> None:
        """Save the typed API key to the OS keyring."""
        provider = self.provider_combo.get()
        api_key = self.api_key_entry.get().strip()
        if not api_key:
            self._log("No API key entered", "error")
            return
        # The entry shows the stored key masked when not replacing. Saving that
        # placeholder would destroy the real key, so require a real replacement.
        if "*" in api_key:
            self._log("That is not a valid key - paste the real key text.", "error")
            return

        try:
            from tonyagent.config.keyring import save_api_key
            save_api_key(provider, api_key)
            self._log(f"API key saved for {provider}", "success")
            self._key_replace_mode = False
            # Reinitialize provider with new key
            self._init_provider()
            self._persist_provider_choice()
        except Exception as e:
            self._log(f"Failed to save key: {e}", "error")

    def _pick_folder(self) -> None:
        """Open folder picker dialog."""
        if folder_manager.is_locked:
            return

        initial_dir = str(folder_manager.current_folder) if folder_manager.current_folder else ""
        path = filedialog.askdirectory(
            title="Select Project Folder",
            initialdir=initial_dir,
        )
        if path:
            success = folder_manager.set_folder(path)
            if success:
                # Trust is per-session AND per-folder: a new folder starts untrusted.
                from tonyagent.tools import tool_orchestrator as _orch

                _orch.set_trusted(path, False)
                if hasattr(self, "_trust_var"):
                    self._trust_var.set(False)
                self._update_folder_display()
                self._log(f"Folder set: {path}", "success")
            else:
                self._log("Failed to set folder", "error")

    def _on_folder_lock_change(self, locked: bool, reason: str) -> None:
        """Handle folder lock state change."""
        if locked:
            self.folder_btn.configure(state="disabled")
            self.lock_indicator.configure(text=f"🔒 {reason}")
            self.lock_indicator.grid()
        else:
            self.folder_btn.configure(state="normal")
            self.lock_indicator.grid_remove()
        self._update_folder_display()

    def _update_folder_display(self) -> None:
        """Update folder label."""
        if folder_manager.current_folder:
            self.folder_label.configure(text=folder_manager.current_folder.name)
        else:
            self.folder_label.configure(text="No folder selected")

    def _init_provider(self) -> None:
        """Initialize provider from settings and hand it to the session.

        The session is the single owner of provider state; ``_current_provider``
        is kept only so the existing UI checks (key present, model label) keep
        working without a wider refactor.
        """
        provider_name = self.provider_combo.get() or settings.provider.name
        model = self.model_combo.get() or settings.provider.model
        try:
            self._current_provider = ProviderFactory.create_provider(
                provider_name, model=model
            )
        except ValueError as exc:
            # A base_url in config with no http(s):// scheme. Report it and run
            # with no provider rather than letting the window fail to open.
            self._current_provider = None
            self._set_connection_state("error", f"● {exc}")
        if self._session is not None:
            # Share the very instance the UI inspected, so a key saved later is
            # picked up without re-creating it here.
            self._session.provider = self._current_provider
            self._session.provider_name = provider_name
            self._session.model = model
        self._reflect_saved_key(provider_name)
        if self._current_provider:
            has_key = bool(getattr(self._current_provider, "api_key", ""))
            if not has_key:
                self._set_connection_state("error", "● No API key")
            elif self._provider_token != "success":
                # Unverified: say so instead of claiming a connection.
                self._set_connection_state("warning", "● Not checked")
            self.model_label.configure(text=f"{provider_name}/{model}")
        else:
            self._provider_token = "error"
            self.provider_status.configure(text="● No Provider", text_color=theme_manager.get_color_pair("error"))

    def _reflect_saved_key(self, provider_name: str) -> None:
        """Show the keyring state for this provider and keep the field usable.

        The entry is ALWAYS enabled and always empty: clicking it and typing must
        just work. Disabling it made it look broken (you cannot click a disabled
        Tk entry), and a forced "Replace key" step was an unnecessary extra click.
        The presence of a saved key is communicated by the hint line instead.
        """
        if not hasattr(self, "api_key_entry"):
            return
        try:
            from tonyagent.config.keyring import load_api_key

            stored = load_api_key(provider_name)
        except Exception:
            stored = None
        self._stored_key_present = bool(stored)

        # Never disabled, never pre-filled with a mask: empty + hint is clearer.
        self.api_key_entry.delete(0, "end")
        self.api_key_entry.configure(
            state="normal",
            show="*",
            placeholder_text=(
                "Paste a new key to replace the saved one" if stored else "Enter API key..."
            ),
        )
        if hasattr(self, "api_key_saved_hint"):
            if stored:
                self.api_key_saved_hint.configure(
                    text=f"A key is saved in the OS keyring for {provider_name}.",
                    text_color=theme_manager.get_color_pair("text_muted"),
                    anchor="w",
                )
            else:
                self.api_key_saved_hint.configure(
                    text=f"No key saved for {provider_name} yet.",
                    text_color=theme_manager.get_color_pair("warning"),
                    anchor="w",
                )
        if hasattr(self, "save_key_btn"):
            self.save_key_btn.configure(state="normal")
        if hasattr(self, "forget_key_btn"):
            if stored:
                self.forget_key_btn.configure(state="normal")
                self.forget_key_btn.grid()
            else:
                self.forget_key_btn.grid_remove()

    def _on_forget_key(self) -> None:
        """Delete the stored key for the current provider."""
        provider = self.provider_combo.get() or settings.provider.name
        try:
            from tonyagent.config.keyring import delete_api_key

            delete_api_key(provider)
            self._log(f"Removed the stored key for {provider}.", "info")
        except Exception as e:
            self._log(f"Could not remove the key: {e}", "error")
        self._key_replace_mode = False
        self._init_provider()

    def _persist_provider_choice(self) -> None:
        """Save the provider/model the user picked so it survives a restart."""
        try:
            provider_name = self.provider_combo.get()
            model = self.model_combo.get()
            if provider_name:
                settings.provider.name = provider_name
            if model:
                settings.provider.model = model
            settings.save()
        except Exception:
            logger.exception("Could not persist provider choice")

    def _on_send(self, event=None) -> str:
        """Send the composer text. Returns "break" so Enter never inserts a newline."""
        text = self.input_text.get("1.0", "end-1c").strip()
        if not text or self._generating:
            return "break"

        if not self._current_provider:
            self._log("No provider configured. Please select a provider and enter API key.", "error")
            return "break"

        self.input_text.delete("1.0", "end")
        self._add_user_message(text)
        self._log(f"User: {text[:50]}...", "info")

        # The session owns the history now; the text is handed to it when the
        # background loop starts.
        self._pending_text = text
        self._start_generation()
        return "break"

    def _on_stop(self) -> None:
        """Handle stop generation."""
        if self._session is not None:
            self._session.cancel()
        self._log("Generation stopped by user", "warning")
        self._set_generating(False)

    def _init_agent_session(self) -> None:
        """Bind the UI to a headless :class:`AgentSession`.

        The session owns message history, the provider and the tool loop; this
        window only renders what the session reports. That split is what lets a
        second frontend (a Tauri sidecar) reuse the core unchanged, and it is why
        a bug in the turn loop is fixed once instead of once per UI.
        """
        from tonyagent.core.events import Event, EventType
        from tonyagent.core.session import AgentSession

        self._session = AgentSession()
        self._session.bus.subscribe(self._on_session_event)

    def _on_session_event(self, event: "Event") -> None:
        """Render one core event on the UI thread.

        Events arrive on whichever thread the turn runs on, so every handler
        is marshalled through schedule_on_ui before touching a widget.
        """
        from tonyagent.core.events import EventType

        kind = event.type
        if kind == EventType.MESSAGE_DELTA:
            schedule_on_ui(self._stream_chunk, event.payload.get("text", ""))
        elif kind == EventType.TOOL_STARTED:
            schedule_on_ui(
                self._log,
                f"Executing tool: {event.payload.get('name')}"
                f"({event.payload.get('arguments')})",
                "info",
            )
        elif kind == EventType.TOOL_COMPLETED:
            result = event.payload.get("result") or {}
            status = result.get("status", "?")
            schedule_on_ui(
                self._log,
                f"Tool {event.payload.get('name')} completed: {status}",
                "success" if str(status) == "success" else "error",
            )
        elif kind == EventType.TURN_FINISHED:
            schedule_on_ui(self._generation_finished)
        elif kind == EventType.TURN_FAILED:
            schedule_on_ui(self._generation_error, event.payload.get("message", ""))
        elif kind == EventType.CONFIRMATION_REQUESTED:
            schedule_on_ui(
                self._show_tool_confirmation, event.payload.get("request")
            )
        elif kind == EventType.LOG:
            schedule_on_ui(self._log, event.payload.get("message", ""),
                           event.payload.get("level", "info"))

    def _start_generation(self) -> None:
        """Start a turn in the background and let events drive the UI."""
        self._set_generating(True)
        self._create_ai_message_placeholder()

        def run_generation() -> None:
            # The session schedules its own coroutine; this thread only has to
            # give it a loop to run on and keep that loop alive until the turn
            # finishes.
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self._loop = loop
            try:
                if self._session.provider is None:
                    self._session.bind_provider(
                        self.provider_combo.get() or "",
                        self.model_combo.get() or "",
                    )
                self._session.send(self._pending_text)
            except Exception as e:  # noqa: BLE001
                schedule_on_ui(self._generation_error, str(e))
            finally:
                # Pending callbacks (deltas, finish) must be delivered before
                # the loop is torn down or the last tokens are lost.
                loop.call_soon(loop.stop)
                try:
                    loop.run_forever()
                finally:
                    loop.close()

        self._loop = None
        threading.Thread(target=run_generation, daemon=True).start()

    def _generate_response(self) -> None:
        """Deprecated shim.

        The turn loop now lives in :class:`AgentSession`. This exists only so
        older callers fail loudly rather than silently doing nothing.
        """
        raise NotImplementedError(
            "The turn loop moved to tonyagent.core.session.AgentSession. "
            "Call _start_generation() instead."
        )

    def _set_generating(self, generating: bool) -> None:
        """Set generating state."""
        self._generating = generating
        if generating:
            self.send_btn.grid_remove()
            self.stop_btn.grid()
            folder_manager.lock("AI generation in progress")
        else:
            self.stop_btn.grid_remove()
            self.send_btn.grid()
            folder_manager.unlock()

    def _create_ai_message_placeholder(self) -> None:
        """Create placeholder for streaming AI message."""
        container = PillFrame(self.chat_scroll, fg_color="transparent")
        container.grid(sticky="ew", padx=8, pady=4)
        container.grid_columnconfigure(0, weight=1)

        self._current_ai_message_frame = PillFrame(container, fg_color=("gray95", "gray15"))
        self._current_ai_message_frame.grid(row=0, column=0, sticky="w")
        self._current_ai_message_frame.grid_columnconfigure(0, weight=1)

        PillLabel(
            self._current_ai_message_frame,
            text="TONYAgent",
            font=("Segoe UI", 10, "bold"),
            text_color=("blue", "lightblue"),
        ).grid(row=0, column=0, padx=16, pady=(8, 0), sticky="w")

        self._current_ai_label = PillLabel(
            self._current_ai_message_frame,
            text="",
            font=("Segoe UI", 13),
            wraplength=600,
            justify="left",
        )
        self._current_ai_label.grid(row=1, column=0, padx=16, pady=12, sticky="w")
        self._message_labels.append(self._current_ai_label)

    def _stream_chunk(self, chunk: str) -> None:
        """Stream a chunk to the chat."""
        if self._current_ai_label:
            current = self._current_ai_label.cget("text")
            self._current_ai_label.configure(text=current + chunk)
            # Auto-scroll
            self.chat_scroll._parent_canvas.yview_moveto(1.0)

    def _update_token_count(self, count: int) -> None:
        """Update token count display."""
        self.token_label.configure(text=f"Tokens: ~{count}")

    def _generation_finished(self) -> None:
        """Handle generation finished."""
        self._set_generating(False)
        # The session already appended the assistant message to the history.
        self._current_ai_message_frame = None
        self._current_ai_label = None
        self._log("AI response generated", "success")

    def _generation_error(self, error: str) -> None:
        """Handle generation error.

        Provider exceptions are flattened to a bare str, which hides the useful
        part (HTTP status, response body, which model failed). Format a detailed
        message here so the user can act on it, and show it in the chat.
        """
        self._set_generating(False)
        detail = self._format_provider_error(error)
        self._log(f"Generation error: {detail}", "error")
        logger.error(f"Generation error: {detail}")
        if self._current_ai_message_frame:
            self._current_ai_label.configure(text=f"Error: {detail}")
        self._current_ai_message_frame = None
        self._current_ai_label = None

    def _format_provider_error(self, error: str) -> str:
        """Turn a raw provider exception string into something actionable."""
        text = str(error) or "Unknown error"
        hints = []
        if "401" in text or "unauthorized" in text.lower():
            hints.append(
                "The API key was rejected. Re-enter it in the API Provider panel "
                "and press Save to Keyring."
            )
        if "404" in text or "model" in text.lower() and "not found" in text.lower():
            hints.append("The model name was not recognised by the provider.")
        if "429" in text:
            hints.append("Rate limited or out of credit - wait and retry.")
        if "400" in text:
            hints.append(
                "The request was rejected. If it mentions 'tools', this model "
                "does not support function calling."
            )
        if "connection" in text.lower() or "timeout" in text.lower():
            hints.append("Network problem reaching the provider.")
        # Keep the raw text, but bounded - some APIs echo the whole body back.
        trimmed = text if len(text) <= 600 else text[:600] + " ...(truncated)"
        return f"{trimmed}\n\n" + "\n".join(hints) if hints else trimmed

    # Tool callbacks
    def _on_tool_log(self, message: str, level: str = "info") -> None:
        """Handle tool log messages."""
        self._log(f"[TOOL] {message}", level)

    def _on_tool_start(self, tool_call: ToolCall) -> None:
        """Handle tool execution start."""
        self._log(f"Executing tool: {tool_call.name}({tool_call.arguments})", "info")

    def _on_tool_result(self, tool_call: ToolCall, result: Any) -> None:
        """Handle tool execution result."""
        status = result.status.value if hasattr(result.status, 'value') else str(result.status)
        duration = f"{result.duration_ms:.0f}ms" if result.duration_ms else ""
        self._log(f"Tool {tool_call.name} completed: {status} ({duration})", 
                  "success" if str(status) == "success" else "error")

    def _show_tool_confirmation(self, confirmation: ConfirmationRequest) -> None:
        """Show confirmation dialog for destructive tool."""
        def on_confirm(confirmed: bool) -> None:
            tool_orchestrator.respond_to_confirmation(confirmation.tool_call.id, confirmed)
        
        dialog = ConfirmationDialog(self.root, confirmation, on_confirm)
        dialog.focus_set()

    #: Chat bubbles never span the full width. A long message wraps at
    #: ``_bubble_max_width``, and short ones shrink to fit their text, which is
    #: what makes the thread readable instead of a stack of full-width bands.
    _bubble_max_width = 720
    _bubble_min_width = 180

    def _bubble_wrap_width(self) -> int:
        """Pixel width a message may wrap at, derived from the chat area.

        The chat column is narrower than the scrollable frame (which has a
        scrollbar), so measuring the frame overstates the room available and
        lets text run under the scrollbar.
        """
        width = self.chat_frame.winfo_width() if hasattr(self, "chat_frame") else 0
        if width <= 1:
            width = self.chat_scroll.winfo_width()
        if width <= 1:
            return self._bubble_max_width
        # Leave room for the bubble's own padding, the outer margins, and the
        # scrollbar.
        return max(self._bubble_min_width, min(self._bubble_max_width, width - 96))

    def _add_bubble(
        self,
        text: str,
        *,
        side: str,
        author: str,
        author_color: Any,
        bg_token: str,
        text_token: str,
    ) -> None:
        """Render one chat bubble.

        ``side`` is "e" (user, right) or "w" (assistant, left). The bubble hugs
        its text instead of filling the row: the inner column deliberately has
        no ``weight``, so the frame is only as wide as the label requires.
        """
        container = PillFrame(self.chat_scroll, fg_color="transparent", corner_radius=0)
        container.grid(sticky="ew", padx=16, pady=6)
        container.grid_columnconfigure(0, weight=1)

        bubble = PillFrame(
            container,
            fg_color=theme_manager.get_color_pair(bg_token),
            corner_radius=16,
        )
        # No weight on the bubble's own column => shrink to fit the content.
        bubble.grid(row=0, column=0, sticky=side)
        bubble.grid_columnconfigure(0, weight=0)

        PillLabel(
            bubble,
            text=author,
            font=("Segoe UI", 10, "bold"),
            text_color=author_color,
        ).grid(row=0, column=0, padx=18, pady=(10, 0), sticky=side)

        body = PillLabel(
            bubble,
            text=text,
            font=("Segoe UI", 13),
            wraplength=self._bubble_wrap_width(),
            justify="left",
            text_color=theme_manager.get_color_pair(text_token),
        )
        body.grid(row=1, column=0, padx=18, pady=(2, 14), sticky=side)
        self._message_labels.append(body)

    def _add_user_message(self, text: str) -> None:
        """Add a right-aligned user bubble to the chat."""
        self._add_bubble(
            text,
            side="e",
            author="You",
            author_color=theme_manager.get_color_pair("text_muted"),
            bg_token="bubble_user",
            text_token="bubble_user_text",
        )

    def _add_ai_message(self, text: str, error: bool = False) -> None:
        """Add a left-aligned assistant bubble to the chat."""
        if error:
            self._add_bubble(
                text,
                side="w",
                author="Connection problem",
                author_color=theme_manager.get_color_pair("error"),
                bg_token="bubble_error",
                text_token="bubble_error_text",
            )
            return
        self._add_bubble(
            text,
            side="w",
            author="TONYAgent",
            author_color=theme_manager.get_color_pair("info"),
            bg_token="bubble_ai",
            text_token="bubble_ai_text",
        )


    def _on_chat_resize(self, event: Any = None) -> None:
        """Re-wrap every message when the chat area is resized."""
        if self.chat_scroll.winfo_width() <= 1 and event is None:
            return
        wrap = self._bubble_wrap_width()
        for label in self._message_labels:
            label.configure(wraplength=wrap)

    def _log(self, message: str, level: str = "info") -> None:
        """Add entry to tool log."""
        self.log_textbox.configure(state="normal")
        timestamp = datetime.now().strftime("%H:%M:%S")
        if not getattr(self, "_log_enabled", True):
            return
        self.log_textbox.insert("end", f"[{timestamp}] {message}\n", level)
        self.log_textbox.configure(state="disabled")
        self.log_textbox.see("end")
        if not hasattr(self, "_log_entries"):
            self._log_entries = []
        if self._log_enabled:
            self._log_entries.append(
                (timestamp, level, message)
            )

    def _on_log_filter(self, value: str) -> None:
        """Re-render the log for the selected category (All/File/Shell/Browser/Error)."""
        wanted = (value or "All").strip().lower()
        entries = getattr(self, "_log_entries", [])
        lines = []
        for ts, level, message in entries:
            if wanted != "all":
                low = message.lower()
                hit = (
                    (wanted == "error" and level == "error")
                    or (wanted == "file" and ("file" in low or "folder" in low))
                    or (wanted == "shell" and ("command" in low or "shell" in low or "exec" in low))
                    or (wanted == "browser" and "browser" in low)
                )
                if not hit:
                    continue
            lines.append(f"[{ts}] {message}\n")
        self.log_textbox.configure(state="normal")
        self.log_textbox.delete("1.0", "end")
        self.log_textbox.insert("end", "".join(lines) or "(no matching entries)\n", "info")
        self.log_textbox.configure(state="disabled")

    def _clear_log(self) -> None:
        """Clear tool log."""
        self._log_entries = []
        self.log_textbox.configure(state="normal")
        self.log_textbox.delete("1.0", "end")
        self.log_textbox.configure(state="disabled")

    def _export_log(self) -> None:
        """Write the tool log to a timestamped text file next to the project."""
        try:
            base = folder_manager.current_folder or Path.home()
            target = Path(base) / f"tonyagent-log-{datetime.now():%Y%m%d-%H%M%S}.txt"
            text = self.log_textbox.get("1.0", "end")
            target.write_text(text, encoding="utf-8")
            self._log(f"Log exported to {target}", "success")
        except Exception as e:
            self._log(f"Export failed: {e}", "error")

    def _open_settings(self) -> None:
        """Open the settings dialog and refresh anything it changed."""
        try:
            dialog = SettingsDialog(self.root, on_saved=self._on_settings_saved)
        except Exception as e:
            logger.exception("Failed to open settings dialog")
            self._log(f"Could not open settings: {e}", "error")
            return
        dialog.show()
        self._on_settings_saved()

    def _apply_theme_tokens(self) -> None:
        """Walk the whole widget tree and re-resolve theme colors.

        Called after a theme change so every pill frame, label, and button picks
        up the new palette instead of staying frozen in the old one.
        """
        try:
            self.root.configure(fg_color=theme_manager.get_color_pair("background"))
        except Exception:
            logger.debug("Could not theme root", exc_info=True)

        themed_count = 0
        try:
            stack = [self.root]
            while stack:
                parent = stack.pop()
                try:
                    children = parent.winfo_children()
                except Exception:
                    continue
                for child in children:
                    stack.append(child)
                    if type(child).__name__.startswith("Pill"):
                        try:
                            themed(child)
                            themed_count += 1
                        except Exception:
                            logger.debug(f"Could not theme {child}", exc_info=True)
        except Exception:
            logger.exception("Theme sweep failed")
        logger.debug(f"Themed {themed_count} widgets")

    def _on_settings_saved(self) -> None:
        """Re-sync widgets that mirror settings (provider + sandbox config)."""
        try:
            if hasattr(self, "provider_combo"):
                self.provider_combo.set(settings.provider.name or "openai")
            self._update_models()
        except Exception:
            logger.exception("Failed to refresh provider after settings save")

    def _make_collapsible(self, panel, title: str = "", expanded: bool = False, title_label=None):
        """Turn a panel's title row into a clickable show/hide toggle.

        The toggle is bound ONLY to the title label and the chevron - never to the
        panel itself. Binding the panel made a text-selection drag collapse the
        panel mid-drag, which also cancelled the drag, so the section could never
        be reopened. ``<ButtonRelease-1>`` is used instead of ``<Button-1>`` so a
        press that turns into a drag does not toggle.

        Returns a ``(set_expanded, is_expanded)`` pair. Everything below the title
        row is treated as the body, so the title stays visible.
        """
        state = {"expanded": expanded}

        arrow = PillLabel(
            panel,
            text="\u25be" if expanded else "\u25b8",
            font=("Segoe UI", 12),
            text_color=theme_manager.get_color_pair("text_muted"),
            cursor="hand2",
        )
        arrow.grid(row=0, column=1, sticky="e", padx=12, pady=(12, 8))

        def set_body(visible: bool) -> None:
            for child in panel.grid_slaves():
                if child is arrow or child is title_label:
                    continue
                if child.grid_info().get("row") == 0:
                    continue  # title row always visible
                if visible:
                    child.grid()
                else:
                    child.grid_remove()

        def toggle(_event=None) -> None:
            state["expanded"] = not state["expanded"]
            arrow.configure(text="\u25be" if state["expanded"] else "\u25b8")
            set_body(state["expanded"])

        # Bind to the header widgets only, on release, so dragging over the body
        # to select text can never collapse the section.
        for widget in (arrow, title_label):
            if widget is None:
                continue
            widget.configure(cursor="hand2")
            widget.bind("<ButtonRelease-1>", toggle, add="+")
            # Swallow the press so it does not start a text selection on the title.
            widget.bind("<Button-1>", lambda e: "break", add="+")

        if not expanded:
            set_body(False)

        def set_expanded(value: bool) -> None:
            if value != state["expanded"]:
                toggle()

        return set_expanded, lambda: state["expanded"]

    async def _iter_provider_chunks(self, tools):
        """Yield streaming chunks, normalising the providers' inconsistent contract.

        Delegates to the session, which owns this logic. It used to be
        duplicated here, and a copy-pasted provider contract is exactly how five
        providers ended up silently returning None: two copies drift.

        Kept as a thin method so existing callers and tests keep working.
        """
        provider = self._current_provider
        if self._session is not None and getattr(self._session, "provider", None) is provider:
            async for chunk in self._session._iter_chunks(tools):
                yield chunk
            return

        # Standalone fallback: no session bound (unit tests build the window
        # with __new__). Same three-shape normalisation, via a throwaway
        # session so the logic still lives in only one place.
        from tonyagent.core.events import EventBus
        from tonyagent.core.session import AgentSession

        shim = AgentSession(bus=EventBus())
        shim.provider = provider
        shim.messages = self._message_history or []
        async for chunk in shim._iter_chunks(tools):
            yield chunk

    # Sandbox control methods
    def _start_sandbox(self) -> None:
        """Start the sandbox using values from settings (single source of truth)."""
        if not folder_manager.current_folder:
            self._log("No project folder selected", "error")
            return

        backend_type = "windows" if settings.sandbox.type == "windows" else settings.sandbox.type
        self._log(f"Starting sandbox ({backend_type})...", "info")
        self.sandbox_start_btn.configure(state="disabled")
        self.sandbox_panel_status.configure(text="Status: Starting...", text_color=theme_manager.get_color_pair("warning"))

        def run_start():
            config = SandboxConfig(
                project_path=str(folder_manager.current_folder),
                type=settings.sandbox.type,
                docker_image=settings.sandbox.docker_image,
                memory_limit=settings.sandbox.memory_limit,
                cpu_limit=settings.sandbox.cpu_limit,
                timeout=settings.sandbox.timeout,
                enable_network=settings.sandbox.enable_network,
                # Container isolation (see _build_run_args).
                pids_limit=settings.sandbox.pids_limit,
                no_new_privileges=settings.sandbox.no_new_privileges,
                drop_capabilities=settings.sandbox.drop_capabilities,
                tmpfs_size_mb=settings.sandbox.tmpfs_size_mb,
                ulimit_nofile=settings.sandbox.ulimit_nofile,
                ulimit_nproc=settings.sandbox.ulimit_nproc,
                workspace_read_only=settings.sandbox.workspace_read_only,
            )
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                success = loop.run_until_complete(self._sandbox_manager.start(config))
                schedule_on_ui(self._on_sandbox_started, success)
            except Exception as e:
                logger.exception("Sandbox start failed")
                schedule_on_ui(self._on_sandbox_started, False, str(e))
            finally:
                loop.close()

        threading.Thread(target=run_start, daemon=True).start()

    def _on_sandbox_started(self, success: bool, error: str = "") -> None:
        """Handle sandbox start result (success, failure, and WSB special case)."""
        self.sandbox_start_btn.configure(state="normal")
        if success:
            self._log("Sandbox started successfully", "success")
            self._update_sandbox_ui(True)
            self._schedule_sandbox_status_update()
        else:
            backend = self._sandbox_manager.get_backend()
            hint = ""
            if backend is not None and type(backend).__name__ == "WsbSandboxBackend":
                hint = " (Windows Sandbox backend is not yet implemented - set sandbox.type to 'docker' or 'auto')"
            elif "docker" in error.lower() or not error:
                hint = " (is Docker Desktop running? Try: docker version)"
            self._log(f"Sandbox failed to start: {error}{hint}", "error")
            self._update_sandbox_ui(False)

    def _stop_sandbox(self) -> None:
        """Stop the sandbox."""
        self._log("Stopping sandbox...", "info")
        self.sandbox_stop_btn.configure(state="disabled")

        def run_stop():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(self._sandbox_manager.stop())
                schedule_on_ui(self._on_sandbox_stopped)
            except Exception as e:
                schedule_on_ui(self._log, f"Error stopping sandbox: {e}", "error")
                schedule_on_ui(self._on_sandbox_stopped)
            finally:
                loop.close()

        threading.Thread(target=run_stop, daemon=True).start()

    def _on_sandbox_stopped(self) -> None:
        """Handle sandbox stop result."""
        self._cancel_sandbox_status_update()
        self.sandbox_stop_btn.configure(state="normal")
        self._log("Sandbox stopped", "info")
        self._update_sandbox_ui(False)
        if self._restart_pending:
            self._restart_pending = False
            self.root.after(500, self._start_sandbox)

    def _restart_sandbox(self) -> None:
        """Restart the sandbox, but only once the stop has actually finished."""
        self._restart_pending = True
        self.sandbox_restart_btn.configure(state="disabled")
        self._stop_sandbox()

    def _on_trust_toggle(self) -> None:
        """Wire the trust checkbox to the orchestrator (session-only)."""
        from tonyagent.tools import tool_orchestrator as _orch

        trusted = bool(self._trust_var.get())
        current = folder_manager.current_folder
        if current is not None:
            _orch.set_trusted(str(current), trusted)
            # The session deliberately does not log this (the protocol replies
            # instead), so the UI logs it for the person at the keyboard.
            self._log(
                f"Trust {'enabled' if trusted else 'disabled'} for {current.name}",
                "warning" if trusted else "info",
            )
        elif trusted:
            self._trust_var.set(False)
            self._log("Select a project folder before trusting it", "error")

    def _update_sandbox_ui(self, running: bool) -> None:
        """Update sandbox UI based on running state."""
        self._sandbox_running = running
        if running:
            self.sandbox_panel_status.configure(text="Status: Running", text_color=theme_manager.get_color_pair("success"))
            self.sandbox_start_btn.configure(state="disabled")
            self.sandbox_stop_btn.configure(state="normal")
            self.sandbox_restart_btn.configure(state="normal")
            self.sandbox_status.configure(text="Sandbox: Running", text_color=theme_manager.get_color_pair("success"))
        else:
            self.sandbox_panel_status.configure(text="Status: Stopped", text_color=theme_manager.get_color_pair("error"))
            self.sandbox_start_btn.configure(state="normal")
            self.sandbox_stop_btn.configure(state="disabled")
            self.sandbox_restart_btn.configure(state="disabled")
            self.sandbox_cpu_label.configure(text="CPU: --")
            self.sandbox_mem_label.configure(text="Memory: --")
            self.sandbox_status.configure(text="Sandbox: Stopped", text_color=theme_manager.get_color_pair("error"))

    def _schedule_sandbox_status_update(self) -> None:
        """Schedule periodic sandbox status updates (single timer chain)."""
        self._cancel_sandbox_status_update()
        self._update_sandbox_resource_usage()
        self._sandbox_poll_id = self.root.after(5000, self._schedule_sandbox_status_update)

    def _cancel_sandbox_status_update(self) -> None:
        """Stop the sandbox status timer chain."""
        if self._sandbox_poll_id is not None:
            try:
                self.root.after_cancel(self._sandbox_poll_id)
            except Exception:
                pass
            self._sandbox_poll_id = None

    def _update_sandbox_resource_usage(self) -> None:
        """Poll sandbox CPU/memory on a worker thread (never block the Tk loop)."""
        backend = self._sandbox_manager.get_backend()
        if backend is None or backend.status != SandboxStatus.RUNNING:
            return
        get_stats = getattr(backend, "get_stats", None)
        if get_stats is None:
            return

        def run_stats() -> None:
            import asyncio

            try:
                stats = asyncio.run(get_stats())
            except Exception:
                stats = None
            schedule_on_ui(self._apply_sandbox_stats, backend, stats)

        threading.Thread(target=run_stats, daemon=True).start()

    def _apply_sandbox_stats(self, backend, stats: dict | None) -> None:
        """Render stats on the UI thread, discarding results from a dead sandbox."""
        if not stats or self._sandbox_manager.get_backend() is not backend:
            return
        if backend.status != SandboxStatus.RUNNING:
            return
        try:
            cpu_percent = self._calculate_cpu_percent(stats)
            mem_usage = stats["memory_stats"].get("usage", 0)
            mem_limit = stats["memory_stats"].get("limit", 0)
            mem_percent = (mem_usage / mem_limit * 100) if mem_limit > 0 else 0
            self.sandbox_cpu_label.configure(text=f"CPU: {cpu_percent:.1f}%")
            self.sandbox_mem_label.configure(
                text=f"Memory: {mem_usage / 1024 / 1024:.0f}MB / {mem_limit / 1024 / 1024:.0f}MB ({mem_percent:.1f}%)"
            )
        except Exception:
            self.sandbox_cpu_label.configure(text="CPU: --")
            self.sandbox_mem_label.configure(text="Memory: --")

    def _calculate_cpu_percent(self, stats: dict) -> float:
        """Calculate CPU percentage from Docker stats."""
        cpu_delta = stats["cpu_stats"]["cpu_usage"]["total_usage"] - stats["precpu_stats"]["cpu_usage"]["total_usage"]
        system_delta = stats["cpu_stats"]["system_cpu_usage"] - stats["precpu_stats"]["system_cpu_usage"]
        percpu = stats["cpu_stats"]["cpu_usage"].get("percpu_usage") or [0]
        if system_delta > 0 and cpu_delta > 0:
            return (cpu_delta / system_delta) * len(percpu) * 100
        return 0.0