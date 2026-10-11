"""What the agent is working on, kept apart from what it has said.

A transcript records what *happened*. A task list and a goal are what the agent
*intends*, and they differ in every way that matters: they are read on every turn
rather than appended to, they are replaced rather than accumulated, and the model
needs them in front of it without the whole conversation being re-read to find
them. Kept in the message history, a plan becomes something the model has to hunt
for among everything it tried and abandoned.

**Per conversation, and stored with it.** A plan belongs to the chat that made it,
so it is saved beside the messages in the conversation file and comes back when
that chat is reopened -- see ``Conversation.state``. A process-wide plan would
follow the user into an unrelated chat, and a plan kept only in memory would vanish
on a restart nobody asked for.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

#: The states one item of a task list can be in.
#:
#: Three, and not a boolean. "Not done yet" and "being worked on right now" are
#: different things both to a model deciding what to do next and to a reader
#: deciding whether the agent is stuck.
TODO_STATUSES = ("pending", "in_progress", "completed")

#: The states a goal can be in.
#:
#: The harness this is modelled on also counts rounds, continues automatically
#: between them, and refuses to accept "blocked" until the same condition has
#: persisted for three rounds. **None of that is here, because none of it exists in
#: this app.** A turn begins when the user presses send, so there are no rounds for
#: a limit to bound, and nothing would ever read a blocked reason on its own. What
#: survives the trip is the part that means something without a continuation loop:
#: an objective, where it has got to, and why.
GOAL_STATUSES = ("active", "complete", "blocked")

#: Longest a task's text may be. A task list is meant to be read at a glance, and an
#: item long enough to be a paragraph is a plan the reader skips.
MAX_ITEM_CHARS = 200

#: How the prompt block marks each state.
_MARKS = {"pending": "[ ]", "in_progress": "[~]", "completed": "[x]"}


def _one_line(text: Any) -> str:
    """Collapse to a single trimmed line. What every field in here stores."""
    return " ".join(str(text or "").split())


@dataclass
class Todo:
    """One item of the agent's task list."""

    text: str
    status: str = "pending"

    def __post_init__(self) -> None:
        self.text = _one_line(self.text)
        # An unknown status becomes "pending" rather than raising: a state file
        # written by a newer build should cost the reader a status, not the whole
        # list -- the same reasoning `Conversation.from_dict` uses for messages.
        if self.status not in TODO_STATUSES:
            self.status = "pending"

    def to_dict(self) -> dict[str, str]:
        return {"text": self.text, "status": self.status}

    @classmethod
    def from_dict(cls, data: Any) -> "Todo | None":
        if isinstance(data, str):
            # A bare string is accepted so a hand-written or older state file still
            # opens. Refusing the entry would drop a task over its *shape*.
            data = {"text": data}
        if not isinstance(data, dict):
            return None
        text = _one_line(data.get("text"))
        if not text:
            return None
        return cls(text=text, status=str(data.get("status") or "pending"))


@dataclass
class SessionState:
    """The task list and the goal for one conversation."""

    todos: list[Todo] = field(default_factory=list)
    goal: str = ""
    goal_status: str = ""
    goal_note: str = ""

    # -- the task list -------------------------------------------------------
    def replace_todos(self, items: list[Todo]) -> None:
        """Replace the list outright.

        Replace rather than merge, because that is what the caller is asked to
        send: the list it wants to exist. A merge would make *removing* an item
        impossible without a second verb, and a list that can only grow is one
        nobody prunes -- a task the model has quietly abandoned is then read on
        every later turn as work still outstanding.
        """
        self.todos = list(items)

    def set_todo_status(self, index: int, status: str) -> bool:
        """Move one item. ``index`` is 0-based; returns False if it cannot be done."""
        if not 0 <= index < len(self.todos) or status not in TODO_STATUSES:
            return False
        self.todos[index].status = status
        return True

    @property
    def open_todos(self) -> list[Todo]:
        return [todo for todo in self.todos if todo.status != "completed"]

    @property
    def done_count(self) -> int:
        return len(self.todos) - len(self.open_todos)

    # -- the goal ------------------------------------------------------------
    def set_goal(self, objective: str, status: str = "active", note: str = "") -> None:
        self.goal = _one_line(objective)
        self.goal_status = status if status in GOAL_STATUSES else "active"
        self.goal_note = _one_line(note)

    def clear_goal(self) -> None:
        self.goal = ""
        self.goal_status = ""
        self.goal_note = ""

    @property
    def has_goal(self) -> bool:
        return bool(self.goal)

    # -- rendering -----------------------------------------------------------
    def is_empty(self) -> bool:
        return not self.todos and not self.goal

    def render(self) -> str:
        """The state as the block the model reads, or ``""`` when there is none.

        Appended to the system prompt rather than sent as a message. It is not
        something either party *said*, and putting it in the history would make the
        model's own plan a turn in the transcript -- which ``clear()`` and the
        history tests would then have to account for, and which the model would read
        back as though it had claimed it.
        """
        if self.is_empty():
            return ""
        blocks: list[str] = []
        if self.goal:
            block = f"## Goal\n{self.goal}\nState: {self.goal_status or 'active'}"
            if self.goal_note:
                block += f"\nNote: {self.goal_note}"
            blocks.append(block)
        if self.todos:
            rows = "\n".join(
                f"{index}. {_MARKS.get(todo.status, '[ ]')} {todo.text}"
                for index, todo in enumerate(self.todos, start=1)
            )
            blocks.append(
                f"## Task list\n{rows}\n"
                f"({self.done_count} of {len(self.todos)} done. Keep this list "
                "current with todo_write as you go.)"
            )
        return "\n\n".join(blocks)

    def summary(self) -> str:
        """One line about the plan, for a tool card or a status bar."""
        parts: list[str] = []
        if self.goal:
            parts.append(f"goal: {self.goal_status or 'active'}")
        if self.todos:
            parts.append(f"{self.done_count}/{len(self.todos)} tasks done")
        return " \u00b7 ".join(parts) if parts else "no plan"

    # -- storage -------------------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        return {
            "todos": [todo.to_dict() for todo in self.todos],
            "goal": self.goal,
            "goal_status": self.goal_status,
            "goal_note": self.goal_note,
        }

    @classmethod
    def from_dict(cls, data: Any) -> "SessionState":
        """Read state from a conversation file, tolerating anything.

        Every branch here is forgiving on purpose: this runs while a conversation is
        being opened, and a state file that cannot be read must cost the plan rather
        than the transcript. Missing keys, wrong types and junk entries all end as
        "no state", which is what a conversation that never had one looks like.
        """
        if not isinstance(data, dict):
            return cls()
        raw = data.get("todos")
        todos: list[Todo] = []
        if isinstance(raw, list):
            for entry in raw:
                todo = Todo.from_dict(entry)
                if todo is not None:
                    todos.append(todo)
        status = str(data.get("goal_status") or "")
        return cls(
            todos=todos,
            goal=_one_line(data.get("goal")),
            goal_status=status if status in GOAL_STATUSES else ("active" if data.get("goal") else ""),
            goal_note=_one_line(data.get("goal_note")),
        )


#: The state of the conversation in progress.
#:
#: A module global for the same reason ``folder_manager`` is one: this app has one
#: open conversation at a time, and tools are stateless singletons built from a
#: registry with no per-call context to thread a session through. ``AgentSession``
#: publishes its own state here when it adopts one, so a tool writes to the same
#: object the session reads -- a copy would be a plan the model updates and the
#: prompt never sees, which is the worst of both.
_current: SessionState | None = None


def current_state() -> SessionState:
    """The state tools write to.

    Never ``None``, and lazily created, so a tool always has somewhere to write.
    The alternative -- refusing when no session has published -- would turn a
    library-level call into an error about app plumbing.
    """
    global _current
    if _current is None:
        _current = SessionState()
    return _current


def set_current_state(state: SessionState | None) -> None:
    """Point the tools at a state. Called by ``AgentSession`` when it adopts one."""
    global _current
    _current = state
