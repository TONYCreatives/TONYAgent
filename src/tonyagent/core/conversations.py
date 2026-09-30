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


def title_from(text: str) -> str:
    """Derive a list title from the first user message.

    Collapses whitespace so a multi-line paste becomes one line, and cuts on a
    word boundary where it can -- a title ending mid-word looks like a bug even
    when the text is correct.
    """
    flat = " ".join((text or "").split())
    if not flat:
        return "New chat"
    if len(flat) <= _TITLE_MAX:
        return flat
    cut = flat[:_TITLE_MAX]
    if " " in cut:
        cut = cut[: cut.rindex(" ")]
    return cut.rstrip() + "…"


@dataclass
class Conversation:
    """One saved conversation.

    ``messages`` is kept as plain dicts rather than ``ChatMessage`` objects: the
    file format is the schema, and importing the provider layer to read a file
    would make the store depend on the thing it stores transcripts *of*.
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

    def save(self, conversation: Conversation) -> None:
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
        """Every readable conversation, most recently updated first."""
        if not self.root.exists():
            return []
        found: list[Conversation] = []
        for path in self.root.glob("*.json"):
            conversation = self.load(path.stem)
            if conversation is not None:
                found.append(conversation)
        found.sort(key=lambda c: c.updated_at, reverse=True)
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