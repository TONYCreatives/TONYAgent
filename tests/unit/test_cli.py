"""The terminal frontend, and the one boundary it must not cross.

The CLI is a frontend over a protocol that already exists and is already
tested (`test_headless_core.py` covers the server side). What is untested --
and what these tests are for -- is everything the frontend itself is
responsible for, because all of it lives outside the protocol:

* that it does not import a GUI toolkit, which is the same property the core
  asserts for itself and the reason the boundary exists at all;
* that a reply is matched by id rather than by arrival order, which is the
  failure mode that makes a REPL consume a token as if it were an answer;
* that a dead core raises rather than hanging forever, because a terminal with
  no visible window has no other way to report that the agent is gone;
* that colour follows `NO_COLOR`, which is the difference between a transcript
  you can read and one full of escape codes.

The renderer is tested against a `StringIO`, so every assertion here is about
what a person would see.
"""

from __future__ import annotations

import io
import json
import subprocess
import sys
import threading
import time

import pytest

from tonyagent.cli.client import CoreClient, CoreError, core_argv
from tonyagent.cli.render import Renderer, Style, _argument_summary, _result_summary

# --- the boundary ----------------------------------------------------------


def test_the_cli_does_not_pull_in_a_gui_toolkit():
    """The same guarantee the core makes, and for a sharper reason here.

    A terminal frontend that imported a GUI toolkit would fail to start on a
    machine with no display -- which is the entire reason to run this instead
    of the window. The window *needs* pywebview; the CLI must not merely avoid
    wanting it.
    """
    code = (
        "import sys; sys.path.insert(0, 'src');"
        "import tonyagent.cli.repl, tonyagent.cli.render, tonyagent.cli.client;"
        "print(','.join(k for k in ('tkinter','webview','customtkinter')"
        " if k in sys.modules))"
    )
    out = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, cwd="."
    )
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "", f"a GUI toolkit was imported: {out.stdout!r}"


def test_the_entry_point_runs_without_a_display():
    """`python -m tonyagent.cli --help` must work with no DISPLAY at all.

    Checked in a subprocess with the variable cleared, because the failure this
    guards against -- importing something that reaches for a display at import
    time -- is invisible from inside a test that already has one.
    """
    import os
    from pathlib import Path

    src = str(Path(__file__).resolve().parents[2] / "src")
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "PYTHONPATH": src}
    out = subprocess.run(
        [sys.executable, "-m", "tonyagent.cli", "--help"],
        capture_output=True,
        text=True,
        cwd=".",
        env=env,
    )
    assert out.returncode == 0, out.stderr
    assert "terminal" in out.stdout.lower()


# --- colour ----------------------------------------------------------------


class _FakeTty(io.StringIO):
    """A stream that claims to be a terminal, so colour is decided for real."""

    def isatty(self) -> bool:
        return True


def test_no_color_is_honoured(monkeypatch):
    """A user who sets NO_COLOR means it for every program, including this one.

    Tested through `_supports_colour` rather than through `Style(True)`, because
    that flag is the *result* of the decision and asking the result to reverse
    itself would assert nothing about the code that makes it.
    """
    from tonyagent.cli.render import _supports_colour

    stream = _FakeTty()
    monkeypatch.setenv("NO_COLOR", "1")
    assert _supports_colour(stream) is False

    monkeypatch.delenv("NO_COLOR")
    assert _supports_colour(stream) is True


def test_a_non_terminal_gets_no_escape_codes():
    """Piping into a file must produce a readable transcript, not a binary one.

    `tony "..." | tee log` is the whole reason someone would script this, and
    the version with escape codes in it is not a log.
    """
    assert Style(False).cyan("x") == "x"
    assert Renderer(io.StringIO()).style.enabled is False


def test_a_terminal_stream_gets_colour(monkeypatch):
    monkeypatch.delenv("NO_COLOR", raising=False)
    assert Renderer(_FakeTty()).style.enabled is True


# --- rendering -------------------------------------------------------------


def test_the_deltas_stay_on_one_line_until_the_message_completes():
    """No newline per token.

    Streaming with a newline after every delta is what makes a terminal
    transcript unreadable -- it turns one paragraph into hundreds of lines.
    The line is closed by `message.completed`, so a turn in flight looks like a
    terminal that has not pressed Enter yet, which is exactly the intent.
    """
    stream = io.StringIO()
    ui = Renderer(stream)
    ui.handle("message.delta", {"text": "Hel"})
    ui.handle("message.delta", {"text": "lo"})
    assert stream.getvalue() == "Hello"
    assert "\n" not in stream.getvalue()

    ui.handle("message.completed", {})
    assert stream.getvalue() == "Hello\n"


def test_a_turn_starts_on_a_fresh_line():
    stream = io.StringIO()
    ui = Renderer(stream)
    ui.handle("turn.started", {})
    ui.handle("message.delta", {"text": "Hi"})
    ui.handle("message.completed", {})
    # The blank line before a turn is deliberate: without it a turn's first
    # token lands on the same line as whatever the user typed.
    assert stream.getvalue().startswith("\n")


def test_a_tool_call_is_one_line_and_its_result_a_short_tail():
    stream = io.StringIO()
    ui = Renderer(stream)
    ui.handle("tool.started", {"id": "1", "name": "read", "arguments": '{"path": "a.py"}'})
    ui.handle("tool.completed", {"id": "1", "result": "file body"})
    lines = stream.getvalue().strip().split("\n")

    assert len(lines) == 2
    assert "read(a.py)" in lines[0]
    assert "file body" in lines[1]


def test_a_long_result_keeps_the_tail_not_the_head():
    """The error is at the end.

    A command that printed 40 lines of progress and then failed has put its
    message last. A preview cut from the front shows the part already printed
    above it and hides the part that explains the failure.
    """
    body = "\n".join(f"line {n}" for n in range(40))
    summary = _result_summary({"result": body + "\nFATAL: the disk is full"})

    assert "FATAL: the disk is full" in summary
    assert "line 0" not in summary
    assert "earlier lines omitted" in summary


def test_the_omission_count_is_plural_when_it_is_many_lines():
    """The count is stated, so the user knows how much they are not seeing."""
    from tonyagent.cli.render import RESULT_MAX_LINES

    body = "\n".join(f"line {n}" for n in range(RESULT_MAX_LINES + 5))
    summary = _result_summary({"result": body})
    assert "5 earlier lines omitted" in summary


def test_the_omission_count_is_singular_when_it_is_one_line():
    from tonyagent.cli.render import RESULT_MAX_LINES

    body = "\n".join(f"line {n}" for n in range(RESULT_MAX_LINES + 1))
    summary = _result_summary({"result": body})
    assert "1 earlier line omitted" in summary


def test_output_that_already_fits_is_not_marked_as_omitted():
    from tonyagent.cli.render import RESULT_MAX_LINES

    body = "\n".join(f"line {n}" for n in range(RESULT_MAX_LINES))
    summary = _result_summary({"result": body})
    assert "omitted" not in summary
    assert "line 0" in summary


def test_a_long_single_line_result_is_truncated_by_width():
    summary = _result_summary({"result": "x" * 500})
    assert len(summary) < 200
    assert summary.endswith("…")


def test_multiline_arguments_are_flattened_to_one_line():
    """A shell command arrives with its own line structure and must not break
    the one-line-per-call convention that makes the transcript scannable."""
    summary = _argument_summary("execute_command", '{"command": "ls\\n  -la\\n  /tmp"}')
    assert "\n" not in summary
    assert "ls -la /tmp" in summary


def test_a_malformed_argument_blob_still_prints_the_tool_name():
    """Degrading to no summary beats raising: the argument blob is the core's
    problem to report, and the terminal should still say which tool ran."""
    ui = Renderer(io.StringIO())
    ui.handle("tool.started", {"id": "1", "name": "read", "arguments": "{not json"})
    assert "read" in ui.out.getvalue()


def test_a_completion_for_an_unknown_tool_is_not_an_error():
    """The reader may drop a frame. A REPL that crashed on the next one would
    be a worse bug than a missing line."""
    ui = Renderer(io.StringIO())
    ui.handle("tool.completed", {"id": "never-started", "result": "x"})
    assert "never-started" not in ui.out.getvalue()


def test_a_renderer_that_throws_does_not_kill_the_stream():
    stream = io.StringIO()
    ui = Renderer(stream)

    class Exploding(dict):
        def get(self, *_a, **_k):
            raise RuntimeError("boom")

    ui.handle("tool.started", Exploding())
    assert "could not render" in stream.getvalue()


def test_reasoning_is_hidden_when_asked():
    stream = io.StringIO()
    ui = Renderer(stream, show_reasoning=False)
    ui.handle("reasoning.delta", {"text": "thinking"})
    assert "thinking" not in stream.getvalue()


def test_a_second_event_closes_the_partial_line_first():
    """Without this a tool call's output lands mid-sentence."""
    stream = io.StringIO()
    ui = Renderer(stream)
    ui.handle("message.delta", {"text": "half a th"})
    ui.handle("tool.started", {"id": "1", "name": "read", "arguments": "{}"})
    lines = stream.getvalue().split("\n")
    assert lines[0] == "half a th"


def test_an_unknown_event_is_ignored():
    """New event types must not break an older frontend."""
    ui = Renderer(io.StringIO())
    ui.handle("something.brand.new", {"x": 1})
    assert ui.out.getvalue() == ""


def test_cjk_text_is_measured_in_columns_not_characters():
    """A Korean character is one Python character and two terminal columns.

    Padding on `len()` is what turns an aligned column list into a staircase
    as soon as the text is not Latin, and the transcript is read as much by its
    shape as by its words.
    """
    from tonyagent.cli.render import display_width, pad_to

    assert display_width("abc") == 3
    assert display_width("한글") == 4
    assert display_width("a한") == 3

    padded = pad_to("한글", 10)
    assert display_width(padded) == 10


def test_truncation_respects_column_width():
    """Truncating Korean by character count runs past the edge on screen."""
    from tonyagent.cli.render import display_width, truncate_to_width

    truncated = truncate_to_width("가" * 100, 10)
    assert display_width(truncated) <= 10


def test_a_confirmation_offers_always_as_well_as_once():
    """Three options, and the third is the one the user forgets they chose."""
    stream = io.StringIO()
    ui = Renderer(stream)
    ui.handle("confirmation.requested", {
        "id": "1", "name": "delete_file", "arguments": '{"path": "a.py"}',
        "destructive": True,
    })
    out = stream.getvalue()
    assert "[y] once" in out
    assert "[a] always" in out
    assert "[n] no" in out


# --- the input loop, which used to eat the user's next command -------------


class _StubClient:
    """A core that answers everything and records what the frontend sends.

    `during_send` is run on its own thread, which is the point. The real core
    emits events from its reader thread while `send` is still outstanding, and
    a stub that fires them inline would close every dialog before the frontend
    ever woke up -- so the test would pass by never exercising the race it was
    written for, and would equally pass a frontend that never reads at all.
    """

    def __init__(self, during_send=None, send_duration: float = 0.30) -> None:
        self.sent: list[tuple[str, dict]] = []
        self.notified: list[tuple[str, dict]] = []
        self._during_send = during_send
        self._send_duration = send_duration

    def call(self, method, params=None, timeout=None):
        if method == "send":
            if self._during_send is not None:
                runner, self._during_send = self._during_send, None
                threading.Thread(target=runner, daemon=True).start()
            # Long enough that the loop is still waiting when the events land.
            time.sleep(self._send_duration)
        return {}

    def notify(self, method, params=None):
        self.notified.append((method, params))


def _make_repl(client, monkeypatch, stdin_text=""):
    """A `Repl` wired to stubs, with no real terminal and no real core."""
    import threading as _threading

    from tonyagent.cli.repl import Repl

    repl = Repl.__new__(Repl)
    repl.client = client
    repl.ui = Renderer(io.StringIO(), show_reasoning=False)
    repl.running = True
    repl.state = {}
    repl._pending_confirm = None
    repl._pending_ask = None
    repl._asked = _threading.Event()
    repl._sending = ""
    monkeypatch.setattr(sys, "stdin", io.StringIO(stdin_text))
    return repl


def test_a_turn_that_asks_nothing_does_not_read_the_terminal(monkeypatch):
    """The regression, and the reason the input loop is event-driven.

    The first version polled `input()` every 200ms whether or not the core was
    asking anything. On a turn that asked nothing it sat reading the terminal
    and fed every line to `_route_answer` with `_pending_confirm` and
    `_pending_ask` both empty -- so it fired a `user.respond` with an empty id
    once per poll, until the turn ended.

    It looked fine because most turns finish fast. It was stealing input the
    whole time: on a real terminal, the next command a user typed was eaten by
    the previous turn's answer loop instead of reaching the prompt.
    """
    client = _StubClient()
    repl = _make_repl(client, monkeypatch, stdin_text="the next command\n")

    repl._turn("a turn that asks nothing")

    assert client.notified == [], (
        "read the terminal with no dialog open and answered nothing"
    )


def test_a_question_is_answered_exactly_once(monkeypatch):
    """The positive case: a real question still reaches the terminal.

    Without this the fix above would also pass a build that simply never asked
    anything -- which is not a REPL.
    """
    from tonyagent.core.events import EventType

    def ask():
        time.sleep(0.02)
        repl.handle_event(
            EventType.USER_ASKED.value, {"id": "q1", "question": "Which?"}
        )

    client = _StubClient(during_send=ask)
    repl = _make_repl(client, monkeypatch, stdin_text="blue\n")

    repl._turn("pick a colour")

    assert client.notified == [("user.respond", {"id": "q1", "answer": "blue"})]


def test_a_confirmation_is_answered_with_the_id_it_arrived_with(monkeypatch):
    """The id decides where an answer goes; nothing is guessed from the text."""
    from tonyagent.core.events import EventType

    def ask():
        time.sleep(0.02)
        repl.handle_event(
            EventType.CONFIRMATION_REQUESTED.value,
            {"id": "c1", "name": "delete_file", "destructive": True},
        )

    client = _StubClient(during_send=ask)
    repl = _make_repl(client, monkeypatch, stdin_text="y\n")

    repl._turn("delete it")

    assert client.notified == [("confirm.respond", {"id": "c1", "confirmed": True})]


def test_a_dialog_that_closes_is_not_answered_afterwards(monkeypatch):
    """A turn that ends while the key is down must not answer a stale id.

    The core closes its outstanding prompts with "no" at the end of a turn, so
    `confirmation.resolved` can land while the user is part-way through typing
    an answer to a prompt that no longer exists. Routing that answer would put
    a `confirm.respond` for an id the core has already retired, which reads as
    a dropped connection rather than as the turn having ended.

    The close is deliberately scheduled *after* the frontend has started
    reading -- closing it beforehand would close every dialog before the loop
    woke up, and the test would pass without ever reaching the race.
    """
    from tonyagent.core.events import EventType

    reading = threading.Event()

    def open_then_close_during_the_read():
        repl.handle_event(
            EventType.CONFIRMATION_REQUESTED.value, {"id": "c1", "name": "write"}
        )
        # Close it while the frontend is blocked reading the keyboard, which is
        # the window this is about: a person reads a prompt, thinks, and the
        # turn ends underneath them.
        reading.wait(timeout=2)
        time.sleep(0.05)
        repl.handle_event(EventType.CONFIRMATION_RESOLVED.value, {"id": "c1"})

    class _SlowStdin(io.StringIO):
        """Hands over the line, but only once, after a signal.

        A plain StringIO returns instantly, so the answer would be routed
        before the close landed and the race would never actually be entered.
        """

        def readline(self, *args):
            reading.set()
            time.sleep(0.15)
            return super().readline(*args)

    client = _StubClient(during_send=open_then_close_during_the_read, send_duration=0.40)
    repl = _make_repl(client, monkeypatch, stdin_text="y\n")
    monkeypatch.setattr(sys, "stdin", _SlowStdin("y\n"))

    repl._turn("write it")

    assert reading.is_set(), "the frontend never read, so nothing was tested"
    assert client.notified == [], "answered a confirmation the core had closed"


def test_asking_always_raises_the_permission_level_not_just_the_one_call(monkeypatch):
    """"always" is the session's level, and the test says so out loud.

    Pinned because the alternative -- silently treating `a` as `y` -- would
    look identical to a user who never re-reads the prompt, while leaving them
    to be asked again on every tool.
    """
    client = _StubClient()
    repl = _make_repl(client, monkeypatch)
    calls = []

    def fake_call(method, params=None, timeout=None):
        calls.append((method, params))
        if method == "permission.list":
            return {
                "permission": "medium",
                "permissions": [
                    {"name": "medium"}, {"name": "high"}, {"name": "full"}
                ],
            }
        if method == "permission.set":
            return {"name": "high"}
        return {}

    monkeypatch.setattr(repl.client, "call", fake_call)
    monkeypatch.setattr(sys, "stdin", io.StringIO("y\n"))

    assert repl._allow_always() is True
    assert ("permission.set", {"permission": "high"}) in calls


def test_asking_always_at_the_top_level_does_not_promise_more_than_it_can_do(monkeypatch):
    """At `full` there is nothing to raise, so it confirms this once and says so."""
    client = _StubClient()
    repl = _make_repl(client, monkeypatch)

    def fake_call(method, params=None, timeout=None):
        if method == "permission.list":
            return {"permission": "full", "permissions": [{"name": "full"}]}
        return {}

    monkeypatch.setattr(repl.client, "call", fake_call)
    assert repl._allow_always() is True


# --- the theme: the window's palette, ported -------------------------------


def test_the_theme_carries_the_windows_own_tokens():
    """Every colour here is read from `app/src/styles/tokens.css`.

    Pinned because the whole point of this frontend is that it looks like the
    same application as the window. A palette that drifted would not be noticed
    by anything else in the suite, and would be noticed by a person.
    """
    from tonyagent.cli import theme

    # The two ladders and the accent, with the values the file declares.
    assert theme.BG == "#1a1a1a"
    assert theme.SURFACE == "#202020"
    assert theme.CHROME == "#262626"
    assert theme.FG == "#ececec"
    assert theme.FG_MUTE == "#8a8a8a"  # 5.04:1 on --bg, chosen for that reason
    assert theme.ACCENT == "#6393f0"  # not the icon ground #2f6feb: 3.81:1
    css = theme.build_css()
    assert theme.BG in css
    assert theme.ACCENT in css


def test_the_theme_is_achromatic_except_the_accent_and_the_semantics():
    """`tokens.css`: "the accent is the only chroma on screen".

    This is the rule the file gives as the reason the window stopped looking
    borrowed, so it is worth a test rather than a comment -- a violet heading or
    an amber bold would break it, and would look borrowed.
    """
    from tonyagent.cli import theme

    def chroma(hex_value: str) -> int:
        v = hex_value.lstrip("#")
        r, g, b = (int(v[i : i + 2], 16) for i in (0, 2, 4))
        return max(r, g, b) - min(r, g, b)

    for name in ("BG", "SURFACE", "CHROME", "INPUT", "RAISED", "CHIP",
                 "FG", "FG_DIM", "FG_MUTE", "BORDER", "BORDER_STRONG"):
        assert chroma(getattr(theme, name)) == 0, f"{name} is not achromatic"
    # The four places chroma is allowed, and no others in the ladder.
    assert chroma(theme.ACCENT) > 0
    assert chroma(theme.OK) > 0
    assert chroma(theme.DANGER) > 0
    assert chroma(theme.WARN) > 0


def test_the_stylesheet_parses(monkeypatch):
    """The regression, and the reason this test exists.

    The first version converted the palette to xterm-256 by hand whenever
    `COLORTERM` was unset, and emitted Rich's internal spelling -- `color234`.
    That is not a value Textual's CSS parser accepts, so the whole stylesheet
    failed to parse and the interface refused to start on exactly the
    terminals the fallback existed for.

    It was also redundant: Rich quantises hex to whatever the terminal can show,
    at draw time. A pty with no `COLORTERM` rendered `#1a1a1a` as `48;5;234`
    without being asked.

    So the palette is hex now, always, and this parses it to prove it -- rather
    than asserting on the string, which is what let the bad value through.
    """
    pytest.importorskip("textual")

    for env in ({"COLORTERM": "truecolor"}, {"TERM": "xterm-256color"}, {}):
        for name in ("COLORTERM", "TERM"):
            monkeypatch.delenv(name, raising=False)
        for key, value in env.items():
            monkeypatch.setenv(key, value)

        import io

        from textual.css.errors import StylesheetError
        from textual.css.stylesheet import Stylesheet

        from tonyagent.cli.theme import build_css

        sheet = Stylesheet()
        source = build_css()
        sheet.add_source(source, read_from=io.StringIO(source))
        # `parse` raises `StylesheetError` listing every bad value, which is the
        # failure this test exists for -- asserting on the string instead is
        # what let `color234` through in the first place.
        try:
            sheet.parse()
        except StylesheetError as exc:
            raise AssertionError(f"stylesheet failed for {env}: {exc}") from exc
        assert sheet.rules, "the stylesheet parsed to nothing"


def test_no_colour_in_the_stylesheet_is_richs_spelling(monkeypatch):
    """`color234` is Rich's internal name. Textual's parser wants hex.

    Cheap and blunt on purpose: it fails on the whole class of mistake rather
    than on the one value that happened to be wrong.
    """
    pytest.importorskip("textual")

    monkeypatch.delenv("COLORTERM", raising=False)
    monkeypatch.setenv("TERM", "xterm")

    import re

    from tonyagent.cli.theme import build_css

    offenders = re.findall(r"color\d+", build_css())
    assert offenders == [], f"Rich colour names are not valid CSS: {offenders}"


def test_truecolor_detection_is_reported_not_branched_on(monkeypatch):
    """Diagnostics only. Rich does the reduction; nothing here branches on it."""
    from tonyagent.cli import theme

    monkeypatch.setenv("COLORTERM", "truecolor")
    assert theme.truecolor_supported() is True

    monkeypatch.delenv("COLORTERM")
    monkeypatch.setenv("TERM", "xterm-256color")
    assert theme.truecolor_supported() is True

    monkeypatch.setenv("TERM", "dumb")
    assert theme.truecolor_supported() is False


# --- the turn model --------------------------------------------------------


def test_a_tool_call_splits_the_message_it_interrupts():
    """Arrival order is the order on screen.

    An agent that says something, calls a tool, then says more has three
    pieces. Rendered as one accumulating widget the tool has nowhere to go that
    is both after what was said and before what comes next, and either choice
    reorders the transcript -- so the message is frozen at the interruption.
    """
    from tonyagent.cli.widgets import Turn

    turn = Turn()
    turn.on_delta({"text": "Looking now."})
    first = turn.take_answer()
    turn.on_delta({"text": "Fixed."})
    second = turn.take_answer()

    assert first == "Looking now."
    assert second == "Fixed."


def test_taking_an_empty_message_yields_nothing():
    from tonyagent.cli.widgets import Turn

    turn = Turn()
    assert turn.take_answer().strip() == ""


def test_the_throughput_figure_counts_what_actually_arrived():
    """Char/s, not tokens/s.

    The core streams text chunks of varying size, so a token rate would be
    measured against a tokenizer this frontend does not have and would not
    agree with the provider's billing figure anyway.
    """
    from tonyagent.cli.widgets import Turn

    turn = Turn()
    turn.on_delta({"text": "x" * 200})
    assert turn.streamed_chars == 200
    # Measured, so a turn that just started reports nothing rather than a
    # number derived from a handful of milliseconds.
    assert turn.rate() >= 0


# --- the trajectory: what the core actually sends --------------------------


def test_a_tool_result_is_read_as_a_result_not_a_string():
    """`tool.completed` carries an object; the one-line summary wants a string.

    Reading one as the other is how a diff silently disappears: the summary
    path is satisfied by a preview of the JSON, and the trajectory path needs
    `status`, `output`, `error` and `artifacts`, which are not in it.
    """
    from tonyagent.cli.widgets import ToolCall

    call = ToolCall.from_result({
        "result": {
            "status": "success",
            "output": "applied 1 edit",
            "error": "",
            "artifacts": [{
                "type": "file_change",
                "data": {"path": "app.py", "diff": "+x", "added": 1, "removed": 0},
            }],
        }
    })
    assert call.status == "success"
    assert call.output == "applied 1 edit"
    assert call.error == ""
    assert len(call.changes) == 1
    assert call.changes[0].path == "app.py"
    assert call.changes[0].added == 1


def test_a_file_change_with_no_diff_still_names_the_file():
    """`added`/`removed` with no body happens, and the path is the useful part."""
    from tonyagent.cli.widgets import ToolCall

    call = ToolCall.from_result({
        "result": {
            "artifacts": [{"type": "file_change",
                           "data": {"path": "a.py", "added": 3, "removed": 1}}],
        }
    })
    assert call.changes[0].path == "a.py"
    assert call.changes[0].removed == 1


def test_a_tool_result_that_is_a_plain_string_still_renders():
    """Not every tool returns the structured shape, and the summary line wants
    the string. One is not a reason to lose the other."""
    from tonyagent.cli.widgets import ToolCall

    call = ToolCall.from_result({"result": "just text"})
    assert call.result == "just text"
    assert call.changes == []


def test_a_diff_colours_only_the_changed_lines():
    """A diff is mostly context. Colouring all three makes the two halves hard
    to find, which is why `trajectory.css` colours only the changed ones."""
    from tonyagent.cli import theme
    from tonyagent.cli.widgets import DiffBlock, FileChange

    diff = "--- a\n+++ b\n@@ -1 +1 @@\n-old\n+new\n same"
    rendered = DiffBlock(FileChange(path="a", diff=diff)).render()
    styles = [str(span.style) for span in rendered.spans]

    assert theme.TRAJ_ADD in styles, "the added line is not marked"
    assert theme.TRAJ_DEL in styles, "the removed line is not marked"
    assert theme.FG_MUTE in styles, "the context line is not dimmed"


def test_a_long_diff_says_how_much_was_hidden():
    from tonyagent.cli.widgets import DiffBlock, FileChange

    diff = "\n".join(f"+line {n}" for n in range(80))
    rendered = DiffBlock(FileChange(path="a", diff=diff)).render()
    assert "more diff lines" in rendered.plain


# --- the confirmation ------------------------------------------------------


def test_a_destructive_confirmation_says_so_in_words():
    """Not in colour alone.

    `NO_COLOR` and a redirected stdout both strip the escape codes, and a
    destructive tool that only announces itself in `--danger` would then be
    announcing itself in nothing. The window says "destructive" for the same
    reason.
    """
    from tonyagent.cli.widgets import ConfirmDialog

    destructive = ConfirmDialog("delete_file", "secrets.env", True).render().plain
    ordinary = ConfirmDialog("read", "a.py", False).render().plain

    assert "destructive" in destructive
    assert "destructive" not in ordinary
    # And the word is still there with colour off.
    assert "delete_file" in destructive


def test_a_confirmation_offers_once_always_and_no():
    from tonyagent.cli.widgets import ConfirmDialog

    text = ConfirmDialog("write", "a.py", False).render().plain
    assert "[y] once" in text
    assert "[a] always" in text
    assert "[n] no" in text


# --- the optional extra, and what happens without it -----------------------


def test_a_missing_terminal_extra_falls_back_rather_than_raising(monkeypatch):
    """`textual` is optional, and on a person's machine it usually is missing.

    Whether the full-screen interface is wanted depends on whether stdout is a
    terminal, which is only true on the machine someone is sitting at -- and a
    separate Python on that machine is a normal thing to have. So the first
    version's raw traceback, arriving after the core had already started, was
    a fault reported for something that is not one.
    """
    import builtins

    real_import = builtins.__import__

    def refuse_textual(name, *args, **kwargs):
        if name.startswith("textual"):
            raise ImportError("No module named 'textual'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", refuse_textual)
    monkeypatch.setattr(sys, "stdin", io.StringIO("/quit\n"))

    from tonyagent.cli.repl import main

    # Falls back to line mode: the REPL runs and /quit ends it, so this is 0
    # rather than a traceback.
    assert main(["--plain"]) == 0


def test_asking_for_the_interface_by_name_is_a_failure_without_it(monkeypatch):
    """`--tui` that silently downgrades reports success for an interface that
    never ran, which is worse than refusing."""
    import builtins

    real_import = builtins.__import__

    def refuse_textual(name, *args, **kwargs):
        if name.startswith("textual"):
            raise ImportError("No module named 'textual'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", refuse_textual)
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))

    from tonyagent.cli.repl import main

    assert main(["--tui"]) == 1


def test_the_terminal_extra_is_declared_but_not_required():
    """Optional on purpose: a headless install should not be made heavier for
    an interface it cannot use, and a piped run needs no terminal at all."""
    import tomllib
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    with (root / "pyproject.toml").open("rb") as handle:
        config = tomllib.load(handle)

    optional = config["project"]["optional-dependencies"]
    assert any("textual" in dep for dep in optional["terminal"])
    # And not in the required list, which is the half that matters.
    assert not any("textual" in dep for dep in config["project"]["dependencies"])


# --- the composer: Enter sends --------------------------------------------


@pytest.mark.asyncio
async def test_enter_sends_the_turn_and_clears_the_composer(monkeypatch):
    """The regression.

    The composer was a `TextArea`, whose Enter inserts a newline -- correct
    for a multi-line editor, and the wrong widget for a composer whose own
    docstring says a line is one turn. Pressing Enter just added a blank line
    and nothing was sent.

    Driven with real keystrokes through the pilot rather than by calling
    `_submit`, because the bug was in the key path: a test that called the
    method directly passed while the key did nothing.
    """
    pytest.importorskip("textual")


    from tonyagent.cli.tui import TonyApp

    sent: list[str] = []

    class _Client:
        on_event = None

        def call(self, method, params=None, timeout=None):
            if method == "send":
                sent.append(str((params or {}).get("text", "")))
            return {"state": {"mode": "build", "model": "m", "permission": "medium"}}

        def notify(self, method, params=None):
            return {}

    app = TonyApp(_Client())
    async with app.run_test(size=(110, 26)) as pilot:
        await pilot.pause()
        from textual.widgets import Input

        composer = app.query_one("#composer", Input)
        composer.focus()
        await pilot.pause()

        for char in "hello tony":
            await pilot.press(char)
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        await pilot.pause()

        assert sent == ["hello tony"]
        # Cleared, so the next turn is typed into an empty field rather than
        # below the last one.
        assert composer.value == ""


def test_the_composer_is_a_single_line_widget():
    """Pinned so the choice is not silently reverted.

    `Input` posts `Submitted` on Enter and the handler lives in
    `on_input_submitted`. A `TextArea` would insert a newline instead, and
    re-adding an Enter branch to `on_key` would send a turn twice.
    """
    pytest.importorskip("textual")

    import inspect

    from tonyagent.cli.tui import TonyApp

    assert hasattr(TonyApp, "on_input_submitted")
    # Enter must not also be handled here, or a turn goes twice.
    assert "enter" not in inspect.getsource(TonyApp.on_key)


# --- the command palette ---------------------------------------------------


def test_every_palette_command_is_wired_to_a_handler():
    """A command listed but not wired reports itself rather than doing nothing.

    The first version of the palette made exactly this mistake -- every entry
    said "not wired up" -- because the option's id was the command *name* while
    the dispatch table was keyed by `run`. The test is on the pair rather than
    on the behaviour because the behaviour is a message in the transcript,
    which nothing reads.
    """
    pytest.importorskip("textual")

    import inspect

    from tonyagent.cli.tui import COMMANDS, TonyApp

    source = inspect.getsource(TonyApp._run_command)
    for command in COMMANDS:
        assert f'"{command.run}"' in source, f"{command.name} has no handler"


def test_the_palette_lists_the_line_mode_commands_too():
    """The gap this closed.

    The interface had four commands and line mode had fifteen, nine of them
    only in the latter -- so choosing a frontend was choosing which half of the
    commands you had. The palette is now the single place a person looks.
    """
    pytest.importorskip("textual")

    from tonyagent.cli.tui import COMMANDS

    names = {c.name for c in COMMANDS}
    for expected in ("/plan", "/state", "/usage", "/tools", "/reasoning",
                     "/sandbox", "/conversations", "/new", "/key"):
        assert expected in names, f"{expected} is line-mode only again"


def test_a_palette_option_carries_its_run_name_not_its_command_name():
    """The mismatch that made every command report itself unwired."""
    pytest.importorskip("textual")

    from tonyagent.cli.widgets import Command

    command = Command("/mode", "Switch mode", "pick_mode")
    assert command.name != command.run
    # Dispatch is by `run`, so the option id must be the run name.
    assert command.run == "pick_mode"


def test_ctrl_p_is_ours_and_textuals_is_displaced():
    """Textual binds ctrl+p to its own palette and it wins.

    `BINDINGS` on the App are checked before an action of the same name, so
    declaring `ctrl+p` produced Textual's palette -- listing Keys, Quit and
    Theme -- and our handler never ran. That is exactly what was reported.

    Rather than fight it, our palette is on `ctrl+shift+p` and Textual's stays
    on `ctrl+p`, so both exist. Worth pinning because the collision is silent:
    the app does not error, it just shows the wrong list.
    """
    pytest.importorskip("textual")

    from tonyagent.cli.tui import TonyApp

    keys = {b.key for b in TonyApp.BINDINGS}
    assert "ctrl+shift+p" in keys, "our palette lost its key again"
    # Plain ctrl+p is deliberately left alone; it still reaches Textual's.
    assert "ctrl+p" not in keys


def test_palette_filtering_is_a_substring_over_name_and_description():
    """`plan` finds `/plan` and `/mode`, whose description mentions plan."""
    pytest.importorskip("textual")

    from tonyagent.cli.widgets import Command, _matches

    plan = Command("/plan", "Show the task list", "show_plan")
    mode = Command("/mode", "Switch mode: chat, build, plan, mission", "pick_mode")
    tools = Command("/tools", "Per-turn tool call budget", "show_tools")

    assert _matches(plan, "plan") is True
    assert _matches(mode, "plan") is True
    assert _matches(tools, "plan") is False
    assert _matches(plan, "") is True
    assert _matches(plan, "nonsense") is False


# --- the client ------------------------------------------------------------


class _FakeCore:
    """A core that answers what a test tells it to, over a real pipe.

    A real subprocess rather than a mock object, because the property under
    test *is* the framing: that two JSON objects on a pipe come back as two
    replies, in order, with events interleaved and neither mistaken for the
    other. A mock would assert the call, not the wire.
    """

    def __init__(self, script: str) -> None:
        self.proc = subprocess.Popen(  # noqa: S603
            [sys.executable, "-u", "-c", script],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            bufsize=1,
        )

    def send(self, frame: dict) -> None:
        self.proc.stdin.write(json.dumps(frame) + "\n")
        self.proc.stdin.flush()


def test_a_reply_is_matched_by_id_not_by_arrival_order():
    """The failure this whole client exists to avoid.

    An event is pushed between a request and its reply. A client that read one
    line per request would hand `message.delta` back as the answer to `send`.
    """
    script = (
        "import json,sys\n"
        "for line in sys.stdin:\n"
        "    req = json.loads(line)\n"
        "    sys.stdout.write(json.dumps({'event':'message.delta',"
        "'payload':{'text':'streamed'}}) + '\\n')\n"
        "    sys.stdout.write(json.dumps({'id': req['id'],"
        "'result': {'ok': True}}) + '\\n')\n"
        "    sys.stdout.flush()\n"
    )
    core = _FakeCore(script)
    events = []
    client = CoreClient(on_event=lambda kind, payload: events.append((kind, payload)))
    client.proc = core.proc
    client._reader = threading.Thread(target=client._read_stdout, daemon=True)
    client._reader.start()

    assert client.call("send", {"text": "hi"}) == {"ok": True}
    # The event went to the callback, not into the reply.
    assert ("message.delta", {"text": "streamed"}) in events
    core.proc.kill()


def test_two_concurrent_calls_get_their_own_replies():
    """A cancel arriving on a keypress while the main thread asks for state."""
    script = (
        "import json,sys,time\n"
        "for line in sys.stdin:\n"
        "    req = json.loads(line)\n"
        "    if req['method'] == 'slow': time.sleep(0.3)\n"
        "    sys.stdout.write(json.dumps({'id': req['id'],"
        "'result': req['method']}) + '\\n')\n"
        "    sys.stdout.flush()\n"
    )
    core = _FakeCore(script)
    client = CoreClient()
    client.proc = core.proc
    client._reader = threading.Thread(target=client._read_stdout, daemon=True)
    client._reader.start()

    answers = {}

    def slow():
        answers["slow"] = client.call("slow", timeout=10)

    thread = threading.Thread(target=slow)
    thread.start()
    time.sleep(0.05)
    answers["fast"] = client.call("cancel", timeout=10)
    thread.join(timeout=10)

    assert answers["fast"] == "cancel"
    assert answers["slow"] == "slow"
    core.proc.kill()


def test_an_error_reply_raises_with_its_code():
    script = (
        "import json,sys\n"
        "for line in sys.stdin:\n"
        "    req = json.loads(line)\n"
        "    sys.stdout.write(json.dumps({'id': req['id'],"
        "'error': {'message': 'nope', 'code': 'rejected'}}) + '\\n')\n"
        "    sys.stdout.flush()\n"
    )
    core = _FakeCore(script)
    client = CoreClient()
    client.proc = core.proc
    client._reader = threading.Thread(target=client._read_stdout, daemon=True)
    client._reader.start()

    with pytest.raises(CoreError) as caught:
        client.call("send", timeout=10)
    assert "nope" in str(caught.value)
    assert caught.value.code == "rejected"
    core.proc.kill()


def test_a_dead_core_reports_the_stderr_tail():
    """A startup failure is visible only on stderr.

    "the core did not start" with no stderr would send the user looking in
    entirely the wrong place -- the config, the keyring, the import that
    failed -- all of which are only named in the log.
    """
    script = "import sys; sys.stderr.write('no module named tonyagent\\n'); sys.exit(3)\n"
    core = _FakeCore(script)
    client = CoreClient()
    client.proc = core.proc
    client._reader = threading.Thread(target=client._read_stdout, daemon=True)
    threading.Thread(target=client._read_stderr, daemon=True).start()
    core.proc.wait(timeout=10)
    time.sleep(0.2)

    with pytest.raises(CoreError) as caught:
        client.call("state", timeout=5)
    assert "tonyagent" in str(caught.value)
    core.proc.kill()


def test_a_hanging_request_times_out_rather_than_blocking_forever():
    """A REPL that never returns to its prompt is indistinguishable from a
    crash, and a timeout is at least a message."""
    script = "import sys\nfor line in sys.stdin:\n    pass\n"
    core = _FakeCore(script)
    client = CoreClient()
    client.proc = core.proc
    client._reader = threading.Thread(target=client._read_stdout, daemon=True)
    client._reader.start()

    with pytest.raises(CoreError):
        client.call("send", timeout=0.5)
    core.proc.kill()


def test_core_argv_keeps_the_unbuffered_flag():
    """`-u` is load-bearing.

    Without it stdout becomes block-buffered on a pipe, and every streaming
    frame sits waiting for 8KB or an exit -- so the transcript appears in
    chunks, long after the model emitted them. It looks like slowness rather
    than like buffering, which is why it is pinned here.
    """
    argv = core_argv()
    assert argv[1] == "-u"
    assert argv[2:] == ["-m", "tonyagent.headless.server"]


def test_the_console_script_is_declared():
    """`tony` on PATH, so the installed copy is not `python -m` every time."""
    import tomllib
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    with (root / "pyproject.toml").open("rb") as handle:
        config = tomllib.load(handle)
    assert config["project"]["scripts"]["tony"] == "tonyagent.cli.repl:main"
