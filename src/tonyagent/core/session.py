"""UI-agnostic conversation session - the headless agent core.

This is the piece that lets TONYAgent run without a display. It owns message
history, provider selection and the tool loop, and reports everything it does
through :class:`~tonyagent.core.events.EventBus`. It imports no GUI toolkit, so
it can be driven by Tkinter, by a Tauri sidecar over stdio, or by a test.

The behaviour previously lived inside ``MainWindow._generate_response`` mixed
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
from tonyagent.core.modes import DEFAULT_MODE, Mode, get_mode
from tonyagent.providers import (
    ChatCompletionChunk,
    ChatMessage,
    ProviderFactory,
    ToolChoice,
    ToolSchema,
)
from tonyagent.providers.base import MessageRole
from tonyagent.tools import ALL_SCHEMAS, ToolCall, tool_orchestrator

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

        return max(1, int(settings.tools.max_tool_calls))
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
        self.provider: Any = None
        self._cancel: Optional[asyncio.Event] = None
        self._busy = False
        #: What the provider said about this model's thinking, resolved once.
        #: ``_UNRESOLVED`` rather than None because "not looked up yet" and
        #: "looked up, does not reason" lead to the same request but only one
        #: of them should cost a network call.
        self._reasoning_spec: Any = _UNRESOLVED
        #: Composer mode. Governs the system prompt and which tools exist.
        self._mode: Mode = get_mode(DEFAULT_MODE)
        #: 1-based tool-round numbers executed in the turn in flight, so the
        #: closing digest can name the results the model just produced.
        self._round_orders: list[int] = []
        #: Individual tool calls already spent in the turn in flight. Counted
        #: per call rather than per round, so a model that asks for five tools
        #: in one message has spent five and the number on the card is the
        #: number of things that were actually run.
        self._tool_calls_used: int = 0
        #: The per-turn tool budget, read once at construction so a mid-turn
        #: settings change cannot make the counter and the label disagree.
        self.max_tool_calls: int = _default_max_tool_calls()

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
        return self.bus.emit(type, payload, turn_id=turn_id)

    # -- public API ----------------------------------------------------------
    def cancel(self) -> None:
        """Stop the running turn. Safe to call when nothing is running."""
        if self._cancel is not None:
            self._cancel.set()

    def clear(self) -> None:
        """Drop the conversation history."""
        self.messages.clear()

    # -- sandbox -------------------------------------------------------------
    async def start_sandbox(self, project_path: str = "") -> bool:
        """Start the shared sandbox and report the outcome as an event."""
        from tonyagent.config.settings import settings
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
        self.emit(
            EventType.CONFIRMATION_RESOLVED,
            {"id": tool_call_id, "confirmed": bool(confirmed)},
        )

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

        Floored at one rather than at zero. A budget of zero refuses every
        tool, which is a different thing from a small budget and is expressed
        by taking tools off the model's list -- so the floor corrects a
        mistake instead of obeying it.

        The change applies from the *next* turn. A turn in flight is mid-loop
        with its own idea of how far it may go, and moving the number under it
        would make the labels on results already in the transcript wrong.
        """
        self.max_tool_calls = max(1, int(limit))
        return self.max_tool_calls

    def _tool_budget_label(self) -> str:
        """Where the turn stands, as the model and the UI both read it."""
        return f"Tool call {self._tool_calls_used}/{self.max_tool_calls}"

    def _budget_exhausted_error(self) -> str:
        """What the user is told when the turn ran out of tool calls."""
        return (
            f"Stopped after {self.max_tool_calls} tool calls "
            f"(last: {self._tool_budget_label()}). The model kept requesting "
            "tools; ask it to summarise what it has, or raise the limit."
        )

    async def _run_turn(self, turn_id: str) -> None:
        try:
            self.emit(EventType.TURN_STARTED, {"model": self.model}, turn_id=turn_id)
            self._round_orders = []
            self._tool_calls_used = 0
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
            self._busy = False

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
        allowed = self._mode.allowed_tools
        return [
            ToolSchema.from_tool_schema_dict(s)
            for s in ALL_SCHEMAS
            if s.get("name") in allowed
        ]

    # -- mode ----------------------------------------------------------------
    @property
    def mode_name(self) -> str:
        return self._mode.name

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
        """
        return [ChatMessage(role="system", content=self._mode.system_prompt), *self.messages]

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
        """
        refused = False
        for raw in tool_calls:
            self._check_cancelled()
            function = raw.get("function", {}) or {}
            name = function.get("name", "")
            if not name:
                continue
            call_id = raw.get("id") or uuid.uuid4().hex
            if self._tool_calls_used >= self.max_tool_calls:
                refused = True
                self._append_refused_tool_message(call_id, name, turn_id)
                continue
            try:
                arguments = json.loads(function.get("arguments") or "{}")
            except (ValueError, TypeError):
                # A malformed arguments blob is the model's fault, not a crash.
                arguments = {}
            call = ToolCall(id=call_id, name=name, arguments=arguments)
            # Counted before the call runs, not after it returns. A tool that
            # fails still consumed a call: the model asked for it, the request
            # went out, and the budget is what bounds spending. Counting only
            # successes would make a loop of failing tools free.
            self._tool_calls_used += 1
            self.emit(
                EventType.TOOL_STARTED,
                {
                    "id": call.id,
                    "name": call.name,
                    "arguments": call.arguments,
                    "tool_call_budget": self._budget_payload(),
                },
                turn_id=turn_id,
            )
            # The async entry point is required: the synchronous
            # execute_tool() refuses to run inside a live event loop, so
            # calling it from a coroutine used to raise and the tool silently
            # never ran.
            result = await tool_orchestrator.execute_tool_async(call)
            payload = result.to_dict()
            # The same field the model reads, on the same number. The card and
            # the model must not be able to disagree about how far the turn
            # got, and there is exactly one place that knows.
            payload["tool_call_budget"] = self._budget_payload()
            self.emit(
                EventType.TOOL_COMPLETED,
                {
                    "id": call.id,
                    "name": call.name,
                    "result": payload,
                    "tool_call_budget": self._budget_payload(),
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
        # Every round that produced a result gets a number, whether the turn
        # continues or stops at the cap: the digest references the results by
        # these numbers.
        self._round_orders.append(round_no)
        return refused

    def _budget_payload(self) -> dict[str, Any]:
        """The turn's tool-call standing, as one dict for every consumer."""
        return {
            "index": self._tool_calls_used,
            "limit": self.max_tool_calls,
            "label": self._tool_budget_label(),
        }

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
