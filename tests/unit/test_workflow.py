"""The workflow loop: one parent turn that talks to a child again — Phase 6.

Phase 5 built a child that answers once and finishes. This phase makes the
child's session loop re-entrant: ``send_message`` hands an existing child
another turn on the transcript it already has, and ``subagent_fork`` copies that
transcript into a new child and leaves the original alone. All three verbs go
through one loop (``subagent_tools._drive_child``), which is the point — the
verbs differ in *where the child comes from*, not in how a turn runs.

**Everything here goes through the real entry point.** ``AgentSession.run_turn``
drives the parent, the parent's provider asks for the verbs, and the tools run
exactly as they do in the window. Driving the tools directly (as
``test_subagents.py`` does, deliberately) cannot reach the two properties this
file exists for:

* the parent's *turn* is what makes the child legal — no turn, no parent session
  to continue or copy — so the mode/permission/context plumbing only assembles
  correctly on the real path; and
* the link the nested view draws with. A child's frames carry the id of the
  parent tool call that asked for *that turn* (``Event.parent_call_id``), so a
  follow-up is drawn under the ``send_message`` card and not under the
  ``subagent`` card that created the child. The child's own turn id cannot do
  that: the parent's transcript has never seen it.

The provider is a script, keyed by the last user message in the conversation —
which is how the parent's transcript is told apart from a child's. The parent
authors exactly one user message for the whole turn; a child's is its seed or
the follow-up it was just handed.
"""

from __future__ import annotations

import asyncio
import json

import pytest

import tonyagent.tools  # noqa: F401  -- registers everything
from tonyagent.core.events import EventBus
from tonyagent.core.modes import get_mode, get_permission
from tonyagent.core.task_state import SessionState, current_state, set_current_state
from tonyagent.providers.base import ChatCompletionChunk
from tonyagent.tools.base import ToolResultStatus, tool_registry
from tonyagent.tools.context import use_context
from tonyagent.tools.subagent_tools import (
    MAX_CHILDREN_PER_TURN,
    MAX_CONCURRENT_CHILDREN,
    MAX_SUBAGENT_DEPTH,
    subagent_registry,
)


def tool(name: str):
    found = tool_registry.get(name)
    assert found is not None, f"missing tool {name}"
    return found


@pytest.fixture(autouse=True)
def _clean_subagent_state():
    """No child, and the parent's plan, outlives the test that made it."""
    subagent_registry.restart()
    before = current_state()
    yield
    subagent_registry.restart()
    set_current_state(before)


def _session(provider=None):
    """A session the way the tests build one: no settings writes, no network."""
    from tonyagent.core.session import AgentSession

    session = AgentSession(
        provider_name="openrouter", model="openrouter/auto", bus=EventBus()
    )
    session.provider = provider
    session._mode = get_mode("build")
    session._permission = get_permission("medium")
    # Four assistant rounds for the parent (three verbs and an answer) and two
    # for the child that runs a tool of its own.
    session.max_tool_calls = 12
    return session


#: The parent's one user message, and the child's three.
PARENT = "delegate the work"
CHILD = "child work"
FOLLOW_UP = "child again"
FORK_TASK = "child fork"


def _call(call_id: str, name: str, arguments: dict) -> ChatCompletionChunk:
    return _batch((call_id, name, arguments))


def _batch(*calls: tuple[str, str, dict]) -> ChatCompletionChunk:
    """One assistant message that declares several calls: the fan-out shape.

    **This is the whole fan-out mechanism.** There is no "run these in
    parallel" verb and no orchestration tool: the session already executes a
    batch of independent calls concurrently (``AgentSession._execute_batch``),
    so a model that declares three ``subagent`` calls in one message gets three
    children running at once. What this phase added is the bound on that.
    """
    return ChatCompletionChunk(
        tool_calls=[
            {
                "id": call_id,
                "function": {"name": name, "arguments": json.dumps(arguments)},
            }
            for call_id, name, arguments in calls
        ],
        finish_reason="tool_calls",
    )


def _text(content: str) -> ChatCompletionChunk:
    return ChatCompletionChunk(content=content, finish_reason="stop")


class ScriptedProvider:
    """One provider for several conversations, told apart by their last user turn.

    The child shares the parent's provider *object* (``SubagentRegistry.spawn``
    works that way on purpose, so there is one HTTP client and one
    reasoning-spec lookup per process), so a single stub has to answer for all of
    them. The discriminator is the last ``user`` message: this is the only field
    that differs between the parent's transcript and a child's, and it is what
    makes the parent's scripted sequence independent of the children's.

    A key with no steps left answers with a text naming the key, so a script that
    runs short shows up as a confusing answer in the transcript rather than as a
    ``StopIteration`` from the stub.
    """

    model = "stub-model"

    def __init__(self, scripts: dict[str, list], child_delay: float = 0.0) -> None:
        self.scripts = {key: list(steps) for key, steps in scripts.items()}
        #: Every conversation this stub was asked about, in order.
        self.asked: list[str] = []
        #: Seconds each *child* stream holds before yielding, so overlap is
        #: measurable. The parent's own passes are never delayed: a parent pass
        #: happens between batches, with no child running.
        self.child_delay = child_delay
        self.streaming: dict[str, int] = {}
        #: The most child streams that were open at the same moment. This is the
        #: only honest evidence of concurrency -- counting completed turns
        #: cannot tell four-at-once from four-in-a-row.
        self.peak_children = 0

    def estimate_tokens(self, messages) -> int:
        return 1

    def _key(self, messages) -> str:
        for message in reversed(messages or []):
            if message.role_value == "user":
                return message.content
        return ""

    async def chat_completion(self, messages=None, tools=None, tool_choice=None,
                              stream=False, **kw):
        key = self._key(messages)
        self.asked.append(key)
        steps = self.scripts.get(key)
        step = steps.pop(0) if steps else _text(f"no script for {key!r}")
        delay = self.child_delay if key != PARENT else 0.0

        async def gen():
            if delay:
                self.streaming[key] = self.streaming.get(key, 0) + 1
                self.peak_children = max(
                    self.peak_children, sum(self.streaming.values())
                )
                try:
                    await asyncio.sleep(delay)
                finally:
                    self.streaming[key] -= 1
            yield step

        return gen()


class ExplodingFollowUpProvider(ScriptedProvider):
    """The scripted provider, except one conversation dies mid-stream."""

    def __init__(self, scripts: dict[str, list], bombs: str) -> None:
        super().__init__(scripts)
        self.bombs = bombs

    async def chat_completion(self, messages=None, tools=None, tool_choice=None,
                              stream=False, **kw):
        if self._key(messages) == self.bombs:

            async def gen():
                raise RuntimeError("provider exploded")
                yield _text("never")

            return gen()
        return await super().chat_completion(messages=messages, tools=tools, **kw)


def _send_and_fork_provider() -> ScriptedProvider:
    """The parent asks for all three verbs, in order, then answers."""
    return ScriptedProvider(
        {
            PARENT: [
                _call("sub-1", "subagent", {"task": CHILD, "name": "probe"}),
                _call(
                    "msg-1",
                    "send_message",
                    {"name": "probe", "message": FOLLOW_UP},
                ),
                _call(
                    "fork-1",
                    "subagent_fork",
                    {"name": "probe", "task": FORK_TASK, "new_name": "copy"},
                ),
                _text("parent answer"),
            ],
            # The child runs a tool of its own, so its frames carry the thing the
            # nested view exists to draw: a child doing work, not just talking.
            CHILD: [_call("kid-1", "list_agents", {}), _text("child one")],
            FOLLOW_UP: [_text("child two")],
            FORK_TASK: [_text("fork answer")],
        }
    )


def _tool_results(session) -> list:
    return [m for m in session.messages if m.role_value == "tool"]


# --- the real turn: send, then fork ---------------------------------------------


async def test_a_parent_turn_sends_to_and_forks_a_child():
    """One turn: spawn, follow up, fork — each read back by the parent's model."""
    bus = EventBus()
    parent = _session(provider=_send_and_fork_provider())
    parent.bus = bus
    frames: list = []
    bus.subscribe(frames.append)

    await parent.run_turn(PARENT)

    # -- all three verbs ran, in the order the parent asked for them ----------
    results = _tool_results(parent)
    assert [m.tool_call_id for m in results] == ["sub-1", "msg-1", "fork-1"]
    assert "child one" in results[0].content
    assert "child two" in results[1].content
    assert "fork answer" in results[2].content

    # -- send_message continued the child rather than making a new one --------
    probe = subagent_registry.get("probe")
    assert [m.content for m in probe.session.messages if m.role_value == "user"] == [
        CHILD,
        FOLLOW_UP,
    ]
    # And its own tool call really ran, which is what the nested view shows.
    assert any(m.role_value == "tool" for m in probe.session.messages)

    # -- the fork copied that conversation, and left the original alone ------
    copy = subagent_registry.get("copy")
    assert copy.forked_from == "probe"
    assert copy.session.messages is not probe.session.messages
    assert copy.session.messages[0] is not probe.session.messages[0]
    assert [m.content for m in copy.session.messages if m.role_value == "user"] == [
        CHILD,
        FOLLOW_UP,
        FORK_TASK,
    ]
    # Nothing the copy did reached back into the child it came from.
    assert all(
        "fork answer" not in (m.content or "") for m in probe.session.messages
    )

    # -- every child frame says which call asked for that turn ---------------
    child_frames = [f for f in frames if f.parent_call_id]
    assert child_frames, "no child frame reached the bus"
    probe_calls = {f.parent_call_id for f in child_frames if f.subagent == "probe"}
    assert probe_calls == {"sub-1", "msg-1"}, (
        "a follow-up turn was drawn under the wrong card: "
        f"{sorted(probe_calls)}"
    )
    assert {
        f.parent_call_id for f in child_frames if f.subagent == "copy"
    } == {"fork-1"}
    # The parent's own frames stay unattributed, or the window would nest the
    # parent's turn inside its own tool card.
    parent_turn = frames[0].turn_id
    assert all(f.turn_id == parent_turn for f in frames if not f.parent_call_id)
    assert all(not f.parent_call_id for f in frames if f.turn_id == parent_turn)

    # Two turns of one child are two turns, not one: the follow-up runs on its
    # own uuid, so the window appends it to its own message under its own card.
    first = {f.turn_id for f in child_frames if f.parent_call_id == "sub-1"}
    second = {f.turn_id for f in child_frames if f.parent_call_id == "msg-1"}
    assert len(first) == 1 and len(second) == 1
    assert not (first & second), "the follow-up reused the first turn's id"
    assert not (first & {parent_turn}) and not (second & {parent_turn})

    # And the parent's transcript never took the children's words.
    assert all(
        "child one" not in (m.content or "")
        for m in parent.messages
        if m.role_value == "assistant"
    )

    # -- the registry names the fork, which is where a reader looks ----------
    listing = await tool("list_agents").execute()
    assert "probe" in listing.output
    assert "forked from probe" in listing.output


async def test_a_forked_child_already_has_the_work_it_inherited():
    """The point of a fork: the copy starts from what was read, not from a brief.

    Asserted through the copy's own answer, not through its message list — the
    message-list check above proves the *copy*; this proves the copy was handed
    a task it could answer *from that context*, which is the only thing a caller
    can observe.
    """
    parent = _session(provider=_send_and_fork_provider())
    await parent.run_turn(PARENT)

    copy = subagent_registry.get("copy")
    # The copy ran its own turn on the copied transcript plus the new task.
    assert copy.session.messages[-1].role_value == "assistant"
    assert "fork answer" in copy.session.messages[-1].content
    # The tool result the parent read is the copy's answer, and names the child.
    results = _tool_results(parent)
    assert "subagent copy:" in results[2].content


# --- the shared loop: a follow-up fails the way a first turn does ----------------


async def test_a_follow_up_failure_reads_like_a_first_turn_failure():
    """``_drive_child`` is one loop, so a broken follow-up fails the same way.

    This is the assertion that would catch the loop being forked per verb rather
    than shared: a follow-up whose provider dies has to come back as an ERROR
    ToolResult the model can act on — never as an exception the orchestrator
    paraphrases into nothing diagnostic.
    """
    provider = ExplodingFollowUpProvider(
        {
            PARENT: [
                _call("sub-1", "subagent", {"task": CHILD, "name": "probe"}),
                _call(
                    "msg-1",
                    "send_message",
                    {"name": "probe", "message": FOLLOW_UP},
                ),
                _text("parent answer"),
            ],
            CHILD: [_text("child one")],
        },
        bombs=FOLLOW_UP,
    )
    parent = _session(provider=provider)

    await parent.run_turn(PARENT)

    results = _tool_results(parent)
    assert len(results) == 2, f"the parent's turn did not finish: {results}"
    failed = json.loads(results[1].content)
    assert failed["status"] == "error"
    assert "no answer" in failed["error"]
    # The child is finished, not left "running" and blocking the next verb.
    assert subagent_registry.snapshot("probe").finished
    assert not subagent_registry.snapshot("probe").running
    # And the parent still answered: a child's death is a tool result, not the
    # end of the turn that asked for it.
    assert "parent answer" in parent.messages[-1].content


# --- fail-closed: the two refusals the new verbs owe a reader --------------------


async def test_send_message_names_a_child_it_does_not_have():
    """An unknown name is *named back*, with the ones that exist."""
    parent = _session(provider=ScriptedProvider({}))

    with use_context(session=parent):
        result = await tool("send_message").execute(name="ghost", message="hi")

    assert result.status is ToolResultStatus.ERROR
    assert "no subagent named" in result.error
    assert "'ghost'" in result.error


async def test_a_fork_refuses_a_source_that_is_still_writing():
    """A copy of a half-written conversation is a copy of a half-finished thought."""
    parent = _session(provider=ScriptedProvider({}))
    handle = subagent_registry.spawn(parent, seed="first", name_hint="first")
    handle.task = asyncio.ensure_future(asyncio.sleep(30))
    try:
        with use_context(session=parent):
            result = await tool("subagent_fork").execute(
                name="first", task="copy it"
            )
        assert result.status is ToolResultStatus.ERROR
        assert "still running" in result.error
    finally:
        handle.task.cancel()


async def test_the_plan_is_not_published_by_a_child_running_inside_a_parent_turn():
    """The isolation test, restated at the workflow level.

    Phase 5 closed the hijack where building a child published its (empty) plan
    into the process-global the parent's prompt reads. A re-entrant loop runs
    more turns per child and more children per turn, which is more chances to
    re-open it — so the invariant is asserted here too, against a real turn.
    """
    parent_state = SessionState()
    set_current_state(parent_state)

    parent = _session(provider=_send_and_fork_provider())
    await parent.run_turn(PARENT)

    assert current_state() is parent_state


# --- fan-out: several children inside one turn ---------------------------------


def _fan_out_provider(delay: float = 0.0) -> ScriptedProvider:
    """A parent that fans out twice: three fresh children, then a mix.

    Pass one declares three ``subagent`` calls in *one* assistant message — the
    batch shape that makes them concurrent. Pass two mixes the other two verbs:
    a follow-up to the child that already answered, and a fork of another. Pass
    three answers.
    """
    return ScriptedProvider(
        {
            PARENT: [
                _batch(
                    ("sub-a", "subagent", {"task": "task a", "name": "alpha"}),
                    ("sub-b", "subagent", {"task": "task b", "name": "beta"}),
                    ("sub-c", "subagent", {"task": "task c", "name": "gamma"}),
                ),
                _batch(
                    ("msg-a", "send_message", {"name": "alpha", "message": "more a"}),
                    (
                        "fork-b",
                        "subagent_fork",
                        {"name": "beta", "task": "fork b", "new_name": "beta-copy"},
                    ),
                ),
                _text("parent answer"),
            ],
            "task a": [_text("answer a")],
            "task b": [_text("answer b")],
            "task c": [_text("answer c")],
            "more a": [_text("answer a2")],
            "fork b": [_text("answer fork")],
        },
        child_delay=delay,
    )


async def test_a_batch_of_children_runs_together_and_each_answers_its_own_call():
    """Fan-out, end to end: three at once, then a follow-up and a fork."""
    provider = _fan_out_provider(delay=0.05)
    bus = EventBus()
    parent = _session(provider=provider)
    parent.bus = bus
    frames: list = []
    bus.subscribe(frames.append)

    await parent.run_turn(PARENT)

    # -- real overlap, and never past the bound -----------------------------
    assert provider.peak_children > 1, (
        "the children never overlapped, so this proves nothing about fan-out"
    )
    assert provider.peak_children <= MAX_CONCURRENT_CHILDREN, (
        f"{provider.peak_children} children streamed at once, past the bound"
    )

    # -- one result per declared call, in the order the model declared them --
    results = _tool_results(parent)
    assert [m.tool_call_id for m in results] == [
        "sub-a",
        "sub-b",
        "sub-c",
        "msg-a",
        "fork-b",
    ]
    payloads = [json.loads(m.content) for m in results]
    assert [p["status"] for p in payloads] == ["success"] * 5, payloads
    # Concurrent execution must not scramble which answer belongs to which
    # call: this is the assertion that would catch a gather that zipped results
    # as they completed.
    assert [p["output"] for p in payloads] == [
        "answer a",
        "answer b",
        "answer c",
        "answer a2",
        "answer fork",
    ]

    # -- each child's frames land under its own card ------------------------
    child_frames = [f for f in frames if f.parent_call_id]
    by_child: dict[str, set[str]] = {}
    for frame in child_frames:
        by_child.setdefault(frame.subagent, set()).add(frame.parent_call_id)
    assert by_child == {
        "alpha": {"sub-a", "msg-a"},
        "beta": {"sub-b"},
        "gamma": {"sub-c"},
        "beta-copy": {"fork-b"},
    }, by_child

    # Five child turns over four children, each on its own turn id, none of
    # them the parent's -- which is what keeps four concurrent children from
    # ever being mistaken for the parent's own message.
    child_turns = {f.turn_id for f in child_frames}
    parent_turn = frames[0].turn_id
    assert len(child_turns) == 5, f"expected one turn id per child turn: {child_turns}"
    assert parent_turn not in child_turns
    assert all(not f.parent_call_id for f in frames if f.turn_id == parent_turn)


async def test_the_concurrency_bound_queues_instead_of_refusing():
    """Six children, four streams at once, six answers.

    A queue, not a cap: the fifth and sixth child still run and still answer, so
    a model that asks for six gets six and never has to guess the limit. What
    the bound limits is how many streams the provider sees at once.
    """
    count = MAX_CONCURRENT_CHILDREN + 2
    calls = tuple(
        (f"sub-{i}", "subagent", {"task": f"task {i}", "name": f"kid{i}"})
        for i in range(count)
    )
    provider = ScriptedProvider(
        {
            PARENT: [_batch(*calls), _text("parent answer")],
            **{f"task {i}": [_text(f"answer {i}")] for i in range(count)},
        },
        child_delay=0.05,
    )
    parent = _session(provider=provider)

    await parent.run_turn(PARENT)

    assert provider.peak_children == MAX_CONCURRENT_CHILDREN, (
        f"peak overlap was {provider.peak_children}; expected exactly "
        f"{MAX_CONCURRENT_CHILDREN} -- fewer means the bound is not the queue, "
        "more means there is no bound"
    )
    results = _tool_results(parent)
    assert len(results) == count, "a queued child was dropped rather than run"
    assert [json.loads(m.content)["output"] for m in results] == [
        f"answer {i}" for i in range(count)
    ]


async def test_with_no_budget_the_per_turn_child_cap_still_bounds_the_turn():
    """The budget decision, proven end to end.

    ``max_tool_calls = 0`` means "no limit" — a real setting the user can pick —
    so the parent's own tool count bounds nothing at all. ``MAX_CHILDREN_PER_TURN``
    is what does, and this is the shape that shows why it has to exist: without
    it, one assistant message could spawn as many children as it liked and the
    queue would work through them forever.
    """
    count = MAX_CHILDREN_PER_TURN + 1
    calls = tuple(
        (f"sub-{i}", "subagent", {"task": f"task {i}", "name": f"kid{i}"})
        for i in range(count)
    )
    provider = ScriptedProvider(
        {
            PARENT: [_batch(*calls), _text("parent answer")],
            **{f"task {i}": [_text(f"answer {i}")] for i in range(count)},
        }
    )
    parent = _session(provider=provider)
    parent.max_tool_calls = 0  # "no limit": the parent's own bound is off.

    await parent.run_turn(PARENT)

    payloads = [json.loads(m.content) for m in _tool_results(parent)]
    assert len(payloads) == count, "the parent's turn did not declare every call"
    successes = [p for p in payloads if p["status"] == "success"]
    failures = [p for p in payloads if p["status"] == "error"]
    assert len(successes) == MAX_CHILDREN_PER_TURN, (
        f"{len(successes)} children ran under a cap of {MAX_CHILDREN_PER_TURN}"
    )
    assert len(failures) == 1, failures
    assert f"{MAX_CHILDREN_PER_TURN} subagent turns" in failures[0]["error"]
    assert "send_message" in failures[0]["error"], (
        "the refusal did not say the child can still be used"
    )
    # The refusal is a tool result, not the end of the turn.
    assert "parent answer" in parent.messages[-1].content


def test_the_fan_out_bounds_are_pinned():
    """A tripwire, in the spirit of the tool-count one.

    These three numbers are the entire bound on a fan-out, and all of them are
    module constants rather than settings. Changing any one changes how much a
    single assistant message can spend, so it should be a diff somebody reads --
    the depth one especially, where the cost multiplies rather than adds.
    """
    assert MAX_CONCURRENT_CHILDREN == 4
    assert MAX_CHILDREN_PER_TURN == 8
    assert MAX_SUBAGENT_DEPTH == 1


async def test_a_child_fanning_out_further_is_refused_through_the_real_turn():
    """The one-level rule, end to end — the invariant fan-out had to not break.

    Removing the serial gate would have quietly allowed a child to spawn a
    child, because that gate was the only thing refusing it. Here a real turn
    spawns a child, the child asks for a grandchild, and the grandchild never
    runs. Proven on the parent's own transcript, where the child reads it.
    """
    provider = ScriptedProvider(
        {
            PARENT: [
                _batch(("sub-l1", "subagent", {"task": "level one", "name": "l1"})),
                _text("parent answer"),
            ],
            "level one": [
                _batch(("sub-l2", "subagent", {"task": "level two", "name": "l2"})),
                _text("l1 answer"),
            ],
            "level two": [_text("l2 answer")],
        }
    )
    parent = _session(provider=provider)

    await parent.run_turn(PARENT)

    # The child ran, and answered -- it just could not delegate onwards.
    assert "l1 answer" in json.loads(_tool_results(parent)[0].content)["output"]

    l1 = subagent_registry.get("l1")
    inner = [m for m in l1.session.messages if m.role_value == "tool"]
    assert len(inner) == 1, "the child's own tool result is missing"
    refusal = json.loads(inner[0].content)
    assert refusal["status"] == "error"
    assert "one level deep" in refusal["error"]
    # The grandchild exists and never ran -- no transcript, no provider call.
    assert subagent_registry.get("l2").running() is False
    assert subagent_registry.get("l2").session.messages == []
    assert "level two" not in provider.asked, "the grandchild was actually run"


# --- stopping, which is the other half of running things at once -----------------
#
# The fan-out's own bounds are above. These two are about the turn *ending* --
# the case nobody exercises by hand because it needs five children in flight at
# the moment someone hits Stop.


async def test_stopping_the_parent_stops_every_child_it_started():
    """Stop is a Stop for the whole fan-out, and nothing outlives it.

    One turn can have six child turns in flight. A parent turn that returns
    while its children still think is not stopped: their frames keep arriving
    once the window has drawn the turn as finished, their answers are read by
    nobody, and the queue they were holding is still holding it. The last
    assertion is the one a leak shows up in -- a permit kept by a dead child
    would silently halve the *next* turn's fan-out, which no test above would
    notice because they all start from a clean registry.
    """
    count = MAX_CONCURRENT_CHILDREN + 2
    calls = tuple(
        (f"sub-{i}", "subagent", {"task": f"task {i}", "name": f"kid{i}"})
        for i in range(count)
    )
    script = {f"task {i}": [_text(f"answer {i}")] for i in range(count)}

    provider = ScriptedProvider(
        {PARENT: [_batch(*calls), _text("parent answer")], **script},
        child_delay=5.0,
    )
    parent = _session(provider=provider)

    turn = asyncio.create_task(parent.run_turn(PARENT))
    for _ in range(600):
        if provider.streaming:
            break
        await asyncio.sleep(0.01)
    started = [
        f"kid{i}"
        for i in range(count)
        if subagent_registry.get(f"kid{i}").running()
    ]
    assert started, "no child ever started, so there is nothing to stop"

    parent.cancel()
    await asyncio.wait_for(turn, timeout=5)

    for _ in range(100):
        if not [t for t in asyncio.all_tasks() if t.get_name().startswith("subagent:")]:
            break
        await asyncio.sleep(0.01)
    leftovers = [
        t.get_name() for t in asyncio.all_tasks() if t.get_name().startswith("subagent:")
    ]
    assert leftovers == [], f"child turns outlived the stopped turn: {leftovers}"

    for i in range(count):
        snapshot = subagent_registry.snapshot(f"kid{i}")
        assert snapshot.running is False, f"kid{i} is still running after Stop"
        assert snapshot.cancelled is True, (
            f"kid{i} stopped without being recorded as cancelled, so list_agents "
            "still offers it as a child whose answer is coming"
        )

    fresh = ScriptedProvider(
        {PARENT: [_batch(*calls), _text("parent answer")], **script},
        child_delay=0.1,
    )
    second = _session(provider=fresh)
    # Bounded, so a leaked permit is a failure with a message rather than a test
    # that hangs on the semaphore until the suite's own timeout.
    await asyncio.wait_for(second.run_turn(PARENT), timeout=5)

    assert fresh.peak_children == MAX_CONCURRENT_CHILDREN, (
        f"the next fan-out peaked at {fresh.peak_children}: a child that was "
        f"stopped kept a slot, so {MAX_CONCURRENT_CHILDREN} is no longer the width"
    )


async def test_a_queued_child_can_be_interrupted_before_its_turn_starts():
    """The queue is addressable, and interrupting a waiting child costs nothing.

    With four slots and six children, two are waiting when the fifth is declared.
    ``interrupt_agent`` has to reach a child whose *task* exists but whose turn
    has not begun -- a state the queue created, and one the old serial gate used
    to make impossible. The interrupted child's stream is never opened, which is
    how "it did not run" is measured, and the child behind it in the queue still
    answers, which is how "the queue survived" is measured.
    """
    count = MAX_CONCURRENT_CHILDREN + 2
    calls = tuple(
        (f"sub-{i}", "subagent", {"task": f"task {i}", "name": f"kid{i}"})
        for i in range(count)
    )
    provider = ScriptedProvider(
        {
            PARENT: [_batch(*calls), _text("parent answer")],
            **{f"task {i}": [_text(f"answer {i}")] for i in range(count)},
        },
        child_delay=0.4,
    )
    parent = _session(provider=provider)

    turn = asyncio.create_task(parent.run_turn(PARENT))
    for _ in range(800):
        if len(provider.streaming) >= MAX_CONCURRENT_CHILDREN:
            break
        await asyncio.sleep(0.01)
    assert len(provider.streaming) >= MAX_CONCURRENT_CHILDREN, (
        "the queue never filled, so no child was waiting"
    )

    last = count - 1
    queued = subagent_registry.get(f"kid{last}")
    assert queued.running() and f"task {last}" not in provider.asked, (
        "the last child had already started, so the queue is not what this tests"
    )

    result = await tool("interrupt_agent").execute(name=f"kid{last}")
    assert result.status is ToolResultStatus.SUCCESS, result.error

    await asyncio.wait_for(turn, timeout=10)

    payloads = {m.tool_call_id: json.loads(m.content) for m in _tool_results(parent)}
    interrupted = payloads[f"sub-{last}"]
    assert interrupted["status"] == "error", interrupted
    assert "interrupted" in interrupted["error"], interrupted["error"]
    assert f"task {last}" not in provider.asked, (
        "the interrupted child's turn ran anyway"
    )
    assert subagent_registry.snapshot(f"kid{last}").cancelled is True
    # The child that was waiting behind it still got its turn: an interrupted
    # sibling is not a broken queue.
    assert payloads[f"sub-{last - 1}"]["status"] == "success", payloads[f"sub-{last - 1}"]
