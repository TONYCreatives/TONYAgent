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

import subprocess
import threading
from typing import Any, ClassVar, Optional

from rich.cells import cell_len
from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Footer, Input, OptionList, Static
from textual.widgets.option_list import Option

from tonyagent.cli import theme
from tonyagent.cli.client import CoreClient, CoreError
from tonyagent.cli.delegate import (
    OpenCodeDelegate,
    opencode_available,
    opencode_command,
)
from tonyagent.cli.render import (
    _argument_summary,
    _context_label,
    _one_line,
    _result_summary,
    pad_to,
    truncate_to_width,
)
from tonyagent.cli.widgets import (
    ChangeHeader,
    Command,
    CommandPalette,
    ConfirmDialog,
    ConfirmScreen,
    ConversationsDialog,
    DiffBlock,
    KeyDialog,
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
#: Under this there is no width left that keeps both a readable transcript and
#: a panel, and everything the panel holds is carried by the status line -- see
#: `_refresh_status`, which exists for these sizes.
SIDEBAR_MIN_WIDTH = 80

#: At and above this many columns the sidebar gets the width in the CSS.
#:
#: Between this and `SIDEBAR_MIN_WIDTH` it is drawn compact. **The old rule was
#: a single threshold at 108, and 108 is wider than a plain console window is**:
#: 1920 pixels at a readable font is about 106 columns, so the panel was
#: invisible for exactly the people who never resize the window -- every fact in
#: it (mode, model, permission, the context meter) and no way to know it was
#: there. Hiding a panel rather than squeezing it is the window's rule, and it
#: needs a window's menu bar to hide things in.
SIDEBAR_WIDE_WIDTH = 108

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
        # The keyboard route to the top bar's `+`. A click is never the only
        # way to reach a feature, and this key is bound nowhere else.
        Binding("ctrl+n", "new_chat", "new chat", show=False),
        # Reading back through a turn without reaching for the wheel.
        # `VerticalScroll` scrolls itself only while it has the focus, and the
        # focus is in the composer, so these are done by hand.
        Binding("pageup", "transcript_up", "page up", show=False),
        Binding("pagedown", "transcript_down", "page down", show=False),
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
        #: The OpenCode backend, or None for the core. Two backends rather
        #: than two providers, because OpenCode executes its own tools: see
        #: `delegate` for why a provider adapter would run them twice.
        self._delegate: Optional[OpenCodeDelegate] = None
        #: The column the top bar's `+` occupies, for hit-testing a click.
        self._new_chat_column: Optional[int] = None
        #: The open chat's name, kept so the bar can be redrawn when the
        #: backend changes without a `conversations.list` call to get it again.
        self._topbar_title = ""
        #: The last `context.get` reply, kept for the status line -- below
        #: `SIDEBAR_MIN_WIDTH` there is no sidebar and the meter is the one
        #: number that has no other home.
        #:
        #: **Never called `_context`.** `textual.app.App._context` is a method
        #: -- `run_test` opens with `with app._context():` -- and an instance
        #: attribute of that name shadows it with a dict, so the app's own task
        #: died of `'dict' object is not callable` before `on_mount` and every
        #: `run_test` test hung forever on `app_ready_event`. Textual has no
        #: `_last_context`, which is also the shape `_last_catalog` already uses.
        self._last_context: dict[str, Any] = {}
        #: The clickable stretches of the status line, as `(start, end,
        #: target)` in cells. Rebuilt by every `_refresh_status`, and cell
        #: offsets rather than character offsets because that is what a click
        #: arrives as.
        self._status_spans: list[tuple[int, int, str]] = []
        #: Prompts that were actually sent, oldest first, for the up arrow.
        #: Turns only: a slash command is typed once and lives in the palette.
        self._history: list[str] = []
        #: Where a browse through `_history` has got to, or None when what is
        #: in the field is the user's own text rather than a recalled prompt.
        self._history_at: Optional[int] = None
        #: The last `models.catalog` reply, so the delegate's rows can say
        #: which of them the core also serves. One list, two routes.
        self._last_catalog: list[Any] = []
        #: What the open picker will set, so one handler serves both.
        self._picker_action: Optional[tuple[str, str, dict[str, Any]]] = None

    # -- layout --------------------------------------------------------------

    def compose(self) -> ComposeResult:
        # The open tab, at the very top, above everything.
        #
        # **One tab, because the core holds one conversation.** There is no
        # second session to have open, so a strip with one entry is not a
        # pretence of tabs -- it is the name of the one that is open, in the
        # place a person looks first. It doubles as the way into the chat list,
        # which is why it is clickable.
        yield Static("", id="topbar")
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
        """How much room the sidebar gets -- or none at all.

        Three sizes rather than two: full, compact, and gone. The compact size
        is a real one because a console window that is 97 columns wide is a
        normal window, not a degenerate case, and a panel that only appears on a
        maximized 1920-pixel display is a panel most people never see.

        When it is gone the status line is what remains, which is why the meter
        and the permission level live there as well.
        """
        sidebar = self.query_one("#sidebar", Sidebar)
        width = self.size.width
        sidebar.display = width >= SIDEBAR_MIN_WIDTH
        if sidebar.display:
            # The width itself is the stylesheet's, including the compact one:
            # a number here as well would be a second place to keep it right.
            sidebar.set_class(width < SIDEBAR_WIDE_WIDTH, "compact")

    # -- the transcript ------------------------------------------------------

    def _welcome(self) -> str:
        """The opening panel, as a Markdown widget like every other message.

        Handing back markup from `render()` would leave the asterisks on
        screen, because markup is a Rich feature and this returns a `Text`.
        """
        return (
            f"TONYAgent {self._version()} · terminal\n\n"
            "ctrl+p commands · ctrl+n new chat · ctrl+c twice interrupts · ctrl+d quit\n"
            "click a sidebar row for mode, model or permission · "
            "click a tool call for its output · ↑ recalls your last prompt"
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
        """Fence a new turn, and draw the question that opened it.

        **The user's own message was missing entirely** -- stored on the `Turn`
        and never mounted, so the transcript showed the agent answering a
        question nobody could see. That is the worse half of a conversation to
        lose, and no test asked about it, because every test drove the turn
        directly rather than sending one.

        Shaped like the window's: a chip on `--raised`, which is what
        `transcript.css` says distinguishes it from the assistant's prose. A
        terminal has no bubbles, so the fill and the marker carry it.
        """
        transcript = self.query_one("#transcript", VerticalScroll)
        self.turn = Turn(text=text)
        self._turn_box = Vertical(classes="turn turn-rule")
        transcript.mount(self._turn_box)

        prompt = Static("")
        self._turn_box.mount(prompt)
        prompt.update(Text(f"{theme.prompt_marker()} {_one_line(text)}", style=theme.FG))
        prompt.add_class("prompt")

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

        **A tick that arrives once the app is stopping is a no-op.**
        `App._shutdown` flips `_running` first and stops the app's timers last
        -- `_close_all` closes the widget pumps in between -- so a tick queued
        in that window reaches a screen that no longer has a `#sidebar`. The
        query raised `NoMatches` into `app._exception`, which `run_test`
        re-raises at exit, so a test with several app sessions in it failed on
        the strength of a poll that had nothing left to poll.
        """
        if not self.is_running:
            return
        try:
            self.state = self.client.call("state", timeout=5) or {}
        except CoreError:
            return
        sidebar = self.query_one("#sidebar", Sidebar)
        sidebar.update_state(self.state)
        self._refresh_conversation_title(sidebar)
        self._refresh_context()
        self._refresh_status()

    def _refresh_conversation_title(self, sidebar: Sidebar) -> None:
        """Name the open chat, in the top bar and in the sidebar.

        Read from `conversations.list` rather than cached, because `state`
        reports only the id -- and an id is not something a person can tell
        two chats apart by. One request, and only while a conversation is
        open.
        """
        conversation_id = str(self.state.get("conversation") or "")
        title = ""
        if conversation_id:
            try:
                payload = self.client.call("conversations.list", timeout=5) or {}
            except CoreError:
                payload = {}
            for row in payload.get("conversations") or []:
                if isinstance(row, dict) and str(row.get("id")) == conversation_id:
                    title = str(row.get("title") or "(untitled)")
                    break
        sidebar.set_conversation(title)
        self._topbar_title = title
        self._render_topbar(title)

    def _render_topbar(self, title: str) -> None:
        """The one open tab.

        **The chat name leads, and that is a correction.** The reference this
        was modelled on shows a single word in the tab position -- "Build" --
        and that is a name somebody gave a conversation, not a mode. I read it
        as the mode and put mode first, which made the tab say what the agent
        is *allowed* to do rather than what it is *doing it about*. Those are
        different facts and only one of them identifies the thing on screen.

        So: the chat, marked with the accent bar that stands in for a selected
        tab, then the mode dimmed beside it. One tab, because the core holds
        one conversation -- there is no second session to have open, so this is
        not a pretence of tabs, it is the name of the one that is.

        The name itself is not a button: it sits mid-line, so a click on it
        would have to be hit-tested to a column with nothing to aim at. The
        sidebar's `Chat` row opens the same list with a whole row to hit
        (`Sidebar.on_click`), and `/conversations` does it from the keyboard --
        which is why this says where to go rather than inviting a click.
        """
        topbar = self.query_one("#topbar", Static)
        text = Text()
        if title:
            text.append(f"{theme.tab_marker()} ", style=theme.ACCENT)
            text.append(truncate_to_width(title, 48), style=f"bold {theme.FG}")
        else:
            text.append(f"{theme.tab_marker()} ", style=theme.ACCENT)
            text.append("no conversation", style=theme.FG_MUTE)
        text.append("  ")
        # The column the `+` lands in, remembered so the click is hit-tested
        # against one cell rather than against the whole bar.
        self._new_chat_column = text.cell_len
        text.append("+", style=theme.ACCENT)
        text.append("  ")
        mode = str(self.state.get("mode") or "")
        text.append(mode or "-", style=theme.FG_MUTE)
        text.append("   ")
        if self._delegate is not None:
            # Named, not styled: which agent is running is the one fact a turn's
            # transcript cannot tell you, because both backends draw the same
            # events into the same widgets.
            text.append("opencode", style=theme.WARN)
            if self._delegate is not None and self._delegate.model:
                text.append(
                    f" · {truncate_to_width(self._delegate.model, 28)}",
                    style=theme.FG_MUTE,
                )
            text.append(" · --auto", style=theme.FG_MUTE)
        text.append("   ")
        text.append("/conversations", style=theme.FG_MUTE)
        topbar.update(text)

    def on_click(self, event: Any) -> None:
        """The clicks this app acts on, and nothing else.

        **This is safe where a click on a floating dialog would not be.** A
        terminal reports a click by position, so a button laid over the
        transcript is hit while the person meant the text. Both of these are
        rows of the chrome -- above and below everything -- so a click there
        was always aimed at the row, and a click anywhere else reaches the
        transcript and is left alone.

        The `+` is hit-tested against a single column because the top bar is
        one `Static`; the status line is hit-tested against per-part spans for
        the same reason. The sidebar does its own, because it is a widget with
        rows of its own to find (see `Sidebar.on_click`).

        Every one of these has a keyboard route -- `ctrl+shift+n`, `/new`,
        `ctrl+1`, `ctrl+2`, `ctrl+3`, `ctrl+4` -- because a click is never the
        only way to reach a feature, and because on a terminal narrower than
        `SIDEBAR_MIN_WIDTH` there is no sidebar to click at all.
        """
        if event.widget is self.query_one("#topbar", Static):
            column = getattr(self, "_new_chat_column", None)
            if column is None or event.offset.x != column:
                return
            event.stop()
            self._new_conversation()
            return
        if event.widget is self.query_one("#status", Static):
            self._click_status(event)

    def _click_status(self, event: Any) -> None:
        """Which part of the status line was clicked, by column.

        The meter and the permission level are here rather than only in the
        sidebar because the sidebar is dropped below `SIDEBAR_MIN_WIDTH` -- so
        on a narrow terminal this is the only place either can be clicked, and
        the only place the meter appears at all.
        """
        x = int(getattr(event.offset, "x", -1))
        for start, end, target in self._status_spans:
            if start <= x < end:
                event.stop()
                self._open_row(target)
                return

    def on_sidebar_picked(self, message: Sidebar.Picked) -> None:
        """A sidebar row was clicked: open what it names."""
        self._open_row(str(message.target))

    def _open_row(self, target: str) -> bool:
        """Open whatever a clicked row names. False if it names nothing.

        One table for both the sidebar and the status line, because they name
        the same four things and two tables would be two places for the meter
        and the permission picker to drift apart.
        """
        actions = {
            "mode": self._pick_mode,
            "model": self._pick_model,
            "permission": self._pick_permission,
            "chat": self._show_conversations,
            # The keyboard route is `ctrl+4`, and this is the same request: the
            # core's own numbers, never a count kept here.
            "context": self._refresh_context,
        }
        action = actions.get(target)
        if action is None:
            return False
        action()
        return True

    def _refresh_context(self) -> None:
        try:
            payload = self.client.call("context.get", timeout=5) or {}
        except CoreError:
            return
        self._last_context = payload
        self.query_one("#sidebar", Sidebar).update_context(payload)
        # The status line carries the same measurement, because below
        # `SIDEBAR_MIN_WIDTH` there is no sidebar and the meter is the one
        # number that has no other home. Without this the meter simply vanishes
        # on a narrow terminal, which is where it would matter most.
        self._refresh_status()

    def _refresh_status(self) -> None:
        """The one line that is always on screen.

        **The context meter and the permission level live here, not only in the
        sidebar.** Everything else the sidebar holds is already duplicated --
        mode in the top bar, model and project here -- so dropping the sidebar
        on a narrow terminal was costing exactly two things: how full the
        context is, and how much the agent is allowed to do. Both are things
        people come to a status line *for*, and both were silently absent on
        any terminal narrower than the panel's own floor.

        So the sidebar is now the *expanded* view and this is the floor. The
        numbers are the core's own -- `context.get`, never counted here -- and
        when the core cannot measure, this says which half is missing rather
        than drawing an empty bar at 0%.
        """
        from tonyagent.cli.repl import _basename

        project = str(self.state.get("project") or "")
        left = _basename(project) if project else "no project"
        bound = bool(self.state.get("bound"))
        right = str(self.state.get("model")) if bound else "no provider bound"

        # Each part carries what a click on it should open. The project name
        # opens nothing: there is no picker for "which folder", only the
        # sidebar's own and the `-C` flag.
        rows: list[tuple[str, str]] = [(left, ""), (right, "model" if bound else "")]
        permission = str(self.state.get("permission") or "")
        if permission:
            rows.append((permission, "permission"))
        rows.append((self._context_summary(), "context"))

        # Composed by hand rather than with `join`, because the spans have to
        # be known: a click arrives as a column, and ` · ` is three cells.
        line = " "
        spans: list[tuple[int, int, str]] = []
        for value, target in rows:
            if not value:
                continue
            if line.strip():
                line += " · "
            start = cell_len(line)
            line += value
            if target:
                spans.append((start, cell_len(line), target))
        self._status_spans = spans

        status = self.query_one("#status", Static)
        status.update(line)
        status.set_class(bound, "bound")

    def _context_summary(self) -> str:
        """How full the context is, in as few characters as say it.

        Compact because this line has to survive an 80-column terminal next to
        the project and the model. The words are the same ones the sidebar
        uses -- including *which* half of the measurement is missing, since
        "unknown" without that is a shrug.
        """
        used = int(self._last_context.get("used") or 0)
        window = int(self._last_context.get("window") or 0)
        known = bool(self._last_context.get("known"))
        if not known:
            return (
                "ctx unknown"
                if not window
                else f"ctx ?/{_context_label(window, suffix='')}"
            )
        if window <= 0:
            return f"ctx {_context_label(used, suffix='')}/?"
        if used <= 0:
            return f"ctx 0/{_context_label(window, suffix='')}"
        return (
            f"ctx {_context_label(used, suffix='')}"
            f"/{_context_label(window, suffix='')}"
        )

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
        elif event.key in ("up", "down") and not self._pending_ask:
            # The composer's, once the inline list is closed. A single-line
            # `Input` has nothing to do with these keys, and a prompt already
            # typed once is the most expensive thing in here to type twice.
            if self._recall(-1 if event.key == "up" else 1):
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
        self._remember(text)
        self._begin_turn(text)
        self._send(text)

    def _remember(self, text: str) -> None:
        """Keep a sent prompt for the up arrow.

        A repeat of the newest entry is not stored twice: a run of the same
        prompt is one prompt, and up-arrowing through five copies of it is
        worse than up-arrowing through one.
        """
        if not self._history or self._history[-1] != text:
            self._history.append(text)
        self._history_at = None

    def _recall(self, direction: int) -> bool:
        """Walk through sent prompts, as a shell does. True if it acted.

        Only while the field is empty or a prompt is already recalled: with a
        half-typed line in the field, up and down belong to whoever typed it,
        and stealing them would lose text they were still working on. Walking
        past the newest prompt lands on an empty field again, which is where
        the browse started rather than a wall to be stuck against.
        """
        composer = self.query_one("#composer", Input)
        if not self._history:
            return False
        if composer.value and self._history_at is None:
            return False
        if self._history_at is None and direction > 0:
            return False
        index = len(self._history) if self._history_at is None else self._history_at
        index += direction
        if index < 0:
            return False
        if index >= len(self._history):
            self._history_at = None
            composer.value = ""
            composer.cursor_position = 0
            return True
        self._history_at = index
        composer.value = self._history[index]
        # The caret after the recalled text, so typing continues it rather than
        # landing in front of it.
        composer.cursor_position = len(composer.value)
        return True

    def _send(self, text: str) -> None:
        """Send a turn without blocking the UI thread.

        `send` only returns when the turn is over, and a turn can run for
        minutes, so it goes to a worker. That is also what lets the composer
        answer a confirmation while the turn is still in flight.

        **The delegate runs here too, and in the same place deliberately.** The
        two backends differ in who executes the tools, not in how a turn is
        dispatched, so keeping them at one seam means the transcript, the
        footer and the interrupt are the same code either way -- there is no
        second rendering path to drift.
        """
        delegate = self._delegate

        def worker() -> None:
            if delegate is not None:
                delegate.run(text)
                return
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

        **`/model` follows whichever backend is running.** When the delegate is
        on it lists what `opencode models` says and sets the delegate's model;
        otherwise it reads `models.catalog` from the core. Showing the core's
        three providers while OpenCode is the one taking the turns is worse than
        showing nothing -- the list looks authoritative and every row in it is
        inert -- and it is where someone goes looking for a model they just
        enabled.

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
        # Kept so the delegate's rows can be matched against it.
        self._last_catalog = models
        # Asked for first, because it decides which rows exist at all: a model
        # the core serves *and* OpenCode serves is one row naming both routes,
        # not two rows that look like two models.
        opencode_ids = self._opencode_model_ids()

        def route_note(model_id: str) -> str:
            # Leading space, so it reads as a suffix on the numbers rather than
            # running into them: "Free·  also via opencode" was not a thing.
            return "  ·  also via opencode" if model_id in opencode_ids else ""

        entries: list[PickerEntry] = []
        if current and current in by_id:
            # The current row carries its numbers too. Leaving them off would
            # make the model you are on the one row you cannot compare.
            entries.append(
                PickerEntry(f"core:{current}", current, group="current",
                            note=f"·  {note_for(by_id[current])}".rstrip()
                                 + route_note(current))
            )
        for model_id in sorted(by_id, key=lambda i: (group_of(i), i)):
            if model_id == current:
                continue
            entries.append(
                PickerEntry(f"core:{model_id}", model_id,
                            group=_GROUP_OF_PROVIDER.get(
                                group_of(model_id), group_of(model_id)),
                            note=(note_for(by_id[model_id]) + route_note(model_id)).strip())
            )

        entries.extend(
            self._delegate_model_entries(opencode_ids, skip=set(by_id))
        )

        # **Merged by group, not concatenated.** The delegate's rows are built
        # after the core's and land after them, which put a second "OpenCode Go"
        # heading at the bottom of the list -- the same subscription, the same
        # heading, twice, and it read as two. Grouping first and flattening
        # second is what makes "aligned" true rather than approximately true.
        order = ["current", "OpenCode Go", "OpenCode Zen",
                 "OpenCode free (client only)", "OpenRouter"]
        by_group: dict[str, list[PickerEntry]] = {}
        for entry in entries:
            by_group.setdefault(entry.group, []).append(entry)
        entries = [
            row
            for group in order + [g for g in by_group if g not in order]
            for row in by_group.get(group, [])
        ]

        self.push_screen(
            PickerDialog(
                "select model", entries,
                hint=(
                    f"{len(by_id)} core · "
                    f"{sum(1 for e in entries if e.value.startswith('delegate:'))} "
                    "via opencode · enter select · esc close"
                ),
            ),
            self._apply_model_choice,
        )

    def _apply_model_choice(self, value: Optional[str]) -> None:
        """Send a chosen row to whichever backend can actually run it.

        **The route is carried in the value, because it cannot be inferred.**
        A row can name a model the core serves (`core:opencode-go/kimi-k3`) or
        one only OpenCode will serve (`delegate:opencode/space-bunny-free`), and
        picking the second has to start the delegate -- otherwise the selection
        would be accepted, announced, and then ignored by every turn.

        Picking a core model while the delegate is running turns it off, for the
        same reason: a model that is chosen and not used is worse than one that
        was never offered.
        """
        if not value:
            return
        if value.startswith("delegate:"):
            self._start_delegate(value.split(":", 1)[1])
            return
        model_id = value.split(":", 1)[1] if ":" in value else value
        # Polled here rather than trusted from the caller. `_pick_model` already
        # polls, so this is belt-and-braces -- but the failure it prevents is
        # the one the code next door warns about: an empty provider name makes
        # `bind_provider` fail at the core, having looked like a selection the
        # user made correctly.
        self._poll_state()
        if self._delegate is not None:
            self._delegate.close()
            self._delegate = None
        self._set(
            "bind_provider",
            {"name": str(self.state.get("provider") or ""), "model": model_id},
            "model",
        )
        self._render_topbar(self._topbar_title)

    def _opencode_model_ids(self) -> set[str]:
        """What `opencode models` currently lists, or nothing.

        Failing quietly is the point: a missing binary, a timeout or an
        unfamiliar output shape should cost the delegate's rows and nothing
        else. The core's list is the one that matters, and it must still open.
        """
        try:
            if not opencode_available():
                return set()
            return set(self._delegate_models())
        except Exception:  # noqa: BLE001 - see above
            return set()

    def _delegate_model_entries(
        self, opencode_ids: set[str], *, skip: set[str]
    ) -> list[PickerEntry]:
        """OpenCode's models the core cannot serve, as rows.

        **`only` is the exclusion, and it is the point.** `opencode models`
        returns both `opencode-go/…` and `opencode/…`, and `opencode-go` is
        *also* a core provider serving the same ids. Adding those as rows too
        produced `opencode-go/deepseek-v4-pro` twice -- once priced, once not --
        which reads as two models rather than one with two ways in.

        So a model the core already lists is *not* repeated here; its core row
        gains "also via opencode" instead, and what is left is genuinely
        OpenCode's alone. The free tier is most of that remainder, and it is
        the only part the core cannot reach at all.

        `opencode_ids` is passed in rather than fetched again: this runs inside
        the same picker that just asked, and the second call would have been a
        second `opencode models` for the same answer.
        """
        entries: list[PickerEntry] = []
        for model_id in sorted(opencode_ids - skip):
            prefix = model_id.split("/", 1)[0]
            entries.append(
                PickerEntry(
                    f"delegate:{model_id}",
                    model_id,
                    group=_GROUP_OF_PROVIDER.get(prefix, prefix),
                    note="opencode only",
                )
            )
        return entries

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
            self._run_command(match.run, argument)

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
        if self._delegate is not None:
            # **A kill, not a request.** There is no socket here and no protocol
            # to say "stop" through; the process is the cancellable unit. That
            # is sharper than the core's cancel, and it is why the top bar names
            # the backend rather than leaving it to be discovered.
            self._delegate.interrupt()
            self._notice("killed the opencode process", "warn")
            return
        try:
            self.client.notify("cancel", {})
        except CoreError as exc:
            self._notice(str(exc), "error")
            return
        self._notice("cancelled", "warn")

    def _toggle_delegate(self, argument: str = "") -> None:
        """Turn the OpenCode backend on or off, optionally with a model.

        Going on checks the binary is actually there, because a backend that
        fails on the first message is worse than one that declines to start: the
        failure lands in the transcript where it reads as a model problem rather
        than a missing program.

        **A model has to be chosen, because the default is the problem.** With
        no `--model`, `opencode run` uses whatever OpenCode has configured --
        which is not a free model unless you made it one. The whole reason to be
        here is the free tier, so `/delegate` with no argument opens the picker
        rather than starting on somebody else's billing.
        """
        if self._delegate is not None:
            self._delegate.close()
            self._delegate = None
            self._notice("back to the core: your tools and permissions", "ok")
            self._render_topbar(self._topbar_title)
            return
        if not opencode_available():
            self._notice("the opencode binary is not on PATH", "error")
            return
        wanted = argument.strip()
        if not wanted:
            # One picker, reached two ways: `/delegate` to start and `/model`
            # to change once running. Two lists for one set of models is how a
            # model ends up settable in one and not the other.
            entries = [
                PickerEntry(
                    mid,
                    mid,
                    group="free" if mid.endswith("-free") else "other",
                    note="free" if mid.endswith("-free") else "",
                )
                for mid in self._delegate_models()
            ]
            if not entries:
                self._notice("opencode listed no models", "error")
                return
            self.push_screen(
                PickerDialog(
                    "delegate model", entries,
                    hint="enter start opencode on this model · esc cancel",
                ),
                lambda chosen: (self._start_delegate(chosen) if chosen else None),
            )
            return
        self._start_delegate(wanted)

    def _set_delegate_model(self, model: str) -> None:
        """Swap the delegate's model on a running backend.

        In place rather than by restarting: the process is not up while no turn
        is running, and rebuilding the delegate would throw away the OpenCode
        session id -- which is the conversation.
        """
        assert self._delegate is not None
        self._delegate.model = model
        self._notice(f"opencode model: {model}", "ok")
        self._render_topbar(self._topbar_title)

    def _start_delegate(self, model: str) -> None:
        self._delegate = OpenCodeDelegate(
            lambda kind, payload: self.call_from_thread(
                self._apply_core_event, kind, payload
            ),
            model=model,
        )
        self._notice(
            f"opencode · {model} · --auto (no permission prompts)", "warn",
        )
        self._render_topbar(self._topbar_title)

    def _delegate_models(self) -> list[str]:
        """Model ids for the delegate, read from OpenCode itself.

        Asked of `opencode` rather than hardcoded, for the same reason
        `providers.list` is asked of the registry: a list copied into this file
        drifts silently the first time OpenCode renames anything, and the free
        tier is exactly the set that moves.

        **`opencode models` takes no provider argument.** The first version
        passed one and got an exit-1 usage message parsed as an empty list,
        which would have shown a picker with nothing in it and no reason why.
        It prints one `provider/model` id per line and nothing else.
        """
        try:
            completed = subprocess.run(  # noqa: S603 - argv is a list
                [*opencode_command(), "models"],
                capture_output=True, text=True, timeout=30, check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return []
        if completed.returncode != 0:
            return []
        return [
            row.strip()
            for row in (completed.stdout or "").splitlines()
            if row.strip().startswith("opencode")
        ]

    def action_transcript_up(self) -> None:
        """Page the transcript back, by key.

        The scrollbar and the wheel are not always there -- a wheel is not on
        every keyboard, and a scrollbar is one column wide in a terminal.
        """
        self.query_one("#transcript", VerticalScroll).scroll_page_up(animate=False)

    def action_transcript_down(self) -> None:
        """And forward again."""
        self.query_one("#transcript", VerticalScroll).scroll_page_down(animate=False)

    def action_new_chat(self) -> None:
        """The keyboard route to the top bar's `+`, and `/new`."""
        self._new_conversation()

    def action_commands(self) -> None:
        """Open the palette. It used to print a notice about ctrl+p, which is
        not what ctrl+p does -- the shortest possible version of the same
        mistake, and the reason the palette is worth a test."""
        self.push_screen(CommandPalette(COMMANDS), self._run_command)

    def _run_command(self, run: Optional[str], argument: str = "") -> None:
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
            "toggle_delegate": self._toggle_delegate,
            "quit": self.exit,
        }.get(run)
        if handler is None:
            self._notice(f"{run} is listed but not wired up", "warn")
            return
        # Only the handlers that declare an argument are given one. Guessing
        # from whether a string was typed would call `_show_trajectory("x")` on
        # a stray word and raise TypeError out of the keypress handler.
        if argument and _takes_argument(handler):
            handler(argument)
        else:
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
        """The chat list as a dialog, not a paragraph.

        It used to print titles into the transcript, where they scrolled past
        with no way to open one. A list you cannot act on is a list you have no
        reason to ask for.
        """
        try:
            payload = self.client.call("conversations.list") or {}
        except CoreError as exc:
            self._notice(str(exc), "error")
            return
        rows = [c for c in (payload.get("conversations") or []) if isinstance(c, dict)]
        self.push_screen(
            ConversationsDialog(rows, str(self.state.get("conversation", ""))),
            self._conversation_chosen,
        )

    def _conversation_chosen(self, result: Optional[str]) -> None:
        """Act on what the chat list returned.

        The sentinel-prefixed values keep one dismissal channel for every
        action, rather than a callback per action -- and there is no way to
        confuse an id for an instruction, because ids are server-assigned and
        contain no colons.
        """
        if not result:
            return
        if result == "__new__":
            self._new_conversation()
            return
        if result.startswith("__duplicate__:"):
            target = result.split(":", 1)[1]
            self._call("conversations.duplicate", {"id": target}, "duplicated")
            self._show_conversations()
            return
        if result.startswith("__rename__:"):
            _, target, title = result.split(":", 2)
            self._call("conversations.rename", {"id": target, "title": title}, "renamed")
            self._show_conversations()
            return
        if result.startswith("__delete__:"):
            target = result.split(":", 1)[1]
            self._call("conversations.delete", {"id": target}, "deleted")
            self._poll_state()
            self._show_conversations()
            return
        self._switch_conversation(result)

    def _switch_conversation(self, conversation_id: str) -> None:
        """Open a conversation and redraw its transcript.

        `conversations.switch` returns the messages, so the history is drawn
        from that rather than asked for again -- and it is drawn, because a
        reopened chat showing an empty transcript would read as a failed click.
        """
        try:
            payload = self.client.call("conversations.switch", {"id": conversation_id})
        except CoreError as exc:
            self._notice(str(exc), "error")
            return
        self._clear_transcript()
        title = str((payload.get("conversation") or {}).get("title") or "(untitled)")
        self._notice(f"opened {title}", "warn")
        for message in payload.get("messages") or []:
            self._replay_message(message)
        self._poll_state()

    def _clear_transcript(self) -> None:
        transcript = self.query_one("#transcript", VerticalScroll)
        for child in list(transcript.children):
            child.remove()
        self.turn = None
        self._turn_box = None

    def _replay_message(self, message: Any) -> None:
        """Draw one message from a reopened conversation.

        **The shape here is the window's, not a guess.** `showMessages` in
        `App.tsx` is the code that already reads saved history, and it settles
        three things this first version got wrong:

        * `content` is a string *or a list of parts*, and the parts carry the
          text. Reading it as a string only is why a reopened chat came back
          **empty** for any conversation with an attachment -- the shape was
          never wrong for a plain message, which is why the test passed.
        * **`role: "tool"` rows are not replayed.** Their content is the raw
          tool output -- a whole file for `read_file`, stdout for a command --
          and the window's comment says why it must not be shown: restored
          history has no tool card to put it in, so it squirts unrelated source
          into the transcript ahead of the answer written from it.
        * A saved message is **finished by definition**, so nothing waits on a
          `reasoning.completed` that was sent hours ago.
        """
        if not isinstance(message, dict):
            return
        role = str(message.get("role", ""))
        if not role:
            return
        if role == "tool":
            # See the module note: the assistant prose that came out of this
            # work stays, which is what the chat is for.
            return

        text = _message_text(message.get("content"))
        if not text.strip():
            return

        from rich.markdown import Markdown

        transcript = self.query_one("#transcript", VerticalScroll)
        if role == "user":
            widget = Static("")
            widget.add_class("prompt")
            widget.update(Text(f"{theme.prompt_marker()} {_one_line(text)}", style=theme.FG))
        else:
            widget = Static(Markdown(text))
        transcript.mount(widget)

    def _call(self, method: str, params: dict[str, Any], label: str) -> None:
        """One request, and say what it did."""
        try:
            self.client.call(method, params)
        except CoreError as exc:
            self._notice(str(exc), "error")
            return
        self._notice(label, "warn")
        self._poll_state()

    def _new_conversation(self) -> None:
        try:
            self.client.call("conversations.create", {})
        except CoreError as exc:
            self._notice(str(exc), "error")
            return
        self._poll_state()
        self._notice("new conversation", "warn")

    def _show_keys(self) -> None:
        """Set, replace and remove provider keys, from inside the TUI.

        **This used to print a read-only list**, which made `/key` a thing you
        could look at and not a thing you could do. The core has had
        `key.save`, `key.delete` and `key.activate` all along; the frontend
        called only `key.list`. So adding a provider meant leaving the terminal
        for the window -- which is the whole reason somebody ends up asking
        whether the two can be linked, when the gap is one screen wide and on
        this side of it.

        The typed value goes straight into `key.save` and is never rendered,
        stored on the app, or put in a notice. `key.reveal` is deliberately not
        called: the core already argues that a method returning a secret is a
        method whose secret can end up in a screenshot, and nothing about a
        terminal being the only UI here makes that cheaper.
        """
        providers: list[tuple[str, bool]] = []
        keys: dict[str, list[tuple[str, bool]]] = {}
        try:
            listed = self.client.call("providers.list") or {}
            for entry in listed.get("providers") or []:
                if isinstance(entry, dict):
                    name = str(entry.get("name") or "")
                    if name:
                        providers.append(
                            (name, bool(entry.get("has_credentials")))
                        )
            for entry in self.client.call("key.list") or {}:
                if isinstance(entry, dict):
                    name = str(entry.get("provider") or "")
                    if name:
                        keys.setdefault(name, []).append(
                            (str(entry.get("name") or "default"),
                             bool(entry.get("active")))
                        )
        except CoreError as exc:
            self._notice(str(exc), "error")
            return

        # A key can outlive the provider it was saved for. Those rows are added
        # too, because a secret in the keyring that no screen admits to is a
        # secret nobody can revoke.
        known = {name for name, _ in providers}
        providers.extend((name, True) for name in keys if name not in known)
        if not providers:
            self._notice("this build registers no providers", "warn")
            return

        def chosen(request: Any) -> None:
            if request is not None:
                self._apply_key_request(request)

        self.push_screen(
            KeyDialog(providers, keys=keys),
            chosen,
        )

    def _apply_key_request(self, request: Any) -> None:
        """Carry out what the key dialog asked for.

        Removal asks first. It is the one branch where the dialog's `ctrl+x`
        could destroy something a person cannot retype, and the dialog is a
        field-and-a-list rather than a place where a destructive key should be
        enough on its own.
        """
        provider = str(request.provider)
        name = str(request.name or "default")
        if request.action == "remove":
            self.push_screen(
                ConfirmScreen(
                    "Remove this provider key?",
                    f"{provider} / {name} -- you will need to paste it again",
                ),
                lambda ok: self._delete_key(provider, name) if ok else None,
            )
            return
        try:
            reply = self.client.call(
                "key.save", {"provider": provider, "api_key": request.key, "name": name}
            ) or {}
        except CoreError as exc:
            self._notice(str(exc), "error")
            return
        self._notice(f"saved {provider} / {name}", "ok")
        if not reply.get("listed", True):
            # The key *is* stored; only the name registry failed. Saying "saved"
            # and stopping there would send the user round again to re-paste it.
            self._notice("saved, but its name could not be recorded", "warn")
        self._poll_state()

    def _delete_key(self, provider: str, name: str) -> None:
        try:
            self.client.call(
                "key.delete", {"provider": provider, "name": name}
            )
        except CoreError as exc:
            self._notice(str(exc), "error")
            return
        self._notice(f"removed {provider} / {name}", "ok")
        self._poll_state()

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


#: How a provider's models are headed in the picker.
#:
#: **These are services, not strings.** `opencode-go` is a core provider *and*
#: appears in `opencode models`, so a literal `split("/")` gives two different
#: headings for one subscription, which reads as two. And `opencode/` -- the
#: client-only tier -- genuinely cannot be reached from the core at all, so it
#: is a separate heading rather than a row with a footnote.
_GROUP_OF_PROVIDER = {
    "opencode-go": "OpenCode Go",
    "opencode-zen": "OpenCode Zen",
    "opencode": "OpenCode free (client only)",
    "openrouter": "OpenRouter",
}


def _takes_argument(handler: Any) -> bool:
    """Whether a command handler accepts the typed argument."""
    import inspect

    try:
        return bool(inspect.signature(handler).parameters)
    except (TypeError, ValueError):
        return False




def _message_text(content: Any) -> str:
    """The text of a saved message, whether it is a string or a list of parts.

    The port of `textFromContent` in `app/src/attachments.ts`, and the same in
    every particular that matters:

    * a string is the text;
    * a list is a list of parts, each of which carries `.text`;
    * **a text file arrives wrapped in `<file name="...">`**, which is wire
      formatting for the model rather than something to put in front of the
      person who attached it, so the wrapper comes off;
    * parts that are not objects, or have no text, are skipped rather than
      rendered as `None`.

    Skipping a part and rendering `"None"` are not the same mistake, and the
    window's version says which one it is making.
    """
    import re

    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    pieces: list[str] = []
    for part in content:
        if not isinstance(part, dict):
            continue
        value = part.get("text")
        if not isinstance(value, str):
            continue
        unwrapped = re.sub(r"^<file name=\"[^\"]*\">\n?", "", value)
        unwrapped = re.sub(r"\n?</file>$", "", unwrapped)
        if unwrapped.strip():
            pieces.append(unwrapped)
    return "\n\n".join(pieces)


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
    Command("/key", "Set, replace or remove a provider key", "show_keys"),
    Command("/delegate", "Run turns through OpenCode, for its free models",
            "toggle_delegate", "[model]"),
    Command("/quit", "Leave", "quit"),
)


__all__ = [
    "COMMANDS",
    "CONFIRM_PRESS_S",
    "SIDEBAR_MIN_WIDTH",
    "SIDEBAR_WIDE_WIDTH",
    "TURN_TIMEOUT_S",
    "TonyApp",
]
