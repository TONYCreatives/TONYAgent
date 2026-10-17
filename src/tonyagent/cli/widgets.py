"""Widgets for the terminal frontend, and the turn model they draw.

**The turn model is separate from the widgets on purpose.** The core's event
stream is a flat sequence of frames with no idea what a "turn" is, and a widget
that tried to work that out while drawing would be doing two jobs at once. So
`Turn` accumulates frames into the shape a person reads -- body text, tool
calls, reasoning, a footer -- and the widgets render whatever they are handed.

**Why a turn is rebuilt rather than appended to.** Markdown needs the whole
message before it can be rendered: a ``**bold**`` marker opened on one delta
and closed thirty tokens later is unrenderable until it closes, and a streaming
markdown renderer would have to retract and redraw. So the assistant's text is
buffered per message and re-rendered into the widget on completion. Tokens
still arrive live -- they are shown as a plain streaming line while they
accumulate -- but the formatted version appears once it is complete. That is
the same trade every streaming markdown renderer makes, and doing it here
means a half-written ``#`` heading never flashes on screen.

**The footer is measured, not estimated.** `duration` is real wall-clock.
`tokens_per_second` is counted from the `message.delta` frames that actually
arrived, so it is the rate this connection is delivering, not the provider's
billing figure.
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import PurePath
from typing import Any, ClassVar, Optional

from rich.text import Text
from textual.binding import Binding
from textual.message import Message
from textual.screen import ModalScreen
from textual.widgets import Input, OptionList, Static
from textual.widgets.option_list import Option

from tonyagent.cli.render import (
    _context_label,
    display_width,
    pad_to,
    truncate_to_width,
)


def _cap(value: str) -> str:
    """Display form: uppercase first letter, rest untouched.

    Mode and permission arrive lowercase (`build`, `medium`); model ids,
    paths and titles keep their own case and bypass this.
    """
    return value[:1].upper() + value[1:] if value else value

# --------------------------------------------------------------------------
# The turn model
# --------------------------------------------------------------------------


@dataclass
class FileChange:
    """One `file_change` artifact from a tool result.

    The window draws these with `--traj-add` and `--traj-del`; so does this.
    A terminal can carry a background as well as a foreground, so the wash
    colours are available for a diff header without inventing a second palette.
    """

    path: str
    diff: str = ""
    added: int = 0
    removed: int = 0


@dataclass
class ToolCall:
    """One tool call, from `tool.started` to its completion."""

    # `id` and `name` default so `from_result` can build one from a
    # `tool.completed` payload, which carries the result but not the call's
    # identity. The caller copies those two fields back onto the real call.
    id: str = ""
    name: str = ""
    summary: str = ""
    done: bool = False
    failed: bool = False
    result: str = ""
    #: The full result, kept because the trajectory shows `output` and `error`
    #: separately while the one-line summary shows a preview of both.
    output: str = ""
    error: str = ""
    status: str = ""
    changes: list[FileChange] = field(default_factory=list)

    def label(self) -> str:
        return f"{self.name}({self.summary})" if self.summary else self.name

    @classmethod
    def from_result(cls, payload: dict[str, Any]) -> ToolCall:
        """Read what the core actually sends on `tool.completed`.

        Mirrors `TrajectoryView.EventBody`'s `tool.completed` branch: the
        result is an object with `status`, `output`, `error` and `artifacts`,
        not the string the summary line wants. Reading it here rather than in
        the widget keeps the two renderings from disagreeing about one payload.
        """
        result = payload.get("result")
        if not isinstance(result, dict):
            return cls(result=str(result or "") if result is not None else "")
        changes: list[FileChange] = []
        artifacts = result.get("artifacts")
        if isinstance(artifacts, list):
            for artifact in artifacts:
                if not isinstance(artifact, dict) or artifact.get("type") != "file_change":
                    continue
                data = artifact.get("data")
                data = data if isinstance(data, dict) else {}
                changes.append(
                    FileChange(
                        path=str(data.get("path", "")),
                        diff=str(data.get("diff", "")),
                        added=int(data.get("added", 0) or 0),
                        removed=int(data.get("removed", 0) or 0),
                    )
                )
        return cls(
            status=str(result.get("status", "")),
            output=str(result.get("output", "") or ""),
            error=str(result.get("error", "") or ""),
            changes=changes,
        )


@dataclass
class Turn:
    """One user message and everything the agent did in response."""

    text: str = ""
    answer: str = ""
    reasoning: str = ""
    tools: list[ToolCall] = field(default_factory=list)
    error: str = ""
    started: float = field(default_factory=time.monotonic)
    #: Every frame of this turn, for the trajectory view.
    #:
    #: Kept whole because the trajectory is the raw event log rather than a
    #: summary of it -- the same choice `TrajectoryView` makes, for the same
    #: reason: a summary would lose the rows nobody thought to summarise.
    frames: list[dict[str, Any]] = field(default_factory=list)

    #: Deltas seen, for the throughput figure. Counted, not tokenised: the
    #: core streams text chunks of varying size, so this is characters per
    #: second and is labelled as such.
    streamed_chars: int = 0

    _answer_open: bool = field(default=False, repr=False)
    _reasoning_open: bool = field(default=False, repr=False)

    def on_delta(self, payload: dict[str, Any]) -> None:
        chunk = str(payload.get("text", ""))
        self.streamed_chars += len(chunk)
        if self._reasoning_open and not self._answer_open:
            self.reasoning += chunk
            return
        self.answer += chunk
        self._answer_open = True

    def take_answer(self) -> str:
        """The open message's text, and then nothing.

        Called when a tool interrupts, so the frozen widget keeps the text the
        model had said *at that point* and the next message starts empty. Without
        the reset the whole message is rendered again in the new widget, and the
        transcript shows every sentence twice -- once where it belongs and once
        where the tool call interrupted it.
        """
        text = self.answer
        self.answer = ""
        self._answer_open = False
        return text

    def elapsed(self) -> float:
        return time.monotonic() - self.started

    def rate(self) -> float:
        """Characters per second, or 0 before there is anything to measure."""
        seconds = self.elapsed()
        if seconds < 0.05 or not self.streamed_chars:
            return 0.0
        return self.streamed_chars / seconds

    def tool_by_id(self, call_id: str) -> Optional[ToolCall]:
        for call in self.tools:
            if call.id == call_id:
                return call
        return None


# --------------------------------------------------------------------------
# Widgets
# --------------------------------------------------------------------------


class ToolLine(Static):
    """One tool call, one line -- and the output behind it, if you click it.

    A tool's arguments are JSON and a pretty-printed payload in the middle of a
    transcript is how a terminal session becomes unreadable, so this collapses
    to the single argument that identifies the call. The status glyph and the
    label are dim until the call finishes, which is the same signal a build log
    gives for free.

    **The one line is the right default and the wrong only.** The reason a
    command failed is in the output that line elided, and reaching it meant
    `/trajectory` and a scroll back through the frames. So a call with
    something behind it says so with a `▸`, and a click trades the line for the
    tail of the result -- from the *front* it is truncated, because the end is
    where the error is.
    """

    SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
    OK_GLYPH = "✓"
    FAIL_GLYPH = "✗"

    #: How much of a result an unfolded line shows. Twelve, the number the
    #: transcript's own previews use, and for the same reason: a session where
    #: every call is unfolded is one nobody can scan.
    DETAIL_LINES = 12

    #: The two states of the disclosure marker, so the shape of the line says
    #: whether there is more to see without anything having to be pressed.
    CLOSED_GLYPH = "▸"
    OPEN_GLYPH = "▾"

    def __init__(self, call: ToolCall, **kwargs: Any) -> None:
        # `**kwargs` is not decoration: Textual passes `id`, `classes` and the
        # rest to every widget it mounts, and a subclass of Static that does not
        # forward them cannot be mounted at all -- which is a TypeError at
        # compose time, long before anything is drawn.
        super().__init__(**kwargs)
        self.call = call
        self._frame = 0
        self._last_tick = 0.0
        #: Whether the output is showing. Closed by default, because the
        #: collapsed line is what makes a long session readable.
        self.expanded = False

    def on_mount(self) -> None:
        self.refresh_line()
        # The spinner is a timer rather than a per-event redraw: tool output
        # arrives in bursts, and tying the frame to the event count flickers as
        # fast as the data flows instead of at a readable rate.
        self.set_interval(0.1, self._tick)

    def _tick(self) -> None:
        if self.call.done or self.call.failed:
            return
        now = time.monotonic()
        if now - self._last_tick < 0.08:
            return
        self._last_tick = now
        self._frame = (self._frame + 1) % len(self.SPINNER)
        self.refresh_line()

    def refresh_line(self) -> None:
        from tonyagent.cli import theme

        if self.call.failed:
            marker, style, css = self.FAIL_GLYPH, theme.DANGER, "tool-failed"
        elif self.call.done:
            marker, style, css = self.OK_GLYPH, theme.FG_DIM, "tool-done"
        else:
            marker, style, css = self.SPINNER[self._frame], theme.FG_MUTE, "tool"

        text = Text()
        text.append(f"{marker} ", style=style)
        text.append(self.call.label(), style=style)
        if self.expanded:
            text.append(f"  {self.OPEN_GLYPH}", style=theme.FG_MUTE)
            for row in self._detail_rows():
                text.append("\n")
                text.append(row, style=theme.FG_DIM)
        else:
            if self.call.failed and self.call.result:
                text.append("  ")
                text.append(_one_line(self.call.result, 120), style=theme.DANGER)
            if self.detail():
                text.append(f"  {self.CLOSED_GLYPH}", style=theme.FG_MUTE)
        self.set_classes([css])
        self.update(text)

    def detail(self) -> str:
        """The output this line stands in for, if there is any.

        `output` and `error` are what the core sends on completion. `result` is
        not read here on purpose: it is the one-line preview already drawn, so
        reading it would make a call with nothing behind the line look like one
        that had something to open.
        """
        return self.call.output or self.call.error

    def _detail_rows(self) -> list[str]:
        """The tail of the output, indented under the line it belongs to.

        Truncated with `truncate_to_width` rather than `_one_line`: collapsing
        each row's whitespace would strip the indentation a traceback or a JSON
        payload is read *by*.
        """
        rows = [truncate_to_width(row, 200).rstrip() for row in self.detail().splitlines()]
        rows = [row for row in rows if row.strip()]
        hidden = len(rows) - self.DETAIL_LINES
        if hidden > 0:
            noun = "line" if hidden == 1 else "lines"
            rows = [f"… {hidden} earlier {noun}", *rows[-self.DETAIL_LINES :]]
        if not rows:
            return ["  (no output)"]
        return [f"  {row}" for row in rows]

    def on_click(self, event: Any) -> None:
        """Open or close the output.

        A line with nothing behind it does not pretend to open: the marker is
        drawn only when there is something there, and this leaves the event
        alone when there is not, so a click on a bare one-line call stays a
        click on the transcript.
        """
        if not self.detail():
            return
        event.stop()
        self.expanded = not self.expanded
        self.refresh_line()


class DiffBlock(Static):
    """A unified diff, in the window's two colours.

    **Only the added and removed lines are coloured, and only two glyphs are
    used.** A diff is mostly context, and colouring all three makes the two
    halves hard to find in a wall of text. `trajectory.css` solves this the
    same way -- `--traj-add` and `--traj-del` on the changed lines only.

    ``+`` and ``-`` are kept rather than dropped, so a line reads correctly if
    it is copied out of the terminal, and the glyph is a backtick rather than
    a block so an unexpanded font still renders something.
    """

    MAX_LINES = 20

    def __init__(self, change: FileChange, **kwargs: Any) -> None:
        kwargs.setdefault("classes", "diff")
        super().__init__(**kwargs)
        self.change = change

    def render(self) -> Text:
        from tonyagent.cli import theme

        text = Text()
        lines = self.change.diff.splitlines()
        shown = lines[: self.MAX_LINES]

        for line in shown:
            if line.startswith(("+++", "---")):
                text.append(line + "\n", style=theme.FG_MUTE)
            elif line.startswith("@@"):
                text.append(line + "\n", style=theme.ACCENT)
            elif line.startswith("+"):
                text.append(line + "\n", style=theme.TRAJ_ADD)
            elif line.startswith("-"):
                text.append(line + "\n", style=theme.TRAJ_DEL)
            else:
                text.append(line + "\n", style=theme.FG_MUTE)

        hidden = len(lines) - len(shown)
        if hidden > 0:
            text.append(f"  {hidden} more diff line{'s' if hidden != 1 else ''}",
                        style=theme.FG_MUTE)
        return text


class ChangeHeader(Static):
    """The `path  +n -n` line above a diff."""

    def __init__(self, change: FileChange, **kwargs: Any) -> None:
        kwargs.setdefault("classes", "change-head")
        super().__init__(**kwargs)
        self.change = change

    def render(self) -> Text:
        from tonyagent.cli import theme

        text = Text()
        text.append(self.change.path or "(Unknown path)", style=theme.FG_DIM)
        if self.change.added or self.change.removed:
            text.append(f"  +{self.change.added}", style=theme.TRAJ_ADD)
            text.append(f" -{self.change.removed}", style=theme.TRAJ_DEL)
        return text


class ConfirmDialog(Static):
    """A blocking tool confirmation, as a dialog rather than a composer line.

    **A modal is right here, and it is wrong everywhere else.** The window
    dims the page behind its confirm dialog; a terminal cannot dim, but it can
    take the keyboard, which is the part that matters -- an unanswered
    confirmation is the one state where the user must not be able to type a
    message into a turn that is waiting on a decision.

    The window shows which tools may change files and is explicit about the
    fact that this one does. So this says `destructive` in the same word, in
    `--danger`, rather than relying on the colour alone -- a terminal that has
    been piped through `NO_COLOR` loses the colour and must not lose the
    warning with it.
    """

    def __init__(self, tool_name: str, summary: str, destructive: bool,
                 **kwargs: Any) -> None:
        super().__init__(**kwargs)
        # Not `self.name`: `Widget.name` is a Textual property with no setter,
        # so assigning it raises AttributeError at compose time -- which is
        # where this first showed up.
        self.tool_name = tool_name
        self.summary = summary
        self.destructive = destructive
        self.add_class("confirm-destructive" if destructive else "confirm")

    def render(self) -> Text:
        from tonyagent.cli import theme

        text = Text()
        label = "destructive" if self.destructive else "confirm"
        text.append(label, style=theme.DANGER if self.destructive else theme.WARN)
        text.append("  ")
        text.append(self.tool_name, style=f"bold {theme.FG}")
        if self.summary:
            text.append(f"({self.summary})", style=theme.FG_MUTE)
        text.append("\n\n")
        text.append("[y] once    ", style=theme.OK)
        text.append("[a] always    ", style=theme.WARN)
        text.append("[n] no", style=theme.DANGER)
        return text


@dataclass(frozen=True)
class Command:
    """One entry in the palette.

    `run` is a name rather than a callable so a command table can be built at
    import time without capturing an instance of anything, and so the palette
    can be shown before the app is fully wired.
    """

    name: str
    description: str
    run: str
    #: Optional argument, drawn after the name in the way a usage line reads.
    argument: str = ""


class _ListScreen(ModalScreen[Any]):
    """A modal whose list is driven from the screen, not from the list itself.

    **The arrows were not reaching the list, in any of these dialogs.** Each one
    is a filter `Input` above an `OptionList`, and the Input keeps focus so that
    typing filters. They are *siblings*, so a keypress goes to the Input and
    then up to the screen -- never sideways to the OptionList, which is the only
    widget that would have moved the highlight. `down` therefore did nothing at
    all, in the model picker, in the chat list and in the key dialog alike: the
    first row was the only row anybody could reach.

    `Input` binds neither `up` nor `down` (it binds them for nothing, being one
    line tall), which is what makes screen-level bindings the right fix rather
    than a fight over focus: the filter keeps the keyboard for *text* and the
    screen takes it for *movement*.

    Movement skips disabled rows, because those are the group headers, and
    wrapping is deliberate -- a list you cannot come back up is a list you have
    to close and reopen.
    """

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("down", "cursor_down", "down", show=False),
        Binding("up", "cursor_up", "up", show=False),
        Binding("page_down", "cursor_down", show=False),
        Binding("page_up", "cursor_up", show=False),
    ]

    def _list(self) -> OptionList:
        return self.query_one(OptionList)

    def _step(self, delta: int) -> None:
        options = self._list()
        count = options.option_count
        if count == 0:
            return
        start = options.highlighted
        if start is None:
            options.highlighted = 0 if delta > 0 else count - 1
            return
        index = start
        for _ in range(count):
            index = (index + delta) % count
            option = options.get_option_at_index(index)
            if option is not None and option.id:
                options.highlighted = index
                return
        # Every remaining row is a header, so there is nowhere to go. Leaving
        # the highlight alone is better than parking it on something unenterable.
        options.highlighted = start

    def action_cursor_down(self) -> None:
        self._step(1)

    def action_cursor_up(self) -> None:
        self._step(-1)


class CommandPalette(_ListScreen):
    """The `ctrl+p` list.

    **A modal screen, not a widget over the app.** It has to take the keyboard
    completely -- the whole point is that you can type a filter and pick from a
    list without any of it reaching a turn -- and a `ModalScreen` is what Textual
    provides for taking the keyboard and being dismissed cleanly. A `layer:
    dialog` widget like the confirm dialog can be dismissed by anything behind
    it.

    **Filtering is a plain substring match over name and description, and that
    is a choice.** Fuzzy matching finds `/perm` for `/permission`, which is
    convenient, and also finds `/perm` for something unrelated that happens to
    share letters. A person scanning a short list of twenty is helped more by
    "the list is in the order I wrote it, and it only shrinks" than by a
    matcher that reorders under them.

    Returns the `run` name of the chosen command, or None.
    """

    BINDINGS: ClassVar[list[Binding]] = [Binding("escape", "dismiss", "close", show=True)]

    DEFAULT_CSS = """
    CommandPalette {
        align: center middle;
    }
    #palette-box {
        /* 72, with the model picker and the chat list. Every dialog in the
           interface is the same width, so opening one from another does not
           change the shape of the screen. */
        width: 72;
        height: auto;
        max-height: 80%;
        background: $surface;
        border: round $accent;
        padding: 0 1;
    }
    #palette-filter {
        border: none;
        height: 3;
        background: $surface;
    }
    #palette-list {
        height: auto;
        max-height: 18;
        background: $surface;
        border: none;
    }
    #palette-list > .option-list--option-highlighted {
        background: $accent 35%;
        color: $text;
        text-style: bold;
    }
    #palette-empty {
        color: $text-muted;
        padding: 0 1;
        height: 1;
    }
    """

    def __init__(self, commands: Sequence[Command]) -> None:
        super().__init__()
        self.commands = list(commands)

    def compose(self) -> Any:
        from textual.containers import Vertical
        with Vertical(id="palette-box"):
            yield Input(placeholder="filter commands", id="palette-filter")
            yield OptionList(id="palette-list")
            yield Static("", id="palette-empty")

    def on_mount(self) -> None:
        self._rebuild("")
        self.query_one("#palette-filter", Input).focus()

    # -- filtering -----------------------------------------------------------

    def _rebuild(self, needle: str) -> None:
        needle = needle.strip().lower()
        matches = [c for c in self.commands if _matches(c, needle)]

        options = self.query_one("#palette-list", OptionList)
        options.clear_options()
        # The name column is padded on *display width*, not character count, so
        # a description containing Korean does not push the column out of line.
        # `Option` carries only a prompt and an id, so both columns go in the
        # prompt -- which is also what the row looks like.
        width = max((len(c.name) for c in matches), default=0)
        for command in matches:
            label = pad_to(command.name, width)
            if command.argument:
                label += f" {command.argument}"
            # The id is the *run* name, not the command name: it is what the screen
            # returns and what the caller dispatches on. An id of the command
            # name made the palette hand back "/mode" to a table keyed by
            # "pick_mode", so every command reported itself unwired.
            options.add_option(Option(f"{label}   {command.description}", command.run))
        # Keep the highlight on whatever was highlighted before, by name, so
        # re-filtering while a selection is made does not silently move it to
        # the top -- which would make the next Enter run something else.
        if needle:
            self._restore_highlight(options, matches)

        empty = self.query_one("#palette-empty", Static)
        if not matches:
            empty.update(f"nothing matches {needle!r}")
        else:
            empty.update("")

    def _restore_highlight(self, options: Any, matches: list[Command]) -> None:
        """Keep the highlight where it was, matched by `run` because that is
        what the option id carries."""
        previous = self._highlighted_name
        if previous is None:
            return
        runs = [c.run for c in matches]
        if previous in runs:
            options.highlighted = runs.index(previous)

    @property
    def _highlighted_name(self) -> Optional[str]:
        options = self.query_one("#palette-list", OptionList)
        index = options.highlighted
        if index is None or index >= options.option_count:
            return None
        return options.get_option_at_index(index).id

    def on_input_changed(self, event: Any) -> None:
        self._rebuild(event.value)

    def on_option_list_option_highlighted(self, event: Any) -> None:
        self.query_one("#palette-empty").update("")

    def on_input_submitted(self, event: Any) -> None:
        """Enter runs the highlighted command, or the first one if there is no
        highlight -- which is what a person means by pressing Enter after typing
        a filter that narrowed to a single match."""
        name = self._highlighted_name
        if name is None:
            options = self.query_one("#palette-list", OptionList)
            if options.option_count:
                name = options.get_option_at_index(0).id
        event.stop()
        self.dismiss(name)

    def on_option_list_option_selected(self, event: Any) -> None:
        event.stop()
        self.dismiss(event.option.id)

    def action_dismiss(self) -> None:
        self.dismiss(None)


def _matches(command: Command, needle: str) -> bool:
    if not needle:
        return True
    return needle in command.name.lower() or needle in command.description.lower()


@dataclass(frozen=True)
class PickerEntry:
    """One row in a picker, with the group it belongs to."""

    value: str
    label: str
    group: str = ""
    #: Right-hand annotation -- a price tier, a context size, whatever the
    #: source knows that the label does not.
    note: str = ""
    #: Headers are rendered as disabled rows and cannot be chosen.
    is_header: bool = False


class PickerDialog(_ListScreen):
    """A titled dialog with a filter, for choosing one of many values.

    **The filter is the point, not a convenience.** OpenRouter answers with
    several hundred models and `mode.list` with five. A list you have to arrow
    through is unusable at the first size and merely tedious at the second, so
    the filter is what makes the picker usable at all.

    Entries carry a `group` and are drawn with headers, so a long list is
    navigable by where things are as well as by what they are called. Headers
    are disabled options, which is how an `OptionList` expresses a row that
    cannot be chosen -- and which is why Enter has to skip them.
    """

    BINDINGS: ClassVar[list[Binding]] = [Binding("escape", "dismiss", "close", show=True)]

    DEFAULT_CSS = """
    PickerDialog { align: center middle; }
    #picker-box {
        width: 72;
        height: auto;
        max-height: 85%;
        background: $surface;
        border: round $accent;
        padding: 0 1;
    }
    #picker-title { color: $text-muted; padding: 0 1; height: 1; }
    #picker-filter { border: none; height: 3; background: $surface; }
    #picker-options {
        height: auto;
        max-height: 20;
        background: $surface;
        border: none;
    }
    #picker-options > .option-list--option-highlighted {
        background: $accent 35%;
        color: $text;
        text-style: bold;
    }
    #picker-options > .option-list--option-disabled { color: $text-muted; }
    #picker-hint { color: $text-muted; padding: 0 1; height: 1; }
    """

    def __init__(
        self,
        title: str,
        entries: Sequence[PickerEntry],
        *,
        hint: str = "",
    ) -> None:
        super().__init__()
        self.title_text = title
        self.entries = list(entries)
        self.hint = hint

    def compose(self) -> Any:
        from textual.containers import Vertical

        with Vertical(id="picker-box"):
            yield Static(self.title_text, id="picker-title")
            yield Input(placeholder="filter", id="picker-filter")
            yield OptionList(id="picker-options")
            yield Static(self.hint or "enter select · esc close", id="picker-hint")

    def on_mount(self) -> None:
        self._rebuild("")
        self.query_one("#picker-filter", Input).focus()

    def _rebuild(self, needle: str) -> None:
        needle = needle.strip().lower()
        options = self.query_one("#picker-options", OptionList)
        options.clear_options()

        last_group: Optional[str] = None
        rows = 0
        width = max((len(e.label) for e in self.entries), default=0)
        for entry in self.entries:
            if needle and needle not in entry.label.lower():
                continue
            # A header is drawn only when the group it introduces has a visible
            # member, so filtering never leaves "Recent" over nothing.
            if entry.group and entry.group != last_group:
                options.add_option(Option(f"  {entry.group}", id=None, disabled=True))
                last_group = entry.group
            note = f"   {entry.note}" if entry.note else ""
            options.add_option(Option(f"  {pad_to(entry.label, width)}{note}", id=entry.value))
            rows += 1

        if rows == 0:
            options.add_option(Option(f"nothing matches {needle!r}", id=None, disabled=True))
        else:
            # The highlight must not start on a group header. `OptionList`
            # defaults it to row 0, which is always one, and a highlighted
            # header is both misleading and un-enterable.
            for index in range(options.option_count):
                if options.get_option_at_index(index).id:
                    options.highlighted = index
                    break

    def on_input_changed(self, event: Any) -> None:
        self._rebuild(event.value)

    def on_input_submitted(self, event: Any) -> None:
        event.stop()
        self._choose()

    def on_option_list_option_selected(self, event: Any) -> None:
        event.stop()
        if event.option.id:
            self.dismiss(event.option.id)

    def _choose(self) -> None:
        """Take the highlighted row, skipping headers.

        The first row is a group header, so Enter on it would otherwise do
        nothing at all -- which reads as a dead key rather than as a disabled
        row.
        """
        options = self.query_one("#picker-options", OptionList)
        count = options.option_count
        start = options.highlighted if options.highlighted is not None else 0
        for step in range(count):
            option = options.get_option_at_index((start + step) % count)
            if option.id:
                self.dismiss(option.id)
                return
        self.dismiss(None)

    def action_dismiss(self) -> None:
        self.dismiss(None)


class ConfirmScreen(ModalScreen[bool]):
    """A yes/no modal, for a decision this interface made on its own.

    `ConfirmDialog` next door cannot answer this question. It is an inline
    widget wired to `confirm.respond`, which answers a *core*-issued tool
    confirmation by id -- and removing a stored key is neither: nothing is
    waiting in the core, there is no id to reply to. Reusing it would have meant
    inventing an id for a call that does not exist, so this is a separate modal
    that answers with a bool and nothing else.

    Default is **no**. A destructive key should be the one that needs a
    deliberate second press, not the one a stray Enter accepts.
    """

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("escape", "cancel", "cancel", show=True),
        Binding("y", "accept", "yes", show=True),
        Binding("n", "cancel", "no", show=True),
    ]

    DEFAULT_CSS = """
    ConfirmScreen { align: center middle; }
    #confirm-box {
        width: 72;
        height: auto;
        background: $surface;
        border: round $error;
        padding: 1 2;
    }
    #confirm-question { height: auto; }
    #confirm-detail { color: $text-muted; height: auto; }
    #confirm-hint { color: $text-muted; height: 1; }
    """

    def __init__(self, question: str, detail: str = "") -> None:
        super().__init__()
        self.question = question
        self.detail = detail

    def compose(self) -> Any:
        from textual.containers import Vertical

        with Vertical(id="confirm-box"):
            yield Static(self.question, id="confirm-question")
            if self.detail:
                yield Static(self.detail, id="confirm-detail")
            yield Static("y remove · n or esc keep it", id="confirm-hint")

    def on_mount(self) -> None:
        self.query_one("#confirm-box").focus()

    def action_accept(self) -> None:
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)


@dataclass(frozen=True)
class KeyRequest:
    """What the key dialog is asking the caller to do.

    A dialog that only ever says "here is a key" cannot delete one, and a
    dialog that says "here is a provider" cannot either -- so the intent
    travels with the value rather than being inferred from which field was
    filled in. `remove` carries no secret at all, because deleting a key is
    the one operation that must never involve holding one.
    """

    action: str
    provider: str
    name: str = "default"
    key: str = ""


class KeyDialog(_ListScreen):
    """Set, replace and remove provider keys without leaving the TUI.

    **`/key` used to be show-only.** The core has had `key.save`, `key.delete`
    and `key.activate` for as long as it has had `key.list`, and the terminal
    frontend called only the fourth one. So the one task a person actually
    comes to `/key` for -- pasting a key -- was impossible from the terminal
    and had to be done in the window. That is the gap this closes.

    **The key is typed into a `password` field and never rendered.** Not
    masked-with-a-placeholder, not shown-until-you-press-reveal: the core's own
    `SECURITY` note above `key.save` is that a value on stdout is a value in a
    log strip and a screenshot, and the one method that hands a secret back
    (`key.reveal`) is deliberately not wired here. What this dialog shows is
    *whether* a key exists, never any part of one.

    Two states in one screen, because two modals for one task is one too many:
    a list of providers, then a single masked field for the chosen one.
    `provider/name` in that field stores a *named* key rather than replacing
    the default, which is what makes the keyring's per-name slots reachable
    without a third screen for them.

    **`ctrl+r` removes, and that chord was not the first one tried.** `ctrl+x`
    is the obvious choice and it is `Input`'s `cut` -- the filter field has
    focus, so the key was consumed there and never reached the screen at all.
    A test presses the chord rather than calling the action, because calling
    the action would have passed while the key did nothing.
    """

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("escape", "dismiss", "close", show=True),
        Binding("ctrl+r", "remove", "remove key", show=True),
    ]

    DEFAULT_CSS = """
    KeyDialog { align: center middle; }
    #key-box {
        width: 72;
        height: auto;
        max-height: 85%;
        background: $surface;
        border: round $accent;
        padding: 0 1;
    }
    #key-title { color: $text-muted; padding: 0 1; height: 1; }
    #key-filter { border: none; height: 3; background: $surface; }
    #key-options {
        height: auto;
        max-height: 20;
        background: $surface;
        border: none;
    }
    #key-options > .option-list--option-highlighted {
        background: $accent 35%;
        color: $text;
        text-style: bold;
    }
    #key-name, #key-entry {
        border: none;
        height: 3;
        background: $surface;
    }
    #key-hint { color: $text-muted; padding: 0 1; height: 1; }
    """

    def __init__(
        self,
        providers: Sequence[tuple[str, bool]],
        *,
        keys: Optional[dict[str, list[tuple[str, bool]]]] = None,
    ) -> None:
        """`providers` is `(name, has_key)`, so a provider with no key is
        visible rather than missing -- it is the row you press to add one.

        `keys` is the `key.list` reply keyed by provider: each entry is
        `(name, active)`. Keeping the active flag rather than just the names
        is what lets one row show all of a provider's keys and still say which
        one the next turn will actually spend.
        """
        super().__init__()
        self.providers = list(providers)
        self.keys = dict(keys or {})

    def compose(self) -> Any:
        from textual.containers import Vertical

        with Vertical(id="key-box"):
            yield Static("provider keys", id="key-title")
            yield Input(placeholder="filter", id="key-filter")
            yield OptionList(id="key-options")
            yield Input(placeholder="the key", password=True, id="key-entry")
            yield Input(placeholder="name (default)", id="key-name")
            yield Static(
                "enter edit · ctrl+r remove · esc close",
                id="key-hint",
            )

    def on_mount(self) -> None:
        self._set_state("list")
        self._rebuild("")
        self.query_one("#key-filter", Input).focus()

    def _set_state(self, state: str) -> None:
        """Show one of the two screens.

        Both are mounted and one is hidden, rather than swapping widgets, so a
        half-typed key is not destroyed by a rebuild and the screen's scroll
        position survives a trip back from the field.
        """
        listing = state == "list"
        self.query_one("#key-filter", Input).display = listing
        self.query_one("#key-options", OptionList).display = listing
        self.query_one("#key-name", Input).display = not listing
        self.query_one("#key-entry", Input).display = not listing
        self.query_one("#key-title", Static).update(
            "provider keys" if listing else f"key for {self._editing}"
        )
        self.query_one("#key-hint", Static).update(
            "enter edit · ctrl+r remove · esc close"
            if listing
            else "enter save · esc back"
        )
        (self.query_one("#key-filter", Input) if listing
         else self.query_one("#key-entry", Input)).focus()

    _editing = ""

    def _rebuild(self, needle: str) -> None:
        needle = needle.strip().lower()
        options = self.query_one("#key-options", OptionList)
        options.clear_options()
        width = max((len(name) for name, _ in self.providers), default=0)
        rows = 0
        for name, has_key in self.providers:
            if needle and needle not in name.lower():
                continue
            stored = self.keys.get(name) or []
            if stored:
                note = "   " + ", ".join(
                    f"{'*' if active else ' '}{n}" for n, active in stored
                )
            elif has_key:
                # A key this keyring can see but `key.list` did not name. The
                # row still has to say something true about it.
                note = "   saved"
            else:
                note = "   no key"
            options.add_option(Option(f"  {pad_to(name, width)}{note}", id=name))
            rows += 1
        if rows == 0:
            options.add_option(
                Option(f"nothing matches {needle!r}", id=None, disabled=True)
            )
            return
        options.highlighted = 0

    def _highlighted(self) -> Optional[str]:
        options = self.query_one("#key-options", OptionList)
        index = options.highlighted
        if index is None:
            return None
        option = options.get_option_at_index(index)
        return str(option.id) if option and option.id else None

    def on_input_changed(self, event: Any) -> None:
        # The filter drives the list; the masked field must not filter anything,
        # and a rebuild would wipe what was typed into it.
        if event.input.id == "key-filter":
            self._rebuild(event.value)

    def on_input_submitted(self, event: Any) -> None:
        event.stop()
        if event.input.id == "key-filter":
            self._edit()
        elif event.input.id == "key-name":
            # Enter saves from either field. The name is optional and prefilled,
            # so there is no state in which Enter here should do nothing.
            self._save(self.query_one("#key-entry", Input).value)
        else:
            self._save(event.value)

    def on_option_list_option_selected(self, event: Any) -> None:
        event.stop()
        if event.option.id:
            self._editing = str(event.option.id)
            self._open_entry()

    def _edit(self) -> None:
        provider = self._highlighted()
        if provider is None:
            return
        self._editing = provider
        self._open_entry()

    def _open_entry(self) -> None:
        """Open the two fields for the chosen provider.

        The name is prefilled with the key this provider is *currently* using,
        so pressing straight through replaces the active one rather than
        quietly creating a second key the turns will not spend.
        """
        stored = self.keys.get(self._editing) or []
        active = next((n for n, is_active in stored if is_active), None)
        self.query_one("#key-name", Input).value = active or "default"
        self.query_one("#key-entry", Input).value = ""
        self._set_state("entry")

    def _save(self, raw: str) -> None:
        """Hand the value back, with the name from its own field.

        **The name is a separate field because it cannot be parsed out of the
        key.** The first version took `provider/name` typed into the key box,
        which is wrong in a way a test caught immediately: API keys are
        routinely base64 and contain `/`, so the tail would have been stored as
        a key *name* while the real name went to the provider slot. A key and
        the label for it are two facts, and two fields is the honest count.
        """
        text = raw.strip()
        if not text:
            return
        name = self.query_one("#key-name", Input).value.strip() or "default"
        self.dismiss(KeyRequest("save", self._editing, name, text))

    def action_remove(self) -> None:
        provider = self._editing or self._highlighted() or ""
        if not provider:
            return
        stored = [n for n, _ in (self.keys.get(provider) or [])] or ["default"]
        # With several keys stored, the first is the one removed -- and the
        # caller confirms before anything is deleted, so this is a proposal
        # rather than an action.
        self.dismiss(KeyRequest("remove", provider, stored[0]))

    def action_dismiss(self) -> None:
        # Escape from the field goes back to the list, because a person who
        # pressed it by accident should not lose the list they were reading.
        if self.query_one("#key-entry", Input).display:
            self._set_state("list")
            return
        self.dismiss(None)


class ConversationsDialog(_ListScreen):
    """The chat list: viewable, and every row actionable.

    **`/conversations` used to print the list into the transcript**, where it
    was unreadable and unusable -- a title scrolled past with no way to open it.
    A list you cannot act on is a list you have no reason to ask for, so this
    is a dialog with keys on it.

    The keys are single letters rather than a menu, because the actions differ
    per row and a row context menu in a terminal is three more keystrokes for
    the same thing:

    * `Enter` switch · `n` new · `r` rename · `y` duplicate · `d` delete

    **Rename reuses the filter field** rather than opening a second input.
    Two inputs on one screen is two focus states to explain, and the filter is
    never wanted at the same moment as a title.

    **Delete takes two presses**, the same rule as `ctrl+c`, for the same
    reason: it is irreversible and it is one keystroke away.

    Returns the conversation to switch to, or None.
    """

    #: **Ctrl chords, not letters.** The filter has focus, and `Input` consumes
    #: printable keys as text -- so a `d` binding would either never fire or,
    #: given priority, make "delete" untypeable in the search. `ctrl+d` is
    #: avoided because the App binds it to quit. OpenCode's dialogs use ctrl
    #: chords for exactly this reason.
    BINDINGS: ClassVar[list[Binding]] = [
        Binding("ctrl+r", "rename", "rename", show=False, priority=True),
        Binding("ctrl+y", "duplicate", "duplicate", show=False, priority=True),
        Binding("ctrl+x", "delete", "delete", show=False, priority=True),
        Binding("ctrl+t", "new", "new", show=False, priority=True),
        Binding("escape", "dismiss", "close", show=True, priority=True),
    ]

    DEFAULT_CSS = """
    ConversationsDialog { align: center middle; }
    #conv-box {
        /* 72, the same as `PickerDialog`, and for the same reason: at 80 this
           went full-bleed in a 78-column terminal, with no margin either side
           and the border clipped by the screen edge. A dialog that fills the
           width reads as a panel, not as something laid over the session --
           which is the difference between "visual" and not. */
        width: 72;
        height: auto;
        max-height: 85%;
        background: $surface;
        border: round $accent;
        padding: 0 1;
    }
    /* No padding of its own: the box already has it, and two of them left a
       two-column gap before the right border. */
    #conv-head { height: 1; padding: 0; }
    /* The title takes the flexible width so `esc` lands against the right
       edge rather than sitting beside the title where it reads as part of it. */
    #conv-title { color: $text-muted; height: 1; width: 1fr; }
    #conv-esc { color: $text-muted; height: 1; width: auto; }
    #conv-filter { border: none; height: 3; background: $surface; }
    #conv-options { height: auto; max-height: 18; background: $surface; border: none; }
    #conv-options > .option-list--option-highlighted {
        background: $accent 35%;
        color: $text;
        text-style: bold;
    }
    #conv-options > .option-list--option-disabled { color: $text-muted; }
    /* `auto`, so the action list wraps rather than being cut off. At 72
       columns the full list does not fit on one line, and a hint truncated
       mid-chord is worse than one that takes two rows. */
    #conv-hint { color: $text-muted; padding: 0 1; height: auto; }
    #conv-hint.-warn { color: $warning; }
    """

    def __init__(self, conversations: Sequence[dict[str, Any]], current: str) -> None:
        super().__init__()
        self.rows = list(conversations)
        self.current = current
        #: `""` browsing, or the name of the action the next key performs.
        self.mode = ""
        self._delete_pending = ""

    def compose(self) -> Any:
        from textual.containers import Horizontal, Vertical

        with Vertical(id="conv-box"):
            # Title and `esc` on the same row, right-aligned, the way the model
            # dialog states its own way out. A hint only in the footer is one
            # line further away than the key it describes.
            with Horizontal(id="conv-head"):
                yield Static("conversations", id="conv-title")
                yield Static("esc", id="conv-esc")
            yield Input(placeholder="filter", id="conv-filter")
            yield OptionList(id="conv-options")
            yield Static("", id="conv-hint")

    def on_mount(self) -> None:
        self._rebuild("")
        self.query_one("#conv-filter", Input).focus()
        self._hint(self._actions())

    def _actions(self) -> str:
        """The footer, with the count -- as `PickerDialog` does with its models."""
        count = len(self.rows)
        return (
            f"{count} chat{'s' if count != 1 else ''} · enter open · ctrl+t new · "
            "ctrl+r rename · ctrl+y duplicate · ctrl+x delete"
        )

    # -- rows ----------------------------------------------------------------

    def _rebuild(self, needle: str) -> None:
        needle = needle.strip().lower()
        options = self.query_one("#conv-options", OptionList)
        options.clear_options()

        rows = [r for r in self.rows if not needle or needle in str(r.get("title", "")).lower()]
        rows.sort(key=lambda r: str(r.get("updated_at") or ""), reverse=True)
        if not rows:
            options.add_option(Option("  nothing here", id=None, disabled=True))
            options.highlighted = None
            return

        titles = [str(r.get("title") or "(untitled)") for r in rows]
        width = max(len(t) for t in titles)
        last_project: Optional[str] = None
        for row, title in zip(rows, titles, strict=True):
            project = str(row.get("project") or "")
            # Grouped by folder, because a conversation belongs to one and the
            # folder is the thing a person with several projects is scanning for.
            if project != last_project:
                options.add_option(
                    Option(f"  {_short_path(project) or 'No project'}", id=None, disabled=True)
                )
                last_project = project
            marker = "●" if str(row.get("id")) == self.current else " "
            count = int(row.get("message_count", 0) or 0)
            # A `Text` rather than markup, because the count is dimmed with a
            # real style: the first version interpolated the hex into the
            # prompt and the dialog rendered the literal `#8a8a8a`.
            from rich.text import Text

            from tonyagent.cli import theme

            row_text = Text(f"  {marker} {pad_to(title, width)}   ")
            row_text.append(f"{count} msg", style=theme.FG_MUTE)
            options.add_option(Option(row_text, id=str(row.get("id"))))
        # On the first selectable row, not row 0 -- which is a group header,
        # and a highlighted header is unselectable and reads as a dead key.
        for index in range(options.option_count):
            if options.get_option_at_index(index).id:
                options.highlighted = index
                break

    def _hint(self, text: str, warn: bool = False) -> None:
        hint = self.query_one("#conv-hint", Static)
        hint.update(text)
        hint.set_class(warn, "-warn")

    def _ids(self) -> list[str]:
        options = self.query_one("#conv-options", OptionList)
        return [o.id for o in options._options if o.id]  # noqa: SLF001 - no public walk

    def _highlighted_id(self) -> Optional[str]:
        options = self.query_one("#conv-options", OptionList)
        index = options.highlighted
        if index is None or index >= options.option_count:
            return None
        return options.get_option_at_index(index).id

    def _title_of(self, conversation_id: Optional[str]) -> str:
        for row in self.rows:
            if str(row.get("id")) == conversation_id:
                return str(row.get("title") or "(untitled)")
        return "it"

    # -- keys ----------------------------------------------------------------

    def on_input_changed(self, event: Any) -> None:
        if self.mode == "rename":
            return
        self._rebuild(event.value)

    def on_input_submitted(self, event: Any) -> None:
        event.stop()
        if self.mode == "rename":
            self._commit_rename(event.value)
            return
        chosen = self._highlighted_id()
        if chosen:
            self.dismiss(chosen)

    def on_key(self, event: Any) -> None:
        """Only Enter and Escape reach here; the actions are bindings.

        `Input` consumes printable keys as text, which is correct for a search
        field, so anything that is meant to be a command has to be a binding
        with priority rather than a letter handled here.
        """
        key = event.key
        if key == "escape":
            if self.mode:
                self._cancel_mode()
            else:
                self.dismiss(None)
            event.stop()
            return
        if self.mode == "rename":
            return  # the input owns every key while renaming

    # -- actions, one per binding -------------------------------------------

    def action_new(self) -> None:
        self.dismiss("__new__")

    def action_rename(self) -> None:
        if self._highlighted_id():
            self._begin_rename()

    def action_duplicate(self) -> None:
        target = self._highlighted_id()
        if target:
            self.dismiss(f"__duplicate__:{target}")

    def action_delete(self) -> None:
        self._ask_delete()

    def _begin_rename(self) -> None:
        target = self._highlighted_id()
        if not target:
            return
        self.mode = "rename"
        field = self.query_one("#conv-filter", Input)
        field.value = ""
        field.placeholder = f"new title for {self._title_of(target)}"
        self._hint("enter saves · esc cancels", warn=True)

    def _commit_rename(self, title: str) -> None:
        target = self._highlighted_id()
        self._cancel_mode()
        if target and title.strip():
            self.dismiss(f"__rename__:{target}:{title.strip()}")

    def _cancel_mode(self) -> None:
        self.mode = ""
        self._delete_pending = ""
        field = self.query_one("#conv-filter", Input)
        field.placeholder = "filter"
        self._hint("enter open · n new · r rename · y duplicate · d delete · esc close")

    def _ask_delete(self) -> None:
        target = self._highlighted_id()
        if not target:
            return
        if self._delete_pending != target:
            self._delete_pending = target
            self._hint(
                f"press ctrl+x again to delete {self._title_of(target)} — esc cancels",
                warn=True,
            )
            return
        self._delete_pending = ""
        self.dismiss(f"__delete__:{target}")

    def action_dismiss(self) -> None:
        self.dismiss(None)


def _short_path(path: str) -> str:
    """The last component of a project path, for a group header."""
    return PurePath(str(path or "")).name or str(path or "")


class TurnFooter(Static):
    """The line under a turn: mode, model, how long, how fast.

    Present because "how long did that take" is the first question after a long
    turn, and the only place it can be answered without scrolling back through
    the transcript.
    """

    def __init__(self, turn: Turn, *, mode: str = "", model: str = "",
                 **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.turn = turn
        self.mode = mode
        self.model = model

    def render(self) -> Text:
        from tonyagent.cli import theme

        text = Text()
        parts = [p for p in (self.mode, self.model) if p]
        parts.append(f"{self.turn.elapsed():.1f}s")
        rate = self.turn.rate()
        if rate:
            parts.append(f"{rate:.0f} char/s")
        if self.turn.tools:
            failed = sum(1 for t in self.turn.tools if t.failed)
            count = f"{len(self.turn.tools)} tool{'s' if len(self.turn.tools) != 1 else ''}"
            parts.append(count + (f", {failed} failed" if failed else ""))
        text.append(" · ".join(parts), style=theme.FG_MUTE)
        return text


class Sidebar(Static):
    """Mode, model, and the context meter.

    The meter is two numbers and a bar, and both numbers come from the core
    (`context.get`) rather than from anything counted here. When the core cannot
    say -- no provider bound, no usage reported, a model with no published
    window -- this says so instead of drawing an empty bar, because a bar at 0%
    for a long conversation is confidently wrong rather than merely unhelpful.
    """

    #: Where the bar starts worrying. These are not the provider's limits and
    #: not OpenAI's either; they are the point at which the remaining space is
    #: small enough that a summary is likely, which is where a person wants
    #: warning rather than after the fact.
    WARN_FRACTION = 0.60
    DANGER_FRACTION = 0.85

    BAR_WIDTH = 20

    #: The key that reaches each row, drawn beside its name.
    #:
    #: **A clickable row that says nothing about itself is a row nobody
    #: clicks.** Worse, these four chords appeared nowhere on screen at all: the
    #: footer lists what `BINDINGS` holds and these are handled in `on_key`, so
    #: there was no way to learn that a mode picker existed except by typing a
    #: slash and reading the list. Drawing them here teaches the keys and marks
    #: the values as things you can act on -- which is the half that works on a
    #: terminal that does not report the mouse.
    HINTS: ClassVar[dict[str, str]] = {
        "mode": "ctrl+1",
        "model": "ctrl+2",
        "permission": "ctrl+3",
        "context": "ctrl+4",
    }

    class Picked(Message):
        """A click landed on a row that names something.

        Posted rather than acted on here: a `Static` has no way to open a
        picker, and posting keeps the sidebar from growing a second copy of the
        app's wiring for what each row means.
        """

        def __init__(self, target: str) -> None:
            self.target = target
            super().__init__()

    def __init__(self, **kwargs: Any) -> None:
        # Forwards `id="sidebar"` and friends; see `ToolLine.__init__`.
        super().__init__(**kwargs)
        self.mode = ""
        self.model = ""
        self.permission = ""
        self.project = ""
        self.conversation = ""
        self.used = 0
        self.window = 0
        self.known = False
        self.busy = False
        #: Which line of the sidebar each click target sits on, keyed by line
        #: because that is what a terminal reports. Rebuilt by every render:
        #: the rows move -- `Chat` exists only while a chat is open, and the
        #: meter grows a line when it has to say why it cannot measure.
        self._regions: dict[int, str] = {}

    def on_click(self, event: Any) -> None:
        """Act on the row that was clicked, if it names something.

        **Textual resolves a click to the widget under it**, so this only has
        to find the row *within* the sidebar -- unlike the top bar's `+`, which
        the app hit-tests against a column because that bar is one `Static`
        with no rows to speak of. A blank line, or a label rather than the
        value beneath it, does nothing.
        """
        target = self._regions.get(event.offset.y, "")
        if not target:
            return
        event.stop()
        self.post_message(self.Picked(target))

    def update_state(self, state: dict[str, Any]) -> None:
        self.mode = str(state.get("mode", "") or "")
        self.model = str(state.get("model", "") or "")
        self.permission = str(state.get("permission", "") or "")
        self.project = str(state.get("project", "") or "")
        self.busy = bool(state.get("busy"))
        self.refresh()

    def set_conversation(self, title: str) -> None:
        """Which chat is open.

        Truncated to the sidebar's width: a long title that wraps pushes the
        context meter -- the number people come here for -- off the bottom.
        """
        self.conversation = title or ""
        self.refresh()

    def update_context(self, payload: dict[str, Any]) -> None:
        """Take the core's measurement, unchanged."""
        self.used = int(payload.get("used", 0) or 0)
        self.window = int(payload.get("window", 0) or 0)
        self.known = bool(payload.get("known"))
        self.refresh()

    def _fit(self, value: str, indent: int = 2) -> str:
        """A value clipped to the panel rather than left to wrap.

        A wrapped value pushes every row below it down, and the rows below it
        are the meter. In the compact width a long model id is the difference
        between four rows and seven. `indent` reserves the two leading spaces
        the value row carries, so the fit matches what is actually drawn.
        """
        width = self.content_size.width
        if width:
            width = max(1, width - indent)
            return truncate_to_width(value, width) if width else value
        return value

    def _fit_path(self, value: str, indent: int = 2) -> str:
        """A path clipped from the front, keeping the tail that names it.

        End-truncation keeps `C:\\Users\\...` and drops the folder name, which
        is the one part that distinguishes projects. Front-truncation keeps
        `…\\Project`, which is what the status line and picker already show.
        """
        width = self.content_size.width
        if width:
            width = max(1, width - indent)
        if not width or display_width(value) <= width:
            return value
        # Walk from the tail until the width (minus the ellipsis) is filled.
        tail: list[str] = []
        used = 0
        for char in reversed(value):
            step = display_width(char)
            if used + step > width - 1:
                break
            tail.append(char)
            used += step
        return "…" + "".join(reversed(tail))

    def _fraction(self) -> Optional[float]:
        if not self.known or not self.window or self.used <= 0:
            return None
        return min(1.0, self.used / self.window)

    def render(self) -> Text:
        """The panel, in the room it has.

        **Rendered twice at most, and the second time is for a short window.**
        `height: 1fr` gives the panel a share of the column rather than letting
        it size itself -- which is what stops the late rows from being clipped
        -- but a share of a short column is less than the panel wants, and the
        block a silent clip takes is the last one: the meter, the row this
        exists for. So the roomy form is tried first and the blanks between
        blocks are what give way, because they are the only rows carrying
        nothing. Measured: at 24 rows and above, both forms fit.
        """
        text = self._draw(tight=False)
        if self.size.height and text.plain.count("\n") + 1 > self.size.height:
            text = self._draw(tight=True)
        return text

    def _draw(self, *, tight: bool) -> Text:
        # Named `_draw`, not `_compose`: **`Widget._compose` is Textual's**, and
        # a same-named method here is called by the framework with no arguments
        # while mounting -- a `TypeError` at compose time, before anything is
        # on screen. `_compose` is not a name this class may use.
        from tonyagent.cli import theme

        # One blank row between blocks normally, none when they have to go.
        gap = "\n" if tight else "\n\n"
        text = Text()

        def heading(name: str, hint_key: str) -> None:
            """A section label with its key right-aligned, and the line ended.

            Uppercase muted label, dimmed key: the label says what the block
            is, the value below says what it holds. Right-aligned rather than
            run after the name: the keys then line up in a column of their own,
            which is what makes them read as a keybinding legend rather than as
            part of the label.
            """
            hint = self.HINTS.get(hint_key, "")
            style = theme.FG_MUTE
            if not hint:
                text.append(f"{name}\n", style=style)
                return
            room = max(0, self.content_size.width - display_width(hint))
            if not room:
                # Before there is a width to align against -- a render taken
                # outside a layout -- the name and its key still belong on the
                # line rather than being dropped for want of a column count.
                text.append(f"{name} {hint}\n", style=style)
                return
            # Truncated on display width, then padded to it: `pad_to` alone
            # leaves a name that is too long sticking out past the key.
            text.append(pad_to(truncate_to_width(name, room), room), style=style)
            text.append(f"{hint}\n", style=theme.FG_MUTE)

        def value_row(val: str, style: str) -> None:
            text.append("  ", style=style)
            text.append(f"{self._fit(val)}\n", style=style)

        heading("MODE", "mode")
        value_row(_cap(self.mode) or "-", theme.FG)
        text.append(gap)

        heading("MODEL", "model")
        text.append("  ", style=theme.FG)
        text.append(f"{self._fit(self.model or 'Not bound')}\n", style=theme.FG)
        text.append(gap)

        heading("PERMISSION", "permission")
        value_row(_cap(self.permission) or "-", theme.FG)
        text.append(gap)

        if not tight:
            heading("PROJECT", "project")
            text.append("  ", style=theme.FG_MUTE)
            text.append(f"{self._fit_path(self.project or 'No folder')}\n", style=theme.FG_MUTE)
            text.append(gap)

        if self.conversation and not tight:
            heading("CHAT", "chat")
            value_row(self.conversation, theme.FG)
            text.append(gap)

        heading("CONTEXT", "context")
        fraction = self._fraction()

        if fraction is None:
            # Not "0%": the honest statement is that the number is not
            # available, and saying why costs one line. Muted, not warning:
            # an unmeasured meter is the normal state on a fresh session,
            # not something that needs the eye.
            text.append("  Unknown\n", style=theme.FG_MUTE)
            if self.model:
                text.append("  ", style=theme.FG_MUTE)
                text.append(f"{_cap(self._why_unknown())}\n", style=theme.FG_MUTE)
            else:
                text.append("  No provider bound\n", style=theme.FG_MUTE)
        else:
            # Two spellings, because the panel has two widths. `314,139 tokens
            #  31% of 1,000,000` is 33 columns and the compact panel has 23, so
            # the long form wrapped -- and wrapped it read `314,139 tokens  31%
            # of` followed by a bare `1,000,000`, a number under a line that
            # promises a percentage, with the bar pushed a row further down.
            # `1M` is what anyone calls a million; see `_context_label`.
            percent = f"{fraction * 100:.0f}%"
            full = f"{self.used:,} tokens  {percent} of {self.window:,}"
            width = self.content_size.width
            text.append("  ", style=theme.FG_DIM)
            if width and display_width(full) + 2 > width:
                text.append(
                    f"{self.used:,} / {_context_label(self.window, '')}",
                    style=theme.FG_DIM,
                )
                text.append(f"  {percent}", style=theme.FG_MUTE)
            else:
                text.append(f"{self.used:,} tokens", style=theme.FG_DIM)
                text.append(f"  {percent} of {self.window:,}", style=theme.FG_MUTE)
            text.append("\n")
            text.append("  ", style=theme.FG_MUTE)
            text.append(self._bar(fraction, theme))

        # The rows a click can act on, read back out of what was just drawn
        # rather than counted while drawing it. A counter kept by hand drifts
        # the first time a row grows a branch, and the branches are the reason
        # this is not simply four fixed line numbers.
        rows = text.plain.split("\n")
        regions: dict[int, str] = {0: "mode", 1: "mode"}
        for index, row in enumerate(rows):
            # The first word, because a row now carries its key beside the
            # name: `MODEL      ctrl+2` is still the MODEL row. Uppercase
            # labels, case-insensitive match so the click map survives.
            stripped = row.strip()
            label = stripped.split(" ", 1)[0].upper() if stripped else ""
            if label in ("MODEL", "PERMISSION", "PROJECT", "CHAT"):
                # The value sits under its label, which is the row worth
                # clicking: "PERMISSION" is a word, `medium` is the setting.
                regions[index] = label.lower()
                regions[index + 1] = label.lower()
            elif label == "CONTEXT":
                # A label, a value, and a bar when there is one -- and the last
                # block, so everything from here down is the meter.
                regions.update(dict.fromkeys(range(index, len(rows)), "context"))
        self._regions = regions
        return text

    def _bar(self, fraction: float, theme: Any) -> Text:
        filled = round(fraction * self.BAR_WIDTH)
        if fraction >= self.DANGER_FRACTION:
            style = theme.DANGER
        elif fraction >= self.WARN_FRACTION:
            style = theme.WARN
        else:
            style = theme.FG_DIM
        bar = Text()
        bar.append("\u2588" * filled, style=style)
        bar.append("\u2591" * (self.BAR_WIDTH - filled), style=theme.FG_MUTE)
        return bar

    def _why_unknown(self) -> str:
        """Which of the two numbers is missing, if either.

        Worth the method because the two failures read differently to a user: a
        provider that has not reported usage yet is normal on a fresh install,
        while a model that publishes no context window will never produce a
        percentage at all, and confusing the two sends people looking for a key
        that is already saved.
        """
        if not self.known:
            return "no usage reported yet"
        if not self.window:
            return "model publishes no window"
        return ""


class NavRail(Static):
    """The left nav: conversation accelerator for the redesigned layout.

    A thin column, not a second sidebar: the chat list dialog remains the
    route, this only shows recent titles. Posts ``Sidebar.Picked`` with
    ``chat``/``new`` so the app reuses one dispatch table.
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.titles: list[str] = []
        self.active = ""
        self._regions: dict[int, str] = {}

    def set_conversations(self, titles: list[str], active: str = "") -> None:
        self.titles = list(titles[:8])
        self.active = active or ""
        self.refresh()

    def on_click(self, event: Any) -> None:
        target = self._regions.get(event.offset.y, "")
        if not target:
            return
        event.stop()
        self.post_message(Sidebar.Picked(target))

    def render(self) -> Text:
        from tonyagent.cli import theme

        text = Text()
        text.append("Chats\n", style=theme.FG_MUTE)
        self._regions = {}
        for i, title in enumerate(self.titles or ["(no chats yet)"]):
            mark = theme.tab_marker() + " " if title == self.active else "  "
            style = f"bold {theme.FG}" if title == self.active else theme.FG_DIM
            text.append(mark + title[:20] + "\n", style=style)
            self._regions[i + 1] = "chat"
        text.append("\n+ new  ctrl+n\n", style=theme.FG_MUTE)
        self._regions[len(self._regions) + 1] = "new"
        return text


def _one_line(text: str, limit: int) -> str:
    """Collapse to one line and truncate.

    Newlines are the whole problem: a shell command or a code fragment arrives
    with its own line structure, and printing it verbatim would break the
    one-line-per-call convention that makes the transcript scannable.
    """
    flat = " ".join(str(text).split())
    if len(flat) <= limit:
        return flat
    return flat[: limit - 1] + "…"
