"""Conversation tracks: chat is a conversation, build is the agent acting.

Five pills used to share one row, and Chat was one of them -- which made it
look like a mode among modes. It is not: build/plan/mission/skills are four
ways for the agent to act, chosen per turn, while Chat is a different kind of
conversation with no tools at all. So a conversation records which track it
belongs to, set at creation, and opening one adopts the track's mode.

Three properties are pinned here:

* **The track survives the file.** It is written with the conversation and
  read back from it; a file that predates the field opens as Build, the track
  the five-pill world behaved as.
* **Adoption never clears.** Opening a conversation sets the track's mode on
  a *fresh* session, before the transcript loads. A `mode.set` after the load
  would clear the transcript that was just loaded -- which is why the window
  adopts the reply's mode instead of sending one of its own.
* **A carried chat-only provider is dropped, not fatal.** Opening a
  build-track conversation while `airllm` is bound unbinds it and names it in
  the reply, the same shape `mode.set` answers with. Before tracks this raised
  out of the switch, because a fresh session defaults to Build and the bind
  refused the carried provider.
"""

from __future__ import annotations

import asyncio
import io
import json

from tonyagent.core.conversations import (
    Conversation,
    ConversationStore,
    coerce_track,
)
from tonyagent.core.events import EventBus
from tonyagent.core.session import AgentSession
from tonyagent.headless.server import StdioServer


def _drive(requests, session, store):
    """Requests through a server holding `store`, frames back."""
    stdin = io.StringIO("\n".join(json.dumps(r) for r in requests) + "\n")
    stdout = io.StringIO()
    asyncio.run(StdioServer(session, stdin, stdout, store=store).serve())
    return [json.loads(l) for l in stdout.getvalue().splitlines() if l.strip()]


def _reply(frames, request_id):
    return next(f for f in frames if f.get("id") == request_id)


def _mode_after(session_requests, session, store):
    """The mode in force after `session_requests`, read via `mode.list`."""
    frames = _drive(
        session_requests + [{"id": 99, "method": "mode.list", "params": {}}],
        session,
        store,
    )
    return _reply(frames, 99)["result"]["mode"]


# --- the field ---------------------------------------------------------------


def test_a_track_survives_the_file(tmp_path):
    store = ConversationStore(tmp_path / "chats")
    stored = store.create(title="Talk", project="", track="chat")

    assert store.load(stored.id).track == "chat"
    assert stored.summary()["track"] == "chat"


def test_a_file_that_predates_tracks_opens_as_build(tmp_path):
    store = ConversationStore(tmp_path / "chats")
    stored = store.create(title="Old", project="")
    raw = json.loads((tmp_path / "chats" / f"{stored.id}.json").read_text())
    del raw["track"]
    (tmp_path / "chats" / f"{stored.id}.json").write_text(json.dumps(raw))

    assert store.load(stored.id).track == "build"


def test_an_unknown_track_coerces_to_build():
    assert coerce_track("mission") == "build"
    assert coerce_track("") == "build"
    assert coerce_track(None) == "build"
    assert coerce_track("chat") == "chat"
    assert Conversation.from_dict({"id": "a" * 32, "track": "CHAT"}).track == "chat"


def test_a_duplicate_keeps_the_track(tmp_path):
    store = ConversationStore(tmp_path / "chats")
    stored = store.create(title="Talk", project="", track="chat")

    clone = store.duplicate(stored.id)

    assert clone.track == "chat"


# --- creating ----------------------------------------------------------------


def test_creating_with_a_track_answers_it_and_sets_its_mode(tmp_path):
    store = ConversationStore(tmp_path / "chats")
    frames = _drive(
        [{"id": 1, "method": "conversations.create", "params": {"track": "chat"}}],
        AgentSession(bus=EventBus()),
        store,
    )

    reply = _reply(frames, 1)
    assert "error" not in reply, reply
    assert reply["result"]["conversation"]["track"] == "chat"
    assert reply["result"]["mode"] == "chat"


def test_creating_with_an_unknown_track_falls_back_to_build(tmp_path):
    store = ConversationStore(tmp_path / "chats")
    frames = _drive(
        [{"id": 1, "method": "conversations.create", "params": {"track": "mission"}}],
        AgentSession(bus=EventBus()),
        store,
    )

    reply = _reply(frames, 1)
    assert "error" not in reply, reply
    assert reply["result"]["conversation"]["track"] == "build"
    assert reply["result"]["mode"] == "build"


def test_an_empty_conversation_is_reused_across_tracks_not_duplicated(tmp_path):
    """One "New chat" row, whatever the toggle does.

    An empty conversation is unclaimed -- no transcript, so taking the
    requested track rewrites nothing a turn could contradict. Minting one
    empty per track instead would leave two identical rows, which is the
    duplication `find_empty` exists to prevent.
    """
    store = ConversationStore(tmp_path / "chats")
    session = AgentSession(bus=EventBus())
    first = _reply(
        _drive(
            [{"id": 1, "method": "conversations.create", "params": {"track": "build"}}],
            session,
            store,
        ),
        1,
    )["result"]["conversation"]
    second = _reply(
        _drive(
            [{"id": 2, "method": "conversations.create", "params": {"track": "chat"}}],
            session,
            store,
        ),
        2,
    )["result"]["conversation"]

    assert second["id"] == first["id"]
    assert second["track"] == "chat"
    assert len(store.list()) == 1


# --- opening -----------------------------------------------------------------


def test_opening_adopts_the_track_without_clearing_the_transcript(tmp_path):
    """The ordering trap, pinned: mode first on a fresh session, then the load.

    A `mode.set` after the switch would clear the transcript that was just
    loaded -- the reply it answers with would describe messages the session no
    longer holds, and the next persist would save the empty session over them.
    """
    store = ConversationStore(tmp_path / "chats")
    stored = store.create(title="Talk", project="", track="chat")
    stored.messages = [{"role": "user", "content": "remember me"}]
    store.save(stored)

    session = AgentSession(bus=EventBus())
    session.set_mode("build")
    frames = _drive(
        [
            {"id": 1, "method": "conversations.switch", "params": {"id": stored.id}},
            {"id": 2, "method": "mode.list", "params": {}},
        ],
        session,
        store,
    )

    switch = _reply(frames, 1)
    assert "error" not in switch, switch
    assert switch["result"]["mode"] == "chat"
    assert [m["content"] for m in switch["result"]["messages"]] == ["remember me"]
    assert _reply(frames, 2)["result"]["mode"] == "chat"


def test_opening_a_build_track_conversation_leaves_chat(tmp_path):
    store = ConversationStore(tmp_path / "chats")
    stored = store.create(title="Work", project="", track="build")

    session = AgentSession(bus=EventBus())
    session.set_mode("chat")
    mode = _mode_after(
        [{"id": 1, "method": "conversations.switch", "params": {"id": stored.id}}],
        session,
        store,
    )

    assert mode == "build"


def test_opening_a_build_track_conversation_drops_a_chat_only_provider(tmp_path):
    """Unbound and named, not raised.

    Before tracks, a fresh session defaulted to Build and the carried bind
    refused the chat-only provider -- so the switch errored over a chat that
    was otherwise fine to open.
    """
    store = ConversationStore(tmp_path / "chats")
    stored = store.create(title="Work", project="", track="build")

    session = AgentSession(bus=EventBus())
    session.set_mode("chat")
    session.bind_provider("airllm")
    frames = _drive(
        [
            {"id": 1, "method": "conversations.switch", "params": {"id": stored.id}},
            {"id": 2, "method": "mode.list", "params": {}},
        ],
        session,
        store,
    )

    switch = _reply(frames, 1)
    assert "error" not in switch, switch
    assert switch["result"]["disconnected_provider"] == "airllm"
    assert _reply(frames, 2)["result"]["mode"] == "build"


def test_opening_a_chat_track_conversation_keeps_a_chat_only_provider(tmp_path):
    store = ConversationStore(tmp_path / "chats")
    stored = store.create(title="Talk", project="", track="chat")

    session = AgentSession(bus=EventBus())
    session.set_mode("chat")
    session.bind_provider("airllm")
    frames = _drive(
        [{"id": 1, "method": "conversations.switch", "params": {"id": stored.id}}],
        session,
        store,
    )

    switch = _reply(frames, 1)
    assert "error" not in switch, switch
    assert switch["result"]["disconnected_provider"] == ""
