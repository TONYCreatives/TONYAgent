"""The one-line detail a tool card can show.

`describeResult` in `app/src/events.ts` draws a card's detail from a single string
and looks for `summary` first. It only accepts a string, so a tool whose `output`
is a structured dict rendered as a **bare card**: `execute_command` reported
success and the transcript said nothing about what it printed.

`ToolResult.summary` is the missing channel. These tests hold both ends of it: the
excerpt helper behaves, and the tools that return structured output actually
populate it. The invariant worth stating is the one the bug broke -- *a successful
result whose `output` is not a string must carry a summary*, or the card is blank.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

import tonyagent.tools  # noqa: F401  -- importing registers every tool
from tonyagent.folder import folder_manager
from tonyagent.tools import shell_tools, tool_registry
from tonyagent.tools.base import EXCERPT_CHARS, ToolResult, ToolResultStatus, output_excerpt


def tool(name: str):
    found = tool_registry.get(name)
    assert found is not None, f"{name} is not registered"
    return found


def py(code: str) -> str:
    assert '"' not in code
    return f'"{sys.executable}" -c "{code}"'


@pytest.fixture
def host(monkeypatch, tmp_path):
    """Host execution and a project folder, so a command can actually run."""
    monkeypatch.setattr(shell_tools, "_HOST_EXECUTION", True)
    monkeypatch.setattr(folder_manager, "_current_folder", tmp_path)
    return tmp_path


# --- the excerpt helper ------------------------------------------------------


def test_the_first_non_empty_line_is_the_one_used():
    assert output_excerpt("\n\n  hello there  \nsecond\n") == "hello there"


def test_whitespace_inside_a_line_collapses():
    """A card is one line, so a tab-indented command output must not carry tabs."""
    assert output_excerpt("a\t\tb   c") == "a b c"


def test_nothing_to_say_comes_back_empty():
    assert output_excerpt("") == ""
    assert output_excerpt("\n\n   \n") == ""


def test_a_long_line_is_bounded():
    excerpt = output_excerpt("x" * 500)
    assert len(excerpt) == EXCERPT_CHARS
    assert excerpt.endswith("\u2026")


def test_a_line_that_just_fits_is_not_truncated():
    line = "y" * EXCERPT_CHARS
    assert output_excerpt(line) == line


# --- the channel exists ------------------------------------------------------


def test_the_summary_reaches_the_payload_the_window_reads():
    """`to_dict` is what is sent to the window *and* written to the conversation."""
    result = ToolResult(status=ToolResultStatus.SUCCESS, output={"a": 1}, summary="one line")
    assert result.to_dict()["summary"] == "one line"


def test_the_summary_defaults_to_none_rather_than_an_empty_string():
    """Absent and empty are different: the window falls through to `error` on absent."""
    result = ToolResult(status=ToolResultStatus.SUCCESS, output="text")
    assert result.to_dict()["summary"] is None


# --- execute_command ---------------------------------------------------------


async def test_a_successful_command_has_a_line_to_show(host):
    """The bug this fixes, asserted at the result the window receives."""
    result = await tool("execute_command").execute(py("print('5 passed')"))

    assert result.status is ToolResultStatus.SUCCESS
    assert isinstance(result.output, dict), "the structured shape is what the model reads"
    assert result.summary, "a dict-output tool with no summary is a blank card"
    assert "exit 0" in result.summary
    assert "5 passed" in result.summary


async def test_a_failing_command_says_so_in_its_line(host):
    result = await tool("execute_command").execute(
        py("import sys; sys.stderr.write('boom\\n'); sys.exit(2)")
    )

    assert result.status is ToolResultStatus.ERROR
    assert "exit 2" in result.summary
    assert "boom" in result.summary


async def test_a_silent_command_says_it_was_silent(host):
    """`exit 0` alone is honest; an empty string would be a blank card again."""
    result = await tool("execute_command").execute(py("pass"))

    assert result.summary == "exit 0 \u00b7 no output"


async def test_a_timeout_has_a_line_to_show(host):
    result = await tool("execute_command").execute(
        py("import time; time.sleep(10)"), timeout=1
    )

    assert result.status is ToolResultStatus.ERROR
    assert "Timeout" in result.summary


async def test_the_summary_is_a_string_the_window_can_render(host):
    """Not a dict, not a number: `describeResult` checks `typeof value === "string"`."""
    result = await tool("execute_command").execute(py("print('anything')"))
    assert isinstance(result.summary, str)
    assert len(result.summary) <= 200, "the window truncates past this anyway"


# --- http_request ------------------------------------------------------------


async def test_a_fetched_page_has_a_line_to_show(monkeypatch):
    """`http_request` returns the same structured shape and had the same blank card."""
    import httpx as real_httpx

    from tonyagent.tools import network_tools

    class _Response:
        status_code = 200
        text = "the docs say so"
        headers: dict = {}

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def request(self, **kwargs):
            return _Response()

    monkeypatch.setattr(
        network_tools,
        "httpx",
        type(
            "Stub",
            (),
            {"AsyncClient": _Client, "TimeoutException": real_httpx.TimeoutException},
        ),
    )

    result = await tool("http_request").execute(url="https://example.com")

    assert result.status is ToolResultStatus.SUCCESS
    assert isinstance(result.output, dict)
    assert "HTTP 200" in result.summary
    assert "the docs say so" in result.summary


# --- the invariant ----------------------------------------------------------


async def test_no_successful_dict_output_is_left_without_a_summary(host):
    """The general form of the bug, checked over every tool that can run here.

    A tool that returns structured ``output`` and no ``summary`` renders as a card
    with nothing on it, and nothing anywhere reports that -- which is why it went
    unnoticed. Tools that cannot run in this environment return an ERROR, and an
    error is rendered from ``error`` instead, so they are skipped rather than
    counted as passing.
    """
    from tonyagent.core.modes import get_mode
    from tonyagent.tools.orchestrator import ToolCall, ToolOrchestrator

    dummy = {"string": "x", "integer": 1, "number": 1, "boolean": False, "array": [], "object": {}}
    overrides = {
        ("execute_command", "command"): py("print('ok')"),
        ("read", "path"): "f.txt",
        ("write", "path"): "f.txt",
        ("write", "content"): "hello\n",
        ("edit", "path"): "f.txt",
        ("edit", "old_string"): "hello",
        ("edit", "new_string"): "goodbye",
        ("read_image", "path"): "f.txt",
        ("grep", "pattern"): "hello",
        ("glob", "pattern"): "*",
    }
    (Path(folder_manager.current_folder) / "f.txt").write_text("hello\n", encoding="utf-8")

    orchestrator = ToolOrchestrator()
    orchestrator.set_mode(get_mode("build"))

    blank: list[str] = []
    for tool_obj in tool_registry.get_all():
        properties = tool_obj.parameters.get("properties") or {}
        arguments = {}
        for key in tool_obj.required:
            if (tool_obj.name, key) in overrides:
                arguments[key] = overrides[(tool_obj.name, key)]
            else:
                declared = properties.get(key) or {}
                arguments[key] = (
                    declared["enum"][0] if declared.get("enum") else dummy.get(declared.get("type"), "x")
                )
        call = ToolCall(id=f"s-{tool_obj.name}", name=tool_obj.name, arguments=arguments)
        try:
            result = await orchestrator.execute_tool_async(call)
        except Exception:  # noqa: BLE001 - a raise here is another test's business
            continue
        if result.status is not ToolResultStatus.SUCCESS:
            continue
        if isinstance(result.output, str):
            continue
        if not (result.summary or result.error):
            blank.append(tool_obj.name)

    assert not blank, (
        "these tools return structured output and would draw a blank card, "
        f"because they set neither summary nor error: {blank}"
    )
