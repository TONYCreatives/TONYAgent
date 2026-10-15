"""UI-agnostic conversation session - the headless agent core.

This is the piece that lets TONYAgent run without a display. It owns message
history, provider selection and the tool loop, and reports everything it does
through :class:`~tonyagent.core.events.EventBus`. It imports no GUI toolkit, so
it can be driven by a Tauri sidecar over stdio, or by a test.

The behaviour previously lived inside the Tkinter UI's ``_generate_response`` mixed
together with widget updates. Extracting it is what makes the core reusable: a
new frontend only sends text in and renders events out.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any, Optional

from loguru import logger

from tonyagent.api import LLMError
from tonyagent.api.dialects import ReasoningSpec
from tonyagent.core.attachments import build_parts
from tonyagent.core.events import Event, EventType, bus as default_bus
from tonyagent.core.modes import (
    DEFAULT_MODE,
    DEFAULT_PERMISSION,
    TOOL_CALL_ECONOMY,
    tool_budget_note,
    Mode,
    Permission,
    get_mode,
    get_permission,
)
from tonyagent.providers import (
    ChatCompletionChunk,
    ChatMessage,
    ProviderFactory,
    ToolChoice,
    ToolSchema,
)
from tonyagent.providers.base import MessageRole
from tonyagent.core import user_io
from tonyagent.core.skills import SkillInvocation, invocation_for
from tonyagent.folder.manager import folder_manager
from tonyagent.core.task_state import SessionState, set_current_state
from tonyagent.tools import ALL_SCHEMAS, ToolCall, ToolResult, tool_orchestrator
from tonyagent.tools.context import use_context

#: Said when a model used its whole token allowance thinking and wrote nothing.
#: The tokens are billed either way, so the user needs to know the difference
#: between a model that over-thought and one that failed outright.
_THINKING_BUDGET_NOTICE = (
    "The model spent its whole token budget thinking and stopped before "
    "writing an answer. It was still billed for that thinking. Try a model "
    "that reasons faster, or ask for something smaller."
)


def _results_digest(orders: list[int]) -> str:
    """Build the assistant note that stands in for an unanswered tool result.

    ``orders`` is the 1-based numbering of the rounds the turn executed; the
    note lists them so the model's next call can reference a specific tool
    result instead of guessing which one it means.
    """
    order_note = "".join(f"\n[result {n}]" for n in orders)
    return (
        "Tool results are above. The conversation cannot continue with a tool "
        "result, so this note stands in for the next assistant turn."
        + order_note
    )


#: Sentinel for "the model's thinking has not been looked up yet". Distinct
#: from None, which means "looked up; it does not reason".
_UNRESOLVED = object()


def _default_max_tool_calls() -> int:
    """The per-turn tool budget, from settings, with a floor of one.

    A limit of zero would refuse every tool, which is not a small budget --
    it is a different product, expressed by removing tools from the model
    list. So the floor is one call rather than none.
    """
    try:
        from tonyagent.config.settings import settings

        stored = int(settings.tools.max_tool_calls)
        # 0 is the no-limit sentinel and survives a restart; anything below it
        # was never a budget and is corrected to the floor.
        return stored if stored == 0 else max(1, stored)
    except Exception as exc:  # noqa: BLE001 - a bad setting must not stop a launch
        logger.warning(f"Could not read max_tool_calls; using 10: {exc}")
        return 10


class SessionCancelled(Exception):
    """Raised when the user stops a turn."""


class AgentSession:
    """One conversation with one provider.

    A session is cheap to create and holds no GUI state, so a frontend can keep
    one per window and rebind it when the provider changes.
    """

    def __init__(
        self,
        provider_name: str = "openrouter",
        model: str = "",
        bus: Any = None,
    ) -> None:
        self.bus = bus or default_bus
        self.provider_name = provider_name
        self.model = model
        #: Optional endpoint override typed by the user. Empty means "use the
        #: provider default" (OpenRouter's own API, the `custom` section's
        #: base_url, ...). Stored so `state` can report it back to a window
        #: that reloaded, and so the settings panel reopens pre-filled.
        self.base_url: str = ""
        #: How hard to ask the model to think. "" means "whatever the model
        #: defaults to", which is also what a model with no effort dial gets.
        self.reasoning_effort: str = ""
        self.messages: list[ChatMessage] = []
        #: Set by ``SubagentRegistry.spawn`` when this session is a child: its
        #: name, and the id of the parent tool call that spawned it. Every
        #: frame the child emits then says so, which is what lets the window
        #: render the child's work under that call's card instead of ignoring
        #: it as a foreign turn. Empty for every ordinary session.
        self.subagent_name: str = ""
        self.subagent_call_id: str = ""
        #: How many spawns below the session the user is talking to this one is:
        #: 0 for an ordinary session, 1 for a child, 2 for a child of a child.
        #: Set by ``SubagentRegistry.spawn`` and read as the nesting bound.
        self.subagent_depth: int = 0
        self.provider: Any = None
        self._cancel: Optional[asyncio.Event] = None
        self._busy = False
        #: Confirmation prompts this session has put on screen and not yet seen
        #: answered, by tool-call id. The session owns this because the dialog is
        #: *its* event: the orchestrator publishes nothing when a prompt is
        #: abandoned, so the turn's end is the only place that can take down a
        #: prompt whose turn is gone. See `_close_open_confirmations`.
        self._open_confirmations: set[str] = set()
        #: What the provider said about this model's thinking, resolved once.
        #: ``_UNRESOLVED`` rather than None because "not looked up yet" and
        #: "looked up, does not reason" lead to the same request but only one
        #: of them should cost a network call.
        self._reasoning_spec: Any = _UNRESOLVED
        #: Composer mode. Governs the system prompt and which tools exist.
        self._mode: Mode = get_mode(DEFAULT_MODE)
        # The permission level, intersecting with the mode. Separate from
        # `max_tool_calls` because it changes what the agent may *do* rather
        # than how much, and it is worth being able to raise the budget without
        # also handing over the keys.
        self._permission: Permission = get_permission(DEFAULT_PERMISSION)
        #: 1-based tool-round numbers executed in the turn in flight, so the
        #: closing digest can name the results the model just produced.
        self._round_orders: list[int] = []
        #: Individual tool calls already spent in the turn in flight. Counted
        #: per call rather than per round, so a model that asks for five tools
        #: in one message has spent five and the number on the card is the
        #: number of things that were actually run.
        self._tool_calls_used: int = 0
        #: Child turns started in the turn in flight. Reset with the counters
        #: above, and read by `subagent_tools` as the cap on fan-out: the
        #: per-turn tool budget bounds how many children a turn may *ask for*,
        #: but it can be set to "no limit" (`0`), and this is the backstop that
        #: stops that setting from meaning "spawn without bound". It lives here
        #: rather than in the registry because "per turn" is session state, and
        #: this is the one place a turn's counters are reset -- a child has its
        #: own counter, on its own turn, for free.
        self._children_started: int = 0
        #: The tool calls this session has in flight, one task each.
        #:
        #: Held so that `cancel()` can stop a call that is already running -- a
        #: flag is only polled between rounds, and a tool that awaits can run for
        #: a minute. Registered in `_start_tool_call` and dropped by a
        #: done-callback, so the set is empty whenever nothing is running.
        self._tool_tasks: set[asyncio.Task] = set()
        #: The skill this turn was asked for with `/name`, resolved once at the
        #: start of the turn. Per turn rather than per conversation because it
        #: is an *invocation* -- the user typed `/review` on this message -- and
        #: a session that kept it would keep following a procedure nobody asked
        #: for again. Cleared in the turn's `finally`, beside `_busy`.
        self._active_skill: SkillInvocation | None = None
        #: The per-turn tool budget, read once at construction so a mid-turn
        #: settings change cannot make the counter and the label disagree.
        self.max_tool_calls: int = _default_max_tool_calls()
        #: The plan and the goal for this conversation, rendered into the system
        #: prompt and written by the planning tools. Adopted through `set_state`
        #: so the tools and this session hold the *same* object -- see there.
        #:
        #: **Construction does not publish it.** That used to happen here as a
        #: side effect (`set_current_state(self.state)`), and it read as nothing:
        #: in the one-session-per-process world whatever session was built last
        #: owned the global, which is what the conversation flow always wanted
        #: anyway. A subagent is the first thing that makes it wrong -- a child
        #: session built while the parent's turn is in flight would silently
        #: repoint the planning tools at the child's plan, and the parent's next
        #: turn would render a task list nobody in the conversation wrote.
        #: Publishing is `set_state`'s one job now, called explicitly by the
        #: host -- the same lesson `install_question_bridge` taught (publishing
        #: to a process-global is a host act, not a consequence of building
        #: something). ``tests/unit/test_subagent_isolation.py`` pins it.
        self.state: SessionState = SessionState()

    # -- provider ------------------------------------------------------------
    def bind_provider(
        self, provider_name: str, model: str = "", base_url: str = ""
    ) -> Any:
        """Point this session at a provider. Returns the provider or None.

        ``model`` and ``base_url`` are both free text: the model list a provider
        ships with is a set of suggestions, not a closed set. OpenRouter alone
        carries hundreds of namespaced ids (``anthropic/claude-sonnet-4.5``,
        ``deepseek/deepseek-chat:free``) and self-hosted gateways use ids the
        registry has never heard of, so the UI must be able to type one in.
        """
        self.provider_name = provider_name
        self.base_url = base_url
        self.provider = ProviderFactory.create_provider(
            provider_name, model=model, base_url=base_url
        )
        # A new provider, or a new model, is a different answer to "can this
        # think, and how hard". Cached against the old one would ask the new
        # model to be told an effort it never offered.
        self._reasoning_spec = _UNRESOLVED
        if self.provider is None:
            self.model = model
            self.emit(EventType.ERROR, {"message": f"Unknown provider: {provider_name}"})
            return None
        # Record the model actually in force, not the one that was requested.
        # An empty request falls back to the provider's own default, and if
        # `state` echoed the empty request a reloaded window would show a model
        # that is not the one being sent.
        self.model = getattr(self.provider, "model", "") or model
        return self.provider

    @property
    def busy(self) -> bool:
        return self._busy

    # -- events --------------------------------------------------------------
    def emit(
        self,
        type: EventType,
        payload: Optional[dict[str, Any]] = None,
        turn_id: Optional[str] = None,
    ) -> Event:
        """Publish one frame of this session's work.

        A child session's frames carry its own turn id *and* the parent call
        that owns it (see :attr:`subagent_name`); an ordinary session's carry
        neither attribution field, so the wire stays exactly as it was.
        """
        return self.bus.emit(
            type,
            payload,
            turn_id=turn_id,
            subagent=self.subagent_name,
            parent_call_id=self.subagent_call_id,
        )

    # -- public API ----------------------------------------------------------
    def cancel(self) -> None:
        """Stop the running turn. Safe to call when nothing is running.

        Three things have to stop, and each was a bug once:

        * **The turn's own loop**, via the flag `_check_cancelled` polls after
          every round.
        * **A prompt the turn raised.** A confirmation prompt counts as part of
          the turn: Stop answers it no, which releases the waiting tool
          immediately and takes the dialog down with it. Without that, Stop left
          a destructive call's Allow/Deny on screen and the tool ran to its
          60-second timeout before the turn could end.
        * **A tool call already running**, via the task it was started in. The
          flag cannot reach one -- nothing polls it while a tool awaits -- so a
          stopped turn kept working for as long as that call took: measured, a
          turn that had spawned a child lived 2.7s past Stop while the child
          finished its turn, and its tokens were billed. A stopped turn that
          keeps working is not stopped, which is the same sentence the
          confirmation fix above was written from.
        """
        if self._cancel is not None:
            self._cancel.set()
        self._close_open_confirmations()
        self._cancel_running_tools()

    def clear(self) -> None:
        """Drop the conversation history, and the plan that went with it.

        The plan goes too: a task list outliving the transcript it was written
        against is a list describing work whose context has been thrown away, and
        it would still be rendered into the prompt of the conversation that
        replaced it.
        """
        self.messages.clear()
        self.set_state(SessionState())

    def set_state(self, state: SessionState) -> None:
        """Adopt a plan and publish it to the tools that write to it.

        **Both halves, and to the same object.** The session renders the state into
        the system prompt and the planning tools mutate it, so handing the tools a
        copy would leave the model updating a plan it never sees again -- the plan
        would appear to save and then read as unchanged on the next turn.
        """
        self.state = state
        set_current_state(state)

    # -- sandbox -------------------------------------------------------------
    async def start_sandbox(self, project_path: str = "") -> bool:
        """Start the shared sandbox and report the outcome as an event.

        With no path, the folder the core already holds is used -- which is
        what the Settings panel's Start button sends, because the window is
        showing that folder and restating it would only let the two disagree.

        ``folder_manager`` is imported here rather than at module scope because
        it was previously never imported at all: every caller passed a path, so
        ``project_path or ...`` short-circuited before the name was looked up
        and the missing import went unnoticed. The pathless call -- the only
        way to restart a sandbox on an already-chosen folder -- raised
        ``NameError: folder_manager`` on every press of the new button.
        """
        from tonyagent.config.settings import settings
        from tonyagent.folder import folder_manager
        from tonyagent.sandbox import SandboxConfig, get_shared_sandbox_manager

        path = project_path or str(folder_manager.current_folder or "")
        if not path:
            self.emit(EventType.ERROR, {"message": "No project folder selected"})
            return False

        backend_type = "windows" if settings.sandbox.type == "windows" else settings.sandbox.type
        self.emit(EventType.SANDBOX_STATUS, {"status": "starting", "type": backend_type})
        config = SandboxConfig(
            project_path=path,
            type=backend_type,
            cpu_limit=settings.sandbox.cpu_limit,
            memory_limit=settings.sandbox.memory_limit,
            timeout=settings.sandbox.timeout,
            enable_network=settings.sandbox.enable_network,
            pids_limit=settings.sandbox.pids_limit,
            no_new_privileges=settings.sandbox.no_new_privileges,
            drop_capabilities=settings.sandbox.drop_capabilities,
            tmpfs_size_mb=settings.sandbox.tmpfs_size_mb,
            ulimit_nofile=settings.sandbox.ulimit_nofile,
            ulimit_nproc=settings.sandbox.ulimit_nproc,
            workspace_read_only=settings.sandbox.workspace_read_only,
            container_user=settings.sandbox.container_user,
            wsl_distro=settings.sandbox.wsl_distro,
        )
        try:
            ok = await get_shared_sandbox_manager().start(config)
        except Exception as exc:  # noqa: BLE001 - report, never crash the server
            self.emit(
                EventType.SANDBOX_STATUS,
                {"status": "stopped", "error": str(exc)},
            )
            return False
        self.emit(
            EventType.SANDBOX_STATUS,
            {
                "status": "running" if ok else "stopped",
                # Reported apart from the status so the UI can say "working, but
                # not isolated" instead of a single boolean that hides which of
                # the two the user actually got.
                "isolated": self.is_sandbox_isolated(),
            },
        )
        return bool(ok)

    def is_sandbox_isolated(self) -> bool:
        """True when code the agent generates is contained by a sandbox."""
        from tonyagent.sandbox import get_shared_sandbox_manager

        return get_shared_sandbox_manager().is_isolated()

    def sandbox_status(self) -> str:
        """Report the runtime as the session finds it right now.

        Asked by state so a reloaded window knows whether a sandbox is up
        without being told: the folder is restored from disk, but a container is
        not, so before this the panel could sit on stopped while the core was
        serving a running runtime (or the reverse).

        The same string the sandbox.status event carries, so a window that
        started the sandbox itself and a window that reloaded onto it render the
        same word.
        """
        from tonyagent.sandbox import get_shared_sandbox_manager

        return "running" if get_shared_sandbox_manager().is_running() else "stopped"

    async def stop_sandbox(self) -> None:
        """Stop the shared sandbox."""
        from tonyagent.sandbox import get_shared_sandbox_manager

        self.emit(EventType.SANDBOX_STATUS, {"status": "stopping"})
        try:
            await get_shared_sandbox_manager().stop()
        except Exception as exc:  # noqa: BLE001
            self.emit(EventType.SANDBOX_STATUS, {"status": "stopped", "error": str(exc)})
            return
        self.emit(EventType.SANDBOX_STATUS, {"status": "stopped"})

    async def sandbox_stats(self) -> dict:
        """One CPU/memory snapshot, published as an event."""
        from tonyagent.sandbox import SandboxStatus, get_shared_sandbox_manager

        backend = get_shared_sandbox_manager().get_backend()
        if backend is None or backend.status != SandboxStatus.RUNNING:
            return {}
        get_stats = getattr(backend, "get_stats", None)
        if get_stats is None:
            return {}
        try:
            stats = await get_stats()
        except Exception:  # noqa: BLE001 - stats are best-effort telemetry
            return {}
        if stats:
            self.emit(EventType.SANDBOX_STATS, dict(stats))
        return dict(stats) if stats else {}

    # -- confirmation / trust ------------------------------------------------
    def set_trusted(self, project: str, trusted: bool) -> None:
        """Trust or untrust a project folder for this session.

        Deliberately does NOT emit a log event. A frontend learns the outcome
        from the reply to its ``trust.set`` request; a push emitted first would
        break the "reply before its events" ordering the protocol guarantees.
        """
        tool_orchestrator.set_trusted(project, trusted)

    def install_confirmation_bridge(self) -> None:
        """Route tool-confirmation requests through the event bus.

        Without this the orchestrator queues a callback that only Tkinter's
        ``after()`` loop ever drains, so under a sidecar the request would
        vanish and the tool would time out after 60s. The callback stays
        synchronous by design; it only publishes an event.
        """
        tool_orchestrator.set_confirmation_callback(self._on_confirmation_requested)
        tool_orchestrator.set_log_callback(
            lambda message, level: self.emit(
                EventType.LOG, {"message": message, "level": level}
            )
        )

    def _on_confirmation_requested(self, request: Any) -> None:
        tool_call = request.tool_call
        tool = request.tool
        self._open_confirmations.add(tool_call.id)
        self.emit(EventType.CONFIRMATION_REQUESTED, {
            "id": tool_call.id,
            "name": tool_call.name,
            "arguments": tool_call.arguments,
            "description": getattr(tool, "description", ""),
            "destructive": bool(getattr(tool, "destructive", False)),
        })

    def respond_to_confirmation(self, tool_call_id: str, confirmed: bool) -> None:
        """Answer a pending confirmation request."""
        tool_orchestrator.respond_to_confirmation(tool_call_id, confirmed)
        self._open_confirmations.discard(tool_call_id)
        self.emit(
            EventType.CONFIRMATION_RESOLVED,
            {"id": tool_call_id, "confirmed": bool(confirmed)},
        )

    def _close_open_confirmations(self) -> None:
        """Answer every prompt this turn has outstanding with "no".

        Called from the end of the turn and from `cancel`, because a prompt
        cannot outlive the turn that raised it: the tool waiting for approval
        has nothing else to release it, and a dialog over a turn that has ended
        is a dialog neither button can mean anything on. Going through
        `respond_to_confirmation` rather than emitting directly is the whole
        point -- it is what also releases the orchestrator's wait, so a stopped
        turn does not leave the tool sitting out its 60-second timeout.

        A no-op when nothing is open, which is the normal case.
        """
        for call_id in sorted(self._open_confirmations):
            self.respond_to_confirmation(call_id, False)

    # -- questions / presentations -------------------------------------------
    def install_question_bridge(self) -> None:
        """Route questions and presentations through the event bus.

        The same shape as the confirmation bridge, and the same reason: a tool
        that stops the turn has to put something in front of the user, and the
        event bus is the only channel a window has. Both hooks stay synchronous
        -- they publish an event and nothing else, exactly like the
        confirmation callback, which has to run while the tool is suspended.
        """
        user_io.set_callbacks(self._on_user_asked, self._on_user_resolved)

    def _on_user_asked(self, request: Any) -> None:
        """Publish an ask. ``to_payload`` is the contract the window reads."""
        self.emit(EventType.USER_ASKED, request.to_payload())

    def _on_user_resolved(self, question_id: str, answer: str | None) -> None:
        """Take a settled ask down in the window.

        Emitted from ``user_io`` on every path that ends an ask -- answered,
        timed out, or abandoned by a cancelled turn -- so the dialog cannot
        outlive the turn that raised it.
        """
        self.emit(
            EventType.USER_RESOLVED,
            {"id": question_id, "answered": answer is not None},
        )

    def respond_to_question(self, question_id: str, answer: str) -> bool:
        """Answer a pending question. False if there was nothing to answer.

        Delegates, rather than emitting here: ``user_io`` emits
        ``user.resolved`` when it settles, so a late answer for a question that
        already timed out produces no event at all instead of a stale one.
        """
        return user_io.respond(question_id, answer)

    def send(self, text: str, attachments: list[dict] | None = None) -> str:
        """Queue a user message. Returns the turn id, or "" if rejected.

        Synchronous on purpose: the caller gets an id immediately and then
        follows the turn over the event bus, like a streaming response that
        does not block the caller.

        A rejection is reported only through the empty return value, never as
        an ERROR event. The caller turns it into the reply for this request,
        and emitting as well would put a push on the wire *before* the reply it
        belongs to, which a frontend cannot attribute.

        ``attachments`` are already-validated entries from
        :mod:`tonyagent.core.attachments`. The *typed* text may be empty when
        there are files: "what is in this screenshot?" is a message with no
        words in it, and refusing it would make the obvious use of the feature
        the one thing it cannot do.
        """
        text = (text or "").strip()
        attachments = attachments or []
        if not text and not attachments:
            return ""
        if self._busy:
            return ""
        if self.provider is None:
            return ""

        self.messages.append(ChatMessage(role="user", content=self._user_content(text, attachments)))
        turn_id = uuid.uuid4().hex
        self._cancel = asyncio.Event()
        self._busy = True
        asyncio.ensure_future(self._run_turn(turn_id))
        return turn_id

    @staticmethod
    def _user_content(text: str, attachments: list[dict]) -> str | list[dict]:
        """One message's content: a plain string, or content parts.

        A string when there is nothing attached, because that is what every
        other message in the history is and a special case for the common path
        would be a special case in every reader.
        """
        if not attachments:
            return text
        return build_parts(attachments, text)

    async def run_turn(self, text: str) -> None:
        """Run a full turn to completion.

        Convenience for scripts and tests. Real frontends use :meth:`send`,
        which returns immediately and streams over the event bus.
        """
        text = (text or "").strip()
        if not text or self._busy:
            return
        if self.provider is None:
            self.emit(EventType.ERROR, {"message": "No provider configured."})
            return
        self.messages.append(ChatMessage(role="user", content=text))
        self._cancel = asyncio.Event()
        self._busy = True
        try:
            await self._run_turn(uuid.uuid4().hex)
        finally:
            self._busy = False

    # -- turn execution ------------------------------------------------------
    # The per-turn tool budget lives in ``self.max_tool_calls`` rather than
    # being a class constant, because it is a setting the user can change and
    # because a class constant cannot be lowered for one test without lowering
    # it for every other. What it bounds is *individual calls*: the old
    # ``MAX_TOOL_ROUNDS = 6`` counted assistant passes, so a model asking for
    # five tools in a single message spent one round and could do it five
    # times over for the price of six. The unit the model spends in is the
    # unit the cap has to be in, or it does not bound anything.
    #
    # The per-call budget is the bound, but it cannot be the *only* one. A
    # tool call whose ``function.name`` is empty is skipped without ever being
    # counted, so a gateway that answers with nothing but nameless calls would
    # spin this loop forever without spending a single call of the budget.
    # That is a hang, not a slow turn, and it is reachable from a malformed
    # response. So the loop keeps a round backstop as well -- generous enough
    # that no honest turn ever meets it, since a turn that made no real call
    # has nothing to show for its extra passes.
    MAX_TOOL_ROUNDS = 100

    async def available_models(self) -> list[str]:
        """Every model the bound provider offers, sorted.

        Asked of the provider rather than read from the registry's seed list,
        which is five illustrative ids. OpenRouter proxies several hundred and
        the seed list says so in a comment, so a menu built from it would show
        a user five of the models they have and none of the ones they want.

        Public because the protocol needs the same answer the request layer
        does: a picker offering an id the provider does not serve would bind
        to a model whose first request is a 404.
        """
        provider = self.provider
        if provider is None:
            return []
        # `http_client` is a *method* on the OpenAI-compatible provider, not a
        # cached attribute, so it has to be called to get the client. Reading it
        # and using it directly hands the caller a bound method, and the failure
        # arrives as an AttributeError on a function -- which is the same
        # confusing error a genuinely absent client would produce, so the
        # absence check below has nothing left to say.
        factory = getattr(provider, "http_client", None)
        if factory is None:
            return []
        try:
            models = await factory().list_models()
        except Exception as exc:  # noqa: BLE001 - reported to the caller
            raise LLMError.network(exc, self.provider_name) from exc
        return sorted(models)

    def set_max_tool_calls(self, limit: int) -> int:
        """Change the per-turn tool budget. Returns what took effect.

        Floored at one rather than at zero -- except for the one value that is
        not a budget at all: **0 means no limit**. A budget of zero is otherwise
        the refusal of every tool, which is a different thing from a small
        budget and is expressed by taking tools off the model's list, so the
        floor corrects a mistake instead of obeying it. "No limit" needs a value
        too, and zero is the only number below the floor -- which is exactly what
        makes it safe to give the opposite meaning here, and only here. Every
        reader of `max_tool_calls` has to know that; there is one comparison that
        matters and it is written to test the budget rather than the number.

        The change applies from the *next* turn. A turn in flight is mid-loop
        with its own idea of how far it may go, and moving the number under it
        would make the labels on results already in the transcript wrong.
        """
        wanted = int(limit)
        self.max_tool_calls = wanted if wanted == 0 else max(1, wanted)
        return self.max_tool_calls

    def _tool_budget_label(self) -> str:
        """Where the turn stands, as the model and the UI both read it."""
        if not self.max_tool_calls:
            return f"Tool call {self._tool_calls_used} of no limit"
        return f"Tool call {self._tool_calls_used}/{self.max_tool_calls}"

    def _budget_exhausted_error(self) -> str:
        """What the user is told when the turn ran out of tool calls."""
        return (
            f"Stopped after {self.max_tool_calls} tool calls "
            f"(last: {self._tool_budget_label()}). The model kept requesting "
            "tools; ask it to summarise what it has, or raise the limit."
        )

    async def _run_turn(self, turn_id: str) -> None:
        # This session is *the* session for the duration of its turn: published
        # into the tool context, which is how a tool learns whose turn reached
        # it. A child's own turn (started from inside the parent's tool call)
        # nests inside the parent's context and restores it on unwind, so the
        # parent's remaining calls still see the parent.
        #
        # A ContextVar rather than the module global this replaced: a global
        # written as a side effect of *running* something is exactly the shape
        # the `user_io` leak warned about, and two sessions can be running at
        # once here (a parent and its child) in a way they never could before
        # this phase.
        with use_context(session=self):
            await self._run_turn_body(turn_id)

    async def _run_turn_body(self, turn_id: str) -> None:
        try:
            # Resolved before the first request, so the prompt and the turn
            # agree about what this turn is. See `_skill_for_this_turn`.
            self._active_skill = self._skill_for_this_turn()
            self.emit(EventType.TURN_STARTED, {"model": self.model}, turn_id=turn_id)
            self._round_orders = []
            self._tool_calls_used = 0
            self._children_started = 0
            for _round in range(self.MAX_TOOL_ROUNDS):
                tool_calls = await self._stream_assistant(turn_id)
                if not tool_calls:
                    break
                exhausted = await self._run_tool_calls(
                    tool_calls, turn_id, len(self._round_orders) + 1
                )
                if exhausted:
                    # The model has results it has not yet answered about.
                    # Say so rather than pretending the turn completed.
                    self.emit(
                        EventType.ERROR,
                        {"message": self._budget_exhausted_error()},
                        turn_id=turn_id,
                    )
                    break
                self._check_cancelled()
            else:
                # The round backstop ran out. Reachable only by a turn that
                # made no real call at all, but silent termination is how a
                # truncated turn becomes a mystery, so it says the same thing
                # the budget does rather than ending without a word.
                self.emit(
                    EventType.ERROR,
                    {"message": self._budget_exhausted_error()},
                    turn_id=turn_id,
                )
            # A turn whose last act was a tool call must not leave the history
            # ending on a bare tool result; one that produced a real answer is
            # left alone. The condition lives in the helper.
            self._append_results_digest()
            self.emit(EventType.TURN_FINISHED, {}, turn_id=turn_id)
        except SessionCancelled:
            # A user-initiated stop is not a failure.
            self.emit(
                EventType.TURN_FINISHED, {"cancelled": True}, turn_id=turn_id
            )
        except LLMError as exc:
            self.emit(
                EventType.TURN_FAILED,
                {"message": exc.user_message(), "kind": exc.kind.value},
                turn_id=turn_id,
            )
        except Exception as exc:  # noqa: BLE001 - a turn must never kill the loop
            logger.exception("Turn failed")
            self.emit(
                EventType.TURN_FAILED, {"message": str(exc)}, turn_id=turn_id
            )
        finally:
            # Whatever ended the turn -- an answer, a stop, a provider error, a
            # task cancelled from outside -- a prompt it raised cannot outlive
            # it. The child's own turn comes through here too, which is why this
            # is the body and not `run_turn`.
            self._close_open_confirmations()
            # Nothing a turn started outlives it: a call left running by a
            # failure or a stop would be answered to nobody, and would still be
            # spending the user's money.
            self._cancel_running_tools()
            # A skill is invoked for one turn. Left set, the next turn would
            # still be following a procedure nobody asked for again -- and it
            # would look like the model refusing to let go of it.
            self._active_skill = None
            self._busy = False

    def _skill_for_this_turn(self) -> SkillInvocation | None:
        """The skill this turn's message asks for, if it asks for one that exists.

        Read from the last message rather than from ``send``, because ``send`` is
        not the only way into a turn: ``run_turn`` (scripts and tests) and a
        child's own turn (``subagent_tools._child_turn``) each append their user
        message and then call ``_run_turn``. Every one of them appends first, so
        the last message *is* this turn's -- and a `/name` in a child's brief
        means the same thing it means at the top level, which is the answer that
        needs no special case.

        The *current* folder is passed explicitly. `invocation_for` takes one
        required rather than defaulting, because a default would have to mean
        "the user root only" and would read as "the project" -- the bug being a
        skill that exists and is never found.

        An unknown name is not a skill invocation at all: see
        ``core.skills.invocation_for`` for why a message is never hijacked just
        for starting with a slash.
        """
        if not self.messages:
            return None
        last = self.messages[-1]
        if last.role != MessageRole.USER:
            return None
        # An attachment message carries content parts rather than text, and a
        # list of parts is not something a slash command can be read out of.
        if not isinstance(last.content, str):
            return None
        return invocation_for(last.content, folder_manager.current_folder)

    def _check_cancelled(self) -> None:
        if self._cancel is not None and self._cancel.is_set():
            raise SessionCancelled()

    def _tool_schemas(self) -> list[ToolSchema]:
        """The tools this mode is allowed to see.

        Filtering the schema is advisory: it stops the model asking for a tool
        it was never shown. The guarantee lives in the orchestrator, which
        refuses the call even if the model hallucinates it anyway.
        """
        # ALL_SCHEMAS entries carry extra UI-only keys, so use the dedicated
        # converter rather than **schema.
        allowed = self._mode.allowed_tools & self._permission.allowed_tools
        return [
            ToolSchema.from_tool_schema_dict(s)
            for s in ALL_SCHEMAS
            if s.get("name") in allowed
        ]

    # -- mode ----------------------------------------------------------------
    @property
    def mode_name(self) -> str:
        return self._mode.name

    @property
    def permission_name(self) -> str:
        return self._permission.name

    def set_permission(self, name: str) -> Permission:
        """Switch permission level and return the one that ended up active.

        Returns the resolved level rather than the string asked for, for the
        same reason `set_mode` does: an unrecognised name falls back to a safe
        default, and the caller has to report what is actually in force rather
        than what it hoped for.

        **Deliberately does not clear the conversation**, unlike `set_mode`. A
        mode change re-shapes what the agent is *for*, so the old turns are
        about a different task. A permission change does not: the user is the
        same, the project is the same, and only the ceiling moved. Throwing the
        transcript away would lose work for a change the user can see and
        reverse in one click.
        """
        self._permission = get_permission(name)
        # Push it to the layer that enforces it, for the reason `set_mode`
        # does -- setting it here alone would filter the schema and nothing
        # else, which is advice rather than a rule.
        tool_orchestrator.set_permission(self._permission)
        return self._permission

    def set_mode(self, name: str) -> Mode:
        """Switch mode and return the mode that ended up active.

        Returns the resolved mode rather than the string asked for, because an
        unrecognised name resolves to Build -- the caller must report what is
        actually in force, not what it hoped for.
        """
        self._mode = get_mode(name)
        # Push the restriction to the layer that enforces it. Setting it only
        # here would filter the schema and nothing else, which is advice rather
        # than a rule.
        tool_orchestrator.set_mode(self._mode)
        # A mode change re-shapes the conversation, and the old system prompt
        # would otherwise linger and contradict the new one. The history is
        # user and assistant turns; dropping it is honest ("this is a new
        # conversation under different rules") and avoids a model that read
        # "you cannot write files" in turn 3 and is still trying to obey it
        # after the user switched to Build.
        self.clear()
        return self._mode

    def _messages_with_system(self) -> list[ChatMessage]:
        """The conversation with the active mode's system prompt in front.

        Built per request rather than stored, so the prompt always matches the
        mode in force. `self.messages` stays exactly what the user and the
        model said, which keeps `clear()` and the history tests honest.

        The plan is appended to the prompt rather than sent as a message. It is not
        something either party *said* -- and in the history the model would read its
        own plan back as a claim it had made, while `clear()` and the history tests
        would have to account for a turn nobody took.

        The skill this turn was asked for with `/name` is appended for the same
        reason: the user typed `/review`, and that is what the transcript keeps --
        the procedure itself is background for one turn, not a document either
        party said, and a transcript that grew a pasted procedure per invocation
        would make the file on disk unreadable in a week.
        """
        # The mode's own rules first -- what kind of work this is -- then how a
        # turn is spent, which is the same in every mode and is appended here
        # rather than copied into four prompts so a fifth mode cannot be the one
        # that forgets it. See `modes.TOOL_CALL_ECONOMY`.
        prompt = f"{self._mode.system_prompt}\n\n{TOOL_CALL_ECONOMY}"
        # The actual budget, once per request. The economy rules say *how* to
        # spend a turn but not *how many* calls there are, and a model that is
        # never given the number cannot plan against it -- it finds the wall on
        # the call that hits it. Empty when the budget is unlimited (`0`).
        budget = tool_budget_note(self._tool_calls_used, self.max_tool_calls)
        if budget:
            prompt = f"{prompt}\n\n{budget}"
        plan = self.state.render()
        if plan:
            prompt = f"{prompt}\n\n{plan}"
        if self._active_skill is not None:
            prompt = f"{prompt}\n\n{self._active_skill.prompt_block()}"
        return [ChatMessage(role="system", content=prompt), *self.messages]

    async def _iter_chunks(self, tools: list[ToolSchema]):
        """Yield chunks, normalising the providers' three call shapes.

        Anthropic/Gemini/Ollama define ``chat_completion`` as a true async
        generator; the OpenAI-compatible family defines a coroutine that
        *returns* an async generator or a single completion. Callers should
        never have to care which provider is in use.
        """
        result = self.provider.chat_completion(
            messages=self._messages_with_system(),
            tools=tools,
            tool_choice=ToolChoice.AUTO,
            stream=True,
            **(await self._reasoning_request()),
        )
        if hasattr(result, "__aiter__"):
            async for chunk in result:
                yield chunk
            return
        result = await result
        if hasattr(result, "__aiter__"):
            async for chunk in result:
                yield chunk
            return
        if getattr(result, "content", None) or getattr(result, "tool_calls", None):
            yield ChatCompletionChunk(
                content=getattr(result, "content", None),
                tool_calls=getattr(result, "tool_calls", None),
                finish_reason=getattr(result, "finish_reason", None),
                model=getattr(result, "model", "") or "",
                reasoning=getattr(result, "reasoning", None),
                reasoning_details=getattr(result, "reasoning_details", None),
            )

    async def reasoning_capability(self) -> ReasoningSpec | None:
        """What the current model says about its thinking, read once.

        Public because the protocol needs the same answer the request layer
        does, and two lookups that disagree would be a dropdown offering a
        choice the request then throws away.
        """
        if self._reasoning_spec is _UNRESOLVED:
            self._reasoning_spec = None
            getter = getattr(self.provider, "reasoning_spec", None)
            if getter is not None:
                try:
                    self._reasoning_spec = await getter(self.model)
                except Exception as exc:  # noqa: BLE001 - unknown model, no key sent
                    logger.warning(f"Could not read reasoning support: {exc}")
                    self._reasoning_spec = None
        return self._reasoning_spec

    async def _reasoning_request(self) -> dict[str, Any]:
        """The ``reasoning`` field for this request, or nothing at all.

        Nothing is the common and important answer. A model that does not
        reason rejects a request carrying the key, so the field is only built
        once the model is known to accept it *and* the chosen effort is one it
        offers. A model that reasons with no dial is left to its own default
        rather than guessed at, and a mandatory one is never told ``none``.

        The lookup is cached because the model list does not change under us
        and this runs once per assistant pass.
        """
        if self._reasoning_spec is _UNRESOLVED:
            await self.reasoning_capability()
        spec = self._reasoning_spec
        if not isinstance(spec, ReasoningSpec) or not spec.accepts(self.reasoning_effort):
            return {}
        return {"reasoning": {"effort": self.reasoning_effort}}

    def set_reasoning_effort(self, effort: str) -> str:
        """Choose how hard the model should think. Returns what took effect.

        An effort is refused only when the model is already known and does not
        offer it. Before the first request the answer is taken on trust and
        re-checked by :meth:`_reasoning_request`, which is where the spec is
        actually in hand -- refusing here would mean refusing everything that
        arrived before the model list had been read.
        """
        effort = (effort or "").strip()
        if not effort:
            self.reasoning_effort = ""
            return ""
        spec = self._reasoning_spec
        if isinstance(spec, ReasoningSpec) and not spec.accepts(effort):
            return self.reasoning_effort
        self.reasoning_effort = effort
        return effort

    async def _stream_assistant(self, turn_id: str) -> Any:
        """One assistant pass. Returns the tool calls it requested, if any."""
        self.emit(EventType.MESSAGE_STARTED, {}, turn_id=turn_id)
        text = ""
        reasoning = ""
        reasoning_details: Any = None
        tool_calls: Any = None
        finish_reason: str | None = None
        async for chunk in self._iter_chunks(self._tool_schemas()):
            self._check_cancelled()
            if chunk.content:
                text += chunk.content
                self.emit(
                    EventType.MESSAGE_DELTA, {"text": chunk.content}, turn_id=turn_id
                )
            # Thinking goes out on its own event so a frontend can show it
            # arriving without splicing it into the answer being typed below.
            if chunk.reasoning:
                reasoning += chunk.reasoning
                self.emit(
                    EventType.REASONING_DELTA,
                    {"text": chunk.reasoning},
                    turn_id=turn_id,
                )
            # Each chunk repeats the whole list so far, so the last one wins and
            # nothing has to be reassembled here.
            if chunk.reasoning_details:
                reasoning_details = chunk.reasoning_details
            if chunk.tool_calls:
                tool_calls = chunk.tool_calls
            if chunk.finish_reason:
                finish_reason = chunk.finish_reason
                break
        # The budget trap: reasoning tokens are drawn from the same allowance as
        # output, so a model that thinks at length can spend everything and stop
        # at ``length`` with nothing written. Silent, it looks exactly like a
        # provider that returned nothing, and the user has no way to tell a
        # model that thought too long from a broken one.
        truncated = finish_reason == "length" and not text and not tool_calls
        if reasoning or reasoning_details or truncated:
            self.emit(
                EventType.REASONING_COMPLETED,
                {
                    "text": reasoning,
                    "truncated": truncated,
                    # Absent rather than empty when nothing went wrong, so a
                    # frontend can tell "fine" from "not reported".
                    **({"notice": _THINKING_BUDGET_NOTICE} if truncated else {}),
                },
                turn_id=turn_id,
            )
            if truncated:
                self.emit(
                    EventType.ERROR, {"message": _THINKING_BUDGET_NOTICE}, turn_id=turn_id
                )
        # A tool-call pass often carries no text at all, but it MUST still
        # land in the history: OpenAI-compatible APIs reject a tool message
        # whose preceding assistant turn (carrying the matching tool_calls)
        # is missing. The reasoning goes with it, because that is what the
        # provider needs back to continue the same line of thought.
        if text or tool_calls:
            self.messages.append(
                ChatMessage(
                    role="assistant",
                    content=text,
                    tool_calls=tool_calls,
                    reasoning=reasoning or None,
                    reasoning_details=reasoning_details,
                )
            )
        self.emit(EventType.MESSAGE_COMPLETED, {"text": text}, turn_id=turn_id)
        return tool_calls

    async def _run_tool_calls(self, tool_calls: list[dict], turn_id: str,
                              round_no: int) -> bool:
        """Execute each requested tool and append its result to the history.

        Returns True when the turn ran out of tool calls before finishing the
        batch, which is the only thing the caller needs to know: a turn that
        stopped for any other reason continues.

        Every requested call gets exactly one tool message, including the ones
        the budget refused. That is not tidiness. The assistant message above
        already declared these calls in its ``tool_calls`` array, and an
        OpenAI-compatible endpoint rejects a history where a declared call has
        no matching result -- so dropping the refused ones would turn a
        finished, explainable turn into a 400 on the *next* message, with the
        cause one request removed from anything the user can see.

        **Three phases, and the order between them is load-bearing.** The batch
        is planned first -- what runs, what is refused, and each admitted call's
        number in the turn -- then the admitted calls run, concurrently when
        nothing in the batch will ask the user a question, and only then are the
        refusals emitted. Refusals *last* is the part that is easy to get wrong:
        a refusal quotes the budget line the turn actually reached, and the
        frontend reads the final ``TOOL_COMPLETED`` as the failure, so emitting
        them while planning would have both of them describing a turn that had
        not run yet.
        """
        #: Admitted calls, each with the budget line it was admitted under.
        planned: list[tuple[ToolCall, dict[str, Any]]] = []
        #: ``(call id, tool name)`` pairs the budget would not pay for.
        refused: list[tuple[str, str]] = []

        for raw in tool_calls:
            self._check_cancelled()
            function = raw.get("function", {}) or {}
            name = function.get("name", "")
            if not name:
                continue
            call_id = raw.get("id") or uuid.uuid4().hex
            # A truth test, not `!= 0`: 0 is the no-limit sentinel, so the
            # budget only bites when there is one.
            if self.max_tool_calls and self._tool_calls_used >= self.max_tool_calls:
                refused.append((call_id, name))
                continue
            try:
                arguments = json.loads(function.get("arguments") or "{}")
            except (ValueError, TypeError):
                # A malformed arguments blob is the model's fault, not a crash.
                arguments = {}
            # Counted before the call runs, not after it returns. A tool that
            # fails still consumed a call: the model asked for it, the request
            # went out, and the budget is what bounds spending. Counting only
            # successes would make a loop of failing tools free.
            self._tool_calls_used += 1
            # The number is frozen here rather than read again when the call
            # finishes. With calls running concurrently the turn has moved on by
            # then, and every result would report the *last* number instead of
            # its own -- so the model and the card would be told the same wrong
            # place in the turn, which is the kind of agreement that hides a bug.
            planned.append(
                (
                    ToolCall(id=call_id, name=name, arguments=arguments),
                    self._budget_payload(),
                )
            )

        if planned:
            # Every card is announced before anything runs, so the transcript
            # shows the whole batch as in flight rather than revealing it one
            # call at a time as each happens to be scheduled.
            for call, budget in planned:
                self.emit(
                    EventType.TOOL_STARTED,
                    {
                        "id": call.id,
                        "name": call.name,
                        "arguments": call.arguments,
                        "tool_call_budget": budget,
                    },
                    turn_id=turn_id,
                )

            try:
                results = await self._execute_batch(planned)
            except BaseException:
                # **The pairing rule holds on this path too**, and it is the same
                # rule the budget refusals below exist for: the assistant message
                # above already declared these calls, and an OpenAI-compatible
                # endpoint rejects a history where a declared call has no
                # answering tool message -- a 400 attached to the *next* message,
                # with the cause one request out of sight.
                #
                # It matters most on the stop path, which is the common one: a
                # Stop used to leave the calls unfinished but *answered*, because
                # the turn waited for them. Cancelling the call is what makes Stop
                # immediate (see `_cancel_running_tools`), and it is also what
                # would leave the history half-answered without this.
                self._answer_unfinished_calls(planned, turn_id)
                raise

            for (call, budget), result in zip(planned, results):
                payload = result.to_dict()
                # The same field the model reads, on the same number. The card
                # and the model must not be able to disagree about how far the
                # turn got, and there is exactly one place that knows.
                payload["tool_call_budget"] = budget
                self.emit(
                    EventType.TOOL_COMPLETED,
                    {
                        "id": call.id,
                        "name": call.name,
                        "result": payload,
                        "tool_call_budget": budget,
                    },
                    turn_id=turn_id,
                )
                self.messages.append(
                    ChatMessage(
                        role="tool",
                        content=self._tool_content(payload, result),
                        tool_call_id=call.id,
                    )
                )

        for call_id, name in refused:
            self._append_refused_tool_message(call_id, name, turn_id)

        # Every round that produced a result gets a number, whether the turn
        # continues or stops at the cap: the digest references the results by
        # these numbers.
        self._round_orders.append(round_no)
        return bool(refused)

    async def _execute_batch(
        self, planned: list[tuple[ToolCall, dict[str, Any]]]
    ) -> list[ToolResult]:
        """Run the admitted calls, concurrently when nothing will prompt.

        Results come back in the order the calls were planned, which is what the
        wire needs: the tool messages after an assistant message's ``tool_calls``
        array have to line up with it one for one, and a batch answering out of
        order would pair each result with the wrong request.

        **A batch with a confirmation prompt in it runs in order.** That is the
        whole reason ``will_prompt`` exists. Concurrent prompts would put two
        dialogs on screen at once, and the second would be asking about a call
        the user has not read yet -- so the case that needs a human stays exactly
        as sequential as it has always been, and only the case that needs nobody
        gets faster.

        Calls run one at a time in the prompting case and in a batch of one, and
        each is still started as its own task even when nothing overlaps --
        a task is the handle `cancel()` needs, and a single call is the shape a
        stopped turn most often has.
        """
        try:
            if len(planned) == 1 or any(
                tool_orchestrator.will_prompt(call.name, call.arguments)
                for call, _ in planned
            ):
                # One at a time -- and each still inside its own task, because a
                # task is the handle Stop needs. A call run in line cannot be
                # cancelled, and a single call is the common case: one
                # `execute_command` is exactly the turn a user stops.
                return [await self._run_tool_call(call) for call, _ in planned]

            tasks = [self._start_tool_call(call) for call, _ in planned]
            try:
                return list(await asyncio.gather(*tasks))
            except BaseException:
                # Nothing may be left running behind a failure: a gather
                # abandoned because one call raised would leave the rest running
                # with nobody reading their results. The tasks are cancelled
                # *and awaited*, so their exceptions are collected rather than
                # surfacing later as "never retrieved".
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                raise
        except asyncio.CancelledError:
            # The calls were cancelled by `cancel()`, which is the session's own
            # "this turn was stopped" -- the exception `_check_cancelled` raises,
            # and the one `_run_turn_body` turns into a cancelled turn's frame.
            #
            # Translating it matters: `CancelledError` is a `BaseException`, so
            # nothing in `_run_turn_body` catches it, and a turn that ended with
            # no terminal frame would leave the window showing "busy" forever. A
            # cancellation that is *not* ours -- the turn's own task cancelled
            # from outside, at shutdown -- is left alone to propagate, because
            # that caller is awaiting it.
            if self._cancel is not None and self._cancel.is_set():
                raise SessionCancelled()
            raise

    def _start_tool_call(self, call: ToolCall) -> asyncio.Task:
        """One tool call in its own task, registered so `cancel()` can reach it.

        Registration is what makes Stop work on a call that is already running.
        The flag `cancel()` sets is only *polled* -- before a call, and between
        rounds -- so a turn stopped while a tool ran on kept running to that
        tool's own end: measured, a turn that had spawned a child stayed alive
        for the child's whole turn after Stop (2.7s of a 3s child), and a turn
        waiting on a command would have waited out its timeout.
        """
        task = asyncio.create_task(self._execute_one(call))
        self._tool_tasks.add(task)
        task.add_done_callback(self._tool_tasks.discard)
        return task

    async def _run_tool_call(self, call: ToolCall) -> ToolResult:
        """One call, awaited in order -- the sequential half of a batch.

        Its own task even though nothing overlaps here, for the reason above: a
        batch of one is the common case, and it is the case the user stops.
        """
        return await self._start_tool_call(call)

    def _cancel_running_tools(self) -> None:
        """Cancel the tool calls this session has in flight, if any.

        Called by `cancel()` (the user's Stop) and at the end of every turn, so
        nothing a turn started can outlive it. A cancelled call is not answered
        on the wire -- there is no result to report about work that did not
        finish -- and the turn waiting on it ends as a cancelled turn.

        A child stopped this way is stopped *by* this: cancelling the parent's
        call raises `CancelledError` inside `_drive_child`, whose own branch
        interrupts the child before re-raising. That branch was written for this
        path and had no caller until now.
        """
        for task in list(self._tool_tasks):
            task.cancel()


    async def _execute_one(self, call: ToolCall) -> ToolResult:
        """One tool call, on the entry point a coroutine has to use.

        ``execute_tool()`` -- the synchronous one -- refuses to run inside a live
        event loop, so calling it from a coroutine used to raise and the tool
        silently never ran. That is why this goes through the async entry point
        and why the cancellation check is here rather than only around the batch.
        """
        self._check_cancelled()
        return await tool_orchestrator.execute_tool_async(call)

    @staticmethod
    def _tool_content(payload: dict[str, Any], result: Any) -> Any:
        """The tool message: JSON text, or text plus the images it produced.

        A tool that returns a picture has to put the picture in the message. A
        path would not do it -- the model would be told a file exists and would
        have to ask for it with a second tool call, which is a different product
        with an extra round trip and one more thing to fail. So a result
        carrying images becomes the same OpenAI-style content-parts list a user
        attachment uses, with the JSON first so the words still lead.

        Plain JSON otherwise, which is every other tool and therefore the shape
        the rest of the transcript is already built around.
        """
        images = getattr(result, "images", None)
        if not images:
            return json.dumps(payload)
        parts: list[dict[str, Any]] = [{"type": "text", "text": json.dumps(payload)}]
        for image in images:
            parts.append(
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{image['mime']};base64,{image['data']}"
                    },
                }
            )
        return parts

    def _budget_payload(self) -> dict[str, Any]:
        """The turn's tool-call standing, as one dict for every consumer."""
        return {
            "index": self._tool_calls_used,
            "limit": self.max_tool_calls,
            "label": self._tool_budget_label(),
        }

    def _answer_unfinished_calls(
        self, planned: list[tuple[ToolCall, dict[str, Any]]], turn_id: str
    ) -> None:
        """Answer every call in a batch that ended without results.

        Called when the batch raised -- a stopped turn, or a failing call that
        took its siblings with it. Each planned call gets one tool message saying
        it produced no result, which is what keeps the assistant message above it
        valid: a declared ``tool_calls`` entry with nothing answering it is
        rejected outright by OpenAI-compatible endpoints, so the alternative to
        this message is not "silence", it is a 400 on the user's next message.

        The wording is careful in both directions. It says *not run* rather than
        "failed" (nothing was attempted at the end of it), and it says "before it
        produced a result" rather than "before it started", because a concurrent
        batch stopped midway can contain a call that did run and whose result was
        discarded with the batch.
        """
        for call, budget in planned:
            reason = (
                "Not run: the turn was stopped before this call produced a "
                "result. Nothing else happened because of it."
            )
            payload = {
                "status": "error",
                "output": None,
                "summary": None,
                "error": reason,
                "artifacts": [],
                "duration_ms": 0.0,
                "tool_call_budget": budget,
            }
            self.emit(
                EventType.TOOL_COMPLETED,
                {
                    "id": call.id,
                    "name": call.name,
                    "result": payload,
                    "tool_call_budget": budget,
                },
                turn_id=turn_id,
            )
            self.messages.append(
                ChatMessage(
                    role="tool",
                    content=json.dumps(payload),
                    tool_call_id=call.id,
                )
            )

    def _append_refused_tool_message(self, call_id: str, name: str,
                                     turn_id: str) -> None:
        """Answer a call the budget will not pay for.

        A refusal rather than a silence, and said plainly: the model is
        reading this, and a result that merely says "error" leaves it to guess
        whether to retry in a loop. The turn's real limit goes in the message
        so the next turn can be planned inside it.
        """
        self.emit(
            EventType.TOOL_COMPLETED,
            {
                "id": call_id,
                "name": name,
                "result": {
                    "status": "error",
                    "output": None,
                    "error": (
                        f"Not run: this turn reached its tool call budget "
                        f"({self._tool_budget_label()}). Answer from the "
                        "results you already have, or ask the user to raise "
                        "the limit."
                    ),
                    "artifacts": [],
                    "duration_ms": 0.0,
                    "tool_call_budget": self._budget_payload(),
                },
                "tool_call_budget": self._budget_payload(),
            },
            turn_id=turn_id,
        )
        self.messages.append(
            ChatMessage(
                role="tool",
                content=json.dumps(
                    {
                        "status": "error",
                        "output": None,
                        "error": (
                            f"Not run: this turn reached its tool call budget "
                            f"({self._tool_budget_label()})."
                        ),
                        "artifacts": [],
                        "duration_ms": 0.0,
                        "tool_call_budget": self._budget_payload(),
                    }
                ),
                tool_call_id=call_id,
            )
        )

    def _append_results_digest(self) -> None:
        """Close a turn that ended on tool results with an assistant note.

        Some providers reject a history that ends on a tool message, and a
        history that ends with an unanswered result is ambiguous for the next
        turn anyway. The note is the assistant speaking; the next call gets a
        normal prompt to answer from. A turn that ended with a real answer is
        left untouched -- no synthetic message after it.
        """
        if not self._round_orders:
            return
        if not self.messages or self.messages[-1].role != MessageRole.TOOL:
            return
        digest = _results_digest(self._round_orders)
        self.messages.append(ChatMessage(role="assistant", content=digest))
