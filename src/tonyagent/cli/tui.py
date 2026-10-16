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
from textual.widgets import Footer, Input, OptionList, Static
from textual.widgets.option_list import Option

from tonyagent.cli import theme
from tonyagent.cli.client import CoreClient, CoreError
from tonyagent.cli.render import _argument_summary, _result_summary, pad_to
from tonyagent.cli.widgets import (
    ChangeHeader,
    Command,
    CommandPalette,
    ConfirmDialog,
    DiffBlock,
    PickerDialog,
    PickerEntry,
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


#: How long the second ctrl+c has to arrive. Long enough to be deliberate,
#: short enough that a hint left on screen is not still there later.
CONFIRM_PRESS_S = 5.0


class TonyApp(App[None]):
    """TONYAgent, drawn as widgets."""

    CSS = theme.build_css()
    TITLE = "TONYAgent"

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("ctrl+c", "cancel", "interrupt", show=True, priority=True),
        Binding("ctrl+d", "quit", "quit", show=True, priority=True),
        Binding("ctrl+q", "quit", "quit", show=False),
        Binding("ctrl+shift+p", "commands", "commands", show=True),
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
        #: The `run` name of each row in the inline list, parallel to it.
        self._slash_runs: list[str] = []
        #: Presses so far on ctrl+c, and the timer after which the second is
        #: no longer wanted. See `action_cancel`.
        self._confirm_presses = 0
        self._confirm_timer: Any = None
        #: True between `turn.started` and `turn.finished`. `state.busy` is
        #: refreshed twice a second, which is far too coarse to answer "is a
        #: turn running right now" when the answer decides whether ctrl+c
        #: interrupts or quits.
        self._turn_open = False
        #: What the open picker will set, so one handler serves both.
        self._picker_action: Optional[tuple[str, str, dict[str, Any]]] = None

    # -- layout --------------------------------------------------------------

    def compose(self) -> ComposeResult:
        with Horizontal(id="body"):
            with VerticalScroll(id="transcript"):
                yield Static(self._welcome(), id="intro")
            yield Sidebar(id="sidebar")
        yield Static("", id="status")
        # The inline command list. Sits directly above the composer and is
        # hidden until a `/` is typed, because typing `/` and getting nothing
        # back is how a command set ends up looking empty.
        yield OptionList(id="slash-menu", classes="hidden")
        yield Input(placeholder="ask tony anything", id="composer")
        yield Footer()
        # A confirmation is the one thing that takes the keyboard, so it is a
        # real dialog rather than a line in the composer. Hidden until asked.
        yield ConfirmDialog("", "", False, id="confirm-dialog", classes="hidden")
        # The pickers, same reasoning: a list of models is not something to
        # type at a prompt, and re-implementing them as free text is how a
        # picker ends up offering something the core would refuse.

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
            "ctrl+p commands · ctrl+c twice to interrupt · ctrl+d quit"
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
        # Tracked before the early return: `turn.started` arrives before any
        # turn widget exists, and it is the event that decides whether ctrl+c
        # interrupts or quits.
        if kind == "turn.started":
            self._turn_open = True
        elif kind in ("turn.finished", "turn.failed"):
            self._turn_open = False

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
        self.query_one("#composer", Input).display = False
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
        composer = self.query_one("#composer", Input)
        composer.border_title = "the agent is asking"
        composer.placeholder = question or "your answer"
        composer.display = True
        composer.focus()

    def _close_dialog(self) -> None:
        self._pending_confirm = ""
        self._pending_ask = ""
        dialog = self.query_one("#confirm-dialog", ConfirmDialog)
        dialog.add_class("hidden")
        composer = self.query_one("#composer", Input)
        composer.border_title = ""
        composer.placeholder = ""
        composer.display = True


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
            self.query_one("#composer", Input).value = self.initial_prompt
            self.initial_prompt = ""
            self._submit()
            return
        self.query_one("#composer", Input).focus()

    # -- the inline command list --------------------------------------------

    def _slash_matches(self, text: str) -> list[Command]:
        """The commands a partially-typed `/` could mean.

        Matches on the part after the slash, and returns them in registry
        order rather than best-first. Reordering as you type is disorienting:
        the row you were about to press Enter on moves.
        """
        needle = text.lstrip("/").strip().lower()
        return [
            c for c in COMMANDS
            if needle in c.name.lower().lstrip("/")
            or needle in c.description.lower()
        ]

    def _refresh_slash_menu(self) -> None:
        """Show the list when the composer holds a `/`, hide it otherwise.

        **Only a leading slash opens it.** A `/` in the middle of a sentence is
        a path, not a command, and opening a menu over it would swallow the
        Enter that was meant to send the turn.
        """
        menu = self.query_one("#slash-menu", OptionList)
        value = self.query_one("#composer", Input).value
        if not value.startswith("/") or self._pending_confirm:
            self._hide_slash_menu()
            return

        matches = self._slash_matches(value)
        menu.clear_options()

        # **Stop offering once the text exactly names a command.** Otherwise the
        # list keeps matching its own completion: `/co` + Enter gives `/state `,
        # which still matches `/state`, so the next Enter completed again and
        # the command never ran. Hiding on an exact match is what makes the two
        # Enters mean different things -- the first completes, the second runs.
        if value.rstrip() in {c.name for c in matches}:
            self._hide_slash_menu()
            return

        # Both columns in the prompt, and the id is the `run` name -- which is
        # what `_accept_slash` dispatches on. Passing the description as the id
        # (the natural-looking `Option(name, description)`) rendered a list of
        # bare names with the help text silently discarded.
        width = max((len(c.name) for c in matches), default=0)
        for command in matches:
            label = f"{pad_to(command.name, width)}   {command.description}"
            menu.add_option(Option(label, command.run))
        self._slash_runs = [c.run for c in matches]
        if matches:
            menu.highlighted = 0
            menu.remove_class("hidden")
            menu.display = True
        else:
            self._hide_slash_menu()

    def _hide_slash_menu(self) -> None:
        menu = self.query_one("#slash-menu", OptionList)
        menu.add_class("hidden")
        menu.display = False
        self._slash_runs = []

    @property
    def _slash_visible(self) -> bool:
        menu = self.query_one("#slash-menu", OptionList)
        return menu.display and bool(self._slash_runs)

    def on_input_changed(self, event: Any) -> None:
        self._refresh_slash_menu()

    def _move_slash_highlight(self, delta: int) -> None:
        menu = self.query_one("#slash-menu", OptionList)
        if not self._slash_runs:
            return
        current = menu.highlighted or 0
        count = len(self._slash_runs)
        # Wraps, because a list you reach the end of and have to start again
        # is a list you stop using.
        menu.highlighted = (current + delta) % count

    def _accept_slash(self) -> bool:
        """Put the highlighted command in the composer, rather than running it.

        Completing rather than executing is the right default: `/mo` + Enter
        gives you `/mode` with the cursor after it, so you can go on typing an
        argument. Running it would make a typo into a state change. `Enter`
        again submits.
        """
        menu = self.query_one("#slash-menu", OptionList)
        index = menu.highlighted or 0
        if index >= len(self._slash_runs):
            return False
        command = next(c for c in COMMANDS if c.run == self._slash_runs[index])
        composer = self.query_one("#composer", Input)
        composer.value = f"{command.name} "
        composer.cursor_position = len(composer.value)
        # Kept open: the argument half is still to be typed.
        self._refresh_slash_menu()
        return True

    def on_input_submitted(self, event: Any) -> None:
        """Enter sends.

        `Input` posts this on Enter, rather than the key arriving here. The
        composer used to be a `TextArea`, whose Enter inserts a newline --
        correct for a multi-line editor, and the wrong widget entirely for a
        composer whose own docstring says a line is one turn. `Input` is the
        single-line widget, so the convention every other terminal agent uses
        comes from the widget rather than from a key handler that has to
        intercept it first.
        """
        event.stop()
        # The inline list claims the first Enter: it completes the command, and
        # the second submits it. Without this, typing `/pl` and pressing Enter
        # runs a command the person had not finished naming.
        if self._slash_visible and self._accept_slash():
            return
        self._submit()

    def on_key(self, event: Any) -> None:
        """Escape and the shortcuts.

        Enter is not here: it is the composer's own `Submitted` message, and
        re-handling it would send a turn twice. Bindings are dispatched before
        this, so only keys no binding claimed arrive -- which is what stops
        Ctrl-C or Ctrl-D from being read as text.
        """
        if self._pending_confirm:
            # The confirmation owns the keyboard. Anything that is not y/a/n is
            # a decline rather than a stray keystroke reaching the transcript,
            # because "no" is the only safe reading of a key pressed while a
            # destructive tool is waiting.
            event.stop()
            self._answer_confirm(event.key)
            return
        if event.key == "escape" and self._pending_ask:
            self._answer("")
        elif event.key == "escape" and self._slash_visible:
            # Close the list but keep the text, so a `/` that was meant as a
            # character is still there to send.
            self._hide_slash_menu()
            event.stop()
        elif event.key == "up" and self._slash_visible:
            self._move_slash_highlight(-1)
            event.stop()
        elif event.key == "down" and self._slash_visible:
            self._move_slash_highlight(1)
            event.stop()
        elif event.key == "ctrl+1":
            self._pick_mode()
        elif event.key == "ctrl+2":
            self._pick_model()
        elif event.key == "ctrl+3":
            self._pick_permission()
        elif event.key == "ctrl+4":
            self._refresh_context()

    def _submit(self) -> None:
        composer = self.query_one("#composer", Input)
        text = composer.value.strip()
        if self._pending_ask:
            composer.value = ""
            self._answer(text)
            return
        if not text:
            return
        composer.value = ""
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
        entries: list[PickerEntry],
        action: tuple[str, str, dict[str, Any]],
        *,
        hint: str = "",
    ) -> None:
        """Offer a list, with a filter.

        ``action`` is ``(label, method, param_template)``, so one handler serves
        every picker. The options come from the core's own list methods and
        never from a table here: `mode.list` says explicitly that a mode the
        frontend cannot see is a mode nobody can select, and a second table
        would drift.
        """
        self._picker_action = action

        def chosen(value: Optional[str]) -> None:
            self._picker_action = None
            if not value:
                return
            label, method, template = action
            params = {k: (value if v is None else v) for k, v in template.items()}
            self._set(method, params, label)

        self.push_screen(PickerDialog(title, entries, hint=hint), chosen)

    def _pick_mode(self) -> None:
        payload = self.client.call("mode.list") or {}
        modes = payload.get("modes") or []
        current = str(payload.get("mode", ""))
        entries: list[PickerEntry] = []
        # The current mode first, under its own heading, because "what am I in
        # now" is the first question when opening a mode picker.
        for name in [current] + [str(m.get("name")) for m in modes if isinstance(m, dict)]:
            if not name or any(e.value == name for e in entries):
                continue
            mode = next((m for m in modes if isinstance(m, dict) and m.get("name") == name), {})
            entries.append(PickerEntry(
                value=name,
                label=name,
                group="current" if name == current else "",
                note="·" if name == current else ("writes" if mode.get("writes") else "read only"),
            ))
        self._open_picker(
            "mode", entries, ("mode", "mode.set", {"mode": None}),
            hint="enter select · esc close",
        )

    def _pick_permission(self) -> None:
        payload = self.client.call("permission.list") or {}
        levels = payload.get("permissions") or []
        current = str(payload.get("permission", ""))
        names = [str(item.get("name", "")) for item in levels if isinstance(item, dict)]
        # Current first, so the groups stay contiguous. Left in the server's
        # order, `low / *medium* / high / full` alternates between two groups
        # and the header is drawn three times for one list.
        entries = [
            PickerEntry(value=name, label=name, group="current" if name == current else "levels",
                        note="·" if name == current else "")
            for name in [current] + [n for n in names if n != current]
            if name
        ]
        self._open_picker(
            "permission", entries,
            ("permission", "permission.set", {"permission": None}),
            hint="full runs commands with no sandbox · esc close",
        )

    def _pick_model(self) -> None:
        """The model picker: grouped by provider, with price and context size.

        Reads `models.catalog`, which carries the provider's own `context_length`
        and `pricing` and costs no extra request over the model list.

        **The labels are the provider's, not estimates.** A model it publishes
        no price for gets no price label, which is a different thing from
        getting "Free" -- a gateway that omits pricing has not said the model
        is free, and saying so on its behalf would be the frontend deciding
        what a token costs.
        """
        try:
            # Refreshed first, because the bind needs the provider's name and
            # `state` may not have been polled yet on a cold start -- an empty
            # name there fails at the core, having looked like a selection the
            # user made correctly.
            self._poll_state()
            payload = self.client.call("models.catalog") or {}
        except CoreError as exc:
            self._notice(str(exc), "error")
            return
        raw = payload.get("models") or []
        current = str(payload.get("current", ""))
        models = [m for m in raw if isinstance(m, dict) and m.get("id")]
        if not models:
            self._notice("The provider returned no models.", "warn")
            return

        def group_of(model_id: str) -> str:
            return model_id.split("/", 1)[0] if "/" in model_id else "other"

        def note_for(model: dict) -> str:
            parts: list[str] = []
            window = _context_label(model.get("context_length"))
            if window:
                parts.append(window)
            price = _price_label(model.get("pricing"))
            if price:
                parts.append(price)
            return "  ".join(parts)

        by_id = {str(m["id"]): m for m in models}
        entries: list[PickerEntry] = []
        if current and current in by_id:
            # The current row carries its numbers too. Leaving them off would
            # make the model you are on the one row you cannot compare.
            entries.append(
                PickerEntry(current, current, group="current",
                            note=f"·  {note_for(by_id[current])}".rstrip())
            )
        for model_id in sorted(by_id, key=lambda i: (group_of(i), i)):
            if model_id == current:
                continue
            entries.append(
                PickerEntry(model_id, model_id, group=group_of(model_id),
                            note=note_for(by_id[model_id]))
            )

        # A model change is a re-bind: there is no `model.set`, and the provider
        # is what holds the keyring entry, so the current provider's name is
        # reused rather than switching providers by accident.
        provider = str(self.state.get("provider") or "")
        self._open_picker(
            "select model", entries,
            ("model", "bind_provider", {"name": provider, "model": None}),
            hint=f"{len(models)} models · enter select · esc close",
        )

    def _slash(self, line: str) -> None:
        """Slash commands.

        **The typed form and the palette go through one registry.** `/plan` and
        choosing `/plan` from ctrl+p run the same handler, because two lists
        are how a command ends up in one and not the other -- which is exactly
        what happened with the nine that were line-mode only until the palette
        existed.

        The three that take an argument (`/mode plan`) are handled before the
        registry, because there is nothing to pick from a list when the value
        is already typed.
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
        else:
            match = next((c for c in COMMANDS if c.name == f"/{command}"), None)
            if match is None:
                self._notice(f"/{command} is not a command; ctrl+p lists them", "warn")
                return
            self._run_command(match.run)

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
        """Two presses, and what the second does depends on the turn.

        **One ctrl+c used to cancel a running turn, and one at an empty prompt
        used to quit.** Both are destructive on a key a terminal hands out for a
        dozen unrelated reasons -- a copy that became an interrupt, a
        muscle-memory habit, something else on the system that claims it.
        Losing a turn to that is what the convenience costs.

        So the first press says what the second will do, and the second has
        five seconds to arrive. The timer clears the count, so a stray press
        leaves nothing behind to confuse the next one. This is OpenCode's
        two-press interrupt, and the reason it is worth copying is that it is
        not a confirmation dialog: it does not steal the turn's place on
        screen, it just says one sentence in the transcript.
        """
        if self._pending_confirm:
            # A pending confirmation already owns the key: one press declines.
            self._client_call(
                "confirm.respond", {"id": self._pending_confirm, "confirmed": False}
            )
            self._close_dialog()
            return
        if self._pending_ask:
            self._answer("")
            return

        self._confirm_presses += 1
        if self._confirm_presses >= 2:
            self._clear_confirm()
            self._fire_interrupt()
            return

        busy = bool(self.state.get("busy")) or self._turn_open
        self._notice(f"press ctrl+c again to {'interrupt the turn' if busy else 'quit'}")
        self._confirm_timer = self.set_timer(CONFIRM_PRESS_S, self._clear_confirm)

    def _clear_confirm(self) -> None:
        """Forget an unanswered press, so the next one starts over."""
        self._confirm_presses = 0
        timer, self._confirm_timer = self._confirm_timer, None
        if timer is not None:
            try:
                timer.stop()
            except Exception:  # noqa: BLE001 - a timer that already fired is fine
                pass

    def _fire_interrupt(self) -> None:
        if not (bool(self.state.get("busy")) or self._turn_open):
            self.exit()
            return
        try:
            self.client.notify("cancel", {})
        except CoreError as exc:
            self._notice(str(exc), "error")
            return
        self._notice("cancelled", "warn")

    def action_commands(self) -> None:
        """Open the palette. It used to print a notice about ctrl+p, which is
        not what ctrl+p does -- the shortest possible version of the same
        mistake, and the reason the palette is worth a test."""
        self.push_screen(CommandPalette(COMMANDS), self._run_command)

    def _run_command(self, run: Optional[str]) -> None:
        """Do what the chosen command says."""
        if not run:
            return
        handler = {
            "pick_mode": self._pick_mode,
            "pick_model": self._pick_model,
            "pick_permission": self._pick_permission,
            "pick_reasoning": self._pick_reasoning,
            "show_plan": self._show_plan,
            "show_state": self._show_state,
            "show_trajectory": self._show_trajectory,
            "show_usage": self._show_usage,
            "show_tools": self._show_tools,
            "show_sandbox": self._show_sandbox,
            "show_conversations": self._show_conversations,
            "new_conversation": self._new_conversation,
            "show_keys": self._show_keys,
            "quit": self.exit,
        }.get(run)
        if handler is None:
            self._notice(f"{run} is listed but not wired up", "warn")
            return
        handler()

    # -- the commands the interface did not have before ----------------------

    def _panel(self, title: str, rows: list[tuple[str, str]]) -> None:
        """Draw a titled block into the transcript.

        One helper for nine commands, because they are nine renderings of the
        same two-column thing and writing them out separately is how they end
        up looking like nine different features.
        """
        self._notice("")
        self._notice(f"{title}", "warn")
        if not rows:
            self._notice("  nothing to show", "warn")
            return
        width = max(len(label) for label, _ in rows)
        for label, value in rows:
            self._notice(f"  {pad_to(label, width)}  {value}")

    def _show_plan(self) -> None:
        try:
            payload = self.client.call("plan.get") or {}
        except CoreError as exc:
            self._notice(str(exc), "error")
            return
        rendered = str(payload.get("rendered") or "").strip()
        summary = str(payload.get("summary") or "").strip()
        if not rendered and not summary:
            self._notice("no plan")
            return
        self._notice("")
        for line in (rendered or summary).splitlines():
            self._notice(f"  {line}")

    def _show_state(self) -> None:
        self._poll_state()
        rows = [
            (
                key,
                str(value)
                if not isinstance(value, (dict, list))
                else f"<{type(value).__name__}>",
            )
            for key, value in sorted(self.state.items())
        ]
        self._panel("state", rows)

    def _show_trajectory(self) -> None:
        frames = self.turn.frames if self.turn else []
        kinds: dict[str, int] = {}
        for frame in frames:
            kinds[str(frame.get("type", "?"))] = kinds.get(str(frame.get("type", "?")), 0) + 1
        rows = [(kind, str(count)) for kind, count in sorted(kinds.items())]
        self._panel(f"trajectory — {len(frames)} frames", rows or [("(none yet)", "")])

    def _show_usage(self) -> None:
        try:
            payload = self.client.call("usage.summary") or {}
        except CoreError as exc:
            self._notice(str(exc), "error")
            return
        totals = payload.get("totals")
        if not isinstance(totals, dict):
            self._notice("no usage recorded")
            return
        rows = [
            ("requests", str(totals.get("requests", 0))),
            ("failed", str(totals.get("failed", 0))),
            ("input tokens", str(totals.get("input_tokens", 0))),
            ("output tokens", str(totals.get("output_tokens", 0))),
        ]
        self._panel(f"usage — last {payload.get('window', '?')}", rows)

    def _show_tools(self) -> None:
        try:
            payload = self.client.call("tools.get") or {}
        except CoreError as exc:
            self._notice(str(exc), "error")
            return
        self._panel("tool budget", [("per turn", str(payload.get("label", "?")))])

    def _show_sandbox(self) -> None:
        try:
            stats = self.client.call("sandbox.stats") or {}
        except CoreError:
            stats = {}
        running = (self.state.get("sandbox") or "")
        rows = [(key, str(value)) for key, value in stats.items()
                if not isinstance(value, (dict, list))]
        rows.insert(0, ("status", str(running or "unknown")))
        self._panel("sandbox", rows)

    def _show_conversations(self) -> None:
        try:
            payload = self.client.call("conversations.list") or {}
        except CoreError as exc:
            self._notice(str(exc), "error")
            return
        items = payload.get("conversations") or []
        current = str(self.state.get("conversation", ""))
        rows = []
        for item in items:
            if not isinstance(item, dict):
                continue
            ident = str(item.get("id", ""))
            title = str(item.get("title") or "(untitled)")
            rows.append(("*" if ident == current else " ", f"{title}  {ident[:8]}"))
        self._panel("conversations", rows or [("", "none saved")])

    def _new_conversation(self) -> None:
        try:
            self.client.call("conversations.create", {})
        except CoreError as exc:
            self._notice(str(exc), "error")
            return
        self._poll_state()
        self._notice("new conversation", "warn")

    def _show_keys(self) -> None:
        try:
            payload = self.client.call("key.list") or {}
        except CoreError as exc:
            self._notice(str(exc), "error")
            return
        keys = payload.get("keys") or []
        rows = []
        for entry in keys:
            if isinstance(entry, dict):
                provider = str(entry.get("provider") or entry.get("name") or "?")
                rows.append(("*" if entry.get("active") else " ", provider))
            else:
                rows.append(("", str(entry)))
        self._panel("keys", rows or [("", "none saved — /key in the line interface adds one")])

    def _pick_reasoning(self) -> None:
        try:
            payload = self.client.call("reasoning.list") or {}
        except CoreError as exc:
            self._notice(str(exc), "error")
            return
        efforts = payload.get("efforts") or []
        if not efforts:
            # A model that cannot think reports no efforts; the honest thing is
            # to say so rather than offer a choice that would be refused.
            self._notice("this model does not report a thinking effort", "warn")
            return
        current = str(payload.get("effort") or payload.get("model") or "")
        entries = [(str(e), "") for e in efforts]
        self._open_picker(
            "reasoning", entries, current,
            ("reasoning", "reasoning.set", {"effort": None}),
        )


def _context_label(tokens: Any) -> str:
    """A context size in the unit people say it in.

    `1048576` is a megabyte of digits; `1M` is what a person would call it.
    Anything at or above a million is shown in millions, because rounding
    1,048,576 down to `1048K` is the kind of accuracy nobody asked for.
    """
    try:
        n = int(tokens)
    except (TypeError, ValueError):
        return ""
    if n <= 0:
        return ""
    if n >= 1_000_000:
        # Rounded to one decimal, not `:g`. 1048576 is 1.048576M, and `:g`
        # printed all of them -- `1.04858M ctx`, which is more precision than
        # the word "about" and less than anyone reads.
        return f"{round(n / 1_000_000, 1):g}M ctx"
    return f"{n // 1000}K ctx"


def _price_label(pricing: Any) -> str:
    """What a model costs, in the provider's own numbers.

    **Absent is not free.** An entry with no `pricing` object gets no label,
    because a gateway that publishes nothing has not said the model costs
    nothing. Both prices zero *is* a statement, and reads as "Free".
    """
    if not isinstance(pricing, dict) or not pricing:
        return ""
    price_in = float(pricing.get("input", 0) or 0)
    price_out = float(pricing.get("output", 0) or 0)
    if price_in == 0 and price_out == 0:
        return "Free"
    if price_in == price_out:
        return f"${price_in:g}/M"
    return f"${price_in:g} in · ${price_out:g} out"


#: Every command the palette offers, in the order it shows them.
#:
#: **One list, and it includes the line-mode commands.** Until this existed the
#: interface had four commands and line mode had fifteen, with nine only in the
#: latter -- so choosing a frontend was choosing which half of the commands you
#: had. The palette is now the single place a person looks, and `action_commands`
#: used to print a two-line notice saying what ctrl+p did, which is not what
#: ctrl+p did.
COMMANDS: tuple[Command, ...] = (
    Command("/mode", "Switch mode: chat, build, plan, mission, skills", "pick_mode"),
    Command("/model", "Switch model", "pick_model"),
    Command("/permission", "Switch permission level", "pick_permission"),
    Command("/plan", "Show the task list", "show_plan"),
    Command("/state", "What the core reports about itself", "show_state"),
    Command("/trajectory", "Frames captured this turn", "show_trajectory"),
    Command("/usage", "What this app has spent", "show_usage"),
    Command("/tools", "Per-turn tool call budget", "show_tools"),
    Command("/reasoning", "How hard the model should think", "pick_reasoning"),
    Command("/sandbox", "Sandbox status", "show_sandbox"),
    Command("/conversations", "Saved conversations", "show_conversations"),
    Command("/new", "Start a conversation", "new_conversation"),
    Command("/key", "Provider keys in the OS keyring", "show_keys"),
    Command("/quit", "Leave", "quit"),
)


__all__ = ["COMMANDS", "CONFIRM_PRESS_S", "SIDEBAR_MIN_WIDTH", "TURN_TIMEOUT_S", "TonyApp"]
