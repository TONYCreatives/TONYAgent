"""Every tool, through the path the agent actually uses.

Calling ``tool().execute(...)`` directly is how the harnesses tested tools, and
it is a path the agent never takes. The agent goes through
``ToolOrchestrator.execute_tool_async``, which validates the mode, validates the
arguments, checks the folder, and asks for confirmation. A tool can therefore
pass every direct-call test and still be completely dead in the product.

This module drives all registered tools through the orchestrator with arguments
synthesised from their own schemas, so a tool that is not wired like the others
fails here rather than in front of a user. See ``test_every_registered_tool_is_a
_tool`` for the structural half of the same problem.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from tonyagent.core.modes import get_mode
from tonyagent.folder import folder_manager
from tonyagent.tools.base import Tool, ToolResultStatus, tool_registry
from tonyagent.tools.orchestrator import ToolCall, ToolOrchestrator
from tonyagent.tools.schemas import SCHEMAS_BY_NAME


def _load_all_tool_modules() -> None:
    """Import every tool module so the registry is fully populated."""
    import tonyagent.tools.browser_tools  # noqa: F401
    import tonyagent.tools.file_tools  # noqa: F401
    import tonyagent.tools.network_tools  # noqa: F401
    import tonyagent.tools.sandbox_file_tools  # noqa: F401
    import tonyagent.tools.search_tools  # noqa: F401
    import tonyagent.tools.shell_tools  # noqa: F401


_load_all_tool_modules()

TOOL_NAMES = sorted(t.name for t in tool_registry.get_all())

#: Values that satisfy a declared parameter without doing anything harmful. A
#: tool is allowed to fail on them -- "file not found" is a correct answer --
#: but it is not allowed to raise, because a raise means the plumbing is broken
#: rather than the request.
_DUMMY: dict[str, Any] = {
    "string": "x",
    "integer": 1,
    "number": 1,
    "boolean": False,
    "array": [],
    "object": {},
}

#: Per-parameter overrides, where the type alone is not a usable value.
_OVERRIDES: dict[tuple[str, str], Any] = {
    ("read", "path"): "hello.txt",
    ("write", "path"): "written.txt",
    ("write", "content"): "hello\n",
    ("edit", "path"): "hello.txt",
    ("edit", "old_string"): "hello",
    ("edit", "new_string"): "goodbye",
    ("delete_file", "path"): "doomed.txt",
    ("list_dir", "path"): ".",
    ("grep", "pattern"): "hello",
    ("glob", "pattern"): "*",
    ("http_request", "url"): "https://example.com",
    ("browser_navigate", "url"): "https://example.com",
    ("browser_click", "selector"): "body",
    ("browser_type", "selector"): "body",
    ("browser_type", "text"): "x",
    ("browser_wait_for", "state"): "load",
    ("execute_command", "command"): "python --version",
    ("execute_js", "script"): "1+1",
}


def _arguments_for(name: str) -> dict[str, Any]:
    """Build a structurally valid argument dict from the tool's own schema."""
    schema = SCHEMAS_BY_NAME.get(name, {})
    parameters = schema.get("parameters") or {}
    properties = parameters.get("properties") or {}
    required = list(parameters.get("required") or [])
    args: dict[str, Any] = {}
    for key in required:
        override = _OVERRIDES.get((name, key))
        if override is not None:
            args[key] = override
            continue
        declared = properties.get(key) or {}
        args[key] = _DUMMY.get(declared.get("type"), "x")
    return args


@pytest.fixture
def orchestrator(tmp_path: Path, monkeypatch):
    """An orchestrator with a project folder attached, in Build mode.

    Build is the only mode that sees all 22 tools, so it is the one that can
    prove every tool is reachable.
    """
    monkeypatch.setattr(folder_manager, "_current_folder", tmp_path)
    # Nothing is trusted, so a destructive tool asks for confirmation instead of
    # running. The test never answers, and that is fine: what is under test is
    # whether the call gets that far.
    orc = ToolOrchestrator()
    orc.set_mode(get_mode("build"))
    return orc


@pytest.mark.parametrize("name", TOOL_NAMES)
async def test_tool_survives_the_orchestrator(name, orchestrator, tmp_path):
    """No tool may raise on the agent's own path.

    An exception here is a plumbing failure. A returned ERROR is not: a tool
    legitimately refuses a sandbox, a network, or a missing file, and those
    refusals are the behaviour the rest of the suite pins down.
    """
    call = ToolCall(id=f"test-{name}", name=name, arguments=_arguments_for(name))
    try:
        result = await orchestrator.execute_tool_async(call)
    except Exception as exc:  # noqa: BLE001 - the failure is the finding
        pytest.fail(
            f"{name} raised {type(exc).__name__} through the orchestrator: {exc}. "
            "A tool that raises here is dead in the product even if its "
            "execute() works when called directly."
        )
    assert isinstance(result.status, ToolResultStatus)


# --- the structural invariants that make the above impossible to regress -----


def test_every_registered_tool_is_a_tool():
    """Every registered tool must inherit the base class.

    This is the whole bug in one assertion. The 11 browser tools subclassed
    ``object``, so they had no ``validate_args``, and the orchestrator calls it
    on every tool -- so all 11 raised ``AttributeError`` on the only path the
    agent uses while passing every direct-call test.
    """
    strays = [
        f"{t.name} ({type(t).__name__})"
        for t in tool_registry.get_all()
        if not isinstance(t, Tool)
    ]
    assert not strays, f"tools that do not inherit Tool: {strays}"


def test_required_is_a_real_list_of_strings():
    """``required`` must be usable, not a dataclasses.Field.

    ``Tool`` is not a dataclass, so ``field(default_factory=list)`` produced a
    ``Field`` object for all 22 tools. ``validate_args`` masked it with an
    ``isinstance`` guard and validated nothing.
    """
    broken = []
    for tool in tool_registry.get_all():
        value = getattr(tool, "required", None)
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            broken.append(f"{tool.name} -> {type(value).__name__}")
    assert not broken, f"tools whose .required is not a list of strings: {broken}"


def test_required_agrees_with_the_advertised_schema():
    """Validation must check what the model was told is required.

    The model reads ``parameters["required"]``; validation reads
    ``Tool.required``. Deriving one from the other is what keeps them equal.
    """
    mismatched = []
    for tool in tool_registry.get_all():
        schema_required = list(
            (SCHEMAS_BY_NAME.get(tool.name, {}).get("parameters") or {}).get("required") or []
        )
        if list(tool.required) != schema_required:
            mismatched.append(
                f"{tool.name}: validates {tool.required} but advertises {schema_required}"
            )
    assert not mismatched, "\n".join(mismatched)


def test_every_tool_emits_a_serialisable_schema():
    """``get_schema`` must produce JSON, since it is what goes on the wire.

    This is the check that would have caught the ``Field`` object: a
    ``dataclasses.Field`` in the ``required`` slot serialises to nothing useful.
    """
    bad = []
    for tool in tool_registry.get_all():
        try:
            json.dumps(tool.get_schema())
        except (TypeError, ValueError) as exc:
            bad.append(f"{tool.name}: {exc}")
    assert not bad, "\n".join(bad)


def test_no_schema_declares_a_required_parameter_it_does_not_describe():
    """A required name with no property is a promise the model cannot keep.

    The provider is free to send anything, so this would surface as a confusing
    validation error rather than as an obvious schema bug.
    """
    bad = []
    for name in TOOL_NAMES:
        parameters = SCHEMAS_BY_NAME.get(name, {}).get("parameters") or {}
        properties = parameters.get("properties") or {}
        for key in parameters.get("required") or []:
            if key not in properties:
                bad.append(f"{name}: requires {key!r} but does not describe it")
    assert not bad, "\n".join(bad)


@pytest.mark.parametrize("name", TOOL_NAMES)
async def test_orchestrator_reports_missing_required_arguments(name, orchestrator):
    """A required argument left out must be refused in plain language.

    Without this the caller gets a raw ``TypeError`` from the execute
    signature, which surfaces to the user as a Python message rather than as
    something they can act on.
    """
    tool = tool_registry.get(name)
    required = list(getattr(tool, "required", []) or [])
    if not required:
        pytest.skip(f"{name} declares no required arguments")

    arguments = _arguments_for(name)
    for key in required:
        arguments.pop(key, None)

    call = ToolCall(id=f"missing-{name}", name=name, arguments=arguments)
    try:
        result = await orchestrator.execute_tool_async(call)
    except Exception as exc:  # noqa: BLE001 - the failure is the finding
        pytest.fail(
            f"{name} raised {type(exc).__name__} instead of reporting the "
            f"missing argument(s) {required}: {exc}"
        )
    assert result.status is ToolResultStatus.ERROR
    assert "Invalid arguments" in (result.error or ""), (
        f"{name} refused a missing argument without saying which: {result.error!r}"
    )
