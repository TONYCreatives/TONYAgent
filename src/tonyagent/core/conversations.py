"""Conversations on disk.

The core kept history in ``AgentSession.messages`` and nowhere else, so closing
the window destroyed the conversation and "New chat" could only ever mean
"clear". A list of chats is therefore not a UI feature; it needs somewhere for
the chats to live, and that is this module.

One JSON file per conversation, named by its id. That choice is deliberate
against a single index file: a corrupt conversation should cost you that one
conversation rather than every conversation, and a write costs one small file
rather than a rewrite of the whole history. With tens of conversations rather
than tens of thousands, the cost difference does not matter.

The store deliberately knows nothing about providers, tools or the protocol.
It holds titles and messages, and it is the only place that decides where on
disk a conversation lives.
"""

from __future__ import annotations

import copy
import json
import re
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from loguru import logger


#: A conversation title is the first thing the user said, trimmed to something
#: that fits a list row. Generated, never asked for: a rename field in an empty
#: sidebar is a form the user has to fill in before they know what to call it.
_TITLE_MAX = 60

#: Ids are used as filenames, so they are constrained to characters that cannot
#: escape the directory on any platform. A uuid4 hex already satisfies this; the
#: check exists because the id also arrives over the wire in ``switch`` and
#: ``delete``, and a caller must not be able to name a path.
_SAFE_ID = re.compile(r"^[0-9a-f]{32}$")


def _one_line(text: str, limit: int = _TITLE_MAX) -> str:
    """Collapse text to a single trimmed line, cut on a word boundary.

    A title ending mid-word looks like a bug even when the text is correct, so
    the cut backs up to the last space. An empty result means the input was
    nothing but whitespace.
    """
    flat = " ".join((text or "").split())
    if len(flat) <= limit:
        return flat
    cut = flat[:limit]
    if " " in cut:
        cut = cut[: cut.rindex(" ")]
    return cut.rstrip() + "…"


def title_from(text: str) -> str:
    """Derive a list title from the first user message."""
    return _one_line(text) or "New chat"


def _suffixed(title: str, suffix: str) -> str:
    """``"name"`` plus a suffix, with room kept for the suffix.

    Truncating the whole string after appending would eat the suffix itself,
    which is the one part of the row that says what happened to it.
    """
    room = _TITLE_MAX - len(suffix)
    base = _one_line(title, room) or "New chat"
    return base + suffix


class EmptyTitle(ValueError):
    """Raised when a conversation would be left with no name.

    Its own type rather than a bare ``ValueError`` because the protocol layer
    has to tell this apart from every other ``ValueError`` -- and
    ``UnicodeEncodeError`` is one of them, so catching ``ValueError`` there
    turned a failed write into a "you gave me a bad name" rejection and hid the
    real fault behind the user's typo.
    """


@dataclass
class Conversation:
    """One saved conversation.

    ``messages`` is kept as plain dicts rather than ``ChatMessage`` objects: the
    file format is the schema, and importing the provider layer to read a file
    would make the store depend on the thing it stores transcripts *of*.

    Those dicts are whatever ``ChatMessage.to_dict`` produced, so a message
    written by a reasoning model carries its ``reasoning`` and
    ``reasoning_details`` alongside ``content``. A conversation saved before
    either field existed has no such keys, and reads back fine: nothing here
    validates message shape, and the reader defaults an absent field to None.
    That is the reason for the loose typing -- a new field on a message is
    stored and restored without a migration, because the only thing that has to
    survive is "does this old chat still open".
    """

    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    title: str = "New chat"
    project: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    messages: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "project": self.project,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "messages": self.messages,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Conversation":
        return cls(
            id=str(data.get("id") or uuid.uuid4().hex),
            title=str(data.get("title") or "New chat"),
            project=str(data.get("project") or ""),
            created_at=float(data.get("created_at") or time.time()),
            updated_at=float(data.get("updated_at") or time.time()),
            messages=list(data.get("messages") or []),
        )

    def summary(self) -> dict[str, Any]:
        """What a list row needs, without the transcript.

        The transcript is the expensive part and no row renders it, so shipping
        it to build a sidebar would mean transferring the entire chat history on
        every launch to display a dozen titles.
        """
        return {
            "id": self.id,
            "title": self.title,
            "project": self.project,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "message_count": len(self.messages),
        }


class ConversationStore:
    """Read and write conversations under one directory.

    Failures are logged and swallowed into empty results. A conversation file
    that cannot be read is a problem for that conversation; taking the whole app
    down because one file is malformed would make a recoverable problem
    unrecoverable.
    """

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def _path(self, conversation_id: str) -> Path:
        if not _SAFE_ID.match(conversation_id or ""):
            # Refused rather than sanitised: a caller naming something that is
            # not an id is a bug, and quietly rewriting it would store the
            # conversation under a name the caller never learns.
            raise ValueError(f"Not a conversation id: {conversation_id!r}")
        return self.root / f"{conversation_id}.json"

    def create(self, title: str = "New chat", project: str = "") -> Conversation:
        conversation = Conversation(title=title, project=project)
        self.save(conversation)
        return conversation

    def save(self, conversation: Conversation, touch: bool = True) -> None:
        """Write a conversation to disk.

        ``touch`` stamps ``updated_at`` to now, which is what moves a
        conversation to the top of the list -- correct for a turn that just
        happened, wrong for a copy, which is *about* an older conversation and
        belongs next to it rather than above everything.
        """
        if touch:
            conversation.updated_at = time.time()
        self.root.mkdir(parents=True, exist_ok=True)
        path = self._path(conversation.id)
        # Write-then-replace, so an interrupted write cannot leave a truncated
        # file where a whole conversation used to be. The temp file is in the
        # same directory so the rename stays on one filesystem, which is what
        # makes it atomic.
        temp = path.with_suffix(".json.tmp")
        temp.write_text(
            json.dumps(conversation.to_dict(), ensure_ascii=False, indent=1),
            encoding="utf-8",
        )
        temp.replace(path)

    def load(self, conversation_id: str) -> Conversation | None:
        try:
            path = self._path(conversation_id)
        except ValueError:
            return None
        if not path.exists():
            return None
        try:
            return Conversation.from_dict(json.loads(path.read_text(encoding="utf-8")))
        except Exception as exc:  # noqa: BLE001 - one bad file, not a dead app
            logger.warning(f"Could not read conversation {conversation_id}: {exc}")
            return None

    def list(self) -> list[Conversation]:
        """Every readable conversation, most recently updated first.

        Ties on ``updated_at`` break by ``created_at`` *ascending*, which is
        what puts a duplicate directly under the conversation it was copied
        from: the copy shares the original's ``updated_at`` and was created
        later. Without the tiebreak the two rows would come back in whatever
        order the directory happened to yield, which is not a rule anyone can
        rely on.
        """
        if not self.root.exists():
            return []
        found: list[Conversation] = []
        for path in self.root.glob("*.json"):
            conversation = self.load(path.stem)
            if conversation is not None:
                found.append(conversation)
        # Negating rather than reverse=True: the two keys sort in opposite
        # directions, and a tuple key is the only way to say that in one pass.
        found.sort(key=lambda c: (-c.updated_at, c.created_at))
        return found

    def summaries(self) -> list[dict[str, Any]]:
        return [c.summary() for c in self.list()]

    def delete(self, conversation_id: str) -> bool:
        try:
            path = self._path(conversation_id)
        except ValueError:
            return False
        if not path.exists():
            return False
        try:
            path.unlink()
            return True
        except OSError as exc:
            logger.warning(f"Could not delete conversation {conversation_id}: {exc}")
            return False

    def most_recent(self) -> Conversation | None:
        conversations = self.list()
        return conversations[0] if conversations else None

    # -- manual names --------------------------------------------------------
    def rename(self, conversation_id: str, title: str) -> Conversation | None:
        """Give a conversation a name the user chose. ``None`` if not found.

        An empty or whitespace-only name is refused by raising
        :class:`EmptyTitle` rather than being quietly replaced with something.
        The title *is* the conversation as far as the list is concerned: a row
        with no name is a row the user cannot find again, and silently writing
        "New chat" over their typing would look like the rename had worked.
        """
        clean = _one_line(title)
        if not clean:
            raise EmptyTitle("A conversation needs a name")
        conversation = self.load(conversation_id)
        if conversation is None:
            return None
        conversation.title = clean
        self.save(conversation)
        return conversation

    def duplicate(self, conversation_id: str) -> Conversation | None:
        """Copy a conversation, messages and all, under a new id.

        The messages are deep-copied rather than shared. They are plain dicts
        holding nested lists (``reasoning_details``), so a shallow copy would
        hand the caller two records pointing at one set of objects. Today
        nothing can observe that, because the store re-reads a conversation
        from disk on every operation and the object ``duplicate`` was derived
        from is discarded -- but that is a property of the current callers, not
        of the data, and a shallow copy here would turn a future refactor into a
        silent corruption bug.

        The copy keeps the original's ``updated_at`` so the list shows it
        directly beneath the conversation it came from. The file itself is
        written now, so its mtime on disk is fresh either way; it is the
        *record's* timestamp that stays put, and that is the one the list sorts
        on.
        """
        original = self.load(conversation_id)
        if original is None:
            return None
        clone = Conversation(
            id=uuid.uuid4().hex,
            title=_suffixed(original.title, " (copy)"),
            project=original.project,
            created_at=time.time(),
            updated_at=original.updated_at,
            messages=copy.deepcopy(original.messages),
        )
        self.save(clone, touch=False)
        return clone
