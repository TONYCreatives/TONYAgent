"""Read-only file tools that go through the sandbox runtime.

Why these exist: the shell allowlist deliberately excludes ``cat``/``ls`` so a
model-chosen command can't do anything unexpected. But without them the model
burns turns failing with "Command 'cat' not in allowlist" when it only wanted to
look at a file. These give that capability back through a narrow, typed,
read-only RPC instead of a general shell.

Use the host-side tools (``read_file``/``list_dir`` in file_tools.py) for normal
work. These matter when you specifically need the runtime's view - a dependency
resolved inside the container image, or a file that only exists there.

They run on the local runtime too, so no Docker daemon is required. What they
do not provide is containment: the workspace boundary holds, nothing more.
"""

from __future__ import annotations

from typing import Any

from tonyagent.config.settings import settings
from tonyagent.sandbox import get_shared_sandbox_manager
from tonyagent.sandbox.base import SandboxStatus
from tonyagent.tools.base import Tool, ToolCategory, ToolResult, ToolResultStatus, register_tool
from tonyagent.tools.runtime_access import running_backend


def _running_backend():
    """The RUNNING runtime, or raise with an actionable message.

    Alias for :func:`runtime_access.running_backend`, shared with the browser
    tools so one condition cannot be described two ways.
    """
    return running_backend()


@register_tool
class SandboxReadFileTool(Tool):
    """Read a file through the sandbox runtime, scoped to the project folder.

    Prefer ``read_file`` for ordinary project files. This exists for the case
    where the runtime's view differs -- a dependency that exists only inside
    the container's image, for instance.

    Works on the local runtime too, so it does not need Docker; only the
    workspace boundary is guaranteed, not containment.
    """

    name = "sandbox_read_file"
    description = (
        "Read a text file through the sandbox runtime, scoped to the project "
        "folder. Use this when you need the runtime's view of a file (e.g. a "
        "dependency installed only in the container image). For ordinary "
        "project files prefer read_file, which is simpler."
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
    """List files through the sandbox runtime, scoped to the project folder.

    The runtime-scoped counterpart to ``list_dir``, which is the better default
    for ordinary project files. Works on the local runtime as well, so Docker is
    not required.
    """

    name = "sandbox_list_files"
    description = (
        "List files through the sandbox runtime, scoped to the project folder. "
        "Use this to inspect the runtime's filesystem. For ordinary project "
        "files prefer list_dir, which is simpler."
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
