"""One-shot fix script for TONYAgent GUI layout + code issues.

Applies every patch idempotently, then syntax-checks the result.
Run:  python fix_gui_layout.py
"""

from __future__ import annotations

import ast
import io
import sys
from pathlib import Path

TARGET = Path(__file__).parent / "src" / "tonyagent" / "ui" / "views" / "main_window.py"

PATCHES: list[tuple[str, str]] = []


def patch(old: str, new: str) -> None:
    PATCHES.append((old, new))


# ---------------------------------------------------------------- P1 imports
patch(
    """import asyncio
import json
import threading
import uuid
from typing import Any
""",
    """import asyncio
import json
import threading
import uuid
from datetime import datetime
from typing import Any
""",
)

patch(
    """    PillScrollableFrame,
    PillLabel,
    ToolTip,
)""",
    """    PillScrollableFrame,
    PillLabel,
    PillTextbox,
    ToolTip,
)""",
)

patch(
    """from tonyagent.providers import ProviderFactory, ChatMessage, ToolSchema, ToolChoice, ChatCompletionChunk
from tonyagent.tools import tool_orchestrator, ToolCall, ConfirmationRequest, ALL_SCHEMAS
from tonyagent.tools.orchestrator import tool_orchestrator
from tonyagent.ui.views.confirm_dialog import ConfirmationDialog
from tonyagent.utils.threading import run_async, schedule_on_ui
from tonyagent.sandbox import SandboxManager, SandboxConfig
class MainWindow:""",
    """from tonyagent.providers import ProviderFactory, ChatMessage, ToolSchema, ToolChoice
from tonyagent.tools import tool_orchestrator, ToolCall, ConfirmationRequest, ALL_SCHEMAS
from tonyagent.ui.views.confirm_dialog import ConfirmationDialog
from tonyagent.utils.threading import schedule_on_ui
from tonyagent.sandbox import SandboxManager, SandboxConfig


class MainWindow:""",
)

# ------------------------------------------------------- P2 init new fields
patch(
    """        self._current_ai_message_frame = None
        self._current_ai_label = None
        self._sandbox_manager = SandboxManager()""",
    """        self._current_ai_message_frame = None
        self._current_ai_label = None
        self._message_labels: list[ctk.CTkLabel] = []
        self._sandbox_poll_id: str | None = None
        self._docker_client = None
        self._sandbox_manager = SandboxManager()""",
)

# ---------------------------------------- P3 root grid: header/содержимое/status
patch(
    """        self.root.grid_columnconfigure(0, weight=0, minsize=320)  # Sidebar
        self.root.grid_columnconfigure(1, weight=1)  # Chat area
        self.root.grid_rowconfigure(0, weight=1)
        self.root.grid_rowconfigure(1, weight=0)  # Status bar""",
    """        # 3 rows: 0 = header (fixed), 1 = sidebar + chat (expanding), 2 = status bar
        self.root.grid_columnconfigure(0, weight=0, minsize=320)  # Sidebar
        self.root.grid_columnconfigure(1, weight=1)  # Chat area
        self.root.grid_rowconfigure(0, weight=0)  # Header
        self.root.grid_rowconfigure(1, weight=1)  # Sidebar + chat area
        self.root.grid_rowconfigure(2, weight=0)  # Status bar""",
)

# ---------------------------------------------------- P4 sidebar goes row 1
patch(
    """        self.sidebar = PillScrollableFrame(self.root, width=320, corner_radius=0)
        self.sidebar.grid(row=0, column=0, sticky="nsew", padx=0, pady=0)""",
    """        self.sidebar = PillScrollableFrame(self.root, width=320, corner_radius=0)
        self.sidebar.grid(row=1, column=0, sticky="nsew", padx=0, pady=0)""",
)

# ----------------------------------- P5 only the tool-log panel may expand
patch(
    """        # Configure row weights for proper scrolling
        self.sidebar.grid_rowconfigure(3, weight=1)""",
    """        # Only the tool-log panel expands; the sandbox panel keeps its natural height
        self.sidebar.grid_rowconfigure(2, weight=1)""",
)

patch(
    """        panel.grid_rowconfigure(2, weight=1)
        self.sidebar.grid_rowconfigure(2, weight=1)""",
    """        panel.grid_rowconfigure(2, weight=1)""",
)

# ----------------------------------------------------- P6 chat goes row 1
patch(
    """        self.chat_frame = PillFrame(self.root, corner_radius=0)
        self.chat_frame.grid(row=0, column=1, sticky="nsew", padx=0, pady=0)""",
    """        self.chat_frame = PillFrame(self.root, corner_radius=0)
        self.chat_frame.grid(row=1, column=1, sticky="nsew", padx=0, pady=0)""",
)

# --------------------------- P7 log textbox: PillTextbox + one-time tag setup
patch(
    """        self.log_textbox = ctk.CTkTextbox(
            panel,
            width=280,
            height=200,
            corner_radius=8,
            font=("Consolas", 11),
            wrap="word",
            border_width=1,
            activate_scrollbars=True,
        )
        self.log_textbox.grid(row=2, column=0, sticky="nsew", padx=12, pady=(0, 8))
        self.log_textbox.configure(state="disabled")""",
    """        self.log_textbox = PillTextbox(
            panel,
            width=280,
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
        self.log_textbox.tag_config("error", foreground="red")""",
)

# ------------- P8 composer: no clamped height (this clipped the Send button)
patch(
    """        # Conversation history
        self.chat_scroll = PillScrollableFrame(self.chat_frame)
        self.chat_scroll.grid(row=0, column=0, sticky="nsew", padx=16, pady=16)
        self.chat_scroll.grid_columnconfigure(0, weight=1)

        # Input composer
        self.composer_frame = PillFrame(self.chat_frame, height=120)
        self.composer_frame.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 16))
        self.composer_frame.grid_propagate(False)
        self.composer_frame.grid_columnconfigure(0, weight=1)

        # Input textbox
        self.input_text = ctk.CTkTextbox(
            self.composer_frame,
            height=80,
            corner_radius=12,
            font=("Segoe UI", 13),
            wrap="word",
            border_width=1,
            activate_scrollbars=True,
        )
        self.input_text.grid(row=0, column=0, sticky="ew", padx=12, pady=12)
        self.input_text.bind("<Return>", self._on_send)
        self.input_text.bind("<Shift-Return>", lambda e: None)  # Allow newline""",
    """        # Conversation history
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
        self.input_text.bind("<Shift-Return>", lambda e: None)  # Allow newline""",
)

patch(
    """        btn_frame = PillFrame(self.composer_frame, fg_color="transparent", height=40)""",
    """        btn_frame = PillFrame(self.composer_frame, fg_color="transparent")""",
)

# --------------------------------------- P9 status bar: row 2 + right pinned
patch(
    """        self.status_bar = PillFrame(self.root, corner_radius=0, height=30)
        self.status_bar.grid(row=1, column=0, columnspan=2, sticky="ew", padx=0, pady=0)
        self.status_bar.grid_propagate(False)
        self.status_bar.grid_columnconfigure(1, weight=1)""",
    """        self.status_bar = PillFrame(self.root, corner_radius=0, height=30)
        self.status_bar.grid(row=2, column=0, columnspan=2, sticky="ew", padx=0, pady=0)
        self.status_bar.grid_propagate(False)
        # Let column 2 soak up the spare width so the version label stays pinned right
        self.status_bar.grid_columnconfigure(0, weight=0)
        self.status_bar.grid_columnconfigure(1, weight=0)
        self.status_bar.grid_columnconfigure(2, weight=1)
        self.status_bar.grid_columnconfigure(3, weight=0)""",
)

patch(
    """        self.model_label.grid(row=0, column=1, padx=16, pady=4)""",
    """        self.model_label.grid(row=0, column=1, padx=16, pady=4, sticky="w")""",
)

patch(
    """        self.sandbox_status.grid(row=0, column=2, padx=16, pady=4)""",
    """        self.sandbox_status.grid(row=0, column=2, padx=16, pady=4, sticky="w")""",
)

patch(
    """        self.version_label.grid(row=0, column=3, padx=16, pady=4)""",
    """        self.version_label.grid(row=0, column=3, padx=16, pady=4, sticky="e")""",
)

# ------------------------------------- P10 theme toggle resolves 'system' mode
patch(
    """    def _on_theme_change(self, mode: str) -> None:
        \"\"\"Handle theme change.\"\"\"
        icon = "\U0001F319" if mode == "light" else "\u2600\ufe0f"
        self.theme_btn.configure(text=icon)""",
    """    def _on_theme_change(self, mode: str) -> None:
        \"\"\"Handle theme change (resolve "system" to the real appearance).\"\"\"
        actual = theme_manager.get_actual_theme()
        self.theme_btn.configure(text="\U0001F319" if actual == "light" else "\u2600\ufe0f")""",
)

# ------------------------ P11 Enter must not also insert a newline / re-entry
patch(
    """    def _on_send(self, event=None) -> None:
        \"\"\"Handle send message.\"\"\"
        text = self.input_text.get("1.0", "end-1c").strip()
        if not text:
            return

        if not self._current_provider:
            self._log("No provider configured. Please select a provider and enter API key.", "error")
            return

        self.input_text.delete("1.0", "end")""",
    """    def _on_send(self, event=None) -> str:
        \"\"\"Send the composer text. Returns "break" so Enter never inserts a newline.\"\"\"
        text = self.input_text.get("1.0", "end-1c").strip()
        if not text or self._generating:
            return "break"

        if not self._current_provider:
            self._log("No provider configured. Please select a provider and enter API key.", "error")
            return "break"

        self.input_text.delete("1.0", "end")""",
)

patch(
    """        # Start generation
        self._start_generation()""",
    """        # Start generation
        self._start_generation()
        return "break\"""",
)

# ------------------------------------------- P12 log(): no re-tagging per call
patch(
    """        timestamp = __import__("datetime").datetime.now().strftime("%H:%M:%S")
        color_tag = level
        self.log_textbox.insert("end", f"[{timestamp}] {message}\\n", color_tag)
        self.log_textbox.configure(state="disabled")
        self.log_textbox.see("end")

        # Configure tags - use single color strings that work in both light/dark modes
        self.log_textbox.tag_config("info", foreground="gray")
        self.log_textbox.tag_config("success", foreground="green")
        self.log_textbox.tag_config("warning", foreground="orange")
        self.log_textbox.tag_config("error", foreground="red")""",
    """        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_textbox.insert("end", f"[{timestamp}] {message}\\n", level)
        self.log_textbox.configure(state="disabled")
        self.log_textbox.see("end")""",
)

# ------------------------------------- P13 stop() was defined twice (dedupe)
patch(
    """    def _on_stop(self) -> None:
        \"\"\"Handle stop generation.\"\"\"
        if self._cancel_token:
            self._cancel_token.set()
        self._log("Generation stopped by user", "warning")
        self._set_generating(False)

    def _set_generating(self, generating: bool) -> None:""",
    """    def _set_generating(self, generating: bool) -> None:""",
)

# ---------------------- P14 assistant reply was appended to history twice
patch(
    """        self._set_generating(False)
        if self._current_ai_message_frame:
            # Add to history
            content = self._current_ai_label.cget("text")
            if content:
                self._message_history.append(ChatMessage(role="assistant", content=content))
        self._current_ai_message_frame = None""",
    """        self._set_generating(False)
        # _generate_response() already appended the assistant message to the history
        self._current_ai_message_frame = None""",
)

# ------------------- P15 bubbles: right-aligned user, responsive wrap length
patch(
    """        self._current_ai_message_frame = PillFrame(self.chat_scroll, fg_color=("gray95", "gray15"))
        self._current_ai_message_frame.grid(sticky="ew", padx=8, pady=4)
        self._current_ai_message_frame.grid_columnconfigure(0, weight=1)""",
    """        container = PillFrame(self.chat_scroll, fg_color="transparent")
        container.grid(sticky="ew", padx=8, pady=4)
        container.grid_columnconfigure(0, weight=1)

        self._current_ai_message_frame = PillFrame(container, fg_color=("gray95", "gray15"))
        self._current_ai_message_frame.grid(row=0, column=0, sticky="w")
        self._current_ai_message_frame.grid_columnconfigure(0, weight=1)""",
)

patch(
    """        self._current_ai_label.grid(row=1, column=0, padx=16, pady=12, sticky="w")""",
    """        self._current_ai_label.grid(row=1, column=0, padx=16, pady=12, sticky="w")
        self._message_labels.append(self._current_ai_label)""",
)

patch(
    """    def _add_user_message(self, text: str) -> None:
        \"\"\"Add user message to chat.\"\"\"
        msg_frame = PillFrame(self.chat_scroll, fg_color=("gray90", "gray20"))
        msg_frame.grid(sticky="ew", padx=8, pady=4)
        msg_frame.grid_columnconfigure(0, weight=1)

        PillLabel(
            msg_frame,
            text=text,
            font=("Segoe UI", 13),
            wraplength=600,
            justify="right",
        ).grid(row=0, column=0, padx=16, pady=12, sticky="e")

        PillLabel(
            msg_frame,
            text="You",
            font=("Segoe UI", 10),
            text_color=("gray50", "gray60"),
        ).grid(row=1, column=0, padx=16, pady=(0, 8), sticky="e")""",
    """    def _add_user_message(self, text: str) -> None:
        \"\"\"Add a right-aligned user bubble to the chat.\"\"\"
        container = PillFrame(self.chat_scroll, fg_color="transparent")
        container.grid(sticky="ew", padx=8, pady=4)
        container.grid_columnconfigure(0, weight=1)

        msg_frame = PillFrame(container, fg_color=("gray90", "gray20"))
        msg_frame.grid(row=0, column=0, sticky="e")
        msg_frame.grid_columnconfigure(0, weight=1)

        body = PillLabel(
            msg_frame,
            text=text,
            font=("Segoe UI", 13),
            wraplength=600,
            justify="left",
        )
        body.grid(row=0, column=0, padx=16, pady=12, sticky="e")
        self._message_labels.append(body)

        PillLabel(
            msg_frame,
            text="You",
            font=("Segoe UI", 10),
            text_color=("gray50", "gray60"),
        ).grid(row=1, column=0, padx=16, pady=(0, 8), sticky="e")""",
)

patch(
    """    def _add_ai_message(self, text: str) -> None:
        \"\"\"Add AI message to chat.\"\"\"
        msg_frame = PillFrame(self.chat_scroll, fg_color=("gray95", "gray15"))
        msg_frame.grid(sticky="ew", padx=8, pady=4)
        msg_frame.grid_columnconfigure(0, weight=1)""",
    """    def _add_ai_message(self, text: str) -> None:
        \"\"\"Add a left-aligned assistant bubble to the chat.\"\"\"
        container = PillFrame(self.chat_scroll, fg_color="transparent")
        container.grid(sticky="ew", padx=8, pady=4)
        container.grid_columnconfigure(0, weight=1)

        msg_frame = PillFrame(container, fg_color=("gray95", "gray15"))
        msg_frame.grid(row=0, column=0, sticky="w")
        msg_frame.grid_columnconfigure(0, weight=1)""",
)

patch(
    """        PillLabel(
            msg_frame,
            text=text,
            font=("Segoe UI", 13),
            wraplength=600,
            justify="left",
        ).grid(row=1, column=0, padx=16, pady=12, sticky="w")""",
    """        body = PillLabel(
            msg_frame,
            text=text,
            font=("Segoe UI", 13),
            wraplength=600,
            justify="left",
        )
        body.grid(row=1, column=0, padx=16, pady=12, sticky="w")
        self._message_labels.append(body)

    def _on_chat_resize(self, event: Any = None) -> None:
        \"\"\"Re-wrap every message when the chat area is resized.\"\"\"
        width = self.chat_scroll.winfo_width()
        if width <= 1 and event is not None:
            width = event.width
        if width <= 1:
            return
        wrap = max(240, width - 90)
        for label in self._message_labels:
            label.configure(wraplength=wrap)""",
)

# --------------------------------------- P16 sandbox: timer chain + docker reuse
patch(
    """        def run_start():
            import asyncio
            config = SandboxConfig(""",
    """        def run_start():
            config = SandboxConfig(""",
)

patch(
    """            finally:
                loop.close()

        import threading
        threading.Thread(target=run_start, daemon=True).start()""",
    """            finally:
                loop.close()

        threading.Thread(target=run_start, daemon=True).start()""",
)

patch(
    """        def run_stop():
            import asyncio
            loop = asyncio.new_event_loop()""",
    """        def run_stop():
            loop = asyncio.new_event_loop()""",
)

patch(
    """            finally:
                loop.close()

        import threading
        threading.Thread(target=run_stop, daemon=True).start()""",
    """            finally:
                loop.close()

        threading.Thread(target=run_stop, daemon=True).start()""",
)

patch(
    """    def _on_sandbox_stopped(self) -> None:
        \"\"\"Handle sandbox stop result.\"\"\"
        self.sandbox_stop_btn.configure(state="normal")""",
    """    def _on_sandbox_stopped(self) -> None:
        \"\"\"Handle sandbox stop result.\"\"\"
        self._cancel_sandbox_status_update()
        self.sandbox_stop_btn.configure(state="normal")""",
)

patch(
    """    def _schedule_sandbox_status_update(self) -> None:
        \"\"\"Schedule periodic sandbox status updates.\"\"\"
        self._update_sandbox_resource_usage()
        self.root.after(5000, self._schedule_sandbox_status_update)""",
    """    def _schedule_sandbox_status_update(self) -> None:
        \"\"\"Schedule periodic sandbox status updates (single timer chain).\"\"\"
        self._cancel_sandbox_status_update()
        self._update_sandbox_resource_usage()
        self._sandbox_poll_id = self.root.after(5000, self._schedule_sandbox_status_update)

    def _cancel_sandbox_status_update(self) -> None:
        \"\"\"Stop the sandbox status timer chain.\"\"\"
        if self._sandbox_poll_id is not None:
            try:
                self.root.after_cancel(self._sandbox_poll_id)
            except Exception:
                pass
            self._sandbox_poll_id = None""",
)

patch(
    """        backend = self._sandbox_manager.get_backend()
        if backend and backend.status == "running":
            try:
                import docker
                client = docker.from_env()
                container = client.containers.get(backend._container_id)
                stats = container.stats(stream=False)
                cpu_percent = self._calculate_cpu_percent(stats)
                mem_usage = stats["memory_stats"].get("usage", 0)
                mem_limit = stats["memory_stats"].get("limit", 0)
                mem_percent = (mem_usage / mem_limit * 100) if mem_limit > 0 else 0
                self.sandbox_cpu_label.configure(text=f"CPU: {cpu_percent:.1f}%")
                self.sandbox_mem_label.configure(text=f"Memory: {mem_usage / 1024 / 1024:.0f}MB / {mem_limit / 1024 / 1024:.0f}MB ({mem_percent:.1f}%)")
            except Exception:
                self.sandbox_cpu_label.configure(text="CPU: --")
                self.sandbox_mem_label.configure(text="Memory: --")""",
    """        backend = self._sandbox_manager.get_backend()
        if backend is None or backend.status != "running":
            return
        try:
            import docker

            if self._docker_client is None:
                self._docker_client = docker.from_env()
            container_id = getattr(backend, "container_id", None) or getattr(backend, "_container_id", None)
            if not container_id:
                return
            container = self._docker_client.containers.get(container_id)
            stats = container.stats(stream=False)
            if not stats:
                return
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
            self.sandbox_mem_label.configure(text="Memory: --")""",
)

patch(
    """        if system_delta > 0 and cpu_delta > 0:
            return (cpu_delta / system_delta) * len(stats["cpu_stats"]["cpu_usage"]["percpu_usage"]) * 100
        return 0.0""",
    """        percpu = stats["cpu_stats"]["cpu_usage"].get("percpu_usage") or [0]
        if system_delta > 0 and cpu_delta > 0:
            return (cpu_delta / system_delta) * len(percpu) * 100
        return 0.0""",
)


def main() -> int:
    source = TARGET.read_text(encoding="utf-8")
    applied = skipped = failed = 0

    for index, (old, new) in enumerate(PATCHES, start=1):
        if old in source:
            source = source.replace(old, new, 1)
            applied += 1
        elif new in source:
            skipped += 1
        else:
            failed += 1
            sys.stdout.write(f"  PATCH {index} MATCH FAILED:\n{io.StringIO(old).getvalue()[:160]}\n")

    if failed:
        sys.stdout.write(f"aborted: {failed} patch(es) did not match, nothing written\n")
        return 1

    ast.parse(source)
    TARGET.write_text(source, encoding="utf-8")

    sys.stdout.write(f"applied={applied} already_present={skipped} failed={failed}\n")
    sys.stdout.write("syntax: OK\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
