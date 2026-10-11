"""The user, as a resource a tool can use.

Two tools reach a human mid-turn: ``ask_user_question`` and ``present``. Both
need a way to put something in front of the user and get an answer back, and
neither may invent one -- a second dialog mechanism beside the destructive-tool
confirmation would mean two pending-answer tables, two timeouts, and two ways to
strand a turn. So the machinery lives here, once.

**The shape is copied from the confirmation path on purpose.** The orchestrator's
``ConfirmationRequest`` is a future plus a table plus a callback, and all three
parts of it are load-bearing: the future is what the awaiting tool suspends on,
the table is what lets a late reply find the question it belongs to, and the
callback is what publishes the ask as an event so a window can render it. What
differs here is only the *answer*: a confirmation resolves to a bool, this
resolves to whatever the user typed.

**Tools are stateless singletons**, which is the same constraint
``folder_manager`` and ``task_state`` live with -- there is no per-call context
to thread a session through, so this is a module-level registry with one hook
pair installed by the session. It is also why the tests reset it per test: the
per-conversation design would otherwise leak through the back door.

**The loop is the one the turn runs on**, and that is not an accident. The
confirmation path proves a ``respond`` arriving on the read loop can settle a
future created inside a tool call, because ``headless/server.py`` serves the
protocol and runs the turn on one ``asyncio.run``. Nothing here marshals across
threads, for the same reason the confirmation does not.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Sequence

from loguru import logger

#: How long an ask waits for the user before the turn carries on without them.
#:
#: 60 seconds, the same as the destructive-tool confirmation waits. One bound a
#: user can learn, and a bound that exists at all: a question nobody answers
#: must not block a turn indefinitely, because a model told "nobody answered"
#: can proceed and say so, while a model hung on an unanswered dialog produces
#: a window that looks broken with nothing anywhere saying why.
ASK_TIMEOUT_S = 60.0

#: The two kinds of ask. One event pair and one dialog serve both, because the
#: only difference the plumbing can see is what the user is shown -- and what
#: the tool makes of a non-answer, which is the *tool's* judgement, not the
#: transport's.
KIND_QUESTION = "question"
KIND_PRESENTATION = "presentation"


class UserUnavailable(RuntimeError):
    """Nothing is listening for questions, so the ask cannot be made.

    A bare session -- tests, a scripted import, a core with no window -- has no
    user attached to it. That is a *refusal*, not a failure: the tool reports it
    and the turn continues with a model that has learned it is on its own,
    which is the honest outcome. The alternative -- hanging on a timeout for a
    user who does not exist -- would make every such run cost a minute.
    """


class UserSilent(RuntimeError):
    """The ask went out and no answer came back in time."""


@dataclass
class QuestionRequest:
    """One ask, and the future its answer will land in."""

    id: str
    tool_name: str
    kind: str
    #: The question, or a presentation's title. One field because the dialog
    #: shows it in the same place and the model is told to write it that way.
    prompt: str
    #: A presentation's body. Empty for a question.
    content: str = ""
    options: list[str] = field(default_factory=list)
    future: asyncio.Future | None = None
    timestamp: float = field(default_factory=time.time)

    def to_payload(self) -> dict[str, Any]:
        """The event payload a window reads to draw the dialog.

        Every key is plain JSON, because this crosses a process boundary when
        the core is a child of the window host. The ``kind`` travels with it
        rather than being inferred by the frontend: which of the two tools is
        asking changes what the buttons mean, and a guess would be a guess.
        """
        return {
            "id": self.id,
            "name": self.tool_name,
            "kind": self.kind,
            "prompt": self.prompt,
            "content": self.content,
            "options": list(self.options),
        }


#: Asks awaiting an answer, by question id.
_pending: dict[str, QuestionRequest] = {}

_on_asked: Callable[[QuestionRequest], None] | None = None
_on_resolved: Callable[[str, str | None], None] | None = None


def set_callbacks(
    on_asked: Callable[[QuestionRequest], None] | None,
    on_resolved: Callable[[str, str | None], None] | None,
) -> None:
    """Install the two hooks the session provides.

    ``on_asked`` publishes the ask; ``on_resolved`` takes it down again, with
    the answer or ``None`` when there was not one. Both are synchronous by
    design -- they only publish an event, exactly like the confirmation
    callback, which has to run while the tool is still suspended.
    """
    global _on_asked, _on_resolved
    _on_asked = on_asked
    _on_resolved = on_resolved


def pending_count() -> int:
    """How many asks are outstanding. Diagnostics, and the leak test."""
    return len(_pending)


def is_listening() -> bool:
    """Whether an ask could be made at all.

    False before the session installs the bridge, which is what a bare session
    and a test have. Exposed because "nobody is listening" is otherwise only
    observable by making an ask and catching the refusal.
    """
    return _on_asked is not None


def reset() -> None:
    """Drop every ask and both hooks. For tests.

    Cancels rather than resolves: nothing is waiting on these futures any more,
    and a test that leaves one behind would have the next test inherit it.
    """
    global _on_asked, _on_resolved
    for request in list(_pending.values()):
        future = request.future
        if future is not None and not future.done():
            future.cancel()
    _pending.clear()
    _on_asked = None
    _on_resolved = None


def respond(question_id: str, answer: str) -> bool:
    """Answer an outstanding ask. False if there was nothing to answer.

    A late answer -- the user clicks a fraction after the turn was cancelled,
    or after the timeout already fired -- is a no-op rather than an error,
    because the frontend clears its own dialog on the way out and a reply that
    arrives for a question nobody is holding is the normal end of a race, not a
    fault. Returning the bool lets the caller say so.
    """
    request = _pending.get(question_id)
    if request is None:
        return False
    future = request.future
    if future is None or future.done():
        return False
    future.set_result(answer if isinstance(answer, str) else str(answer or ""))
    _notify_resolved(question_id, answer)
    return True


async def ask(
    *,
    kind: str,
    prompt: str,
    content: str = "",
    options: Sequence[str] = (),
    tool_name: str = "",
    timeout: float | None = None,
) -> str:
    """Put something in front of the user and wait for their answer.

    Returns whatever they typed or clicked -- an empty string when they chose
    not to answer, which is an answer and not a failure. Raises
    :class:`UserUnavailable` when nothing is listening and :class:`UserSilent`
    when the wait ran out; both are the caller's to word.

    ``timeout`` defaults to :data:`ASK_TIMEOUT_S`, read here rather than bound
    in the signature so the constant stays one knob rather than two -- and so a
    test can shorten it without reaching into the call sites.

    The ask is published only once it is in ``_pending``, so a reply cannot
    arrive for something no reader can find -- the order is the whole reason
    this is not two lines shorter.
    """
    if _on_asked is None:
        raise UserUnavailable(
            "There is no user to ask in this session: nothing is listening for "
            "questions. Decide what to do with what you already know, say which "
            "assumption you are making, and carry on."
        )
    wait = ASK_TIMEOUT_S if timeout is None else timeout

    loop = asyncio.get_running_loop()
    request = QuestionRequest(
        id=uuid.uuid4().hex,
        tool_name=tool_name,
        kind=kind,
        prompt=prompt,
        content=content,
        options=[str(option) for option in options],
    )
    request.future = loop.create_future()
    _pending[request.id] = request

    try:
        _on_asked(request)
    except Exception:  # noqa: BLE001 - a broken hook must not hold the ask
        logger.exception("user_io: the asked callback raised")
        _pending.pop(request.id, None)
        raise

    try:
        return await asyncio.wait_for(request.future, timeout=wait)
    except asyncio.TimeoutError:
        # The dialog is still up in the window and nobody is behind it. Take it
        # down here rather than leaving it there for its full animation and
        # then nothing.
        _notify_resolved(request.id, None)
        raise UserSilent(
            "No answer arrived within "
            f"{wait:g} seconds -- the user is not there to answer. Either "
            "state the assumption you are making and carry on, or stop and say "
            "what you needed from them."
        ) from None
    except BaseException:
        # A cancelled turn, or a caller that gave up. The future will never be
        # read, so the round trip is closed here instead of being left
        # half-open with a dialog on screen for a turn that stopped.
        #
        # Not gated on `future.done()`: cancelling the awaiting task cancels the
        # future it is waiting on, so a cancelled ask looks "done" -- and
        # gating on that is what left the dialog up over a stopped turn, which
        # is the one thing this whole module exists to prevent. The only other
        # path that notifies is `respond`, on the success path, which never
        # reaches an `except` at all.
        _notify_resolved(request.id, None)
        raise
    finally:
        _pending.pop(request.id, None)


def _notify_resolved(question_id: str, answer: str | None) -> None:
    """Tell the window an ask is over, with the answer or without one."""
    callback = _on_resolved
    if callback is None:
        return
    try:
        callback(question_id, answer)
    except Exception:  # noqa: BLE001 - taking the dialog down must not raise
        logger.exception("user_io: the resolved callback raised")


