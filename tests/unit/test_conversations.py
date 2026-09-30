"""The conversation store.

The point of these tests is that a chat survives the window closing. Every other
test in the suite runs inside one process with the history in memory, so
nothing here was ever exercised -- which is why the store had to be written
before the list that reads from it.
"""

from __future__ import annotations

import json
from pathlib import Path

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


# --- names the user chose -------------------------------------------------
def test_a_rename_sticks_and_survives_a_reopen(store):
    conversation = store.create(title="New chat")
    store.rename(conversation.id, "  Invoice questions  ")
    assert store.load(conversation.id).title == "Invoice questions"
    # Through a second store, i.e. off the disk rather than out of a cache.
    assert ConversationStore(store.root).load(conversation.id).title == (
        "Invoice questions"
    )


@pytest.mark.parametrize("blank", ["", "   ", "\t\n  "])
def test_a_blank_name_is_refused_rather_than_invented(store, blank):
    """A list row with no name is a conversation the user cannot find again."""
    conversation = store.create(title="Something worth keeping")
    with pytest.raises(ValueError):
        store.rename(conversation.id, blank)
    assert store.load(conversation.id).title == "Something worth keeping"


def test_renaming_a_conversation_that_is_not_there_reports_it_as_missing(store):
    missing = "0" * 32
    assert store.rename(missing, "whatever") is None
    assert store.duplicate(missing) is None


def test_a_renamed_title_is_cut_on_a_word_boundary(store):
    """A title ending mid-word looks like a bug even when it is correct."""
    conversation = store.create()
    store.rename(conversation.id, "word " * 40)
    title = store.load(conversation.id).title
    assert len(title) <= 61  # the ellipsis is one character over the budget
    assert title.endswith("…")
    assert not title.endswith("wor…")


# --- copies ---------------------------------------------------------------
def _seed(store, title="Original"):
    conversation = store.create(title=title)
    conversation.messages = [
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "second", "reasoning": "because"},
    ]
    store.save(conversation)
    return store.load(conversation.id)


def test_a_copy_takes_the_whole_transcript_under_a_new_id(store):
    original = _seed(store)
    clone = store.duplicate(original.id)
    assert clone is not None
    assert clone.id != original.id
    assert clone.messages == original.messages


def test_a_copy_sits_directly_under_the_conversation_it_came_from(store):
    """Position, not just content: a copy you have to hunt for is a lost copy."""
    older = _seed(store, "Older")
    newer = _seed(store, "Newer")
    store.rename(older.id, "Older")

    clone = store.duplicate(newer.id)
    order = [c.id for c in store.list()]
    assert order.index(clone.id) == order.index(newer.id) + 1


def test_the_position_of_a_copy_does_not_depend_on_directory_order(store):
    """The ordering is a rule, not an accident of how the files were read.

    The copy and its original share an ``updated_at``, so which of the two
    comes first is decided by the tiebreak. Without it the answer is whatever
    order the filesystem happened to yield, and this test passes whenever that
    order happens to agree.
    """
    original = _seed(store)
    clone = store.duplicate(original.id)
    assert clone.updated_at == original.updated_at, "they must actually tie"

    real_glob = Path.glob

    def reversed_glob(self, pattern):
        # The copy's file is offered first -- the order that would put it above
        # its original if the sort did not care.
        return iter(sorted(real_glob(self, pattern), reverse=True))

    store.root  # the store must exist before its directory is read
    monkey = pytest.MonkeyPatch()
    monkey.setattr(Path, "glob", reversed_glob)
    try:
        order = [c.id for c in store.list()]
    finally:
        monkey.undo()

    assert order.index(clone.id) == order.index(original.id) + 1


def test_a_copy_and_its_original_do_not_share_state(store):
    """Editing the copy must not reach the original, or the reverse.

    The store re-reads a conversation from disk on every operation, so the two
    only ever meet as files -- which is exactly the guarantee worth pinning. A
    copy written over the original's filename, or an id reused by mistake,
    shows up here and nowhere else.
    """
    original = _seed(store)
    clone = store.duplicate(original.id)

    clone.messages[1]["reasoning"] = "rewritten"
    clone.messages.append({"role": "user", "content": "only in the copy"})
    store.save(clone, touch=False)

    reread_original = store.load(original.id)
    assert reread_original.messages[1]["reasoning"] == "because"
    assert len(reread_original.messages) == 2

    reread_original.messages[0]["content"] = "edited in the original"
    store.save(reread_original)
    assert store.load(clone.id).messages[0]["content"] == "first"


def test_a_copy_is_told_apart_from_its_original_by_name(store):
    original = _seed(store, "Deploy plan")
    clone = store.duplicate(original.id)
    assert clone.title == "Deploy plan (copy)"
    assert store.load(original.id).title == "Deploy plan"


def test_a_copy_keeps_room_for_its_own_suffix(store):
    """A 60-character title plus " (copy)" must not push the suffix off the end."""
    original = _seed(store, "word " * 30)
    clone = store.duplicate(original.id)
    assert clone.title.endswith(" (copy)")
    assert len(clone.title) <= 61


def test_deleting_a_copy_leaves_the_original_alone(store):
    original = _seed(store)
    clone = store.duplicate(original.id)
    assert store.delete(clone.id) is True
    assert store.load(original.id) is not None


# --- ordering -------------------------------------------------------------
def test_the_list_is_still_newest_first(store):
    first = _seed(store, "First")
    second = store.create(title="Second")
    order = [c.id for c in store.list()]
    assert order.index(second.id) < order.index(first.id)