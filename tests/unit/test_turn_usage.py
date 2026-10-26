"""What a turn spent, from the request that measured it to the event the window reads.

Three layers have to agree, and each of them can be wrong in a way that looks
fine from the other two:

* the transport, which is the only place the provider's usage block appears --
  and it appears *after* the frame carrying ``finish_reason``, which is why
  leaving the stream there recorded every request as zero tokens;
* the session, which has to sum the requests a turn made rather than the last
  one, because a turn with four rounds spends four requests;
* and the wire, which must carry nothing at all when nothing was measured.
  ``turn.usage`` with zeros in it would be a measurement nobody made, and the
  window would print ``0 in / 0 out`` for a provider that simply does not
  report tokens.

The tests below are written against those three claims rather than against the
implementation: a chunk shape, a summed turn, and an absent event.
"""

from __future__ import annotations

import json

import httpx
import pytest

from tonyagent.api.client import LLMClient
from tonyagent.core.events import EventBus, EventType
from tonyagent.core.session import AgentSession


def _frame(payload: dict) -> str:
    return "data: " + json.dumps(payload) + "\n\n"


def _client_with(monkeypatch, frames: list[str]) -> LLMClient:
    """An LLMClient whose HTTP layer replays ``frames`` and nothing else."""
    import tonyagent.api.client as client_mod

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": []})
        return httpx.Response(
            200, text="".join(frames), headers={"content-type": "text/event-stream"}
        )

    transport = httpx.MockTransport(handler)
    real = httpx.AsyncClient

    def factory(*a, **kw):
        kw.pop("transport", None)
        return real(*a, transport=transport, **kw)

    monkeypatch.setattr(client_mod.httpx, "AsyncClient", factory)
    return LLMClient(
        provider="openrouter",
        api_key="sk-or-v1-" + "a" * 64,
        model="m",
        base_url="https://example.invalid/api/v1",
        key_prefix="sk-or-v1-",
    )


async def test_usage_that_arrives_after_the_answer_is_still_read(monkeypatch):
    """The frame order every OpenAI-compatible gateway uses.

    ``finish_reason`` ends the answer; the usage block is one frame later. A
    loop that stops at the first one never sees the second, and since every
    request the window makes is streamed, that is every request.
    """
    frames = [
        _frame({"choices": [{"delta": {"content": "hi"}, "finish_reason": None}]}),
        _frame({"choices": [{"delta": {}, "finish_reason": "stop"}]}),
        _frame(
            {
                "choices": [],
                "usage": {
                    "prompt_tokens": 120,
                    "completion_tokens": 30,
                    "completion_tokens_details": {"reasoning_tokens": 8},
                    "cost": 0.0042,
                },
            }
        ),
        "data: [DONE]\n\n",
    ]
    client = _client_with(monkeypatch, frames)

    text = ""
    async for chunk in client.stream([{"role": "user", "content": "hi"}]):
        text += chunk.content or ""

    # The answer is unchanged: the trailing frame carried no content.
    assert text == "hi"
    usage = client.take_usage()
    assert usage is not None
    assert (usage.input_tokens, usage.output_tokens, usage.reasoning_tokens) == (120, 30, 8)
    assert usage.cost == pytest.approx(0.0042)
    # Taken, not read: a second look must not hand the same numbers out again.
    assert client.take_usage() is None


async def test_a_stream_without_usage_leaves_nothing_to_take(monkeypatch):
    frames = [
        _frame({"choices": [{"delta": {"content": "hi"}, "finish_reason": "stop"}]}),
        "data: [DONE]\n\n",
    ]
    client = _client_with(monkeypatch, frames)
    async for _ in client.stream([{"role": "user", "content": "hi"}]):
        pass
    assert client.take_usage() is None


class _MeteredProvider:
    """A provider that answers with a tool call, then with prose.

    Each pass reports usage, so a turn over it spends two requests. The numbers
    differ per pass on purpose: a total that came from one of them is
    distinguishable from a total that came from both.
    """

    def __init__(self) -> None:
        self.rounds = 0
        self._pending = None

    def estimate_tokens(self, messages):
        return 0

    def take_usage(self):
        usage, self._pending = self._pending, None
        return usage

    async def chat_completion(self, messages=None, tools=None, tool_choice=None,
                              stream=False, **kw):
        from tonyagent.api.dialects import Usage
        from tonyagent.providers import ChatCompletionChunk

        self.rounds += 1
        n = self.rounds

        async def gen():
            if n == 1:
                yield ChatCompletionChunk(
                    tool_calls=[{"id": "c1", "function": {"name": "list_files",
                                                          "arguments": "{}"}}],
                    finish_reason="tool_calls",
                )
                self._pending = Usage(100, 10, 4, 0.001)
            else:
                yield ChatCompletionChunk(content="done", finish_reason="stop")
                self._pending = Usage(200, 20, 6, 0.002)

        return gen()


class _SilentProvider(_MeteredProvider):
    """The same turn, from a provider that reports no usage at all."""

    def take_usage(self):
        self._pending = None
        return None


async def _run(monkeypatch, provider) -> list:
    from tonyagent.tools import tool_orchestrator
    from tonyagent.tools.base import ToolResult, ToolResultStatus

    async def fake_async(self, tool_call):
        return ToolResult(status=ToolResultStatus.SUCCESS, output="a.py")

    monkeypatch.setattr(
        tool_orchestrator,
        "execute_tool_async",
        fake_async.__get__(tool_orchestrator, type(tool_orchestrator)),
    )

    bus = EventBus()
    session = AgentSession(bus=bus)
    session.provider = provider
    session.model = "stub"
    seen: list = []
    bus.subscribe(seen.append)
    await session.run_turn("list my files")
    return seen


async def test_a_turn_sums_every_request_it_made(monkeypatch):
    seen = await _run(monkeypatch, _MeteredProvider())

    usage = [e for e in seen if e.type == EventType.TURN_USAGE]
    assert len(usage) == 1, f"expected one usage frame, got {len(usage)}"
    payload = usage[0].payload
    assert payload["input_tokens"] == 300, "the second pass replaced the first"
    assert payload["output_tokens"] == 30
    assert payload["reasoning_tokens"] == 10
    assert payload["cost"] == pytest.approx(0.003)

    # Before the terminal frame: a number that arrived after `turn.finished`
    # would land on a card the window had already reset to Idle.
    order = [e.type for e in seen if e.type in (EventType.TURN_USAGE, EventType.TURN_FINISHED)]
    assert order == [EventType.TURN_USAGE, EventType.TURN_FINISHED]


async def test_a_provider_that_reports_nothing_emits_no_usage(monkeypatch):
    """No event, rather than an event of zeros.

    The window draws `unknown` for a missing event and `0 in / 0 out` for a
    zero, and only one of those is true when the provider said nothing.
    """
    seen = await _run(monkeypatch, _SilentProvider())
    assert [e for e in seen if e.type == EventType.TURN_USAGE] == []


async def test_a_cancelled_turn_still_says_what_it_spent(monkeypatch):
    """A stopped turn paid for the pass it stopped in the middle of."""
    from tonyagent.api.dialects import Usage
    from tonyagent.providers import ChatCompletionChunk

    class _Stops(_MeteredProvider):
        def __init__(self):
            super().__init__()
            self.session = None

        async def chat_completion(self, messages=None, tools=None, tool_choice=None,
                                  stream=False, **kw):
            self._pending = Usage(50, 5, 0, None)

            async def gen():
                yield ChatCompletionChunk(content="partial", finish_reason="stop")

            return gen()

    bus = EventBus()
    session = AgentSession(bus=bus)
    provider = _Stops()
    session.provider = provider
    session.model = "stub"
    seen: list = []
    bus.subscribe(seen.append)

    # Cancel from inside the turn: the first delta is the moment the user
    # presses Stop.
    original = session.emit

    def emit(type_, payload=None, turn_id=None):
        event = original(type_, payload, turn_id)
        if type_ == EventType.MESSAGE_DELTA:
            session.cancel()
        return event

    session.emit = emit
    await session.run_turn("say something")

    usage = [e for e in seen if e.type == EventType.TURN_USAGE]
    assert len(usage) == 1
    assert usage[0].payload["input_tokens"] == 50
    assert usage[0].payload["cost"] is None, "a missing cost must stay missing, not become 0"
