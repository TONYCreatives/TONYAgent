"""Reasoning travels in its own channel, all the way to the stored file.

OpenRouter streams a reasoning model's thinking under ``delta.reasoning``,
beside ``delta.content`` rather than inside it. The one mistake this whole
module exists to prevent is folding the two together, because the damage is
not visible at the point it happens:

* the transcript shows the model's scratchpad as though it were the answer, and
* the next request sends that scratchpad back as part of what the user was
  told, so the model reads its own working as the conversation.

So the assertions below are mostly negative. ``content`` must stay clean at
every layer, and the reasoning must survive a save/reopen round trip -- which
is the part that is easy to get right in a test and wrong in the file format.
"""

from __future__ import annotations

import asyncio
import io
import json

import pytest

from tonyagent.api.dialects import Chunk, Completion, Dialect
from tonyagent.core.conversations import ConversationStore
from tonyagent.core.events import Event, EventBus, EventType
from tonyagent.core.session import AgentSession
from tonyagent.headless.server import StdioServer
from tonyagent.providers import ChatCompletionChunk, ChatMessage

NEWLINE = chr(10)

#: A reasoning block as OpenRouter streams it: a text block that grows, then a
#: redacted one. Copied from the shape the docs show rather than invented.
_BLOCK = {"type": "reasoning.text", "text": "First I check the config."}
_BLOCK_TAIL = {"type": "reasoning.text", "text": "First I check the config. Then the path."}
_ENCRYPTED = {"type": "reasoning.encrypted", "data": "gAAAA"}


def _sse(delta: dict, **choice) -> str:
    """One streaming frame, as the provider writes it."""
    body = {"choices": [{"delta": delta, **choice}]}
    return json.dumps(body)


# --- the wire ------------------------------------------------------------


def test_reasoning_is_read_from_its_own_key():
    acc: dict = {}
    chunk = Dialect().parse_stream_event("", _sse({"reasoning": "thinking"}), acc)
    assert chunk.reasoning == "thinking"
    # The load-bearing half: it did NOT arrive as an answer.
    assert chunk.content is None


def test_the_reasoning_content_alias_reads_the_same():
    """OpenRouter carries `reasoning_content` as an alias, and both appear."""
    acc: dict = {}
    chunk = Dialect().parse_stream_event("", _sse({"reasoning_content": "thinking"}), acc)
    assert chunk.reasoning == "thinking"
    assert chunk.content is None


def test_reasoning_details_accumulate_into_one_list():
    """Each chunk repeats the whole list so far, and the last value is complete.

    The array is what goes back on the assistant message; if it were only the
    newest slice, the provider would receive reasoning it cannot match to the
    tool call it is being asked to continue from.
    """
    d = Dialect()
    acc: dict = {}
    first = d.parse_stream_event("", _sse({"reasoning_details": [_BLOCK]}), acc)
    assert first.reasoning_details == [_BLOCK]
    second = d.parse_stream_event("", _sse({"reasoning_details": [_ENCRYPTED]}), acc)
    assert second.reasoning_details == [_BLOCK, _ENCRYPTED]
    # A later plain-text chunk still carries the list rather than dropping it.
    plain = d.parse_stream_event("", _sse({"content": "hi"}), acc)
    assert plain.reasoning_details == [_BLOCK, _ENCRYPTED]


def test_two_unindexed_blocks_are_kept_as_two():
    """Without an index a new block is indistinguishable from a grown one.

    Appending is the only safe reading: guessing that the second is a rewrite
    of the first would silently drop reasoning the model actually produced.
    """
    d = Dialect()
    acc: dict = {}
    d.parse_stream_event("", _sse({"reasoning_details": [_BLOCK]}), acc)
    chunk = d.parse_stream_event("", _sse({"reasoning_details": [_ENCRYPTED]}), acc)
    assert chunk.reasoning_details == [_BLOCK, _ENCRYPTED]


def test_an_indexed_block_replaces_its_earlier_version():
    """The same index is the same block, seen again -- not a second block.

    A streaming provider re-sends a block's growing text under the index it
    first appeared at. Appending it would send two entries for one piece of
    reasoning, which the provider rejects.
    """
    d = Dialect()
    acc: dict = {}
    d.parse_stream_event("", _sse({"reasoning_details": [{"index": 0, **_BLOCK}]}), acc)
    chunk = d.parse_stream_event("", _sse({"reasoning_details": [{"index": 0, **_BLOCK_TAIL}]}), acc)
    assert chunk.reasoning_details == [{"index": 0, **_BLOCK_TAIL}]


def test_indexed_blocks_land_in_their_own_slots():
    d = Dialect()
    acc: dict = {}
    d.parse_stream_event("", _sse({"reasoning_details": [{"index": 1, **_ENCRYPTED}]}), acc)
    chunk = d.parse_stream_event("", _sse({"reasoning_details": [{"index": 0, **_BLOCK}]}), acc)
    # Blocks are kept exactly as sent, `index` key included, because this list
    # is handed back to the provider verbatim and a rewritten block is one it
    # will not match to anything.
    assert chunk.reasoning_details == [{"index": 0, **_BLOCK}, {"index": 1, **_ENCRYPTED}]


def test_no_reasoning_field_when_the_model_thinks_nothing():
    acc: dict = {}
    chunk = Dialect().parse_stream_event("", _sse({"content": "hi"}), acc)
    assert chunk.reasoning is None
    assert chunk.reasoning_details is None


def test_a_non_streaming_reply_keeps_them_apart_too():
    comp = Dialect().parse_completion({"choices": [{"message": {
        "content": "The answer.",
        "reasoning": "The thinking.",
        "reasoning_details": [_BLOCK],
    }}]})
    assert comp.content == "The answer."
    assert comp.reasoning == "The thinking."
    assert comp.reasoning_details == [_BLOCK]


def test_reasoning_tokens_are_separated_from_the_output_count():
    """4200 output tokens could be 4000 of thinking and 200 of prose.

    Collapsing them is how a turn that over-thought looks like a turn that
    wrote at length.
    """
    comp = Dialect().parse_completion({"choices": [{"message": {"content": "hi"}}], "usage": {
        "prompt_tokens": 100,
        "completion_tokens": 4200,
        "completion_tokens_details": {"reasoning_tokens": 4000},
    }})
    assert comp.usage.output_tokens == 4200
    assert comp.usage.reasoning_tokens == 4000
    assert comp.usage.total == 4300


def test_a_reply_with_no_usage_reports_zero_rather_than_failing():
    comp = Dialect().parse_completion({"choices": [{"message": {"content": "hi"}}]})
    assert comp.usage.reasoning_tokens == 0


# --- the message we send back --------------------------------------------


def test_an_assistant_turn_returns_its_reasoning_to_the_provider():
    """This is the tool-call continuity guarantee.

    The second round of a tool-calling turn sends the history again. Without
    `reasoning_details` the provider sees reasoning blocks it produced with no
    matching message and the chain breaks.
    """
    message = ChatMessage(role="assistant", content="Reading it now.",
                          reasoning="I should read the file.",
                          reasoning_details=[_BLOCK])
    wire = message.to_dict()
    assert wire["reasoning"] == "I should read the file."
    assert wire["reasoning_details"] == [_BLOCK]
    assert wire["content"] == "Reading it now."


def test_a_plain_assistant_message_sends_no_reasoning_keys():
    """No thinking means no keys, rather than two empty ones."""
    wire = ChatMessage(role="assistant", content="hi").to_dict()
    assert "reasoning" not in wire
    assert "reasoning_details" not in wire


def test_a_user_turn_never_carries_reasoning():
    """A user did not think anything; sending the keys would be a lie."""
    wire = ChatMessage(role="user", content="hi", reasoning="not mine").to_dict()
    assert "reasoning" not in wire
    assert "reasoning_details" not in wire


def test_a_stored_message_round_trips_through_a_dict():
    original = ChatMessage(role="assistant", content="ok",
                           reasoning="thinking", reasoning_details=[_BLOCK])
    assert ChatMessage.from_dict(original.to_dict()) == original


def test_a_message_saved_before_thinking_existed_still_reads():
    """Old conversations have no such keys, and must open unchanged."""
    restored = ChatMessage.from_dict({"role": "assistant", "content": "hi"})
    assert restored.reasoning is None
    assert restored.reasoning_details is None
    assert restored.content == "hi"


# --- the session ---------------------------------------------------------


class _ReasoningProvider:
    """A provider that thinks, then answers, on the same stream."""

    model = "thinker"

    def __init__(self, deltas, finish_reason="stop"):
        self._deltas = deltas
        self._finish_reason = finish_reason
        #: The message list exactly as it was sent, so a test can assert on
        #: what the second request would carry.
        self.sent: list[list[dict]] = []

    async def chat_completion(self, messages=None, tools=None, tool_choice=None,
                              stream=False, **kw):
        self.sent.append([m.to_dict() for m in messages])

        async def gen():
            for delta in self._deltas:
                yield ChatCompletionChunk(reasoning=delta.get("reasoning"),
                                         content=delta.get("content"),
                                         reasoning_details=delta.get("details"))
            yield ChatCompletionChunk(finish_reason=self._finish_reason)

        return gen()

    def estimate_tokens(self, messages):
        return 1


def _session(provider):
    session = AgentSession(bus=EventBus())
    session.provider = provider
    session.provider_name = "openrouter"
    session.model = "thinker"
    return session


def _collect(session):
    seen: list[Event] = []
    session.bus.subscribe(seen.append)
    return seen


async def _run(session, text="Hello"):
    events = _collect(session)
    await session.run_turn(text)
    return events


def _of_type(events, kind):
    return [e for e in events if e.type is kind]


def test_thinking_streams_on_its_own_events():
    provider = _ReasoningProvider([
        {"reasoning": "Let me "},
        {"reasoning": "think."},
        {"content": "Answer."},
    ])
    session = _session(provider)
    events = asyncio.run(_run(session))

    deltas = _of_type(events, EventType.REASONING_DELTA)
    assert [e.payload["text"] for e in deltas] == ["Let me ", "think."]

    completed = _of_type(events, EventType.REASONING_COMPLETED)
    assert len(completed) == 1
    assert completed[0].payload["text"] == "Let me think."
    assert completed[0].payload.get("truncated") is not True

    # And the answer itself never carried any of it.
    text = "".join(e.payload["text"] for e in _of_type(events, EventType.MESSAGE_DELTA))
    assert text == "Answer."


def test_no_reasoning_events_from_a_model_that_does_not_think():
    """An event type that fires on every turn trains the UI to ignore it."""
    session = _session(_ReasoningProvider([{"content": "Answer."}]))
    events = asyncio.run(_run(session))
    assert _of_type(events, EventType.REASONING_DELTA) == []
    assert _of_type(events, EventType.REASONING_COMPLETED) == []


def test_thinking_never_enters_the_saved_message_content():
    provider = _ReasoningProvider([
        {"reasoning": "secret scratchpad"},
        {"content": "Answer."},
    ])
    session = _session(provider)
    asyncio.run(_run(session))
    assistant = session.messages[-1]
    assert assistant.content == "Answer."
    assert assistant.reasoning == "secret scratchpad"


def test_thinking_is_sent_back_on_the_next_request():
    provider = _ReasoningProvider([
        {"reasoning": "I should look.", "details": [_BLOCK]},
        {"content": "Looking."},
    ])
    session = _session(provider)
    asyncio.run(_run(session))
    asyncio.run(_run(session, "And now?"))

    second = provider.sent[-1]
    assistant = next(m for m in second if m["role"] == "assistant")
    assert assistant["reasoning"] == "I should look."
    assert assistant["reasoning_details"] == [_BLOCK]
    assert assistant["content"] == "Looking."


def test_a_thinking_pass_with_no_answer_is_reported_not_swallowed():
    """The budget trap.

    Reasoning tokens come out of the same allowance as output, so a model can
    think until the allowance is gone and stop at `length` having written
    nothing. The user was billed for all of it, so silence is the worst
    possible answer.
    """
    provider = _ReasoningProvider([{"reasoning": "thinking for a long time"}],
                                  finish_reason="length")
    session = _session(provider)
    events = asyncio.run(_run(session))

    completed = _of_type(events, EventType.REASONING_COMPLETED)
    assert completed[0].payload["truncated"] is True
    assert "budget" in completed[0].payload["notice"]
    # The user is told, rather than left with a turn that appears to have done
    # nothing.
    assert _of_type(events, EventType.ERROR)
    # And no empty answer was written to the history.
    assert not [m for m in session.messages if m.role_value == "assistant"]


def test_a_truncated_answer_that_did_write_something_is_left_alone():
    """`length` mid-answer is normal. Only a total absence is the trap."""
    provider = _ReasoningProvider([
        {"reasoning": "thinking"},
        {"content": "Here is the first half"},
    ], finish_reason="length")
    session = _session(provider)
    events = asyncio.run(_run(session))
    completed = _of_type(events, EventType.REASONING_COMPLETED)
    assert completed[0].payload.get("truncated") is not True
    assert "notice" not in completed[0].payload
    assert _of_type(events, EventType.ERROR) == []
    assert session.messages[-1].content == "Here is the first half"


# --- the stored conversation ---------------------------------------------


def _drive(requests, session, store, conversation_id=""):
    stdin = io.StringIO(NEWLINE.join(json.dumps(r) for r in requests) + NEWLINE)
    stdout = io.StringIO()
    server = StdioServer(session, stdin, stdout, store=store,
                         conversation_id=conversation_id)
    asyncio.run(server.serve())
    return server, [json.loads(l) for l in stdout.getvalue().splitlines() if l.strip()]


def _by_id(frames):
    return {f["id"]: f for f in frames if "id" in f}


@pytest.fixture
def store(tmp_path) -> ConversationStore:
    return ConversationStore(tmp_path / "conversations")


def _converse(store, provider, text="Hi", conversation_id=None):
    """Run one turn to completion against a server holding ``store``.

    Two things this deliberately avoids. The `send` method schedules the turn
    and returns, and the loop is torn down when stdin closes, so the turn would
    be cancelled before it finished and nothing would be persisted. And a
    freshly-created session rebuilds its provider from the registry, which
    throws away the stub this test needs -- so a new conversation is opened
    directly on the store, and the provider is re-attached afterwards whenever
    a real switch replaced the session underneath it.
    """
    if conversation_id is None:
        conversation_id = store.create(title="chat").id
        server, _ = _drive([], _session(provider), store)
        server.conversation_id = conversation_id
    else:
        # The real reopen path, so the restore is what is being tested rather
        # than a hand-built session.
        server, _ = _drive([{"id": 1, "method": "conversations.switch",
                             "params": {"id": conversation_id}}],
                           _session(provider), store)
        server.session.provider = provider
    asyncio.run(server.session.run_turn(text))
    return server


def test_a_turn_persists_its_reasoning_with_the_conversation(store):
    _converse(store, _ReasoningProvider([
        {"reasoning": "thinking", "details": [_BLOCK]},
        {"content": "Answer."},
    ]))
    saved = store.list()[0]
    assistant = next(m for m in saved.messages if m["role"] == "assistant")
    assert assistant["reasoning"] == "thinking"
    assert assistant["reasoning_details"] == [_BLOCK]
    assert assistant["content"] == "Answer."


def test_reopening_a_conversation_restores_its_reasoning(store):
    """The whole point of storing it: the panel can be drawn again.

    A reopened chat that lost its thinking would render a different
    conversation from the one on disk.
    """
    _converse(store, _ReasoningProvider([
        {"reasoning": "thinking", "details": [_BLOCK]},
        {"content": "Answer."},
    ]))
    conversation_id = store.list()[0].id

    # A brand-new server, as after a restart.
    _, frames = _drive([{"id": 1, "method": "conversations.switch",
                         "params": {"id": conversation_id}}],
                       _session(_ReasoningProvider([])), store)
    messages = _by_id(frames)[1]["result"]["messages"]
    assistant = next(m for m in messages if m["role"] == "assistant")
    assert assistant["reasoning"] == "thinking"
    assert assistant["reasoning_details"] == [_BLOCK]


def test_restored_reasoning_reaches_the_next_request(store):
    """Restoring it into the session is not enough if it stops there.

    The point of keeping it is the next tool round, so this asserts the
    restored value is the one that would be sent.
    """
    _converse(store, _ReasoningProvider([
        {"reasoning": "thinking", "details": [_BLOCK]},
        {"content": "Answer."},
    ]))
    conversation_id = store.list()[0].id

    provider2 = _ReasoningProvider([{"content": "Again."}])
    _converse(store, provider2, text="More?", conversation_id=conversation_id)
    assistant = next(m for m in provider2.sent[-1] if m["role"] == "assistant")
    assert assistant["reasoning"] == "thinking"
    assert assistant["reasoning_details"] == [_BLOCK]


def test_a_conversation_saved_before_thinking_existed_still_opens(store):
    """The compatibility case, written the way an older version wrote it."""
    old = store.create(title="Old chat")
    old.messages = [
        {"role": "user", "content": "Hi"},
        {"role": "assistant", "content": "Hello"},
    ]
    store.save(old)

    _, frames = _drive([{"id": 1, "method": "conversations.switch",
                         "params": {"id": old.id}}],
                       _session(_ReasoningProvider([])), store)
    result = _by_id(frames)[1]["result"]
    assert [m["content"] for m in result["messages"]] == ["Hi", "Hello"]


def test_a_stored_tool_call_message_still_restores_its_tool_fields(store):
    """`from_dict` replaced a hand-written field list that dropped `name`.

    Losing a field on the way back in is the same bug as losing reasoning, and
    the same fix closes it.
    """
    saved = store.create(title="Tool chat")
    saved.messages = [{
        "role": "assistant",
        "content": None,
        "tool_calls": [{"id": "c1", "type": "function",
                        "function": {"name": "read_file", "arguments": "{}"}}],
        "reasoning": "I need the file.",
    }, {"role": "tool", "content": "contents", "tool_call_id": "c1"}]
    store.save(saved)

    server, _ = _drive([{"id": 1, "method": "conversations.switch",
                         "params": {"id": saved.id}}],
                       _session(_ReasoningProvider([])), store)
    assistant = server.session.messages[0]
    assert assistant.tool_calls[0]["function"]["name"] == "read_file"
    assert assistant.reasoning == "I need the file."
    assert server.session.messages[1].tool_call_id == "c1"
