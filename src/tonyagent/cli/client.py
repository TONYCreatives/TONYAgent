"""The core as a child process, and a request/reply loop over its pipes.

`tonyagent.window.core` does this for the window; this is the terminal's copy.
The duplication is real and deliberate, because the two differ in something
structural rather than cosmetic:

* the window frames the child's stdout for a page and never blocks on a reply,
  because the React side is the renderer and does not wait for anything;
* a REPL is a *read-eval-print loop*. The prompt cannot come back until the
  current turn has finished, so this client owns a reader thread and a queue,
  and the main thread only ever waits on a future.

Reimplementing that rather than importing the window's pump is the smaller
cost. Sharing it would mean the window's no-reply path and the REPL's blocking
path living in one class, both always on, neither ever quite right.

**Three threads, and what each one owns.**

* the reader thread owns `stdout` and nothing else. It parses lines and pushes
  them onto one queue. It never touches a request, never writes, and never
  raises into the main thread.
* the writer is not a thread. `call()` writes one line under a lock, because
  two threads may legitimately call at once (a keystroke cancelling a turn
  while the main thread asks for `state`). A partial line on a shared pipe is
  not a thing anyone wants to debug.
* the main thread owns the REPL.

**Why the reply is matched by id rather than assumed to be next.** Events are
pushed as they happen, untagged, interleaved with replies in any order. A
client that read one line per request would consume a `message.delta` as if it
were the answer to `send`. So: lines carrying an `id` settle a future; lines
carrying an `event` are dispatched to the event callback; nothing is assumed
about the order of either.

**Reads are unbuffered on purpose.** `-u` on the child's command line is what
makes a token appear as the model emits it rather than when a 8KB block fills.
Dropping it reintroduces the stall this whole file is arranged to avoid.
"""

from __future__ import annotations

import json
import subprocess
import sys
import threading
from collections import deque
from collections.abc import Callable
from typing import Any, Optional

EventCallback = Callable[[str, dict[str, Any]], None]
"""Called as ``callback(event_type, payload)`` for every event frame."""


class CoreError(RuntimeError):
    """The core refused a request, or died while one was in flight."""

    def __init__(self, message: str, code: str = "") -> None:
        super().__init__(message)
        #: The server's own classification ("rejected", "unknown_method", ...).
        #: Kept separate from the text so a caller can tell "you asked wrongly"
        #: from "the core broke", which are different things to report.
        self.code = code


class CoreClient:
    """A running ``tonyagent.headless.server``, spoken to over JSONL."""

    def __init__(
        self,
        *,
        on_event: Optional[EventCallback] = None,
        on_log: Optional[Callable[[str], None]] = None,
    ) -> None:
        self._on_event = on_event
        self._on_log = on_log
        self._next_id = 1
        self._pending: dict[int, threading.Event] = {}
        self._results: dict[int, Any] = {}
        self._errors: dict[int, CoreError] = {}
        self._lock = threading.Lock()
        self._write_lock = threading.Lock()
        self._closed = threading.Event()
        self._reader: Optional[threading.Thread] = None
        self._log_tail: deque[str] = deque(maxlen=200)
        self.proc: Optional[subprocess.Popen[str]] = None

    # -- lifecycle -----------------------------------------------------------

    def start(self, argv: Optional[list[str]] = None) -> None:
        """Spawn the core and start reading it."""
        if self.proc is not None:
            raise CoreError("the core is already running")
        argv = argv or core_argv()
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        self.proc = subprocess.Popen(  # noqa: S603 - argv built here, not by a user
            argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            creationflags=creationflags,
        )
        self._reader = threading.Thread(
            target=self._read_stdout, name="tony-reader", daemon=True
        )
        self._reader.start()
        threading.Thread(
            target=self._read_stderr, name="tony-log", daemon=True
        ).start()

    def close(self) -> None:
        """Shut the core down, escalating only if it will not go."""
        proc = self.proc
        if proc is None:
            return
        self._closed.set()
        try:
            if proc.stdin and not proc.stdin.closed:
                # Closing stdin is the protocol's own EOF signal; the reader loop
                # in the server breaks on it and returns.
                proc.stdin.close()
        except OSError:
            pass
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()

    @property
    def returncode(self) -> Optional[int]:
        return None if self.proc is None else self.proc.poll()

    def log_tail(self) -> list[str]:
        """Recent stderr lines, for a crash report.

        The core logs to stderr and answers on stdout, so a startup failure --
        a bad config, a missing dependency -- is visible *only* here. Reporting
        "the core did not start" with no stderr would send the user looking in
        entirely the wrong place.
        """
        return list(self._log_tail)

    # -- requests ------------------------------------------------------------

    def call(
        self,
        method: str,
        params: Optional[dict[str, Any]] = None,
        timeout: Optional[float] = None,
    ) -> Any:
        """Send one request and wait for its reply.

        `timeout` of None waits forever, which is right for `send`: a turn can
        legitimately run for many minutes and the REPL should not abandon it.
        """
        proc = self.proc
        if proc is None or proc.poll() is not None:
            raise CoreError(self._dead_message())
        with self._lock:
            req_id = self._next_id
            self._next_id += 1
            done = threading.Event()
            self._pending[req_id] = done

        frame = {"id": req_id, "method": method, "params": params or {}}
        try:
            with self._write_lock:
                proc.stdin.write(json.dumps(frame, ensure_ascii=False) + "\n")
                proc.stdin.flush()
        except (OSError, ValueError) as exc:
            self._pending.pop(req_id, None)
            raise CoreError(self._dead_message()) from exc

        if not done.wait(timeout):
            self._pending.pop(req_id, None)
            raise CoreError(f"{method} did not answer within {timeout:g}s", "timeout")

        with self._lock:
            error = self._errors.pop(req_id, None)
            result = self._results.pop(req_id, None)
        if error is not None:
            raise error
        return result

    def notify(self, method: str, params: Optional[dict[str, Any]] = None) -> None:
        """Send a request whose reply is not wanted.

        Used for cancelling a turn from a key handler. The reply is still
        consumed by the reader (so the id is retired properly) and simply
        dropped -- writing it to the void instead would leave a future pending
        forever, which is a leak rather than a shortcut.
        """
        self.call(method, params, timeout=30)

    def _dead_message(self) -> str:
        code = self.returncode
        tail = self.log_tail()
        where = "the core is not running" if code is None else f"the core exited ({code})"
        if tail:
            return f"{where}. Its last output was:\n  " + "\n  ".join(tail[-5:])
        return f"{where}."

    # -- the reader ----------------------------------------------------------

    def _read_stdout(self) -> None:
        proc = self.proc
        if proc is None or proc.stdout is None:
            return
        try:
            for line in proc.stdout:
                self._on_line(line)
        except (ValueError, OSError):
            # The pipe closed under us: the core exited. Outstanding requests
            # are failed below so a blocked REPL wakes up instead of hanging.
            pass
        finally:
            self._fail_all("the core closed its output stream")

    def _on_line(self, line: str) -> None:
        line = line.strip()
        if not line:
            return
        try:
            frame = json.loads(line)
        except ValueError:
            # Not fatal and not worth crashing over. The server is documented
            # to emit one object per line, so this is either a stray print or a
            # future bug; both are better surfaced as a line than as a dead CLI.
            self._log(f"core wrote a line that was not JSON: {line[:200]}")
            return
        if not isinstance(frame, dict):
            return

        if "event" in frame:
            payload = frame.get("payload") or {}
            callback = self._on_event
            if callback is not None:
                try:
                    callback(str(frame["event"]), payload if isinstance(payload, dict) else {})
                except Exception:  # noqa: BLE001 - a renderer bug must not kill the pipe
                    pass
            return

        req_id = frame.get("id")
        if not isinstance(req_id, int):
            return
        with self._lock:
            done = self._pending.pop(req_id, None)
            if done is None:
                return
            if "error" in frame and frame["error"] is not None:
                err = frame["error"]
                if isinstance(err, dict):
                    self._errors[req_id] = CoreError(
                        str(err.get("message", "request failed")),
                        str(err.get("code", "")),
                    )
                else:
                    self._errors[req_id] = CoreError(str(err))
            else:
                self._results[req_id] = frame.get("result")
        if done is not None:
            done.set()

    def _fail_all(self, message: str) -> None:
        with self._lock:
            pending = list(self._pending.items())
            self._pending.clear()
            for req_id, _ in pending:
                self._errors[req_id] = CoreError(message, "dead")
        for _, done in pending:
            done.set()

    def _read_stderr(self) -> None:
        proc = self.proc
        if proc is None or proc.stderr is None:
            return
        try:
            for line in proc.stderr:
                self._log(line.rstrip())
        except (ValueError, OSError):
            pass

    def _log(self, message: str) -> None:
        self._log_tail.append(message)
        if self._on_log is not None:
            self._on_log(message)


def core_argv() -> list[str]:
    """The command that starts the core.

    The same `-u` the window uses. Its absence is invisible until you watch a
    reply arrive several seconds late, because stdout becomes block-buffered
    once it is a pipe -- which it always is here -- and every streaming frame
    sits in a buffer waiting for either 8KB or an exit.
    """
    return [sys.executable, "-u", "-m", "tonyagent.headless.server"]
