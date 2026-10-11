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
write into its transcript; the parent reads only the child's final answer.
Peer messaging arrives with the workflow phase (Phase 6), which needs a session
loop with a place to be re-entered.

**Serial by construction.** One child turn runs at a time. The child call
spends one of the *parent's* tool-call budget slots (it is one of the parent's
tool calls, in the parent's transcript), while the work the child does spends
the child's own budget. That is what keeps a fan-out of subagents from being
an unbounded spend under a capped parent.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional

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
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from tonyagent.core.session import AgentSession

# ``core.session`` imports ``tonyagent.tools`` (for the schema list), so a
# module-level import here would close a circle the package layout cannot
# survive: ``tools/__init__`` is mid-import when this module loads. The import
# below runs on first *use*, by which point both sides are initialised. Every
# other tool module avoids this by never needing the session; subagents are
# the first that does, and the comment is the reason this stays local.


def _agent_session_cls():
    from tonyagent.core.session import AgentSession

    return AgentSession

#: Longest one child turn may run, seconds.
#:
#: A child cannot have the parent's judgement, only its own bound. Generous on
#: purpose: an honest child only ever meets this on a provider request that
#: would otherwise hang the parent turn forever.
CHILD_TURN_TIMEOUT_S = 120.0


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


@dataclass
class SubagentHandle:
    """One live child and the task carrying its turn."""

    name: str
    session: AgentSession
    seed_message: str
    task: Optional[asyncio.Task] = None
    cancelled: bool = False
    finished: bool = False


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
    ) -> SubagentHandle:
        """Build a child session for this parent and record it.

        The child inherits the parent's mode and permission — permission may
        only *narrow*, and these are already the narrowest the parent has. It
        gets the parent's per-turn budget as its own ceiling, and the seed
        message is the only user turn it will ever read.
        """
        mode: Mode = parent._mode
        permission: Permission = parent._permission
        # Children never read the parent's conversation, plan or reasoning
        # effort: the seed alone decides what the child is for, and whatever
        # the parent was planning is the parent's business. Construction does
        # not publish anything — set_state below is this child's own, local.
        child = _agent_session_cls()(
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
            running=handle.task is not None and not handle.task.done(),
            cancelled=handle.cancelled,
            finished=handle.finished,
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
        handle.cancelled = True
        return True

    def mark_finished(self, name: str) -> None:
        handle = self.get(name)
        handle.finished = True

    def restart(self) -> None:
        """Drop every child. A host act, called when the conversation resets."""
        for handle in list(self._children.values()):
            if handle.task is not None and not handle.task.done():
                handle.task.cancel()
        self._children.clear()

    # -- answers -------------------------------------------------------------

    def final_answer(self, name: str) -> str:
        """The child's last assistant text, or raise naming the absence.

        The parent asked for conclusions, not a transcript: the last assistant
        message is the one that answered. A child with none (cancelled before
        its first pass, a dead provider) raises so the tool says *why* there
        is no answer rather than returning an empty string that reads as
        silent success.
        """
        handle = self.get(name)
        for message in reversed(handle.session.messages):
            if message.role_value == "assistant" and message.content:
                return message.content
        state = "cancelled" if handle.cancelled else "it stopped without an answer"
        raise SubagentError(f"{name} has no answer: {state}.")


#: The process-wide registry — one per core, by the same argument that makes
#: ``jobs_registry`` one: it owns live tasks, and the window is one process.
subagent_registry = SubagentRegistry()


# -- the turn's parent --------------------------------------------------------

#: The session whose turn is running. A tool is a stateless singleton, so the
#: parent reaches it this way rather than through a per-tool field — the same
#: reason ``folder_manager`` exists at all. Set when the turn starts, cleared
#: when it unwinds, so no later call inherits a stale pointer.
_PARENT: Optional[AgentSession] = None


def record_parent(session: AgentSession) -> None:
    global _PARENT
    _PARENT = session


def forget_parent() -> None:
    global _PARENT
    _PARENT = None


def _current_parent() -> AgentSession:
    if _PARENT is None:
        raise SubagentError(
            "no turn is running; subagent is a turn-scoped call"
        )
    return _PARENT


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


async def _run_and_answer(handle: SubagentHandle) -> ToolResult:
    """Run the child to completion and shape what the parent's model reads."""
    name = handle.name

    async def runner() -> None:
        await _child_turn(handle.session, handle.seed_message)

    task = asyncio.create_task(runner(), name=f"subagent:{name}")
    subagent_registry.start(name, task)
    try:
        await asyncio.wait_for(asyncio.shield(task), timeout=CHILD_TURN_TIMEOUT_S)
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
        # The shield lets the child keep unwinding its own finally-blocks
        # while the parent gets its answer now.
        registry_int = subagent_registry.interrupt(name)
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
    except asyncio.CancelledError:
        # The parent's call itself was cancelled (user stop). Stop the child
        # with it, and let the parent's own CancelledError propagate.
        subagent_registry.interrupt(name)
        raise
    finally:
        subagent_registry.mark_finished(name)

    try:
        answer = subagent_registry.final_answer(name)
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

    Serial by construction — the child runs inside this call. Use it for leaf
    work whose *conclusions* are what the parent needs, and that is big enough
    that doing it inline would spend the parent's whole budget.
    """

    name = "subagent"
    description = (
        "Delegate a task to a fresh child session and wait for its answer. "
        "The child has its own transcript and its own tool-call budget; only "
        "its final answer reaches you. One subagent runs at a time."
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
            parent = _current_parent()
        except SubagentError as exc:
            return ToolResult(status=ToolResultStatus.ERROR, error=str(exc))
        # Serialiser invariant FIRST, before the provider check: a model
        # waiting on concurrency deserves the concurrency answer, not a
        # different complaint about a provider it already knows is bound.
        for snapshot in subagent_registry.list():
            if snapshot.running:
                return ToolResult(
                    status=ToolResultStatus.ERROR,
                    error=(
                        f"subagent {snapshot.name!r} is still running; one "
                        "subagent runs at a time. Wait for it, or interrupt "
                        "it first."
                    ),
                )
        if parent.provider is None:
            return ToolResult(
                status=ToolResultStatus.ERROR,
                error=(
                    "no provider is bound in this session, so the subagent "
                    "would have nothing to think with. Bind one first."
                ),
            )
        handle = subagent_registry.spawn(
            parent, seed=task, name_hint=(name or "").strip()
        )
        return await _run_and_answer(handle)


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
            rows.append(
                f"- {snap.name}: {state}, mode {snap.mode_name}, "
                f"permission {snap.permission_name}, "
                f"{snap.tool_calls_used} used of {limit} tool calls"
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
