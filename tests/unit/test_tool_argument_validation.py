"""Argument validation: what a tool refuses, and what it must not.

``validate_args`` used to check presence and nothing else, on the stated grounds
that type and range were the provider's business. The provider, it turns out, has
no way to know what a *tool* wants: it forwards JSON, and a wrong type then
reached Python and failed somewhere unrelated to the argument at fault.

The replacement is a **check, not a coercion** -- it never rewrites a value, so
there is still exactly one place that decides what a value means (the provider)
and exactly one place that decides whether a value is acceptable (here). These
tests pin both halves: that bad arguments are refused in language the model can
act on, and that good arguments are passed through untouched.

The tools here are local doubles rather than the real registry. ``register_tool``
writes to a global, and a test that adds to it would change what every other test
in the suite sees -- including the wire-format test that counts them.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tonyagent.folder import folder_manager
from tonyagent.tools.base import Tool, ToolRegistry, ToolResult, ToolResultStatus
from tonyagent.tools.orchestrator import ToolCall, ToolOrchestrator

#: One property of every JSON type the schemas use, plus an enum.
_RICH_PARAMETERS = {
    "type": "object",
    "properties": {
        "count": {"type": "integer"},
        "label": {"type": "string"},
        "ratio": {"type": "number"},
        "flag": {"type": "boolean"},
        "tags": {"type": "array"},
        "options": {"type": "object"},
        "mode": {"type": "string", "enum": ["fast", "slow"]},
        "anything": {"description": "No declared type at all."},
    },
    "required": ["count"],
    "additionalProperties": False,
}


class _Probe(Tool):
    """A tool that records how it was called and never fails."""

    name = "probe"
    description = "Test double."
    parameters = _RICH_PARAMETERS

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def execute(self, **kwargs) -> ToolResult:
        self.calls.append(kwargs)
        return ToolResult(status=ToolResultStatus.SUCCESS, output=kwargs)


def _validate(args: dict, parameters: dict | None = None) -> tuple[bool, str | None]:
    tool = _Probe()
    if parameters is not None:
        tool.parameters = parameters
    return tool.validate_args(args)


# --- what must be accepted --------------------------------------------------


def test_a_well_formed_call_passes():
    ok, error = _validate({"count": 3, "label": "x", "mode": "fast"})
    assert ok, error
    assert error is None


def test_an_optional_parameter_may_be_absent():
    ok, error = _validate({"count": 1})
    assert ok, error


def test_a_float_satisfies_number():
    ok, error = _validate({"count": 1, "ratio": 1.5})
    assert ok, error


def test_an_integer_satisfies_number():
    """``number`` is the wider type, so an int belongs in it."""
    ok, error = _validate({"count": 1, "ratio": 2})
    assert ok, error


def test_empty_collections_satisfy_array_and_object():
    ok, error = _validate({"count": 1, "tags": [], "options": {}})
    assert ok, error


def test_additional_properties_opt_in_allows_extras():
    """A tool that advertises extra properties is allowed to receive them."""
    permissive = dict(_RICH_PARAMETERS, additionalProperties=True)
    ok, error = _validate({"count": 1, "surprise": "anything"}, permissive)
    assert ok, error


# --- what must be refused ---------------------------------------------------


def test_a_missing_required_parameter_is_named():
    ok, error = _validate({"label": "x"})
    assert not ok
    assert "count" in (error or "")


@pytest.mark.parametrize(
    ("name", "value", "expected_type"),
    [
        ("count", "3", "integer"),
        ("count", 3.5, "integer"),
        ("count", [3], "integer"),
        ("label", 7, "string"),
        ("ratio", "1.5", "number"),
        ("flag", "true", "boolean"),
        ("tags", "a,b", "array"),
        ("options", ["a"], "object"),
    ],
)
def test_a_wrong_type_is_refused_and_both_types_are_named(name, value, expected_type):
    args = {"count": 1, name: value}
    if name == "count":
        args = {name: value}
    ok, error = _validate(args)
    assert not ok, f"{name}={value!r} should not have been accepted"
    assert name in (error or ""), error
    assert expected_type in (error or ""), error


def test_a_boolean_is_not_an_integer():
    """The subclass trap: ``isinstance(True, int)`` is True in Python.

    Without the explicit check a schema asking for a count accepts ``true``,
    which is a different argument than the one the model was asked for.
    """
    ok, error = _validate({"count": True})
    assert not ok
    assert "boolean" in (error or "")


def test_a_boolean_is_not_a_number():
    ok, error = _validate({"count": 1, "ratio": False})
    assert not ok
    assert "boolean" in (error or "")


def test_a_string_is_not_coerced_into_an_integer():
    """Refused, not converted. ``"3"`` is a different value from ``3``."""
    ok, _ = _validate({"count": "3"})
    assert not ok


def test_an_enum_value_outside_the_list_names_the_choices():
    ok, error = _validate({"count": 1, "mode": "sideways"})
    assert not ok
    assert "fast" in (error or "") and "slow" in (error or ""), error


def test_an_unknown_parameter_names_what_is_accepted():
    ok, error = _validate({"count": 1, "invented": "x"})
    assert not ok
    assert "invented" in (error or "")
    assert "label" in (error or ""), "the message must say what the tool does take"


def test_a_property_with_no_declared_type_is_not_guessed_at():
    """No type is not an implicit ``string`` -- the check declines to have a view."""
    ok, error = _validate({"count": 1, "anything": {"any": "shape"}})
    assert ok, error


# --- passed through unchanged -----------------------------------------------


def test_validation_does_not_rewrite_the_arguments():
    """The values that survive validation are the values that were handed in.

    This is the property that keeps validation from becoming a second, competing
    implementation of the provider's coercion rules.
    """
    args = {"count": 3, "label": "x", "ratio": 1.5, "tags": ["a"]}
    before = {key: (type(value), value) for key, value in args.items()}
    ok, error = _validate(args)
    assert ok, error
    assert {key: (type(value), value) for key, value in args.items()} == before


# --- through the orchestrator, which is the path that matters ---------------


@pytest.fixture
def orchestrator(tmp_path: Path, monkeypatch):
    """An orchestrator holding only the probe tool.

    The registry is patched rather than added to, so the probe cannot leak into
    the global one and change what other tests see.
    """
    registry = ToolRegistry()
    probe = _Probe()
    registry.register(probe)
    monkeypatch.setattr("tonyagent.tools.orchestrator.tool_registry", registry)
    # `current_folder` is a read-only property over `_current_folder`, so the
    # backing field is what gets patched -- setting the property itself would
    # raise rather than take effect.
    monkeypatch.setattr(folder_manager, "_current_folder", tmp_path)
    orc = ToolOrchestrator()
    return orc, probe


async def test_the_orchestrator_refuses_a_bad_argument_without_running_the_tool(orchestrator):
    """The refusal has to happen *before* execution, or it is a report, not a gate."""
    orc, probe = orchestrator
    call = ToolCall(id="c1", name="probe", arguments={"count": "three"})
    result = await orc.execute_tool_async(call)
    assert result.status is ToolResultStatus.ERROR
    assert "Invalid arguments" in (result.error or ""), result.error
    assert probe.calls == [], "the tool ran despite invalid arguments"


async def test_the_orchestrator_runs_a_well_formed_call(orchestrator):
    orc, probe = orchestrator
    call = ToolCall(id="c2", name="probe", arguments={"count": 2, "mode": "fast"})
    result = await orc.execute_tool_async(call)
    assert result.status is ToolResultStatus.SUCCESS, result.error
    assert probe.calls == [{"count": 2, "mode": "fast"}]


async def test_every_real_tool_accepts_arguments_built_from_its_own_schema():
    """The stricter check must not refuse a tool's own advertised shape.

    This is the regression guard for the whole change: validation is only useful
    if a well-formed call -- one built by reading the schema the model is shown --
    still goes through. It is exercised with the real registry and the real
    schemas, and the orchestrator is not involved, so a failure here is about the
    schema and the check disagreeing rather than about any sandbox.
    """
    import tonyagent.tools  # noqa: F401  (populates the registry)
    from tonyagent.tools.base import tool_registry
    from tonyagent.tools.schemas import SCHEMAS_BY_NAME

    # Values that satisfy a declared type without doing anything.
    dummy = {
        "string": "x",
        "integer": 1,
        "number": 1,
        "boolean": False,
        "array": [],
        "object": {},
    }

    refused = []
    for tool in tool_registry.get_all():
        properties = ((SCHEMAS_BY_NAME[tool.name].get("parameters") or {}).get("properties")) or {}
        arguments = {}
        for key in tool.required:
            declared = properties.get(key) or {}
            if declared.get("enum"):
                arguments[key] = declared["enum"][0]
            else:
                arguments[key] = dummy.get(declared.get("type"), "x")
        ok, error = tool.validate_args(arguments)
        if not ok:
            refused.append(f"{tool.name}: {error}")

    assert not refused, "a tool refuses the arguments its own schema advertises:\n" + "\n".join(
        refused
    )
