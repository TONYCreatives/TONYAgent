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

    def set_trusted(self, project: str, trusted: bool = True) -> None:
        """Mark a project folder as trusted (skip per-command confirmations)."""
        if trusted:
            self._trusted_projects.add(str(project))
        else:
            self._trusted_projects.discard(str(project))

    def is_trusted(self, project: str) -> bool:
        return str(project) in self._trusted_projects

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
        
        valid, error = tool.validate_args(tool_call.arguments)
        if not valid:
            return ToolResult(status=ToolResultStatus.ERROR, error=f"Invalid arguments: {error}")
        
        if tool_call.name != "http_request" and not folder_manager.current_folder:
            return ToolResult(status=ToolResultStatus.ERROR, error="No project folder selected")
        
        if tool.destructive and tool.requires_confirmation:
            # Per-session "trust this project": skip the modal for trusted
            # folders, but non-allowlisted shell commands always ask.
            skip_confirm = False
            current = folder_manager.current_folder
            if current is not None and self.is_trusted(str(current)):
                if tool_call.name == "execute_command":
                    from tonyagent.tools.shell_tools import _is_command_allowed

                    allowed, _ = _is_command_allowed(tool_call.arguments.get("command", ""))
                    skip_confirm = allowed
                else:
                    skip_confirm = True
            if not skip_confirm:
                result = await self._request_confirmation(tool_call, tool)
                if result:
                    return result
        
        self._log(f"Executing {tool_call.name}({tool_call.arguments})", "info")
        
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