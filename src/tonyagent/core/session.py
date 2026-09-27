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
from tonyagent.providers import (
    ChatCompletionChunk,
    ChatMessage,
    ProviderFactory,
    ToolChoice,
    ToolSchema,
)
from tonyagent.tools import ALL_SCHEMAS, ToolCall, tool_orchestrator


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
        self.messages: list[ChatMessage] = []
        self.provider: Any = None
        self._cancel: Optional[asyncio.Event] = None
        self._busy = False

    # -- provider ------------------------------------------------------------
    def bind_provider(self, provider_name: str, model: str = "") -> Any:
        """Point this session at a provider. Returns the provider or None."""
        self.provider_name = provider_name
        self.model = model
        self.provider = ProviderFactory.create_provider(provider_name, model=model)
        if self.provider is None:
            self.emit(EventType.ERROR, {"message": f"Unknown provider: {provider_name}"})
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
            {"status": "running" if ok else "stopped"},
        )
        return bool(ok)

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
    async def _run_turn(self, turn_id: str) -> None:
        try:
            self.emit(EventType.TURN_STARTED, {"model": self.model}, turn_id=turn_id)
            tool_calls = await self._stream_assistant(turn_id)
            if tool_calls:
                await self._run_tool_calls(tool_calls, turn_id)
                self._check_cancelled()
                extra = await self._stream_assistant(turn_id)
                if extra:
                    # A follow-up that asks for tools again would need a loop.
                    # Rather than recursing without bound, say so.
                    self.emit(
                        EventType.ERROR,
                        {"message": "Model requested more tools after a tool result."},
                        turn_id=turn_id,
                    )
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
        # ALL_SCHEMAS entries carry extra UI-only keys, so use the dedicated
        # converter rather than **schema.
        return [ToolSchema.from_tool_schema_dict(s) for s in ALL_SCHEMAS]

    async def _iter_chunks(self, tools: list[ToolSchema]):
        """Yield chunks, normalising the providers' three call shapes.

        Anthropic/Gemini/Ollama define ``chat_completion`` as a true async
        generator; the OpenAI-compatible family defines a coroutine that
        *returns* an async generator or a single completion. Callers should
        never have to care which provider is in use.
        """
        result = self.provider.chat_completion(
            messages=self.messages,
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
            )

    async def _stream_assistant(self, turn_id: str) -> Any:
        """One assistant pass. Returns the tool calls it requested, if any."""
        self.emit(EventType.MESSAGE_STARTED, {}, turn_id=turn_id)
        text = ""
        tool_calls: Any = None
        async for chunk in self._iter_chunks(self._tool_schemas()):
            self._check_cancelled()
            if chunk.content:
                text += chunk.content
                self.emit(
                    EventType.MESSAGE_DELTA, {"text": chunk.content}, turn_id=turn_id
                )
            if chunk.tool_calls:
                tool_calls = chunk.tool_calls
            if chunk.finish_reason:
                break
        if text:
            self.messages.append(
                ChatMessage(role="assistant", content=text, tool_calls=tool_calls)
            )
        self.emit(EventType.MESSAGE_COMPLETED, {"text": text}, turn_id=turn_id)
        return tool_calls

    async def _run_tool_calls(self, tool_calls: list[dict], turn_id: str) -> None:
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
