"""The three calls that manage background jobs.

These are deliberately thin. Everything that is actually hard -- owning the
process, streaming its output, taking its whole tree down -- lives in ``jobs``,
because none of it is a *tool* concern and two of these three calls would
otherwise each need their own copy of the liveness check.

The one shape decision worth stating: **``output`` is a string, not the
structured ``{stdout, stderr, returncode}`` that ``execute_command`` returns.**
The window renders a tool card's detail from ``result.output`` only when it is a
string -- see ``describeResult`` in ``app/src/events.ts``, which skips anything
that is not text. A job's output is what the reader came for, so it is handed
over in the shape that actually reaches them.
"""

from __future__ import annotations

import asyncio
import time

from tonyagent.config.settings import settings
from tonyagent.tools.base import (
    Tool,
    ToolCategory,
    ToolResult,
    ToolResultStatus,
    register_tool,
)
from tonyagent.tools.jobs import Job, JobStatus, jobs_registry


def _command_line(command: str, limit: int = 80) -> str:
    """A command on one bounded line, for a listing or a card."""
    collapsed = " ".join(command.split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: limit - 1] + "\u2026"


def _state(job: Job) -> str:
    if job.status is JobStatus.RUNNING:
        return "running"
    if job.status is JobStatus.KILLED:
        return "killed"
    return f"exited({job.returncode})"


def _unknown(job_id: str) -> str:
    """The refusal for an id that names nothing, naming what would work.

    The known ids are listed because the alternative is a model retrying the id
    it just made up: an id is opaque, and "no such job" without the real ones is
    a dead end rather than a correction.
    """
    known = ", ".join(job.id for job in jobs_registry.all()) or "none"
    return f"No background job with id '{job_id}'. Known jobs: {known}."


def _render(job: Job, stdout: str, stderr: str, out_dropped: int, err_dropped: int) -> str:
    """What ``job_output`` returns: the status first, then the new text."""
    lines = [f"{job.id}: {_state(job)} after {job.elapsed:.1f}s"]
    if out_dropped or err_dropped:
        lines.append(
            f"[dropped {out_dropped} chars of stdout and {err_dropped} of stderr; "
            "the buffer keeps the most recent output]"
        )
    if stdout:
        lines.append("--- stdout ---")
        lines.append(stdout.rstrip("\n"))
    if stderr:
        lines.append("--- stderr ---")
        lines.append(stderr.rstrip("\n"))
    if not stdout and not stderr:
        lines.append("(no new output)")
    body = "\n".join(lines)

    max_size = settings.tools.max_output_size
    if len(body) > max_size:
        body = body[:max_size] + "\n... (truncated)"
    return body


@register_tool
class JobListTool(Tool):
    """List the background jobs this session has started.

    Read-only, and so available in every mode: knowing what is running changes
    nothing, and a job outlives the mode that started it.
    """

    name = "job_list"
    description = (
        "List background jobs started with execute_command(background=true), "
        "with their ids, status and how long they have been running."
    )
    category = ToolCategory.SHELL
    parameters = {"type": "object", "properties": {}, "additionalProperties": False}
    destructive = False
    requires_confirmation = False
    # Reads process state, not the workspace, so it needs no project folder --
    # the same reasoning as the network tools.
    folder_required = False

    async def execute(self) -> ToolResult:
        jobs = jobs_registry.all()
        if not jobs:
            return ToolResult(
                status=ToolResultStatus.SUCCESS,
                output=(
                    "No background jobs. Start one with "
                    "execute_command(command=..., background=true)."
                ),
            )
        # A finished job's reader threads may still be draining the tail of its
        # output, and the listing reports the exit code -- so let them finish
        # first, or the status and the output could disagree for a moment.
        for job in jobs:
            if not job.running:
                job.drain(timeout=0.5)
        lines = [
            f"{job.id}  {_state(job):>13}  {job.elapsed:8.1f}s  {_command_line(job.command)}"
            for job in jobs
        ]
        running = sum(1 for job in jobs if job.running)
        header = f"{len(jobs)} job(s), {running} running:"
        return ToolResult(
            status=ToolResultStatus.SUCCESS,
            output="\n".join([header, *lines]),
        )


@register_tool
class JobOutputTool(Tool):
    """Read what a background job has produced since the last read.

    **Since the last read**, which is what makes polling affordable: a job is
    checked from a turn loop, and re-sending the whole log each time would put the
    same text into the conversation over and over, paid for on every turn.

    ``wait`` is the other half. Without it a model watching a build has to spend
    a turn asking "done yet?" and get "no" back; with it the call returns when the
    job finishes or the timeout expires, whichever is first. The wait is
    cooperative -- it sleeps on the event loop rather than joining the reader
    threads -- because blocking here would freeze the window, including the Stop
    button that is the way out of a wait that should not have been started.

    The result is a *success* even when the command failed, and says the exit code
    in its text. Reading a job's output worked; reporting that as a failed tool
    call would mark the card red for something the card is also showing, and the
    model would be told the tool broke when the command did.
    """

    name = "job_output"
    description = (
        "Read the new output of a background job since the last read. Set wait "
        "to true to block until the job finishes or the timeout expires."
    )
    category = ToolCategory.SHELL
    parameters = {
        "type": "object",
        "properties": {
            "job_id": {
                "type": "string",
                "description": "Job id, from job_list or the start result",
            },
            "wait": {
                "type": "boolean",
                "description": "Wait for the job to finish before answering",
                "default": False,
            },
            "timeout_ms": {
                "type": "integer",
                "description": "Longest to wait, in milliseconds",
                "default": 30000,
            },
        },
        "required": ["job_id"],
        "additionalProperties": False,
    }
    destructive = False
    requires_confirmation = False
    folder_required = False

    #: How often a waiting call checks whether the job has finished.
    #:
    #: Short enough that a finished job is noticed promptly and long enough that a
    #: two-minute wait costs two thousand wake-ups rather than two hundred
    #: thousand. It is a poll rather than an event because the job is a thread
    #: with a process in it, not something with a future to await.
    POLL_SECONDS = 0.05

    async def execute(self, job_id: str, wait: bool = False,
                      timeout_ms: int = 30000) -> ToolResult:
        job = jobs_registry.get(job_id)
        if job is None:
            return ToolResult(status=ToolResultStatus.ERROR, error=_unknown(job_id))

        if wait and job.running:
            deadline = time.monotonic() + max(0, timeout_ms) / 1000
            while job.running and time.monotonic() < deadline:
                await asyncio.sleep(self.POLL_SECONDS)

        if not job.running:
            # The process is gone; let its readers finish putting the last bytes
            # in the buffer before reading it, or the final line of a command's
            # output is reported as never having been written.
            job.drain(timeout=1.0)

        stdout, stderr, out_dropped, err_dropped = job.read()
        return ToolResult(
            status=ToolResultStatus.SUCCESS,
            output=_render(job, stdout, stderr, out_dropped, err_dropped),
        )


@register_tool
class JobKillTool(Tool):
    """Stop a background job and everything it started.

    **Not confirmation-gated, on purpose.** The process is one this agent started
    through ``execute_command``, which has already passed the command denylist,
    the allow-list, the isolation check and the user's confirmation. Asking again
    before letting the user stop their own runaway server would make the stop
    button the slowest part of the feature, and the thing being stopped is the
    agent's own child rather than the user's data.
    """

    name = "job_kill"
    description = "Stop a background job and the processes it started."
    category = ToolCategory.SHELL
    parameters = {
        "type": "object",
        "properties": {
            "job_id": {"type": "string", "description": "Job id, from job_list"},
        },
        "required": ["job_id"],
        "additionalProperties": False,
    }
    destructive = False
    requires_confirmation = False
    folder_required = False

    async def execute(self, job_id: str) -> ToolResult:
        job = jobs_registry.get(job_id)
        if job is None:
            return ToolResult(status=ToolResultStatus.ERROR, error=_unknown(job_id))

        if not job.running:
            # Said as a success rather than an error: the caller wanted it
            # stopped and it is stopped. A failure here would invite a retry that
            # cannot do anything.
            return ToolResult(
                status=ToolResultStatus.SUCCESS,
                output=f"{job.id} had already {_state(job)}; nothing to stop.",
            )

        elapsed = job.elapsed
        jobs_registry.kill(job_id)
        return ToolResult(
            status=ToolResultStatus.SUCCESS,
            output=(
                f"Stopped {job.id} after {elapsed:.1f}s "
                f"({_command_line(job.command)})."
            ),
        )
