"""Background jobs: commands that outlive the call that started them.

A tool call is synchronous from the model's point of view -- it asks, and the
answer comes back with the result. That is exactly the wrong shape for a
development server, a watch loop or a long build, because the interesting thing
about them is that they *keep going*: a turn that waits for one either times out
or spends its whole length doing nothing else. So they become jobs -- started,
polled and stopped by separate calls, with the process owned here rather than by
whichever tool call happened to launch it.

**Threads and `Popen`, not `asyncio` subprocesses, and that is the load-bearing
decision.** An `asyncio.subprocess.Process` belongs to the event loop that created
it. When that loop closes -- at the end of a turn, a request, or a test -- its
pipes go with it, and the job can no longer be read even though its process is
still running. A job is *defined* by outliving the thing that started it, so it
must not be tied to the lifetime of a loop. A `Popen` and two reader threads have
no such owner, which is also what lets `job_output` be a plain read of a buffer
instead of a scheduling problem.

**What this deliberately does not do.** Jobs run through the user's own shell, so
they are available exactly where host execution is: the Full rung, or
`tools.fallback_to_local`. They are refused inside the sandbox, and that is not an
omission. The container is driven by a one-shot request/response RPC
(``exec_command``) which runs a command and answers with its output; there is no
handle to poll afterwards and no way to ask about a process from an earlier
request. Faking it by detaching inside the container would mean a second job
mechanism -- its own PIDs, log files and liveness checks, over a shell that may be
restarted underneath it -- and two implementations of one idea is the thing this
codebase already refuses to do elsewhere. ``BACKGROUND_NEEDS_HOST`` in
``shell_tools`` says so to the user, and names what would change the answer.
"""

from __future__ import annotations

import atexit
import os
import signal
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from loguru import logger

#: Most text kept per stream, in characters.
#:
#: A job that logs for an hour must not be able to exhaust memory, and it must not
#: be able to do it *quietly* either: text dropped from the front is counted, and
#: ``job_output`` reports the loss rather than presenting the gap as continuous
#: output. 256 KiB is far more than a turn's worth of reading and small enough
#: that a hundred jobs cost nothing.
MAX_BUFFER_CHARS = 256 * 1024

#: How long a kill waits for the process tree to go before escalating.
KILL_GRACE_SECONDS = 5.0


#: How many *finished* jobs are kept before the oldest are forgotten.
#:
#: Each finished job still holds its output buffers, so an unbounded history is an
#: unbounded amount of memory for jobs nobody will read again -- and a session that
#: starts a job per build would notice. Running jobs are never pruned. Forgetting an
#: id is not silent: the refusal for an unknown id lists the ones that do exist, so
#: a pruned job reads as "that one is gone", which is true.
MAX_FINISHED_JOBS = 50


class JobStatus(str, Enum):
    """Where a job has got to. ``KILLED`` is recorded, not inferred.

    A killed process reports a non-zero return code, and so does a command that
    crashed. They are different events with different next steps -- one means
    "the user stopped it", the other means "it failed" -- and the return code
    alone cannot tell them apart, so the kill is remembered.
    """

    RUNNING = "running"
    EXITED = "exited"
    KILLED = "killed"


class _Stream:
    """One stream's text, a reader cursor, and a bounded tail.

    The cursor rather than "the last N lines" because ``job_output`` is polled
    from a turn loop: re-sending everything each poll would put the same log into
    the conversation over and over, and the cost of that is paid in the transcript
    on every turn.
    """

    def __init__(self, limit: int | None = None) -> None:
        # Read at construction rather than bound as a default argument, so a test
        # can patch `MAX_BUFFER_CHARS` and actually change what happens -- a
        # default of `MAX_BUFFER_CHARS` would freeze the value at import time.
        self._limit = MAX_BUFFER_CHARS if limit is None else limit
        self._text = ""
        self._cursor = 0
        self._dropped = 0
        self.total = 0

    def append(self, text: str) -> None:
        self._text += text
        self.total += len(text)
        overflow = len(self._text) - self._limit
        if overflow > 0:
            self._text = self._text[overflow:]
            self._dropped += overflow
            # The cursor is a position *in this buffer*, so dropping from the
            # front has to move it too -- otherwise the next read starts in the
            # middle of a line, or reads nothing at all.
            self._cursor = max(0, self._cursor - overflow)

    def read(self) -> tuple[str, int]:
        """Text written since the last read, and how much was lost before it."""
        fresh = self._text[self._cursor:]
        self._cursor = len(self._text)
        dropped, self._dropped = self._dropped, 0
        return fresh, dropped


@dataclass
class Job:
    """One background command."""

    id: str
    command: str
    cwd: Path
    started_at: float
    process: subprocess.Popen
    stdout: _Stream = field(default_factory=_Stream)
    stderr: _Stream = field(default_factory=_Stream)
    killed: bool = False
    _readers: list[threading.Thread] = field(default_factory=list, repr=False)

    @property
    def pid(self) -> int:
        return self.process.pid

    @property
    def elapsed(self) -> float:
        return time.time() - self.started_at

    @property
    def returncode(self) -> int | None:
        return self.process.poll()

    @property
    def running(self) -> bool:
        return self.process.poll() is None

    @property
    def status(self) -> JobStatus:
        if self.killed:
            return JobStatus.KILLED
        return JobStatus.RUNNING if self.running else JobStatus.EXITED

    def drain(self, timeout: float = 1.0) -> None:
        """Let the reader threads catch up, so the last bytes are readable.

        Called before a finished job is reported. ``poll()`` returning is a fact
        about the *process*; the pipes can still be holding output nobody has read
        yet, and a caller told "finished" and then shown half the output would
        reasonably conclude the rest never happened.
        """
        for reader in self._readers:
            reader.join(timeout=timeout)

    def read(self) -> tuple[str, str, int, int]:
        """``(stdout, stderr, stdout_dropped, stderr_dropped)`` since the last read."""
        out, out_dropped = self.stdout.read()
        err, err_dropped = self.stderr.read()
        return out, err, out_dropped, err_dropped


def _pump(source, target: _Stream, job_id: str) -> None:
    """Copy a pipe into a stream until it closes.

    ``read1`` rather than ``read``: ``read(n)`` blocks until it has n bytes or
    reaches EOF, so a command that prints one line and then waits would show
    nothing at all -- which is the exact case a background job exists for, and it
    would look like the job had produced no output rather than like a bug.
    """
    try:
        while True:
            chunk = source.read1(4096)
            if not chunk:
                break
            target.append(chunk.decode("utf-8", errors="replace"))
    except (ValueError, OSError):
        # The pipe went away underneath the reader, which is what a killed
        # process does to its own stdout. Not worth reporting: the job's status
        # is the thing the caller needs, and it is recorded separately.
        pass
    except Exception as exc:  # noqa: BLE001 - a reader thread must not die loudly
        logger.warning(f"Reader for job {job_id} stopped: {exc}")


def _popen(command: str, cwd: Path) -> subprocess.Popen:
    """Start the command in a session of its own, with no console input.

    ``start_new_session`` / ``CREATE_NEW_PROCESS_GROUP`` is what makes the kill
    path work at all. Without a group of its own, signalling the job would signal
    the shell that started it too, and because ``shell=True`` makes the real
    program a *child* of that shell, terminating the process we hold would leave
    the server running with its port still bound -- a "stopped" job that is not.

    ``stdin`` is closed rather than inherited. A background command that decides
    to prompt would otherwise sit there forever holding a pipe nobody will ever
    write to, and the job would look hung rather than like it was waiting for an
    answer that cannot come.
    """
    kwargs: dict = {}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    return subprocess.Popen(  # noqa: S602 - the command is gated by the caller
        command,
        shell=True,
        cwd=str(cwd),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        **kwargs,
    )


def _kill_tree(process: subprocess.Popen) -> None:
    """Stop the process and everything it started.

    See ``_popen`` for why the tree and not just the process. Each platform has a
    way to take the whole group; both are used, and the escalation to ``kill``
    covers the process that ignores a polite request.
    """
    if process.poll() is not None:
        return
    if os.name == "nt":
        # DEVNULL rather than capture: this needs no output, and a pipe here
        # would be one more thing to drain before the kill can return.
        subprocess.run(  # noqa: S603 - a fixed argv, no shell
            ["taskkill", "/F", "/T", "/PID", str(process.pid)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    else:
        try:
            os.killpg(os.getpgid(process.pid), signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            # Already gone, or not ours to signal. Falling back to the single
            # process is still better than leaving it running.
            process.terminate()
    try:
        process.wait(timeout=KILL_GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        process.kill()
        try:
            process.wait(timeout=KILL_GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            # Reported as killed regardless: the caller asked for it to stop and
            # there is nothing further this process can do about it.
            logger.warning(f"Job process {process.pid} did not stop after kill")


class JobRegistry:
    """Every background job in this process, keyed by the id the model is given."""

    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def start(self, command: str, cwd: Path) -> Job:
        """Start a job and begin reading it. Raises if the process will not start."""
        with self._lock:
            job_id = self._allocate_id()
            process = _popen(command, cwd)
            job = Job(
                id=job_id,
                command=command,
                cwd=cwd,
                started_at=time.time(),
                process=process,
            )
            for source, target, stream_name in (
                (process.stdout, job.stdout, "stdout"),
                (process.stderr, job.stderr, "stderr"),
            ):
                if source is None:  # pragma: no cover - both are PIPEs by construction
                    continue
                reader = threading.Thread(
                    target=_pump,
                    args=(source, target, job_id),
                    name=f"job-{job_id}-{stream_name}",
                    daemon=True,
                )
                reader.start()
                job._readers.append(reader)
            self._jobs[job_id] = job
            self._prune()
            logger.info(f"Started job {job_id} (pid {process.pid}): {command}")
            return job

    def _prune(self) -> None:
        """Forget the oldest finished jobs once there are too many. Caller holds the lock."""
        finished = [job for job in self._jobs.values() if not job.running]
        excess = len(finished) - MAX_FINISHED_JOBS
        if excess <= 0:
            return
        for job in sorted(finished, key=lambda item: item.started_at)[:excess]:
            self._jobs.pop(job.id, None)

    def _allocate_id(self) -> str:
        """A short id, checked against the live set.

        Eight hex characters because it is typed by a model and shown to a user,
        and checked anyway because "unlikely" is not "impossible" when the whole
        point of the id is that it names one particular job.
        """
        for _ in range(100):
            candidate = uuid.uuid4().hex[:8]
            if candidate not in self._jobs:
                return candidate
        raise RuntimeError("Could not allocate a job id")

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get((job_id or "").strip())

    def all(self) -> list[Job]:
        """Every job, oldest first, with the history bounded.

        Pruned here as well as at `start`, and that is not belt-and-braces: a job
        that is still running when the next one starts is not yet countable as
        finished, so pruning only at `start` lets the history settle one above the
        cap. Pruning on read makes the list that is *seen* the bounded one, which
        is the property anyone can check.
        """
        with self._lock:
            self._prune()
            return sorted(self._jobs.values(), key=lambda job: job.started_at)

    def kill(self, job_id: str) -> Job | None:
        job = self.get(job_id)
        if job is None:
            return None
        # Only a running job is *killed*. Marking a job that already exited on
        # its own would relabel a crash or a success as "the user stopped it",
        # and the two have different next steps.
        if job.running:
            job.killed = True
            _kill_tree(job.process)
        job.drain()
        return job

    def shutdown(self) -> None:
        """Stop everything and forget it.

        Registered with ``atexit`` below. The core runs as a child process, so
        without this an exit leaves every job it started still running with
        nothing left that knows about them -- orphaned servers holding ports,
        which the user has to find and kill by hand.
        """
        for job in self.all():
            if job.running:
                _kill_tree(job.process)
        with self._lock:
            self._jobs.clear()

    def reset(self) -> None:
        """Stop everything and start from empty. For tests, and for a new session."""
        self.shutdown()


jobs_registry = JobRegistry()

atexit.register(jobs_registry.shutdown)
