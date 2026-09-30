"""The conversation methods on the wire.

The store itself is covered in ``test_conversations``. What is untested here and
cannot be tested there is the part that made this feature possible at all:
switching conversations replaces the ``AgentSession`` object, and a replacement
that is not fully wired answers requests and emits no events -- a window with a
blank transcript and no error to explain it.
"""

from __future__ import annotations

import asyncio
import io
import json

import pytest

from tonyagent.core.conversations import ConversationStore
from tonyagent.core.events import EventBus, EventType
from tonyagent.core.session import AgentSession
from tonyagent.headless.server import StdioServer

NEWLINE = chr(10)


class _StubProvider:
    model = "stub-model"

    async def chat_completion(self, messages=None, tools=None, tool_choice=None,
                              stream=False, **kw):
        from tonyagent.providers import ChatCompletionChunk

        async def gen():
            yield ChatCompletionChunk(content="ok")
            yield ChatCompletionChunk(finish_reason="stop")

        return gen()

    def estimate_tokens(self, messages):
        return 1


def _session():
    session = AgentSession(bus=EventBus())
    session.provider = _StubProvider()
    session.provider_name = "openrouter"
    session.model = "stub-model"
    return session


def _drive(requests, session=None, store=None, conversation_id=""):
    """Push requests through the server and return parsed frames."""
    session = session or _session()
    stdin = io.StringIO(NEWLINE.join(json.dumps(r) for r in requests) + NEWLINE)
    stdout = io.StringIO()
    server = StdioServer(session, stdin, stdout, store=store,
                         conversation_id=conversation_id)
    asyncio.run(server.serve())
    frames = [json.loads(l) for l in stdout.getvalue().splitlines() if l.strip()]
    return server, frames


def _by_id(frames):
    return {f["id"]: f for f in frames if "id" in f}


@pytest.fixture
def store(tmp_path) -> ConversationStore:
    return ConversationStore(tmp_path / "conversations")


# --- listing ---------------------------------------------------------------
def test_listing_an_empty_store_is_empty_not_an_error(store):
    _, frames = _drive([{"id": 1, "method": "conversations.list"}], store=store)
    assert _by_id(frames)[1]["result"] == {"conversations": []}


def test_listing_without_a_store_is_a_clean_rejection():
    """A build without the store must say so, not fail as an internal error."""
    _, frames = _drive([{"id": 1, "method": "conversations.list"}])
    reply = _by_id(frames)[1]
    assert reply["error"]["code"] == "rejected"
    assert "conversation" in reply["error"]["message"]


def test_a_created_conversation_appears_in_the_list(store):
    _, frames = _drive([
        {"id": 1, "method": "conversations.create"},
        {"id": 2, "method": "conversations.list"},
    ], store=store)
    listed = _by_id(frames)[2]["result"]["conversations"]
    assert len(listed) == 1
    assert listed[0]["title"] == "New chat"


# --- switching -------------------------------------------------------------
def test_switching_keeps_the_provider_bound(store):
    """The failure this guards is the whole point of the feature.

    A replacement session built bare comes up with no provider, so the first
    message after switching would be rejected -- in a chat that was working a
    moment earlier.
    """
    server, frames = _drive([
        {"id": 1, "method": "conversations.create"},
        {"id": 2, "method": "state"},
    ], store=store)
    replies = _by_id(frames)
    assert replies[2]["result"]["bound"] is True
    assert server.session.provider is not None


def test_switching_reloads_the_transcript(store):
    first = store.create(title="Earlier chat")
    first.messages = [
        {"role": "user", "content": "remember this"},
        {"role": "assistant", "content": "remembered"},
    ]
    store.save(first)

    server, frames = _drive([
        {"id": 1, "method": "conversations.switch", "params": {"id": first.id}},
    ], store=store)
    reply = _by_id(frames)[1]["result"]
    assert [m["content"] for m in reply["messages"]] == ["remember this", "remembered"]
    assert len(server.session.messages) == 2


def test_a_switched_session_still_streams_events(store):
    """The silent failure: a new session with no subscription answers but never
    emits, so the transcript stays blank with no error anywhere."""
    store.create(title="target")
    server, _ = _drive([
        {"id": 1, "method": "conversations.switch",
         "params": {"id": store.list()[0].id}},
    ], store=store)

    seen = []
    server.session.bus.subscribe(seen.append)
    server.session.bus.emit(EventType.LOG, {"message": "still wired"})
    assert any(e.type is EventType.LOG for e in seen)


def test_switching_to_a_missing_conversation_is_a_rejection(store):
    _, frames = _drive([
        {"id": 1, "method": "conversations.switch", "params": {"id": "0" * 32}},
    ], store=store)
    assert _by_id(frames)[1]["error"]["code"] == "rejected"


def test_switching_without_an_id_is_a_rejection(store):
    _, frames = _drive([{"id": 1, "method": "conversations.switch"}], store=store)
    assert _by_id(frames)[1]["error"]["code"] == "rejected"


# --- persistence -----------------------------------------------------------
def _server_for(conversation_id: str, store: ConversationStore) -> StdioServer:
    """A server already switched to this conversation.

    Messages must be appended *after* this returns: constructing with a
    ``conversation_id`` replaces the session with one loaded from disk, so
    anything attached to the session passed in beforehand is discarded. That is
    correct behaviour, and it is also an easy way to write a test that passes for
    the wrong reason.
    """
    return StdioServer(_session(), io.StringIO(""), io.StringIO(),
                       store=store, conversation_id=conversation_id)

def test_a_restored_session_is_not_wired_twice(store):
    """Each event must reach the wire once, however the session got there.

    A frontend appends every ``message.delta`` to the text already on screen, so
    a session wired twice does not read as a duplicate frame -- it reads as
    every answer typed twice. That is also why this is silent: nothing errors,
    the transcript just gets worse.

    Restoring at startup is the case that doubled it: loading the conversation
    wires the loaded session, and the constructor then wired ``self.session``
    again -- which by then is that same loaded session.
    """
    conversation_id = store.create(title="target").id
    server = _server_for(conversation_id, store)
    lines = io.StringIO()
    server.stdout = lines
    server.session.bus.emit(EventType.MESSAGE_DELTA, {"text": "x"})
    assert lines.getvalue().count("message.delta") == 1


def test_switching_does_not_accumulate_event_subscriptions(store):
    conversation_id = store.create(title="target").id
    server = _server_for(conversation_id, store)
    for _ in range(5):
        server._load_into_session(conversation_id)
    lines = io.StringIO()
    server.stdout = lines
    server.session.bus.emit(EventType.MESSAGE_DELTA, {"text": "x"})
    assert lines.getvalue().count("message.delta") == 1


def test_replacing_a_session_does_not_leak_onto_the_process_wide_bus(store):
    """`AgentSession` falls back to a shared default bus.

    Subscribing to that from every replacement left a live subscriber behind on
    each switch, and they all kept writing to the server that created them.
    """
    from tonyagent.core.events import bus as default_bus

    before = len(default_bus._subscribers)
    conversation_id = store.create(title="target").id
    server = _server_for(conversation_id, store)
    for _ in range(5):
        server._load_into_session(conversation_id)
    assert len(default_bus._subscribers) == before


def test_a_finished_turn_is_written_to_disk(store):
    """The guarantee the whole feature rests on: the chat survives the window."""
    from tonyagent.providers import ChatMessage

    created = store.create(title="New chat")
    server = _server_for(created.id, store)
    server.session.messages.append(
        ChatMessage(role="user", content="what does this do?")
    )
    server._persist()

    reloaded = store.load(created.id)
    assert reloaded.messages[0]["content"] == "what does this do?"


def test_a_conversation_takes_its_title_from_the_first_message(store):
    from tonyagent.providers import ChatMessage

    created = store.create(title="New chat")
    server = _server_for(created.id, store)
    server.session.messages.append(ChatMessage(role="user", content="Fix the parser bug"))
    server._persist()

    assert store.load(created.id).title == "Fix the parser bug"


def test_a_title_is_not_rewritten_once_it_has_been_read(store):
    """A list that renames itself while you are looking at it is disorienting,
    and a conversation's opening line is the best title it will ever get."""
    from tonyagent.providers import ChatMessage

    created = store.create(title="A title I already read")
    server = _server_for(created.id, store)
    server.session.messages.append(ChatMessage(role="user", content="a later message"))
    server._persist()

    assert store.load(created.id).title == "A title I already read"


def test_nothing_is_written_when_no_conversation_is_open():
    """A window that never said anything should not leave empty conversations
    behind -- that is how a list fills with blank rows nobody can explain."""
    root = io.StringIO()
    StdioServer(_session(), io.StringIO(""), root)._persist()  # no store, no id
    assert root.getvalue() == ""


# --- deleting --------------------------------------------------------------
def test_deleting_removes_it_from_the_list(store):
    created = store.create(title="temporary")
    _, frames = _drive([
        {"id": 1, "method": "conversations.delete", "params": {"id": created.id}},
        {"id": 2, "method": "conversations.list"},
    ], store=store)
    assert _by_id(frames)[1]["result"]["deleted"] is True
    assert _by_id(frames)[2]["result"]["conversations"] == []


def test_deleting_the_open_conversation_clears_the_transcript(store):
    """Otherwise the user is left staring at a chat that no longer exists,
    which reads as a failure rather than as the result they asked for."""
    created = store.create(title="current")
    created.messages = [{"role": "user", "content": "hi"}]
    store.save(created)

    server, _ = _drive([
        {"id": 1, "method": "conversations.delete", "params": {"id": created.id}},
    ], store=store, conversation_id=created.id)

    assert server.session.messages == []
    assert server.conversation_id == ""


def test_deleting_without_an_id_is_a_rejection(store):
    _, frames = _drive([{"id": 1, "method": "conversations.delete"}], store=store)
    assert _by_id(frames)[1]["error"]["code"] == "rejected"


# --- state -----------------------------------------------------------------
def test_state_names_the_open_conversation(store):
    """A reloaded window has to know which row it is showing."""
    created = store.create(title="current")
    _, frames = _drive([{"id": 1, "method": "state"}], store=store,
                       conversation_id=created.id)
    assert _by_id(frames)[1]["result"]["conversation"] == created.id


# --- naming ----------------------------------------------------------------
def test_renaming_reports_the_new_title_so_the_row_can_update(store):
    created = store.create(title="New chat")
    _, frames = _drive([{
        "id": 1,
        "method": "conversations.rename",
        "params": {"id": created.id, "title": "Invoice questions"},
    }], store=store)

    result = _by_id(frames)[1]["result"]
    assert result["conversation"]["title"] == "Invoice questions"
    assert store.load(created.id).title == "Invoice questions"


def test_renaming_to_nothing_is_a_rejection_and_changes_nothing(store):
    """Reported as refused, not quietly filled in with something else."""
    created = store.create(title="Worth keeping")
    _, frames = _drive([{
        "id": 1,
        "method": "conversations.rename",
        "params": {"id": created.id, "title": "   "},
    }], store=store)

    assert _by_id(frames)[1]["error"]["code"] == "rejected"
    assert store.load(created.id).title == "Worth keeping"


def test_renaming_a_conversation_that_is_not_there_is_a_rejection(store):
    _, frames = _drive([{
        "id": 1,
        "method": "conversations.rename",
        "params": {"id": "0" * 32, "title": "ghost"},
    }], store=store)
    assert _by_id(frames)[1]["error"]["code"] == "rejected"


def test_duplicating_reports_the_new_row(store):
    created = store.create(title="Deploy plan")
    created.messages = [{"role": "user", "content": "hello"}]
    store.save(created)

    _, frames = _drive([{
        "id": 1,
        "method": "conversations.duplicate",
        "params": {"id": created.id},
    }], store=store)

    result = _by_id(frames)[1]["result"]
    assert result["conversation"]["id"] != created.id
    assert result["conversation"]["title"] == "Deploy plan (copy)"
    assert result["conversation"]["message_count"] == 1


def test_duplicating_leaves_the_window_on_the_conversation_you_used(store):
    """You right-clicked a row; jumping the window elsewhere is not that."""
    created = store.create(title="current")
    created.messages = [{"role": "user", "content": "hi"}]
    store.save(created)

    server, _ = _drive([{
        "id": 1,
        "method": "conversations.duplicate",
        "params": {"id": created.id},
    }], store=store, conversation_id=created.id)

    assert server.conversation_id == created.id


# --- the rule that keeps a manual name -------------------------------------
def test_a_manual_name_is_not_overwritten_by_the_automatic_one(store):
    """The auto-title fires only while the conversation is still "New chat".

    It is the whole reason a rename is safe to do: without this, the next turn
    would quietly take the name back and the rename would appear to have been
    lost the moment it worked.
    """
    server, _ = _drive([{
        "id": 1,
        "method": "conversations.rename",
        "params": {"id": store.create().id, "title": "KEEP ME"},
    }], store=store, conversation_id=store.most_recent().id)
    from tonyagent.providers import ChatMessage

    server.session.messages = [
        ChatMessage(role="user", content="How do I ship this?")
    ]

    server._persist()
    assert store.load(server.conversation_id).title == "KEEP ME"


def test_the_automatic_name_still_fires_when_nothing_was_chosen(store):
    """The rename must not have disarmed the naming that made titles work."""
    from tonyagent.providers import ChatMessage

    created = store.create()
    server = _drive([], store=store, conversation_id=created.id)[0]
    server.session.messages = [
        ChatMessage(role="user", content="How do I ship this?")
    ]
    server._persist()
    assert store.load(created.id).title == "How do I ship this?"


def test_a_copy_keeps_its_name_through_a_later_turn(store):
    """A copy is "New chat (copy)" -- not the sentinel -- so it is left alone."""
    original = store.create()
    server = _drive([], store=store, conversation_id=original.id)[0]
    clone = store.duplicate(original.id)

    server._persist()
    assert store.load(clone.id).title == "New chat (copy)"