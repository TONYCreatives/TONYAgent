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
    if os.name == "nt":
        # `SystemRoot` and `SystemDrive` are not displays, and the Windows
        # loader reads both for every child process. Without `SystemRoot` the
        # child cannot even import `asyncio` -- `_overlapped` starts Winsock
        # and answers `[WinError 10106]` -- so the test measured the platform
        # instead of the import. Without `SystemDrive` the loader's activation
        # cache resolves
        # `%SystemDrive%\ProgramData\Microsoft\Windows\Caches` *relatively*
        # and drops a literal `%SystemDrive%` directory into the working
        # directory, which here is the repository. The display is what is
        # being cleared; these are the platform requirements that survive it.
        # `noqa: SIM112` -- capitalisation is not a style question here. These
        # two are Windows' own names, spelled exactly this way, and "fixing"
        # the warning would blank both and break every child process.
        env["SystemRoot"] = os.environ.get("SystemRoot", "")  # noqa: SIM112
        env["SystemDrive"] = os.environ.get("SystemDrive", "")  # noqa: SIM112
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


# --- the inline command list ----------------------------------------------


def test_a_slash_is_not_its_own_match():
    """Typing `/` and getting nothing back is how a command set looks empty."""
    pytest.importorskip("textual")

    import asyncio

    from textual.widgets import Input, OptionList

    from tonyagent.cli.tui import COMMANDS, TonyApp

    class _Client:
        on_event = None

        def call(self, method, params=None, timeout=None):
            return {"state": {"mode": "build", "model": "m", "permission": "medium"}}

        def notify(self, method, params=None):
            return {}

    async def run() -> None:
        app = TonyApp(_Client())
        async with app.run_test(size=(96, 24)) as pilot:
            await pilot.pause()
            composer = app.query_one("#composer", Input)
            composer.focus()
            await pilot.pause()
            await pilot.press("/")
            await pilot.pause()
            menu = app.query_one("#slash-menu", OptionList)
            assert menu.display, "typing / showed nothing"
            assert menu.option_count == len(COMMANDS)
            # Both columns in the row. The description was being passed as the
            # option id once, which rendered bare names and dropped the help.
            first = menu.get_option_at_index(0).prompt
            assert "Switch mode" in str(first)

    asyncio.run(run())


def test_two_enters_complete_and_then_run(monkeypatch):
    """The first Enter completes, the second submits.

    Without hiding the list on an exact match, `/state ` kept matching `/state`
    and the command never ran -- the list completed itself forever.
    """
    pytest.importorskip("textual")

    import asyncio

    from textual.widgets import Input, OptionList

    from tonyagent.cli.tui import TonyApp

    calls: list[str] = []

    class _Client:
        on_event = None

        def call(self, method, params=None, timeout=None):
            calls.append(method)
            return {
                "state": {"mode": "build", "model": "m", "permission": "medium"},
                "trajectory": {"rendered": "", "summary": ""},
            }

        def notify(self, method, params=None):
            return {}

    async def run() -> None:
        app = TonyApp(_Client())
        async with app.run_test(size=(96, 24)) as pilot:
            await pilot.pause()
            app.query_one("#composer", Input).focus()
            await pilot.pause()
            for char in "/tr":
                await pilot.press(char)
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            assert app.query_one("#composer", Input).value == "/trajectory "
            # The list steps aside once the name is complete.
            assert not app.query_one("#slash-menu", OptionList).display

            await pilot.press("enter")
            await pilot.pause()
            await pilot.pause()
            assert "plan.get" in calls or "state" in calls

    asyncio.run(run())


def test_a_slash_inside_a_sentence_does_not_open_the_list():
    """`read /etc/hosts` is a path, not a command.

    Opening a menu over it would swallow the Enter that was meant to send the
    turn, which is worse than no menu.
    """
    pytest.importorskip("textual")

    import asyncio

    from textual.widgets import Input, OptionList

    from tonyagent.cli.tui import TonyApp

    class _Client:
        on_event = None

        def call(self, method, params=None, timeout=None):
            return {"state": {"mode": "build", "model": "m", "permission": "medium"}}

        def notify(self, method, params=None):
            return {}

    async def run() -> None:
        app = TonyApp(_Client())
        async with app.run_test(size=(96, 24)) as pilot:
            await pilot.pause()
            composer = app.query_one("#composer", Input)
            composer.focus()
            await pilot.pause()
            composer.value = "read /etc/hosts"
            await pilot.pause()
            assert not app.query_one("#slash-menu", OptionList).display

    asyncio.run(run())


def test_every_slash_option_carries_its_run_name():
    """The prompt holds both columns; the id is what dispatch uses.

    The natural-looking `Option(name, description)` passes the description as
    the id, which renders bare names and dispatches to nothing.
    """
    pytest.importorskip("textual")

    import inspect

    from tonyagent.cli.tui import TonyApp

    source = inspect.getsource(TonyApp._refresh_slash_menu)
    assert "Option(label, command.run)" in source
    assert "Option(command.name, command.description)" not in source


# --- the pickers -----------------------------------------------------------


def test_a_picker_header_has_no_id_rather_than_an_empty_one():
    """`id=""` is a real id to an `OptionList`, so two headers collide.

    Found by mounting one: `DuplicateID` at the second group header. `None` is
    how an option says "I have no id", which is what a header is.
    """
    pytest.importorskip("textual")

    import inspect

    from tonyagent.cli.widgets import PickerDialog

    source = inspect.getsource(PickerDialog._rebuild)
    assert "id=None, disabled=True" in source
    assert 'id=""' not in source


def test_a_picker_puts_the_current_value_first():
    """So the groups stay contiguous.

    Left in the server's order, `low / medium / high / full` alternates between
    two groups and the header is drawn three times for one list.
    """
    pytest.importorskip("textual")

    import asyncio

    from tonyagent.cli.tui import TonyApp

    class _Client:
        on_event = None

        def call(self, method, params=None, timeout=None):
            # Dispatched on the method. A stub that returned one dict for
            # everything looks fine until the frontend asks for `permissions`
            # and finds a dict with `permission.list` in it instead.
            return {
                "state": {"mode": "build", "model": "m", "permission": "medium",
                          "bound": True},
                "permission.list": {
                    "permission": "medium",
                    "permissions": [{"name": n} for n in ("low", "medium", "high", "full")],
                },
            }.get(method, {})

        def notify(self, method, params=None):
            return {}

    async def run() -> None:
        app = TonyApp(_Client())
        async with app.run_test(size=(80, 22)) as pilot:
            await pilot.pause()
            await pilot.press("ctrl+3")
            await pilot.pause()
            await pilot.pause()
            groups = [e.group for e in app.screen.entries]
            # One contiguous run per group: `levels` appears once at the head
            # of its run, not again after the current entry in the middle.
            assert groups == ["current", "levels", "levels", "levels"]
            assert app.screen.entries[0].value == "medium"
            app.exit()

    asyncio.run(run())


def test_the_model_picker_filters_hundreds_of_models():
    """The filter is what makes a provider's model list usable.

    OpenRouter answers with several hundred. A list you have to arrow through
    is not a small inconvenience -- it is the feature missing.
    """
    pytest.importorskip("textual")

    import asyncio

    from tonyagent.cli.tui import TonyApp

    models = [f"vendor-{n}/model-{n}" for n in range(300)] + ["anthropic/claude-sonnet-4"]

    class _Client:
        on_event = None

        def call(self, method, params=None, timeout=None):
            return {
                "state": {"mode": "build", "model": "anthropic/claude-sonnet-4",
                          "permission": "medium", "bound": True, "provider": "openrouter"},
                "models.catalog": {
                    "models": [{"id": m, "context_length": 0, "pricing": {}} for m in models],
                    "current": "anthropic/claude-sonnet-4",
                },
            }.get(method, {})

        def notify(self, method, params=None):
            return {}

    import unittest.mock

    async def run() -> None:
        app = TonyApp(_Client())
        async with app.run_test(size=(92, 26)) as pilot:
            await pilot.pause()
            # OpenCode is stubbed out: `/model` also reads `opencode models`,
            # and on a machine with OpenCode installed that added 39 real rows
            # to a test about 301 fake ones. A test that changes size depending
            # on what happens to be on PATH is not a test.
            with unittest.mock.patch(
                "tonyagent.cli.tui.opencode_available", return_value=False
            ):
                await pilot.press("ctrl+2")
                await pilot.pause()
                await pilot.pause()
            # The current model is already in the list and is not duplicated:
            # it is lifted to the top rather than added again.
            assert len(app.screen.entries) == len(models)
            assert app.screen.entries[0].value == "core:anthropic/claude-sonnet-4"

            from textual.widgets import Input

            app.screen.query_one("#picker-filter", Input).value = "sonnet"
            await pilot.pause()
            await pilot.pause()
            from textual.widgets import OptionList

            shown = app.screen.query_one("#picker-options", OptionList).option_count
            # One header plus one model.
            assert shown == 2, f"{shown} rows survived the filter"
            app.exit()

    asyncio.run(run())


def test_the_model_picker_refreshes_state_before_binding():
    """The bind needs the provider's name, and `state` may not have been polled
    on a cold start. An empty name fails at the core, having looked like a
    selection the user made correctly."""
    pytest.importorskip("textual")

    import asyncio

    from tonyagent.cli.tui import TonyApp

    bound: list[dict] = []

    class _Client:
        on_event = None

        def call(self, method, params=None, timeout=None):
            if method == "bind_provider":
                bound.append(params or {})
                return {}
            return {
                "state": {"mode": "build", "model": "anthropic/claude-sonnet-4",
                          "permission": "medium", "bound": True, "provider": "openrouter"},
                "models.catalog": {
                    "models": [{"id": "anthropic/claude-sonnet-4",
                                "context_length": 200000, "pricing": {}}],
                    "current": "anthropic/claude-sonnet-4",
                },
            }.get(method, {})

        def notify(self, method, params=None):
            return {}

    async def run() -> None:
        app = TonyApp(_Client())
        async with app.run_test(size=(92, 26)) as pilot:
            await pilot.pause()
            await pilot.press("ctrl+2")
            await pilot.pause()
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            await pilot.pause()
            assert bound, "nothing was bound"
            assert bound[0].get("name") == "openrouter", bound[0]
            app.exit()

    asyncio.run(run())


# --- models.catalog: the numbers beside a model's name ---------------------


def test_pricing_is_read_per_million_not_per_token():
    """Providers publish per-token and everyone quotes per-million.

    OpenRouter publishes `"0.000003"`; the multiplication by a million is the
    only arithmetic here, and it is what makes the number comparable.
    """
    from tonyagent.api.client import _read_pricing

    assert _read_pricing({"prompt": "0.000003", "completion": "0.000015"}) == {
        "input": 3.0,
        "output": 15.0,
    }


def test_absent_pricing_is_not_free():
    """The distinction the whole label rests on.

    An entry with no `pricing` block has not been said to be free -- nobody said
    anything. Both prices zero *is* a statement.
    """
    from tonyagent.api.client import _read_pricing

    assert _read_pricing(None) == {}
    assert _read_pricing({}) == {}
    assert _read_pricing({"prompt": "0", "completion": "0"}) == {"input": 0.0, "output": 0.0}
    assert _read_pricing({"prompt": "n/a"}) == {}
    assert _read_pricing({"prompt": True}) == {}  # a bool is not a price


def test_a_context_length_may_arrive_as_a_string_or_as_nothing():
    """Gateways disagree about the type, and `0` means "not stated"."""
    from tonyagent.api.client import _as_int

    assert _as_int(200000) == 200000
    assert _as_int("128000") == 128000
    assert _as_int(None) == 0
    assert _as_int("") == 0
    assert _as_int(True) == 0
    assert _as_int(-5) == 0


def test_a_free_model_is_labelled_free_and_an_unpriced_one_is_not():
    from tonyagent.cli.tui import _price_label

    assert _price_label({"input": 0.0, "output": 0.0}) == "Free"
    assert _price_label({}) == ""
    assert _price_label(None) == ""
    assert _price_label({"input": 3.0, "output": 3.0}) == "$3/M"
    assert _price_label({"input": 3.0, "output": 15.0}) == "$3 in · $15 out"


def test_a_context_size_is_read_in_the_unit_a_person_uses():
    from tonyagent.cli.tui import _context_label

    assert _context_label(200000) == "200K ctx"
    assert _context_label(128000) == "128K ctx"
    # 1048576 is 1.048576M, and `:g` printed every digit of it.
    assert _context_label(1048576) == "1M ctx"
    assert _context_label(0) == ""
    assert _context_label(None) == ""


def test_the_picker_shows_the_numbers_and_the_current_row_included():
    """`models.catalog`, end to end through the picker."""
    pytest.importorskip("textual")

    import asyncio

    from tonyagent.cli.tui import TonyApp

    catalog = {
        "models": [
            {"id": "anthropic/claude-sonnet-4.5", "context_length": 200000,
             "pricing": {"input": 3.0, "output": 15.0}},
            {"id": "vendor/free-model", "context_length": 128000,
             "pricing": {"input": 0.0, "output": 0.0}},
            {"id": "vendor/unpriced", "context_length": 0, "pricing": {}},
        ],
        "current": "anthropic/claude-sonnet-4.5",
    }

    class _Client:
        on_event = None

        def call(self, method, params=None, timeout=None):
            return {
                "state": {"mode": "build", "model": "anthropic/claude-sonnet-4.5",
                          "permission": "medium", "bound": True, "provider": "openrouter"},
                "models.catalog": catalog,
            }.get(method, {})

        def notify(self, method, params=None):
            return {}

    async def run() -> None:
        app = TonyApp(_Client())
        async with app.run_test(size=(92, 26)) as pilot:
            await pilot.pause()
            await pilot.press("ctrl+2")
            await pilot.pause()
            await pilot.pause()
            notes = {e.label: e.note for e in app.screen.entries}
            assert notes["anthropic/claude-sonnet-4.5"].endswith("200K ctx  $3 in · $15 out")
            assert notes["vendor/free-model"] == "128K ctx  Free"
            # Unpriced, unknown context: no label at all rather than a lie.
            assert notes["vendor/unpriced"] == ""
            app.exit()

    asyncio.run(run())


def test_escape_closes_both_dialogs():
    """The regression.

    Both dialogs defined `action_dismiss` and neither bound Escape to it. The
    base `Screen` binds only tab and ctrl+c, and `Input` -- which has focus,
    because it is the filter -- binds no Escape at all. So the key went nowhere
    and a dialog could only be left by choosing something, which for the model
    picker means a selection the user had not made.
    """
    pytest.importorskip("textual")

    import asyncio

    from tonyagent.cli.tui import TonyApp
    from tonyagent.cli.widgets import CommandPalette, PickerDialog

    for dialog in (PickerDialog, CommandPalette):
        keys = {b.key for b in dialog.BINDINGS}
        assert "escape" in keys, f"{dialog.__name__} cannot be dismissed"
        assert any(b.action == "dismiss" for b in dialog.BINDINGS)

    class _Client:
        on_event = None

        def call(self, method, params=None, timeout=None):
            return {
                "state": {"mode": "build", "model": "anthropic/claude-sonnet-4.5",
                          "permission": "medium", "bound": True, "provider": "openrouter"},
                "models.catalog": {
                    "models": [{"id": "anthropic/claude-sonnet-4.5",
                                "context_length": 200000, "pricing": {}}],
                    "current": "anthropic/claude-sonnet-4.5",
                },
            }.get(method, {})

        def notify(self, method, params=None):
            return {}

    async def run() -> None:
        app = TonyApp(_Client())
        async with app.run_test(size=(86, 24)) as pilot:
            await pilot.pause()
            await pilot.press("ctrl+2")
            await pilot.pause()
            await pilot.pause()
            assert type(app.screen).__name__ == "PickerDialog"
            await pilot.press("escape")
            await pilot.pause()
            await pilot.pause()
            assert type(app.screen).__name__ != "PickerDialog", "escape did nothing"

            await pilot.press("ctrl+shift+p")
            await pilot.pause()
            await pilot.pause()
            assert type(app.screen).__name__ == "CommandPalette"
            await pilot.press("escape")
            await pilot.pause()
            await pilot.pause()
            assert type(app.screen).__name__ != "CommandPalette", "escape did nothing"

    asyncio.run(run())


def test_escaping_a_picker_selects_nothing():
    """Esc is a decline, not a choice of whatever happened to be highlighted.

    Otherwise closing the picker by accident would bind the model under the
    cursor, which is the opposite of what the key means.
    """
    pytest.importorskip("textual")

    import asyncio

    from tonyagent.cli.tui import TonyApp

    bound: list[dict] = []

    class _Client:
        on_event = None

        def call(self, method, params=None, timeout=None):
            if method == "bind_provider":
                bound.append(params or {})
            return {
                "state": {"mode": "build", "model": "anthropic/claude-sonnet-4.5",
                          "permission": "medium", "bound": True, "provider": "openrouter"},
                "models.catalog": {
                    "models": [
                        {"id": "anthropic/claude-sonnet-4.5", "context_length": 200000,
                         "pricing": {}},
                        {"id": "openai/gpt-5", "context_length": 400000, "pricing": {}},
                    ],
                    "current": "anthropic/claude-sonnet-4.5",
                },
            }.get(method, {})

        def notify(self, method, params=None):
            return {}

    async def run() -> None:
        app = TonyApp(_Client())
        async with app.run_test(size=(86, 24)) as pilot:
            await pilot.pause()
            await pilot.press("ctrl+2")
            await pilot.pause()
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()
            await pilot.pause()
            assert bound == [], f"escape bound a model: {bound}"

    asyncio.run(run())


def test_ctrl_c_takes_two_presses_and_says_what_the_second_does():
    """A single ctrl+c used to cancel a turn, and to quit at an idle prompt.

    Both are destructive on a key a terminal hands out for a dozen unrelated
    reasons. Borrowed from OpenCode's two-press interrupt, and worth copying
    precisely because it is *not* a confirmation dialog: it does not steal the
    turn's place on screen, it says one sentence in the transcript.
    """
    pytest.importorskip("textual")

    import asyncio

    from tonyagent.cli.tui import TonyApp

    class _Client:
        on_event = None

        def __init__(self):
            self.cancelled = 0

        def call(self, method, params=None, timeout=None):
            if method == "state":
                return {"mode": "build", "model": "m", "permission": "medium",
                        "bound": False, "busy": False}
            return {}

        def notify(self, method, params=None):
            if method == "cancel":
                self.cancelled += 1

    def last_line(app):
        return app.screen.query_one("#transcript").children[-1].render().plain

    async def idle() -> None:
        client = _Client()
        app = TonyApp(client)
        async with app.run_test(size=(80, 20)) as pilot:
            await pilot.pause()
            app.query_one("#composer").focus()
            await pilot.pause()
            await pilot.press("ctrl+c")
            await pilot.pause()
            assert client.cancelled == 0, "one press cancelled"
            assert app.is_running, "one press quit"
            assert "quit" in last_line(app)

    async def busy() -> None:
        client = _Client()
        app = TonyApp(client)
        async with app.run_test(size=(80, 20)) as pilot:
            await pilot.pause()
            app.query_one("#composer").focus()
            await pilot.pause()
            app._turn_open = True
            await pilot.press("ctrl+c")
            await pilot.pause()
            assert client.cancelled == 0, "one press cancelled a running turn"
            assert app.is_running, "one press quit during a turn"
            assert "interrupt" in last_line(app)
            await pilot.press("ctrl+c")
            await pilot.pause()
            await pilot.pause()
            assert client.cancelled == 1, "the second press did not interrupt"
            assert app.is_running, "ctrl+c quit instead of interrupting"

    asyncio.run(idle())
    asyncio.run(busy())


def test_the_confirm_window_clears_itself():
    """A stray press leaves nothing behind to confuse the next one."""
    pytest.importorskip("textual")

    import asyncio

    from tonyagent.cli.tui import CONFIRM_PRESS_S, TonyApp

    assert CONFIRM_PRESS_S >= 2.0, "too short to be deliberate"
    assert CONFIRM_PRESS_S <= 10.0, "too long for the hint to feel live"

    class _Client:
        on_event = None

        def call(self, method, params=None, timeout=None):
            if method == "state":
                return {"mode": "build", "model": "m", "permission": "medium",
                        "bound": False, "busy": False}
            return {}

        def notify(self, method, params=None):
            return {}

    async def run() -> None:
        app = TonyApp(_Client())
        async with app.run_test(size=(80, 20)) as pilot:
            await pilot.pause()
            app.query_one("#composer").focus()
            await pilot.pause()
            await pilot.press("ctrl+c")
            await pilot.pause()
            assert app._confirm_presses == 1
            app._clear_confirm()
            assert app._confirm_presses == 0
            # The next press starts over rather than firing.
            await pilot.press("ctrl+c")
            await pilot.pause()
            assert app._confirm_presses == 1
            assert app.is_running

    asyncio.run(run())


def test_the_users_own_message_appears_in_the_transcript():
    """It did not.

    The text was stored on the `Turn` and never mounted, so the transcript
    showed the agent answering a question nobody could see. No test caught it,
    because every one of them called `_begin_turn` and then asserted on the
    agent's side.
    """
    pytest.importorskip("textual")

    import asyncio

    from textual.widgets import Static

    from tonyagent.cli.tui import TonyApp

    class _Client:
        on_event = None

        def call(self, method, params=None, timeout=None):
            return {"state": {"mode": "build", "model": "m", "permission": "medium",
                              "bound": False, "busy": False}}

        def notify(self, method, params=None):
            return {}

    async def run() -> None:
        app = TonyApp(_Client())
        async with app.run_test(size=(90, 20)) as pilot:
            await pilot.pause()
            # Sent the way a person sends one: typed into the composer.
            app.query_one("#composer").value = "fix app.py so it exits 0"
            await pilot.press("enter")
            await pilot.pause()
            await pilot.pause()
            # The composer's own text is the source of truth; the transcript's
            # rendered content is what has to contain it.
            rendered = " ".join(
                str(w.render())
                for w in app.screen.query_one("#transcript").query(Static)
            )
            assert "fix app.py so it exits 0" in rendered, (
                f"the user's message is not in the transcript: {rendered!r}"
            )

    asyncio.run(run())


def test_a_long_user_message_is_one_row():
    """The chip is a chip. A wrapped prompt reads as part of the answer."""
    pytest.importorskip("textual")

    from tonyagent.cli.render import _one_line

    assert "\n" not in _one_line("a\nb\nc")
    assert _one_line("x" * 200).endswith("…")


def test_the_chat_list_actions_are_ctrl_chords_not_letters():
    """The filter has focus, and `Input` consumes printable keys as text.

    A `d` binding would either never fire or, given priority, make "delete"
    untypeable in the search box. `ctrl+d` is avoided because the App binds it
    to quit. OpenCode's dialogs use ctrl chords for the same reason.
    """
    pytest.importorskip("textual")

    from textual.widgets import Input

    from tonyagent.cli.widgets import ConversationsDialog

    keys = {b.key for b in ConversationsDialog.BINDINGS}
    assert {"ctrl+r", "ctrl+y", "ctrl+x", "ctrl+t"} <= keys
    # No bare letters, and not the two the App already owns.
    assert not any(k in {"d", "r", "y", "n", "p"} for k in keys)
    assert "ctrl+d" not in keys, "ctrl+d is quit"

    # And the filter really does take printable keys, which is why it must.
    assert not any(b.key == "d" for b in Input.BINDINGS)


def test_every_chat_list_action_reaches_the_app():
    """The dialog returns a sentinel; the app turns it into one request.

    Run inside `run_test` because acting on a sentinel also reports the outcome,
    and reporting touches a widget.
    """
    pytest.importorskip("textual")

    import asyncio

    from tonyagent.cli.tui import TonyApp

    convs = {"conversations": [
        {"id": "c1", "title": "one", "project": "/p", "message_count": 3},
        {"id": "c2", "title": "two", "project": "/p", "message_count": 9},
    ]}

    for sentinel, expected_method, params in [
        ("__new__", "conversations.create", {}),
        ("__duplicate__:c2", "conversations.duplicate", {"id": "c2"}),
        ("__rename__:c2:hello", "conversations.rename", {"id": "c2", "title": "hello"}),
        ("__delete__:c2", "conversations.delete", {"id": "c2"}),
    ]:
        calls: list[tuple[str, dict]] = []

        class _Client:
            on_event = None

            def call(self, method, p=None, timeout=None):
                if method in ("conversations.create", "conversations.duplicate",
                              "conversations.rename", "conversations.delete"):
                    calls.append((method, p))
                    return {}
                return {
                    "state": {"mode": "build", "model": "m", "permission": "medium",
                              "bound": False, "conversation": "c1"},
                    "conversations.list": convs,
                }.get(method, {})

            def notify(self, method, params=None):
                return {}

        async def run(sentinel=sentinel) -> None:
            app = TonyApp(_Client())
            async with app.run_test(size=(90, 20)) as pilot:
                await pilot.pause()
                app._poll_state = lambda: None  # type: ignore[method-assign]
                app._show_conversations = lambda: None  # type: ignore[method-assign]
                app._conversation_chosen(sentinel)
                await pilot.pause()

        asyncio.run(run())
        assert calls, f"{sentinel} sent nothing"
        assert calls[0][0] == expected_method, calls
        assert calls[0][1] == params, calls


def test_switching_a_conversation_draws_its_transcript():
    """`conversations.switch` returns the messages, and they are drawn.

    A reopened chat showing an empty transcript reads as a click that did not
    land, which is the failure the reply's own comment warns about.
    """
    pytest.importorskip("textual")

    import asyncio

    from tonyagent.cli.tui import TonyApp

    class _Client:
        on_event = None

        def call(self, method, params=None, timeout=None):
            if method == "conversations.switch":
                return {
                    "conversation": {"id": "c1", "title": "old chat"},
                    "messages": [
                        {"role": "user", "content": "what did you do"},
                        {"role": "assistant", "content": "I changed the parser"},
                    ],
                    "project": "/p",
                }
            return {"state": {"mode": "build", "model": "m", "permission": "medium",
                              "bound": False, "conversation": "c1"}}

        def notify(self, method, params=None):
            return {}

    async def run() -> None:
        app = TonyApp(_Client())
        async with app.run_test(size=(90, 22)) as pilot:
            await pilot.pause()
            app._poll_state = lambda: None  # type: ignore[method-assign]
            app._switch_conversation("c1")
            await pilot.pause()
            await pilot.pause()
            # Asserted on the rendered screen rather than on the widgets' contents,
            # because that is what a person reads: a Markdown widget's repr is
            # not its text, and asserting on internals would pass whether or
            # not anything was actually drawn.
            screen = " ".join(
                strip.text for strip in app.screen._compositor.render_strips()  # noqa: SLF001
            )
            assert "what did you do" in screen, screen[-400:]
            assert "I changed the parser" in screen, screen[-400:]

    asyncio.run(run())



def test_the_chat_list_is_the_same_width_as_the_model_dialog():
    """It was 80, and went full-bleed in a 78-column terminal.

    No margin either side and the border clipped by the screen edge -- a dialog
    that fills the width reads as a panel rather than as something laid over the
    session, which is the difference between looking designed and not.
    """
    pytest.importorskip("textual")

    import re

    from tonyagent.cli.widgets import CommandPalette, ConversationsDialog, PickerDialog

    def width_of(dialog) -> int:
        # `[^}]*?` rather than `\s*` so a comment inside the block does not
        # break it -- the reason for the number lives there, and will from the
        # next edit.
        match = re.search(r"#\w[\w-]* \{[^}]*?width: (\d+);", dialog.DEFAULT_CSS)
        assert match, f"{dialog.__name__} sets no explicit width"
        return int(match.group(1))

    assert width_of(ConversationsDialog) == width_of(PickerDialog)
    assert width_of(CommandPalette) == width_of(PickerDialog)


def test_the_chat_list_states_its_way_out_on_the_title_row():
    """`esc` against the right edge, as the model dialog does.

    A hint only in the footer is one line further from the key than the model
    dialog puts it, and this footer is long enough to wrap.
    """
    pytest.importorskip("textual")

    import re

    from tonyagent.cli.widgets import ConversationsDialog

    css = ConversationsDialog.DEFAULT_CSS
    assert "conv-head" in css
    assert "conv-esc" in css
    # The title takes the flexible width, or `esc` sits beside it and reads as
    # part of the title rather than as the way out.
    assert "width: 1fr" in css
    # And the footer must be allowed to wrap rather than cut off mid-chord.
    assert re.search(r"#conv-hint \{[^}]*height: auto", css) is not None


def test_the_chat_list_footer_counts_what_it_lists():
    pytest.importorskip("textual")

    from tonyagent.cli.widgets import ConversationsDialog

    two = ConversationsDialog([{"id": "a"}, {"id": "b"}], "a")
    assert two._actions().startswith("2 chats ·")
    one = ConversationsDialog([{"id": "a"}], "")
    assert one._actions().startswith("1 chat ·")


def test_a_saved_message_can_be_a_list_of_parts_not_a_string():
    """It is, and reading it as a string reopened an empty chat.

    `textFromContent` in `app/src/attachments.ts` is the code that already
    reads saved history, and this is a port of it. The test that passed a plain
    string is why the bug survived: the shape is right for every message
    without an attachment.
    """
    from tonyagent.cli.tui import _message_text

    assert _message_text("plain") == "plain"
    assert _message_text([{"text": "a"}, {"text": "b"}]) == "a\n\nb"
    # A text file arrives wrapped for the model, not for the reader.
    assert _message_text([{"text": '<file name="x.py">\nhello\n</file>'}]) == "hello"
    # A part that is not text is skipped, not rendered as `None`.
    assert _message_text([None, {"x": 1}, {"text": "ok"}]) == "ok"
    assert _message_text(None) == ""
    assert _message_text({"not": "a list"}) == ""


def test_a_reopened_transcript_does_not_replay_tool_output():
    """`role: "tool"` rows are skipped.

    Their content is the raw output -- a whole file for `read_file`, stdout for
    a command -- and `showMessages` says why it must not be shown: restored
    history has no tool card to put it in, so replaying it squirts unrelated
    source into the transcript ahead of the answer written from it.
    """
    pytest.importorskip("textual")

    import asyncio

    from tonyagent.cli.tui import TonyApp

    class _Client:
        on_event = None

        def call(self, method, params=None, timeout=None):
            if method == "conversations.switch":
                return {
                    "conversation": {"id": "c1", "title": "old chat"},
                    "messages": [
                        {"role": "user", "content": [{"text": "read the file"}]},
                        {"role": "tool", "content": "1  # a file\n2  # unrelated"},
                        {"role": "assistant", "content": [{"text": "it is sorted"}]},
                    ],
                    "project": "/p",
                }
            return {"state": {"mode": "build", "model": "m", "permission": "medium",
                              "bound": False, "conversation": "c1"}}

        def notify(self, method, params=None):
            return {}

    async def run() -> None:
        app = TonyApp(_Client())
        async with app.run_test(size=(90, 22)) as pilot:
            await pilot.pause()
            app._poll_state = lambda: None  # type: ignore[method-assign]
            app._switch_conversation("c1")
            await pilot.pause()
            await pilot.pause()
            screen = " ".join(
                strip.text
                for strip in app.screen._compositor.render_strips()  # noqa: SLF001
            )
            assert "read the file" in screen, screen[-300:]
            assert "it is sorted" in screen, screen[-300:]
            assert "unrelated" not in screen, "a tool result was replayed as prose"

    asyncio.run(run())


def test_the_top_bar_names_the_chat_before_the_mode():
    """The reference shows a chat name in the tab position, not a mode.

    "Build" there is a name somebody gave a conversation. Reading it as the
    mode put mode first, so the tab said what the agent is *allowed* to do
    rather than what it is *doing it about* -- two different facts, and only
    one of them identifies the thing on screen. Pinned because it is the kind
    of ordering that gets "tidied" back.
    """
    pytest.importorskip("textual")

    import asyncio

    from tonyagent.cli.tui import TonyApp

    class _Client:
        on_event = None

        def call(self, method, params=None, timeout=None):
            return {
                "state": {"mode": "build", "model": "m", "permission": "medium",
                          "bound": True, "conversation": "c1", "project": "/p"},
                "conversations.list": {"conversations": [
                    {"id": "c1", "title": "my chat name", "project": "/p"}]},
                "context.get": {"model": "m", "used": 1, "known": True, "window": 10},
            }.get(method, {})

        def notify(self, method, params=None):
            return {}

    async def run() -> None:
        app = TonyApp(_Client())
        async with app.run_test(size=(90, 18)) as pilot:
            await pilot.pause()
            app._poll_state()
            await pilot.pause()
            await pilot.pause()
            from textual.widgets import Static

            bar = app.screen.query_one("#topbar", Static)
            text = str(bar.render())
            assert "my chat name" in text, text
            assert text.index("my chat name") < text.index("build"), text

    asyncio.run(run())


def test_the_top_bar_says_so_when_nothing_is_open():
    pytest.importorskip("textual")

    from tonyagent.cli.theme import tab_marker

    # An empty tab must not render as a bare accent bar with nothing after it.
    assert tab_marker() in (">", "\u258c", "|")
    assert len(tab_marker()) == 1


def test_the_new_chat_plus_is_clickable_on_exactly_one_column():
    """A terminal reports clicks by position, so this is hit-tested to a cell.

    Safe here where a button over the transcript would not be: the top bar is
    its own row, above everything, so a click on it was always aimed at it. A
    click on the chat title must do nothing at all.
    """
    pytest.importorskip("textual")

    import asyncio

    from tonyagent.cli.tui import TonyApp

    created: list[dict] = []

    class _Client:
        on_event = None

        def call(self, method, params=None, timeout=None):
            if method == "conversations.create":
                created.append(params or {})
            return {
                "state": {"mode": "build", "model": "m", "permission": "medium",
                          "bound": True, "conversation": "c1", "project": "/p"},
                "conversations.list": {"conversations": [
                    {"id": "c1", "title": "a chat", "project": "/p"}]},
                "context.get": {"model": "m", "used": 1, "known": True, "window": 10},
            }.get(method, {})

        def notify(self, method, params=None):
            return {}

    async def run() -> None:
        app = TonyApp(_Client())
        async with app.run_test(size=(84, 16)) as pilot:
            await pilot.pause()
            app._poll_state()
            await pilot.pause()
            await pilot.pause()
            column = app._new_chat_column
            assert column is not None
            assert column > 0, "the + landed at the first column"

            await pilot.click("#topbar", offset=(column, 0))
            await pilot.pause()
            assert len(created) == 1, "clicking the + did not create a chat"

            # Anywhere else on the bar does nothing.
            await pilot.click("#topbar", offset=(2, 0))
            await pilot.pause()
            assert len(created) == 1, "a click on the chat title created a chat"

            # And the keyboard route reaches the same thing.
            await pilot.press("ctrl+n")
            await pilot.pause()
            assert len(created) == 2, "ctrl+n did not create a chat"

    asyncio.run(run())


# --- the mouse: rows that open what they name -------------------------------


def test_a_click_on_a_sidebar_row_opens_what_that_row_names():
    """The sidebar is where the pickers are *found*.

    `ctrl+1`, `ctrl+2` and `ctrl+3` open mode, model and permission, and none of
    the three appears in the footer -- so before this, nothing on screen said
    they existed and the only way in was the slash menu. The row worth clicking
    is the value (`medium`), not the label above it, and the blanks between the
    rows are not rows.
    """
    pytest.importorskip("textual")

    import asyncio

    from tonyagent.cli.tui import TonyApp
    from tonyagent.cli.widgets import PickerDialog, Sidebar

    calls: list[str] = []

    class _Client:
        on_event = None

        def call(self, method, params=None, timeout=None):
            calls.append(method)
            return {
                "state": {"mode": "build", "model": "kimi-k3", "permission": "medium",
                          "bound": True, "project": "/p"},
                "context.get": {"model": "kimi-k3", "used": 314139, "known": True,
                                "window": 1000000},
            }.get(method, {})

        def notify(self, method, params=None):
            return {}

    async def run() -> None:
        app = TonyApp(_Client())
        async with app.run_test(size=(120, 24)) as pilot:
            await pilot.pause()
            app._poll_state()
            await pilot.pause()
            sidebar = app.query_one("#sidebar", Sidebar)
            rows = {target: line for line, target in sidebar._regions.items()}
            assert {"mode", "model", "permission", "context"} <= set(rows), rows
            assert "chat" not in rows, "no chat is open, so there is no Chat row"

            await pilot.click("#sidebar", offset=(1, rows["mode"]))
            await pilot.pause()
            assert isinstance(app.screen, PickerDialog), "the mode row opened nothing"
            await pilot.press("escape")
            await pilot.pause()

            # The line between two rows is not a row.
            await pilot.click("#sidebar", offset=(1, rows["mode"] + 1))
            await pilot.pause()
            assert not isinstance(app.screen, PickerDialog), "a blank line opened something"

            # The meter asks the core again rather than opening anything.
            before = calls.count("context.get")
            await pilot.click("#sidebar", offset=(1, rows["context"]))
            await pilot.pause()
            assert calls.count("context.get") > before, "the meter was not re-measured"

            await pilot.click("#sidebar", offset=(1, rows["permission"]))
            await pilot.pause()
            assert isinstance(app.screen, PickerDialog), "the permission row opened nothing"

    asyncio.run(run())


def test_every_key_the_sidebar_draws_is_a_key_that_works():
    """A hint is a promise, and this is the promise being kept.

    These four chords are handled in `on_key` rather than declared in
    `BINDINGS`, which is exactly how they came to be invisible in the first
    place: the footer lists bindings and nothing else, so there was no way to
    learn a mode picker existed except by typing a slash and reading the list.
    Drawing them beside the rows only helps if they still do what the sidebar
    says they do.
    """
    pytest.importorskip("textual")

    import asyncio

    from tonyagent.cli.tui import TonyApp
    from tonyagent.cli.widgets import Sidebar

    asked: list[str] = []

    class _Client:
        on_event = None

        def call(self, method, params=None, timeout=None):
            asked.append(method)
            return {
                "state": {"mode": "build", "model": "kimi-k3", "permission": "medium",
                          "bound": True, "project": "/p"},
                "context.get": {"model": "kimi-k3", "used": 1, "known": True,
                                "window": 10},
            }.get(method, {})

        def notify(self, method, params=None):
            return {}

    expected = {
        "mode": "mode.list",
        "model": "models.catalog",
        "permission": "permission.list",
        "context": "context.get",
    }
    assert expected.keys() == Sidebar.HINTS.keys(), "a row gained or lost its key"

    async def run() -> None:
        for target, method in expected.items():
            key = Sidebar.HINTS[target]
            asked.clear()
            app = TonyApp(_Client())
            async with app.run_test(size=(120, 24)) as pilot:
                await pilot.pause()
                app._poll_state()
                await pilot.pause()
                asked.clear()  # the mount's own polling is not the key
                await pilot.press(key)
                await pilot.pause()
                assert method in asked, f"{key} (the {target} hint) asked for {asked}"

    asyncio.run(run())


def test_the_sidebar_shows_the_key_beside_each_row_it_names():
    """The chords were invisible; now they are written down where they apply.

    A clickable row that says nothing about itself is one nobody clicks, and on
    a console that does not report the mouse it is one nobody can *use*. The
    key is the half that works everywhere, so it is drawn.
    """
    pytest.importorskip("textual")

    import asyncio

    from tonyagent.cli.tui import TonyApp
    from tonyagent.cli.widgets import Sidebar

    class _Client:
        on_event = None

        def call(self, method, params=None, timeout=None):
            return {
                "state": {"mode": "build", "model": "kimi-k3", "permission": "medium",
                          "bound": True, "project": "/p", "conversation": ""},
                "context.get": {"model": "kimi-k3", "used": 314139, "known": True,
                                "window": 1000000},
            }.get(method, {})

        def notify(self, method, params=None):
            return {}

    async def run() -> None:
        app = TonyApp(_Client())
        async with app.run_test(size=(120, 24)) as pilot:
            await pilot.pause()
            app._poll_state()
            await pilot.pause()
            rendered = app.query_one("#sidebar", Sidebar).render().plain
            for target, key in Sidebar.HINTS.items():
                assert key in rendered, f"{target} says nothing about {key}"
            # And the rows are still found: the key sits beside the name rather
            # than becoming part of it.
            regions = app.query_one("#sidebar", Sidebar)._regions
            assert {"mode", "model", "permission", "context"} <= set(regions.values())

    asyncio.run(run())


def test_the_sidebar_is_there_at_the_width_a_console_window_is():
    """The panel needed 108 columns, and a console window is about 97.

    Measured off the user's own screen: the welcome line wraps at 97, and 1920
    pixels at a readable font is about 106 columns -- so a panel that only
    appeared at 108 was invisible for everyone who never resized the window.
    Three sizes rather than two: full, compact, and gone.
    """
    pytest.importorskip("textual")

    import asyncio

    from tonyagent.cli.tui import (
        SIDEBAR_MIN_WIDTH,
        SIDEBAR_WIDE_WIDTH,
        TonyApp,
    )
    from tonyagent.cli.widgets import Sidebar

    class _Client:
        on_event = None

        def call(self, method, params=None, timeout=None):
            return {"state": {}, "context.get": {}}.get(method, {})

        def notify(self, method, params=None):
            return {}

    async def at(width: int) -> tuple[bool, bool, int]:
        app = TonyApp(_Client())
        async with app.run_test(size=(width, 22)) as pilot:
            await pilot.pause()
            sidebar = app.query_one("#sidebar", Sidebar)
            return sidebar.display, "compact" in sidebar.classes, sidebar.size.width

    shown, compact, _ = asyncio.run(at(97))
    assert shown, "97 columns is a console window, and the panel belongs on it"
    assert compact, "97 is under the wide width, so it is drawn compact"

    assert not asyncio.run(at(SIDEBAR_MIN_WIDTH - 1))[0], "dropped under the floor"

    shown, compact, width = asyncio.run(at(SIDEBAR_WIDE_WIDTH))
    assert shown, "shown at the wide width"
    assert not compact, "and full size, not compact"
    assert width > 26, f"the full panel is wider than the compact one: {width}"


def test_the_meter_reaches_the_screen_at_the_compact_width():
    """The panel was measured once and its late rows were clipped.

    Mode, model, permission, the chat title and the context numbers all arrive
    from the core *after* the mount, so each one makes the panel taller. With
    an automatic height it was measured on an early frame and not again: the
    `Context` row and the bar were in `render()` and drawn below the bottom of
    the box the panel had already claimed. A meter that exists in a unit test
    of the render and on no screen at all is the exact complaint this came
    from, so this reads the compositor rather than `render()`.
    """
    pytest.importorskip("textual")

    import asyncio

    from tonyagent.cli.tui import TonyApp
    from tonyagent.cli.widgets import Sidebar

    class _Client:
        on_event = None

        def call(self, method, params=None, timeout=None):
            return {}

        def notify(self, method, params=None):
            return {}

    async def run() -> str:
        app = TonyApp(_Client())
        async with app.run_test(size=(97, 22)) as pilot:
            await pilot.pause()
            sidebar = app.query_one("#sidebar", Sidebar)
            # The order the core answers in, and no forced relayout after it:
            # the point is that nothing has to be nudged for the row to appear.
            sidebar.update_state(
                {"mode": "build", "model": "kimi-k3", "permission": "medium"}
            )
            await pilot.pause()
            sidebar.set_conversation("fix the parser")
            await pilot.pause()
            sidebar.update_context({"used": 314139, "window": 1000000, "known": True})
            await pilot.pause()
            left = sidebar.region.x
            return "\n".join(
                "".join(segment.text for segment in strip)[left:]
                for strip in app.screen._compositor.render_strips()  # noqa: SLF001
            )

    panel = asyncio.run(run())
    assert "Context" in panel, panel
    assert "314,139" in panel, panel
    assert "31%" in panel, panel
    assert "\u2588" in panel, "the bar was clipped off the bottom"


def test_the_meter_survives_a_short_window():
    """A share of a short column is less than the panel wants.

    `height: 1fr` is what keeps the late rows from being clipped on a normal
    window, and it is also why a 20-row window has a 12-row panel: the blocks
    have to give something up, and the blanks between them are the only rows
    carrying nothing. Without this the meter was clipped again -- silently, at
    every height under 24, which is a small console with a large font.
    """
    pytest.importorskip("textual")

    import asyncio

    from tonyagent.cli.tui import TonyApp
    from tonyagent.cli.widgets import Sidebar

    class _Client:
        on_event = None

        def call(self, method, params=None, timeout=None):
            return {}

        def notify(self, method, params=None):
            return {}

    async def run() -> str:
        app = TonyApp(_Client())
        async with app.run_test(size=(97, 20)) as pilot:
            await pilot.pause()
            sidebar = app.query_one("#sidebar", Sidebar)
            sidebar.update_state({"mode": "build", "model": "kimi-k3", "permission": "medium"})
            await pilot.pause()
            sidebar.set_conversation("fix the parser")
            await pilot.pause()
            sidebar.update_context({"used": 314139, "window": 1000000, "known": True})
            await pilot.pause()
            assert sidebar.size.height < 14, "the blanks should have to go here"
            left = sidebar.region.x
            return "\n".join(
                "".join(segment.text for segment in strip)[left:]
                for strip in app.screen._compositor.render_strips()  # noqa: SLF001
            )

    panel = asyncio.run(run())
    assert "31%" in panel, panel
    assert "\u2588" in panel, panel


def test_the_compact_meter_is_one_line_that_fits_the_panel():
    """`314,139 tokens  31% of 1,000,000` is 33 columns against 23.

    Wrapped, it read `314,139 tokens  31% of` and then a bare `1,000,000` -- a
    number under a line that promises a percentage -- with the bar pushed a row
    further down. The same facts abbreviated fit, because `1M` is what anyone
    calls a million.
    """
    pytest.importorskip("textual")

    import asyncio

    from tonyagent.cli.render import display_width
    from tonyagent.cli.tui import TonyApp
    from tonyagent.cli.widgets import Sidebar

    class _Client:
        on_event = None

        def call(self, method, params=None, timeout=None):
            return {}

        def notify(self, method, params=None):
            return {}

    async def rendered(width: int) -> tuple[list[str], int]:
        app = TonyApp(_Client())
        async with app.run_test(size=(width, 22)) as pilot:
            await pilot.pause()
            sidebar = app.query_one("#sidebar", Sidebar)
            sidebar.update_context({"used": 314139, "window": 1000000, "known": True})
            await pilot.pause()
            return sidebar.render().plain.split("\n"), sidebar.content_size.width

    rows, room = asyncio.run(rendered(97))
    over = [row for row in rows if display_width(row) > room]
    assert not over, f"wider than the {room} columns it has: {over}"
    assert any("1M" in row for row in rows), rows

    rows, room = asyncio.run(rendered(140))
    assert any("of 1,000,000" in row for row in rows), "the full form where it fits"


def test_the_status_line_opens_what_its_parts_name():
    """Under the floor there is no sidebar, so the line is what is left.

    The meter and the permission level lived in the sidebar and nowhere else,
    so on a narrow terminal the only way to either was a chord the footer never
    mentions. The parts are hit-tested in *cells*, because that is what a click
    arrives as and ` · ` is three of them.
    """
    pytest.importorskip("textual")

    import asyncio

    from tonyagent.cli.tui import SIDEBAR_MIN_WIDTH, TonyApp
    from tonyagent.cli.widgets import PickerDialog

    calls: list[str] = []

    class _Client:
        on_event = None

        def call(self, method, params=None, timeout=None):
            calls.append(method)
            return {
                "state": {"mode": "build", "model": "kimi-k3", "permission": "medium",
                          "bound": True, "project": "/home/me/Project"},
                "context.get": {"model": "kimi-k3", "used": 314139, "known": True,
                                "window": 1000000},
            }.get(method, {})

        def notify(self, method, params=None):
            return {}

    async def run() -> None:
        app = TonyApp(_Client())
        # One column under the floor: the only size where the status line is
        # the whole interface. A number here rather than the constant would go
        # stale the next time the floor moves, which it has done once already.
        async with app.run_test(size=(SIDEBAR_MIN_WIDTH - 1, 16)) as pilot:
            await pilot.pause()
            app._poll_state()
            await pilot.pause()
            assert not app.query_one("#sidebar").display, "dropped below the floor"
            spans = {target: (start, end) for start, end, target in app._status_spans}
            assert {"model", "permission", "context"} <= set(spans), spans

            before = calls.count("context.get")
            await pilot.click("#status", offset=(spans["context"][0], 0))
            await pilot.pause()
            assert calls.count("context.get") > before, "the meter part was not re-measured"

            await pilot.click("#status", offset=(spans["permission"][0], 0))
            await pilot.pause()
            assert isinstance(app.screen, PickerDialog), "the permission part opened nothing"

    asyncio.run(run())


def test_a_tool_line_opens_the_output_it_stands_in_for():
    """The one line is the right default and the wrong only.

    A failed command's reason is in the output that line elides, and reaching
    it meant `/trajectory` and a scroll back through the raw frames. The line
    says there is more with a marker, and a click unfolds the tail -- truncated
    from the *front*, because the end is where the error is.
    """
    pytest.importorskip("textual")

    import asyncio

    from textual.app import App as TextualApp

    from tonyagent.cli.widgets import ToolCall, ToolLine

    call = ToolCall(
        id="t1", name="execute_command", summary="pytest -q", done=True, failed=True,
        result="exit 1",
        output="\n".join(f"row {index}" for index in range(30)),
    )

    class _App(TextualApp[None]):
        def compose(self):
            yield ToolLine(call)

    async def run() -> None:
        app = _App()
        async with app.run_test(size=(80, 40)) as pilot:
            line = app.query_one(ToolLine)
            await pilot.pause()
            collapsed = str(line.render())
            assert "row 29" not in collapsed, "the output showed before it was asked for"
            assert ToolLine.CLOSED_GLYPH in collapsed, "nothing says there is more"

            await pilot.click(ToolLine)
            await pilot.pause()
            opened = str(line.render())
            assert line.expanded
            assert "row 29" in opened, "the click did not unfold the output"
            assert "18 earlier lines" in opened
            assert "row 0" not in opened, "the whole output was shown, not its tail"
            assert ToolLine.OPEN_GLYPH in opened

            await pilot.click(ToolLine)
            await pilot.pause()
            assert not line.expanded
            assert "row 29" not in str(line.render())

    asyncio.run(run())


def test_a_tool_line_with_nothing_behind_it_does_not_offer_to_open():
    """A marker with nothing behind it is a lie told by a glyph.

    `result` is the one-line preview this very line draws, so a call that has
    only a preview has nothing to unfold -- and must not hint otherwise, nor
    swallow the click.
    """
    pytest.importorskip("textual")

    import asyncio

    from textual.app import App as TextualApp

    from tonyagent.cli.widgets import ToolCall, ToolLine

    call = ToolCall(id="t1", name="read_file", summary="main.py", done=True,
                    result="42 lines")

    class _App(TextualApp[None]):
        def compose(self):
            yield ToolLine(call)

    async def run() -> None:
        app = _App()
        async with app.run_test(size=(80, 20)) as pilot:
            line = app.query_one(ToolLine)
            await pilot.pause()
            assert ToolLine.CLOSED_GLYPH not in str(line.render())
            await pilot.click(ToolLine)
            await pilot.pause()
            assert not line.expanded, "a call with no output opened on a click"

    asyncio.run(run())


# --- the keyboard: less of it ----------------------------------------------


def test_the_up_arrow_recalls_a_prompt_already_sent():
    """Retyping a prompt is the most expensive thing in here to do by hand.

    The composer is a single-line `Input`, so up and down have no caret to
    move -- which is exactly why they are free to mean what they mean in a
    shell, whose convention this is.
    """
    pytest.importorskip("textual")

    import asyncio

    from textual.widgets import Input

    from tonyagent.cli.tui import TonyApp

    class _Client:
        on_event = None

        def call(self, method, params=None, timeout=None):
            return {"state": {"mode": "build", "model": "m", "permission": "medium"}}

        def notify(self, method, params=None):
            return {}

    async def run() -> None:
        app = TonyApp(_Client())
        async with app.run_test(size=(100, 20)) as pilot:
            await pilot.pause()
            composer = app.query_one("#composer", Input)
            composer.focus()
            await pilot.pause()

            await pilot.press(*"hello tony")
            await pilot.press("enter")
            await pilot.pause()
            assert composer.value == "", "the composer did not clear"

            await pilot.press("up")
            await pilot.pause()
            assert composer.value == "hello tony", "up did not recall the prompt"
            # The caret after the text, so typing continues it rather than
            # landing in front of it.
            assert composer.cursor_position == len("hello tony")

            await pilot.press("down")
            await pilot.pause()
            assert composer.value == "", "down did not come back to an empty field"

    asyncio.run(run())


def test_the_arrows_leave_a_half_typed_line_alone():
    """A recall must not overwrite work in progress.

    Up and down are claimed only while the field is empty, so a line somebody
    is still editing keeps the keys it was already using.
    """
    pytest.importorskip("textual")

    import asyncio

    from textual.widgets import Input

    from tonyagent.cli.tui import TonyApp

    class _Client:
        on_event = None

        def call(self, method, params=None, timeout=None):
            return {"state": {"mode": "build", "model": "m", "permission": "medium"}}

        def notify(self, method, params=None):
            return {}

    async def run() -> None:
        app = TonyApp(_Client())
        async with app.run_test(size=(100, 20)) as pilot:
            await pilot.pause()
            composer = app.query_one("#composer", Input)
            composer.focus()
            await pilot.pause()

            await pilot.press(*"an older prompt")
            await pilot.press("enter")
            await pilot.pause()
            assert composer.value == ""

            await pilot.press(*"draft")
            await pilot.press("up")
            await pilot.pause()
            assert composer.value == "draft", "the half-typed line was replaced"

    asyncio.run(run())


def test_page_keys_scroll_the_transcript():
    """The scrollbar and the wheel are not always there.

    `VerticalScroll` scrolls itself only while it has the focus, and the focus
    is in the composer -- so reading back through a turn meant grabbing a
    column of the screen, or a wheel a keyboard may not have.
    """
    pytest.importorskip("textual")

    import asyncio

    from textual.containers import VerticalScroll
    from textual.widgets import Static

    from tonyagent.cli.tui import TonyApp

    class _Client:
        on_event = None

        def call(self, method, params=None, timeout=None):
            return {"state": {"mode": "build", "model": "m", "permission": "medium"}}

        def notify(self, method, params=None):
            return {}

    async def run() -> None:
        app = TonyApp(_Client())
        async with app.run_test(size=(100, 20)) as pilot:
            await pilot.pause()
            transcript = app.query_one("#transcript", VerticalScroll)
            transcript.mount(Static("\n".join(f"row {index}" for index in range(200))))
            await pilot.pause()
            assert transcript.scroll_offset.y == 0, "the transcript started scrolled"

            await pilot.press("pagedown")
            await pilot.pause()
            paged = transcript.scroll_offset.y
            assert paged > 0, "pagedown did not scroll"

            await pilot.press("pageup")
            await pilot.pause()
            assert transcript.scroll_offset.y < paged, "pageup did not scroll back"

    asyncio.run(run())


def test_the_new_chat_key_is_bound_and_bound_nowhere_else():
    pytest.importorskip("textual")

    from textual.app import App
    from textual.screen import Screen
    from textual.widgets import Input

    from tonyagent.cli.tui import TonyApp

    keys = {b.key for b in TonyApp.BINDINGS}
    assert "ctrl+n" in keys, "the keyboard route to the + is not bound"
    for other in (App, Screen, Input):
        assert "ctrl+n" not in {b.key for b in other.BINDINGS}, other.__name__


# --- /key: setting a provider key from inside the terminal -------------------


def _key_app(**overrides):
    """A TonyApp whose core answers the three calls `/key` makes."""
    from unittest.mock import MagicMock

    calls: list[tuple[str, dict]] = []

    replies = {
        "state": {"mode": "build", "model": "m", "permission": "medium",
                  "bound": True},
        "providers.list": {"providers": [
            {"name": "opencode-go", "has_credentials": False},
            {"name": "openrouter", "has_credentials": True},
        ]},
        "key.list": [{"provider": "openrouter", "name": "default", "active": True}],
        "key.save": {"saved": True, "listed": True},
        "key.delete": {"deleted": True},
    }
    replies.update(overrides)

    client = MagicMock()
    client.on_event = None

    def call(method, params=None, timeout=None):
        calls.append((method, params or {}))
        return replies.get(method, {})

    client.call.side_effect = call
    from tonyagent.cli.tui import TonyApp

    return TonyApp(client), calls


def test_key_saves_from_the_tui_without_the_key_ever_being_rendered():
    """`/key` was show-only, so adding a provider meant leaving the terminal.

    The typed value goes to `key.save` and nowhere else. It is asserted absent
    from every rendered cell, because the core's own security note is that a
    value on stdout is a value in a log strip and a screenshot -- and a terminal
    is the whole UI here, so there is nowhere else for it to leak *to*.
    """
    pytest.importorskip("textual")

    import asyncio

    async def run() -> None:
        app, calls = _key_app()
        async with app.run_test(size=(90, 22)) as pilot:
            await pilot.pause()
            app._poll_state()
            await pilot.pause()
            app._show_keys()
            await pilot.pause()
            await pilot.press(*"go")  # filter to opencode-go
            await pilot.press("enter")
            await pilot.pause()
            await pilot.press(*"oc_sk_secretvalue")
            await pilot.pause()
            screen = "\n".join(
                s.text for s in app.screen._compositor.render_strips()
            )
            assert "oc_sk_secretvalue" not in screen
            assert app.screen.query_one("#key-entry").password
            await pilot.press("enter")
            await pilot.pause()
            saved = [p for m, p in calls if m == "key.save"]
            assert saved == [
                {"provider": "opencode-go", "api_key": "oc_sk_secretvalue",
                 "name": "default"}
            ], saved

    asyncio.run(run())


def test_a_named_key_saves_under_that_name():
    """The keyring has per-name slots, and this is what makes them reachable.

    **The name is a separate field because it cannot be parsed out of the key.**
    The first version typed `provider/name` into the key box; API keys are
    routinely base64 and contain `/`, so the tail became the key *name* and the
    real name went to the provider slot. This test exists to keep that from
    coming back.
    """
    pytest.importorskip("textual")

    import asyncio

    async def run() -> None:
        app, calls = _key_app()
        async with app.run_test(size=(90, 22)) as pilot:
            await pilot.pause()
            app._show_keys()
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            await pilot.press("enter")  # filter -> key field
            await pilot.press(*"sk/live")  # a key that legitimately holds a /
            await pilot.press("tab")  # over to the name
            for _ in range(len("default")):
                await pilot.press("backspace")
            await pilot.press(*"work")
            await pilot.press("enter")  # save from either field
            await pilot.pause()
            saved = [p for m, p in calls if m == "key.save"]
            assert saved == [
                # The `/` is the point: it stayed in the key.
                {"provider": "opencode-go", "api_key": "sk/live", "name": "work"}
            ], saved

    asyncio.run(run())


def test_removing_a_key_is_confirmed_and_the_chord_is_actually_reachable():
    """`ctrl+x` was the first choice and it is `Input`'s `cut`.

    The test presses the key rather than calling `action_remove`, because
    calling the action passes whether or not the key ever arrives -- which is
    exactly how a chord that silently does nothing gets shipped.
    """
    pytest.importorskip("textual")

    import asyncio

    from textual.app import App
    from textual.screen import Screen
    from textual.widgets import Input, OptionList

    from tonyagent.cli.widgets import KeyDialog

    chords = {b.key for b in KeyDialog.BINDINGS}
    assert "ctrl+r" in chords
    for other in (App, Screen, Input, OptionList):
        assert "ctrl+r" not in {b.key for b in other.BINDINGS}, other.__name__

    async def run() -> None:
        app, calls = _key_app()
        async with app.run_test(size=(90, 22)) as pilot:
            await pilot.pause()
            app._show_keys()
            await pilot.pause()
            await pilot.press("ctrl+r")
            await pilot.pause()
            from tonyagent.cli.widgets import ConfirmScreen

            assert isinstance(app.screen, ConfirmScreen)
            assert not [m for m, _ in calls if m == "key.delete"]
            await pilot.press("n")
            await pilot.pause()
            assert not [m for m, _ in calls if m == "key.delete"]
            # Reopen: the dialog closed to make room for the confirmation, so
            # declining has to leave you able to try again rather than nowhere.
            app._show_keys()
            await pilot.pause()
            await pilot.press("ctrl+r")
            await pilot.pause()
            await pilot.press("y")
            await pilot.pause()
            assert [p for m, p in calls if m == "key.delete"] == [
                {"provider": "opencode-go", "name": "default"}
            ]

    asyncio.run(run())


def test_every_list_dialog_is_navigable_by_arrow():
    """The arrows never reached the list in *any* of these dialogs.

    Each is a filter `Input` above an `OptionList`; they are siblings, so a
    keypress went to the Input and then up to the screen, never sideways to the
    list. In the model picker that meant the first row was the only row anyone
    could select. All three are asserted here because the fix is shared and a
    shared fix can be lost on one subclass.
    """
    pytest.importorskip("textual")

    import asyncio

    from textual.widgets import OptionList

    from tonyagent.cli.widgets import (
        Command,
        CommandPalette,
        ConversationsDialog,
        KeyDialog,
        PickerDialog,
        PickerEntry,
    )

    cases = [
        ("picker", PickerDialog("t", [PickerEntry("a", "a"), PickerEntry("b", "b"),
                                      PickerEntry("c", "c")]), "#picker-options"),
        ("palette", CommandPalette([Command("/a", "x", "a"), Command("/b", "y", "b"),
                                    Command("/c", "z", "c")]), "#palette-list"),
        ("keys", KeyDialog([("opencode-go", False), ("openrouter", True)]),
         "#key-options"),
        ("chats", ConversationsDialog(
            [{"id": "c1", "title": "one", "project": "/p"},
             {"id": "c2", "title": "two", "project": "/p"}], "c1"),
         "#conv-options"),
    ]

    async def run() -> None:
        for name, screen, list_id in cases:
            app, _ = _key_app()
            async with app.run_test(size=(90, 22)) as pilot:
                app.push_screen(screen)
                await pilot.pause()
                await pilot.pause()
                options = app.screen.query_one(list_id, OptionList)
                enabled = [
                    i
                    for i in range(options.option_count)
                    if options.get_option_at_index(i).id
                ]
                assert len(enabled) >= 2, f"{name}: nothing to navigate"
                options.highlighted = enabled[0]
                await pilot.pause()
                await pilot.press("down")
                await pilot.pause()
                assert options.highlighted == enabled[1], f"{name}: down did nothing"
                # And it wraps past the group headers to the last real row, so a
                # long list is escapable upwards without closing the dialog.
                await pilot.press("up", "up")
                await pilot.pause()
                assert options.highlighted == enabled[-1], name

    asyncio.run(run())


# --- the OpenCode delegate --------------------------------------------------


def _recorded_turn() -> list[str]:
    """A real `opencode run --format json` transcript, not a hand-written one.

    Recorded against `opencode/space-bunny-free` on 2026-10-16 with a prompt
    that made it call a tool, because the interesting lines in this protocol are
    the ones a text-only turn never produces.
    """
    from pathlib import Path

    fixture = (
        Path(__file__).resolve().parents[2]
        / "tests"
        / "fixtures"
        / "opencode_turn.jsonl"
    )
    assert fixture.exists(), "the recorded turn went missing"
    return fixture.read_text().splitlines()


def test_the_delegate_reads_part_type_not_the_outer_type():
    """The outer `type` and `part.type` disagree, and only one of them is right.

    In the recorded turn the outer field was `step_start`, `tool_use` and
    `step_finish` while `part.type` was `step-start`, `tool` and `step-finish`.
    They agree on `text` and disagree on everything else -- so a parser keyed on
    the outer field silently loses every tool call on the exact stream this
    exists to handle. That is why `part.type` is the field read.
    """
    from tonyagent.cli.delegate import translate

    lines = _recorded_turn()
    outer = {json.loads(line).get("type") for line in lines if line.strip()}
    inner = {
        (json.loads(line).get("part") or {}).get("type")
        for line in lines
        if line.strip()
    }
    assert "tool_use" in outer, "the outer field stopped disagreeing"
    assert "tool" in inner

    kinds = [k for line in lines for k, _ in translate(line)]
    assert "tool.started" in kinds
    assert "tool.completed" in kinds
    assert "message.delta" in kinds
    assert "turn.usage" in kinds


def test_the_delegate_reports_the_providers_own_token_counts():
    """The context meter reads real numbers on this path too.

    `step-finish` carries input/output/reasoning and cache reads. Estimating
    here would mean the delegate path silently met a lower standard than the
    direct one, which is the thing that makes a meter worth having at all.
    """
    from tonyagent.cli.delegate import parse_stream

    usage = [p for k, p in parse_stream(iter(_recorded_turn())) if k == "turn.usage"]
    assert usage, "no usage at all -- the meter would read zero"
    assert usage[0]["input_tokens"] > 0
    assert usage[0]["cache_read"] > 0, "the cache figure was dropped"


def test_the_last_steps_usage_is_never_reported_and_the_meter_says_so():
    """The recorded turn ends on text, with no closing `step-finish`.

    Not a truncated recording -- the file is complete, and the final line is the
    final answer. So the *last* step's token counts never arrive, and the newest
    real figure the meter can hold is from the step before it. That is a
    low-water mark, not a current one, and showing it as current would be the
    exact failure the meter was built to avoid. It is pinned here so the
    behaviour is a decision rather than an accident.
    """
    from tonyagent.cli.delegate import parse_stream

    lines = _recorded_turn()
    last = json.loads(lines[-1])
    assert (last.get("part") or {}).get("type") == "text", "fixture changed"

    events = list(parse_stream(iter(lines)))
    assert [k for k, _ in events][-1] == "message.delta", (
        "if OpenCode starts closing its turns this test should change"
    )
    # The most recent usage available is therefore not the final one, and the
    # interface has to be able to say which step it came from.
    assert events[-2][0] == "turn.usage"


def test_a_completed_tool_call_is_both_started_and_completed():
    """So the line is drawn running and then ticked, the way a core turn is.

    The record arrives whole -- `opencode run` emits finished parts, not
    progress -- so both events come from one line. Emitting only the finished
    one would mean the tool never appeared as running; emitting only the
    started one would mean it never stopped.
    """
    from tonyagent.cli.delegate import translate

    tools = [
        (k, p)
        for line in _recorded_turn()
        for k, p in translate(line)
        if k.startswith("tool.")
    ]
    assert [k for k, _ in tools] == ["tool.started", "tool.completed"]
    started = tools[0][1]
    assert started["name"] == "shell"
    assert started["arguments"] == {"command": "echo tony-probe"}
    assert tools[1][1]["id"] == started["id"]


def test_a_malformed_line_does_not_end_the_turn():
    """OpenCode prints progress and warnings on the same stream as the events."""
    from tonyagent.cli.delegate import parse_stream

    lines = ["not json at all", "", "[]", '{"no":"part"}', *_recorded_turn()]
    kinds = [k for k, _ in parse_stream(iter(lines))]
    assert "message.delta" in kinds
    assert "tool.started" in kinds


def test_the_delegate_passes_auto_and_is_never_silent_about_it():
    """`opencode run` is non-interactive, so permission prompts cannot be answered.

    That makes `--auto` the difference between a working backend and one that
    dies on the first file read. It is passed by default, and the top bar names
    the backend -- auto-approve must be something you can see, not something you
    find out about afterwards.
    """
    import os
    import shutil

    from tonyagent.cli.delegate import opencode_argv

    argv = opencode_argv("hello", model="opencode/space-bunny-free")
    assert "--auto" in argv

    # **The launcher is platform policy, not a constant** (`opencode_command`).
    # npm ships no .exe: where `which` finds only a `.cmd`, CreateProcess
    # cannot run a batch file directly and the prefix is
    # `COMSPEC /c <the .cmd>` -- the whole reason the delegate reported
    # "not on PATH" on Windows. This assertion used to read `argv[:4] ==
    # ["opencode", ...]`, the POSIX half of a policy that has two halves, so it
    # failed on any machine with npm's install while `--auto` -- what the test
    # is for -- was being checked fine.
    found = shutil.which("opencode")
    if os.name == "nt" and found and found.lower().endswith((".cmd", ".bat")):
        launcher = [os.environ.get("COMSPEC") or "cmd.exe", "/c", found]
    elif os.name == "nt" and found:
        launcher = [found]
    else:
        launcher = ["opencode"]
    assert argv[: len(launcher)] == launcher
    at = len(launcher)
    assert argv[at:at + 3] == ["run", "--format", "json"]
    assert argv[-1] == "hello", "the prompt must not be shell-interpreted"
    assert "--auto" not in opencode_argv("hello", auto=False)


def test_a_missing_opencode_binary_says_so_instead_of_crashing():
    from tonyagent.cli.delegate import OpenCodeDelegate

    events: list[tuple[str, dict]] = []
    delegate = OpenCodeDelegate(lambda k, p: events.append((k, p)))
    # A binary that cannot exist. The message has to name the fix, because
    # "No such file or directory" sends nobody to the right place.
    import unittest.mock

    with unittest.mock.patch(
        "subprocess.Popen", side_effect=FileNotFoundError("opencode")
    ):
        delegate.run("hi")
    kinds = [k for k, _ in events]
    assert kinds == ["turn.started", "turn.failed"]
    assert "not on PATH" in events[-1][1]["error"]


def test_an_opencode_refusal_arrives_on_stdout_with_no_part_and_no_stderr():
    """Errors are top-level records on stdout -- not stderr, and not a `part`.

    Measured against the real binary with a bad model id: it printed

        {"type":"error","error":{"type":"provider.no-route",
         "message":"Model unavailable: opencode/no-such-model-xyz"}}

    on stdout, wrote **nothing** to stderr, and exited 1. The first version of
    this read stderr for the reason and would have shown "opencode exited 1" --
    the one message nobody can act on -- so the exact line is pinned here.

    It is also the sharpest evidence for reading `part.type`: the outer `type`
    vocabulary is `error`, `step_start`, `tool_use`, `step_finish`, and has
    nothing to do with `step-start`, `tool`, `step-finish`.
    """
    from tonyagent.cli.delegate import translate

    line = json.dumps({
        "type": "error",
        "timestamp": 1792126087696,
        "sessionID": "ses_x",
        "error": {"type": "provider.no-route",
                  "message": "Model unavailable: opencode/no-such-model-xyz"},
    })
    assert translate(line) == [
        ("turn.failed", {"error": "Model unavailable: opencode/no-such-model-xyz"})
    ]
    # And the part-shaped spelling of an error must not be silently dropped.
    assert translate(json.dumps({"part": {"type": "error"}})) == []


def test_a_non_zero_exit_with_nothing_said_says_it_said_nothing():
    """The shape nobody expected is still a shape, and it gets its own words."""
    from tonyagent.cli.delegate import OpenCodeDelegate

    events: list[tuple[str, dict]] = []
    delegate = OpenCodeDelegate(lambda k, p: events.append((k, p)))

    import unittest.mock

    proc = unittest.mock.MagicMock()
    proc.stdout = iter([""])
    proc.stderr.read.return_value = ""
    proc.wait.return_value = 1
    with unittest.mock.patch("subprocess.Popen", return_value=proc):
        delegate.run("hi")
    assert events[-1][0] == "turn.failed"
    assert "without saying why" in events[-1][1]["error"]


def test_an_error_line_stops_a_second_failure_message():
    """One refusal, one message.

    The stream says why and the exit code repeats it. Reporting both would put
    "Model unavailable" and "opencode exited 1" in the transcript for a single
    mistake.
    """
    from tonyagent.cli.delegate import OpenCodeDelegate

    events: list[tuple[str, dict]] = []
    delegate = OpenCodeDelegate(lambda k, p: events.append((k, p)))

    import unittest.mock

    proc = unittest.mock.MagicMock()
    proc.stdout = iter([json.dumps({
        "type": "error",
        "error": {"message": "Model unavailable: opencode/nope"},
    })])
    proc.stderr.read.return_value = ""
    proc.wait.return_value = 1
    with unittest.mock.patch("subprocess.Popen", return_value=proc):
        delegate.run("hi")
    failures = [p["error"] for k, p in events if k == "turn.failed"]
    assert len(failures) == 1, failures
    assert failures[0] == "Model unavailable: opencode/nope"


def test_the_top_bar_names_the_backend_because_the_transcript_cannot():
    """Both backends draw the same events into the same widgets.

    A delegate turn produces a text part and a tool line, and so does a core
    turn. Reading the transcript afterwards, there is no way to tell whose agent
    ran -- which is why the bar says so, and why `--auto` is spelled out there
    rather than left to be discovered.
    """
    pytest.importorskip("textual")

    import asyncio

    from tonyagent.cli.tui import TonyApp

    class _Client:
        on_event = None

        def call(self, method, params=None, timeout=None):
            return {"state": {"mode": "build", "model": "m", "permission": "medium",
                              "bound": True}}.get(method, {})

        def notify(self, method, params=None):
            return {}

    async def run() -> None:
        app = TonyApp(_Client())
        async with app.run_test(size=(100, 20)) as pilot:
            await pilot.pause()
            app._poll_state()
            await pilot.pause()
            app._topbar_title = "a chat"
            app._render_topbar("a chat")
            await pilot.pause()
            before = "\n".join(
                s.text for s in app.screen._compositor.render_strips()
            )
            assert "opencode" not in before, "the marker showed with the core on"

            import unittest.mock

            with unittest.mock.patch(
                "tonyagent.cli.tui.opencode_available", return_value=True
            ):
                app._toggle_delegate("opencode/space-bunny-free")
            await pilot.pause()
            after = "\n".join(
                s.text for s in app.screen._compositor.render_strips()
            )
            assert "opencode" in after
            assert "--auto" in after, "auto-approve must be visible, not implied"
            # The model is named too: which agent ran, on what, under which
            # permissions is the whole of what the transcript cannot tell you.
            assert "space-bunny-free" in after

    asyncio.run(run())


def test_the_delegate_is_declined_when_the_binary_is_missing():
    """A backend that fails on the first message reads as a model problem.

    Refusing to start is the honest version: the person finds out now, not from
    a transcript that says `opencode exited 1`.
    """
    pytest.importorskip("textual")

    import asyncio
    import unittest.mock

    from tonyagent.cli.tui import TonyApp

    class _Client:
        on_event = None

        def call(self, method, params=None, timeout=None):
            return {"state": {"mode": "build", "model": "m", "permission": "medium",
                              "bound": True}}.get(method, {})

        def notify(self, method, params=None):
            return {}

    async def run() -> None:
        app = TonyApp(_Client())
        async with app.run_test(size=(100, 20)) as pilot:
            await pilot.pause()
            with unittest.mock.patch(
                "tonyagent.cli.tui.opencode_available", return_value=False
            ):
                app._toggle_delegate()
            await pilot.pause()
            assert app._delegate is None

    asyncio.run(run())


def test_delegate_without_a_model_offers_a_picker_instead_of_a_default():
    """`opencode run` with no `--model` uses OpenCode's configured default.

    That default is not a free model unless you made it one, and the free tier
    is the entire reason to be here -- so `/delegate` with no argument asks,
    rather than quietly starting on somebody else's billing. The typed form
    `/delegate opencode/space-bunny-free` skips the question.
    """
    pytest.importorskip("textual")

    import asyncio
    import unittest.mock

    from tonyagent.cli.tui import TonyApp
    from tonyagent.cli.widgets import PickerDialog

    class _Client:
        on_event = None

        def call(self, method, params=None, timeout=None):
            return {"state": {"mode": "build", "model": "m", "permission": "medium",
                              "bound": True}}.get(method, {})

        def notify(self, method, params=None):
            return {}

    async def run() -> None:
        app = TonyApp(_Client())
        async with app.run_test(size=(100, 22)) as pilot:
            await pilot.pause()
            models = ["opencode/space-bunny-free", "opencode/big-pickle",
                      "opencode-go/space-bunny"]
            with unittest.mock.patch(
                "tonyagent.cli.tui.opencode_available", return_value=True
            ), unittest.mock.patch.object(
                TonyApp, "_delegate_models", return_value=models
            ):
                app._toggle_delegate()
                await pilot.pause()
                await pilot.pause()
                assert isinstance(app.screen, PickerDialog)
                assert app._delegate is None, "it started before a model was chosen"

                await pilot.press(*"space-bunny-free")
                await pilot.press("enter")
                await pilot.pause()
                await pilot.pause()
                assert app._delegate is not None
                assert app._delegate.model == "opencode/space-bunny-free"
                # And the typed form skips the picker entirely.
                app._toggle_delegate()
                await pilot.pause()
                app._toggle_delegate("opencode/big-pickle")
                await pilot.pause()
                assert app._delegate.model == "opencode/big-pickle"

    asyncio.run(run())


def test_a_stray_word_after_a_command_does_not_raise():
    """`/trajectory blah` must not call `_show_trajectory("blah")`.

    Arguments are passed only to handlers that declare one, decided by
    signature rather than by whether a word was typed -- otherwise every
    argument-taking command is one typo away from a TypeError raised out of a
    keypress handler.
    """
    from tonyagent.cli.tui import _takes_argument

    assert _takes_argument(lambda: None) is False
    assert _takes_argument(lambda _argument="": None) is True


def test_one_model_picker_covers_both_sources_aligned_by_service():
    """`/model` lists the core's models and OpenCode's, under shared headings.

    **They are aligned, not concatenated.** `opencode models` returns both
    `opencode-go/…` and `opencode/…`, and `opencode-go` is *also* a core
    provider serving the same ids. A literal `split("/")` would give two
    headings for one subscription, which reads as two. And `opencode/` is the
    client-only tier, which the core cannot serve at all, so it is a separate
    heading rather than a footnote.

    Rows for models both routes reach say so; rows only OpenCode can serve say
    that too. Nothing is presented as reachable by a route that cannot run it.
    """
    pytest.importorskip("textual")

    import asyncio
    import unittest.mock

    from tonyagent.cli.tui import TonyApp
    from tonyagent.cli.widgets import PickerDialog

    core_models = [
        {"id": "openrouter/auto", "context_length": 0, "pricing": {}},
        # The same id OpenCode also lists -- served by both routes.
        {"id": "opencode-go/kimi-k3", "context_length": 0, "pricing": {}},
    ]
    opencode_models = [
        "opencode-go/kimi-k3",
        "opencode/space-bunny-free",
        "opencode/deepseek-v4.1-flash-free",
    ]

    class _Client:
        on_event = None

        def call(self, method, params=None, timeout=None):
            return {
                "state": {"mode": "build", "model": "openrouter/auto",
                          "permission": "medium", "bound": True,
                          "provider": "openrouter"},
                "models.catalog": {"current": "openrouter/auto",
                                   "models": core_models},
            }.get(method, {})

        def notify(self, method, params=None):
            return {}

    async def run() -> None:
        app = TonyApp(_Client())
        async with app.run_test(size=(110, 26)) as pilot:
            await pilot.pause()
            with unittest.mock.patch(
                "tonyagent.cli.tui.opencode_available", return_value=True
            ), unittest.mock.patch.object(
                TonyApp, "_delegate_models", return_value=opencode_models
            ):
                app._pick_model()
                await pilot.pause()
                await pilot.pause()
                assert isinstance(app.screen, PickerDialog)
                rows = "\n".join(
                    s.text for s in app.screen._compositor.render_strips()
                )

                # Both sources are in the one list.
                assert "opencode/space-bunny-free" in rows
                assert "opencode-go/kimi-k3" in rows
                assert "openrouter/auto" in rows

                # Aligned by service, not by literal prefix.
                assert "OpenCode Go" in rows
                assert "OpenCode free (client only)" in rows
                assert rows.count("OpenCode Go") == 1, (
                    "the same subscription headed twice -- aligned means adjacent, "
                    "not concatenated"
                )

                # And each row says which route reaches it.
                assert "also via opencode" in rows
                assert "opencode only" in rows

                # One row per model, not one per route. `opencode-go/kimi-k3` is
                # served by the core and listed by OpenCode; two rows for it
                # read as two models. The first version excluded the wrong set
                # (`by_id - opencode_ids`, which is the core's-only models --
                # not in OpenCode's list to begin with) and so excluded nothing.
                assert rows.count("opencode-go/kimi-k3") == 1, rows

                # Choosing a client-only model starts the delegate, rather than
                # being accepted and then ignored by every turn.
                await pilot.press(*"space-bunny-free")
                await pilot.press("enter")
                await pilot.pause()
                await pilot.pause()
                assert app._delegate is not None
                assert app._delegate.model == "opencode/space-bunny-free"

    asyncio.run(run())


def test_choosing_a_core_model_turns_the_delegate_off():
    """A model that is chosen and not used is worse than one never offered.

    Picking a core model while OpenCode is the backend taking the turns would
    be accepted, announced, and then ignored -- the exact failure the single
    picker was built to remove.
    """
    pytest.importorskip("textual")

    import asyncio
    import unittest.mock

    from tonyagent.cli.tui import TonyApp

    calls: list[tuple[str, dict]] = []

    class _Client:
        on_event = None

        def call(self, method, params=None, timeout=None):
            calls.append((method, params or {}))
            return {
                "state": {"mode": "build", "model": "openrouter/auto",
                          "permission": "medium", "bound": True,
                          "provider": "openrouter"},
                "models.catalog": {
                    "current": "openrouter/auto",
                    "models": [{"id": "openrouter/auto", "context_length": 0,
                                "pricing": {}}],
                },
            }.get(method, {})

        def notify(self, method, params=None):
            return {}

    async def run() -> None:
        app = TonyApp(_Client())
        async with app.run_test(size=(110, 26)) as pilot:
            await pilot.pause()
            with unittest.mock.patch(
                "tonyagent.cli.tui.opencode_available", return_value=True
            ):
                app._toggle_delegate("opencode/space-bunny-free")
                await pilot.pause()
                assert app._delegate is not None

                app._apply_model_choice("core:openrouter/auto")
                await pilot.pause()
                assert app._delegate is None
                assert ("bind_provider",
                        {"name": "openrouter", "model": "openrouter/auto"}) in calls

    asyncio.run(run())


def test_every_command_is_wired_and_every_handler_is_reachable():
    """The registry and the dispatch table have to agree, in both directions.

    `/delegate` was implemented, tested, documented and committed, and was
    still "not a command". The `Command(...)` line was inserted with a
    whitespace-sensitive string replacement whose pattern had eight leading
    spaces where the file had four, so it replaced nothing and said nothing --
    and `str.replace` not matching is not an error.

    The handler was in the dispatch table the whole time, so the only trace was
    one dangling key. That is exactly the shape a one-way check misses: a test
    asserting every `Command` has a handler passes, because there was no
    `Command` to check.
    """
    import inspect

    from tonyagent.cli.tui import COMMANDS, TonyApp

    source = inspect.getsource(TonyApp._run_command)
    # Every name the registry can dispatch must appear in the table.
    for command in COMMANDS:
        assert f'"{command.run}"' in source, (
            f"{command.name} dispatches to {command.run!r}, which is not wired"
        )
    # And every key in the table must be something a Command can reach --
    # otherwise it is a handler no command can ever call.
    wired = {
        line.strip().split(":")[0].strip().strip('",')
        for line in source.splitlines()
        if line.strip().startswith('"') and ":" in line
    }
    for command in COMMANDS:
        assert command.run in wired, command.run
    for run in wired:
        assert any(c.run == run for c in COMMANDS), (
            f"{run!r} is handled but no command reaches it"
        )


def test_the_context_meter_survives_the_sidebar_being_dropped():
    """Everything else in the sidebar is duplicated; two things were not.

    Mode is in the top bar, model and project in the status bar. The **context
    meter** and the **permission level** were in the sidebar and nowhere else,
    so at 108 columns and below both silently vanished -- and both are things
    people open a status line for. A narrower terminal is not a reason to stop
    telling you how full the context is.

    The sidebar is the expanded view now; this line is the floor.
    """
    pytest.importorskip("textual")

    import asyncio

    from tonyagent.cli.tui import TonyApp

    class _Client:
        on_event = None

        def call(self, method, params=None, timeout=None):
            return {
                "state": {"mode": "build", "model": "kimi-k3",
                          "permission": "medium", "bound": True,
                          "project": "/home/me/Project", "provider": "opencode-go"},
                "context.get": {"model": "m", "used": 314139, "known": True,
                                "window": 1000000},
            }.get(method, {})

        def notify(self, method, params=None):
            return {}

    async def run(width: int) -> str:
        app = TonyApp(_Client())
        async with app.run_test(size=(width, 14)) as pilot:
            await pilot.pause()
            app._poll_state()
            app._refresh_context()
            await pilot.pause()
            await pilot.pause()
            shown = app.query_one("#sidebar").display
            bar = str(app.screen.query_one("#status").render())
            return f"{shown}|{bar}"

    from tonyagent.cli.tui import SIDEBAR_MIN_WIDTH

    narrow = asyncio.run(run(SIDEBAR_MIN_WIDTH - 1))
    wide = asyncio.run(run(120))
    assert narrow.startswith("False|"), "the sidebar is dropped below the floor"
    assert wide.startswith("True|"), "and shown at 120"
    for label, bar in (("narrow", narrow), ("wide", wide)):
        assert "314K/1M" in bar, f"{label}: {bar}"
        assert "medium" in bar, f"{label}: {bar}"


def test_the_status_line_says_which_half_of_the_context_is_unknown():
    """A shrug is not a measurement.

    `context.get` can answer with the window and no usage, or the reverse. The
    sidebar already said which was missing; the status line has to, because on
    a narrow terminal it is the only place the answer appears at all.
    """
    pytest.importorskip("textual")

    import asyncio

    from tonyagent.cli.tui import TonyApp

    async def summary(payload: dict) -> str:
        class _Client:
            on_event = None

            def call(self, method, params=None, timeout=None):
                return {"state": {"mode": "build", "model": "m",
                                  "permission": "low", "bound": True}}.get(method, {})

            def notify(self, method, params=None):
                return {}

        app = TonyApp(_Client())
        async with app.run_test(size=(90, 14)) as pilot:
            await pilot.pause()
            app._last_context = payload
            # The 0.5s poll would repaint this line in the app; a test does
            # not wait out a timer, so ask for the line directly. Reading the
            # payload is not what redraws it -- `_refresh_status` is.
            app._refresh_status()
            await pilot.pause()
            return str(app.screen.query_one("#status").render())

    assert "ctx 314K/1M" in asyncio.run(
        summary({"used": 314139, "window": 1000000, "known": True})
    )
    assert "ctx unknown" in asyncio.run(
        summary({"used": 0, "window": 0, "known": False})
    )
    # Window known, usage not: say which one is missing.
    assert "ctx ?/1M" in asyncio.run(
        summary({"used": 0, "window": 1000000, "known": False})
    )
    assert "ctx 0/1M" in asyncio.run(
        summary({"used": 0, "window": 1000000, "known": True})
    )


def test_the_app_leaves_textuals_context_method_alone():
    """`self._context` hung every `run_test` test in this file.

    `textual.app.App._context` is a method -- `run_test` opens with
    `with app._context():` -- so an instance attribute of that name replaces
    it with a dict. The app's own task then died of
    `'dict' object is not callable` *before* `on_mount`, which meant
    `app_ready_event` was never set and every test that opened `run_test`
    waited forever instead of failing: a name collision that cost the whole
    suite rather than one red line.

    Pinned cheaply and without `run_test`, because the failure mode this
    guards is a hang and a guard must not share it.
    """
    pytest.importorskip("textual")

    from textual.app import App

    from tonyagent.cli.tui import TonyApp

    class _Client:
        on_event = None

        def call(self, method, params=None, timeout=None):
            return {}

        def notify(self, method, params=None):
            return {}

    app = TonyApp(_Client())
    if hasattr(App, "_context"):  # Textual is a floor of 1.0, not a pin.
        assert getattr(app._context, "__func__", None) is App._context, (
            "TonyApp._context shadows Textual's `with app._context():`, "
            "and run_test hangs forever when it does"
        )


def test_a_poll_that_arrives_after_shutdown_is_a_no_op():
    """The interval outlives the widget tree by one tick.

    `App._shutdown` sets `_running` first, closes the widget pumps next and
    stops the app's own timers last, so a tick queued in that window reached
    `query_one("#sidebar")` on a screen whose widgets were already gone and
    raised `NoMatches` -- which lands in `app._exception`, and `run_test`
    re-raises that at exit. It surfaced in
    `test_every_list_dialog_is_navigable_by_arrow`, which runs four app
    sessions and failed roughly once in several runs: timing, not that test's
    subject.

    Driven without `run_test`, because an app that is not running is exactly
    the state under test -- `_running` is False from construction and only
    becomes True inside the message loop.
    """
    pytest.importorskip("textual")

    from tonyagent.cli.tui import TonyApp

    class _Client:
        on_event = None

        def call(self, method, params=None, timeout=None):
            raise AssertionError("a stopped app must not ask the core anything")

        def notify(self, method, params=None):
            return {}

    app = TonyApp(_Client())
    assert not app.is_running, "an app that never started is the state under test"
    # Must not raise, and must not reach the core: there is no widget tree and
    # no state left to draw into.
    app._poll_state()


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
