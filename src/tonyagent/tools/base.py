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


#: Longest one-line excerpt a card shows before it is cut.
#:
#: The window truncates a card's detail to 200 characters regardless; this is
#: shorter because a card is one line in a narrow column, and a line that has to be
#: truncated twice is a line nobody finishes reading.
EXCERPT_CHARS = 120


def output_excerpt(text: str, limit: int = EXCERPT_CHARS) -> str:
    """The first non-empty line of a tool's text output, collapsed and bounded.

    **Why this exists.** The window draws a tool card's detail from one string --
    ``describeResult`` in ``app/src/events.ts``, which checks ``summary`` first and
    only accepts a string. A tool whose ``output`` is a structured dict therefore
    renders as a bare card with nothing on it: ``execute_command`` succeeded and the
    transcript said nothing at all about what it printed. This is the line that
    fixes that, and ``ToolResult.summary`` is where it goes.

    The *first* line rather than the last because output that opens with a path, a
    banner or a command echo is more often identifying than output ending in a
    blank line or a progress figure.
    """
    for line in (text or "").splitlines():
        collapsed = " ".join(line.split())
        if collapsed:
            if len(collapsed) <= limit:
                return collapsed
            return collapsed[: limit - 1] + "\u2026"
    return ""


@dataclass
class ToolResult:
    """Result of tool execution."""

    status: ToolResultStatus
    output: Any = None
    #: One line for the tool card, for a tool whose ``output`` is not a string.
    #:
    #: Deliberately not derived automatically: only the tool knows which part of its
    #: result is worth a line, and a guess would put a `returncode: 0` where the
    #: interesting sentence should be.
    summary: str | None = None
    error: str | None = None
    artifacts: list[dict] = field(default_factory=list)  # files created, screenshots, etc.
    duration_ms: float = 0.0
    #: Images the *model* should look at, as ``{"mime", "data"}`` with ``data``
    #: already base64.
    #:
    #: Deliberately not part of `to_dict`. That dict is the wire payload for the
    #: window *and* the body of the tool message that is written into every
    #: saved conversation, and a screenshot is megabytes of base64: putting it
    #: there would make one capture cost as much disk as the rest of a chat put
    #: together. The session reads this field to build content parts for the
    #: model, and `attachments.strip_images` drops them again on the way to disk,
    #: so the pixels live exactly as long as the turn they belong to.
    images: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "status": self.status.value,
            "output": self.output,
            "summary": self.summary,
            "error": self.error,
            "artifacts": self.artifacts,
            "duration_ms": self.duration_ms,
        }


#: JSON Schema type name -> the Python types that satisfy it as validation.
#:
#: ``bool`` is excluded from ``integer`` and ``number`` deliberately and by name.
#: It is a subclass of ``int`` in Python, so ``isinstance(True, int)`` is True and
#: a schema asking for a count would otherwise accept ``true``.
_JSON_TYPES: dict[str, tuple[type, ...]] = {
    "string": (str,),
    "integer": (int,),
    "number": (int, float),
    "boolean": (bool,),
    "array": (list,),
    "object": (dict,),
    "null": (type(None),),
}


class Tool(ABC):
    """Base class for all tools."""

    name: str = ""
    description: str = ""
    category: ToolCategory = ToolCategory.UTILITY
    parameters: dict[str, Any] = {}
    #: Required parameters, derived from ``parameters`` rather than declared.
    #:
    #: This used to be ``field(default_factory=list)``, which is meaningless
    #: here because ``Tool`` is not a dataclass: the class attribute was a
    #: ``dataclasses.Field`` object, not a list, for all 22 tools. Nothing
    #: noticed because ``validate_args`` guarded with ``isinstance(..., list)``
    #: and quietly validated nothing, so a model could omit a required argument
    #: and get a raw ``TypeError`` from the execute signature instead of a
    #: sentence telling it which argument was missing.
    #:
    #: Reading it from ``parameters`` makes the schema the single source of
    #: truth, which is also the only copy ``ToolSchema.from_tool_schema_dict``
    #: consults -- so validation and the advertised contract now agree by
    #: construction rather than by two hand-maintained lists happening to match.
    @property
    def required(self) -> list[str]:
        declared = (self.parameters or {}).get("required") or []
        return list(declared)

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
    #: Needs a project folder to be selected before it can run.
    #:
    #: True for everything that touches the workspace. The network tools are the
    #: exception: fetching a URL neither reads nor writes the project, so
    #: requiring a folder for it would refuse the one call that works perfectly
    #: well without one.
    #:
    #: Declared here rather than special-cased by name in the orchestrator, which
    #: is where it started -- `!= "http_request"` -- and where it could only ever
    #: describe exactly one tool. A second folderless tool made that a lie.
    folder_required: bool = True

    #: Stops the turn to reach the *user*, rather than to ask permission for
    #: something destructive.
    #:
    #: Deliberately not in ``describe()``. That descriptor is the advertised
    #: contract -- what the model is shown and what ``tools.get`` reports --
    #: and "this tool will interrupt you" is not part of the model's contract.
    #: It is the orchestrator's scheduling information: ``will_prompt`` reads it
    #: to keep a batch containing such a call serial, because two dialogs at
    #: once is the one outcome worse than a slower turn.
    #:
    #: Trust and the Full rung do not skip it, and cannot: ``skips_confirmation``
    #: is a statement about approvals of destructive work, and a question is not
    #: that. A user who said "stop asking me" about file writes has not said
    #: "never ask me anything".
    asks_user: bool = False

    def describe(self) -> dict:
        """This tool as one flat descriptor: the single declaration everything reads.

        **This is the one place a tool is described.** ``parameters`` already *is*
        a complete JSON Schema object, and the four flags beside it are the same
        class attributes the orchestrator enforces -- so the advertised contract
        and the enforced one are one object rather than two lists that have to be
        kept in step by hand. ``tonyagent.tools.schemas`` builds its
        ``ALL_SCHEMAS`` from these, which is why declaring a tool is now one edit
        instead of two.

        The flat shape (metadata beside ``name``/``description`` rather than
        nested under a ``function`` key) is the shape ``ALL_SCHEMAS`` has always
        had and the shape ``ToolSchema.from_tool_schema_dict`` reads. The OpenAI
        nesting is applied exactly once, on the way out, by
        ``ToolSchema.to_openai_format``.

        Every flag is emitted even when it is ``False``, so the descriptor has a
        fixed shape. The hand-written schemas this replaces omitted the false
        ones, which meant "absent" and "false" were indistinguishable to a reader
        and a new tool could silently leave one out.
        """
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
            "category": self.category,
            "destructive": self.destructive,
            "requires_confirmation": self.requires_confirmation,
            "sandbox_required": self.sandbox_required,
            "isolation_required": self.isolation_required,
            "folder_required": self.folder_required,
        }

    def get_schema(self) -> dict:
        """The OpenAI-compatible function schema for this one tool.

        ``parameters`` is passed through rather than rebuilt. It is already a
        complete JSON Schema object -- ``{"type": "object", "properties": {...},
        "required": [...]}`` -- and re-wrapping it under ``properties`` nested the
        whole schema one level too deep, so a model reading this would have been
        told the tool takes a single parameter named ``type``.

        That was live in this method for as long as it existed, and it never
        reached a provider only because nothing called it: the wire path builds
        its payload from ``describe()`` through ``ToolSchema``, which does this
        correctly. It is fixed rather than deleted because it is public and the
        next caller would otherwise inherit the bug intact. The defensive wrap is
        kept for a tool built by hand with a bare properties dict, matching
        ``ToolSchema.to_openai_format``.
        """
        parameters = self.parameters or {"type": "object", "properties": {}}
        if "properties" not in parameters:
            parameters = {"type": "object", "properties": parameters}
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": parameters,
            },
        }

    @abstractmethod
    async def execute(self, **kwargs) -> ToolResult:
        """Execute the tool with given arguments."""
        pass

    def validate_args(self, args: dict) -> tuple[bool, str | None]:
        """Check arguments against the tool's own advertised schema.

        **Validation, not coercion.** Nothing here changes a value or fills one
        in; it only decides whether the call may proceed. That distinction is what
        keeps this compatible with the rule the previous version of this method
        was written to respect -- that turning a provider's JSON into Python
        values is the provider's job, and a second implementation of it here
        would be a second thing to disagree with. A check cannot disagree with a
        coercion: it either accepts the value it was handed or says why it will
        not. Defaults still come from the ``execute`` signature, in one place.

        What the check buys is that a malformed call is refused in the model's
        own language. Before this, a wrong type reached Python and failed
        somewhere unrelated to the argument that was wrong -- ``"offset": "10"``
        surfaced as a ``TypeError`` from inside the tool, which tells the model
        nothing about what to fix. It also makes ``additionalProperties: False``
        -- which every schema advertises -- a fact rather than a claim, so an
        invented parameter is refused instead of silently ignored.

        Type and enum only. Range is deliberately not checked: the schemas do not
        express it, so enforcing a bound here would mean inventing one the model
        was never shown and could not have known.
        """
        for req in self.required:
            if req not in args:
                return False, f"Missing required parameter: {req}"

        schema = self.parameters or {}
        properties: dict = schema.get("properties") or {}

        # Honour what is advertised rather than assuming: a tool that opts into
        # extra properties is allowed to receive them.
        if not schema.get("additionalProperties", False):
            unknown = sorted(set(args) - set(properties))
            if unknown:
                known = ", ".join(sorted(properties)) or "none"
                return False, (
                    f"Unknown parameter(s): {', '.join(unknown)}. "
                    f"This tool accepts: {known}."
                )

        for name, value in args.items():
            declared = properties.get(name) or {}
            expected = declared.get("type")
            if expected is None:
                # A property with no declared type is not a reason to guess one.
                continue
            allowed = _JSON_TYPES.get(expected)
            if allowed is None:
                # An unknown type name is a defect in the schema, not in the
                # call, so the call is not the thing to refuse.
                continue
            if expected in ("integer", "number") and isinstance(value, bool):
                return False, (
                    f"Parameter {name!r} must be {expected}, got a boolean"
                )
            if not isinstance(value, allowed):
                return False, (
                    f"Parameter {name!r} must be {expected}, "
                    f"got {type(value).__name__}"
                )
            choices = declared.get("enum")
            if choices and value not in choices:
                rendered = ", ".join(repr(choice) for choice in choices)
                return False, (
                    f"Parameter {name!r} must be one of {rendered}, got {value!r}"
                )
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
        """Every registered tool's flat descriptor. See ``Tool.describe``.

        Deliberately the *flat* shape rather than the OpenAI-wrapped one: this is
        what ``ALL_SCHEMAS`` is built from, and the single wrapping step happens
        once, later, in ``ToolSchema.to_openai_format``.
        """
        return [tool.describe() for tool in self._tools.values()]

    def list_names(self) -> list[str]:
        """List all tool names."""
        return list(self._tools.keys())


# Global registry
tool_registry = ToolRegistry()


def register_tool(tool_cls: type[Tool] | Tool) -> type[Tool] | Tool:
    """Decorator to register a tool class (or instance)."""
    return tool_registry.register(tool_cls)