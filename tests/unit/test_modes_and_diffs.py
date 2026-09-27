"""Composer modes and file-change diffs.

Both features were added in Phase 3 and both have a failure mode that a
passing build would not reveal:

* A mode that only changes the *prompt* produces a model that says "I will not
  modify that file" and then modifies it. So modes are enforced in the
  orchestrator, and these tests check the enforcement, not the wording.
* A diff stat computed from string lengths reports "no change" for a file that
  was rewritten line for line. So the stats come from a real line diff, and
  the tests below use cases where a length comparison gives the wrong answer.

`folder_manager` is a module-level singleton that also persists the choice to
settings, so every test here saves and restores it. A test that leaves it
pointed at a tmp dir silently changes the project for every test after it.
"""

from __future__ import annotations

import asyncio
import io
import json
from pathlib import Path

import pytest

from tonyagent.core.events import EventBus
from tonyagent.core.modes import MODE_ORDER
from tonyagent.core.session import AgentSession
from tonyagent.headless.server import StdioServer
from tonyagent.providers.base import ChatMessage

MUTATING = {"write_file", "edit_file", "delete_file", "execute_command"}


@pytest.fixture
def project(tmp_path):
    """Point the folder manager at a tmp dir for the duration of one test."""
    from tonyagent.folder import folder_manager

    previous = folder_manager.current_folder
    folder_manager.set_folder(tmp_path)
    try:
        yield tmp_path
    finally:
        if previous is not None:
            folder_manager.set_folder(previous)


def drive(requests, session=None):
    """Push requests through the stdio server and return parsed frames."""
    session = session or AgentSession(bus=EventBus())
    stdin = io.StringIO("\n".join(json.dumps(r) for r in requests) + "\n")
    stdout = io.StringIO()
    asyncio.run(StdioServer(session, stdin, stdout).serve())
    return [json.loads(line) for line in stdout.getvalue().splitlines() if line.strip()]


def replies_of(frames):
    """Index replies by id. Async handlers reply after the events they cause."""
    return {f["id"]: f["result"] for f in frames if "id" in f}


def tool(name):
    from tonyagent.tools import tool_registry

    found = tool_registry.get(name)
    assert found is not None, f"{name} is not registered"
    return found


def change_of(result):
    """The `file_change` payload, or None if the tool reported no change."""
    for artifact in result.artifacts:
        if artifact.get("type") == "file_change":
            return artifact["data"]
    return None


@pytest.fixture(autouse=True)
def _unrestricted_orchestrator():
    """Keep a mode from one test out of the next.

    The orchestrator is a module-level singleton, exactly like the folder
    manager, and a leaked Plan mode would make an unrelated write test fail
    for reasons that look nothing like the bug.
    """
    from tonyagent.tools import tool_orchestrator

    tool_orchestrator.set_mode(None)
    yield
    tool_orchestrator.set_mode(None)


# --- mode discovery --------------------------------------------------------


def test_mode_list_comes_from_the_core():
    """The UI must not hardcode the modes.

    A mode the frontend cannot see is one nobody can select, and the pills
    would drift from the tool allow-lists they are meant to describe.
    """
    result = drive([{"id": 1, "method": "mode.list"}])[0]["result"]
    assert [m["name"] for m in result["modes"]] == list(MODE_ORDER)
    assert {m["label"] for m in result["modes"]} == {"Build", "Plan", "Mission", "Skills"}
    assert result["mode"] == "build", "a fresh session starts in build"


def test_mode_set_reports_the_mode_actually_in_force():
    frames = drive([
        {"id": 1, "method": "mode.set", "params": {"mode": "plan"}},
        {"id": 2, "method": "state"},
    ])
    replies = replies_of(frames)
    assert replies[1]["mode"] == "plan"
    assert replies[1]["writes"] is False
    assert replies[2]["mode"] == "plan", "state must report the mode too"


def test_an_unknown_mode_falls_back_and_says_so():
    """A stale name from an older UI must not be a rejection.

    The reply has to name Build, not the string that was asked for: echoing
    the request would leave the UI showing a mode that is not in force.
    """
    result = drive([{"id": 1, "method": "mode.set", "params": {"mode": "wat"}}])[0]["result"]
    assert result["mode"] == "build"
    assert result["writes"] is True


# --- mode: the advisory half (schema filtering) ----------------------------


@pytest.mark.parametrize("mode", ["plan", "skills"])
def test_read_only_modes_hide_every_mutating_tool(mode):
    session = AgentSession(bus=EventBus())
    session.set_mode(mode)
    names = {s.name for s in session._tool_schemas()}
    assert {"read_file", "grep", "glob", "list_dir"} <= names
    assert not names & MUTATING


@pytest.mark.parametrize("mode", ["build", "mission"])
def test_writing_modes_keep_every_mutating_tool(mode):
    session = AgentSession(bus=EventBus())
    session.set_mode(mode)
    names = {s.name for s in session._tool_schemas()}
    assert MUTATING <= names


def test_every_registered_tool_is_reachable_in_some_mode():
    """A tool in no mode's allow-list is dead code that still ships.

    The allow-lists are spelled out by hand, so adding a tool and forgetting
    to add it to a mode is easy and completely silent. This is the check.
    """
    from tonyagent.core.modes import MODES
    from tonyagent.tools import ALL_SCHEMAS

    reachable = set().union(*(m.allowed_tools for m in MODES.values()))
    orphans = {s["name"] for s in ALL_SCHEMAS} - reachable
    assert not orphans, f"no mode can call: {sorted(orphans)}"


# --- mode: the guarantee (orchestrator enforcement) ------------------------


def test_the_orchestrator_refuses_a_tool_the_mode_forbids(project):
    """The load-bearing test: a hallucinated call is still refused.

    Filtering the schema only tells the model what it may want. A model that
    asks for `write_file` anyway must hit a wall here -- before argument
    validation, and before any confirmation prompt.
    """
    from tonyagent.tools import ToolCall, tool_orchestrator

    AgentSession(bus=EventBus()).set_mode("plan")
    result = asyncio.run(
        tool_orchestrator.execute_tool_async(
            ToolCall(id="t1", name="write_file",
                     arguments={"path": "nope.txt", "content": "x"})
        )
    )
    assert result.status.value == "error"
    assert "Plan" in (result.error or ""), "the refusal must name the mode"
    # The decisive part. Not "it returned an error" but "nothing happened".
    assert not (project / "nope.txt").exists()


def test_a_forbidden_tool_never_reaches_the_confirmation_prompt(project):
    """Asking the user to approve a mode-forbidden tool would be worse.

    It would present a destructive action as an ordinary yes/no at exactly
    the moment the mode was meant to make it impossible.
    """
    from tonyagent.tools import ToolCall, tool_orchestrator

    asked: list = []
    AgentSession(bus=EventBus()).set_mode("plan")
    tool_orchestrator.set_confirmation_callback(lambda req: asked.append(req))
    try:
        asyncio.run(
            tool_orchestrator.execute_tool_async(
                ToolCall(id="t2", name="delete_file", arguments={"path": "x.txt"})
            )
        )
        assert asked == [], "a mode-forbidden tool must not prompt"
    finally:
        tool_orchestrator.set_confirmation_callback(None)


def test_the_same_call_succeeds_once_the_mode_allows_it(project):
    """Proves the refusal above is the mode, not a broken tool.

    Without this, "write_file was refused" would be equally consistent with
    the tool being broken and the test above passing for the wrong reason.
    """
    from tonyagent.tools import ToolCall, tool_orchestrator

    tool_orchestrator.set_mode(None)  # the Tkinter UI's unrestricted default
    result = asyncio.run(
        tool_orchestrator.execute_tool_async(
            ToolCall(id="t3", name="write_file",
                     arguments={"path": "yes.txt", "content": "ok"})
        )
    )
    assert result.status.value == "success"
    assert (project / "yes.txt").read_text(encoding="utf-8") == "ok"


# --- mode: the system prompt ----------------------------------------------


def test_the_system_prompt_reaches_the_provider_and_is_not_stored():
    """Sent, but never kept in the conversation.

    `session.messages` is what `clear()` empties and what the history tests
    assert on. Baking the system prompt into it would make both of them lie
    about what the user said.
    """

    class Provider:
        model = "test"
        seen: dict = {}

        def validate_credentials(self):
            return True

        def chat_completion(self, messages, tools, tool_choice, stream, **kw):
            Provider.seen = {
                "roles": [m.role_value for m in messages],
                "system": messages[0].content,
                "tools": [t.name for t in tools],
            }

            async def gen():
                from tonyagent.providers.base import ChatCompletionChunk

                yield ChatCompletionChunk(content="ok", finish_reason="stop")

            return gen()

    session = AgentSession(bus=EventBus())
    session.provider = Provider()
    session.set_mode("plan")
    asyncio.run(session.run_turn("how should I do this?"))

    assert Provider.seen["roles"][0] == "system"
    assert "PLAN mode" in Provider.seen["system"]
    assert not (set(Provider.seen["tools"]) & MUTATING)
    assert all(m.role_value != "system" for m in session.messages)


def test_the_prompt_follows_the_mode():
    """Two modes must not send the same instruction."""

    class Provider:
        model = "test"

        def __init__(self):
            self.prompts = []

        def validate_credentials(self):
            return True

        def chat_completion(self, messages, tools, tool_choice, stream, **kw):
            self.prompts.append(messages[0].content)

            async def gen():
                from tonyagent.providers.base import ChatCompletionChunk

                yield ChatCompletionChunk(content="ok", finish_reason="stop")

            return gen()

    session = AgentSession(bus=EventBus())
    session.provider = Provider()
    for mode in ("build", "plan", "mission", "skills"):
        session.set_mode(mode)
        asyncio.run(session.run_turn("go"))
    assert len(set(session.provider.prompts)) == 4, "each mode needs its own prompt"


def test_switching_mode_clears_the_conversation():
    """A prompt from the old mode must not outlive it.

    Otherwise the model reads "you cannot write files" in turn 3 and is still
    trying to obey it after the user has switched to Build.
    """
    session = AgentSession(bus=EventBus())
    session.messages.append(ChatMessage(role="user", content="an earlier turn"))
    session.set_mode("plan")
    assert session.messages == []


# --- diff stats ------------------------------------------------------------


def test_write_to_a_new_file_is_all_additions(project):
    result = asyncio.run(tool("write_file").execute(path="new.py", content="a\nb\nc\n"))
    assert change_of(result) == {"path": "new.py", "added": 3, "removed": 0}


def test_rewriting_a_file_reports_a_real_line_diff(project):
    """The case a length comparison gets wrong.

    The content is rewritten line for line at the same character count, so
    `len(after) - len(before)` is zero and the file would show no badge at
    all despite having changed.
    """
    (project / "f.py").write_text("one\ntwo\nthree\nfour\n", encoding="utf-8")
    result = asyncio.run(
        tool("write_file").execute(path="f.py", content="one\nTWO\nthree\nfour\n")
    )
    assert change_of(result) == {"path": "f.py", "added": 1, "removed": 1}


def test_appending_only_adds(project):
    (project / "f.py").write_text("a\nb\n", encoding="utf-8")
    result = asyncio.run(tool("write_file").execute(path="f.py", content="a\nb\nc\nd\n"))
    assert change_of(result) == {"path": "f.py", "added": 2, "removed": 0}


def test_truncating_only_removes(project):
    (project / "f.py").write_text("a\nb\nc\nd\n", encoding="utf-8")
    result = asyncio.run(tool("write_file").execute(path="f.py", content="a\nb\n"))
    assert change_of(result) == {"path": "f.py", "added": 0, "removed": 2}


def test_edit_file_reports_the_span_it_changed(project):
    (project / "f.py").write_text("keep\nold\nkeep2\n", encoding="utf-8")
    result = asyncio.run(
        tool("edit_file").execute(path="f.py", old_text="old", new_text="new\nadded")
    )
    assert change_of(result) == {"path": "f.py", "added": 2, "removed": 1}
    assert (project / "f.py").read_text(encoding="utf-8") == "keep\nnew\nadded\nkeep2\n"


def test_delete_file_reports_the_lines_it_removed(project):
    (project / "gone.py").write_text("a\nb\nc\n", encoding="utf-8")
    result = asyncio.run(tool("delete_file").execute(path="gone.py"))
    assert change_of(result) == {"path": "gone.py", "added": 0, "removed": 3}


def test_an_identical_rewrite_reports_no_change(project):
    """Writing the same bytes is not an edit.

    The Files tree must not sprout a badge for a no-op, which is the easiest
    way for a diff feature to become noise nobody reads.
    """
    (project / "f.py").write_text("a\nb\n", encoding="utf-8")
    result = asyncio.run(tool("write_file").execute(path="f.py", content="a\nb\n"))
    assert change_of(result) == {"path": "f.py", "added": 0, "removed": 0}


def test_read_only_tools_report_no_change(project):
    """Only mutating tools produce a change.

    A `file_change` from `read_file` would put a phantom badge on every file
    the agent merely looked at.
    """
    (project / "f.py").write_text("hello\n", encoding="utf-8")
    assert change_of(asyncio.run(tool("read_file").execute(path="f.py"))) is None


def test_a_failed_write_reports_no_change(project):
    """A path that escapes the project must not leave a badge behind.

    The stat describes what happened on disk. If nothing happened, there is
    nothing to show, and a badge would be a claim the filesystem contradicts.
    """
    result = asyncio.run(
        tool("write_file").execute(path="../escape.py", content="x")
    )
    assert result.status.value == "error"
    assert change_of(result) is None


def test_the_change_artifact_carries_the_relative_path(project):
    """The tree shows paths relative to the project root.

    An absolute path would render as a full row of `C:\\Users\\...` in a
    425px sidebar.
    """
    result = asyncio.run(tool("write_file").execute(path="src/deep/f.py", content="x\n"))
    assert change_of(result)["path"] == "src/deep/f.py"


# --- tool arguments are not echoed into the log ----------------------------


def test_a_written_file_is_not_echoed_into_the_log(project):
    """The log stream is displayed, so arguments must be summarised.

    `_log` feeds both the core's LOG event -- which the React UI renders in
    its log strip -- and loguru on stderr. Interpolating arguments whole put
    the entire contents of every file the agent wrote on screen, which is the
    same leak Phase 2 closed for API keys: a user who asked the agent to write
    a config holding a credential would see it echoed back.
    """
    from tonyagent.tools import ToolCall, tool_orchestrator

    secret = "sk-ant-should-never-appear-in-the-log-strip"
    lines: list[str] = []
    tool_orchestrator.set_log_callback(lambda message, level: lines.append(message))
    try:
        asyncio.run(
            tool_orchestrator.execute_tool_async(
                ToolCall(id="l1", name="write_file",
                         arguments={"path": "cfg.py", "content": secret})
            )
        )
    finally:
        tool_orchestrator.set_log_callback(None)

    joined = "\n".join(lines)
    assert secret not in joined
    # The useful part survives: which tool, which file.
    assert "write_file" in joined
    assert "cfg.py" in joined


def test_short_arguments_are_still_shown_in_full(project):
    """Summarising must not make the log useless.

    "which file" is the thing that makes a line worth reading, so a path has
    to survive intact.
    """
    from tonyagent.tools import ToolCall, tool_orchestrator

    lines: list[str] = []
    tool_orchestrator.set_log_callback(lambda message, level: lines.append(message))
    try:
        asyncio.run(
            tool_orchestrator.execute_tool_async(
                ToolCall(id="l2", name="write_file",
                         arguments={"path": "short.py", "content": "x"})
            )
        )
    finally:
        tool_orchestrator.set_log_callback(None)

    joined = "\n".join(lines)
    assert "path='short.py'" in joined
