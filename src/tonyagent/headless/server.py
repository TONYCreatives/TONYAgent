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

from tonyagent.core.conversations import (
    ConversationStore,
    EmptyTitle,
    title_from,
)
from tonyagent.core.events import Event, EventBus, EventType
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

    def __init__(
        self,
        session: AgentSession,
        stdin: TextIO,
        stdout: TextIO,
        store: ConversationStore | None = None,
        conversation_id: str = "",
    ) -> None:
        self.session = session
        self.stdin = stdin
        self.stdout = stdout
        self._running = True
        # The conversation this session writes into. Empty until one is created
        # or restored, which is also what keeps `_persist` from inventing a
        # conversation for a window that never said anything.
        self.conversations = store
        self.conversation_id = conversation_id
        # Released before the next session is wired, so repeated switches do
        # not accumulate subscribers. See ``_attach_session``.
        self._unsubscribe: Callable[[], None] | None = None
        if conversation_id:
            self._load_into_session(conversation_id)
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
            "key.save": self._h_key_save,
            "key.delete": self._h_key_delete,
            "state": self._h_state,
            "search": self._h_search,
            "mode.set": self._h_mode_set,
            "mode.list": self._h_mode_list,
            "reasoning.list": self._h_reasoning_list,
            "reasoning.set": self._h_reasoning_set,
            "sandbox.start": self._h_sandbox_start,
            "sandbox.stop": self._h_sandbox_stop,
            "sandbox.stats": self._h_sandbox_stats,
            "confirm.respond": self._h_confirm_respond,
            "trust.set": self._h_trust_set,
            "conversations.list": self._h_conversations_list,
            "conversations.create": self._h_conversations_create,
            "conversations.switch": self._h_conversations_switch,
            "conversations.delete": self._h_conversations_delete,
            "conversations.rename": self._h_conversations_rename,
            "conversations.duplicate": self._h_conversations_duplicate,
        }
        # Tool confirmations must reach the frontend as events, not a Tkinter
        # callback that only an after() loop would drain.
        #
        # Through `_attach_session` rather than against the `session` argument:
        # restoring a conversation above may already have replaced it, and
        # subscribing the original would leave the live session mute.
        self._attach_session(self.session)

    # -- session plumbing ----------------------------------------------------
    def _attach_session(self, session: AgentSession) -> None:
        """Point the server at a session and wire the callbacks it needs.

        Switching conversations means a different ``AgentSession`` object, and
        the two things a session owns -- the confirmation bridge and the event
        subscription -- live on the object, not on the server. Forgetting either
        is quiet and severe: the new session would answer every request and emit
        no events at all, so the window would show a permanently blank
        transcript and no error anywhere.

        The old subscription is released first. A frontend appends each
        ``message.delta`` to the text it is already showing, so a session
        wired twice does not look like a duplicate frame on the wire -- it looks
        like every answer typed twice, and the longer the session runs the more
        times over.
        """
        if self._unsubscribe is not None:
            self._unsubscribe()
        self.session = session
        session.install_confirmation_bridge()
        self._unsubscribe = session.bus.subscribe(self._on_event)

    def _new_session(self) -> AgentSession:
        """A replacement session configured like the current one.

        Built bare it would come up with no provider bound, so switching chats
        would answer the next message with "no provider configured" -- from a
        conversation the user had been using a moment earlier.

        It gets its own event bus. ``AgentSession`` falls back to a
        process-wide default, and subscribing to that from every replacement
        meant each conversation switch left another live subscriber behind --
        all of them writing every event to stdout, so a chat's tenth switch
        printed each delta ten times over.
        """
        session = AgentSession(bus=EventBus())
        if self.session.provider is not None:
            session.bind_provider(
                self.session.provider_name, self.session.model, self.session.base_url
            )
        # The effort is a property of the window, not of one conversation, so
        # switching chats must not silently reset it to the model default.
        session.set_reasoning_effort(self.session.reasoning_effort)
        return session

    def _persist(self) -> None:
        """Write the current transcript to disk.

        Called when a turn ends rather than on every message. A turn is the unit
        the user thinks in, and saving mid-stream would leave a transcript whose
        last entry is a half-received tool call.
        """
        if not self.conversations or not self.conversation_id:
            return
        conversation = self.conversations.load(self.conversation_id)
        if conversation is None:
            return
        conversation.messages = [m.to_dict() for m in self.session.messages]
        # Retitle from the first user message, but only once. A list that
        # renames itself while you are reading it is disorienting, and a
        # conversation's opening line is the best title it will ever get.
        #
        # The sentinel is what makes a manual name stick: once `rename` has
        # written anything else, this test is false and the name survives every
        # later turn. (Naming a conversation "New chat" opts it back in --
        # indistinguishable from having never been named, which is a fine thing
        # for that name to mean.)
        first_user = next(
            (m.content for m in self.session.messages if m.role_value == "user"),
            None,
        )
        if first_user and conversation.title == "New chat":
            conversation.title = title_from(first_user)
        conversation.project = self.project
        self.conversations.save(conversation)

    def _load_into_session(self, conversation_id: str) -> None:
        """Replace the session with one holding a saved transcript."""
        if self.conversations is None:
            return
        conversation = self.conversations.load(conversation_id)
        if conversation is None:
            return
        from tonyagent.providers import ChatMessage

        session = self._new_session()
        for raw in conversation.messages:
            try:
                # Through ``from_dict`` rather than picking fields here: it is
                # the one place that knows which keys a stored message has, and
                # this loop used to silently drop every field it did not name.
                row = dict(raw)
                row.setdefault("role", "user")
                session.messages.append(ChatMessage.from_dict(row))
            except Exception as exc:  # noqa: BLE001 - one bad row, not a dead chat
                logger.warning(f"Skipping an unreadable message: {exc}")
        self.conversation_id = conversation_id
        self._attach_session(session)

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

        A finished turn is also the point at which the transcript becomes worth
        writing down. It is saved after the event is pushed, so the frontend
        never sees a turn it could not reopen.
        """
        self._write({"event": True, **event.to_dict()})
        if event.type is EventType.TURN_FINISHED:
            try:
                self._persist()
            except Exception as exc:  # noqa: BLE001 - a full disk is not a crash
                logger.error(f"Could not save the conversation: {exc}")

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
        base_url = params.get("base_url", "")
        if not isinstance(model, str):
            model = ""
        if not isinstance(base_url, str):
            base_url = ""
        from tonyagent.providers.factory import normalize_base_url

        try:
            # Normalise before storing, so `state` and the reply agree with the
            # endpoint the provider actually uses (and a trailing slash is gone).
            base_url = normalize_base_url(base_url)
            provider = self.session.bind_provider(name, model, base_url)
        except ValueError as exc:
            # The one user error that lands here is a base_url with no
            # http(s):// scheme. It describes the user's own field, never a
            # secret, so it is safe to surface as a rejection rather than an
            # opaque 500.
            raise RpcError(str(exc)) from None
        if provider is None:
            raise RpcError(f"Unknown provider: {name}")

        # Persist the choice, so the next launch starts on it instead of on a
        # default name with no provider behind it.
        #
        # A failure here is reported rather than raised: the bind itself worked
        # and the session is usable, so failing the whole call would be a lie.
        # But it is not swallowed either -- a selection that silently stops
        # surviving a restart is exactly the bug this replaces, and the user is
        # the only one who can notice it.
        persisted = True
        try:
            from tonyagent.config import save_provider_selection

            save_provider_selection(name, getattr(provider, "model", model), base_url)
        except Exception as exc:  # noqa: BLE001 - a full disk must not kill the bind
            persisted = False
            logger.error(f"Could not save the provider selection: {exc}")

        return {
            "provider": name,
            "model": getattr(provider, "model", model),
            "persisted": persisted,
            # Echo back the *requested* override, not the provider's resolved
            # default. The panel prefills from this, and pinning a default that
            # the provider may later change would be a lie about what the user
            # configured.
            "base_url": base_url,
        }

    async def _h_reasoning_list(self, params: dict) -> Any:
        """What the bound model can be asked to think at.

        Read from the provider rather than a local table, because the effort
        names are the provider's and change with its models. A model that
        cannot think reports ``supported: False`` with no efforts, and the
        frontend's job is to show nothing rather than offer a choice that would
        be refused.
        """
        session = self.session
        spec = await session.reasoning_capability()
        efforts = list(spec.efforts) if spec else []
        if spec is not None and spec.mandatory:
            # Cannot be turned off, so "off" is not one of the options.
            efforts = [e for e in efforts if e != "none"]
        return {
            "model": session.model,
            "supported": spec is not None,
            "efforts": efforts,
            "default_effort": (spec.default_effort if spec else "") or "",
            "mandatory": bool(spec.mandatory) if spec else False,
            "effort": session.reasoning_effort,
        }

    async def _h_reasoning_set(self, params: dict) -> Any:
        """Choose how hard the model should think, and remember it.

        Checked against the model before it is accepted, so a dropdown that
        offers something the request would silently drop cannot report
        success: a rejected effort is a 400 on the next message, and the user
        would be looking at that instead of at their own choice.
        """
        effort = params.get("effort")
        if not isinstance(effort, str):
            raise RpcError("effort must be a string")
        wanted = effort.strip()
        session = self.session
        spec = await session.reasoning_capability()
        if wanted and (spec is None or not spec.accepts(wanted)):
            raise RpcError(
                f"{session.model or 'this model'} does not support thinking effort "
                f"{wanted!r}"
            )
        applied = session.set_reasoning_effort(wanted)
        try:
            from tonyagent.config import save_reasoning_effort

            save_reasoning_effort(applied)
        except Exception as exc:  # noqa: BLE001 - the choice still applies this session
            logger.error(f"Could not save the reasoning effort: {exc}")
            return {"effort": applied, "persisted": False}
        return {"effort": applied, "persisted": True}

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

    # -- credentials ---------------------------------------------------------
    #
    # SECURITY: a key arrives here over stdin and must never leave by any other
    # route. stdout is the protocol, and every line on it is rendered by the
    # frontend -- replies, error messages and events alike. stderr is no
    # safer: the React UI shows it verbatim in the log strip. So the rules are:
    #
    #   * the reply reports only success/failure and the provider NAME
    #   * an error is re-raised with a fixed message, never str(exc), because
    #     keyring's own exceptions can quote the value it was handed
    #   * nothing logs the key, and the request itself is never logged
    #
    # There is deliberately no `key.get`. A protocol method that returns a
    # secret is a method whose secret can end up in a screenshot.

    def _h_key_save(self, params: dict) -> Any:
        from tonyagent.config.keyring import KeyringError, save_api_key

        provider = str(params.get("provider", "")).strip()
        api_key = params.get("api_key", "")
        if not provider:
            raise RpcError("missing provider")
        if not isinstance(api_key, str) or not api_key.strip():
            raise RpcError("missing api_key")
        try:
            save_api_key(provider, api_key)
        except KeyringError:
            # The cause is dropped on purpose: `KeyringError` wraps whatever
            # the keyring backend raised, and quoting it back would put the
            # rejected value in front of the user and into the log strip.
            raise RpcError("the system keyring rejected this key") from None
        return {"provider": provider, "saved": True}

    def _h_key_delete(self, params: dict) -> Any:
        from tonyagent.config.keyring import KeyringError, delete_api_key

        provider = str(params.get("provider", "")).strip()
        if not provider:
            raise RpcError("missing provider")
        try:
            delete_api_key(provider)
        except KeyringError:
            raise RpcError("the system keyring could not delete this key") from None
        return {"provider": provider, "deleted": True}

    def _h_state(self, params: dict) -> Any:
        """Report what the session can actually do, not what it was asked for.

        ``AgentSession`` carries a provider *name* from construction
        ("openrouter") with no provider object behind it, so echoing that name
        straight back made `state` claim a working configuration on a session
        that would reject every message with "no provider configured". A window
        that reloads then shows a provider it cannot use, which reads exactly
        like the key never being saved.

        So the name and model are reported only when a provider is actually
        bound; unbound means "". `bound` is reported explicitly so the frontend
        can tell "no provider" apart from "provider with an empty name" without
        having to infer it.
        """
        bound = self.session.provider is not None
        return {
            "provider": self.session.provider_name if bound else "",
            "model": self.session.model if bound else "",
            "base_url": self.session.base_url if bound else "",
            "bound": bound,
            "busy": self.session.busy,
            "messages": len(self.session.messages),
            "project": self.project,
            "mode": self.session.mode_name,
            "conversation": self.conversation_id,
            "reasoning_effort": self.session.reasoning_effort,
        }

    # -- conversations --------------------------------------------------------
    def _require_store(self) -> ConversationStore:
        if self.conversations is None:
            raise RpcError("conversations are not available in this build")
        return self.conversations

    def _h_conversations_list(self, params: dict) -> Any:
        """List saved conversations, newest first.

        Summaries only. The rows render a title and a timestamp; sending the
        transcripts would mean transferring every conversation's full history on
        each launch to draw a sidebar.
        """
        store = self._require_store()
        try:
            return {"conversations": store.summaries()}
        except Exception as exc:  # noqa: BLE001 - an empty list beats a dead UI
            logger.warning(f"conversations.list failed: {exc}")
            return {"conversations": []}

    def _h_conversations_create(self, params: dict) -> Any:
        """Start a new conversation and switch to it.

        Creating and switching are one action because that is what "New chat"
        means to the person pressing it: a fresh empty conversation, not a new
        row that they then have to go and click.
        """
        store = self._require_store()
        project = str(params.get("project") or self.project or "")
        conversation = store.create(title="New chat", project=project)
        self._persist()  # Bank the outgoing conversation before leaving it.
        self.project = project
        self._load_into_session(conversation.id)
        return {"conversation": conversation.summary()}

    def _h_conversations_switch(self, params: dict) -> Any:
        conversation_id = str(params.get("id") or "")
        if not conversation_id:
            raise RpcError("missing conversation id")
        store = self._require_store()
        conversation = store.load(conversation_id)
        if conversation is None:
            raise RpcError(f"No such conversation: {conversation_id}")
        self._persist()
        self.project = conversation.project
        self._load_into_session(conversation_id)
        return {
            "conversation": conversation.summary(),
            # The transcript, so the window can render the reopened chat without
            # asking for it again. Returning the id alone would leave the user
            # looking at an empty pane wondering whether the click landed.
            "messages": conversation.messages,
            "project": conversation.project,
        }

    def _h_conversations_delete(self, params: dict) -> Any:
        conversation_id = str(params.get("id") or "")
        if not conversation_id:
            raise RpcError("missing conversation id")
        store = self._require_store()
        deleted = store.delete(conversation_id)
        # Deleting the conversation you are looking at leaves you looking at
        # nothing, which reads as a failure rather than as the intended result.
        # So the window is moved on to a fresh one.
        if deleted and conversation_id == self.conversation_id:
            self.conversation_id = ""
            self.session.clear()
        return {"id": conversation_id, "deleted": deleted}

    def _h_conversations_rename(self, params: dict) -> Any:
        """Give a conversation a name the user chose.

        Refused, not repaired, when the name is empty: the title is the only
        handle the list has on a conversation, so quietly substituting
        something else would report success for a rename that did not happen.
        """
        conversation_id = str(params.get("id") or "")
        if not conversation_id:
            raise RpcError("missing conversation id")
        store = self._require_store()
        try:
            conversation = store.rename(
                conversation_id, str(params.get("title") or "")
            )
        except EmptyTitle as exc:
            # Only this one exception. A bare ``except ValueError`` also caught
            # ``UnicodeEncodeError``, so a failure while *writing* the
            # conversation came back as "you gave me a bad name" -- a message
            # pointing at the user's typing for a fault that was not theirs.
            raise RpcError(str(exc)) from exc
        if conversation is None:
            raise RpcError(f"No such conversation: {conversation_id}")
        return {"conversation": conversation.summary()}

    def _h_conversations_duplicate(self, params: dict) -> Any:
        """Copy a conversation under a new id.

        Does not switch to the copy. Jumping the window away from the
        conversation you right-clicked is not what "duplicate" asked for, and
        the new row lands directly below the one you used.
        """
        conversation_id = str(params.get("id") or "")
        if not conversation_id:
            raise RpcError("missing conversation id")
        store = self._require_store()
        conversation = store.duplicate(conversation_id)
        if conversation is None:
            raise RpcError(f"No such conversation: {conversation_id}")
        return {"conversation": conversation.summary()}

    # -- sandbox -------------------------------------------------------------
    async def _h_sandbox_start(self, params: dict) -> Any:
        requested = str(params.get("path", "") or "")
        if requested:
            # Register the folder before starting, not after.
            #
            # `start_sandbox` takes a path and mounts the container on it, but
            # it never told `folder_manager` about it. Only the Tkinter UI
            # called `set_folder`, so under the sidecar the sandbox was running
            # against one directory while every file tool -- and `search` --
            # still resolved paths against "no project folder selected". The
            # symptom was a working sandbox that could not read its own
            # workspace.
            #
            # Doing it first also means a bad path fails before a container is
            # created, rather than leaving one running against nothing.
            from pathlib import Path

            from tonyagent.folder import folder_manager

            if not folder_manager.set_folder(Path(requested)):
                raise RpcError(f"Not a usable folder: {requested}")

        ok = await self.session.start_sandbox(requested)
        # The folder is recorded whether or not a container came up. It is what
        # the file tools and `search` resolve against, so tying it to container
        # success left a machine with no Docker daemon reporting "no folder"
        # while the core had a perfectly usable workspace.
        from tonyagent.folder import folder_manager

        self.project = str(folder_manager.current_folder or params.get("path", ""))
        # `isolated` is reported separately and on purpose. A local runtime
        # means most tools work; only code execution needs the container, and
        # the UI should say which of the two it got rather than showing one
        # boolean for both.
        isolated = bool(self.session.is_sandbox_isolated())
        return {
            "running": bool(ok),
            "isolated": isolated,
            "project": self.project,
        }

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

    # -- search --------------------------------------------------------------
    async def _h_search(self, params: dict) -> Any:
        """Search the project from the UI, using the agent's own grep tool.

        This delegates to ``GrepTool`` rather than scanning here. A second
        implementation would be a second set of rules about which directories
        to skip, how big a file may be, and how a path is confined to the
        project - and the two would drift, so the search the user runs and the
        search the agent runs would quietly disagree.
        """
        from tonyagent.tools import tool_registry
        from tonyagent.tools.base import ToolResultStatus

        pattern = params.get("pattern", "")
        if not isinstance(pattern, str) or not pattern.strip():
            raise RpcError("empty pattern")

        grep = tool_registry.get("grep")
        if grep is None:
            # The registry is populated by importing tonyagent.tools; if grep
            # is genuinely absent that is a broken build, not a user error.
            raise RpcError("search is unavailable in this build")

        result = await grep.execute(
            pattern=pattern,
            path=str(params.get("path", ".")),
            include=str(params.get("include", "")),
            case_sensitive=bool(params.get("case_sensitive", True)),
            max_results=int(params.get("max_results", 100)),
            context_lines=int(params.get("context_lines", 0)),
        )
        if result.status is not ToolResultStatus.SUCCESS:
            # The tool's own message ("Invalid regex: ...") is safe to return:
            # it is derived from the pattern the user typed, never from a secret.
            raise RpcError(result.error or "search failed")

        matches: list[dict] = []
        for artifact in result.artifacts:
            if artifact.get("type") == "grep_result":
                matches = artifact.get("data") or []
                break
        return {"matches": matches, "output": result.output}

    # -- modes ---------------------------------------------------------------
    def _h_mode_set(self, params: dict) -> Any:
        """Switch the composer mode.

        Returns the mode that is actually in force, not the one that was
        asked for: an unrecognised name resolves to Build, and a frontend that
        reported the request back would be lying about what just happened.
        """
        requested = str(params.get("mode", ""))
        mode = self.session.set_mode(requested)
        return {
            "mode": mode.name,
            "label": mode.label,
            "description": mode.description,
            "writes": mode.writes,
        }

    def _h_mode_list(self, params: dict) -> Any:
        """The available modes, in display order.

        The frontend must not hardcode this list: a mode the UI cannot see is
        a mode nobody can select, and the tool allow-lists would drift from
        the labels shown beside them.
        """
        from tonyagent.core.modes import MODE_ORDER, MODES

        return {
            "mode": self.session.mode_name,
            "modes": [
                {
                    "name": MODES[n].name,
                    "label": MODES[n].label,
                    "description": MODES[n].description,
                    "writes": MODES[n].writes,
                }
                for n in MODE_ORDER
            ],
        }

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


def configure_stdio() -> None:
    """Force all three streams to UTF-8, and send all logs to stderr.

    Colour is off, deliberately and not as a matter of taste. loguru decides
    whether to emit ANSI codes by asking whether stderr looks like a terminal,
    and under ``tauri dev`` it decided yes -- so the log strip rendered
    literal ``ESC[32m`` and ``ESC[0m`` in the middle of every line. The
    packaged build answered no and looked fine, which is the worst kind of bug:
    correct in the build the user runs, broken in the one a developer opens.

    The consumer here is a React view rendering text, not a terminal, so the
    answer is the same in every environment.

    **All three** streams are forced to UTF-8, and that is not a preference.
    Under the sidecar they are pipes, so Python picks the *console* code page
    for them: on this machine cp949. Two separate faults came out of that, and
    fixing one hid the other.

    On the way out, cp949 wrote a title's ``...`` as the two bytes ``a1 a6``.
    Tauri's shell plugin decodes the sidecar's output with a strict UTF-8
    decoder, raises ``invalid utf-8 sequence of 1 bytes from index 133``, and
    reports it on the Command's ``error`` event -- which the frontend reads as
    "the core died". One non-ASCII conversation title in a log line therefore
    killed the whole backend on launch.

    On the way *in*, the same code page decoded requests. A rename to
    ``café`` was stored as ``caf챕`` -- silently wrong, no error anywhere -- and
    a rename to ``한`` raised ``UnicodeEncodeError: surrogates not allowed``
    from inside the write, because the three UTF-8 bytes of one character had
    become one Korean character and a stray lead byte. The request stream is
    the one that carries user text, so leaving it on the console code page
    meant the feature was unusable for exactly the people most likely to need
    it.

    ``errors="replace"`` on the output streams rather than strict, so an
    unencodable character is visibly wrong in a log line instead of taking the
    process down with it. ``stdin`` is strict: a request that did not decode is
    a request whose meaning is already unknown, and quietly substituting
    U+FFFD for it would corrupt a conversation instead of reporting the fault.
    """
    for stream, errors in (
        (sys.stdin, "strict"),
        (sys.stdout, "replace"),
        (sys.stderr, "replace"),
    ):
        # A frozen build or a redirected stream may not be a TextIOWrapper, and
        # TextIOWrapper.reconfigure raises on anything else.
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors=errors)
        except (ValueError, OSError):  # pragma: no cover -- platform specific
            pass
    logger.remove()
    logger.add(sys.stderr, level="INFO", colorize=False)


def build_session() -> AgentSession:
    """Create a session already bound to the provider the user last chose.

    Without this the window starts on ``AgentSession``'s default provider *name*
    with no provider object behind it, so ``state`` looks configured while the
    first message fails with "no provider configured" -- which reads, from the
    UI, exactly like a key that was never saved.

    Every failure here falls back to an unbound session rather than raising.
    A sidecar that cannot start is a dead app; a sidecar that starts and asks
    for a provider is a working app telling the truth about what it needs.
    """
    session = AgentSession()
    try:
        from tonyagent.config import load_config
        from tonyagent.config.migration import get_config_path

        # Log which file this is reading. `get_config_dir` resolves `APPDATA`,
        # and on Windows that value is *different processes' answers to the
        # question*: a Microsoft Store Python redirects it under
        # `AppData\Local\Packages\...\LocalCache\Roaming`, while the
        # packaged sidecar gets the real one. So a launch can report "no saved
        # provider" while a perfectly good config sits a directory away, and
        # nothing on screen says which file was asked for.
        try:
            logger.info(f"Reading provider selection from {get_config_path()}")
        except Exception:  # noqa: BLE001 - the path is a diagnostic, not a gate
            pass

        provider = load_config().get("provider") or {}
        name = str(provider.get("name") or "").strip()
        if not name:
            logger.info("No saved provider; starting unbound.")
            return session
        model = str(provider.get("model") or "")
        base_url = str(provider.get("base_url") or "")
        bound = session.bind_provider(name, model, base_url)
        if bound is None:
            logger.warning(
                f"Saved provider {name!r} is no longer available; starting unbound."
            )
        else:
            logger.info(f"Restored provider {name!r} (model={model or 'default'!r}).")
        # Applied after the bind, because the model has to be known before an
        # effort can be checked against what it offers.
        session.set_reasoning_effort(str(provider.get("reasoning_effort") or ""))
    except Exception as exc:  # noqa: BLE001 - never fail startup over config
        logger.warning(f"Could not restore the saved provider: {exc}")
    return session


def build_store() -> ConversationStore:
    """Where conversations live on disk.

    A sibling of ``config.toml`` rather than inside the project folder: a
    conversation is a property of the person using the app, not of whichever
    directory happens to be open, and putting it under the project would make
    the history disappear the moment you switched folders.

    Failure to create the directory is not fatal here -- the store writes
    lazily and reports its own failures -- because a sidecar that refuses to
    start is worse than one that starts and cannot yet save.
    """
    from tonyagent.config.settings import settings

    return ConversationStore(settings.get_config_dir() / "conversations")


async def run(session: AgentSession | None = None) -> None:
    """Entry point for ``python -m tonyagent.headless.server``."""
    configure_stdio()
    session = session or build_session()

    store = build_store()
    # Reopen the most recent conversation, so launching the app puts you back
    # where you were. Restoring it into the session here rather than in the
    # frontend means the history is present before the window asks for anything,
    # which is what keeps a reload from showing an empty transcript.
    conversation_id = ""
    try:
        recent = store.most_recent()
        if recent is not None:
            conversation_id = recent.id
            logger.info(f"Reopening conversation {recent.title!r}.")
    except Exception as exc:  # noqa: BLE001 - never fail startup over history
        logger.warning(f"Could not read saved conversations: {exc}")

    await StdioServer(
        session, sys.stdin, sys.stdout, store=store, conversation_id=conversation_id
    ).serve()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
