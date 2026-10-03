"""Shell command tools for TONYAgent."""

from __future__ import annotations

import asyncio
import re
import shlex
from pathlib import Path

from tonyagent.sandbox import get_shared_sandbox_manager
from tonyagent.sandbox.base import SandboxStatus
from tonyagent.tools.base import Tool, ToolResult, ToolResultStatus, ToolCategory, register_tool
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


async def _execute_local(command: str, cwd: str, timeout: int) -> ToolResult:
    """Host fallback (only when settings.tools.fallback_to_local is True)."""
    logger.warning(f"Executing on HOST (no sandbox): {command}")
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
    """

    name = "execute_command"
    description = "Execute a shell command in the sandbox environment."
    category = ToolCategory.SHELL
    parameters = {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "Command to execute"},
            "cwd": {"type": "string", "description": "Working directory (relative to project root)", "default": "."},
            "timeout": {"type": "integer", "description": "Timeout in seconds", "default": 30},
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

    async def execute(self, command: str, cwd: str = ".", timeout: int = 30) -> ToolResult:
        # Validate command. The level comes from the module flag rather than
        # from an orchestrator instance -- see `_ALLOWLIST_BYPASS` for why there
        # is exactly one of those.
        allowed, reason = _is_command_allowed(
            command, bypass_allowlist=allowlist_bypassed()
        )
        if not allowed:
            return ToolResult(status=ToolResultStatus.ERROR, error=f"Command not allowed: {reason}")

        # An *isolating* backend only. get_backend() deliberately does not
        # return the local runtime, because running a model-authored command on
        # the host is exactly the thing that runtime must never be trusted for.
        manager = get_shared_sandbox_manager()
        if manager.get_runtime_backend() is None and not settings.tools.fallback_to_local:
            # Checked first so this tool says the same thing as execute_js when
            # nothing is attached at all. Two tools that both need isolation
            # should not tell the user two different stories about one cause.
            # Skipped when host execution was explicitly opted into, since that
            # opt-in is precisely a way to run with no sandbox at all.
            return ToolResult(
                status=ToolResultStatus.ERROR,
                error=(
                    "The sandbox runtime is not running. Choose a project folder "
                    "in Settings first."
                ),
            )
        backend = manager.get_backend()
        if (
            backend is not None
            and backend.status is SandboxStatus.RUNNING
            # A third-party backend without the flag reads as not isolating,
            # so an older plugin fails closed instead of running on the host.
            and getattr(backend, "provides_isolation", False)
        ):
            try:
                sandbox_cwd = _resolve_sandbox_cwd(cwd)
            except ValueError as e:
                return ToolResult(status=ToolResultStatus.ERROR, error=str(e))
            try:
                result = await backend.execute_command(command, cwd=sandbox_cwd, timeout=timeout)
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
                error=stderr_str if result.returncode != 0 else None,
            )

        # Sandbox not running: fail closed unless fallback explicitly enabled.
        if settings.tools.fallback_to_local:
            try:
                return await _execute_local(command, cwd, timeout)
            except Exception as e:
                return ToolResult(status=ToolResultStatus.ERROR, error=str(e))
        return ToolResult(
            status=ToolResultStatus.ERROR,
            error=(
                "No isolated sandbox is running. Running commands on the host is "
                "not a substitute, so this is refused on purpose -- start Docker "
                "and pick the project folder again (or set "
                "tools.fallback_to_local=true to accept host execution)."
            ),
        )
