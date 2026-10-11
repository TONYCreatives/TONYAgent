"""Shell command tools for TONYAgent."""

from __future__ import annotations

import asyncio
import re
import shlex
from pathlib import Path
from typing import Any, NamedTuple

from tonyagent.sandbox import get_shared_sandbox_manager
from tonyagent.sandbox.base import SandboxStatus
from tonyagent.tools.base import (
    Tool,
    ToolResult,
    ToolResultStatus,
    ToolCategory,
    output_excerpt,
    register_tool,
)
from tonyagent.tools.jobs import jobs_registry
from tonyagent.folder.manager import folder_manager
from tonyagent.config.settings import settings
from loguru import logger


def _resolve_path(path: str) -> Path:
    project_root = folder_manager.current_folder
    if not project_root:
        raise ValueError("No project folder selected")
    
    target = (project_root / path).resolve()
    try:
        target.relative_to(project_root.resolve())
    except ValueError:
        raise ValueError(f"Path '{path}' attempts to escape project folder")
    return target


#: Whether the user has chosen a level that runs commands off the allow-list.
#:
#: **A module flag rather than a parameter threaded through, deliberately.**
#: The first attempt read the level off `tool_orchestrator`, the module-level
#: singleton -- and a test that constructs its own `ToolOrchestrator` then got
#: two different answers from two authorities: the orchestrator's confirmation
#: logic saw `full` and skipped asking, while `ExecuteCommandTool` saw the
#: singleton's default and refused the command anyway. Two readers of "what may
#: this session run" is the bug, not the fix.
#:
#: The permission level is session state, so one process-wide flag set by the
#: single place that owns the level is the honest shape. Written only by
#: `ToolOrchestrator.set_permission`.
_ALLOWLIST_BYPASS = False


def set_allowlist_bypass(bypassed: bool) -> None:
    """Record whether commands off the allow-list may run. See `_ALLOWLIST_BYPASS`."""
    global _ALLOWLIST_BYPASS
    _ALLOWLIST_BYPASS = bool(bypassed)


def allowlist_bypassed() -> bool:
    return _ALLOWLIST_BYPASS


#: Whether the chosen permission level runs commands on the host.
#:
#: A second instance of the argument `_ALLOWLIST_BYPASS` makes, and for the same
#: reason. `ExecuteCommandTool` is the only thing that can decide whether a
#: command may run on the host, and it is not the thing that holds the
#: permission level -- so the level is published to it, once, by the one place
#: that owns the level. Reading it off the orchestrator singleton instead is
#: what produced two authorities disagreeing about the same session once
#: already.
#:
#: **What this flag does and does not authorise.** It is set by exactly one
#: permission rung (`full`), it is the reason `ExecuteCommandTool`'s isolation
#: gate can be passed without a container, and it is *not* a general escape
#: hatch: `tools.fallback_to_local` remains a separate, independent opt-in, and
#: a session at High with this False is refused exactly as before.
#:
#: Written only by `ToolOrchestrator.set_permission`.
_HOST_EXECUTION = False


def set_host_execution(enabled: bool) -> None:
    """Record whether commands may run on the host. See `_HOST_EXECUTION`."""
    global _HOST_EXECUTION
    _HOST_EXECUTION = bool(enabled)


def host_execution() -> bool:
    return _HOST_EXECUTION


#: Leading words that only wrap another command. Stripped before the denylist
#: looks at anything, so `cmd /c format C:` and `powershell -Command rm -rf /`
#: are judged on what they run rather than on how they were spelled.
#:
#: Two things are deliberately *not* here:
#:
#: * The flag requirement lives inside each branch, not after the alternation.
#:   Written as `powershell|pwsh\s+-command`, the first branch matches bare
#:   `powershell`, and every PowerShell command had its first word deleted
#:   before the denylist ran.
#: * `-enc` / `-encodedcommand` / `-ec` are **not** unwrapped. They look like a
#:   wrapper but the payload is base64, so unwrapping one leaves an opaque blob
#:   no pattern can read -- and it silently defeats the pattern that exists to
#:   block it. An obfuscating flag is refused on sight, not looked inside.
_DENYLIST_WRAPPERS = (
    r"(?:cmd(?:\.exe)?\s+/[ck]\s+)",
    r"(?:powershell|pwsh)(?:\.exe)?\s+-+(?:command|c)\s+",
)


def normalize_for_denylist(command: str) -> str:
    """Reduce a command to the text the destructive-command patterns match on.

    **What this is for.** The denylist is matched with `re.search`, so anything
    that changes the spelling changes the answer. Three things are undone first:

    * quotes are removed, so a quoted path reads the same as a bare one;
    * runs of whitespace collapse to one space;
    * `cmd /c` and `powershell -Command` wrappers are stripped, repeatedly, so
      the command that actually runs is what gets judged.

    **What this does not do, stated plainly.** It is a normalisation, not a
    parser, and it is not a security boundary by itself. The built-in patterns
    are now written broadly enough (`[^|;&]*` between the verb and its flags)
    that most of the disguises they used to miss are caught without it -- the
    normaliser is not what makes those tests pass. It earns its place for the
    patterns *other people write*: `command_denylist` is a setting, and a
    careful pattern added to `config.toml` would silently stop matching the day
    someone quoted a path, with nothing to say so.

    The real boundary is the sandbox. See `ExecuteCommandTool`'s isolation gate:
    an allow-listed interpreter can delete a tree from inside a container the
    agent cannot see out of, which no denylist over command strings will ever
    prevent. This is the cheap inner ring, not the wall.
    """
    text = command.lower().replace("'", "").replace('"', "")
    text = re.sub(r"\s+", " ", text)
    # Stripped repeatedly: `cmd /c powershell -Command rm -rf /` is two deep,
    # and a single pass would leave the inner wrapper in place for the patterns
    # to miss.
    for _ in range(4):
        before = text
        for wrapper in _DENYLIST_WRAPPERS:
            text = re.sub(r"^\s*" + wrapper, "", text)
        if text == before:
            break
    return text.strip()


def _is_command_allowed(command: str, bypass_allowlist: bool = False) -> tuple[bool, str]:
    """Check if command is allowed by allowlist/denylist.

    ``bypass_allowlist`` is the user having chosen the `Full` permission level:
    commands outside the allow-list run then. **The denylist is checked first
    and is not bypassed**, because it is not a list of commands we happen not to
    trust -- it is the handful that destroy the machine (`rm -rf /`,
    `format C:`, `shutdown`, `reboot`). Widening what may run does not have to
    mean widening what may never run, and the two are separate decisions.

    At Full this list is the *only* thing between the agent and the machine, so
    it is matched against `normalize_for_denylist` rather than the raw string --
    see that function for the disguises that motivated it.
    """
    parts = shlex.split(command)
    if not parts:
        return False, "Empty command"

    base_cmd = Path(parts[0]).name.lower()

    # Check denylist first, unconditionally.
    normalized = normalize_for_denylist(command)
    for deny_pattern in settings.tools.command_denylist:
        if re.search(deny_pattern, normalized):
            return False, f"Command matches denylist pattern: {deny_pattern}"

    if bypass_allowlist:
        logger.warning(
            f"Running a command outside the allow-list because Full is selected: {command}"
        )
        return True, "OK"

    # Check allowlist
    allowed = False
    for allow_pattern in settings.tools.command_allowlist:
        if base_cmd == allow_pattern.lower() or base_cmd.startswith(allow_pattern.lower()):
            allowed = True
            break

    if not allowed:
        return False, f"Command '{base_cmd}' not in allowlist"

    return True, "OK"


def _resolve_sandbox_cwd(cwd: str) -> str:
    """Map a host-relative cwd to its /workspace path inside the container."""
    project_root = folder_manager.current_folder
    if not project_root:
        raise ValueError("No project folder selected")
    target = (project_root / cwd).resolve()
    try:
        rel = target.relative_to(project_root.resolve()).as_posix()
    except ValueError:
        raise ValueError(f"Path '{cwd}' attempts to escape project folder")
    if rel == ".":
        return "/workspace"
    return f"/workspace/{rel}"


#: Shown when nothing at all can run a command, because no runtime is attached.
#:
#: Worded identically to ``runtime_access.NO_RUNTIME`` on purpose -- ``execute_js``
#: gives the same answer for the same state, and two tools describing one cause
#: differently is the failure ``runtime_access`` was created to end. It cannot be
#: imported from there, because ``runtime_access`` imports this module, so the
#: string is repeated rather than the dependency reversed. A test compares them.
NO_RUNTIME = (
    "The sandbox runtime is not running. Choose a project folder in Settings first."
)

#: Shown when a runtime exists but does not contain what a command would do.
NO_ISOLATION = (
    "No isolated sandbox is running. Running commands on the host is "
    "not a substitute, so this is refused on purpose -- start Docker "
    "and pick the project folder again (or set "
    "tools.fallback_to_local=true to accept host execution)."
)

#: Shown when a background job is asked for where only the sandbox could run it.
#:
#: A job has to outlive the call that started it, and the only thing this process
#: can hold onto afterwards is a *local* child. The container runs one command per
#: request and answers with its output, so once that answer is in there is no
#: handle left to poll. That is a limit of the interface rather than a missing
#: flag, so the refusal says what would change the answer instead of just no.
BACKGROUND_NEEDS_HOST = (
    "This command would run in the sandbox, and the sandbox cannot host a "
    "background job: it runs one command per request and answers with the output, "
    "so there is no process left to poll afterwards. Run it in the foreground, or "
    "select the Full permission level (or set tools.fallback_to_local=true) so it "
    "runs on this computer, where a job can be started, read and stopped."
)


def _brief(command: str, limit: int = 120) -> str:
    """A command on one bounded line, for a message about it."""
    collapsed = " ".join(command.split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: limit - 1] + "\u2026"


def _command_summary(returncode: int, stdout: str, stderr: str) -> str:
    """One line for the tool card: how it exited, and what it said.

    Both halves are the point. The exit code is what tells a reader at a glance
    whether the command worked; the excerpt is what tells them *what* it did. A card
    reading only "exit 0" is the blank card this exists to fix, one step removed.
    """
    excerpt = output_excerpt(stdout) or output_excerpt(stderr)
    said = f"exit {returncode}"
    return f"{said} \u00b7 {excerpt}" if excerpt else f"{said} \u00b7 no output"


class _Target(NamedTuple):
    """Where a command would run, and what to say if it can run nowhere."""

    kind: str  # "host" | "sandbox" | "none"
    why: str = ""  # the reason logged, when kind is "host"
    refusal: str | None = None  # the message to return, when kind is "none"
    backend: Any = None  # the isolating backend, when kind is "sandbox"


def _resolve_target() -> _Target:
    """The one answer to "where does this command run".

    **One answer, asked by both the foreground path and the background one.** A
    job started on the host while the permission level says sandbox is exactly the
    failure the isolation gate exists to prevent, and two copies of this decision
    would eventually drift into it -- which is why it is a function rather than a
    paragraph repeated in two places.

    The order of the checks *is* the order of the gates, and it matters:

    1. **Full** runs on the host without needing a container at all, which is the
       entire reason that rung exists. Checked before the runtime lookup so a
       session at Full does not have to have Docker running.
    2. Nothing attached and no opt-in is refused before the backend is consulted,
       so this tool and ``execute_js`` say the same thing about one cause.
    3. A running backend that provides isolation takes it.
    4. ``tools.fallback_to_local`` is the *setting* accepting host execution -- a
       different decision from the permission rung, and logged as such.
    """
    if host_execution():
        return _Target("host", why="the Full permission level")

    manager = get_shared_sandbox_manager()
    if manager.get_runtime_backend() is None and not settings.tools.fallback_to_local:
        return _Target("none", refusal=NO_RUNTIME)

    backend = manager.get_backend()
    if (
        backend is not None
        and backend.status is SandboxStatus.RUNNING
        # A third-party backend without the flag reads as not isolating, so an
        # older plugin fails closed instead of running on the host.
        and getattr(backend, "provides_isolation", False)
    ):
        return _Target("sandbox", backend=backend)

    if settings.tools.fallback_to_local:
        return _Target("host", why="tools.fallback_to_local")

    return _Target("none", refusal=NO_ISOLATION)


async def _execute_local(command: str, cwd: str, timeout: int, why: str) -> ToolResult:
    """Run a command through the user's own shell, with no container.

    ``why`` is logged rather than swallowed: host execution is the one event in
    this file that leaves no trace anywhere the user can see, because the
    sandbox boundary is exactly what makes the sandboxed path safe to allow.
    Two different reasons reach here -- the Full permission rung, and the
    ``tools.fallback_to_local`` setting -- and they are not the same decision,
    so the log says which one it was.
    """
    logger.warning(f"Executing on HOST (no sandbox, via {why}): {command}")
    target_cwd = _resolve_path(cwd)

    process = await asyncio.create_subprocess_shell(
        command,
        cwd=str(target_cwd),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        limit=settings.tools.max_output_size,
    )

    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        process.kill()
        await process.wait()
        return ToolResult(
            status=ToolResultStatus.ERROR,
            error=f"Command timed out after {timeout}s",
            output={"stdout": "", "stderr": f"Timeout after {timeout}s", "returncode": -1},
            summary=_command_summary(-1, "", f"Timeout after {timeout}s"),
        )

    stdout_str = stdout.decode("utf-8", errors="replace")
    stderr_str = stderr.decode("utf-8", errors="replace")

    max_size = settings.tools.max_output_size
    if len(stdout_str) > max_size:
        stdout_str = stdout_str[:max_size] + "\n... (truncated)"
    if len(stderr_str) > max_size:
        stderr_str = stderr_str[:max_size] + "\n... (truncated)"

    return ToolResult(
        status=ToolResultStatus.SUCCESS if process.returncode == 0 else ToolResultStatus.ERROR,
        output={"stdout": stdout_str, "stderr": stderr_str, "returncode": process.returncode},
        summary=_command_summary(process.returncode, stdout_str, stderr_str),
        error=stderr_str if process.returncode != 0 else None,
    )




@register_tool
class ExecuteCommandTool(Tool):
    """Run a shell command inside the sandbox.

    One of only two tools that execute model-authored code, so one of only two
    that require a *containing* backend. With only the local runtime available
    this refuses, because "run it on the host instead" is not a lesser version
    of the same thing -- it is the thing the sandbox exists to prevent.

    Four gates, in order: the command denylist, the command allow-list, the
    isolation check, then per-session confirmation. A trusted project skips the
    last of those. The first is never skipped by anything -- see
    `_is_command_allowed`.

    With ``background=True`` the command becomes a job rather than a result: it is
    started, and its id comes back so that later calls can read it and stop it.
    That is what makes a dev server or a watch loop usable at all, because the
    alternative is a turn that waits for something designed never to finish. A job
    needs a host to run on, so the sandbox refuses one -- see
    `BACKGROUND_NEEDS_HOST` for why that is the interface and not an oversight.
    """

    name = "execute_command"
    description = (
        "Execute a shell command. Set background=true for something long-running "
        "such as a dev server or a watch loop, which returns a job id instead of "
        "waiting; read it with job_output and stop it with job_kill."
    )
    category = ToolCategory.SHELL
    parameters = {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "Command to execute"},
            "cwd": {"type": "string", "description": "Working directory (relative to project root)", "default": "."},
            "timeout": {"type": "integer", "description": "Timeout in seconds", "default": 30},
            "background": {
                "type": "boolean",
                "description": (
                    "Start it as a background job and return its id immediately, "
                    "instead of waiting for it to finish."
                ),
                "default": False,
            },
        },
        "required": ["command"],
        "additionalProperties": False,
    }
    destructive = True
    requires_confirmation = True
    sandbox_required = True
    # Arbitrary code, so the local runtime is not enough: this one keeps
    # needing a backend that contains it.
    isolation_required = True

    async def execute(self, command: str, cwd: str = ".", timeout: int = 30,
                      background: bool = False) -> ToolResult:
        # Validate command. The level comes from the module flag rather than
        # from an orchestrator instance -- see `_ALLOWLIST_BYPASS` for why there
        # is exactly one of those.
        allowed, reason = _is_command_allowed(
            command, bypass_allowlist=allowlist_bypassed()
        )
        if not allowed:
            return ToolResult(status=ToolResultStatus.ERROR, error=f"Command not allowed: {reason}")

        # Where this runs is decided in one place, and the background path below
        # is given the same answer -- see `_resolve_target` for the order of the
        # gates and why they are in that order.
        target = _resolve_target()
        if target.refusal is not None:
            return ToolResult(status=ToolResultStatus.ERROR, error=target.refusal)

        if background:
            return self._start_background(command, cwd, target)

        if target.kind == "host":
            try:
                return await _execute_local(command, cwd, timeout, why=target.why)
            except Exception as e:
                return ToolResult(status=ToolResultStatus.ERROR, error=f"Host execution failed: {e}")

        try:
            sandbox_cwd = _resolve_sandbox_cwd(cwd)
        except ValueError as e:
            return ToolResult(status=ToolResultStatus.ERROR, error=str(e))
        try:
            result = await target.backend.execute_command(
                command, cwd=sandbox_cwd, timeout=timeout
            )
        except Exception as e:
            return ToolResult(status=ToolResultStatus.ERROR, error=f"Sandbox execution failed: {e}")
        max_size = settings.tools.max_output_size
        stdout_str, stderr_str = result.stdout, result.stderr
        if len(stdout_str) > max_size:
            stdout_str = stdout_str[:max_size] + "\n... (truncated)"
        if len(stderr_str) > max_size:
            stderr_str = stderr_str[:max_size] + "\n... (truncated)"
        return ToolResult(
            status=ToolResultStatus.SUCCESS if result.returncode == 0 else ToolResultStatus.ERROR,
            output={"stdout": stdout_str, "stderr": stderr_str, "returncode": result.returncode},
            summary=_command_summary(result.returncode, stdout_str, stderr_str),
            error=stderr_str if result.returncode != 0 else None,
        )

    def _start_background(self, command: str, cwd: str, target: _Target) -> ToolResult:
        """Start the command as a job, or explain why it could not be one.

        Every gate has already run by the time this is reached -- this decides
        *where* a command runs, not whether it may. Only the host can hold a job;
        see `BACKGROUND_NEEDS_HOST` for why the sandbox cannot.
        """
        if target.kind != "host":
            return ToolResult(status=ToolResultStatus.ERROR, error=BACKGROUND_NEEDS_HOST)
        try:
            target_cwd = _resolve_path(cwd)
        except ValueError as e:
            return ToolResult(status=ToolResultStatus.ERROR, error=str(e))
        try:
            job = jobs_registry.start(command, target_cwd)
        except Exception as e:
            return ToolResult(
                status=ToolResultStatus.ERROR,
                error=f"Could not start the background job: {e}",
            )
        # Logged for the same reason `_execute_local` logs: a process on the host
        # is the one thing this feature does that leaves no other trace.
        logger.warning(
            f"Started background job {job.id} on HOST (pid {job.pid}): {command}"
        )
        return ToolResult(
            status=ToolResultStatus.SUCCESS,
            output=(
                f"Started job {job.id} (pid {job.pid}): {_brief(command)}. "
                "Read it with job_output, list jobs with job_list, stop it with "
                "job_kill."
            ),
        )
