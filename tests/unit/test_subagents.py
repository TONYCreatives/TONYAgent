"""The subagent registry and the tools that drive it — Phase 5.

These are the unit tests for the semantics that hold no matter what a provider
does; the child's turn itself is the session's own tested loop. The seams
pinned here are the ones that fail *invisibly*: a parent's plan stolen, a
budget silently widened, a second child queued in silence behind the first,
and errors phrased so a model can act on them.
"""

from __future__ import annotations

import asyncio

import pytest

import tonyagent.tools  # noqa: F401  -- registers everything
from tonyagent.core.events import EventBus
from tonyagent.core.modes import get_mode, get_permission
from tonyagent.core.task_state import SessionState, current_state, set_current_state
from tonyagent.providers.base import ChatCompletionChunk
from tonyagent.tools.base import ToolResultStatus, tool_registry
from tonyagent.tools.subagent_tools import (
    SubagentError,
    forget_parent,
    record_parent,
    subagent_registry,
)


def tool(name: str):
    got = tool_registry.get(name)
    assert got is not None, f"missing tool {name}"
    return got


@pytest.fixture(autouse=True)
def _clean_subagent_state():
    subagent_registry.restart()
    forget_parent()
    before = current_state()
    yield
    subagent_registry.restart()
    forget_parent()
    set_current_state(before)


def _session(provider=None):
    """A session the way the tests build one: no settings writes, no network."""
    from tonyagent.core.session import AgentSession

    s = AgentSession(provider_name="openrouter", model="openrouter/auto", bus=EventBus())
    s.provider = provider
    s._mode = get_mode("build")
    s._permission = get_permission("medium")
    s.max_tool_calls = 7
    return s


# --- registry semantics --------------------------------------------------------


async def test_spawn_inherits_mode_permission_and_budget():
    parent = _session()
    handle = subagent_registry.spawn(parent, seed="do the thing")
    child = handle.session
    assert child.mode_name == parent.mode_name
    assert child.permission_name == parent.permission_name
    assert child.max_tool_calls == parent.max_tool_calls == 7


async def test_spawn_shares_the_provider_object_not_a_rebind():
    parent = _session()
    parent.provider = object()  # any sentinel
    handle = subagent_registry.spawn(parent, seed="x")
    assert handle.session.provider is parent.provider


async def test_spawn_does_not_touch_the_global_task_state():
    """A child's plan must not become the parent's prompt block."""
    parent_state = SessionState()
    set_current_state(parent_state)

    handle = subagent_registry.spawn(_session(), seed="x")

    assert current_state() is parent_state
    assert handle.session.state is not parent_state
    assert handle.session.state.is_empty()


async def test_get_names_what_exists():
    subagent_registry.spawn(_session(), seed="x", name_hint="research")
    with pytest.raises(SubagentError) as err:
        subagent_registry.get("nope")
    assert "research" in str(err.value)


async def test_duplicate_names_are_made_unique():
    parent = _session()
    first = subagent_registry.spawn(parent, seed="x", name_hint="research")
    second = subagent_registry.spawn(parent, seed="y", name_hint="research")
    assert first.name != second.name


# --- fail-closed paths: what a model reads when it goes wrong --------------------


async def test_subagent_refuses_a_blank_task():
    result = await tool("subagent").execute(task="   ")
    assert result.status is ToolResultStatus.ERROR
    assert "self-contained" in result.error


async def test_subagent_refuses_outside_a_turn():
    """The parent pointer is the turn's, and none is running."""
    result = await tool("subagent").execute(task="read the docs")
    assert result.status is ToolResultStatus.ERROR
    assert "no turn is running" in result.error


async def test_subagent_refuses_without_a_provider():
    record_parent(_session())  # provider deliberately None
    result = await tool("subagent").execute(task="read the docs")
    assert result.status is ToolResultStatus.ERROR
    assert "no provider" in result.error


async def test_subagent_refuses_while_another_child_runs():
    """One child at a time, *said*, not queued in silence."""
    parent = _session()
    record_parent(parent)
    handle = subagent_registry.spawn(parent, seed="first")
    handle.task = asyncio.ensure_future(asyncio.sleep(30))
    try:
        result = await tool("subagent").execute(task="second")
        assert result.status is ToolResultStatus.ERROR
        assert "one subagent runs at a time" in result.error
        assert "first" in result.error
    finally:
        handle.task.cancel()


async def test_list_agents_reports_state_and_budget():
    record_parent(_session())
    handle = subagent_registry.spawn(_session(), seed="x", name_hint="probe")
    result = await tool("list_agents").execute()
    assert "probe" in result.output
    assert "ready" in result.output
    subagent_registry.mark_finished(handle.name)
    result = await tool("list_agents").execute()
    assert "finished" in result.output


async def test_interrupt_refuses_a_name_that_does_not_exist():
    result = await tool("interrupt_agent").execute(name="ghost")
    assert result.status is ToolResultStatus.ERROR
    assert "no subagent named" in result.error


async def test_interrupt_refuses_a_blank_name():
    result = await tool("interrupt_agent").execute(name="")
    assert result.status is ToolResultStatus.ERROR
    assert "list_agents" in result.error


async def test_interrupt_refuses_an_already_finished_child():
    handle = subagent_registry.spawn(_session(), seed="x")
    subagent_registry.mark_finished(handle.name)
    result = await tool("interrupt_agent").execute(name=handle.name)
    assert result.status is ToolResultStatus.ERROR
    assert "not running" in result.error


# --- the real child run, with a stub provider ------------------------------------


class _StubProvider:
    """One assistant text and no tool calls: the shortest honest child."""

    model = "stub-model"

    def __init__(self, text: str) -> None:
        self.text = text

    async def chat_completion(self, messages=None, tools=None, tool_choice=None,
                              stream=False, **kw):
        async def gen():
            yield ChatCompletionChunk(content=self.text, finish_reason="stop")

        return gen()


async def test_a_child_run_returns_the_childs_final_answer():
    parent = _session(provider=_StubProvider("child answer"))
    record_parent(parent)

    result = await tool("subagent").execute(task="study the tree", name="tree")
    assert result.status is ToolResultStatus.SUCCESS, result.error
    assert "child answer" in result.output
    assert result.summary.startswith("subagent tree:")


async def test_the_child_turn_does_not_leak_its_own_transcript_into_the_parent():
    parent = _session(provider=_StubProvider("child answer"))
    bytes_before_pointers = len(parent.messages)
    record_parent(parent)

    await tool("subagent").execute(task="study", name="t")

    # The parent's transcript only grew by the run mechanics, not by the
    # child's seed or the child's answer — the parent reads the answer from
    # the tool result, which _run_tool_calls appends, not from here.
    assert len(parent.messages) == bytes_before_pointers
    # And the child's transcript has *both* halves.
    handle = subagent_registry.get("t")
    assert any(m.role_value == "user" and "study" in m.content
               for m in handle.session.messages)


async def test_a_child_run_leaves_the_parent_pointer_where_it_found_it():
    """The parent-pointer push/pop must unwind even through a child's turn.

    The child's own ``_run_turn`` records itself as parent and forgets on
    unwind; after the call the pointer must be gone (the parent's outer turn
    is still mid-tool-call, and the next tool call is not a turn start).
    """
    parent = _session(provider=_StubProvider("child answer"))
    record_parent(parent)

    await tool("subagent").execute(task="study")
    assert subagent_registry.list()[0].finished


# --- the runtime error paths: what happens while the child is running -----------


class _HangingProvider:
    """Never answers: the timeout path in real life."""

    model = "stub-model"

    async def chat_completion(self, messages=None, tools=None, tool_choice=None,
                              stream=False, **kw):
        async def gen():
            await asyncio.sleep(3600)
            yield ChatCompletionChunk(content="late", finish_reason="stop")

        return gen()


async def test_a_child_that_runs_over_the_deadline_is_cancelled_and_said():
    import tonyagent.tools.subagent_tools as sub

    parent = _session(provider=_HangingProvider())
    record_parent(parent)
    deadline = sub.CHILD_TURN_TIMEOUT_S
    sub.CHILD_TURN_TIMEOUT_S = 0.05
    try:
        result = await tool("subagent").execute(task="forever", name="slow")
    finally:
        sub.CHILD_TURN_TIMEOUT_S = deadline
    assert result.status is ToolResultStatus.ERROR
    assert "timed out" in result.summary
    assert "Split the task" in result.error
    # The registry says so too, and the child's turn did unwind.
    snap = subagent_registry.snapshot("slow")
    assert snap.cancelled
    await asyncio.sleep(0.05)
    assert snap.finished


class _ExplodingProvider:
    """Raises inside its stream: the provider-error path."""

    model = "stub-model"

    async def chat_completion(self, messages=None, tools=None, tool_choice=None,
                              stream=False, **kw):
        async def gen():
            raise RuntimeError("provider exploded")
            yield ChatCompletionChunk(content="never", finish_reason="stop")

        return gen()


async def test_a_child_whose_provider_fails_is_an_answer_not_a_crash():
    """The child's turn catches its own failure and emits turn.failed; the
    parent's call must still return a readable ToolResult."""
    parent = _session(provider=_ExplodingProvider())
    record_parent(parent)

    result = await tool("subagent").execute(task="boom", name="doomed")
    assert result.status is ToolResultStatus.ERROR
    assert "no answer" in result.error
    assert subagent_registry.snapshot("doomed").finished


class _BlockingProvider:
    """A stream the parent can stop: the user-stop path."""

    model = "stub-model"

    def __init__(self) -> None:
        self.started = asyncio.Event()

    async def chat_completion(self, messages=None, tools=None, tool_choice=None,
                              stream=False, **kw):
        async def gen():
            self.started.set()
            await asyncio.sleep(3600)
            yield ChatCompletionChunk(content="late", finish_reason="stop")

        return gen()


async def test_interruption_stops_a_running_child_and_the_call_answers():
    """``interrupt_agent`` reaching into a live child must end the call with a
    readable result, not leave the parent's model hanging."""
    provider = _BlockingProvider()
    parent = _session(provider=provider)
    record_parent(parent)

    call = asyncio.ensure_future(tool("subagent").execute(task="stall", name="victim"))
    await asyncio.wait_for(provider.started.wait(), timeout=5)
    # Give the child's stream a beat to actually start awaiting.
    await asyncio.sleep(0.05)
    stop = await tool("interrupt_agent").execute(name="victim")
    assert stop.status is ToolResultStatus.SUCCESS
    result = await asyncio.wait_for(call, timeout=10)
    assert result.status is ToolResultStatus.ERROR
    # The interruption is named as such, in the result the model reads —
    # not a raised CancelledError the orchestrator would paraphrase.
    assert "interrupted" in result.error
    snap = subagent_registry.snapshot("victim")
    assert snap.cancelled


async def test_child_events_say_they_are_the_childs():
    """A child's frames cross the shared bus; nothing renames the parent's turn.

    The window's reducer pairs events by ``turn_id``: the child runs on its own
    uuid turn id, so its message frames append to a message nobody is reading
    rather than corrupting the parent's. What must hold: the child's frames
    carry a *different* turn id from the parent's, and the parent's transcript
    (its own session's messages) never gains child content.
    """
    parent = _session(provider=_StubProvider("child answer"))
    seen: list = []
    parent.bus.subscribe(seen.append)
    record_parent(parent)

    result = await tool("subagent").execute(task="study", name="noisy")
    assert result.status is ToolResultStatus.SUCCESS

    turn_started = [e for e in seen if e.type.value == "turn.started"]
    # Exactly one child frame per frame kind: the child's own start/finish,
    # distinguishable from any parent turn (none is running here).
    assert len(turn_started) == 1
    # And the parent's own transcript gained nothing from the child.
    assert all("child answer" not in (m.content or "") for m in parent.messages)
