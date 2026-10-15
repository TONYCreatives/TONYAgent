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
