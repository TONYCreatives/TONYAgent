"""Subagents: child sessions the parent runs and reads — Phase 5.

**A child is a real ``AgentSession``, not a lightweight shim.** It carries its
own messages, its own budget, and its own mode/permission pair, so a subagent
that exhausts its allowance is its own failure and never the parent's. The
sharpest hazard the handoff names is closed upstream (see
``tests/unit/test_subagent_isolation.py``): constructing a session no longer
publishes the child's plan into the process-global planning state the parent's
prompt reads, so a child simply owns its own plan.

**What a child is not: a peer.** A subagent runs *inside the parent's turn*.
That is the shape the turn loop forces — the parent's ``run_turn`` awaits the
tool call in which this child runs — and this module says so rather than
hiding it. A child therefore cannot interrupt the parent, ask it questions, or
write into its transcript; the parent reads only the child's answer.

**A child is re-entrant, not one-shot (the workflow phase).** The child's
session loop is entered per turn rather than once per child, so a child that
has answered can be handed another message with ``send_message`` — the same
transcript, continued — and a child's transcript can be copied into a new child
with ``subagent_fork``, which leaves the original alone. Both go through one
loop, :func:`_drive_child`, which is also the only place a child's turn is
started; the difference between the three verbs is where the child comes from
and what its first message says, not how it runs.

**Attribution is per turn, not per child.** Each turn a child runs stamps the
id of the call that asked for it (``AgentSession.subagent_call_id``), so the
window draws *that turn's* frames under *that* card: a follow-up
``send_message`` appears under the ``send_message`` card, not under the
``subagent`` card that created the child. The name is the child's for life; the
call id belongs to the turn.

**Its frames say who it is.** Everything a child emits carries its name and
its own turn id, and -- the link that matters now -- the id of the parent tool
call that spawned it (`Event.subagent` / `Event.parent_call_id`). That link is
what lets the window render the child's work under the card of the call that
started it; the turn id alone cannot, because it is the child's own and the
parent's transcript has never seen it.

**Fan-out is bounded, and it is bounded in three different places.** A parent
turn may run several children at once: the batch of tool calls it declared in
one assistant message is already executed concurrently by the session, so
declaring three ``subagent`` calls gets three children, and mixing
``send_message`` and ``subagent_fork`` into the same batch is the same
mechanism. What keeps that from being an unbounded spend is three separate
limits, each answering a different question -- and each of them in
:func:`_drive_child`, the same single owner that runs a child's turn:

* **one turn per child** -- a child's transcript is what a turn appends to, so
two turns of one child at once would interleave into one conversation. Per
child, not process-wide: two *different* children at once is the point.
* **``MAX_CHILDREN_PER_TURN``** -- how many children one parent turn may start.
The parent's tool budget already bounds that whenever it is set (each verb is
one of the parent's tool calls), and this is the backstop that makes it true
when the parent's budget is ``0``, which means "no limit".
* **``MAX_CONCURRENT_CHILDREN``** -- how many run at once, as a queue: a verb
that arrives with every slot taken waits for one rather than being refused.

The one thing deliberately *not* bounded here is what the children spend.
Each child's budget is its own (inherited as a ceiling, counted separately),
which is the Phase 5 decision and stays: a child that exhausts its allowance
is its own failure and never the parent's.
"""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Iterator, Optional

from loguru import logger

from tonyagent.core.modes import Mode, Permission
from tonyagent.core.task_state import SessionState
from tonyagent.providers.base import ChatMessage, MessageRole
from tonyagent.tools.base import (
    Tool,
    ToolCategory,
    ToolResult,
    ToolResultStatus,
    register_tool,
)
from tonyagent.tools.context import current as current_context

if TYPE_CHECKING:
    from tonyagent.core.session import AgentSession

# ``core.session`` imports ``tonyagent.tools`` (for the schema list), so a
# module-level ``from tonyagent.core.session import AgentSession`` here would
# close a circle the package layout cannot survive: ``tools/__init__`` is
# mid-import when this module loads. The child is therefore built from
# ``type(parent)`` -- the parent *is* an ``AgentSession``, so its own class is
# the constructor we need, and the type is reached through the value instead of
# through an import. No lazy import, no import-order coupling, and a subclass
# that overrides the loop gets its own class back, which is what a fork of a
# child should do.


def _copy_messages(messages: list[ChatMessage]) -> list[ChatMessage]:
    """A transcript that shares no mutable container with the one it came from."""
    return [
        ChatMessage(
            role=message.role,
            content=message.content,
            tool_calls=list(message.tool_calls) if message.tool_calls else None,
            tool_call_id=message.tool_call_id,
            name=message.name,
            reasoning=message.reasoning,
            reasoning_details=(
                list(message.reasoning_details) if message.reasoning_details else None
            ),
        )
        for message in messages
    ]

#: Longest one child turn may run, seconds.
#:
#: A child cannot have the parent's judgement, only its own bound. Generous on
#: purpose: an honest child only ever meets this on a provider request that
#: would otherwise hang the parent turn forever.
#:
#: **It measures the turn, not the wait for a slot.** A child that queued behind
#: three others still gets its full time to think -- see ``_ChildSlots``.
CHILD_TURN_TIMEOUT_S = 120.0

#: How many child turns may run at the same time.
#:
#: The fan-out bound, and it is a *queue*, not a cap: a verb that cannot get a
#: slot waits for one, so every child the model asked for still gets its turn
#: and the model never has to guess a number. Four because a child turn is an
#: HTTP stream of its own -- past a handful, concurrency buys latency on the
#: slowest child and little else, while multiplying the chance of a provider
#: rate limit.
MAX_CONCURRENT_CHILDREN = 4

#: How many child turns **one parent turn** may start.
#:
#: The answer to "does the parent's tool budget bound a fan-out", and it takes
#: two halves to state honestly:
#:
#: * It usually does, mechanically. Each of the three verbs *is* one of the
#:   parent's tool calls, counted before it runs, so a parent with a budget of
#:   ten cannot start more than ten children in a turn.
#: * It need not, because ``max_tool_calls == 0`` means "no limit" -- and that
#:   is a real setting the user can pick. Without this constant, "no limit"
#:   would mean a model could declare a thousand ``subagent`` calls in a single
#:   message and the queue would work through them, four at a time, for as long
#:   as they took.
#:
#: So the parent's budget is the bound, and this is the backstop that makes the
#: bound true when the parent has turned it off. Deliberately larger than
#: ``MAX_CONCURRENT_CHILDREN``: a turn may legitimately want more children than
#: it can run at once.
MAX_CHILDREN_PER_TURN = 8

#: How deep children may nest, counted in spawns below the session the user is
#: talking to. One, so a child may not spawn a child of its own.
#:
#: **This was already true, and only by accident.** The serial gate this phase
#: removed refused *any* spawn while a child was running -- and a child running
#: its own turn is exactly that -- so a grandchild was refused for a reason that
#: had nothing to do with nesting, stated as "one subagent runs at a time".
#: Removing that gate would have quietly made nesting possible, which is why the
#: rule is now its own check with its own words. (The handoff has both claims on
#: record; the serial gate's behaviour is the one the code actually had.)
#:
#: One level, not more, because the cost compounds by construction: a child's
#: budget is a *copy* of its parent's ceiling, so depth and ``MAX_CHILDREN_PER_TURN``
#: multiply -- two levels of eight is 72 child turns under one parent turn.
#: Raising this is a deliberate act, with that arithmetic in hand.
MAX_SUBAGENT_DEPTH = 1


class _ChildSlots:
    """The bound on how many child turns run at once.

    A semaphore with a reset, in this module because ``_drive_child`` is the one
    place a child's turn starts and a bound belongs where the turn does.

    **A queue, not a refusal.** A verb that arrives when every slot is taken
    waits for one. Refusing would make the fifth child of a batch fail for a
    reason the model can only fix by guessing the limit, and it would make a
    fan-out's *result set* depend on scheduling order -- a model that asked for
    six children would get six answers or five depending on timing. Waiting
    keeps the promise simple: ask for six, get six.

    The wait is bounded in practice by the wave structure -- at most
    ``ceil(n / MAX_CONCURRENT_CHILDREN)`` waves, each at most
    ``CHILD_TURN_TIMEOUT_S`` -- and it has no timeout of its own on purpose: a
    waiter that gives up after a fixed time turns a slow sibling into a failed
    child.
    """

    def __init__(self, limit: int = MAX_CONCURRENT_CHILDREN) -> None:
        self.limit = limit
        self._slots = asyncio.Semaphore(limit)

    @contextlib.asynccontextmanager
    async def slot(self) -> Iterator[None]:
        await self._slots.acquire()
        try:
            yield
        finally:
            self._slots.release()

    def reset(self) -> None:
        """A fresh permit set. A host act, like ``SubagentRegistry.restart``.

        A semaphore cannot be refilled, and the only thing that can leave a
        permit held is a turn that never released it -- a bug, but one whose
        symptom would be every later fan-out silently running one child at a
        time. Replacing the semaphore makes that state recoverable instead of
        terminal.
        """
        self._slots = asyncio.Semaphore(self.limit)


#: The process-wide pool, beside the registry and for the same reason: it owns
#: live child turns, and the window is one process.
_child_slots = _ChildSlots()


class SubagentError(Exception):
    """A subagent asked for but unavailable, said in plain words.

    Converted to a ToolResult by the tool below — never raised past the
    orchestrator, which formats exceptions in language the model cannot act on.
    """


@dataclass
class SubagentSnapshot:
    """What ``list_agents`` reports for one child."""

    name: str
    mode_name: str
    permission_name: str
    tool_calls_used: int
    max_tool_calls: int
    running: bool
    cancelled: bool
    finished: bool
    #: The child this one's transcript was copied from, if any.
    forked_from: str = ""


@dataclass
class SubagentHandle:
    """One live child and the task carrying its turn."""

    name: str
    session: AgentSession
    #: The first message this child was given. For a fork, that is the message
    #: the *forked* child runs, which is why it is replaced rather than reused.
    seed_message: str
    task: Optional[asyncio.Task] = None
    cancelled: bool = False
    finished: bool = False
    #: The child this one's transcript was copied from, if any.
    forked_from: str = ""

    def running(self) -> bool:
        """Whether a turn of this child's is in flight (queued or thinking).

        Not "has this child finished": ``send_message`` exists precisely to give
        a finished child another turn, so ``finished`` is not an obstacle. This
        is the one rule ``_drive_child`` enforces per child, stated once so the
        guard and ``list_agents`` cannot disagree about it.
        """
        return self.task is not None and not self.task.done()


class SubagentRegistry:
    """Who is running, who finished, and who may be named again.

    A registry rather than handles scattered through the session because
    ``interrupt_agent`` has to reach a child started turns later and
    ``list_agents`` has to answer without holding any of them.
    """

    def __init__(self) -> None:
        self._children: dict[str, SubagentHandle] = {}

    # -- creation ------------------------------------------------------------

    def spawn(
        self,
        parent: AgentSession,
        seed: str,
        name_hint: str = "",
        call_id: str = "",
    ) -> SubagentHandle:
        """Build a child session for this parent and record it.

        The child inherits the parent's mode and permission — permission may
        only *narrow*, and these are already the narrowest the parent has. It
        gets the parent's per-turn budget as its own ceiling, and the seed
        message is the only user turn it will ever read.

        ``call_id`` is the parent tool call this child belongs to, when the
        orchestrator is running one. The child stamps it on every frame it
        emits (see :attr:`AgentSession.subagent_call_id`), which is the link
        the window draws the child's work under.
        """
        mode: Mode = parent._mode
        permission: Permission = parent._permission
        # Children never read the parent's conversation, plan or reasoning
        # effort: the seed alone decides what the child is for, and whatever
        # the parent was planning is the parent's business. Construction does
        # not publish anything — set_state below is this child's own, local.
        # ``type(parent)``, not an imported ``AgentSession``: see the note above
        # ``_copy_messages`` for why this module cannot name the class.
        child = type(parent)(
            provider_name=parent.provider_name, model=parent.model, bus=parent.bus
        )
        child._mode = mode
        child._permission = permission
        # The child keeps its own fresh state object WITHOUT publishing it:
        # ``set_state`` publishes to the process-global the parent's prompt
        # reads, which is exactly the hijack this phase exists to prevent. A
        # child never renders a prompt block from the global — it renders its
        # own (empty) state through self.state, so a plain assignment is the
        # honest adopt.
        child.state = SessionState()
        child.max_tool_calls = parent.max_tool_calls
        # Share the provider *object*, not a rebind: a second provider would
        # mean a second HTTP client-cache and a second reasoning-spec lookup
        # to disagree with the parent's.
        child.provider = parent.provider
        child.base_url = parent.base_url
        child.model = parent.model

        name = self._unique_name(name_hint or "subagent")
        # Attribution, set before the child can emit anything: every frame it
        # sends from here on says whose name and which call it is. Empty when
        # nothing is running this spawn (a direct test or script call), and the
        # window then treats the child's frames as a foreign turn -- exactly
        # the behavior before nested UI existed.
        child.subagent_name = name
        child.subagent_call_id = call_id
        # How many spawns below the top-level session this child is. Read by
        # `_drive_child` to keep nesting to `MAX_SUBAGENT_DEPTH`.
        child.subagent_depth = parent.subagent_depth + 1
        handle = SubagentHandle(name=name, session=child, seed_message=seed)
        self._children[name] = handle
        return handle

    def _unique_name(self, hint: str) -> str:
        base = (hint or "subagent").strip().replace(" ", "-") or "subagent"
        name = base
        while name in self._children:
            name = f"{base}-{uuid.uuid4().hex[:4]}"
        return name

    # -- lookup --------------------------------------------------------------

    def get(self, name: str) -> SubagentHandle:
        """The one handle, or raise naming what exists."""
        handle = self._children.get(name)
        if handle is None:
            known = ", ".join(sorted(self._children)) or "none yet"
            raise SubagentError(
                f"no subagent named {name!r}. Known: {known}. "
                "Names come from the subagent call that spawned them, or "
                "list_agents."
            )
        return handle

    def snapshot(self, name: str) -> SubagentSnapshot:
        handle = self.get(name)
        session = handle.session
        return SubagentSnapshot(
            name=name,
            mode_name=session.mode_name,
            permission_name=session.permission_name,
            tool_calls_used=session._tool_calls_used,
            max_tool_calls=session.max_tool_calls,
            running=handle.running(),
            cancelled=handle.cancelled,
            finished=handle.finished,
            forked_from=handle.forked_from,
        )

    def list(self) -> list[SubagentSnapshot]:
        return [self.snapshot(name) for name in sorted(self._children)]

    # -- lifecycle -----------------------------------------------------------

    def start(self, name: str, task: asyncio.Task) -> None:
        handle = self.get(name)
        if handle.task is not None and not handle.task.done():
            raise SubagentError(f"{name} is already running")
        handle.task = task

    def interrupt(self, name: str) -> bool:
        """Stop a child. Returns whether anything was actually stopped."""
        handle = self.get(name)
        if handle.finished or (handle.task is not None and handle.task.done()):
            return False
        if handle.session._cancel is not None:
            handle.session._cancel.set()
        if handle.task is not None and not handle.task.done():
            handle.task.cancel()
        self.mark_cancelled(name)
        return True

    def mark_cancelled(self, name: str) -> None:
        """Record that this child's turn was stopped, however it stopped.

        Split from ``interrupt`` because the two are not the same event: a turn
        killed by its own deadline has already ended by the time anything looks
        at it, so ``interrupt`` correctly reports that there was nothing left to
        stop -- and would then leave the child reading as merely ``finished``
        rather than as one whose answer is not coming.
        """
        self.get(name).cancelled = True

    def mark_finished(self, name: str) -> None:
        handle = self.get(name)
        handle.finished = True

    def fork(
        self,
        source_name: str,
        parent: AgentSession,
        name_hint: str = "",
        call_id: str = "",
    ) -> SubagentHandle:
        """Start a second child from a copy of the first one's conversation.

        What a fork is for: the copied transcript already holds what the source
        read, tried and concluded, so the new child starts from that instead of
        being told about it. That only works if the source is *between* turns —
        a child mid-turn has a transcript that is still being written, and a
        copy of it would be a copy of a half-finished thought.

        The copy is per message, and the message payloads (``tool_calls``,
        ``reasoning_details``) are copied too. Two transcripts sharing one list
        object is the kind of aliasing that shows up later as one child's tool
        call appearing in the other's history, which is the one thing a fork
        must not do. The original is not touched anywhere in here.
        """
        source = self.get(source_name)
        if source.task is not None and not source.task.done():
            raise SubagentError(
                f"{source_name} is still running, so its conversation is still "
                "being written. Wait for it, or fork one that has finished."
            )
        handle = self.spawn(
            parent,
            seed="",
            name_hint=name_hint or f"{source_name}-fork",
            call_id=call_id,
        )
        handle.forked_from = source_name
        handle.session.messages = _copy_messages(source.session.messages)
        return handle

    def restart(self) -> None:
        """Drop every child. A host act, called when the conversation resets.

        The fan-out pool is reset with them: it is the other half of the same
        state (what is running), and leaving four child turns' worth of permits
        held by a conversation nobody is looking at would quietly serialise the
        next one.
        """
        for handle in list(self._children.values()):
            if handle.task is not None and not handle.task.done():
                handle.task.cancel()
        self._children.clear()
        _child_slots.reset()

    # -- answers -------------------------------------------------------------

    def final_answer(self, name: str, since: int = 0) -> str:
        """The child's last assistant text, or raise naming the absence.

        The parent asked for conclusions, not a transcript: the last assistant
        message is the one that answered. A child with none (cancelled before
        its first pass, a dead provider) raises so the tool says *why* there
        is no answer rather than returning an empty string that reads as
        silent success.

        ``since`` is the transcript length when *this* turn started, and it is
        not optional in practice once a child can be talked to twice: without it
        a follow-up whose provider died answers with the *previous* turn's text,
        so ``send_message`` reports stale work as the reply it just asked for.
        The state text is about this turn too -- "cancelled" describes the turn
        that was cancelled, not some earlier one.
        """
        handle = self.get(name)
        for message in reversed(handle.session.messages[since:]):
            if message.role_value == "assistant" and message.content:
                return message.content
        state = "cancelled" if handle.cancelled else "it stopped without an answer"
        raise SubagentError(f"{name} has no answer: {state}.")


#: The process-wide registry — one per core, by the same argument that makes
#: ``jobs_registry`` one: it owns live tasks, and the window is one process.
subagent_registry = SubagentRegistry()


# -- who is asking ------------------------------------------------------------


def _running_session() -> AgentSession:
    """The session whose turn is running, or explain that none is.

    This was a module global with a set/forget pair around ``_run_turn``, which
    a parent and its child could not both use truthfully — the child's turn
    runs *inside* the parent's, so one global would have had to hold two
    sessions. It is the tool context now (``tools/context.py``), which nests.
    """
    session = current_context().session
    if session is None:
        raise SubagentError("no turn is running; subagent is a turn-scoped call")
    return session


def _caller_call_id() -> str:
    """The id of the tool call running this, or "" when none is.

    The orchestrator publishes the executing call for the duration of a tool's
    run — a ``ContextVar``, because a parallel batch runs several at once. A
    direct call (a test, the e2e script) has none, and the child then carries
    no link to any card; there is no card for it to belong to.
    """
    return current_context().call_id


# -- running a child ----------------------------------------------------------

async def _child_turn(session: AgentSession, seed: str) -> None:
    """Exactly one child turn: the session's own loop, its own cancel event."""
    session.messages.append(ChatMessage(role=MessageRole.USER, content=seed))
    session._cancel = asyncio.Event()
    session._busy = True
    try:
        await session._run_turn(uuid.uuid4().hex)
    finally:
        session._busy = False


async def _drive_child(
    handle: SubagentHandle, message: str, parent: AgentSession
) -> ToolResult:
    """Run one child turn, and the one place a fan-out is admitted.

    **The one place a child's turn starts**, for all three verbs. ``subagent``
    hands it a fresh child and its brief; ``send_message`` hands it an existing
    child and the next thing to say to it; ``subagent_fork`` hands it a copied
    child and the brief the copy exists for. The loop below — attribution, the
    serial *task*, the deadline, the three failure shapes — is identical for all
    three, and keeping it in one function is what stops a follow-up turn from
    quietly behaving differently from a first one.

    **Three bounds live here, and each answers a different question:**

    * *one turn per child* — a turn appends to the child's transcript, so two
      turns of one child at once would interleave into one conversation. Per
      child, not process-wide: two *different* children at once is the point.
    * *``MAX_CHILDREN_PER_TURN``* — how many children this parent turn may
      start. See the constant for why the parent's budget is not enough by
      itself.
    * *``MAX_CONCURRENT_CHILDREN``* — how many run at once, taken as a slot
      inside the child's own task (see ``_ChildSlots``).

    The first two are decided *synchronously*, before the first ``await``: two
    verbs racing inside one batch must not both pass them and then both claim
    the same child, or the same last child of the turn's allowance.
    """
    name = handle.name

    # Not the *global* serial gate this replaced. Children run in parallel now;
    # what is still one-at-a-time is one child's own turns.
    if handle.running():
        return ToolResult(
            status=ToolResultStatus.ERROR,
            output=None,
            summary=f"subagent {name} is already running a turn",
            error=(
                f"Subagent {name} is already running a turn. One child runs one "
                "turn at a time -- wait for it, or interrupt it first. Other "
                "children may run alongside this one; this is only about this "
                "child."
            ),
        )

    if parent.subagent_depth >= MAX_SUBAGENT_DEPTH:
        return ToolResult(
            status=ToolResultStatus.ERROR,
            output=None,
            summary=f"subagent {name} not started: nesting is one level deep",
            error=(
                "A subagent cannot spawn subagents: children are one level "
                f"deep ({name!r} is at depth {parent.subagent_depth + 1}). Do "
                "this work in the child's own turn, or ask the top-level agent "
                "for it directly."
            ),
        )

    if parent._children_started >= MAX_CHILDREN_PER_TURN:
        return ToolResult(
            status=ToolResultStatus.ERROR,
            output=None,
            summary=f"subagent {name} not started: this turn's limit",
            error=(
                f"This turn has already started {MAX_CHILDREN_PER_TURN} subagent "
                f"turns, which is the limit, so {name!r} was not run. It exists "
                "and can still be given a turn later with send_message; answer "
                "from the results you already have, or start the rest in your "
                "next turn."
            ),
        )

    parent._children_started += 1
    # This turn's frames belong to the call asking for it, which is not
    # necessarily the call that created the child. Stamped before the turn
    # starts, so nothing it emits can land under the wrong card. A ContextVar
    # read, so a batch of verbs running concurrently each read their own call.
    handle.session.subagent_call_id = _caller_call_id()
    handle.cancelled = False
    # Where this turn begins. Everything the answer is read from has to come
    # after it, or a follow-up that produced nothing would be answered with the
    # transcript of the turn before it. See ``final_answer``.
    started_at = len(handle.session.messages)

    async def runner() -> None:
        # The slot is taken *inside* the child's own task, not around it. The
        # task therefore exists the instant the verb above was admitted, so
        # `interrupt_agent` can reach a child that is still queued, `list_agents`
        # calls it running, and -- the subtle one -- the deadline below starts
        # when the child starts thinking rather than when it joined the queue.
        async with _child_slots.slot():
            await asyncio.wait_for(
                _child_turn(handle.session, message), timeout=CHILD_TURN_TIMEOUT_S
            )

    task = asyncio.create_task(runner(), name=f"subagent:{name}")
    subagent_registry.start(name, task)
    try:
        # No timeout here: the deadline is the child's own, inside its task.
        # Wrapping this in another one would charge the child for the time it
        # spent waiting for a slot, which is the queue's cost and not its own.
        await asyncio.shield(task)
    except asyncio.CancelledError:
        # Two cancels arrive here and only one is ours. The OUTER one — the
        # parent's tool call cancelled by a user stop — must keep propagating,
        # or a stopped turn would answer as if it had finished thinking. The
        # INNER one — the child's task cancelled by interrupt_agent — must NOT
        # propagate: shield re-raises the child's cancellation into this
        # awaiter, and a raise would answer a model-visible call with an
        # exception the orchestrator paraphrases into nothing diagnostic. The
        # task's own state is the only witness that can tell the two apart.
        if task.cancelled():
            return ToolResult(
                status=ToolResultStatus.ERROR,
                output=None,
                summary=f"subagent {name} was interrupted",
                error=(
                    f"Subagent {name} was interrupted before it answered. Its "
                    "partial work is discarded; do the task inline or spawn a "
                    "replacement with a tighter brief."
                ),
            )
        subagent_registry.interrupt(name)
        raise
    except asyncio.TimeoutError:
        # Raised by the child's own task, which is already unwinding: the shield
        # means the parent gets its answer now while the child finishes its
        # finally-blocks. `interrupt` cannot report it (the task has ended), so
        # the snapshot is told directly -- `cancelled` is how the window and
        # `list_agents` learn that this child's answer is not coming.
        registry_int = subagent_registry.interrupt(name)
        subagent_registry.mark_cancelled(name)
        logger.warning(f"subagent {name} timed out (interrupted: {registry_int})")
        return ToolResult(
            status=ToolResultStatus.ERROR,
            output=None,
            summary=f"subagent {name} timed out",
            error=(
                f"Subagent {name} ran past {CHILD_TURN_TIMEOUT_S:.0f}s and was "
                "cancelled. Split the task into smaller subagents, or do it "
                "inline within your own budget."
            ),
        )
    finally:
        subagent_registry.mark_finished(name)

    try:
        answer = subagent_registry.final_answer(name, since=started_at)
    except SubagentError as exc:
        return ToolResult(
            status=ToolResultStatus.ERROR,
            output=None,
            summary=f"subagent {name} produced no answer",
            error=str(exc),
        )
    snap = subagent_registry.snapshot(name)
    budget = (
        f"{snap.tool_calls_used}/{snap.max_tool_calls} tool calls"
        if snap.max_tool_calls
        else f"{snap.tool_calls_used} tool calls, no limit"
    )
    return ToolResult(
        status=ToolResultStatus.SUCCESS,
        output=answer,
        summary=f"subagent {name}: {budget}",
    )


@register_tool
class SubagentTool(Tool):
    """Delegate a bounded, self-contained task to a fresh child session.

    The child runs inside this call. Use it for leaf work whose *conclusions*
    are what the parent needs, and that is big enough that doing it inline would
    spend the parent's whole budget. Declare several of these in one message to
    fan out: they run together, up to ``MAX_CONCURRENT_CHILDREN`` at once.
    """

    name = "subagent"
    description = (
        "Delegate a task to a fresh child session and wait for its answer. "
        "The child has its own transcript and its own tool-call budget; only "
        "its final answer reaches you. Ask for several in one message to run "
        "them together -- each answer comes back under its own call."
    )
    category = ToolCategory.UTILITY
    parameters = {
        "type": "object",
        "properties": {
            "task": {
                "type": "string",
                "description": (
                    "The task, self-contained: the child sees only this text "
                    "and its own work — not your conversation, not your plan."
                ),
            },
            "name": {
                "type": "string",
                "description": (
                    "Short name to address this agent by in list_agents and "
                    "interrupt_agent. Optional; a default is generated."
                ),
            },
        },
        "required": ["task"],
        "additionalProperties": False,
    }
    folder_required = False
    destructive = False
    requires_confirmation = False

    async def execute(self, task: str, name: str = "") -> ToolResult:
        task = (task or "").strip()
        if not task:
            return ToolResult(
                status=ToolResultStatus.ERROR,
                error=(
                    "subagent needs a task. Say what the child should do, "
                    "self-contained — it cannot see this conversation."
                ),
            )
        try:
            parent = _running_session()
        except SubagentError as exc:
            return ToolResult(status=ToolResultStatus.ERROR, error=str(exc))
        refusal = _refuse_without_a_provider(parent)
        if refusal is not None:
            return ToolResult(status=ToolResultStatus.ERROR, error=refusal)
        handle = subagent_registry.spawn(
            parent,
            seed=task,
            name_hint=(name or "").strip(),
            call_id=_caller_call_id(),
        )
        return await _drive_child(handle, task, parent)


def _refuse_without_a_provider(session: AgentSession) -> str | None:
    """The one refusal every verb that *starts a turn* shares.

    It used to be two, and the other one -- "one subagent runs at a time" -- is
    gone on purpose: fan-out is what this phase is for, and the bounds that
    replaced it are in ``_drive_child`` (one turn per child, a per-turn cap, and
    a concurrency queue). None of them is a reason to refuse a call before it is
    tried, which is what this check had become.

    What is left is the check no bound replaces: a child with no provider has
    nothing to think with. Asked before the child is spawned, so the failure the
    model reads is about the provider rather than about a tool.
    """
    if session.provider is None:
        return (
            "no provider is bound in this session, so the subagent would have "
            "nothing to think with. Bind one first."
        )
    return None


@register_tool
class SendMessageTool(Tool):
    """Give a subagent you already spawned another turn.

    The difference from ``subagent`` is *which* child: this one keeps the
    transcript it already has, so the message is a continuation of that work
    rather than a new brief. That is the whole point of the tool — a child that
    read a file, tried something and said what it found is worth asking a
    follow-up question that starts from what it knows.

    It is mutating, and sits in the same mode set as ``subagent``, for the same
    reason: the child's turn really runs, spending the child's own budget under
    the parent's permission and mode.
    """

    name = "send_message"
    description = (
        "Send another message to a subagent you already spawned. It keeps its "
        "transcript, so use this to follow up on work it has done rather than "
        "restating the task. Waits for its answer."
    )
    category = ToolCategory.UTILITY
    parameters = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "The subagent's name."},
            "message": {
                "type": "string",
                "description": (
                    "What to say to it. It can see its own earlier turn, so "
                    "this can refer to what it already did."
                ),
            },
        },
        "required": ["name", "message"],
        "additionalProperties": False,
    }
    folder_required = False
    destructive = False
    requires_confirmation = False

    async def execute(self, name: str, message: str) -> ToolResult:
        name = (name or "").strip()
        message = (message or "").strip()
        if not name or not message:
            return ToolResult(
                status=ToolResultStatus.ERROR,
                error=(
                    "send_message needs both the subagent's name and the "
                    "message. list_agents names the ones that exist."
                ),
            )
        try:
            parent = _running_session()
            handle = subagent_registry.get(name)
        except SubagentError as exc:
            return ToolResult(status=ToolResultStatus.ERROR, error=str(exc))
        refusal = _refuse_without_a_provider(parent)
        if refusal is not None:
            return ToolResult(status=ToolResultStatus.ERROR, error=refusal)
        return await _drive_child(handle, message, parent)


@register_tool
class ForkSubagentTool(Tool):
    """Copy a subagent's conversation into a new one and give it a task.

    The source child is left exactly as it was — a fork answers "what would a
    second opinion make of this?", and it does that by handing the copy the
    same transcript, not by telling it about it. Two children from here on have
    separate transcripts and separate budgets, and neither can see the other's.

    The copy inherits this session's mode and permission, exactly as any child
    does: there is no argument that could widen them.
    """

    name = "subagent_fork"
    description = (
        "Fork a subagent: copy its conversation into a new subagent and give "
        "that copy a task. The original is untouched. Use it to explore a "
        "different approach from work already done, without redoing it."
    )
    category = ToolCategory.UTILITY
    parameters = {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "The subagent whose conversation to copy.",
            },
            "task": {
                "type": "string",
                "description": (
                    "What the copy should do, given the conversation it "
                    "inherits."
                ),
            },
            "new_name": {
                "type": "string",
                "description": (
                    "Name for the copy. Optional; defaults to the original's "
                    "name with a suffix."
                ),
            },
        },
        "required": ["name", "task"],
        "additionalProperties": False,
    }
    folder_required = False
    destructive = False
    requires_confirmation = False

    async def execute(self, name: str, task: str, new_name: str = "") -> ToolResult:
        name = (name or "").strip()
        task = (task or "").strip()
        if not name:
            return ToolResult(
                status=ToolResultStatus.ERROR,
                error="subagent_fork needs the subagent to copy. list_agents names them.",
            )
        if not task:
            return ToolResult(
                status=ToolResultStatus.ERROR,
                error=(
                    "subagent_fork needs a task for the copy: the conversation "
                    "it inherits says where it starts, not what to do next."
                ),
            )
        try:
            parent = _running_session()
            handle = subagent_registry.fork(
                name,
                parent,
                name_hint=(new_name or "").strip(),
                call_id=_caller_call_id(),
            )
        except SubagentError as exc:
            return ToolResult(status=ToolResultStatus.ERROR, error=str(exc))
        refusal = _refuse_without_a_provider(parent)
        if refusal is not None:
            # The fork exists by now, and a child with no turn run stays in
            # ``list_agents`` as ready. Leaving it is the honest outcome: the
            # copy was made, its turn was not, and `send_message` can still give
            # it one. It is *not* interrupted -- nothing about it failed.
            return ToolResult(status=ToolResultStatus.ERROR, error=refusal)
        return await _drive_child(handle, task, parent)


@register_tool
class ListAgentsTool(Tool):
    """Report every subagent this process has spawned, finished or not."""

    name = "list_agents"
    description = (
        "List the subagents spawned so far: name, mode, permission, and how "
        "much of their tool budget they have spent."
    )
    category = ToolCategory.UTILITY
    parameters = {
        "type": "object",
        "properties": {},
        "required": [],
        "additionalProperties": False,
    }
    folder_required = False
    destructive = False
    requires_confirmation = False

    async def execute(self) -> ToolResult:
        agents = subagent_registry.list()
        if not agents:
            return ToolResult(
                status=ToolResultStatus.SUCCESS,
                output="No subagents have been spawned.",
                summary="no subagents",
            )
        rows = []
        for snap in agents:
            state = (
                "running"
                if snap.running
                else "cancelled"
                if snap.cancelled
                else "finished"
                if snap.finished
                else "ready"
            )
            limit = snap.max_tool_calls if snap.max_tool_calls else "no limit"
            # A fork is worth saying out loud: two children holding the same
            # conversation are otherwise indistinguishable in this list, and
            # which one is which is the first thing a reader needs.
            forked = (
                f", forked from {snap.forked_from}" if snap.forked_from else ""
            )
            rows.append(
                f"- {snap.name}: {state}, mode {snap.mode_name}, "
                f"permission {snap.permission_name}, "
                f"{snap.tool_calls_used} used of {limit} tool calls{forked}"
            )
        return ToolResult(
            status=ToolResultStatus.SUCCESS,
            output="\n".join(rows),
            summary=f"{len(agents)} subagent(s)",
        )


@register_tool
class InterruptAgentTool(Tool):
    """Stop a subagent whose work is no longer worth waiting for."""

    name = "interrupt_agent"
    description = (
        "Cancel a running subagent by name. Use when its task has drifted "
        "from what you asked, or when you no longer need its answer."
    )
    category = ToolCategory.UTILITY
    parameters = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "The subagent's name."},
        },
        "required": ["name"],
        "additionalProperties": False,
    }
    folder_required = False
    destructive = False
    requires_confirmation = False

    async def execute(self, name: str) -> ToolResult:
        name = (name or "").strip()
        if not name:
            return ToolResult(
                status=ToolResultStatus.ERROR,
                error="interrupt_agent needs the subagent's name. list_agents names them.",
            )
        try:
            was_running = subagent_registry.interrupt(name)
        except SubagentError as exc:
            return ToolResult(status=ToolResultStatus.ERROR, error=str(exc))
        if not was_running:
            return ToolResult(
                status=ToolResultStatus.ERROR,
                error=(
                    f"{name} was not running, so there was nothing to "
                    "interrupt. list_agents shows what state each is in."
                ),
            )
        return ToolResult(
            status=ToolResultStatus.SUCCESS,
            output=f"{name} was interrupted. Its answer, if any, was discarded.",
            summary=f"interrupted {name}",
        )
