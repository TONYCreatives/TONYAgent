"""Run a turn through the real `opencode` binary, and speak the core's grammar.

**Why this exists.** OpenCode's free-tier models answer
`403 FreeTierError: OpenCode's free tier can only be used from within OpenCode`
to any third-party client, with or without a key. The server is deciding, and
no header TONYAgent can set changes that. The one thing that *is* OpenCode is
the OpenCode binary, so the way to reach those models from here is to let
OpenCode do the work and draw the result.

**What this is, precisely: a second backend, not a fourth provider.** A provider
adapter would be the wrong seam and quietly dangerous: TONYAgent's session
executes the tool calls a provider returns, so a shim carrying OpenCode's tool
calls would run every one of them a second time -- the file edits included,
twice. So this is a backend for the interface. TONYAgent's tools, permission
levels and sandbox are *not* in the loop when this is on; OpenCode's are, under
OpenCode's rules, and the top bar says whose agent is running.

**The stream is translated, not reformatted.** `opencode run --format json`
emits `step-start` / `text` / `tool` / `step-finish`, and the transcript carries
real token counts and cache hits -- so the context meter and the turn footer
read the provider's own numbers rather than an estimate, which is the same
standard the direct provider path holds itself to.

**The event names disagree with themselves, and that is why `part.type` is the
field read.** In one recorded turn the outer `type` was `step_start`,
`tool_use` and `step_finish` while `part.type` was `step-start`, `tool` and
`step-finish`. Outer `type` and `part.type` agree for `text` and disagree for
everything else, so a parser keying on the outer field gets tool calls silently
wrong on the exact stream this is meant to handle.
"""

from __future__ import annotations

import json
import subprocess
import threading
from collections.abc import Callable, Iterator
from typing import Any, Optional

#: What a translated event looks like: `(kind, payload)`, the same pair
#: `_apply_core_event` already takes from the core.
Event = tuple[str, dict[str, Any]]


class DelegateError(RuntimeError):
    """The binary could not be run, or refused the turn."""


def opencode_argv(
    prompt: str,
    *,
    model: str = "",
    session: str = "",
    auto: bool = True,
    project: str = "",
) -> list[str]:
    """The command line, as a list.

    **`--auto` is passed by default and this is a decision, not a convenience.**
    OpenCode's tools ask for permission, and `opencode run` is non-interactive,
    so without it a turn that wants to read a file dies at a prompt nobody is
    there to answer. That is the right default for a person who has chosen this
    backend deliberately -- and the interface says so on the top bar, because
    "always auto-approve" should never be something you discover afterwards.
    """
    argv = ["opencode", "run", "--format", "json"]
    if model:
        argv += ["--model", model]
    if session:
        argv += ["--session", session]
    if auto:
        argv.append("--auto")
    if project:
        argv += ["--project", project]
    argv.append(prompt)
    return argv


def translate(line: str) -> list[Event]:
    """One JSONL line into zero or more core-shaped events.

    Returns a list because one line can mean two things: a completed tool call
    is both `tool.started` and `tool.completed`, and the core's transcript
    wants both so the line is drawn running and then ticked.
    """
    text = line.strip()
    if not text:
        return []
    try:
        record = json.loads(text)
    except json.JSONDecodeError:
        # A progress line or a stray warning. Dropping it is better than
        # ending the turn over a line that was never an event.
        return []
    if not isinstance(record, dict):
        return []

    # **Errors arrive top-level, with no `part` at all.** Measured: a bad model
    # id prints
    #     {"type":"error","error":{"type":"provider.no-route",
    #      "message":"Model unavailable: opencode/no-such-model-xyz"}}
    # on *stdout*, exits 1, and writes nothing to stderr. Reading stderr for the
    # reason -- which is what this function did first -- finds nothing and
    # reports "opencode exited 1", the one message nobody can act on. This is
    # also the clearest evidence that the outer `type` field has its own
    # vocabulary (`error`, `step_start`, `tool_use`, `step_finish`) that is not
    # the one `part.type` uses.
    if record.get("type") == "error":
        error = record.get("error")
        detail = error if isinstance(error, dict) else {}
        message = str(detail.get("message") or record.get("message") or "opencode failed")
        return [("turn.failed", {"error": message})]

    part = record.get("part")
    if not isinstance(part, dict):
        return []

    kind = part.get("type")
    if kind == "text":
        body = part.get("text")
        if not isinstance(body, str) or not body:
            return []
        # Sent whole rather than as one-character deltas: `opencode run` emits
        # complete parts, not tokens, so a delta here would be a fiction about
        # how the text arrived.
        return [("message.delta", {"text": body})]

    if kind == "tool":
        call = part.get("id") or part.get("partID") or ""
        if not call:
            return []
        state = part.get("state") if isinstance(part.get("state"), dict) else {}
        tool_input = state.get("input") if isinstance(state.get("input"), dict) else {}
        started: Event = (
            "tool.started",
            {
                "id": call,
                "name": str(part.get("tool") or "tool"),
                "arguments": tool_input,
            },
        )
        status = str(state.get("status") or "")
        if status in ("completed", "error"):
            payload: dict[str, Any] = {
                "id": call,
                "name": str(part.get("tool") or "tool"),
                "output": state.get("output") or "",
            }
            if status == "error":
                return [
                    started,
                    ("tool.failed", {**payload, "error": "the tool failed"}),
                ]
            return [started, ("tool.completed", payload)]
        # Still running -- or a status this version has not heard of. Reporting
        # it as started and never finishing is the honest rendering.
        return [started]

    if kind == "step-finish":
        tokens = part.get("tokens") if isinstance(part.get("tokens"), dict) else {}
        cache = tokens.get("cache") if isinstance(tokens.get("cache"), dict) else {}
        return [
            (
                "turn.usage",
                {
                    "input_tokens": int(tokens.get("input") or 0),
                    "output_tokens": int(tokens.get("output") or 0),
                    "reasoning_tokens": int(tokens.get("reasoning") or 0),
                    "cache_read": int(cache.get("read") or 0),
                    "cost": part.get("cost"),
                },
            )
        ]

    return []


def session_of(line: str) -> str:
    """The OpenCode session id a line carries, or empty.

    Read separately from `translate` because the id is bookkeeping rather than
    something to show: the delegate passes it back as `--session` so
    consecutive turns are one conversation over there instead of a new one each
    time. Every part carries it, so the first line of a turn is enough.
    """
    try:
        record = json.loads(line)
    except (json.JSONDecodeError, TypeError):
        return ""
    if not isinstance(record, dict):
        return ""
    value = record.get("sessionID") or record.get("session_id")
    return value if isinstance(value, str) else ""


def parse_stream(lines: Iterator[str]) -> Iterator[Event]:
    """Every event in a recorded stream, in order."""
    for line in lines:
        yield from translate(line)


class OpenCodeDelegate:
    """Runs one turn per call, in a thread, streaming events back as they land.

    The process is the cancellable unit, because there is no protocol to send a
    polite stop through: terminating it is what a Ctrl-C has to mean here, and
    it is why `interrupt` is a method rather than a flag the caller polls.
    """

    def __init__(
        self,
        on_event: Callable[[str, dict[str, Any]], None],
        *,
        model: str = "",
        auto: bool = True,
        project: str = "",
    ) -> None:
        self._on_event = on_event
        self.model = model
        self.auto = auto
        self.project = project
        #: OpenCode's own session id, learned from the first event and reused
        #: after that, so consecutive turns are one conversation over there.
        self.session = ""
        self._process: Optional[subprocess.Popen[str]] = None

    def run(self, prompt: str, *, timeout: float = 900.0) -> None:
        """Run a turn to completion. Blocks; call it from a worker thread."""
        self._on_event("turn.started", {})
        try:
            self._pump(prompt, timeout=timeout)
        except DelegateError as exc:
            self._on_event("turn.failed", {"error": str(exc)})
            return
        self._on_event("turn.finished", {})

    def _pump(self, prompt: str, *, timeout: float) -> None:
        argv = opencode_argv(
            prompt,
            model=self.model,
            session=self.session,
            auto=self.auto,
            project=self.project,
        )
        try:
            process = subprocess.Popen(  # noqa: S603 - argv is a list, not a shell string
                argv,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )
        except FileNotFoundError:
            raise DelegateError(
                "the opencode binary is not on PATH -- install it, or turn "
                "the delegate off with /delegate"
            ) from None
        except OSError as exc:
            raise DelegateError(f"could not start opencode: {exc}") from None

        self._process = process
        try:
            assert process.stdout is not None
            failed = False
            for line in process.stdout:
                # Learned before translating, so a turn that is interrupted
                # before it finishes still leaves the session id behind and the
                # next turn continues rather than starting over.
                self.session = self.session or session_of(line)
                for event in translate(line):
                    if event[0] == "turn.failed":
                        failed = True
                    self._on_event(*event)
            stderr = process.stderr.read() if process.stderr else ""
            code = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            self.interrupt()
            raise DelegateError("opencode ran past the turn timeout") from None
        finally:
            self._process = None

        if code != 0 and not failed:
            # Normally the reason already arrived as a `turn.failed` event on
            # stdout. This is the shape nobody expected -- a non-zero exit with
            # nothing said -- so stderr is quoted if there is any, and only then
            # is the exit code itself the whole story.
            detail = (stderr or "").strip().splitlines()
            raise DelegateError(
                detail[-1] if detail else f"opencode exited {code} without saying why"
            )

    def interrupt(self) -> None:
        """Stop the running turn.

        There is no polite stop in this protocol, so this is a kill. That is the
        honest cost of driving a binary rather than a socket, and it is why the
        top bar names the backend: Ctrl-C here means something slightly sharper
        than it does on the direct path.
        """
        process, self._process = self._process, None
        if process is None or process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()

    def close(self) -> None:
        self.interrupt()
        self.session = ""


def opencode_available() -> bool:
    """Whether the binary can be found at all, for the mode switch to check."""
    try:
        subprocess.run(  # noqa: S603,S607 - a version probe, no shell
            ["opencode", "--version"],
            capture_output=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return True


__all__ = [
    "DelegateError",
    "Event",
    "OpenCodeDelegate",
    "opencode_argv",
    "opencode_available",
    "parse_stream",
    "translate",
]


def run_in_thread(delegate: OpenCodeDelegate, prompt: str) -> threading.Thread:
    """A delegate turn on its own thread, so the interface stays responsive."""
    thread = threading.Thread(
        target=delegate.run, args=(prompt,), daemon=True, name="tony-delegate"
    )
    thread.start()
    return thread
