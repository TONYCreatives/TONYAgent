"""The conversation store.

The point of these tests is that a chat survives the window closing. Every other
test in the suite runs inside one process with the history in memory, so
nothing here was ever exercised -- which is why the store had to be written
before the list that reads from it.
"""

from __future__ import annotations

import json

import pytest

from tonyagent.core.conversations import (
    Conversation,
    ConversationStore,
    title_from,
)


@pytest.fixture
def store(tmp_path) -> ConversationStore:
    return ConversationStore(tmp_path / "chats")


# --- titles ----------------------------------------------------------------
def test_a_title_is_the_first_thing_said():
    assert title_from("Fix the failing test in session.py") == (
        "Fix the failing test in session.py"
    )


def test_a_multiline_paste_becomes_one_line():
    assert title_from("first line\nsecond line\n\nthird") == "first line second line third"


def test_a_long_first_message_is_cut_on_a_word_boundary():
    title = title_from("word " * 40)
    assert len(title) <= 61  # 60 characters plus the ellipsis
    assert title.endswith("…")
    assert not title[:-1].endswith(" "), "a title must not end mid-whitespace"


def test_an_empty_message_still_gets_a_title():
    assert title_from("") == "New chat"
    assert title_from("   \n  ") == "New chat"


# --- round trips -----------------------------------------------------------
def test_a_saved_conversation_comes_back(store):
    original = store.create(title="Fix the parser", project="C:/work/repo")
    original.messages = [
        {"role": "user", "content": "fix it"},
        {"role": "assistant", "content": "done"},
    ]
    store.save(original)

    reloaded = store.load(original.id)
    assert reloaded is not None
    assert reloaded.title == "Fix the parser"
    assert reloaded.project == "C:/work/repo"
    assert len(reloaded.messages) == 2
    assert reloaded.messages[0]["content"] == "fix it"


def test_a_conversation_survives_a_new_store_over_the_same_directory(tmp_path):
    """The actual guarantee: the data outlives the object that wrote it.

    A fresh store over the same path is what a restart looks like. Asserting
    within one store instance would pass even if nothing reached disk.
    """
    root = tmp_path / "chats"
    first = ConversationStore(root)
    saved = first.create(title="Persisted")
    saved.messages = [{"role": "user", "content": "remember me"}]
    first.save(saved)

    second = ConversationStore(root)
    reloaded = second.load(saved.id)
    assert reloaded is not None
    assert reloaded.messages == [{"role": "user", "content": "remember me"}]


def test_each_conversation_gets_its_own_id(store):
    assert store.create().id != store.create().id


def test_loading_an_unknown_id_returns_nothing(store):
    assert store.load("0" * 32) is None


# --- listing ---------------------------------------------------------------
def test_the_list_is_newest_first(store):
    first = store.create(title="oldest")
    second = store.create(title="middle")
    third = store.create(title="newest")
    # Touch them in a known order rather than sleeping: a test that waits for a
    # clock is a test that fails on a loaded machine.
    for index, conversation in enumerate((first, second, third)):
        conversation.updated_at = 1000 + index
        store.save(conversation)

    assert [c.title for c in store.list()] == ["newest", "middle", "oldest"]


def test_a_list_row_does_not_carry_the_transcript(store):
    """The transcript is the expensive part and no row renders it.

    Shipping it would mean transferring every conversation's full history on
    each launch in order to draw a sidebar of titles.
    """
    conversation = store.create(title="Big one")
    conversation.messages = [{"role": "user", "content": "x"} for _ in range(500)]
    store.save(conversation)

    row = store.summaries()[0]
    assert set(row) == {
        "id", "title", "project", "created_at", "updated_at", "message_count",
    }
    assert row["message_count"] == 500
    assert "messages" not in row


def test_a_missing_directory_lists_as_empty(tmp_path):
    assert ConversationStore(tmp_path / "never-created").list() == []


def test_a_corrupt_file_is_skipped_not_fatal(store):
    """One unreadable conversation must not cost you every conversation."""
    good = store.create(title="survivor")
    (store.root / ("f" * 32 + ".json")).write_text("{not json", encoding="utf-8")

    titles = [c.title for c in store.list()]
    assert "survivor" in titles


def test_deleting_removes_it_from_the_list(store):
    conversation = store.create(title="temporary")
    assert store.delete(conversation.id) is True
    assert conversation.id not in [c.id for c in store.list()]


def test_deleting_something_that_is_not_there_reports_false(store):
    assert store.delete("0" * 32) is False


# --- ids are paths ---------------------------------------------------------
def test_an_id_that_is_a_path_is_refused(store):
    """Ids arrive over the wire, so they are untrusted input.

    A caller must not be able to name a path. It is refused rather than
    sanitised, because quietly rewriting it would store the conversation
    somewhere the caller never learns about.
    """
    for hostile in ("../../secrets", "..\\..\\secrets", "not-a-uuid", "", "z" * 32):
    # "a" * 32 is deliberately absent: it is 32 hex characters, so it is a
    # legitimate id. The check rejects shapes a uuid cannot have, not strings
    # that merely look odd.
        with pytest.raises(ValueError):
            store._path(hostile)
        assert store.load(hostile) is None
        assert store.delete(hostile) is False


def test_a_write_is_never_left_half_finished(store, monkeypatch):
    """An interrupted write must not destroy an existing conversation.

    The temp file is written first and renamed over the target, so the old file
    survives a crash at any point during the write.
    """
    conversation = store.create(title="valuable")
    conversation.messages = [{"role": "user", "content": "original"}]
    store.save(conversation)

    def explode(self, target):
        raise OSError("disk full")

    monkeypatch.setattr(
        "pathlib.Path.replace", explode, raising=True
    )
    conversation.messages = [{"role": "user", "content": "new"}]
    with pytest.raises(OSError):
        store.save(conversation)
    monkeypatch.undo()

    reloaded = store.load(conversation.id)
    assert reloaded.messages == [{"role": "user", "content": "original"}]


def test_no_temp_files_are_left_behind_after_a_save(store):
    store.create(title="clean")
    leftovers = [p.name for p in store.root.glob("*.tmp")]
    assert leftovers == []