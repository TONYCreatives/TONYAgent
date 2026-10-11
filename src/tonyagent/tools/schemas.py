"""Tool schemas, derived from the tools themselves.

**This module used to be a second, hand-written copy of every tool's
declaration** -- 23 dictionaries restating the name, description, parameters and
four flags that the ``Tool`` classes already carried. Nothing kept the two in
step except a handful of parity tests, and the failure mode when they drifted
was silent rather than loud: the registry is what *runs* a tool and this module
is what *advertises* it, so a tool missing here is one the model is never told
about, and a flag disagreeing here is one the UI describes wrongly. Neither
raises anything.

So the direction is inverted. A tool is declared once, on its class, and this
module *derives* the advertised list from the registry. There is nothing left to
keep in sync, which is why adding a tool is one edit rather than two.

**The derivation is lazy, and it has to be.** ``tonyagent.tools`` imports this
module, and this module needs the registry to be full -- which only happens once
the tool modules have been imported. Building the list at import time would
therefore produce an empty one. ``ALL_SCHEMAS`` is resolved on first access
instead, by which point ``tonyagent.tools.__init__`` has imported every tool
module. That ordering is the load-bearing part of this arrangement and is
asserted rather than assumed: see ``test_schemas_are_derived_from_the_registry``.
"""

from __future__ import annotations

from typing import Any

from tonyagent.tools.base import tool_registry


def build_schemas() -> list[dict]:
    """Every registered tool, in registration order, as a flat descriptor.

    Rebuilt per call rather than cached. The list is 23 small dicts, and a cache
    would go stale for any test that registers a tool after import -- which is
    exactly the kind of silent disagreement this module exists to remove.
    """
    return [tool.describe() for tool in tool_registry.get_all()]


def schemas_by_name() -> dict[str, dict]:
    """The same descriptors, keyed by tool name."""
    return {schema["name"]: schema for schema in build_schemas()}


#: The per-tool constants callers import by name, mapped to the tool each one
#: names. Kept because ``tonyagent.tools`` re-exports them, and resolved through
#: the registry rather than restated, so they cannot go stale.
_NAMED: dict[str, str] = {
    "READ_SCHEMA": "read",
    "WRITE_SCHEMA": "write",
    "EDIT_SCHEMA": "edit",
    "DELETE_FILE_SCHEMA": "delete_file",
    "LIST_DIR_SCHEMA": "list_dir",
    "GREP_SCHEMA": "grep",
    "GLOB_SCHEMA": "glob",
    "EXECUTE_COMMAND_SCHEMA": "execute_command",
    "HTTP_REQUEST_SCHEMA": "http_request",
    "BROWSER_NAVIGATE_SCHEMA": "browser_navigate",
    "BROWSER_CLICK_SCHEMA": "browser_click",
    "BROWSER_TYPE_SCHEMA": "browser_type",
    "BROWSER_EVAL_SCHEMA": "browser_eval",
    "BROWSER_SNAPSHOT_SCHEMA": "browser_snapshot",
    "SET_VIEWPORT_SIZE_SCHEMA": "set_viewport_size",
    "BROWSER_GET_TEXT_SCHEMA": "browser_get_text",
    "BROWSER_WAIT_FOR_SCHEMA": "browser_wait_for",
    "BROWSER_SCROLL_SCHEMA": "browser_scroll",
    "BROWSER_SCREENSHOT_SCHEMA": "browser_screenshot",
    "EXECUTE_JS_SCHEMA": "execute_js",
    "SANDBOX_READ_FILE_SCHEMA": "sandbox_read_file",
    "SANDBOX_LIST_FILES_SCHEMA": "sandbox_list_files",
    "TAKE_SCREENSHOT_SCHEMA": "take_screenshot",
}

__all__ = [
    "ALL_SCHEMAS",
    "SCHEMAS_BY_NAME",
    "build_schemas",
    "schemas_by_name",
    *sorted(_NAMED),
]


def __getattr__(name: str) -> Any:
    """Resolve the derived names on first access, once the registry is full.

    Module-level ``__getattr__`` (PEP 562) rather than a computed constant: it is
    what lets ``from tonyagent.tools.schemas import ALL_SCHEMAS`` keep working
    unchanged at every existing call site while deferring the build until the
    tool modules have registered themselves.
    """
    if name == "ALL_SCHEMAS":
        return build_schemas()
    if name == "SCHEMAS_BY_NAME":
        return schemas_by_name()
    tool_name = _NAMED.get(name)
    if tool_name is not None:
        schema = schemas_by_name().get(tool_name)
        if schema is None:
            # Name the tool rather than the constant: the constant is fine and
            # the missing registration is the actual problem.
            raise AttributeError(
                f"{name} resolves to tool {tool_name!r}, which is not registered"
            )
        return schema
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    """Include the lazy names, so tab-completion and ``dir()`` still show them."""
    return sorted(set(globals()) | set(__all__))
