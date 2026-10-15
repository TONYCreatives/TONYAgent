"""The Textual application: the window's layout, in a terminal.

**This is a third frontend, not a rewrite.** `tonyagent.window` draws the same
core in a webview and `tonyagent.cli.repl` draws it in lines; this draws it
with widgets. The core, its 41 tools, its gates and its JSONL protocol are
untouched by any of them, and that is the property worth protecting -- the
protocol is the contract, and a frontend is replaceable precisely because
nothing above it knows what a widget is.

**The layout answers to `tokens.css`, not to a terminal application's habits.**
The window puts the transcript, composer and status bar on one measure and
floats the conversation list as an overlay rather than a column, so opening it
does not reflow the transcript. A terminal has no overlay, so the sidebar here
is a real column -- and it is hidden on narrow terminals rather than squeezing
the messages, because the window's own comment says a column that is always
there is transcript gone before the user has said anything.

**Threading is the one thing that had to be got right.** The core's reader
thread is where every event arrives, and Textual's event loop is not that
thread. Touching a widget from the wrong thread is the kind of bug that shows
up as a corrupted screen hours later, so every update crosses through
`call_from_thread`, and nothing in this file draws from the reader thread
directly.
"""

from __future__ import annotations

import threading
from typing import Any, ClassVar, Optional

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Footer, Static, TextArea

from tonyagent.cli import theme
from tonyagent.cli.client import CoreClient, CoreError
from tonyagent.cli.render import _argument_summary, _result_summary
from tonyagent.cli.widgets import Sidebar, ToolCall, ToolLine, Turn, TurnFooter

#: Below this many columns the sidebar is dropped rather than narrowed.
#:
#: The window's `--measure` is 760px; at roughly 8px per character that is
#: about 95 columns of readable text. A 32-column sidebar plus a 95-column
#: transcript needs 127, so anything under that cannot have both without the
#: transcript becoming a column too narrow to read a line of code in.
SIDEBAR_MIN_WIDTH = 108

#: A turn may legitimately run for many minutes.
TURN_TIMEOUT_S = 3600.0


class TonyApp(App[None]):
    """TONYAgent, drawn as widgets."""

    CSS = theme.build_css()
    TITLE = "TONYAgent"

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("ctrl+c", "cancel", "cancel", show=True, priority=True),
        Binding("ctrl+d", "quit", "quit", show=True, priority=True),
        Binding("ctrl+q", "quit", "quit", show=False),
        Binding("ctrl+p", "commands", "commands", show=True),
    ]

    def __init__(self, client: CoreClient, initial_prompt: str = "") -> None:
        super().__init__()
        self.client = client
        self.initial_prompt = initial_prompt
        self.state: dict[str, Any] = {}
        self.turn: Optional[Turn] = None
        self._turn_box: Optional[Vertical] = None
        self._answer_widget: Optional[Static] = None
        self._streaming = False
        #: The id of the confirmation or question the turn is suspended on.
        #: Empty means the composer sends turns rather than answers.
        self._pending_dialog = ""

    # -- layout --------------------------------------------------------------

    def compose(self) -> ComposeResult:
        with Horizontal(id="body"):
            with VerticalScroll(id="transcript"):
                yield Static(self._welcome(), id="intro")
            yield Sidebar(id="sidebar")
        yield Static("", id="status")
        yield TextArea(id="composer")
        yield Footer()

    def on_resize(self) -> None:
        self._apply_width()

    def _apply_width(self) -> None:
        """Drop the sidebar on a terminal too narrow to carry it.

        The window hides its panels rather than letting them squeeze the
        transcript, and this is the same decision at a different size.
        """
        self.query_one("#sidebar", Sidebar).display = self.size.width >= SIDEBAR_MIN_WIDTH

    # -- the transcript ------------------------------------------------------

    def _welcome(self) -> str:
        """The opening panel, as a Markdown widget like every other message.

        Handing back markup from `render()` would leave the asterisks on
        screen, because markup is a Rich feature and this returns a `Text`.
        """
        return (
            f"TONYAgent {self._version()} · terminal\n\n"
            "ctrl+p commands · ctrl+c cancel · ctrl+d quit"
        )

    def on_mount(self) -> None:
        self.client.on_event = self._on_core_event
        self._apply_width()
        self.set_interval(0.5, self._poll_state)
        self.call_after_refresh(self._start)
        # The welcome is Markdown so it renders like a message rather than as
        # literal `**`, which is what the first version printed.
        from rich.markdown import Markdown

        self.query_one("#intro", Static).update(Markdown(self._welcome()))

    def _version(self) -> str:
        try:
            from tonyagent import __version__

            return __version__
        except Exception:  # noqa: BLE001 - a version string is not worth a crash
            return "0.0.0"

    def _begin_turn(self, text: str) -> None:
        """Fence a new turn and make room for its output."""
        transcript = self.query_one("#transcript", VerticalScroll)
        self.turn = Turn(text=text)
        self._turn_box = Vertical(classes="turn turn-rule")
        transcript.mount(self._turn_box)
        # No id: a turn can open several messages as tools split it, and a
        # repeated id is a DuplicateIds at mount time rather than a widget.
        self._answer_widget = Static("")
        self._turn_box.mount(self._answer_widget)
        transcript.scroll_end(animate=False)
        self._streaming = True

    def _close_open_message(self) -> None:
        """Freeze whatever has been streamed into a finished message widget."""
        if self.turn is None or self._answer_widget is None:
            return
        from rich.markdown import Markdown

        # `take_answer`, not the whole buffer: the text already rendered into
        # this widget must not be rendered again into the next one.
        frozen = self.turn.take_answer()
        if not frozen.strip():
            return
        self._answer_widget.update(Markdown(frozen.strip()))

    def _end_turn(self) -> None:
        # Freeze first, then stop streaming: the frozen widget is Markdown,
        # while `_render_answer` would write the same text as a plain stream.
        self._close_open_message()
        self._streaming = False
        if self.turn is None or self._turn_box is None:
            return
        # Outside the fence, not inside it. The rule marks the turn's body; a
        # footer inside it reads as part of the answer, and the padding it
        # inherits pushes the metadata off the measure the transcript sets.
        transcript = self.query_one("#transcript", VerticalScroll)
        transcript.mount(
            TurnFooter(
                self.turn,
                mode=str(self.state.get("mode", "")),
                model=str(self.state.get("model", "")),
            ),
            after=self._turn_box,
        )
        transcript.scroll_end(animate=False)

    def _render_answer(self) -> None:
        """Draw the assistant's text, formatted once it is complete.

        Markdown is rendered on completion rather than per delta: a ``**bold**``
        marker opened on one chunk and closed thirty tokens later cannot be
        drawn until it closes, and a renderer that guessed would flash a stray
        asterisk on screen. Tokens are still visible while they stream -- as
        plain text -- so the turn never looks stalled.
        """
        if self.turn is None or self._answer_widget is None:
            return
        body = self.turn.answer.lstrip("\n")
        if self._streaming:
            self._answer_widget.update(body)
            return
        from rich.markdown import Markdown

        # `Markdown` rather than markup: the window renders assistant text as
        # markdown (`app/src/styles/markdown.css`), and a terminal that showed
        # `**Fixed.**` with its asterisks would be showing a different document.
        self._answer_widget.update(Markdown(body))

    # -- events from the core, on its reader thread --------------------------

    def _on_core_event(self, kind: str, payload: dict[str, Any]) -> None:
        """Every frame arrives here, on the core's reader thread.

        Nothing is drawn in this method. `call_from_thread` is what crosses onto
        Textual's loop, and doing the drawing after the hop keeps the reader
        thread from ever touching a widget.
        """
        self.call_from_thread(self._apply_core_event, kind, payload)

    def _apply_core_event(self, kind: str, payload: dict[str, Any]) -> None:
        turn, box = self.turn, self._turn_box
        if turn is None or box is None:
            return

        if kind == "message.delta":
            turn.on_delta(payload)
            self._render_answer()
        elif kind == "tool.started":
            call = ToolCall(
                id=str(payload.get("id", "")),
                name=str(payload.get("name", "?")),
                summary=_argument_summary(
                    str(payload.get("name", "")), payload.get("arguments")
                ),
            )
            turn.tools.append(call)
            # **Close the open message before the tool line.**
            #
            # The answer is one accumulating widget, so a tool arriving
            # mid-message has nowhere to go that is both after what was said
            # and before what comes next. Inserting it at the end reorders the
            # transcript to read as though the agent called the tool *after*
            # answering; inserting it at the top reorders it the other way.
            #
            # So the open message is frozen into its own widget and a fresh one
            # starts after the tool. That is the same thing the window does
            # when a tool card splits an assistant message, and it is what
            # makes arrival order the order on screen.
            self._close_open_message()
            box.mount(ToolLine(call))
            self._answer_widget = Static("")
            box.mount(self._answer_widget)
        elif kind in ("tool.completed", "tool.failed"):
            call = turn.tool_by_id(str(payload.get("id", "")))
            if call is None:
                # The reader may have dropped a frame; a crash here would be a
                # worse bug than a line that stays spinning.
                return
            call.done = kind == "tool.completed"
            call.failed = kind == "tool.failed"
            call.result = _result_summary(payload)
            line = self._line_for(call)
            if line is not None:
                line.refresh_line()
        elif kind == "turn.finished":
            self._end_turn()
        elif kind == "turn.failed":
            message = str(payload.get("error") or "the turn failed")
            self._end_turn()
            self._notice(message, "error")
        elif kind == "confirmation.requested":
            self._open_dialog(
                str(payload.get("id", "")), str(payload.get("name", "confirm"))
            )
        elif kind == "user.asked":
            self._open_dialog(
                str(payload.get("id", "")),
                str(payload.get("question") or "The agent is asking"),
            )

    def _line_for(self, call: ToolCall) -> Optional[ToolLine]:
        if self._turn_box is None:
            return None
        for widget in self._turn_box.query(ToolLine):
            if widget.call is call:
                return widget
        return None

    def _open_dialog(self, call_id: str, question: str) -> None:
        """Ask the blocking question in the composer itself.

        A modal would be the wrong shape here: the turn is suspended waiting,
        and a dialog over it would hide the transcript the decision is about.
        The composer already takes input, so the question goes there and the
        transcript stays readable underneath.

        ``call_id`` of `"confirm"` marks a yes/no rather than an open question,
        so the answer can be routed without re-reading the event stream.
        """
        composer = self.query_one("#composer", TextArea)
        composer.border_title = "waiting for you"
        composer.placeholder = question
        composer.focus()
        self._pending_dialog = call_id or "confirm"

    def _close_dialog(self) -> None:
        composer = self.query_one("#composer", TextArea)
        composer.border_title = ""
        composer.placeholder = ""
        self._pending_dialog = ""

    def _notice(self, message: str, style: str = "") -> None:
        text = f"[{style}]{message}[/]" if style else message
        self.query_one("#transcript", VerticalScroll).mount(Static(text))

    # -- state ---------------------------------------------------------------

    def _poll_state(self) -> None:
        """Read the core's state into the sidebar and status bar.

        Polled rather than pushed because `state` is a request and the core has
        no state-changed event; the window asks for the same thing when it
        needs it. Half a second is quick enough that the prompt never shows a
        mode the user has already changed.
        """
        try:
            self.state = self.client.call("state", timeout=5) or {}
        except CoreError:
            return
        self.query_one("#sidebar", Sidebar).update_state(self.state)
        self._refresh_context()
        self._refresh_status()

    def _refresh_context(self) -> None:
        try:
            payload = self.client.call("context.get", timeout=5) or {}
        except CoreError:
            return
        self.query_one("#sidebar", Sidebar).update_context(payload)

    def _refresh_status(self) -> None:
        from tonyagent.cli.repl import _basename

        project = str(self.state.get("project") or "")
        left = _basename(project) if project else "no project"
        bound = bool(self.state.get("bound"))
        right = str(self.state.get("model")) if bound else "no provider bound"
        status = self.query_one("#status", Static)
        status.update(f" {left} · {right}")
        status.set_class(bound, "bound")

    # -- input ---------------------------------------------------------------

    def _start(self) -> None:
        if self.initial_prompt:
            self.query_one("#composer", TextArea).text = self.initial_prompt
            self.initial_prompt = ""
            self._submit()
            return
        self.query_one("#composer", TextArea).focus()

    def on_key(self, event: Any) -> None:
        """Enter submits, Escape declines.

        Bindings are dispatched before this, so only keys no binding claimed
        arrive here. Ctrl-C and Ctrl-D are bindings and never reach it, which
        is what stops an interrupt mid-turn from being read as text.
        """
        if event.key == "enter" and not event.character:
            event.stop()
            self._submit()
        elif event.key == "escape" and self._pending_dialog:
            self._answer("n")
        elif event.key == "ctrl+1":
            self._set("mode.set", {"mode": "chat"}, "mode")
        elif event.key == "ctrl+3":
            self._set("permission.set", {"permission": "high"}, "permission")
        elif event.key == "ctrl+4":
            self._refresh_context()

    def _submit(self) -> None:
        composer = self.query_one("#composer", TextArea)
        text = composer.text.strip()
        if not text:
            return
        composer.text = ""
        if self._pending_dialog:
            self._answer(text)
            return
        if text.startswith("/"):
            self._slash(text)
            return
        self._begin_turn(text)
        self._send(text)

    def _send(self, text: str) -> None:
        """Send a turn without blocking the UI thread.

        `send` only returns when the turn is over, and a turn can run for
        minutes, so it goes to a worker. That is also what lets the composer
        answer a confirmation while the turn is still in flight.
        """

        def worker() -> None:
            try:
                self.client.call("send", {"text": text}, timeout=TURN_TIMEOUT_S)
            except CoreError as exc:
                self.call_from_thread(self._notice, str(exc), "error")

        threading.Thread(target=worker, daemon=True).start()

    def _answer(self, text: str) -> None:
        """Answer whatever the turn is suspended on."""
        call_id = self._pending_dialog
        self._close_dialog()
        if not call_id:
            return
        if call_id == "confirm":
            yes = text.strip().lower() in {"y", "yes", "a", "always", "1", "true"}
            self._client_call("confirm.respond", {"id": "", "confirmed": yes})
            return
        self._client_call("user.respond", {"id": call_id, "answer": text})

    def _client_call(self, method: str, params: dict[str, Any]) -> None:
        try:
            self.client.call(method, params, timeout=30)
        except CoreError as exc:
            self._notice(str(exc), "error")

    def _slash(self, line: str) -> None:
        """Slash commands.

        Only the ones that are one request with no presentation go here. The
        rest are the line-mode REPL's, and pointing at that rather than
        reimplementing them is deliberate: two implementations of `/mode` could
        disagree about what level is in force, which is exactly what `mode.set`
        warns about when it returns the applied level rather than the request.
        """
        parts = line[1:].split(None, 1)
        command = parts[0] if parts else ""
        argument = parts[1].strip() if len(parts) > 1 else ""

        if command in ("quit", "exit"):
            self.exit()
        elif command == "help":
            self.action_commands()
        elif command == "mode" and argument:
            self._set("mode.set", {"mode": argument}, "mode")
        elif command == "permission" and argument:
            self._set("permission.set", {"permission": argument}, "permission")
        else:
            self._notice(
                f"/{command} is not here; ctrl+1 mode, ctrl+3 permission", "warn"
            )

    def _set(self, method: str, params: dict[str, Any], label: str) -> None:
        try:
            result = self.client.call(method, params) or {}
        except CoreError as exc:
            self._notice(str(exc), "error")
            return
        applied = result.get("name") or result.get("mode") or next(iter(params.values()))
        self._notice(f"{label}: {applied}")
        self._poll_state()

    # -- actions -------------------------------------------------------------

    def action_cancel(self) -> None:
        if self._pending_dialog:
            self._answer("n")
            return
        try:
            self.client.notify("cancel", {})
        except CoreError as exc:
            self._notice(str(exc), "error")
            return
        self._notice("cancelled")

    def action_commands(self) -> None:
        self._notice(
            "ctrl+c cancel · ctrl+d quit · ctrl+p commands\n"
            "ctrl+1 chat mode · ctrl+3 permission high · ctrl+4 context"
        )


__all__ = ["SIDEBAR_MIN_WIDTH", "TURN_TIMEOUT_S", "TonyApp"]
