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
from tonyagent.tools.context import current
from tonyagent.tools.jobs import jobs_registry
from tonyagent.tools.workspace import confine, project_root
from tonyagent.config.settings import settings
from loguru import logger


#: The workspace boundary, from its one home -- see
#: `tonyagent.tools.workspace` for why this is one implementation and not four.
_resolve_path = confine


#: The two questions a command tool has to answer before it runs anything.
#:
#: **Why they are asked of the tool context now, and not of two module flags.**
#: These were `_ALLOWLIST_BYPASS` and `_HOST_EXECUTION`, two booleans derived
#: from one permission level and pushed into this module by
#: `ToolOrchestrator.set_permission` the moment the level changed. That fixed an
#: earlier bug -- reading the level off the `tool_orchestrator` singleton meant
#: the orchestrator's confirmation logic and `ExecuteCommandTool` could disagree
#: about the same session -- but it traded one ownership mistake for another:
#: the answer belonged to no call in particular, and a parent and its child (two
#: sessions whose turns now interleave, see `tools/context.py`) shared it.
#:
#: Now the level itself arrives in `ToolContext.permission`, published by the
#: orchestrator around each execution, and these two readers derive their answer
#: from it. One authority, one call at a time. Nothing published (a direct tool
#: call in a test or a script) reads as "no bypass, no host", which is the safe
#: direction.


def allowlist_bypassed() -> bool:
    """Whether this call's level runs commands off the allow-list."""
    return bool(getattr(current().permission, "bypasses_command_allowlist", False))


def host_execution() -> bool:
    """Whether this call's level runs commands on the host.

    **What this authorises and what it does not.** It is true at exactly one
    permission rung (`full`), it is the reason `ExecuteCommandTool`'s isolation
    gate can be passed without a container, and it is *not* a general escape
    hatch: `tools.fallback_to_local` remains a separate, independent opt-in, and
    a session at High is refused exactly as before.
    """
    return bool(getattr(current().permission, "runs_on_host", False))


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


#: Windows' command suffixes, which the shell resolves transparently: the
#: user's PATHEXT turns ``npm.cmd`` into ``npm``. The allow-list is about the
#: *program*, so both spellings are the same match -- and only those two.
_EXECUTABLE_SUFFIXES = (".exe", ".bat", ".cmd", ".com", ".ps1")

#: Ceiling on a model-chosen timeout, in seconds.
#:
#: The timeout is model-authored input like any other argument, and an
#: unbounded one is a turn that never comes back: ``timeout=86400`` holds the
#: call -- and with it a batch, since a prompt-making call is serial -- for a
#: day. 300 aligns with the sandbox container's own ``sandbox.timeout`` so the
#: host and container paths refuse on the same clock, and it is still ten
#: times the 30s default. A call can only be clamped downward.
MAX_TIMEOUT_S = 300


def _allowlist_names(base_cmd: str) -> set[str]:
    """The names this command's first word may match on the allow-list.

    ``python.exe`` on Windows and ``python`` everywhere else are the same
    program -- the shell resolves the extension for you -- so the comparison
    accepts the bare name and the suffixed one, and nothing else. The prefix
    match this replaces (``base_cmd.startswith(pattern)``) admitted
    ``pythonx evil``, ``pipx`` and every other near-miss; a match that is not
    exact is how an allow-list silently becomes a substring check.
    """
    names = {base_cmd}
    for suffix in _EXECUTABLE_SUFFIXES:
        if base_cmd.endswith(suffix):
            names.add(base_cmd[: -len(suffix)])
    return names


def bounded_timeout(timeout: Any) -> int:
    """A model-supplied timeout, clamped to ``[1, MAX_TIMEOUT_S]``.

    A value that is not a number reads as the ceiling rather than the floor:
    a call that asked for a timeout it did not understand still gets one that
    ends. A value below one gets one, for the same reason.
    """
    try:
        wanted = int(timeout)
    except (TypeError, ValueError):
        return MAX_TIMEOUT_S
    return max(1, min(wanted, MAX_TIMEOUT_S))


def effective_command_lists() -> tuple[list[str], list[str]]:
    """The allow and deny lists as they stand *now*, from the config file.

    Read per call rather than captured at import. The settings page writes these
    while the core is running, and a list read once would keep refusing a program
    the user has just allowed until the app restarted -- the same "the file said
    one thing and the tool did another" the file was already guilty of, one
    restart later. The cost is a parse of a file this size, paid against a
    command that is about to be executed somewhere.

    See ``config.migration.load_section`` for why the file rather than
    ``settings``: the model is environment-only, so the copy in the file was
    never read by anything until this release.

    **The deny list is the code's own patterns plus anything the file adds, and
    the file cannot shorten it.** That is not symmetry for its own sake: this is
    the handful of commands that destroy the machine rather than a set we happen
    not to trust, and at Full it is the only thing between the agent and the
    host -- so it is a floor. The settings page shows it rather than editing it.
    The allow list is a genuine choice of the user's, and the file owns it.

    Public because the settings page reports what this returns rather than what
    the file holds: the deny list a turn is held to is the union, and a panel
    that showed the file's half of it would be describing a list nobody is
    using.
    """
    from tonyagent.config.migration import load_section

    section = load_section("tools")
    floor = list(settings.tools.command_denylist)
    added = [pattern for pattern in section.command_denylist if pattern not in floor]
    return list(section.command_allowlist), floor + added


def denylist_reason(command: str, patterns: list[str] | None = None) -> str | None:
    """The denylist pattern this command matches, or ``None`` if none does.

    **Extracted from ``_is_command_allowed`` so the rule has a second
    enforcement point.** ``execute_js`` runs arbitrary code on the host too --
    at the Full rung, where the isolation gate is passed without a container
    -- and giving it its own copy of this loop is how two tools end up
    disagreeing about ``rm -rf /``. One function, both callers.

    ``patterns`` is for the caller that has already read them. Left out, they
    are read here -- see ``effective_command_lists``.
    """
    if patterns is None:
        patterns = effective_command_lists()[1]
    normalized = normalize_for_denylist(command)
    for deny_pattern in patterns:
        if re.search(deny_pattern, normalized):
            return deny_pattern
    return None


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

    # Read once and hand the deny list on: both lists come from the same
    # section, and `denylist_reason` is the one place the deny loop lives.
    allow_patterns, deny_patterns = effective_command_lists()

    # Check denylist first, unconditionally. Shared with `execute_js` -- see
    # `denylist_reason` above for why there is one loop and not two.
    deny_pattern = denylist_reason(command, deny_patterns)
    if deny_pattern:
        return False, f"Command matches denylist pattern: {deny_pattern}"

    if bypass_allowlist:
        logger.warning(
            f"Running a command outside the allow-list because Full is selected: {command}"
        )
        return True, "OK"

    # Check allowlist. Exact match, not a prefix -- see `_allowlist_names` for
    # what the prefix form admitted.
    allowed = False
    candidates = _allowlist_names(base_cmd)
    for allow_pattern in allow_patterns:
        if allow_pattern.lower() in candidates:
            allowed = True
            break

    if not allowed:
        return False, f"Command '{base_cmd}' not in allowlist"

    return True, "OK"


def _resolve_sandbox_cwd(cwd: str) -> str:
    """Map a host-relative cwd to the sandbox's path for the same folder.

    ``/workspace`` is the *contract* spelling every isolating backend
    agrees on, not a location: the Docker backend mounts it, and a backend
    with no such mount (WSL) translates it. The confinement is `confine`'s,
    not a fourth copy of it: the *mapping* is this function's own job, and
    the check on the way in is the boundary's.
    """
    target = confine(cwd)
    rel = target.relative_to(project_root()).as_posix()
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
    # Clamped here rather than by the caller: one gate serves both the
    # foreground and background paths, and a model-supplied timeout is input.
    timeout = bounded_timeout(timeout)

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
            "timeout": {"type": "integer", "description": f"Timeout in seconds (capped at {MAX_TIMEOUT_S})", "default": 30},
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
        # Validate command. The level arrives per call, in the tool context --
        # see `allowlist_bypassed` and the ToolContext note in `tools/context.py`.
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
                command, cwd=sandbox_cwd, timeout=bounded_timeout(timeout)
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
