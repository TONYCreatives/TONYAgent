"""Read-only file tools that run INSIDE the sandbox container.

Why these exist: the shell allowlist deliberately excludes ``cat``/``ls`` so a
model-chosen command can't do anything unexpected. But without them the model
burns turns failing with "Command 'cat' not in allowlist" when it only wanted to
look at a file. These give that capability back through a narrow, typed,
read-only RPC instead of a general shell.

Use the host-side tools (``read_file``/``list_dir`` in file_tools.py) for normal
work. These matter when you specifically need the container's view - a
dependency resolved inside the sandbox, or a file that only exists in the image.
"""

from __future__ import annotations

from typing import Any

from tonyagent.config.settings import settings
from tonyagent.sandbox import get_shared_sandbox_manager
from tonyagent.sandbox.base import SandboxStatus
from tonyagent.tools.base import Tool, ToolCategory, ToolResult, ToolResultStatus, register_tool


def _running_backend():
    """Return the RUNNING backend, or raise with an actionable message."""
    backend = get_shared_sandbox_manager().get_backend()
    if backend is None:
        raise RuntimeError("Sandbox is not running (no backend). Start the sandbox first.")
    if backend.status is not SandboxStatus.RUNNING:
        raise RuntimeError(
            f"Sandbox is not running (status: {backend.status.value}). Start the sandbox first."
        )
    return backend


@register_tool
class SandboxReadFileTool(Tool):
    name = "sandbox_read_file"
    description = (
        "Read a text file from inside the sandbox container. Use this when you need "
        "the container's view of a file (e.g. a dependency installed only in the "
        "image). For ordinary project files prefer read_file, which does not "
        "require a running sandbox."
    )
    category = ToolCategory.FILE
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path relative to the project root (e.g. 'src/main.py')",
            },
            "max_bytes": {
                "type": "integer",
                "description": "Maximum bytes to read",
                "default": 1048576,
            },
        },
        "required": ["path"],
        "additionalProperties": False,
    }
    destructive = False
    requires_confirmation = False
    sandbox_required = True

    async def execute(self, path: str, max_bytes: int = 1048576) -> ToolResult:
        try:
            backend = _running_backend()
        except RuntimeError as e:
            return ToolResult(status=ToolResultStatus.ERROR, error=str(e))
        try:
            cap = min(int(max_bytes or 1048576), settings.tools.max_output_size)
            result = await backend.read_file(path, max_bytes=cap)
        except Exception as e:
            return ToolResult(status=ToolResultStatus.ERROR, error=f"Sandbox read failed: {e}")

        if not result.success:
            return ToolResult(status=ToolResultStatus.ERROR, error=result.error or "Read failed")

        data = result.data if isinstance(result.data, dict) else {}
        content = data.get("content", "")
        size = data.get("size", len(content))
        truncated = data.get("truncated", False)
        note = f"\n\n[truncated: showing {len(content)} of {size} bytes]" if truncated else ""
        return ToolResult(
            status=ToolResultStatus.SUCCESS,
            output=content + note,
            artifacts=[{"type": "sandbox_file", "path": data.get("path", path), "size": size}],
        )


@register_tool
class SandboxListFilesTool(Tool):
    name = "sandbox_list_files"
    description = (
        "List files visible inside the sandbox container. Use this to inspect the "
        "container filesystem. For ordinary project files prefer list_dir, which "
        "does not require a running sandbox."
    )
    category = ToolCategory.FILE
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Directory relative to the project root",
                "default": ".",
            },
            "max_depth": {
                "type": "integer",
                "description": "Maximum recursion depth",
                "default": 3,
            },
        },
        "additionalProperties": False,
    }
    destructive = False
    requires_confirmation = False
    sandbox_required = True

    async def execute(self, path: str = ".", max_depth: int = 3) -> ToolResult:
        try:
            backend = _running_backend()
        except RuntimeError as e:
            return ToolResult(status=ToolResultStatus.ERROR, error=str(e))
        try:
            result = await backend.list_files(path, max_depth=max_depth)
        except Exception as e:
            return ToolResult(status=ToolResultStatus.ERROR, error=f"Sandbox list failed: {e}")

        if not result.success:
            return ToolResult(
                status=ToolResultStatus.ERROR, error=result.error or "List failed"
            )

        data = result.data if isinstance(result.data, dict) else {}
        entries = data.get("entries", [])
        if not entries:
            output = "(empty)"
        else:
            lines = [
                f"{e['path']}/" if e.get("type") == "dir" else f"{e['path']}  ({e.get('size', 0)}B)"
                for e in entries
                if isinstance(e, dict)
            ]
            output = f"{len(lines)} entries:\n" + "\n".join(lines)
        return ToolResult(
            status=ToolResultStatus.SUCCESS,
            output=output,
            artifacts=[{"type": "sandbox_listing", "entries": entries}],
        )
