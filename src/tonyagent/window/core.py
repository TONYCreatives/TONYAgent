"""The headless core as a child process, and the pump that frames it for the page.

The core is the same program the Tauri build ran as a sidecar, and the wire
format is unchanged: newline-delimited JSON, one message per line, in both
directions -- ``tonyagent.headless.server`` is the contract and this file does
not restate it.

What changed is who owns the process. Tauri's shell plugin spawned it from the
frontend and tied its lifetime to the window that used it; here the window host
spawns it before the window exists and reaps it when the window closes. That is
the same guarantee -- a core cannot outlive its window -- with one fewer moving
part, and it is why the frontend no longer needs a spawn API at all.

Three threads, and they do not do each other's jobs:

* the **stdout reader** owns the child's stdout. It splits it into lines and
  queues them, and it does nothing else. It must never block on the page: the
  child writes into a pipe, and a reader that stops reading applies backpressure
  to the core's own stdout, which is a deadlock waiting for a slow webview.
* the **stderr reader** is the same thing for the human-readable channel. The
  log strip reads it and nothing depends on it.
* the **pump** owns the queue and hands it to the page.

Batching is the whole reason the pump is a thread rather than a callback.
``evaluate_js`` marshals onto the GUI thread and waits for the page to answer,
so one call per token would put a full round trip on the critical path of every
delta -- and a model that talks faster than the webview paints would slow the
model down. A 20ms tick caps delivery at fifty calls a second whatever the token
rate is, and 20ms is well under the threshold where a stream stops looking live.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
from collections.abc import Callable, Sequence

from loguru import logger

#: How long the pump sleeps when the queue is empty. Also the stop-check
#: interval, so it bounds how long ``stop()`` waits on the pump.
TICK_SECONDS = 0.02

#: Most lines one batch may carry. Only a backstop: the pump takes everything
#: that is queued, and a batch this size means the page is already far behind.
MAX_BATCH = 1024

#: Suppress the child's console window. Without it a GUI launch flashes a black
#: rectangle for the core's lifetime, because a console-subsystem child of a
#: windowed parent still gets a console unless it is asked not to.
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class CoreProcess:
    """The core, as a child process, with its output framed for the page.

    Not a context manager and not restartable. The host builds one per window
    and throws it away with the window, which is the lifetime the Tauri build
    had too -- a core that outlives its window still holds the sandbox and the
    API key, and there is nobody left to show its errors to.
    """

    def __init__(
        self,
        argv: Sequence[str],
        on_frames: Callable[[list[str]], None],
        *,
        on_stderr: Callable[[str], None] | None = None,
        on_exit: Callable[[], None] | None = None,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
    ) -> None:
        self._argv = list(argv)
        self._on_frames = on_frames
        self._on_stderr = on_stderr
        self._on_exit = on_exit
        self._cwd = cwd
        self._env = env

        self._proc: subprocess.Popen[str] | None = None
        self._queue: list[str] = []
        self._lock = threading.Lock()
        self._write_lock = threading.Lock()
        self._stop = threading.Event()
        self._exited = threading.Event()
        self._threads: list[threading.Thread] = []

    # -- lifecycle -----------------------------------------------------------

    def start(self) -> None:
        """Spawn the core and its three threads.

        ``bufsize=1`` with ``text=True`` is line buffering, which is what makes
        a request leave this process the moment it is written rather than when
        four kilobytes have accumulated. A prompt that sits in a buffer until
        the next prompt arrives is the classic version of this bug.
        """
        if self._proc is not None:
            return
        self._proc = subprocess.Popen(  # noqa: S603 - argv is built here, not by a user
            self._argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=self._cwd,
            env=self._env,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            creationflags=_NO_WINDOW,
        )
        self._spawn(self._read_stdout, "tonyagent-core-stdout")
        self._spawn(self._read_stderr, "tonyagent-core-stderr")
        self._spawn(self._pump, "tonyagent-core-pump")

    def write(self, line: str) -> None:
        """Send one request frame.

        The frame already carries its own newline -- the frontend appends it, as
        it did to the sidecar -- and one is added here only if it is missing. A
        frame without a terminator is a frame the core reads forever.
        """
        proc = self._proc
        if proc is None or proc.stdin is None:
            raise RuntimeError("the core is not running")
        if not line.endswith("\n"):
            line = f"{line}\n"
        with self._write_lock:
            try:
                proc.stdin.write(line)
                proc.stdin.flush()
            except (OSError, ValueError) as exc:
                # A closed pipe is the core having died, not a bug in the
                # caller. Raised as a plain failure so the frontend's reply
                # routing can reject the request that caused it.
                raise RuntimeError("the core has stopped") from exc

    def stop(self) -> None:
        """Close the child's stdin, then the child, then the threads.

        stdin first, because that is what a well-behaved core waits on: it sees
        EOF, finishes the line it is on and exits on its own. ``terminate`` is
        the answer to a core that does not, and ``kill`` to one that will not.
        """
        self._stop.set()
        proc = self._proc
        self._proc = None
        if proc is not None:
            try:
                if proc.stdin is not None:
                    proc.stdin.close()
            except OSError:
                pass
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                logger.warning("The core ignored terminate; killing it.")
                proc.kill()
        for thread in self._threads:
            thread.join(timeout=1)
        self._threads.clear()

    @property
    def alive(self) -> bool:
        """Whether the core is still running. The status bar's own question."""
        return self._proc is not None and not self._exited.is_set()

    # -- the threads ---------------------------------------------------------

    def _spawn(self, target: Callable[[], None], name: str) -> None:
        thread = threading.Thread(target=target, name=name, daemon=True)
        thread.start()
        self._threads.append(thread)

    def _read_stdout(self) -> None:
        stream = self._proc.stdout if self._proc else None
        if stream is None:
            return
        for raw in stream:
            if self._stop.is_set():
                break
            line = raw.rstrip("\r\n")
            # Blank lines are dropped rather than forwarded. The core never
            # writes one, and the frontend's buffer would hand an empty string
            # to JSON.parse, which is a parse error that takes the stream down.
            if line:
                with self._lock:
                    self._queue.append(line)
        self._finish()

    def _read_stderr(self) -> None:
        stream = self._proc.stderr if self._proc else None
        if stream is None:
            return
        for raw in stream:
            if self._stop.is_set():
                break
            line = raw.rstrip("\r\n")
            if line and self._on_stderr is not None:
                self._on_stderr(line)

    def _pump(self) -> None:
        while not self._stop.is_set():
            batch = self._drain()
            if not batch:
                self._stop.wait(TICK_SECONDS)
                continue
            try:
                self._on_frames(batch)
            except Exception as exc:  # noqa: BLE001 - a closing window is not fatal
                # The realistic cause is the window going away mid-batch, and
                # the handler for that is already running. Sleeping keeps a
                # permanently broken delivery path from spinning a core here.
                logger.debug(f"The window refused {len(batch)} frame(s): {exc}")
                self._stop.wait(TICK_SECONDS)

    def _drain(self) -> list[str]:
        with self._lock:
            if not self._queue:
                return []
            batch = self._queue[:MAX_BATCH]
            del self._queue[:MAX_BATCH]
            return batch

    def _finish(self) -> None:
        """The core's stdout closed: it is gone, whoever ended it.

        Fired once, on the reader thread, and never for a stop this class
        started -- a teardown that reported an exit would have the frontend show
        "the backend exited" over a window that is closing on purpose.
        """
        if self._stop.is_set() or self._exited.is_set():
            return
        self._exited.set()
        logger.info("The core exited.")
        if self._on_exit is not None:
            self._on_exit()


def default_argv() -> list[str]:
    """How to start the core from source.

    ``-u`` because a buffered stdout is a stdout that arrives in four-kilobyte
    clumps, which turns a token stream into a stutter; the child is a pipe, so
    Python would otherwise block-buffer it regardless of what this process does.

    ``-m tonyagent.headless.server`` rather than an import, because the core is
    an asyncio program that owns its own stdin and stdout, and there is no
    reason to run two event loops in one process to save a fork.
    """
    return [sys.executable, "-u", "-m", "tonyagent.headless.server"]


def source_env() -> dict[str, str]:
    """The environment a from-source core needs to find its own package.

    Set here rather than assumed to be inherited: the host is launched by a
    double-clicked ``.bat``, whose working directory and ``PYTHONPATH`` are
    whatever that shell had, and a core that cannot import itself dies with a
    traceback on a stderr nobody is reading.
    """
    env = dict(os.environ)
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    src = os.path.join(root, "src")
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{src}{os.pathsep}{existing}" if existing else src
    return env
