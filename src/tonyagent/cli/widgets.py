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
from dataclasses import dataclass, field
from typing import Any, Optional

from rich.text import Text
from textual.widgets import Static

# --------------------------------------------------------------------------
# The turn model
# --------------------------------------------------------------------------


@dataclass
class ToolCall:
    """One tool call, from `tool.started` to its completion."""

    id: str
    name: str
    summary: str = ""
    done: bool = False
    failed: bool = False
    result: str = ""

    def label(self) -> str:
        return f"{self.name}({self.summary})" if self.summary else self.name


@dataclass
class Turn:
    """One user message and everything the agent did in response."""

    text: str = ""
    answer: str = ""
    reasoning: str = ""
    tools: list[ToolCall] = field(default_factory=list)
    error: str = ""
    started: float = field(default_factory=time.monotonic)

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
