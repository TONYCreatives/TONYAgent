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
        self.messages: list[ChatMessage] = []
        self.provider: Any = None
        self._cancel: Optional[asyncio.Event] = None
        self._busy = False
        #: Composer mode. Governs the system prompt and which tools exist.
        self._mode: Mode = get_mode(DEFAULT_MODE)
        #: 1-based tool-round numbers executed in the turn in flight, so the
        #: closing digest can name the results the model just produced.
        self._round_orders: list[int] = []

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

    def send(self, text: str) -> str:
        """Queue a user message. Returns the turn id, or "" if rejected.

        Synchronous on purpose: the caller gets an id immediately and then
        follows the turn over the event bus, like a streaming response that
        does not block the caller.

        A rejection is reported only through the empty return value, never as
        an ERROR event. The caller turns it into the reply for this request,
        and emitting as well would put a push on the wire *before* the reply it
        belongs to, which a frontend cannot attribute.
        """
        text = (text or "").strip()
        if not text:
            return ""
        if self._busy:
            return ""
        if self.provider is None:
            return ""

        self.messages.append(ChatMessage(role="user", content=text))
        turn_id = uuid.uuid4().hex
        self._cancel = asyncio.Event()
        self._busy = True
        asyncio.ensure_future(self._run_turn(turn_id))
        return turn_id

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
    #: How many tool rounds one turn may chain. Each round is one assistant
    #: pass plus the tool calls it asked for; the cap exists so a model stuck
    #: in a loop costs a bounded amount of money, not because one round is the
    #: honest number. Two is not: "list the files, then open the one that looks
    #: relevant" is a normal agent request, and the old single-round behaviour
    #: answered it with an error instead of an answer.
    MAX_TOOL_ROUNDS = 6

    async def _run_turn(self, turn_id: str) -> None:
        try:
            self.emit(EventType.TURN_STARTED, {"model": self.model}, turn_id=turn_id)
            self._round_orders = []
            for _round in range(self.MAX_TOOL_ROUNDS):
                tool_calls = await self._stream_assistant(turn_id)
                if not tool_calls:
                    break
                await self._run_tool_calls(tool_calls, turn_id, len(self._round_orders) + 1)
                self._check_cancelled()
            else:
                # The cap ran out while the model still wanted tools. Explain
                # the state rather than pretending the turn completed: the
                # model has results it has not yet answered about.
                self.emit(
                    EventType.ERROR,
                    {
                        "message": (
                            f"Stopped after {self.MAX_TOOL_ROUNDS} tool rounds. "
                            "The model kept requesting tools; ask it to "
                            "summarise what it has, or continue the task."
                        )
                    },
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
                              round_no: int) -> None:
        """Execute each requested tool and append its result to the history."""
        for raw in tool_calls:
            self._check_cancelled()
            function = raw.get("function", {}) or {}
            name = function.get("name", "")
            if not name:
                continue
            try:
                arguments = json.loads(function.get("arguments") or "{}")
            except (ValueError, TypeError):
                # A malformed arguments blob is the model's fault, not a crash.
                arguments = {}
            call = ToolCall(
                id=raw.get("id") or uuid.uuid4().hex,
                name=name,
                arguments=arguments,
            )
            self.emit(
                EventType.TOOL_STARTED,
                {"id": call.id, "name": call.name, "arguments": call.arguments},
                turn_id=turn_id,
            )
            # The async entry point is required: the synchronous
            # execute_tool() refuses to run inside a live event loop, so
            # calling it from a coroutine used to raise and the tool silently
            # never ran.
            result = await tool_orchestrator.execute_tool_async(call)
            self.emit(
                EventType.TOOL_COMPLETED,
                {"id": call.id, "name": call.name, "result": result.to_dict()},
                turn_id=turn_id,
            )
            self.messages.append(
                ChatMessage(
                    role="tool",
                    content=json.dumps(result.to_dict()),
                    tool_call_id=call.id,
                )
            )
        # Every round that produced a result gets a number, whether the turn
        # continues or stops at the cap: the digest references the results by
        # these numbers.
        self._round_orders.append(round_no)

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
