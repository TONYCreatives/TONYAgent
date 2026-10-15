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
from tonyagent.core.attachments import AttachmentError
from tonyagent.core.attachments import strip_images
from tonyagent.core.attachments import validate as validate_attachments
from tonyagent.core.events import Event, EventBus, EventType
from tonyagent.core.session import AgentSession
from tonyagent.core.skills import discover_current_skills
from tonyagent.core.task_state import SessionState

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


def _permission_payload(level: Any) -> dict[str, Any]:
    """One permission level, as the window needs to draw it.

    Sends ``runs_commands`` and ``skips_confirmation`` as booleans rather than
    making the frontend infer them from the label or the description. The bar
    has to be able to say what a level actually permits -- that is the whole
    point of it -- and prose is not something to parse.
    """
    return {
        "name": level.name,
        "label": level.label,
        "description": level.description,
        # The one fact the bar most needs: whether a shell command can even be
        # attempted. Low and Medium differ from High by exactly this, and it is
        # what separates the two middle rungs at a glance.
        "runs_commands": "execute_command" in level.allowed_tools,
        # Whether the user is asked before a destructive tool runs. Reported
        # separately because it is a different kind of permission from the
        # allow-list: it removes the question, not the check.
        "skips_confirmation": level.skips_confirmation,
        # Whether commands outside the allow-list run. Sent as its own flag so
        # the bar can mark the one rung that widens the command allow-list
        # without having to read the description to find out. This is the fact a
        # user most needs before choosing Full, so it must not be prose-only.
        "runs_any_command": level.bypasses_command_allowlist,
        # Whether this level runs model-authored code on the user's own machine
        # rather than in the sandbox. Sent as a flag for the same reason as the
        # one above and for a sharper reason: this is the fact a user most needs
        # before *choosing* the level, because it is the difference between
        # "very permissive inside a container" and "no container at all". It is
        # also the one fact the description alone must never be the only record
        # of, so the window can mark it rather than print it and hope it is read.
        "runs_on_host": level.runs_on_host,
    }


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
        #
        # Read from `folder_manager` rather than left empty, because that is the
        # folder the file tools are already resolving against. `folder_manager`
        # restores the last choice from settings at import, so a window launched
        # with a project open had a working folder and no record of it: `state`
        # reported none, "New chat" asked for a folder the user had already
        # chosen, and a chat created after a restart was filed under nothing.
        # Same disagreement as the one `_bind_project` fixes, one level up.
        from tonyagent.folder import folder_manager as _folder_manager

        self.project: str = str(_folder_manager.current_folder or "")
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
            "key.list": self._h_key_list,
            "key.delete": self._h_key_delete,
            "key.reveal": self._h_key_reveal,
            "key.activate": self._h_key_activate,
            "usage.summary": self._h_usage_summary,
            "state": self._h_state,
            "context.get": self._h_context_get,
            "search": self._h_search,
            "mode.set": self._h_mode_set,
            "mode.list": self._h_mode_list,
            "skills.list": self._h_skills_list,
            "reasoning.list": self._h_reasoning_list,
            "reasoning.set": self._h_reasoning_set,
            "sandbox.start": self._h_sandbox_start,
            "sandbox.stop": self._h_sandbox_stop,
            "sandbox.stats": self._h_sandbox_stats,
            "confirm.respond": self._h_confirm_respond,
            "user.respond": self._h_user_respond,
            "trust.set": self._h_trust_set,
            "models.list": self._h_models_list,
            "tools.get": self._h_tools_get,
            "tools.set": self._h_tools_set,
            "plan.get": self._h_plan_get,
            "permission.list": self._h_permission_list,
            "permission.set": self._h_permission_set,
            "conversations.list": self._h_conversations_list,
            "conversations.create": self._h_conversations_create,
            "conversations.switch": self._h_conversations_switch,
            "conversations.delete": self._h_conversations_delete,
            "conversations.rename": self._h_conversations_rename,
            "conversations.duplicate": self._h_conversations_duplicate,
            "conversations.move": self._h_conversations_move,
            "files.tree": self._h_files_tree,
            "files.read": self._h_files_read,
            "files.write": self._h_files_write,
        }
        # Tool confirmations must reach the frontend as events, not a
        # callback that only a queue processor would drain.
        #
        # Through `_attach_session` rather than against the `session` argument:
        # restoring a conversation above may already have replaced it, and
        # subscribing the original would leave the live session mute.
        self._attach_session(self.session)

    # -- session plumbing ----------------------------------------------------
    def _attach_session(self, session: AgentSession) -> None:
        """Point the server at a session and wire the callbacks it needs.

        Switching conversations means a different ``AgentSession`` object, and
        the things a session owns -- the confirmation bridge, the question
        bridge and the event subscription -- live on the object, not on the
        server. Forgetting any is quiet and severe: the new session would answer
        every request and emit no events at all, so the window would show a
        permanently blank transcript and no error anywhere.

        The old subscription is released first. A frontend appends each
        ``message.delta`` to the text it is already showing, so a session
        wired twice does not look like a duplicate frame on the wire -- it looks
        like every answer typed twice, and the longer the session runs the more
        times over.

        **The outgoing conversation's subagents leave with it.** The registry is
        process-wide -- one window, one place for ``list_agents`` to look -- but
        a child is spawned for the session whose turn is running, and only that
        session's turn can read its answer back. Left standing, the outgoing
        chat's children would be listed in the incoming chat's ``list_agents``,
        and a still-running one would keep working for a conversation the window
        has left. Dropping them is the same host act as wiring the new session
        below, and it happens here rather than at the call sites so every path
        that replaces a session -- switch, new chat, startup restore -- gets it.
        """
        if self._unsubscribe is not None:
            self._unsubscribe()
        from tonyagent.tools.subagent_tools import subagent_registry

        subagent_registry.restart()
        self.session = session
        session.install_confirmation_bridge()
        session.install_question_bridge()
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
            # The replacement session carries a provider of its own, so the id has
            # to be handed to *that* one: `_sync_provider_session` after the swap
            # does exactly this, and this line is why the swap is not a request
            # away from being wrong.
            self._sync_provider_session()
        # The effort is a property of the window, not of one conversation, so
        # switching chats must not silently reset it to the model default.
        session.set_reasoning_effort(self.session.reasoning_effort)
        # Same for the permission level, and for a stronger reason. A fresh
        # session starts at the default level, so switching conversations would
        # quietly hand the agent back the permissions the user had just taken
        # away -- and the window's bar would go on showing their choice while
        # the core enforced something else. The bar and the gate have to agree.
        session.set_permission(self.session.permission_name)
        return session

    def _bind_project(self, project: str) -> None:
        """Point the working folder at ``project``.

        **Why this is not just bookkeeping on ``self.project``.** The file
        tools and ``search`` resolve their paths against ``folder_manager``, not
        against the field ``state`` echoes back. A conversation carries the
        project it belongs to, so opening one whose project differs from the
        current folder has to move the folder too -- otherwise the window says
        one project while every tool reads another, and the agent edits files in
        a directory the user is not looking at.

        Switching is not *starting*: this records the folder and leaves any
        running sandbox alone, because mounting a container is the user's
        explicit act and a background restart on every conversation click would
        be a surprising thing for a click to do.

        A folder that has since been moved or deleted is reported rather than
        raised. The conversation is still perfectly readable and its transcript
        still loads; refusing the switch would trade a degraded workspace for a
        window that cannot open a chat at all. The old folder is kept, so the
        tools keep working against something real instead of nothing.
        """
        project = str(project or "")
        if not project:
            # Nothing to bind. Clearing the folder here would take away a
            # working one on behalf of a conversation that simply has no project
            # recorded -- the shape every conversation saved before `project`
            # existed is in.
            return
        from pathlib import Path

        from tonyagent.folder import folder_manager

        current = folder_manager.current_folder
        if current is not None and str(current) == project:
            self.project = project
            return
        if folder_manager.set_folder(Path(project)):
            self.project = project
            return
        logger.warning(
            f"Could not open project folder {project}; keeping {current}. "
            "Its tools will not resolve against the conversation's project."
        )

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
        conversation.messages = strip_images(self.session.messages)
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
        # The plan travels with the transcript. Saved here rather than from the
        # planning tools, which have no store to write to -- and a turn is the unit
        # this app saves on, so a plan written mid-turn is banked with the turn that
        # wrote it.
        conversation.state = self.session.state.to_dict()
        self.conversations.save(conversation)

    def _sync_provider_session(self) -> None:
        """Tell the bound provider which conversation it is serving.

        **The provider outlives the conversation, and the session header must not.**
        OpenCode Go routes and caches per session and rejects a request without
        `x-opencode-session`, so the id has to follow the chat rather than the
        process -- while the provider is bound when the *settings* change, which
        happens far less often than switching chats. Both of the places that change
        either one call this, so the two cannot drift apart.

        A provider that has no session notion is left alone: `set_session` is on the
        shared base, and a gateway that never asked for an id never sends one.
        """
        provider = getattr(self.session, "provider", None)
        setter = getattr(provider, "set_session", None)
        if setter is None:
            return
        setter(self.conversation_id or "")

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
        # Adopted *after* the session exists: `_new_session` publishes an empty
        # state for the session it builds, so doing this first would be immediately
        # overwritten by that and the plan would silently not come back.
        session.set_state(SessionState.from_dict(conversation.state))
        self.conversation_id = conversation_id
        self._attach_session(session)
        self._sync_provider_session()

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
        if not isinstance(text, str):
            raise RpcError("text must be a string")
        # Validated here, not in the window. A message is a JSON object on a
        # pipe: anything that can write to the pipe can claim a 400MB
        # attachment is 4KB, and the size limits are the ones that keep a
        # request inside what the provider will accept.
        try:
            attachments = validate_attachments(params.get("attachments"))
        except AttachmentError as exc:
            # A rejection the user can act on, so it is a message rather than
            # a generic failure: "this is a PDF" is a different problem from
            # "something went wrong" and only one of them has a next step.
            raise RpcError(str(exc)) from None
        # What the user changed by hand in the viewer since the last message.
        # Appended to the text rather than kept beside it, so the report is
        # part of the conversation the model receives *and* part of what the
        # transcript records -- a reloaded conversation shows exactly what
        # the agent was told about the files, which is knowledge the user is
        # entitled to audit.
        edits = params.get("user_edits")
        if edits is not None and not isinstance(edits, list):
            raise RpcError("user_edits must be a list")
        report = ""
        if edits:
            from tonyagent.files import format_edit_report

            report = format_edit_report(edits)
        if report:
            text = f"{text}\n\n{report}" if text.strip() else report
        turn_id = self.session.send(text, attachments)
        if not turn_id:
            # Explain which precondition failed so the UI can say something
            # useful, instead of a generic "rejected".
            if not text.strip() and not attachments:
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
        # Bound last, told first: a provider switched to mid-conversation must not
        # spend one request under the previous session's id.
        self._sync_provider_session()

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
    # **`key.reveal` is the one exception, and it was asked for rather than
    # assumed.** This used to be a flat refusal to have any method that returns a
    # secret -- "a method that returns a secret is a method whose secret can end
    # up in a screenshot" -- and that is still exactly what it costs. What the
    # controls buy back is the *window*: the value leaves the keyring only when
    # the user presses Reveal for one named provider, only once, and the frontend
    # clears it on hide, on a provider change and on close.
    #
    # Nothing that runs on its own ever pulls a key out. `providers.list` still
    # reports a boolean, `state` still carries no credential, so the only caller
    # of `key.reveal` is a press. A future method that returns a key without
    # being asked would be the thing this paragraph exists to stop.

    @staticmethod
    def _key_name(params: dict, *, required: bool) -> str | None:
        """Canonicalise the optional name parameter, or None when it is absent.

        One reader rather than five, because the difference between the RPCs is
        exactly the difference between the parameters -- key.delete and
        key.activate name a key, key.save and key.reveal may leave it out -- and
        five copies of this rule is five places for them to drift.

        Values are canonicalised here rather than in keyring, so the name the
        registry records and the name the caller reads back are the same
        string. A name with no letters or digits is refused instead of being
        folded onto the default slot, where it would overwrite the legacy key.
        """
        from tonyagent.config.keyring import KeyringError, normalize_key_name

        raw = params.get("name")
        if raw is None or (isinstance(raw, str) and not raw.strip()):
            if required:
                raise RpcError("missing name")
            return None
        if not isinstance(raw, str):
            raise RpcError("name must be a string")
        try:
            return normalize_key_name(raw)
        except KeyringError:
            raise RpcError("a key name needs at least one letter or digit") from None

    def _h_key_save(self, params: dict) -> Any:
        """Store one key under one name, without ever echoing the value.

        Saving does not make a named key active -- except the first key a
        provider has ever had. Without that exception a user could save their
        only key, close the panel, and come back to a provider whose active
        name (default) resolves to nothing, which reads as a broken save.
        """
        from tonyagent.config.keyring import (
            KeyringError,
            save_api_key,
            stored_key_names,
        )
        from tonyagent.config.migration import add_key_name, set_active_key_name

        provider = str(params.get("provider", "")).strip()
        api_key = params.get("api_key", "")
        if not provider:
            raise RpcError("missing provider")
        if not isinstance(api_key, str) or not api_key.strip():
            raise RpcError("missing api_key")
        name = self._key_name(params, required=False) or "default"

        # Read before the save: "did this provider have any key at all" is not
        # a question that can be asked afterwards, because the save just
        # changed the answer.
        first_key = not stored_key_names(provider)

        try:
            save_api_key(provider, api_key, name)
        except KeyringError:
            # The cause is dropped on purpose: `KeyringError` wraps whatever
            # the keyring backend raised, and quoting it back would put the
            # rejected value in front of the user and into the log strip.
            raise RpcError("the system keyring rejected this key") from None

        # The key is stored at this point, so a registry failure must not be
        # reported as a failed save -- that would send the user to re-paste a
        # key that is already there. It is not swallowed either: `listed` is
        # the panel's only way to know the row it draws will survive a reload.
        listed = True
        try:
            add_key_name(provider, name)
            if first_key:
                set_active_key_name(provider, name)
        except Exception as exc:  # noqa: BLE001 - the secret is already safe
            listed = False
            logger.error(f"Could not record the key name for {provider}: {exc}")
        return {"provider": provider, "name": name, "saved": True, "listed": listed}

    def _h_key_list(self, params: dict) -> Any:
        """Every stored key as a row, and never a value.

        The reply is the panel's list: provider, name and which one is active.
        Nothing here touches a secret -- get_password is not called -- so this
        stays outside the one-method exception that key.reveal is.

        Names come from the config registry (the keyring cannot be
        enumerated), plus the default slot, which predates the registry. The
        result is the bare list the protocol document specifies, not a wrapper
        object, because there is exactly one thing to return.
        """
        from tonyagent.config.keyring import active_key_name, stored_key_names
        from tonyagent.config.migration import load_config

        provider = str(params.get("provider", "")).strip()
        if provider:
            wanted = [provider]
        else:
            from tonyagent.providers.base import provider_registry

            wanted = list(provider_registry.list_providers())
            # A key can outlive the provider it was saved for (renamed, or
            # removed from the registry). Listing those too is what lets the
            # panel draw the row and delete it, rather than leaving a secret
            # in the keyring that no screen admits to.
            try:
                section = load_config().get("keys")
                if isinstance(section, dict):
                    wanted += [name for name in section if name not in wanted]
            except Exception as exc:  # noqa: BLE001 - the registry is best effort
                logger.warning(f"key.list could not read the key registry: {exc}")

        entries: list[dict] = []
        for name in wanted:
            active = active_key_name(name)
            for stored in stored_key_names(name):
                entries.append(
                    {"provider": name, "name": stored, "active": stored == active}
                )
        return entries

    def _h_key_reveal(self, params: dict) -> Any:
        """Hand back one stored key, on request.

        The only method in this server that returns a secret. See the block
        above for what that costs and what bounds it.

        `load_api_key` answers ``None`` for both "nothing stored" and "the
        keyring would not answer", because it swallows the failure and logs it.
        That is the right trade here: the caller shows an empty field the user
        can re-save, and a keyring error -- which can quote the value it was
        handed -- has no path to the page through an exception.
        """
        from tonyagent.config.keyring import (
            KeyringError,
            load_api_key,
            resolve_key_name,
        )

        provider = str(params.get("provider", "")).strip()
        if not provider:
            raise RpcError("missing provider")
        # Absent means "the key in force", so the reply carries the name it
        # resolved as well as the value: the panel labels a row with it, and a
        # panel that guessed would be labelling the wrong one after an
        # activation from another window.
        if params.get("name") is None or str(params.get("name", "")).strip() == "":
            try:
                name = resolve_key_name(provider)
            except KeyringError:
                raise RpcError("a key name needs at least one letter or digit") from None
        else:
            name = self._key_name(params, required=True)
        return {"provider": provider, "name": name, "api_key": load_api_key(provider, name)}

    def _h_key_delete(self, params: dict) -> Any:
        """Remove one named key, and forget its name."""
        from tonyagent.config.keyring import KeyringError, delete_api_key
        from tonyagent.config.migration import remove_key_name

        provider = str(params.get("provider", "")).strip()
        if not provider:
            raise RpcError("missing provider")
        # name is required here, unlike save: "delete the active key" is a
        # destructive default, and a request that forgot the name must not
        # quietly remove a key the user did not point at.
        name = self._key_name(params, required=True)
        assert name is not None  # required=True either raises or answers
        try:
            delete_api_key(provider, name)
        except KeyringError:
            raise RpcError("the system keyring could not delete this key") from None
        try:
            remove_key_name(provider, name)
        except Exception as exc:  # noqa: BLE001 - the secret is already gone
            logger.error(f"Could not forget the key name for {provider}: {exc}")
        return {"provider": provider, "name": name, "deleted": True}

    def _h_key_activate(self, params: dict) -> Any:
        """Choose which stored key this provider's turns spend.

        The name is checked against what is actually stored before it is
        recorded. An active pointer naming an empty slot would make every
        later turn fail with a missing credential, and the panel's press would
        have reported success on the way there.
        """
        from tonyagent.config.keyring import stored_key_names
        from tonyagent.config.migration import set_active_key_name

        provider = str(params.get("provider", "")).strip()
        if not provider:
            raise RpcError("missing provider")
        name = self._key_name(params, required=True)
        assert name is not None
        if name not in stored_key_names(provider):
            # Safe to quote: this is a name the user typed, never a value.
            raise RpcError(f"no key named {name!r} is stored for {provider}")
        try:
            set_active_key_name(provider, name)
        except Exception as exc:  # noqa: BLE001 - a full disk must not be silent
            logger.error(f"Could not save the active key name for {provider}: {exc}")
            raise RpcError("the key choice could not be saved") from None
        return {"provider": provider, "name": name, "active": True}

    # -- usage ---------------------------------------------------------------
    def _h_usage_summary(self, params: dict) -> Any:
        """Everything the dashboard draws for one window, in one reply.

        One method rather than five. The totals, the day series and the
        per-key breakdowns are all derived from the same pass over the same
        records and are drawn together, so five round trips would be five
        chances for the five answers to disagree with each other.

        The window is validated here rather than defaulted quietly: a typo in a
        window name would otherwise answer with `7d` and look like it worked.
        """
        from tonyagent.core.usage import WINDOWS, ledger

        window = str(params.get("window") or "7d")
        if window not in WINDOWS:
            raise RpcError(f"Unknown window: {window}")
        try:
            return ledger().summary(window)
        except Exception as exc:  # noqa: BLE001 - an empty dashboard beats a dead UI
            logger.warning(f"usage.summary failed: {exc}")
            return {
                "window": window,
                "since": None,
                "totals": {
                    "requests": 0,
                    "failed": 0,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "reasoning_tokens": 0,
                    "total_tokens": 0,
                    "duration_ms": 0,
                },
                "buckets": [],
                "by_key": [],
                "by_provider": [],
                "by_model": [],
                "tracking_since": None,
            }

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
            # Reported in `state` as well as `permission.list` so a reloaded
            # window draws the level the core is actually enforcing. Reading it
            # from the core's own session rather than from local state is what
            # stops the bar claiming Medium while the gate is set to Full.
            "permission": self.session.permission_name,
            "conversation": self.conversation_id,
            "reasoning_effort": self.session.reasoning_effort,
            # The runtime, read rather than remembered. A restored project path
            # arrives here with no container behind it, so a window that only
            # listened for sandbox.status events would show "stopped" over a
            # core that is already serving one -- and would offer Start for a
            # sandbox that is up.
            "sandbox": self.session.sandbox_status(),
        }

    async def _h_context_get(self, params: dict) -> Any:
        """How full the conversation is, for a frontend that draws a meter.

        A method of its own rather than two keys on `state`, for the reason
        `plan.get` documents: `state` is about the session's mode, permission
        and sandbox, and a reader of it should not have to know about a field
        it does not use.

        Both numbers are measurements and both are allowed to be absent:

        * ``used`` is the input side of the most recent request to this model,
          which is what the provider saw as the context -- not a tokenizer's
          guess at it, and not a sum over the window, which would be spend.
        * ``window`` is the model's own `context_length`, from the same
          ``/models`` response the model picker already fetches.

        ``known`` is False when the provider reported no usage for the last
        request, and ``window`` is 0 when it does not publish a context size. A
        frontend must draw "unknown" in both cases: a bar reading 0% for a long
        conversation is worse than no bar, because it is confidently wrong.
        """
        from tonyagent.core.usage import current_context

        model = self.session.model
        used = current_context(model) if model else {"used": 0, "known": False}

        window = 0
        client = getattr(self.session.provider, "http_client", None)
        if model and client is not None:
            try:
                window = await client().model_context_window()
            except Exception as exc:  # noqa: BLE001 - a missing meter is not a failure
                logger.warning(f"Could not read the model context window: {exc}")

        return {
            "model": model,
            "used": int(used.get("used", 0) or 0),
            "known": bool(used.get("known", False)),
            "window": int(window or 0),
        }

    def _h_plan_get(self, params: dict) -> Any:
        """The plan for the open conversation.

        Here so a window can draw the task list without scraping it back out of a
        tool result. The plan is already rendered into the system prompt and appears
        as a card whenever it changes; this is the version something can read at any
        time, including on the first paint after a reload.

        **Not folded into ``state``.** That reply is about the session's mode,
        permission and sandbox, and adding a key to it would oblige every existing
        reader to know about a field it does not use. A new method costs nothing.

        ``rendered`` is returned as well as the structured form so a reader can show
        exactly what the model is being shown, rather than a second rendering of the
        same data that could disagree with it.
        """
        state = self.session.state
        return {
            "plan": state.to_dict(),
            "summary": state.summary(),
            "rendered": state.render(),
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

        **The second press reuses the first one's conversation.** What the user
        is asking for is *an empty chat*, and they already have one -- making
        another leaves the sidebar with two rows titled "New chat", neither of
        which has anything in it. So this switches to the empty one when there
        is one and creates only when there is not. The reply has the same shape
        either way, which is what lets the window stay unaware of which happened
        -- and `showMessages([])` is right in both cases, because the
        conversation being switched to is empty by definition.
        """
        store = self._require_store()
        project = str(params.get("project") or self.project or "")
        conversation = store.find_empty(project)
        if conversation is None:
            conversation = store.create(title="New chat", project=project)
        self._persist()  # Bank the outgoing conversation before leaving it.
        # The folder moves *before* the session is replaced, so the tools the
        # new chat will use already resolve against its own project. See
        # `_bind_project` for why this is not optional bookkeeping.
        self._bind_project(project)
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
        self._bind_project(conversation.project)
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
        #
        # **The window does that, not this.** A conversation invented here would
        # be one the window has never heard of -- there is no push for "you are
        # now in a different conversation" -- so the reply would have to carry it
        # and every caller would have to adopt it. `conversations.create` already
        # exists, files under the folder the window knows it is in, and answers
        # the window directly. What this owes the window is a cleared session, so
        # the fresh conversation does not open holding the deleted one's
        # transcript.
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

    def _h_conversations_move(self, params: dict) -> Any:
        """File a conversation under a folder.

        This is what makes a folder a *place* rather than a filter. The window
        works in one folder at a time, so changing that folder moves the chat you
        are looking at into it -- and a chat and the folder it is about cannot
        drift apart, which is the whole point of the sidebar listing one folder's
        chats.

        The folder is named rather than read from ``self.project``. The caller
        has just bound it and knows which one it settled on (a path that will not
        open leaves the old folder in place), so taking it from here would file
        the chat under a folder the pick never reached.

        When the moved conversation is the open one, the core's own project
        follows it. ``_bind_project`` is the one place that points the folder and
        the file tools at the same directory, and a ``state`` still reporting the
        old folder over a chat filed under the new one is exactly the
        disagreement it exists to prevent.
        """
        conversation_id = str(params.get("id") or "")
        if not conversation_id:
            raise RpcError("missing conversation id")
        # Stripped, so a path of spaces is a missing path rather than a folder
        # named "   ". The store accepts any string, so the check has to be here.
        project = str(params.get("project") or "").strip()
        if not project:
            raise RpcError("missing project path")
        store = self._require_store()
        conversation = store.move(conversation_id, project)
        if conversation is None:
            raise RpcError(f"No such conversation: {conversation_id}")
        if conversation_id == self.conversation_id:
            self._bind_project(project)
        return {"conversation": conversation.summary()}

    # -- sandbox -------------------------------------------------------------
    async def _h_sandbox_start(self, params: dict) -> Any:
        requested = str(params.get("path", "") or "")
        # Imported once, above the branch, because the name is read below
        # whether or not a path came in. It used to be imported inside the
        # `if` and again further down -- two imports for one use, and a reader
        # had to work out which one covered which line.
        from pathlib import Path

        from tonyagent.folder import folder_manager

        if requested:
            # Register the folder before starting, not after.
            #
            # `start_sandbox` takes a path and mounts the container on it, but
            # it never told `folder_manager` about it. Only the old UI
            # called `set_folder`, so under the sidecar the sandbox was running
            # against one directory while every file tool -- and `search` --
            # still resolved paths against "no project folder selected". The
            # symptom was a working sandbox that could not read its own
            # workspace.
            #
            # Doing it first also means a bad path fails before a container is
            # created, rather than leaving one running against nothing.
            if not folder_manager.set_folder(Path(requested)):
                raise RpcError(f"Not a usable folder: {requested}")

        # The folder was registered above, before the container was asked for.
        ok = await self.session.start_sandbox(requested)
        # The folder is recorded whether or not a container came up. It is what
        # the file tools and `search` resolve against, so tying it to container
        # success left a machine with no Docker daemon reporting "no folder"
        # while the core had a perfectly usable workspace.
        self._bind_project(
            str(folder_manager.current_folder or params.get("path", ""))
        )
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

    # -- questions / presentations ------------------------------------------
    def _h_user_respond(self, params: dict) -> Any:
        question_id = params.get("id", "")
        if not question_id:
            raise RpcError("missing question id")
        answer = params.get("answer", "")
        if not isinstance(answer, str):
            raise RpcError("answer must be a string")
        answered = self.session.respond_to_question(question_id, answer)
        # Reported, not raised: a reply that arrives after the ask timed out or
        # the turn stopped is the normal end of a race, and the frontend has
        # already closed its dialog on the way out.
        return {"id": question_id, "answered": answered}

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

    # -- files ----------------------------------------------------------------
    async def _h_files_tree(self, params: dict) -> Any:
        """The project tree, for the window's file explorer.

        Delegates to ``tonyagent.files`` for the same reason ``search``
        delegates to ``GrepTool``: the skip rules and the project boundary
        are the agent's, and a second walk in the server would be a second
        set of rules about what counts as inside the project.

        Reads, always. There is no write path here by design -- the agent's
        ``write`` is confirmation-gated, and a UI write that skipped the
        same gate would be a quieter door into the project. See the module
        docstring in ``tonyagent/files.py``.
        """
        from tonyagent.files import project_tree

        tree = project_tree(
            path=str(params.get("path", ".")),
            max_entries=int(params.get("max_entries", 4000)),
            max_depth=int(params.get("max_depth", 6)),
        )
        return tree.to_dict()

    async def _h_files_read(self, params: dict) -> Any:
        """One project file, as whatever the viewer should show for it.

        The reply is one of three shapes -- `text`, `image`, `binary` -- and
        the *core* decides which, because it has the bytes: an image is an
        image because it decodes, a `.zip` is a file the window can name but
        not draw, and "that file is not there" is the only failure. See
        `tonyagent.files.read_for_viewer`.
        """
        from tonyagent.files import SourceError, read_for_viewer

        path = params.get("path", "")
        if not isinstance(path, str) or not path.strip():
            raise RpcError("missing path")
        try:
            return read_for_viewer(path).to_dict()
        except SourceError as exc:
            # The message names the file and the reason, all derived from the
            # path the caller sent -- safe to return verbatim.
            raise RpcError(str(exc)) from None

    async def _h_files_write(self, params: dict) -> Any:
        """Save the window's text back to a project file.

        **This is the user's write, not the agent's.** The confirmation gate
        on the `write` tool exists to ask the user before the *agent*
        touches their files; a person editing the file they are looking at
        is the act the gate is protecting their right to perform. What this
        owes them is the boundary (confined), the cap, an atomic replace so
        a crash cannot truncate a source file, and the report of what
        changed -- which is what the reply carries and what
        `format_edit_report` later hands the model.

        Only text, and only files that already exist: creating a file is the
        agent's tool's business, where the user is asked first.
        """
        from tonyagent.files import SourceError, write_source

        path = params.get("path", "")
        content = params.get("content")
        if not isinstance(path, str) or not path.strip():
            raise RpcError("missing path")
        if not isinstance(content, str):
            raise RpcError("content must be a string")
        try:
            return write_source(path, content).to_dict()
        except SourceError as exc:
            raise RpcError(str(exc)) from None

    # -- models --------------------------------------------------------------
    async def _h_models_list(self, params: dict) -> Any:
        """Every model the bound provider offers.

        From the provider's own ``/models`` endpoint, not from the registry's
        seed list, because the seed is five illustrative ids and the point of
        this method is that the user can pick any of the hundreds. It is also
        an auth probe: a gateway that will not list its models will not serve
        them either, and saying so is more useful than an empty menu.

        The empty list is reported as an error rather than as "no models". An
        empty dropdown and a failed read look identical in the window, and one
        of them is a fixable problem the user needs to hear about.
        """
        if self.session.provider is None:
            raise RpcError("no provider configured")
        models = await self.session.available_models()
        if not models:
            raise RpcError(
                f"{self.session.provider_name or 'This provider'} returned no "
                "models. Check the API key and the endpoint."
            )
        return {"models": models, "current": self.session.model}

    # -- the tool call budget ------------------------------------------------
    def _h_tools_get(self, params: dict) -> Any:
        """The per-turn tool call budget, as it stands.

        Read from the session rather than from settings, because the session is
        what a turn actually consults and the two can differ the moment
        someone changes it here. A control that showed the setting file would
        report a number the next turn is not held to.
        """
        return {
            "max_tool_calls": self.session.max_tool_calls,
            "label": self.session._budget_payload()["label"],
        }

    def _h_tools_set(self, params: dict) -> Any:
        """Change how many tool calls one turn may make.

        Validated rather than clamped silently: a limit the user did not ask for
        is worse than a refusal they can see. One is the floor for a real budget
        -- zero is not a small budget, it is a refusal of every tool -- and
        anything *below* zero is not a smaller budget at all, so it is an error
        the UI can show.

        **Zero is the exception: it means no limit.** It is the one value below
        the floor, which is what makes it safe to give it the opposite meaning --
        see `AgentSession.set_max_tool_calls`.
        """
        raw = params.get("max_tool_calls")
        if isinstance(raw, bool) or not isinstance(raw, (int, float, str)):
            raise RpcError("max_tool_calls must be a number")
        try:
            wanted = int(raw)
        except (TypeError, ValueError):
            raise RpcError("max_tool_calls must be a whole number") from None
        # 0 is the sentinel for no limit and passes; below it is not a smaller
        # budget but a negative one, which is a mistake rather than a choice.
        if wanted < 0:
            raise RpcError("a tool call budget cannot be negative")
        applied = self.session.set_max_tool_calls(wanted)
        try:
            from tonyagent.config import save_max_tool_calls

            save_max_tool_calls(applied)
        except Exception as exc:  # noqa: BLE001 - the choice still applies now
            logger.error(f"Could not save the tool call budget: {exc}")
            return {"max_tool_calls": applied, "persisted": False}
        return {"max_tool_calls": applied, "persisted": True}

    # -- permissions --------------------------------------------------------
    def _h_permission_set(self, params: dict) -> Any:
        """Change what the agent is allowed to do on the next turn.

        Returns the level that is actually in force rather than the one that
        was asked for, for the same reason `mode.set` does: an unrecognised
        name resolves to the default, so a frontend echoing the request back
        would be labelling a level the core is not enforcing.
        """
        requested = str(params.get("permission", ""))
        level = self.session.set_permission(requested)
        return _permission_payload(level)

    def _h_permission_list(self, params: dict) -> Any:
        """The available levels, in display order.

        Not hardcoded in the frontend, for the reason `mode.list` documents: a
        level the UI cannot draw is a level nobody can pick, and the labels
        would drift from the allow-lists they describe.
        """
        from tonyagent.core.modes import PERMISSION_ORDER, PERMISSIONS

        return {
            "permissions": [_permission_payload(PERMISSIONS[n]) for n in PERMISSION_ORDER],
            "permission": self.session.permission_name,
        }

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

    def _h_skills_list(self, params: dict) -> Any:
        """The skills a message may open with ``/name``.

        Read fresh on every call and from the same store ``list_skills`` and
        ``run_skill`` use, for two reasons that are really one: the user adds
        and edits these files while the window is open, and a menu that offered
        a name the agent would refuse to load is a menu that lies. No caching
        anywhere, so there is nothing to invalidate.

        ``problems`` travels with the list rather than being logged. A file the
        user wrote that did not load is the one thing this listing must not be
        quiet about -- and the picker is where they are looking when they
        wonder why their skill is missing.
        """
        found = discover_current_skills()
        return {
            "skills": [skill.to_dict() for skill in found.skills],
            "problems": [problem.to_dict() for problem in found.problems],
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
