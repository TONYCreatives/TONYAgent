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
from typing import Any, Optional

from rich.text import Text
from textual.screen import ModalScreen
from textual.widgets import Input, OptionList, Static
from textual.widgets.option_list import Option

from tonyagent.cli.render import pad_to

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
    """One tool call, one line.

    A tool's arguments are JSON and a pretty-printed payload in the middle of a
    transcript is how a terminal session becomes unreadable, so this collapses
    to the single argument that identifies the call. The status glyph and the
    label are dim until the call finishes, which is the same signal a build log
    gives for free.
    """

    SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
    OK_GLYPH = "✓"
    FAIL_GLYPH = "✗"

    def __init__(self, call: ToolCall, **kwargs: Any) -> None:
        # `**kwargs` is not decoration: Textual passes `id`, `classes` and the
        # rest to every widget it mounts, and a subclass of Static that does not
        # forward them cannot be mounted at all -- which is a TypeError at
        # compose time, long before anything is drawn.
        super().__init__(**kwargs)
        self.call = call
        self._frame = 0
        self._last_tick = 0.0

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
        if self.call.failed and self.call.result:
            text.append("  ")
            text.append(_one_line(self.call.result, 120), style=theme.DANGER)
        self.set_classes([css])
        self.update(text)


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
        text.append(self.change.path or "(unknown path)", style=theme.FG_DIM)
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


class CommandPalette(ModalScreen[Optional[str]]):
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

    DEFAULT_CSS = """
    CommandPalette {
        align: center middle;
    }
    #palette-box {
        width: 76;
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


class PickerDialog(ModalScreen[Optional[str]]):
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

    def __init__(self, **kwargs: Any) -> None:
        # Forwards `id="sidebar"` and friends; see `ToolLine.__init__`.
        super().__init__(**kwargs)
        self.mode = ""
        self.model = ""
        self.permission = ""
        self.project = ""
        self.used = 0
        self.window = 0
        self.known = False
        self.busy = False

    def update_state(self, state: dict[str, Any]) -> None:
        self.mode = str(state.get("mode", "") or "")
        self.model = str(state.get("model", "") or "")
        self.permission = str(state.get("permission", "") or "")
        self.project = str(state.get("project", "") or "")
        self.busy = bool(state.get("busy"))
        self.refresh()

    def update_context(self, payload: dict[str, Any]) -> None:
        """Take the core's measurement, unchanged."""
        self.used = int(payload.get("used", 0) or 0)
        self.window = int(payload.get("window", 0) or 0)
        self.known = bool(payload.get("known"))
        self.refresh()

    def _fraction(self) -> Optional[float]:
        if not self.known or not self.window or self.used <= 0:
            return None
        return min(1.0, self.used / self.window)

    def render(self) -> Text:
        from tonyagent.cli import theme

        text = Text()
        text.append(self.mode or "-", style=f"bold {theme.FG}")
        text.append("\n\n")

        text.append("Model\n", style=theme.FG_MUTE)
        text.append(self.model or "not bound", style=theme.FG_DIM)
        text.append("\n\n")

        text.append("Permission\n", style=theme.FG_MUTE)
        text.append(self.permission or "-", style=theme.FG_DIM)
        text.append("\n\n")

        text.append("Context\n", style=theme.FG_MUTE)
        fraction = self._fraction()

        if fraction is None:
            # Not "0%": the honest statement is that the number is not
            # available, and saying why costs one line.
            text.append("unknown", style=theme.WARN)
            if self.model:
                text.append("\n")
                text.append(self._why_unknown(), style=theme.FG_MUTE)
            else:
                text.append("\nno provider bound", style=theme.FG_MUTE)
        else:
            text.append(f"{self.used:,} tokens", style=theme.FG_DIM)
            text.append(f"  {fraction * 100:.0f}% of {self.window:,}", style=theme.FG_MUTE)
            text.append("\n")
            text.append(self._bar(fraction, theme))
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
