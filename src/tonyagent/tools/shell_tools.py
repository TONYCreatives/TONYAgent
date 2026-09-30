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


def _is_command_allowed(command: str) -> tuple[bool, str]:
    """Check if command is allowed by allowlist/denylist."""
    parts = shlex.split(command)
    if not parts:
        return False, "Empty command"
    
    base_cmd = Path(parts[0]).name.lower()
    
    # Check denylist first
    for deny_pattern in settings.tools.command_denylist:
        if re.search(deny_pattern, command, re.IGNORECASE):
            return False, f"Command matches denylist pattern: {deny_pattern}"
    
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

    Three gates, in order: the command allow/deny list, then the isolation
    check, then per-session confirmation. A trusted project skips the prompt
    but never the allowlist.
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
        # Validate command
        allowed, reason = _is_command_allowed(command)
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
