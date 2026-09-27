"""Headless stdio server: the Tauri sidecar entry point.

Wire format is newline-delimited JSON (JSONL), one message per line, in both
directions. This is the contract the future Tauri UI will speak, so it is
specified here in one place and covered by tests before any frontend exists.

Why JSONL over stdio rather than a local HTTP server:

* the sidecar lifecycle is owned by Tauri, so it starts and dies with the app
* no port to collide with, no auth, no CORS
* a dead pipe is an unambiguous signal that the backend is gone

Requests (``{"id": 1, "method": "send", "params": {...}}``) get exactly one
reply. Events (``{"event": "message.delta", ...}``) are pushed as they happen
and are not tied to a request id.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import sys
from typing import Any, Callable, TextIO

from loguru import logger

from tonyagent.core.events import Event
from tonyagent.core.session import AgentSession

#: Bump when the request/response shape changes incompatibly.
PROTOCOL_VERSION = 1


class RpcError(Exception):
    """An error to report back to the caller instead of crashing the server."""


def _dumps(obj: Any) -> str:
    """Serialise one line, never emitting embedded newlines.

    ``json.dumps`` escapes newlines inside strings, so a single call is always
    exactly one line. ``default=str`` keeps an unexpected object from taking
    down the stream - better a slightly lossy frame than a dead backend.
    """
    return json.dumps(obj, default=str, ensure_ascii=False)


class StdioServer:
    """Reads requests from stdin, writes replies and events to stdout.

    stdout is reserved for the protocol. Anything meant for a human (logging,
    tracebacks) must go to stderr or the frontend will try to parse it as JSON.
    """

    def __init__(self, session: AgentSession, stdin: TextIO, stdout: TextIO) -> None:
        self.session = session
        self.stdin = stdin
        self.stdout = stdout
        self._running = True
        # The project folder the sandbox is attached to, echoed back by `state`
        # so a window that reloads knows what it is working on.
        self.project: str = ""
        # Async handlers awaiting a reply, keyed by request id.
        self._pending: dict[Any, Any] = {}
        self._handlers: dict[str, Callable[[dict], Any]] = {
            "ping": self._h_ping,
            "send": self._h_send,
            "cancel": self._h_cancel,
            "clear": self._h_clear,
            "bind_provider": self._h_bind_provider,
            "providers.list": self._h_providers_list,
            "state": self._h_state,
            "sandbox.start": self._h_sandbox_start,
            "sandbox.stop": self._h_sandbox_stop,
            "sandbox.stats": self._h_sandbox_stats,
            "confirm.respond": self._h_confirm_respond,
            "trust.set": self._h_trust_set,
        }
        # Tool confirmations must reach the frontend as events, not a Tkinter
        # callback that only an after() loop would drain.
        session.install_confirmation_bridge()
        self.session.bus.subscribe(self._on_event)

    # -- outbound ------------------------------------------------------------
    def _write(self, obj: Any) -> None:
        try:
            self.stdout.write(_dumps(obj) + "\n")
            self.stdout.flush()
        except (BrokenPipeError, ValueError):
            # The frontend is gone. Stop trying to talk to it.
            self._running = False

    def _reply(self, req_id: Any, result: Any) -> None:
        self._write({"id": req_id, "result": result})

    def _reply_error(self, req_id: Any, message: str, code: str = "error") -> None:
        self._write({"id": req_id, "error": {"code": code, "message": message}})

    def _on_event(self, event: Event) -> None:
        """Push a core event to the frontend.

        Events and replies share the stream, so they must be distinguishable.
        Events carry no ``id``; replies always do.
        """
        self._write({"event": True, **event.to_dict()})

    # -- handlers ------------------------------------------------------------
    def _h_ping(self, params: dict) -> Any:
        return {"pong": True, "protocol": PROTOCOL_VERSION}

    def _h_send(self, params: dict) -> Any:
        text = params.get("text", "")
        turn_id = self.session.send(text)
        if not turn_id:
            # Explain which precondition failed so the UI can say something
            # useful, instead of a generic "rejected".
            if not text.strip():
                raise RpcError("empty message")
            if self.session.busy:
                raise RpcError("a turn is already running")
            if self.session.provider is None:
                raise RpcError("no provider configured")
            raise RpcError("message rejected")
        return {"turn_id": turn_id}

    def _h_cancel(self, params: dict) -> Any:
        self.session.cancel()
        return {"cancelled": True}

    def _h_clear(self, params: dict) -> Any:
        self.session.clear()
        return {"cleared": True}

    def _h_bind_provider(self, params: dict) -> Any:
        name = params.get("name", "")
        model = params.get("model", "")
        provider = self.session.bind_provider(name, model)
        if provider is None:
            raise RpcError(f"Unknown provider: {name}")
        return {"provider": name, "model": getattr(provider, "model", model)}

    def _h_providers_list(self, params: dict) -> Any:
        """Report which providers exist, without exposing anything secret.

        The registry is the only place provider names are defined, so the
        frontend asks rather than carrying its own copy -- a hardcoded list
        would drift silently the moment a provider is added or renamed.

        ``get_available_providers`` reports ``has_credentials`` as a boolean
        only; the key itself never leaves the keyring.
        """
        from tonyagent.providers import ProviderFactory

        try:
            return {"providers": ProviderFactory.get_available_providers()}
        except Exception as exc:  # noqa: BLE001 - an empty list beats a dead UI
            logger.warning(f"providers.list failed: {exc}")
            return {"providers": []}

    def _h_state(self, params: dict) -> Any:
        return {
            "provider": self.session.provider_name,
            "model": self.session.model,
            "busy": self.session.busy,
            "messages": len(self.session.messages),
            "project": self.project,
        }

    # -- sandbox -------------------------------------------------------------
    async def _h_sandbox_start(self, params: dict) -> Any:
        ok = await self.session.start_sandbox(params.get("path", ""))
        if ok:
            # Remember the project so a later `state` call can tell the UI what
            # it is attached to. Without this a reconnecting window would show
            # "no folder" while the core was happily sandboxed.
            from tonyagent.folder import folder_manager

            self.project = str(folder_manager.current_folder or params.get("path", ""))
        return {"running": bool(ok), "project": self.project}

    async def _h_sandbox_stop(self, params: dict) -> Any:
        await self.session.stop_sandbox()
        return {"running": False}

    async def _h_sandbox_stats(self, params: dict) -> Any:
        return await self.session.sandbox_stats()

    # -- confirmations / trust ----------------------------------------------
    def _h_confirm_respond(self, params: dict) -> Any:
        call_id = params.get("id", "")
        if not call_id:
            raise RpcError("missing confirmation id")
        confirmed = bool(params.get("confirmed"))
        self.session.respond_to_confirmation(call_id, confirmed)
        return {"id": call_id, "confirmed": confirmed}

    def _h_trust_set(self, params: dict) -> Any:
        project = params.get("project", "")
        if not project:
            raise RpcError("missing project path")
        trusted = bool(params.get("trusted"))
        self.session.set_trusted(project, trusted)
        return {"project": project, "trusted": trusted}

    # -- dispatch ------------------------------------------------------------
    def _dispatch(self, req: dict) -> None:
        """Run one request. Errors become replies, never a dead server."""
        req_id = req.get("id")
        method = req.get("method")
        params = req.get("params") or {}
        handler = self._handlers.get(method)
        if handler is None:
            self._reply_error(req_id, f"Unknown method: {method}", "unknown_method")
            return
        try:
            result = handler(params)
            if inspect.isawaitable(result):
                # Sandbox handlers are async. The reply is sent when the
                # coroutine finishes, so ordering stays correct even though
                # other requests may be handled meanwhile.
                self._pending[req_id] = result
                return
            self._reply(req_id, result)
        except RpcError as exc:
            self._reply_error(req_id, str(exc), "rejected")
        except Exception as exc:  # noqa: BLE001
            logger.exception(f"Handler {method} failed")
            self._reply_error(req_id, str(exc), "internal")

    async def _drain_pending(self) -> None:
        """Await every in-flight async handler, replying as each completes."""
        while self._pending:
            items = list(self._pending.items())
            self._pending.clear()
            for req_id, awaitable in items:
                try:
                    self._reply(req_id, await awaitable)
                except RpcError as exc:
                    self._reply_error(req_id, str(exc), "rejected")
                except Exception as exc:  # noqa: BLE001
                    logger.exception("Async handler failed")
                    self._reply_error(req_id, str(exc), "internal")

    # -- main loop -----------------------------------------------------------
    async def serve(self) -> None:
        """Read requests until stdin closes."""
        loop = asyncio.get_running_loop()
        while self._running:
            try:
                line = await loop.run_in_executor(None, self.stdin.readline)
            except Exception:  # noqa: BLE001
                break
            if line == "":  # EOF: the frontend closed the pipe.
                break
            line = line.strip()
            if not line:
                continue
            try:
                req = json.loads(line)
            except ValueError as exc:
                self._reply_error(None, f"Malformed JSON: {exc}", "bad_request")
                continue
            if not isinstance(req, dict):
                self._reply_error(None, "Request must be a JSON object", "bad_request")
                continue
            self._dispatch(req)
            # Async handlers (sandbox control) are awaited inline, so a reply
            # for request N is written before request N+1 is read. That keeps
            # the simple request/response pairing a frontend can rely on.
            await self._drain_pending()


def configure_logging_to_stderr() -> None:
    """Send all logs to stderr, keeping stdout purely for the protocol."""
    logger.remove()
    logger.add(sys.stderr, level="INFO")


async def run(session: AgentSession | None = None) -> None:
    """Entry point for ``python -m tonyagent.headless.server``."""
    configure_logging_to_stderr()
    session = session or AgentSession()
    await StdioServer(session, sys.stdin, sys.stdout).serve()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
