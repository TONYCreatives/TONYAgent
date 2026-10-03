"""Tool orchestrator for TONYAgent."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from loguru import logger

from tonyagent.tools.base import Tool, ToolRegistry, ToolResult, ToolResultStatus, tool_registry
from tonyagent.folder.manager import folder_manager
from tonyagent.utils.threading import schedule_on_ui


#: Longest argument value reproduced verbatim in a log line.
#:
#: 24 characters, not "anything under a line". A path or a glob fits easily;
#: an API key fits too, and an API key in a log strip is the exact failure
#: Phase 2 closed. The threshold is set so that the things worth reading
#: survive and the things that must not be logged cannot.
_SAFE_ARG_CHARS = 24


def _summarise_args(arguments: dict[str, Any]) -> str:
    """A one-line, bounded description of a tool call's arguments.

    These used to be interpolated whole, which put the *entire contents of
    every file the agent wrote* into the log stream -- and that stream is
    rendered in the UI's log strip and written to stderr. So a user who asked
    the agent to write a config containing a credential would see it echoed
    back in the panel, which is the same failure Phase 2 fixed for API keys.

    Short values (paths, patterns, flags) are still shown, because "which
    file" is what makes a log line useful. Anything longer is described by its
    length instead of its content. Note that a *short* secret is still
    printed: this is a bound on the log's usefulness, not a secret detector,
    and it must not be relied on as one.
    """
    parts = []
    for key, value in arguments.items():
        if isinstance(value, str) and len(value) > _SAFE_ARG_CHARS:
            parts.append(f"{key}=<{len(value)} chars>")
        elif isinstance(value, (dict, list)):
            parts.append(f"{key}=<{type(value).__name__}>")
        else:
            parts.append(f"{key}={value!r}")
    return ", ".join(parts)


@dataclass
class ToolCall:
    """Represents a tool call from the AI."""
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class ConfirmationRequest:
    """Request for user confirmation."""
    tool_call: ToolCall
    tool: Tool
    future: asyncio.Future | None = None
    timestamp: float = field(default_factory=time.time)


class ToolOrchestrator:
    """Orchestrates tool execution with validation, confirmation, and logging."""

    def __init__(self):
        self._pending_confirmations: dict[str, ConfirmationRequest] = {}
        self._execution_history: list[dict] = []
        self._confirmation_callback: Optional[Callable] = None
        self._log_callback: Optional[Callable] = None
        self._trusted_projects: set[str] = set()
        #: Active mode, or None for unrestricted (the Tkinter UI's behaviour).
        self._mode: Any = None
        # The permission level, intersecting with the mode. See `tool_permitted`.
        self._permission: Any = None

    def set_trusted(self, project: str, trusted: bool = True) -> None:
        """Mark a project folder as trusted (skip per-command confirmations)."""
        if trusted:
            self._trusted_projects.add(str(project))
        else:
            self._trusted_projects.discard(str(project))

    def is_trusted(self, project: str) -> bool:
        return str(project) in self._trusted_projects

    # -- mode permissions ----------------------------------------------------
    def set_mode(self, mode: Any) -> None:
        """Restrict this orchestrator to one mode's tools.

        The session pushes its mode here so the *enforcement* lives in the
        layer that actually runs tools, not in the layer that describes them.
        Hiding a tool from the schema is a suggestion to a model; this is the
        check that cannot be argued with. `None` means unrestricted, which is
        what the Tkinter UI and the tests get.
        """
        self._mode = mode

    def tool_permitted(self, name: str) -> bool:
        """Whether the active permission level allows this tool.

        **The intersection, not an override.** A mode and a permission level are
        two independent limits and a tool has to satisfy both: asking for Full
        does not put `write_file` back in reach while Plan mode is on, and Plan
        does not withdraw `execute_command` while Full is. Each can only ever
        make the set smaller, so there is no combination of the two controls
        that widens access past what Build mode and Full together already allow.
        """
        mode = self._mode
        permission = self._permission
        if mode is not None and name not in mode.allowed_tools:
            return False
        if permission is not None and name not in permission.allowed_tools:
            return False
        return True

    def allows_any_command(self) -> bool:
        """Whether the active level runs commands off the allow-list.

        False when nothing is set, which is what an unrestricted orchestrator
        (the Tkinter path and most tests) wants.
        """
        return bool(getattr(self._permission, "bypasses_command_allowlist", False))

    def set_permission(self, permission: Any) -> None:
        """Apply a permission level, or ``None`` for unrestricted.

        Same reasoning as `set_mode`: the session pushes the level here so the
        decision is made by the layer that runs tools, not the one that lists
        them. A level enforced only by filtering the schema would be a
        suggestion to the model.

        Also publishes the allow-list decision to `shell_tools`, because
        `ExecuteCommandTool` needs it and must not consult an orchestrator
        instance -- there would then be two readers of one setting. See
        `_ALLOWLIST_BYPASS` there for what went wrong the first time.
        """
        self._permission = permission
        from tonyagent.tools.shell_tools import set_allowlist_bypass

        set_allowlist_bypass(self.allows_any_command())

    def set_confirmation_callback(self, callback: Callable[[ConfirmationRequest], None]) -> None:
        self._confirmation_callback = callback

    def set_log_callback(self, callback: Callable[[str, str], None]) -> None:
        self._log_callback = callback

    def execute_tool(self, tool_call: ToolCall) -> ToolResult:
        """Execute a tool call synchronously (blocking).

        Must be called from a thread WITHOUT a running event loop (e.g. the
        background generation thread in MainWindow). Use
        ``await execute_tool_async(...)`` from async code instead.
        """
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            pass
        else:
            raise RuntimeError("execute_tool() called from async context; use execute_tool_async()")
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(self._execute_tool_async(tool_call))
        finally:
            loop.close()

    async def execute_tool_async(self, tool_call: ToolCall) -> ToolResult:
        """Async entry point for use inside a running event loop."""
        return await self._execute_tool_async(tool_call)

    async def _execute_tool_async(self, tool_call: ToolCall) -> ToolResult:
        start_time = time.time()
        
        tool = tool_registry.get(tool_call.name)
        if not tool:
            return ToolResult(status=ToolResultStatus.ERROR, error=f"Unknown tool: {tool_call.name}")

        # Mode enforcement comes FIRST, before argument validation and before
        # any confirmation prompt. A tool the mode forbids is not a call with
        # bad arguments, and it must not reach the point where the user is
        # asked to approve something the mode was meant to make impossible.
        if not self.tool_permitted(tool_call.name):
            mode = self._mode
            return ToolResult(
                status=ToolResultStatus.ERROR,
                error=(
                    f"{tool_call.name} is not available in {mode.label} mode."
                    if mode is not None
                    else f"{tool_call.name} is not available."
                ),
            )

        valid, error = tool.validate_args(tool_call.arguments)
        if not valid:
            return ToolResult(status=ToolResultStatus.ERROR, error=f"Invalid arguments: {error}")
        
        if tool_call.name != "http_request" and not folder_manager.current_folder:
            return ToolResult(status=ToolResultStatus.ERROR, error="No project folder selected")
        
        if tool.destructive and tool.requires_confirmation:
            # Two ways to stop asking, either of which is enough.
            #
            # **Trust** is the per-session statement about a folder: this code is
            # mine, stop interrupting me. It predates the permission levels and
            # is unchanged by them.
            #
            # **Full** is the user choosing, for this window, not to be asked.
            # It is the *broader* of the two on purpose: trust is set in
            # Settings and tends to stay set, while Full is visible in the bar
            # and read on every turn. That makes it the answer for "I trust this
            # one job" without going to change a setting first.
            #
            # What Full deliberately does not do is widen anything. The mode and
            # permission checks above ran already, the allow-list below still
            # has the last word on commands, and `execute_command` still refuses
            # without an isolating sandbox. It removes the question, not the
            # gates -- which is why the ladder above it still means something.
            permission = self._permission
            full = bool(getattr(permission, "skips_confirmation", False))
            current = folder_manager.current_folder
            trusted = current is not None and self.is_trusted(str(current))
            skip_confirm = False
            if full or trusted:
                if tool_call.name == "execute_command":
                    from tonyagent.tools.shell_tools import _is_command_allowed

                    # At Full the allow-list is not consulted at all -- that is
                    # what this level now means. Below it, an off-allowlist
                    # command still asks, so High keeps a question the user can
                    # answer and Full is the rung that removes it.
                    allowed, _ = _is_command_allowed(
                        tool_call.arguments.get("command", ""),
                        bypass_allowlist=self.allows_any_command(),
                    )
                    skip_confirm = allowed
                else:
                    skip_confirm = True
                    skip_confirm = True
            if not skip_confirm:
                result = await self._request_confirmation(tool_call, tool)
                if result:
                    return result
        
        self._log(f"Executing {tool_call.name}({_summarise_args(tool_call.arguments)})", "info")
        
        try:
            result = await tool.execute(**tool_call.arguments)
        except Exception as e:
            logger.exception(f"Tool {tool_call.name} raised exception")
            result = ToolResult(status=ToolResultStatus.ERROR, error=f"Tool execution failed: {e}")
        
        duration_ms = (time.time() - start_time) * 1000
        result.duration_ms = duration_ms
        
        log_level = "success" if result.status == ToolResultStatus.SUCCESS else "error"
        self._log(f"{tool_call.name} completed in {duration_ms:.0f}ms: {result.status.value}", log_level)
        
        self._execution_history.append({
            "call": {"id": tool_call.id, "name": tool_call.name, "arguments": tool_call.arguments},
            "result": result.to_dict(),
            "duration_ms": duration_ms,
        })
        
        return result

    async def _request_confirmation(self, tool_call: ToolCall, tool: Tool) -> ToolResult | None:
        if self._confirmation_callback:
            confirmation = ConfirmationRequest(tool_call, tool)
            confirmation.future = asyncio.get_running_loop().create_future()
            
            self._pending_confirmations[tool_call.id] = confirmation
            
            schedule_on_ui(self._confirmation_callback, confirmation)
            
            try:
                confirmed = await asyncio.wait_for(confirmation.future, timeout=60.0)
            except asyncio.TimeoutError:
                confirmed = False
            
            del self._pending_confirmations[tool_call.id]
            
            if not confirmed:
                return ToolResult(status=ToolResultStatus.CANCELLED, error="User cancelled")
        return None

    def respond_to_confirmation(self, tool_call_id: str, confirmed: bool) -> None:
        if tool_call_id in self._pending_confirmations:
            confirmation = self._pending_confirmations[tool_call_id]
            if confirmation.future and not confirmation.future.done():
                confirmation.future.set_result(confirmed)

    def _log(self, message: str, level: str = "info") -> None:
        if self._log_callback:
            schedule_on_ui(self._log_callback, message, level)
        getattr(logger, level)(message)

    def get_history(self) -> list[dict]:
        return self._execution_history.copy()

    def clear_history(self) -> None:
        self._execution_history.clear()


# Global orchestrator
tool_orchestrator = ToolOrchestrator()