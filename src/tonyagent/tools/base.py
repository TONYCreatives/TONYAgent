"""Tool system base classes for TONYAgent."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable
from enum import Enum


class ToolCategory(str, Enum):
    """Tool categories for UI filtering."""
    FILE = "file"
    SEARCH = "search"
    SHELL = "shell"
    NETWORK = "network"
    BROWSER = "browser"
    UTILITY = "utility"


class ToolResultStatus(str, Enum):
    """Tool execution result status."""
    SUCCESS = "success"
    ERROR = "error"
    CANCELLED = "cancelled"
    CONFIRMATION_REQUIRED = "confirmation_required"


@dataclass
class ToolResult:
    """Result of tool execution."""
    status: ToolResultStatus
    output: Any = None
    error: str | None = None
    artifacts: list[dict] = field(default_factory=list)  # files created, screenshots, etc.
    duration_ms: float = 0.0

    def to_dict(self) -> dict:
        return {
            "status": self.status.value,
            "output": self.output,
            "error": self.error,
            "artifacts": self.artifacts,
            "duration_ms": self.duration_ms,
        }


class Tool(ABC):
    """Base class for all tools."""

    name: str = ""
    description: str = ""
    category: ToolCategory = ToolCategory.UTILITY
    parameters: dict[str, Any] = {}
    required: list[str] = field(default_factory=list)
    destructive: bool = False
    requires_confirmation: bool = False
    #: Needs a sandbox *runtime* of some kind. The local runtime satisfies
    #: this, so these tools work with no Docker daemon.
    sandbox_required: bool = False
    #: Needs a runtime that actually *contains* what runs inside it.
    #:
    #: Distinct from ``sandbox_required`` on purpose. A headless browser or a
    #: read of a workspace file is not a shell escape, so those tools are happy
    #: on the local runtime. A tool that executes arbitrary code is not, and
    #: must be refused there rather than quietly run on the user's machine.
    isolation_required: bool = False

    def get_schema(self) -> dict:
        """Get OpenAI-compatible function schema."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": self.parameters,
                    "required": self.required,
                    "additionalProperties": False,
                },
            },
        }

    @abstractmethod
    async def execute(self, **kwargs) -> ToolResult:
        """Execute the tool with given arguments."""
        pass

    def validate_args(self, args: dict) -> tuple[bool, str | None]:
        """Validate arguments against schema."""
        required = self.required if isinstance(self.required, list) else []
        for req in required:
            if req not in args:
                return False, f"Missing required parameter: {req}"
        return True, None


class ToolRegistry:
    """Registry for managing available tools."""

    def __init__(self):
        self._tools: dict[str, Tool] = {}
        self._categories: dict[ToolCategory, list[str]] = {cat: [] for cat in ToolCategory}

    def register(self, tool_cls: type[Tool] | Tool) -> type[Tool] | Tool:
        """Register a tool class or instance.

        Used as ``@register_tool`` directly on the class, so the decorator
        usually receives the class object. The registry stores INSTANCES (so
        ``validate_args``/``execute`` are bound), but returns the CLASS
        unchanged so ``ToolClass()`` keeps working at call sites.
        """
        if isinstance(tool_cls, type):
            tool: Tool = tool_cls()
            if not tool.name:
                raise ValueError("Tool must have a name")
            if tool.name in self._tools:
                raise ValueError(f"Tool '{tool.name}' already registered")
            self._tools[tool.name] = tool
            self._categories[tool.category].append(tool.name)
            return tool_cls
        if not tool_cls.name:
            raise ValueError("Tool must have a name")
        if tool_cls.name in self._tools:
            raise ValueError(f"Tool '{tool_cls.name}' already registered")
        self._tools[tool_cls.name] = tool_cls
        self._categories[tool_cls.category].append(tool_cls.name)
        return tool_cls

    def get(self, name: str) -> Tool | None:
        """Get tool by name."""
        return self._tools.get(name)

    def get_all(self) -> list[Tool]:
        """Get all registered tools."""
        return list(self._tools.values())

    def get_by_category(self, category: ToolCategory) -> list[Tool]:
        """Get tools by category."""
        return [self._tools[name] for name in self._categories[category] if name in self._tools]

    def get_schemas(self) -> list[dict]:
        """Get all tool schemas for function calling."""
        return [tool.get_schema() for tool in self._tools.values()]

    def list_names(self) -> list[str]:
        """List all tool names."""
        return list(self._tools.keys())


# Global registry
tool_registry = ToolRegistry()


def register_tool(tool_cls: type[Tool] | Tool) -> type[Tool] | Tool:
    """Decorator to register a tool class (or instance)."""
    return tool_registry.register(tool_cls)