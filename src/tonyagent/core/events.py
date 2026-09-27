"""UI-agnostic event bus for the agent core.

This is the replacement for ``schedule_on_ui()``. The old mechanism pushed
callables onto a queue that only Tkinter's ``after()`` loop ever drained, so
under a headless process every callback vanished silently - which is how
tool-confirmation requests could be issued and then dropped.

The bus is deliberately dependency-free: the core emits events, and each
frontend (Tkinter, a Tauri sidecar, a test) subscribes with its own transport.
That is what makes the core runnable without a display.
"""

from __future__ import annotations

import asyncio
import inspect
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional


class EventType(str, Enum):
    """Events the core emits. Values are the wire names used by the protocol."""

    # Conversation lifecycle
    TURN_STARTED = "turn.started"
    TURN_FINISHED = "turn.finished"
    TURN_FAILED = "turn.failed"

    # Assistant output
    MESSAGE_STARTED = "message.started"
    MESSAGE_DELTA = "message.delta"
    MESSAGE_COMPLETED = "message.completed"

    # Tool execution
    TOOL_STARTED = "tool.started"
    TOOL_COMPLETED = "tool.completed"
    TOOL_FAILED = "tool.failed"
    #: The core is blocked waiting for the user to approve a tool call.
    CONFIRMATION_REQUESTED = "confirmation.requested"
    CONFIRMATION_RESOLVED = "confirmation.resolved"

    # Sandbox
    SANDBOX_STATUS = "sandbox.status"
    SANDBOX_STATS = "sandbox.stats"

    # Diagnostics
    LOG = "log"
    ERROR = "error"


@dataclass
class Event:
    """One thing that happened in the core.

    ``payload`` holds plain JSON-compatible data only. Anything non-serialisable
    must be converted by the emitter, because these objects cross a process
    boundary when the core runs as a Tauri sidecar.
    """

    type: EventType
    payload: dict[str, Any] = field(default_factory=dict)
    #: Correlates events belonging to one user-initiated turn.
    turn_id: Optional[str] = None
    sequence: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Wire shape for one event.

        ``type`` is the discriminator a frontend switches on; ``seq`` lets a
        late-joining or reconnecting UI detect what it missed.
        """
        return {
            "type": self.type.value,
            "seq": self.sequence,
            "turn_id": self.turn_id,
            "payload": self.payload,
        }


Subscriber = Callable[[Event], Any]


class EventBus:
    """Fan-out of core events to any number of subscribers.

    Subscribers may be sync or async. Sync ones are called immediately, which
    keeps the Tkinter UI simple; async ones are scheduled onto the running
    loop, which is what the sidecar uses to stream events over stdio.
    """

    def __init__(self, history: int = 200) -> None:
        self._subscribers: list[Subscriber] = []
        self._sequence = 0
        # A short replay buffer. A UI that attaches late (or reconnects) can
        # catch up instead of missing everything that happened during startup.
        self._history: deque[Event] = deque(maxlen=history)

    def subscribe(self, subscriber: Subscriber) -> Callable[[], None]:
        """Register a subscriber. Returns an unsubscribe callable."""
        self._subscribers.append(subscriber)

        def _unsubscribe() -> None:
            if subscriber in self._subscribers:
                self._subscribers.remove(subscriber)

        return _unsubscribe

    def replay(self, after_sequence: int = 0) -> list[Event]:
        """Events newer than ``after_sequence``, oldest first."""
        return [e for e in self._history if e.sequence > after_sequence]

    def emit(
        self,
        type: EventType,
        payload: Optional[dict[str, Any]] = None,
        turn_id: Optional[str] = None,
    ) -> Event:
        """Publish an event. Never raises because a subscriber failed.

        A broken subscriber must not be able to abort a generation turn: the
        old queue-based path logged and continued, and so does this.
        """
        self._sequence += 1
        event = Event(
            type=type,
            payload=payload or {},
            turn_id=turn_id,
            sequence=self._sequence,
        )
        self._history.append(event)
        for subscriber in list(self._subscribers):
            try:
                result = subscriber(event)
                if inspect.isawaitable(result):
                    self._schedule(result)
            except Exception:
                # Intentionally swallowed: see docstring.
                pass
        return event

    def _schedule(self, awaitable: Any) -> None:
        """Run an async subscriber on the loop, if there is one."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # No loop (e.g. emitting from a worker thread). Close the
            # coroutine so Python does not warn about it being un-awaited.
            try:
                awaitable.close()
            except Exception:
                pass
            return
        loop.create_task(awaitable)


#: Process-wide bus. The session emits here; transports subscribe.
bus = EventBus()
