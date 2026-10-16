"""Drawing the core's event stream into a terminal.

The window renders with React; this renders with escape sequences, and the
difference shows up in one place that decides most of the design: **a terminal
is a character grid, not a document.** There is no layout engine to reflow, so
the renderer is a small state machine that owns the current line and appends to
it. Every event type has to say which of three things it does:

* append to the assistant's current line (``message.delta``);
* start or end a block (``tool.started``, ``turn.started``);
* change what the next event means (reasoning ended, so deltas are answers).

**Why the delta handling is this particular shape.** `message.delta` arrives one
token at a time, and a prompt must not appear until the turn is over -- so the
renderer writes deltas inline with no newline, and ends the line when
`message.completed` arrives. Mid-stream that looks like a terminal that forgot
to press Enter, which is exactly the intent, and it is why a streaming turn
here uses noticeably fewer lines than the window's chat bubbles.

**Why tool calls are one line each, not a block.** A tool's arguments are JSON,
and pretty-printing a 40-key payload into the middle of a transcript is how a
terminal session becomes unreadable. One dimmed line, a spinner while it runs,
and the result summarised on the same line if it is short. That matches how a
person reads a build log, which is the thing this is competing with.

Colour is emitted only when stdout is a TTY and `NO_COLOR` is unset, following
the informal standard rather than inventing one.
"""

from __future__ import annotations

import json
import os
import sys
import time
import unicodedata
from typing import Any, Optional, TextIO

#: Results longer than this are truncated with a count, not a preview.
RESULT_PREVIEW_CHARS = 160

#: Lines kept when a tool's output is too long to show whole.
#:
#: Borrowed from OpenCode's `collapseToolOutput`, and for its reason: the head of
#: a command's output is the part that was already printed above it, while the
#: tail is the error. Truncating the head shows the user the part they have and
#: hides the part they do not.
RESULT_MAX_LINES = 12


def _context_label(tokens: Any, suffix: str = " ctx") -> str:
    """A context size in the unit people say it in.

    `1048576` is a megabyte of digits; `1M` is what a person would call it.
    Anything at or above a million is shown in millions, because rounding
    1,048,576 down to `1048K` is the kind of accuracy nobody asked for.

    `suffix` is the unit word. The model picker keeps it -- `262K ctx` is a
    row of its own there. The status line passes `""` because it already says
    `ctx` once at the front: composed the other way the line read
    `ctx 314K ctx/1M ctx`, the unit printed three times.

    It lives here rather than beside the status line that first needed it,
    because the sidebar needs the same abbreviation at its compact width: two
    spellings of `1M` in one panel would be two things to keep in step.
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
        return f"{round(n / 1_000_000, 1):g}M{suffix}"
    return f"{n // 1000}K{suffix}"


def display_width(text: str) -> int:
    """How many terminal columns `text` occupies.

    Not `len()`. A CJK character is one Python character and two columns, and
    an emoji is often two characters and zero or four columns, so `len()` turns
    any table of tool arguments into a staircase. Python ships no width table,
    but `unicodedata.east_asian_width` distinguishes the half from the full
    forms, which covers every case that matters here.

    OpenCode carries a grapheme-aware table for this and is more correct about
    emoji sequences. That is a real difference, stated rather than hidden: the
    `W`/`F` split below is correct for text, and wrong for a flag or a skin
    tone, which would miscount by a column or two.
    """
    width = 0
    for char in text:
        if unicodedata.combining(char):
            continue
        width += 2 if unicodedata.east_asian_width(char) in ("W", "F") else 1
    return width


def truncate_to_width(text: str, limit: int) -> str:
    """Truncate on column width rather than character count.

    The two agree for ASCII, which is most of what a transcript holds, and
    disagree exactly where it would be visible: a truncated line of Korean is
    short in characters and over the edge on screen.
    """
    if display_width(text) <= limit:
        return text
    out: list[str] = []
    width = 0
    for char in text:
        step = 0 if unicodedata.combining(char) else (
            2 if unicodedata.east_asian_width(char) in ("W", "F") else 1
        )
        if width + step > limit - 1:
            break
        out.append(char)
        width += step
    return "".join(out) + "…"


def pad_to(text: str, columns: int) -> str:
    """Pad on display width, so aligned columns stay aligned under CJK text."""
    return text + " " * max(0, columns - display_width(text))


def _supports_colour(stream: TextIO) -> bool:
    """Whether to emit ANSI on this stream.

    `NO_COLOR` is honoured because a user who sets it in their shell profile
    means it for every program, and a CLI that overrides it is the kind of
    thing that ends up in `less` with a screenful of escape codes in it.
    """
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("TERM") == "dumb":
        return False
    return bool(getattr(stream, "isatty", lambda: False)())


class Style:
    """ANSI codes, or nothing when the stream is not a terminal.

    Every method returns the string unchanged when colour is off, so a caller
    never has to branch on whether colour is available.
    """

    def __init__(self, enabled: bool) -> None:
        self.enabled = enabled

    def _wrap(self, text: str, code: str) -> str:
        return f"\033[{code}m{text}\033[0m" if self.enabled else text

    def dim(self, text: str) -> str:
        return self._wrap(text, "2")

    def bold(self, text: str) -> str:
        return self._wrap(text, "1")

    def red(self, text: str) -> str:
        return self._wrap(text, "31")

    def green(self, text: str) -> str:
        return self._wrap(text, "32")

    def yellow(self, text: str) -> str:
        return self._wrap(text, "33")

    def blue(self, text: str) -> str:
        return self._wrap(text, "34")

    def magenta(self, text: str) -> str:
        return self._wrap(text, "35")

    def cyan(self, text: str) -> str:
        return self._wrap(text, "36")


SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"


class Renderer:
    """Turns events into lines on a stream.

    Not thread-safe, and it does not need to be: it is only ever called from
    the reader thread (via the client's event callback) and from the main
    thread between turns, never from both at once with a partial line
    outstanding. The main thread's `begin_input` is the one place that must not
    race, and it stops the stream from being mid-line first.
    """

    def __init__(self, stream: Optional[TextIO] = None, show_reasoning: bool = True) -> None:
        self.out = stream if stream is not None else sys.stdout
        self.style = Style(_supports_colour(self.out))
        self.show_reasoning = show_reasoning

        #: True between a `message.delta` and the newline that ends it. The
        #: flag exists so any other event knows to close the line first --
        #: without it a tool call's output lands in the middle of a sentence.
        self._mid_line = False
        #: The tool calls currently running, by id, so `tool.completed` can
        #: find the label it printed when the call started.
        self._active_tools: dict[str, str] = {}
        self._spinner_index = 0
        self._last_spinner = 0.0
        self.started = time.monotonic()

    # -- primitives ----------------------------------------------------------

    def _end_line(self) -> None:
        """Close a partially written line, once."""
        if self._mid_line:
            self.out.write("\n")
            self._mid_line = False

    def write(self, text: str) -> None:
        """Write a delta, staying on the line."""
        self.out.write(text)
        self._mid_line = True
        self.out.flush()

    def line(self, text: str = "") -> None:
        """Write a whole line, ending whatever was in progress."""
        self._end_line()
        self.out.write(text + "\n")
        self.out.flush()

    def blank(self) -> None:
        self.line("")

    def warn(self, text: str) -> None:
        self.line(self.style.yellow(text))

    def error(self, text: str) -> None:
        self.line(self.style.red(text))

    # -- the turn ------------------------------------------------------------

    def handle(self, event_type: str, payload: dict[str, Any]) -> None:
        """Render one event. The dispatch table, in one place."""
        handler = getattr(self, f"_on_{event_type.replace('.', '_')}", None)
        if handler is None:
            return
        try:
            handler(payload)
        except Exception:  # noqa: BLE001 - never let drawing kill the session
            self.error(f"(could not render {event_type})")

    def _on_turn_started(self, payload: dict[str, Any]) -> None:
        self.blank()

    def _on_turn_finished(self, payload: dict[str, Any]) -> None:
        self._end_line()
        self._clear_tools()
        self.blank()

    def _on_turn_failed(self, payload: dict[str, Any]) -> None:
        self._end_line()
        self._clear_tools()
        message = payload.get("error") or payload.get("message") or "the turn failed"
        self.error(f"Turn failed: {message}")

    # -- assistant output ----------------------------------------------------

    def _on_message_delta(self, payload: dict[str, Any]) -> None:
        self.write(str(payload.get("text", "")))

    def _on_message_completed(self, payload: dict[str, Any]) -> None:
        self._end_line()

    def _on_reasoning_delta(self, payload: dict[str, Any]) -> None:
        if not self.show_reasoning:
            return
        # Shown as a dim `· ` prefix on the first token only, so a long
        # reasoning block reads as one paragraph rather than as 400 lines.
        if not self._mid_line:
            self.write(self.style.dim("· "))
        self.write(self.style.dim(str(payload.get("text", ""))))

    def _on_reasoning_completed(self, payload: dict[str, Any]) -> None:
        if self.show_reasoning and self._mid_line:
            self._end_line()

    # -- tools ---------------------------------------------------------------

    def _on_tool_started(self, payload: dict[str, Any]) -> None:
        self._end_line()
        call_id = str(payload.get("id", ""))
        name = str(payload.get("name", "?"))
        summary = _argument_summary(name, payload.get("arguments"))
        label = f"{name}({summary})" if summary else name
        self._active_tools[call_id] = label
        self._spinner_index = 0
        self._last_spinner = time.monotonic()
        self.line(f"  {self.style.cyan(self._spinner())} {self.style.dim(label)}")

    def _on_tool_completed(self, payload: dict[str, Any]) -> None:
        self._finish_tool(payload, self.style.green("done"))

    def _on_tool_failed(self, payload: dict[str, Any]) -> None:
        self._finish_tool(payload, self.style.red("failed"))

    def _finish_tool(self, payload: dict[str, Any], word: str) -> None:
        call_id = str(payload.get("id", ""))
        label = self._active_tools.pop(call_id, None)
        # A completion for a call this renderer never saw started is not an
        # error: the reader can drop a frame, and a REPL that crashed on that
        # would be a worse bug than a stray line.
        if label is None:
            return
        self._end_line()
        detail = _result_summary(payload)
        tail = f" {self.style.dim(detail)}" if detail else ""
        self.line(f"  {word} {self.style.dim(label)}{tail}")

    def _clear_tools(self) -> None:
        self._active_tools.clear()

    def _spinner(self) -> str:
        """Advance the spinner, but only if enough time has passed.

        Called once per event, and events arrive in bursts -- a tool that
        streams output can emit many in a second. Tying the frame to elapsed
        time rather than to the event count keeps it at a readable rate
        instead of flickering as fast as the data flows.
        """
        now = time.monotonic()
        if now - self._last_spinner > 0.08:
            self._spinner_index = (self._spinner_index + 1) % len(SPINNER)
            self._last_spinner = now
        return SPINNER[self._spinner_index]

    # -- blocking on the user ------------------------------------------------

    def _on_confirmation_requested(self, payload: dict[str, Any]) -> None:
        """Draw the prompt. The answer is read by the caller, not here.

        The renderer prints and returns; `repl` collects the reply and sends
        `confirm.respond`. Splitting them is what lets Ctrl-C cancel the turn
        from anywhere without this method having to know about signals.
        """
        self._end_line()
        name = str(payload.get("name", "?"))
        summary = _argument_summary(name, payload.get("arguments"))
        destructive = bool(payload.get("destructive"))
        marker = self.style.red("destructive") if destructive else self.style.yellow("confirm")
        self.blank()
        self.line(f"{marker}: {self.style.bold(name)}")
        if summary:
            self.line(f"  {summary}")
        description = payload.get("description")
        if description:
            self.line(f"  {self.style.dim(str(description))}")
        self.blank()
        self.line("  " + self.style.dim("[y] once   [a] always   [n] no"))

    def _on_user_asked(self, payload: dict[str, Any]) -> None:
        """Print a question or a presentation.

        `kind` says which of `ask_user_question` and `present` is asking,
        because the two want different answers: a question wants text, a
        presentation wants a dismissal. Both arrive here and both are answered
        through `user.respond`.
        """
        self._end_line()
        kind = str(payload.get("kind", "question"))
        self.blank()
        if kind == "present":
            title = str(payload.get("title") or payload.get("question") or "")
            if title:
                self.line(self.style.bold(title))
            body = payload.get("body") or payload.get("content") or ""
            if body:
                self.line(str(body))
            options = payload.get("options")
            if isinstance(options, list) and options:
                for index, option in enumerate(options, 1):
                    label = option.get("label") if isinstance(option, dict) else option
                    self.line(f"  {self.style.cyan(str(index))}. {label}")
            return
        question = str(payload.get("question") or payload.get("text") or "")
        if question:
            self.line(self.style.bold(question))
        options = payload.get("options")
        if isinstance(options, list) and options:
            for index, option in enumerate(options, 1):
                if isinstance(option, dict):
                    label = option.get("label", "")
                    hint = option.get("description") or option.get("hint") or ""
                else:
                    label, hint = str(option), ""
                line = f"  {self.style.cyan(str(index))}. {label}"
                if hint:
                    line += self.style.dim(f"  {hint}")
                self.line(line)

    # -- diagnostics ---------------------------------------------------------

    def _on_error(self, payload: dict[str, Any]) -> None:
        self.error(str(payload.get("message", payload.get("error", "error"))))

    def _on_sandbox_status(self, payload: dict[str, Any]) -> None:
        status = str(payload.get("status", ""))
        if status:
            self.line(self.style.dim(f"  sandbox: {status}"))


# --------------------------------------------------------------------------
# Summarising a tool call into one line
# --------------------------------------------------------------------------

#: The argument worth showing per tool. A tool has forty parameters; the one
#: that identifies what it did is the point of printing it at all.
_HEADLINE_ARGS = {
    "read": "path", "write": "path", "edit": "path", "delete_file": "path",
    "list_dir": "path", "grep": "pattern", "glob": "pattern",
    "execute_command": "command", "execute_js": "code",
    "browser_navigate": "url", "browser_click": "selector",
    "browser_type": "text", "web_fetch": "url", "http_request": "url",
    "subagent": "task", "send_message": "message",
    "ask_user_question": "question", "todo_write": None,
}


def _argument_summary(name: str, arguments: Any) -> str:
    """One short, identifying fragment of a tool call.

    Arguments arrive as a JSON *string* on the wire rather than an object, so
    the parse failure here is expected and is why a bad one degrades to an
    empty summary instead of raising: a malformed argument blob is the core's
    problem to report, and the terminal should still print the tool's name.
    """
    if not arguments:
        return ""
    data = arguments
    if isinstance(arguments, str):
        text = arguments.strip()
        if not text:
            return ""
        try:
            data = json.loads(text)
        except ValueError:
            return _one_line(arguments)
    if not isinstance(data, dict):
        return _one_line(str(data))

    key = _HEADLINE_ARGS.get(name, "path" if "path" in data else None)
    if key and data.get(key):
        return _one_line(str(data[key]))
    for candidate in ("path", "url", "command", "query", "pattern", "name"):
        if data.get(candidate):
            return _one_line(str(data[candidate]))
    return ""


def _one_line(text: str, limit: int = 72) -> str:
    """Collapse to one line and truncate.

    Newlines are the whole problem: a shell command or a code fragment arrives
    with its own line structure, and printing it verbatim would break the
    single-line-per-call convention that makes the transcript scannable.
    """
    flat = " ".join(text.split())
    if len(flat) <= limit:
        return flat
    return flat[: limit - 1] + "…"


def _result_summary(payload: dict[str, Any]) -> str:
    """A short tail for a finished tool call, or nothing useful to add.

    **The tail, not the head.** A command that printed three hundred lines of
    progress and then failed has put its error last, and a preview cut from the
    front shows the user the part they have already seen on their terminal
    while hiding the part they need. This is the one thing borrowed
    deliberately from OpenCode's `collapseShellOutput`, which makes the same
    argument about the same thing.
    """
    result = payload.get("result")
    if result is None:
        return ""
    text = result if isinstance(result, str) else json.dumps(result, default=str)
    if not text.strip():
        return ""

    lines = text.splitlines()
    if len(lines) <= RESULT_MAX_LINES:
        flat = " ".join(text.split())
        if display_width(flat) <= RESULT_PREVIEW_CHARS:
            return flat
        return truncate_to_width(flat, RESULT_PREVIEW_CHARS)

    kept = lines[-RESULT_MAX_LINES:]
    body = truncate_to_width("\n".join(kept), RESULT_PREVIEW_CHARS)
    dropped = len(lines) - len(kept)
    # The marker goes *before* the text, because this is a prefix of what was
    # removed -- and a reader scanning for the error should see "N lines
    # omitted" once, not a trailing ellipsis they have to interpret.
    return f"… {dropped} earlier line{'s' if dropped != 1 else ''} omitted …\n{body}"
