"""Parallel tool execution: what may run at once, and what may not.

A batch of tool calls declared in one assistant message is independent work, and
it used to run strictly one after another -- three ``read`` calls cost three
round trips of wall clock for no reason. They now overlap, with two properties
held fixed:

* the results come back in the order the model *declared* the calls, because the
  tool messages after a ``tool_calls`` array have to line up with it one for one,
  and
* anything that will ask the user a question stays sequential, because two
  confirmation dialogs at once is worse than a slower turn.

``executor == [...].append``-style recording from the budget tests cannot tell
those apart from a serial loop, so these tests measure overlap directly: the
probe counts how many calls were in flight simultaneously, which is the only
honest evidence that concurrency is happening rather than merely being allowed.
"""

from __future__ import annotations

import asyncio
import json
import time

import pytest

from tonyagent.core.events import EventBus, EventType
from tonyagent.core.session import AgentSession
from tonyagent.providers import ChatCompletionChunk
from tonyagent.tools import tool_orchestrator
from tonyagent.tools.base import ToolResult, ToolResultStatus


def _call(name: str, call_id: str, arguments: str = "{}") -> dict:
    return {"id": call_id, "function": {"name": name, "arguments": arguments}}


def _provider_returning(batches):
    """A provider that walks `batches`, one list of tool calls per pass."""

    class _Provider:
        def __init__(self):
            self.passes = 0

        def estimate_tokens(self, messages):
            return 42

        async def chat_completion(self, messages=None, tools=None, tool_choice=None,
                                  stream=False, **kw):
            index = min(self.passes, len(batches) - 1)
            self.passes += 1
            calls = batches[index]

            async def gen():
                if not calls:
                    yield ChatCompletionChunk(content="all done", finish_reason="stop")
                    return
                yield ChatCompletionChunk(tool_calls=calls, finish_reason="tool_calls")

            return gen()

    return _Provider()


def _session(batches, max_tool_calls: int = 10) -> AgentSession:
    session = AgentSession(bus=EventBus())
    session.provider = _provider_returning(batches)
    session.model = "stub"
    session.max_tool_calls = max_tool_calls
    return session


class _Probe:
    """Records overlap and ordering, and can fail or hang on demand."""

    def __init__(self, delays: dict[str, float] | None = None,
                 raises: set[str] | None = None) -> None:
        self.delays = delays or {}
        self.raises = raises or set()
        self.in_flight = 0
        self.peak = 0
        self.started: list[str] = []
        self.finished: list[str] = []
        self.cancelled: list[str] = []

    async def execute(self, call) -> ToolResult:
        self.started.append(call.name)
        self.in_flight += 1
        self.peak = max(self.peak, self.in_flight)
        try:
            await asyncio.sleep(self.delays.get(call.name, 0))
            if call.name in self.raises:
                raise RuntimeError(f"{call.name} exploded")
        except asyncio.CancelledError:
            self.cancelled.append(call.name)
            raise
        finally:
            self.in_flight -= 1
        self.finished.append(call.name)
        return ToolResult(status=ToolResultStatus.SUCCESS, output=f"ran {call.name}")


@pytest.fixture
def probe(monkeypatch):
    def _install(**kwargs) -> _Probe:
        p = _Probe(**kwargs)
        monkeypatch.setattr(tool_orchestrator, "execute_tool_async", p.execute)
        return p

    return _install


def _tool_messages(session) -> list:
    return [m for m in session.messages if m.role.value == "tool"]


# --- the concurrency itself -------------------------------------------------


async def test_independent_calls_overlap(probe):
    """The point of the change: three calls, one round trip of wall clock."""
    p = probe(delays={"a": 0.05, "b": 0.05, "c": 0.05})
    session = _session([[_call("a", "c1"), _call("b", "c2"), _call("c", "c3")], []])

    start = time.monotonic()
    await session.run_turn("go")
    elapsed = time.monotonic() - start

    assert p.peak == 3, f"calls did not overlap: peak in flight was {p.peak}"
    assert elapsed < 0.15, (
        f"the batch took {elapsed:.3f}s, which is the serial cost -- "
        "the calls were not actually concurrent"
    )
    assert p.finished == ["a", "b", "c"]


async def test_a_single_call_is_not_wrapped_in_a_task(probe):
    """A gather of one is all cost and no concurrency, so it runs in line."""
    p = probe()
    session = _session([[_call("only", "c1")], []])
    await session.run_turn("go")
    assert p.started == ["only"]
    assert p.peak == 1


# --- what must stay ordered -------------------------------------------------


async def test_results_are_ordered_as_the_model_declared_them(probe):
    """Completion order must not become message order.

    The first call is made the *slowest*, so a batch that appended its results as
    they arrived would put `b` and `c` ahead of `a` and pair every tool message
    with the wrong request.
    """
    probe(delays={"a": 0.06, "b": 0.0, "c": 0.0})
    session = _session([[_call("a", "c1"), _call("b", "c2"), _call("c", "c3")], []])

    await session.run_turn("go")

    messages = _tool_messages(session)
    assert [m.tool_call_id for m in messages] == ["c1", "c2", "c3"]
    assert [json.loads(m.content)["output"] for m in messages] == [
        "ran a", "ran b", "ran c"
    ]


async def test_every_call_is_announced_before_any_of_them_runs(probe):
    """The transcript shows the whole batch in flight, not one card at a time."""
    probe(delays={"a": 0.02, "b": 0.02})
    session = _session([[_call("a", "c1"), _call("b", "c2")], []])
    seen = []
    session.bus.subscribe(seen.append)

    await session.run_turn("go")

    kinds = [e.type for e in seen]
    first_completed = kinds.index(EventType.TOOL_COMPLETED)
    started = [i for i, k in enumerate(kinds) if k is EventType.TOOL_STARTED]
    assert len(started) == 2
    assert max(started) < first_completed, (
        "a tool was announced after another had already finished"
    )


# --- what must stay sequential ---------------------------------------------


async def test_a_prompt_keeps_the_whole_batch_sequential(probe, monkeypatch):
    """One call needing an answer serialises the batch it is in.

    Two dialogs at once is worse than a slower turn, and the second would be
    asking about a call the user has not read yet.
    """
    p = probe(delays={"a": 0.02, "b": 0.02, "c": 0.02})
    monkeypatch.setattr(tool_orchestrator, "will_prompt", lambda name, args: name == "b")
    session = _session([[_call("a", "c1"), _call("b", "c2"), _call("c", "c3")], []])

    await session.run_turn("go")

    assert p.peak == 1, f"a prompting batch overlapped: peak was {p.peak}"
    assert p.finished == ["a", "b", "c"]


async def test_will_prompt_is_the_only_thing_consulted(probe, monkeypatch):
    """A batch nobody asks about is not serialised for any other reason."""
    p = probe(delays={"a": 0.02, "b": 0.02})
    monkeypatch.setattr(tool_orchestrator, "will_prompt", lambda name, args: False)
    session = _session([[_call("a", "c1"), _call("b", "c2")], []])

    await session.run_turn("go")

    assert p.peak == 2


# --- failure and cancellation ------------------------------------------------


async def test_a_failing_call_cancels_its_siblings(probe):
    """Nothing may be left running behind a failure.

    The failing call is quick and the sibling is slow, so if the sibling were
    abandoned rather than cancelled the turn would take the sibling's full
    duration and report a tool result nobody collected.
    """
    p = probe(delays={"slow": 5.0, "boom": 0.0}, raises={"boom"})
    session = _session([[_call("slow", "c1"), _call("boom", "c2")], []])

    start = time.monotonic()
    await session.run_turn("go")
    elapsed = time.monotonic() - start

    assert elapsed < 1.0, "the turn waited for a sibling that should have been cancelled"
    assert p.cancelled == ["slow"], f"sibling was not cancelled: {p.cancelled}"
    assert p.in_flight == 0, "a call was still running when the turn ended"


async def test_a_cancelled_batch_does_not_answer_the_calls_it_stopped(probe):
    """A cancelled sibling contributes no tool message.

    The result would be a claim about work that did not finish. The turn is
    already failing at that point, so the wire is not left half-answered by a
    *successful* turn -- the retry re-declares every call.
    """
    probe(delays={"slow": 5.0, "boom": 0.0}, raises={"boom"})
    session = _session([[_call("slow", "c1"), _call("boom", "c2")], []])
    seen = []
    session.bus.subscribe(seen.append)

    await session.run_turn("go")

    assert [e.type for e in seen if e.type is EventType.TURN_FAILED], "turn did not fail"
    assert _tool_messages(session) == [], "a tool message was written for a cancelled call"
