"""The subagent registry and the tools that drive it — Phase 5.

These are the unit tests for the semantics that hold no matter what a provider
does; the child's turn itself is the session's own tested loop. The seams
pinned here are the ones that fail *invisibly*: a parent's plan stolen, a
budget silently widened, a second child queued in silence behind the first,
and errors phrased so a model can act on them.
"""

from __future__ import annotations

import asyncio
import json
from contextlib import contextmanager

import pytest

import tonyagent.tools  # noqa: F401  -- registers everything
from tonyagent.core.events import EventBus
from tonyagent.core.modes import get_mode, get_permission
from tonyagent.core.task_state import SessionState, current_state, set_current_state
from tonyagent.providers.base import ChatCompletionChunk
from tonyagent.tools.base import ToolResultStatus, tool_registry
from tonyagent.tools.context import current as current_context
from tonyagent.tools.context import use_context
from tonyagent.tools.subagent_tools import (
    SubagentError,
    subagent_registry,
)


def tool(name: str):
    got = tool_registry.get(name)
    assert got is not None, f"missing tool {name}"
    return got


@contextmanager
def as_running_turn(session):
    """Publish ``session`` as the running turn, the way a real turn does.

    These tests drive the tools *directly* — there is no ``AgentSession.run_turn``
    around them — so they publish the context themselves. The production publish
    is the same call, made by ``AgentSession._run_turn``, which holds it for the
    life of the turn; the whole path end to end is exercised in the e2e script
    and in ``test_a_childs_frames_say_which_call_spawned_them`` below.

    A ``with`` block, not a sticky publish: ``use_context`` resets its token in
    a ``finally``, and ``ContextVar.reset`` only works in the context that made
    the token, so a publish that outlived the block could not be undone from
    this task. Staying inside the block is both the faithful shape and the one
    with nothing left to leak — the property the process-global this replaced
    did *not* have.
    """
    with use_context(session=session):
        yield session


@pytest.fixture(autouse=True)
def _clean_subagent_state():
    subagent_registry.restart()
    before = current_state()
    yield
    subagent_registry.restart()
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


async def test_restart_cancels_a_running_child_and_drops_the_listing():
    """The host act: one conversation's children do not belong to the next.

    Dropping the listing is the visible half; the half that matters is the
    live one -- a child left running would go on spending its budget for a
    conversation that is no longer open.
    """
    parent = _session()
    done = subagent_registry.spawn(parent, seed="x", name_hint="done")
    subagent_registry.mark_finished(done.name)
    live = subagent_registry.spawn(parent, seed="y", name_hint="live")
    task = asyncio.ensure_future(asyncio.sleep(30))
    subagent_registry.start(live.name, task)
    assert len(subagent_registry.list()) == 2

    subagent_registry.restart()

    assert subagent_registry.list() == []
    with pytest.raises(asyncio.CancelledError):
        # A timeout so a regression fails in a second rather than sleeping
        # until the child would have finished on its own.
        await asyncio.wait_for(task, timeout=1)


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
    with as_running_turn(_session()):  # provider deliberately None
        result = await tool("subagent").execute(task="read the docs")
    assert result.status is ToolResultStatus.ERROR
    assert "no provider" in result.error


async def test_a_second_child_runs_while_the_first_is_still_running():
    """Fan-out replaced the serial gate, and the running child is no obstacle.

    This is the negative of what used to be here, and the flip is the phase:
    the call used to be *refused* and name the child in its way. It now runs,
    and the sibling is none the worse for it.
    """
    parent = _session(provider=_StubProvider("second answer"))
    handle = subagent_registry.spawn(parent, seed="first", name_hint="first")
    handle.task = asyncio.ensure_future(asyncio.sleep(30))
    try:
        with as_running_turn(parent):
            result = await tool("subagent").execute(task="second", name="second")
        assert result.status is ToolResultStatus.SUCCESS, result.error
        assert "second answer" in result.output
        # The one that was already running is still running: this call did not
        # stop it, and it did not wait behind it either.
        assert subagent_registry.snapshot("first").running
    finally:
        handle.task.cancel()


async def test_send_message_refuses_a_child_that_is_already_mid_turn():
    """One *child*, one turn at a time -- the bound fan-out did not remove.

    Two turns of one child at once would interleave into one transcript, which
    is a different thing from two children running side by side.
    """
    parent = _session(provider=_StubProvider("answer"))
    handle = subagent_registry.spawn(parent, seed="x", name_hint="busy")
    handle.task = asyncio.ensure_future(asyncio.sleep(30))
    try:
        with as_running_turn(parent):
            result = await tool("send_message").execute(name="busy", message="again")
        assert result.status is ToolResultStatus.ERROR
        assert "already running a turn" in result.error
        assert "busy" in result.error
    finally:
        handle.task.cancel()


async def test_a_turn_may_start_only_the_cap_worth_of_children(monkeypatch):
    """The per-turn cap, said out loud rather than silently enforced.

    It exists for the parent whose budget is ``0`` -- "no limit" -- where the
    parent's own tool count bounds nothing. It is deliberately *not* a bound on
    what the children spend: each child's budget is still its own.
    """
    import tonyagent.tools.subagent_tools as sub

    monkeypatch.setattr(sub, "MAX_CHILDREN_PER_TURN", 2)
    parent = _session(provider=_StubProvider("answer"))

    with as_running_turn(parent):
        first = await tool("subagent").execute(task="one", name="a")
        second = await tool("subagent").execute(task="two", name="b")
        third = await tool("subagent").execute(task="three", name="c")

    assert first.status is ToolResultStatus.SUCCESS, first.error
    assert second.status is ToolResultStatus.SUCCESS, second.error
    assert third.status is ToolResultStatus.ERROR
    assert "2 subagent turns" in third.error, third.error
    assert "send_message" in third.error, "the refusal did not say how to use it later"
    # The third child exists and never ran. It is addressable and reusable
    # rather than a name the model was handed and then had taken away.
    leftover = subagent_registry.get("c")
    assert leftover.running() is False
    assert leftover.finished is False


async def test_list_agents_reports_state_and_budget():
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

    with as_running_turn(parent):
        result = await tool("subagent").execute(task="study the tree", name="tree")
    assert result.status is ToolResultStatus.SUCCESS, result.error
    assert "child answer" in result.output
    assert result.summary.startswith("subagent tree:")


async def test_the_child_turn_does_not_leak_its_own_transcript_into_the_parent():
    parent = _session(provider=_StubProvider("child answer"))
    bytes_before_pointers = len(parent.messages)

    with as_running_turn(parent):
        await tool("subagent").execute(task="study", name="t")

    # The parent's transcript only grew by the run mechanics, not by the
    # child's seed or the child's answer — the parent reads the answer from
    # the tool result, which _run_tool_calls appends, not from here.
    assert len(parent.messages) == bytes_before_pointers
    # And the child's transcript has *both* halves.
    handle = subagent_registry.get("t")
    assert any(m.role_value == "user" and "study" in m.content
               for m in handle.session.messages)


async def test_a_child_run_leaves_the_turn_context_where_it_found_it():
    """The child's nested context must unwind even through its own turn.

    The child's ``_run_turn`` publishes the *child* as the running session and
    restores the parent's on unwind. After the call the parent is still the
    running session (its outer turn is mid-tool-call), and a tool called
    outside any turn sees none at all — which is the assertion the last line
    makes, by copying the state the next test would start in.
    """
    parent = _session(provider=_StubProvider("child answer"))

    with as_running_turn(parent):
        await tool("subagent").execute(task="study")
        assert subagent_registry.list()[0].finished
        # Still the parent's turn: the child did not leave itself behind.
        assert current_context().session is parent
    # And leaving the block is what restored the empty context for good.
    assert current_context().session is None


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

    deadline = sub.CHILD_TURN_TIMEOUT_S
    sub.CHILD_TURN_TIMEOUT_S = 0.05
    try:
        with as_running_turn(parent):
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

    with as_running_turn(parent):
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

    with as_running_turn(parent):
        call = asyncio.ensure_future(
            tool("subagent").execute(task="stall", name="victim")
        )
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


# --- attribution: the link back to the card -------------------------------------
#
# The window draws a child's work under the card of the call that spawned it,
# and the child's turn id cannot do that on its own -- it is the child's own
# id and the parent's transcript has never seen it. These pin the two fields
# that are the link: the parent call's id and the child's name.


class _ParentAndChildProvider:
    """One provider for two conversations, told apart by the seed.

    The parent asks for ``subagent`` and answers once the result is in; the
    child asks for a real tool (``list_agents``) and then answers. The child's
    tool call is there so its frames carry the thing the nested view exists to
    draw: a child that runs tools of its own.
    """

    model = "stub-model"

    def estimate_tokens(self, messages):
        return 1

    async def chat_completion(self, messages=None, tools=None, tool_choice=None,
                              stream=False, **kw):
        messages = messages or []
        last = messages[-1]
        in_child = any(
            m.role_value == "user" and m.content == "child work" for m in messages
        )

        async def gen():
            if in_child:
                if last.role_value == "tool":
                    yield ChatCompletionChunk(content="child answer", finish_reason="stop")
                else:
                    yield ChatCompletionChunk(
                        tool_calls=[{"id": "kid-1", "function": {
                            "name": "list_agents", "arguments": "{}"}}],
                        finish_reason="tool_calls",
                    )
            elif last.role_value == "tool":
                yield ChatCompletionChunk(content="parent answer", finish_reason="stop")
            else:
                yield ChatCompletionChunk(
                    tool_calls=[{"id": "sub-1", "function": {
                        "name": "subagent",
                        "arguments": json.dumps(
                            {"task": "child work", "name": "probe"}
                        ),
                    }}],
                    finish_reason="tool_calls",
                )

        return gen()


async def test_a_childs_frames_say_which_call_spawned_them():
    """The one link the window has from a child's turn back to a card."""
    bus = EventBus()
    parent = _session()
    parent.bus = bus
    parent.provider = _ParentAndChildProvider()
    frames: list = []
    bus.subscribe(frames.append)

    await parent.run_turn("delegate this")

    parent_turn = frames[0].turn_id
    child_frames = [f for f in frames if f.turn_id != parent_turn]
    assert child_frames, "the child's frames never reached the bus"
    assert all(f.parent_call_id == "sub-1" for f in child_frames)
    assert all(f.subagent == "probe" for f in child_frames)
    # The parent's own frames stay unattributed: otherwise the window would
    # nest the parent's turn inside its own tool card.
    assert all(not f.parent_call_id for f in frames if f.turn_id == parent_turn)
    # And the child really ran a tool, which is what the nested view shows.
    child_tools = [f for f in child_frames if f.type.value == "tool.started"]
    assert [f.payload["name"] for f in child_tools] == ["list_agents"]


async def test_a_child_spawned_outside_a_call_carries_no_link():
    """A direct spawn -- a test, a script -- has no card to belong to."""
    handle = subagent_registry.spawn(_session(), seed="x", name_hint="orphan")
    assert handle.session.subagent_name == "orphan"
    assert handle.session.subagent_call_id == ""


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

    with as_running_turn(parent):
        result = await tool("subagent").execute(task="study", name="noisy")
    assert result.status is ToolResultStatus.SUCCESS

    turn_started = [e for e in seen if e.type.value == "turn.started"]
    # Exactly one child frame per frame kind: the child's own start/finish,
    # distinguishable from any parent turn (none is running here).
    assert len(turn_started) == 1
    # And the parent's own transcript gained nothing from the child.
    assert all("child answer" not in (m.content or "") for m in parent.messages)


async def test_a_child_cannot_spawn_a_child():
    """One level deep, now said out loud instead of falling out of a bug.

    The serial gate this phase removed refused every spawn while a child was
    running -- and a child running its own turn is exactly that -- so nesting
    was refused for a reason that had nothing to do with nesting. The rule is
    its own check with its own words now.
    """
    parent = _session(provider=_StubProvider("x"))
    child = subagent_registry.spawn(parent, seed="level one", name_hint="l1")
    assert child.session.subagent_depth == 1
    assert parent.subagent_depth == 0

    with as_running_turn(child.session):  # the child's own turn
        result = await tool("subagent").execute(task="level two", name="l2")

    assert result.status is ToolResultStatus.ERROR
    assert "one level deep" in result.error
    # Spawned before admission, so it is named and idle rather than missing.
    deeper = subagent_registry.get("l2")
    assert deeper.session.subagent_depth == 2
    assert deeper.running() is False
