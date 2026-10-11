"""The tool definitions as the model actually receives them.

The provider hands the function definitions straight to the API, so this module
tests the payload that leaves the process rather than any intermediate object.
That distinction is the whole point: the bug this pins down was invisible in
every other test, because ``ToolSchema.parameters`` correctly held a complete
JSON Schema object and only the final OpenAI wrapper nested it one level too
deep.

A model shown ``properties: {"type": "object", "properties": {...}}`` is being
told each tool has a single parameter named ``type``. It cannot name a real
argument from that, so every tool call it made was a guess -- and a guess is
rejected by ``validate_args`` before the tool ever runs.
"""

from __future__ import annotations

import json

import pytest

from tonyagent.api.dialects import tool_to_openai
from tonyagent.core.modes import get_mode
from tonyagent.providers.base import ToolSchema
from tonyagent.tools.base import tool_registry
from tonyagent.tools.schemas import ALL_SCHEMAS

SCHEMAS_BY_NAME = {s["name"]: s for s in ALL_SCHEMAS}


def _load_all_tool_modules() -> None:
    import tonyagent.tools.browser_tools  # noqa: F401
    import tonyagent.tools.file_tools  # noqa: F401
    import tonyagent.tools.network_tools  # noqa: F401
    import tonyagent.tools.sandbox_file_tools  # noqa: F401
    import tonyagent.tools.search_tools  # noqa: F401
    import tonyagent.tools.shell_tools  # noqa: F401


_load_all_tool_modules()

TOOL_NAMES = sorted(t.name for t in tool_registry.get_all())


def _wire_payload(names=None) -> dict[str, dict]:
    """The exact ``tools`` array the request body would carry."""
    names = names or TOOL_NAMES
    schemas = [
        ToolSchema.from_tool_schema_dict(SCHEMAS_BY_NAME[n])
        for n in names
    ]
    return {t["function"]["name"]: t["function"] for t in (tool_to_openai([s.to_openai_format() for s in schemas]) or [])}


@pytest.mark.parametrize("name", TOOL_NAMES)
def test_wire_properties_are_the_real_parameter_names(name):
    """``properties`` must hold the arguments, not a nested schema.

    The regression signature is a tool whose only property is ``type``: that is
    the whole JSON Schema object having been placed where the argument map
    belongs.
    """
    fn = _wire_payload([name])[name]
    parameters = fn["parameters"]
    assert "properties" in parameters, f"{name}: no properties block on the wire"
    properties = parameters["properties"]

    expected = set((SCHEMAS_BY_NAME[name].get("parameters") or {}).get("properties") or {})
    assert set(properties) == expected, (
        f"{name}: wire properties {sorted(properties)} != schema {sorted(expected)}"
    )
    # A JSON Schema keyword leaking into the argument map is the exact shape of
    # the nesting bug, so name it explicitly rather than only via the mismatch.
    for keyword in ("type", "properties", "required", "additionalProperties"):
        assert keyword not in properties or keyword in expected, (
            f"{name}: {keyword!r} appears as a parameter name -- the schema is "
            "nested one level too deep"
        )


@pytest.mark.parametrize("name", TOOL_NAMES)
def test_wire_required_names_real_parameters(name):
    """Every required name must be a parameter the model can actually see."""
    fn = _wire_payload([name])[name]
    properties = set(fn["parameters"].get("properties") or {})
    required = fn["parameters"].get("required") or []
    assert set(required) <= properties, (
        f"{name}: required {required} is not among the advertised {sorted(properties)}"
    )
    assert list(required) == list(SCHEMAS_BY_NAME[name]["parameters"].get("required") or []), (
        f"{name}: required list on the wire differs from the schema"
    )


@pytest.mark.parametrize("name", TOOL_NAMES)
def test_wire_payload_is_json_serialisable(name):
    """The whole definition must survive ``json.dumps``.

    Enum members are the usual culprit: ``ToolCategory`` is a ``str`` Enum, so
    it serialises, but nothing guarantees that of every value a future field
    might hold.
    """
    json.dumps(_wire_payload([name])[name])


def test_every_tool_reaches_the_wire_intact():
    """A whole-conversation sanity check over the Build mode tool set.

    Uses the same path the session uses -- mode filtering, then the payload --
    so a tool that is registered but not exposed, or vice versa, shows up here
    rather than as a confusing turn.

    **22 -> 23 for `take_screenshot`**, **23 -> 25 for `read_image` and
    `web_fetch`**, **25 -> 28 for `job_list`, `job_output` and `job_kill`**,
    **28 -> 32 for the planning tools**, and **32 -> 34 for
    `ask_user_question` and `present`**. The number is a tripwire rather than the
    assertion: the set comparison above it is what proves the wiring, and this is
    here so that adding a tool to Build is something you read in a diff instead of
    something you find out about from a model calling a tool nobody expected.
    """
    allowed = set(get_mode("build").allowed_tools)
    payload = _wire_payload(sorted(allowed & set(TOOL_NAMES)))
    assert set(payload) == allowed & set(TOOL_NAMES)
    assert len(payload) == 34, f"expected all 34 tools, got {len(payload)}"
    for name, fn in payload.items():
        assert fn["description"].strip(), f"{name}: empty description on the wire"
        assert isinstance(fn["parameters"]["properties"], dict)
