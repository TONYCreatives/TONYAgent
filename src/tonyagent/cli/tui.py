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
from textual.widgets import Footer, OptionList, Static, TextArea

from tonyagent.cli import theme
from tonyagent.cli.client import CoreClient, CoreError
from tonyagent.cli.render import _argument_summary, _result_summary
from tonyagent.cli.widgets import (
    ChangeHeader,
    ConfirmDialog,
    DiffBlock,
    Sidebar,
    ToolCall,
    ToolLine,
    Turn,
    TurnFooter,
)

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
        #: Ids of the confirmation and the question the turn is suspended on.
        #: Empty means the composer sends turns rather than answers.
        self._pending_confirm = ""
        self._pending_ask = ""
        #: What the open picker will set, so one handler serves both.
        self._picker_action: Optional[tuple[str, str, dict[str, Any]]] = None

    # -- layout --------------------------------------------------------------

    def compose(self) -> ComposeResult:
        with Horizontal(id="body"):
            with VerticalScroll(id="transcript"):
                yield Static(self._welcome(), id="intro")
            yield Sidebar(id="sidebar")
        yield Static("", id="status")
        yield TextArea(id="composer")
        yield Footer()
        # A confirmation is the one thing that takes the keyboard, so it is a
        # real dialog rather than a line in the composer. Hidden until asked.
        yield ConfirmDialog("", "", False, id="confirm-dialog", classes="hidden")
        # The pickers, same reasoning: a list of models is not something to
        # type at a prompt, and re-implementing them as free text is how a
        # picker ends up offering something the core would refuse.
        yield OptionList(id="picker", classes="hidden")

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
        # Kept whole, like `TrajectoryView`: the raw log, not a summary of it.
        turn.frames.append({"type": kind, "payload": payload})

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
            # Read the real payload -- status, output, error, and any
            # `file_change` artifacts -- rather than only the preview the
            # one-line summary wants. The diffs come from here.
            detail = ToolCall.from_result(payload)
            call.status = detail.status
            call.output = detail.output
            call.error = detail.error
            call.changes = detail.changes
            call.result = _result_summary(payload)
            line = self._line_for(call)
            if line is not None:
                line.refresh_line()
            if call.changes:
                self._show_changes(call)
        elif kind == "turn.finished":
            self._end_turn()
        elif kind == "turn.failed":
            message = str(payload.get("error") or "the turn failed")
            self._end_turn()
            self._notice(message, "error")
        elif kind == "confirmation.requested":
            self._open_confirm(payload)
        elif kind == "user.asked":
            self._open_ask(payload)
        elif kind in ("confirmation.resolved", "user.resolved"):
            self._close_dialog()

    def _line_for(self, call: ToolCall) -> Optional[ToolLine]:
        if self._turn_box is None:
            return None
        for widget in self._turn_box.query(ToolLine):
            if widget.call is call:
                return widget
        return None

    def _open_confirm(self, payload: dict[str, Any]) -> None:
        """Show a destructive or gated tool confirmation and take the keyboard."""
        self._pending_confirm = str(payload.get("id", ""))
        name = str(payload.get("name", "?"))
        dialog = self.query_one("#confirm-dialog", ConfirmDialog)
        dialog.tool_name = name
        dialog.summary = _argument_summary(name, payload.get("arguments"))
        dialog.destructive = bool(payload.get("destructive"))
        dialog.set_class(dialog.destructive, "confirm-destructive")
        dialog.set_class(not dialog.destructive, "confirm")
        dialog.remove_class("hidden")
        self.query_one("#composer", TextArea).display = False
        dialog.focus()

    def _open_ask(self, payload: dict[str, Any]) -> None:
        """Show a question from `ask_user_question` or `present`.

        A question takes free text rather than yes/no, so it goes back to the
        composer with the question as its title -- there is nothing to confirm
        here, and a dialog that only accepted `y`/`n` would be answering a
        question nobody asked.
        """
        self._pending_ask = str(payload.get("id", ""))
        question = str(payload.get("question") or payload.get("text") or "")
        composer = self.query_one("#composer", TextArea)
        composer.border_title = "the agent is asking"
        composer.placeholder = question or "your answer"
        composer.display = True
        composer.focus()

    def _close_dialog(self) -> None:
        self._pending_confirm = ""
        self._pending_ask = ""
        dialog = self.query_one("#confirm-dialog", ConfirmDialog)
        dialog.add_class("hidden")
        composer = self.query_one("#composer", TextArea)
        composer.border_title = ""
        composer.placeholder = ""
        composer.display = True
        self.query_one("#picker", OptionList).remove_class("hidden")

    def _show_changes(self, call: ToolCall) -> None:
        """Mount the diffs a tool produced, under its line.

        Inside the fence, because a change *is* part of what the agent did in
        this turn. Each change gets a header and then its diff, which is the
        order `TrajectoryView` uses and the order that reads: which file, then
        what happened to it.
        """
        if self._turn_box is None:
            return
        for change in call.changes:
            self._turn_box.mount(ChangeHeader(change))
            if change.diff:
                self._turn_box.mount(DiffBlock(change))

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
        if self._pending_confirm:
            # The confirmation owns the keyboard. Anything that is not y/a/n is
            # a decline rather than a stray keystroke reaching the transcript,
            # because "no" is the only safe reading of a key pressed while a
            # destructive tool is waiting.
            event.stop()
            self._answer_confirm(event.key)
            return
        if event.key == "enter" and not event.character:
            event.stop()
            self._submit()
        elif event.key == "escape" and self._pending_ask:
            self._answer("")
        elif event.key == "ctrl+1":
            self._pick_mode()
        elif event.key == "ctrl+2":
            self._pick_model()
        elif event.key == "ctrl+3":
            self._pick_permission()
        elif event.key == "ctrl+4":
            self._refresh_context()
        elif event.key == "escape" and self._picker_action:
            self._close_picker()

    def _submit(self) -> None:
        composer = self.query_one("#composer", TextArea)
        text = composer.text.strip()
        if self._pending_ask:
            composer.text = ""
            self._answer(text)
            return
        if not text:
            return
        composer.text = ""
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

    def _answer_confirm(self, key: str) -> None:
        """Answer a confirmation from a keypress.

        ``a`` raises the session's permission level rather than remembering one
        tool, because `confirm.respond` takes a bool and there is no per-tool
        allowlist in the protocol. It says so before doing it, for the same
        reason the line REPL does: a user who believes "always" has trusted one
        tool has in fact trusted everything for this session.
        """
        call_id = self._pending_confirm
        if not call_id:
            return
        lowered = key.strip().lower()
        if lowered in {"a", "always"} and not self._raise_permission():
            return
        confirmed = lowered in {"y", "yes", "a", "always", "1", "true"}
        self._client_call("confirm.respond", {"id": call_id, "confirmed": confirmed})

    def _raise_permission(self) -> bool:
        """Step the session up one level, having said what that means."""
        listing = self.client.call("permission.list") or {}
        levels = listing.get("permissions") or []
        current = str(listing.get("permission", ""))
        order = [str(item.get("name")) for item in levels if isinstance(item, dict)]
        if current not in order or order.index(current) + 1 >= len(order):
            self._notice("Already at the highest level; confirming this once.")
            return True
        target = order[order.index(current) + 1]
        self._notice(
            f"'always' raises this session to {target} -- every tool allowed, "
            "not just this one.",
            "warn",
        )
        self._client_call("permission.set", {"permission": target})
        self._poll_state()
        return True

    def _answer(self, text: str) -> None:
        """Answer an open question, or decline it with nothing."""
        ask_id = self._pending_ask
        self._close_dialog()
        if not ask_id:
            return
        self._client_call("user.respond", {"id": ask_id, "answer": text})

    def _client_call(self, method: str, params: dict[str, Any]) -> None:
        try:
            self.client.call(method, params, timeout=30)
        except CoreError as exc:
            self._notice(str(exc), "error")

    def _open_picker(
        self,
        title: str,
        entries: list[tuple[str, str]],
        current: str,
        action: tuple[str, str, dict[str, Any]],
    ) -> None:
        """Offer a list, with the current value marked.

        ``action`` is ``(label, method, param)``, so one handler serves every
        picker and adding a fourth is one call rather than a new method. The
        options come from the core's own list methods and never from a table
        here: `mode.list` says explicitly that a mode the frontend cannot see
        is a mode nobody can select, and a second table would drift.
        """
        picker = self.query_one("#picker", OptionList)
        picker.clear_options()
        picker.border_title = title
        for name, detail in entries:
            label = f"{name}  {detail}" if detail else name
            if name == current:
                label = f"* {label}"
            picker.add_option(label)
        self._picker_action = action
        picker.remove_class("hidden")
        picker.focus()

    def _close_picker(self) -> None:
        self._picker_action = None
        self.query_one("#picker", OptionList).add_class("hidden")
        self.query_one("#composer", TextArea).focus()

    def on_option_list_option_selected(self, event: Any) -> None:
        option = event.option
        text = str(getattr(option, "prompt", "") or "")
        # The mark and the detail are stripped back to the bare name, which is
        # what the core wants as a value.
        name = text.lstrip("* ").split("  ")[0].strip()
        action = self._picker_action
        self._close_picker()
        if action is None or not name:
            return
        label, method, template = action
        params = {key: (name if value is None else value) for key, value in template.items()}
        self._set(method, params, label)

    def _pick_mode(self) -> None:
        payload = self.client.call("mode.list") or {}
        modes = payload.get("modes") or []
        entries = [
            (str(m.get("name", "")), str(m.get("description", "")))
            for m in modes
            if isinstance(m, dict)
        ]
        self._open_picker(
            "mode", entries, str(payload.get("mode", "")), ("mode", "mode.set", {"mode": None})
        )

    def _pick_permission(self) -> None:
        payload = self.client.call("permission.list") or {}
        levels = payload.get("permissions") or []
        entries = [
            (str(item.get("name", "")), str(item.get("description", "")))
            for item in levels
            if isinstance(item, dict)
        ]
        self._open_picker(
            "permission",
            entries,
            str(payload.get("permission", "")),
            ("permission", "permission.set", {"permission": None}),
        )

    def _pick_model(self) -> None:
        try:
            payload = self.client.call("models.list") or {}
        except CoreError as exc:
            self._notice(str(exc), "error")
            return
        models = payload.get("models") or []
        entries = [
            (
                str(m.get("id", "")) if isinstance(m, dict) else str(m),
                str(m.get("label", "")) if isinstance(m, dict) else "",
            )
            for m in models
        ]
        if not entries:
            self._notice("The provider returned no models.", "warn")
            return
        # A model change is a re-bind: there is no `model.set`, and the
        # provider is what holds the keyring entry, so the current provider's
        # name is reused rather than switching providers by accident.
        provider = str(self.state.get("provider") or "")
        self._open_picker(
            "model",
            entries,
            str(payload.get("current", "")),
            ("model", "bind_provider", {"name": provider, "model": None}),
        )

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
        elif command == "mode":
            self._set("mode.set", {"mode": argument}, "mode") if argument \
                else self._pick_mode()
        elif command == "permission":
            self._set("permission.set", {"permission": argument}, "permission") \
                if argument else self._pick_permission()
        elif command == "model":
            self._set("bind_provider",
                      {"name": str(self.state.get("provider") or ""), "model": argument},
                      "model") if argument else self._pick_model()
        elif command == "trajectory":
            self._notice(f"{len(self.turn.frames) if self.turn else 0} frames captured",
                         "warn")
        else:
            self._notice(
                f"/{command} is not here; /mode /model /permission", "warn"
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
        if self._pending_confirm:
            self._client_call(
                "confirm.respond", {"id": self._pending_confirm, "confirmed": False}
            )
            self._close_dialog()
            return
        if self._pending_ask:
            self._answer("")
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
            "ctrl+1 mode · ctrl+2 model · ctrl+3 permission · ctrl+4 context\n"
            "/mode /model /permission · escape closes a picker"
        )


__all__ = ["SIDEBAR_MIN_WIDTH", "TURN_TIMEOUT_S", "TonyApp"]
