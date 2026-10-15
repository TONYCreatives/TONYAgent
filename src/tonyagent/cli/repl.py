"""The REPL: a prompt, some slash commands, and a turn per line of input.

The window is a chat transcript; this is a shell. That single difference
decides most of the design, so it is worth being explicit about it:

* **A line is one turn.** There is no multi-line composer and no paste
  handling. What a window lets you assemble over thirty seconds of typing, a
  terminal asks for at once -- and the escape hatch is `\\` followed by a line
  to keep composing, which is what a person already expects from a shell.
* **The prompt carries the state.** Mode, permission level and model are in
  the prompt string rather than hidden in a status bar, because that is where
  a shell puts the facts you are allowed to forget. It is the single most
  useful thing this frontend does that the window cannot: before you send a
  destructive tool call you can see, in the same line of sight as your
  command, that the agent is in Full.
* **Slash commands, not a settings dialog.** `/mode`, `/model`, `/permission`
  and the rest take an argument and return immediately.

**Cancellation is a key, not a menu.** Ctrl-C during a turn sends `cancel` and
returns to the prompt without ending the session; a second Ctrl-C exits. That
is the shell convention, and the two-stage shape matters: the first interrupt
is a statement about the turn and the second about the process.

**Blocking questions are read here, not by the renderer.** `ask_user_question`
and tool confirmations suspend the turn and arrive as events; the renderer
prints them and this module collects the reply. The 60-second timeout is the
core's, not a local one -- duplicating it would mean two answers to "how long
does this wait", and the reader has to be interruptible anyway, so the wait is
a poll rather than a blocking `input()`.
"""

from __future__ import annotations

import argparse
import sys
import threading
from collections.abc import Callable
from pathlib import Path, PurePath
from typing import Any, Optional

from tonyagent.cli.client import CoreClient, CoreError
from tonyagent.cli.render import Renderer, pad_to
from tonyagent.core.events import EventType

#: How long the input loop blocks on `_asked` before checking whether the turn
#: is still running.
#:
#: This is a liveness backstop, not the mechanism. The loop is normally woken
#: by `_asked` the instant a question opens; the timeout only exists so a dead
#: worker thread cannot leave the loop waiting forever with no way to notice.
#: It is deliberately not called a poll interval any more, because calling it
#: that is what made the original unconditional-read version look reasonable.
_IDLE_POLL_S = 0.25

#: A turn may legitimately run for many minutes. The timeout is generous on
#: purpose: a REPL that abandons a long build is worse than one that waits.
TURN_TIMEOUT_S = 3600.0


class Repl:
    def __init__(
        self,
        client: CoreClient,
        renderer: Renderer,
        *,
        initial_prompt: str = "",
    ) -> None:
        self.client = client
        self.ui = renderer
        self.initial_prompt = initial_prompt
        self.state: dict[str, Any] = {}
        self.running = True
        #: Set by `handle_event` when a dialog opens, cleared once answered.
        #: This is what the input loop waits on -- it is the only reason the
        #: terminal is read at all, which is what keeps the loop from eating
        #: the user's next command on a turn that asked nothing.
        self._asked = threading.Event()
        #: The confirmation currently awaiting an answer, so Ctrl-C during one
        #: answers "no" rather than leaving a suspended turn behind.
        self._pending_confirm: Optional[str] = None
        #: The id of an open `ask_user_question` / `present`, and the text of
        #: the turn in flight, both needed by the answer-routing loop.
        self._pending_ask: Optional[str] = None
        self._sending: str = ""

    # -- the prompt ----------------------------------------------------------

    def prompt_string(self) -> str:
        """The state, in the order a person reads it.

        Permission first and coloured by how much it permits: that is the
        value whose wrongness is expensive, and it is the one a user forgets
        they set.
        """
        if not self.state.get("bound"):
            who = self.ui.style.red("no provider")
        else:
            who = self.state.get("model") or "?"
        permission = str(self.state.get("permission", "?"))
        tone = {
            "full": self.ui.style.red,
            "high": self.ui.style.yellow,
        }.get(permission.lower(), self.ui.style.dim)
        parts = [
            self.ui.style.cyan("tony"),
            tone(permission),
            self.ui.style.dim(who),
            self.ui.style.dim(str(self.state.get("mode", "chat"))),
        ]
        project = str(self.state.get("project") or "")
        if project:
            parts.append(self.ui.style.dim(_basename(project)))
        return " ".join(p for p in parts if p) + " > "

    def refresh_state(self) -> None:
        try:
            self.state = self.client.call("state") or {}
        except CoreError:
            self.state = {}

    def handle_event(self, kind: str, payload: dict[str, Any]) -> None:
        """Render an event, and note the ones that suspend the turn.

        Called on the client's reader thread. The ids and `_asked` below are the
        only shared mutable state in the frontend; `_asked` is what wakes the
        input loop, and it is set *after* the id, so a question can never be
        answered before there is an id to answer against.
        """
        if kind == EventType.CONFIRMATION_REQUESTED.value:
            self._pending_confirm = str(payload.get("id", ""))
        elif kind == EventType.USER_ASKED.value:
            self._pending_ask = str(payload.get("id", ""))
        elif kind in (
            EventType.CONFIRMATION_RESOLVED.value,
            EventType.USER_RESOLVED.value,
            EventType.TURN_FINISHED.value,
            EventType.TURN_FAILED.value,
        ):
            # The dialog is closed, so an answer must not go to a stale id.
            self._pending_confirm = None
            self._pending_ask = None
            self._asked.clear()
        self.ui.handle(kind, payload)
        # Raised last, after the id is stored and the prompt has been drawn, so
        # the loop that wakes on this is guaranteed to have something to route
        # an answer to and something to show.
        if self._pending_confirm or self._pending_ask:
            self._asked.set()

    # -- the loop ------------------------------------------------------------

    def run(self) -> int:
        self._banner()
        self.refresh_state()
        _install_readline()

        if self.initial_prompt:
            # A prompt given on the command line is one turn, not a line at
            # the prompt: it should behave identically to typing it and then
            # waiting, without stealing the terminal first.
            self._turn(self.initial_prompt)
            return 0

        while self.running:
            try:
                raw = input(self.prompt_string())
            except EOFError:
                # Ctrl-D. Not an error: it is how a person says "done", and it
                # is the normal way a piped session ends.
                self.ui.blank()
                return 0
            except KeyboardInterrupt:
                # Ctrl-C at an empty prompt: leave, rather than print ^C and
                # offer another prompt as though nothing happened.
                self.ui.blank()
                return 130
            self._dispatch_line(raw)
        return 0

    def _dispatch_line(self, raw: str) -> None:
        line = raw.strip()
        if not line:
            return
        if line.startswith("\\"):
            # The composer escape from the module docstring.
            self._turn(line[1:].strip())
            return
        if line.startswith("/"):
            self._slash(line)
            return
        self._turn(line)

    # -- blocking on the user during a turn ----------------------------------

    def _read_until_asked(self) -> None:
        """Answer whatever the core blocks on, until the turn's reply arrives.

        This is the reason the client's `send` runs on a worker rather than
        inline: a turn can be suspended mid-flight by `ask_user_question` or by
        a destructive tool's confirmation, and both are answered by a keypress
        here. Reading stdin on the main thread while `send` waits on that same
        thread is a deadlock with a UI on top, so the wait happens on a worker
        and this loop owns the terminal.

        **The loop waits on an event, not on the terminal.** The first version
        polled `input()` every 200ms whether or not anything was being asked,
        which meant a turn that asked nothing still sat reading the user's
        next command and fed it to the core as an answer to nothing --
        `_pending_confirm` and `_pending_ask` were both empty, so it fired a
        `user.respond` with an empty id, once per poll, until the turn ended.
        It looked like it worked because most turns finish fast; it was
        stealing input the whole time.

        So `handle_event` sets `_asked` when a dialog opens and this loop only
        calls `input()` once that is set, clearing it as it goes. The terminal
        is read exactly when there is something to read it for.
        """
        worker = threading.Thread(target=self._send_in_background, daemon=True)
        worker.start()
        try:
            while worker.is_alive():
                # `wait` rather than `sleep`: the loop is asleep until the
                # reader thread says a dialog opened, so a question is answered
                # the moment it is asked and not up to a poll interval later.
                if not self._asked.wait(timeout=_IDLE_POLL_S):
                    continue
                if self._pending_confirm or self._pending_ask:
                    self._ask_once()
        finally:
            self._asked.clear()
            worker.join(timeout=5)

    def _send_in_background(self) -> None:
        try:
            self.client.call("send", {"text": self._sending}, timeout=TURN_TIMEOUT_S)
        except CoreError as exc:
            self.ui.error(str(exc))
        except Exception as exc:  # noqa: BLE001 - reported, never raised at nobody
            self.ui.error(f"send failed: {exc}")

    def _ask_once(self) -> None:
        """Read one answer and route it to whichever dialog is *still* open.

        Consumes the `_asked` signal before reading, so a dialog that closes
        while the user is mid-keystroke does not leave it set for a turn that
        is no longer asking anything.

        **The id is captured after the read, not before.** A confirmation that
        opens and resolves within the same few milliseconds -- the core closing
        its own prompts at the end of a turn does exactly this -- would
        otherwise be answered against an id that no longer exists, and the
        reply would go into the void looking like a dropped connection. So the
        answer is held until the loop knows which dialog is still open, and is
        dropped if none is.
        """
        self._asked.clear()
        if not (self._pending_confirm or self._pending_ask):
            return
        try:
            answer = input(self.ui.style.yellow("  > "))
        except EOFError:
            # ^D with a turn in flight. Answering "no" to whatever is pending
            # is the only safe reading: the core carries on with "nobody
            # answered", which it is built for.
            answer = "n"
        except KeyboardInterrupt:
            self._cancel()
            answer = "n"
        answer = answer.strip()
        # Re-checked here, after the blocking read: a turn can end, and every
        # outstanding prompt be closed by the core, while a key is down.
        if not (self._pending_confirm or self._pending_ask):
            self.ui.line(self.ui.style.dim("(no longer waiting for an answer)"))
            return
        if answer:
            self._route_answer(answer)

    def _route_answer(self, answer: str) -> None:
        """Send a typed line to whichever dialog is open.

        A confirmation takes yes/no/always; a question takes whatever the user
        typed. Guessing wrong here would send an answer to a dialog that is not
        asking for one, so the pending id decides which.

        **"always" is this session's permission level, and nothing more.**
        `confirm.respond` takes a bool and nothing else -- there is no
        per-tool allowlist in the protocol -- so the honest way to stop being
        asked is to raise the level for the conversation, which is what `/permission`
        does. Saying so out loud matters: a user who believes "always" has
        permanently trusted one tool, and has instead trusted *everything* for
        this session, would be badly surprised at a later destructive call.
        So it confirms this turn and then tells the truth about what it did.
        """
        call_id = self._pending_confirm
        if call_id is not None:
            self._pending_confirm = None
            lowered = answer.lower()
            if lowered in {"a", "always"} and not self._allow_always():
                return
            confirmed = lowered in {"y", "yes", "a", "always", "1", "true"}
            try:
                self.client.notify(
                    "confirm.respond", {"id": call_id, "confirmed": confirmed}
                )
            except CoreError as exc:
                self.ui.error(str(exc))
            return
        try:
            self.client.notify("user.respond", {"id": self._pending_ask or "", "answer": answer})
        except CoreError as exc:
            self.ui.error(str(exc))
        self._pending_ask = None

    def _allow_always(self) -> bool:
        """Raise this session's permission level, and say what that means.

        Two steps rather than one, and the second is the point. OpenCode's
        permission dialog has the same three-stage shape (`permission` ->
        `always` -> confirm) and the same reason for it: granting permanent
        access is the option whose consequences the user is least likely to
        have in mind when they are reading a tool's arguments.
        """
        listing = self.client.call("permission.list") or {}
        levels = listing.get("permissions") or []
        current = str(listing.get("permission") or "")
        order = [str(level.get("name")) for level in levels if isinstance(level, dict)]
        index = order.index(current) if current in order else -1
        if index < 0 or index + 1 >= len(order):
            self.ui.warn(f"Already at the highest level ({current}); confirming this once.")
            return True
        target = order[index + 1]

        self.ui.blank()
        self.ui.line(
            self.ui.style.yellow(
                f"'always' raises this session to {target} -- every tool allowed, "
                "not just this one."
            )
        )
        levels_desc = next(
            (str(level.get("description", "")) for level in levels
             if isinstance(level, dict) and level.get("name") == target),
            "",
        )
        if levels_desc:
            self.ui.line(f"  {self.ui.style.dim(levels_desc)}")
        try:
            answer = input(self.ui.style.yellow(f"  Switch to {target}? [y/N] ")).strip()
        except (EOFError, KeyboardInterrupt):
            return False
        if answer.lower() not in {"y", "yes"}:
            self.ui.line(self.ui.style.dim("cancelled; confirming this once only"))
            return False
        try:
            self.client.call("permission.set", {"permission": target})
        except CoreError as exc:
            self.ui.error(str(exc))
            return False
        self.refresh_state()
        return True

    # -- one turn ------------------------------------------------------------

    def _turn(self, text: str) -> None:
        if not text:
            return
        self._sending = text
        try:
            # The event callback sets `_pending_confirm` / `_pending_ask` as the
            # core blocks, and `_read_until_asked` collects the replies. The
            # `send` itself runs on a worker because it only returns when the
            # turn is over, and the turn cannot be over until someone answers.
            self._read_until_asked()
        except KeyboardInterrupt:
            self._cancel()
        finally:
            self._sending = ""
            self._pending_confirm = None
            self._pending_ask = None
            self.refresh_state()

    def _cancel(self) -> None:
        try:
            self.client.notify("cancel", {})
        except CoreError as exc:
            self.ui.error(f"Could not cancel: {exc}")
            return
        self.ui.line(self.ui.style.yellow("cancelled"))

    # -- slash commands ------------------------------------------------------

    def _slash(self, line: str) -> None:
        parts = line[1:].split(None, 1)
        if not parts:
            return
        command, argument = parts[0], (parts[1].strip() if len(parts) > 1 else "")
        handler: Optional[Callable[[str], None]] = {
            "help": self._cmd_help,
            "quit": self._cmd_quit,
            "exit": self._cmd_quit,
            "state": self._cmd_state,
            "mode": self._cmd_mode,
            "model": self._cmd_model,
            "key": self._cmd_key,
            "permission": self._cmd_permission,
            "plan": self._cmd_plan,
            "tools": self._cmd_tools,
            "new": self._cmd_new,
            "conversations": self._cmd_conversations,
            "usage": self._cmd_usage,
            "reasoning": self._cmd_reasoning,
            "sandbox": self._cmd_sandbox,
        }.get(command)
        if handler is None:
            self.ui.error(f"Unknown command /{command}. Try /help.")
            return
        try:
            handler(argument)
        except CoreError as exc:
            self.ui.error(str(exc))

    def _cmd_help(self, argument: str) -> None:
        rows = [
            ("/help", "this list"),
            ("/quit", "leave (Ctrl-D also works)"),
            ("/state", "what the core reports about itself"),
            ("/mode <name>", "switch mode: chat, build, plan, mission, skills"),
            ("/model <id>", "switch model"),
            ("/permission <name>", "switch permission level"),
            ("/plan", "show the task list"),
            ("/tools", "list the registered tools"),
            ("/new [title]", "start a conversation"),
            ("/conversations", "list saved conversations"),
            ("/key [provider key]", "list keys, or save one (goes to the OS keyring)"),
            ("/tools [n]", "show or set the per-turn tool call budget"),
            ("/usage", "what this app has spent"),
            ("/reasoning <effort>", "set the thinking level"),
            ("/sandbox", "show sandbox status"),
            ("\\text", "send a turn without a leading slash"),
        ]
        self.ui.blank()
        self.ui.line(self.ui.style.bold("Commands"))
        # Measured rather than a fixed 22: the column has to fit the longest
        # name, and padding on character count is what put the descriptions out
        # of line under a CJK locale.
        width = max(len(name) for name, _ in rows)
        for name, description in rows:
            self.ui.line(
                f"  {pad_to(self.ui.style.cyan(name), width)}  {self.ui.style.dim(description)}"
            )
        self.ui.blank()
        self.ui.line(
            self.ui.style.dim("Ctrl-C cancels a turn; Ctrl-C again leaves. Ctrl-D leaves.")
        )

    def _cmd_quit(self, argument: str) -> None:
        self.running = False

    def _cmd_key(self, argument: str) -> None:
        """Save or bind a provider key.

        The key itself is never read back, stored, or echoed: it goes from this
        line to the OS keyring through the core and nowhere else. That is why
        there is no `/key` argument completion and why the help says so --
        a REPL that kept the secret in a shell history file to be friendly
        would be the one place in the project that wrote it down.
        """
        parts = argument.split(None, 1)
        if not parts:
            listing = self.client.call("key.list") or {}
            keys = listing.get("keys") or []
            self.ui.blank()
            for entry in keys:
                if isinstance(entry, dict):
                    name = entry.get("provider") or entry.get("name") or "?"
                    active = entry.get("active")
                    mark = self.ui.style.green("*") if active else " "
                    self.ui.line(f"  {mark} {name}")
                else:
                    self.ui.line(f"    {entry}")
            self.ui.blank()
            self.ui.line(self.ui.style.dim("/key <provider> <secret> to add one"))
            self.ui.blank()
            return

        provider = parts[0]
        if len(parts) < 2:
            self.ui.error("usage: /key <provider> <secret>")
            return
        secret = parts[1].strip()
        try:
            self.client.call("key.save", {"provider": provider, "api_key": secret})
            self.client.call("key.activate", {"provider": provider})
        except CoreError as exc:
            self.ui.error(str(exc))
            return
        self.ui.line(self.ui.style.green(f"saved a key for {provider}"))
        self.refresh_state()

    def _cmd_state(self, argument: str) -> None:
        self.refresh_state()
        self.ui.blank()
        for key, value in self.state.items():
            shown = f"<{type(value).__name__}>" if isinstance(value, (dict, list)) else value
            self.ui.line(f"  {self.ui.style.dim(key + ':'):<26} {shown}")
        self.ui.blank()

    def _pick(
        self,
        what: str,
        list_method: str,
        argument: str,
        set_method: str,
        *,
        list_key: str,
        current_key: str,
        set_param: str,
    ) -> None:
        """Shared shape of the pick-a-value commands: `/x` lists, `/x value` sets.

        The four spellings are parameters rather than hardcoded, because the
        server genuinely does differ on each one -- `mode.set` takes `mode`,
        `permission.set` takes `permission`, `reasoning.set` takes `effort`,
        and the lists come back under `modes`, `permissions` and `efforts`
        rather than a common key. Forcing one shape here would have meant
        lying to the server, and the mismatch would surface as a rejected
        request with a message aimed at the window.
        """
        payload = self.client.call(list_method) or {}
        options = payload.get(list_key) or []
        if not isinstance(options, list):
            options = []
        current = str(payload.get(current_key) or "")

        if not argument:
            self.ui.blank()
            if not options:
                self.ui.line(self.ui.style.dim(f"nothing available ({what})"))
            for option in options:
                if isinstance(option, dict):
                    name = str(option.get("name") or option.get("effort") or "?")
                    detail = option.get("description") or option.get("label") or ""
                    if isinstance(option, dict) and option.get("label"):
                        detail = option["description"] or option["label"]
                else:
                    name, detail = str(option), ""
                mark = self.ui.style.green("*") if name == current else " "
                text = f"  {mark} {name}"
                if detail and detail != name:
                    text += self.ui.style.dim(f"  {detail}")
                self.ui.line(text)
            self.ui.blank()
            return

        # The reply is the level actually in force, not the one requested: an
        # unrecognised name resolves to the default, so echoing the argument
        # would label a mode or a level the core is not enforcing.
        result = self.client.call(set_method, {set_param: argument}) or {}
        applied = result.get("name") or result.get("mode") or result.get("effort") or argument
        if applied != argument:
            self.ui.warn(f"{what} {argument!r} is not recognised; using {applied!r}")
        else:
            self.ui.line(self.ui.style.dim(f"{what}: {applied}"))
        self.refresh_state()

    def _cmd_mode(self, argument: str) -> None:
        self._pick(
            "mode", "mode.list", argument, "mode.set",
            list_key="modes", current_key="mode", set_param="mode",
        )

    def _cmd_permission(self, argument: str) -> None:
        self._pick(
            "permission", "permission.list", argument, "permission.set",
            list_key="permissions", current_key="permission", set_param="permission",
        )

    def _cmd_reasoning(self, argument: str) -> None:
        self._pick(
            "reasoning", "reasoning.list", argument, "reasoning.set",
            list_key="efforts", current_key="effort", set_param="effort",
        )

    def _cmd_model(self, argument: str) -> None:
        """Switch model.

        There is no `model.set`, and that is not an oversight to route around:
        changing the model means re-binding the provider with a different one,
        because the provider is what holds the keyring entry and the endpoint.
        So the current provider's name is reused -- switching model must not
        silently rebind a *different* provider -- and only the model changes.

        The `models.list` reply is read from the same provider, so the ids
        offered are the ones that provider actually serves.
        """
        self.refresh_state()
        if not self.state.get("bound"):
            self.ui.error("No provider is bound; add a key first.")
            return
        provider = str(self.state.get("provider") or "")
        if not argument:
            listing = self.client.call("models.list") or {}
            models = listing.get("models") or []
            current = str(listing.get("current") or "")
            self.ui.blank()
            for entry in models:
                ident = entry.get("id") if isinstance(entry, dict) else str(entry)
                mark = self.ui.style.green("*") if ident == current else " "
                self.ui.line(f"  {mark} {ident}")
            self.ui.blank()
            self.ui.line(self.ui.style.dim(f"provider: {provider}"))
            self.ui.line(self.ui.style.dim("/model <id> to switch"))
            return
        result = self.client.call(
            "bind_provider", {"name": provider, "model": argument}
        ) or {}
        if not result.get("persisted", True):
            self.ui.warn("Switched, but the choice could not be saved for next time.")
        self.refresh_state()
        self.ui.line(self.ui.style.dim(f"model: {result.get('model', argument)}"))

    def _cmd_tools(self, argument: str) -> None:
        """The per-turn tool call budget.

        Not a list of tools: `tools.get` answers with what the budget *is*,
        because it is read from the session rather than from the settings file
        -- a number shown from settings would be a number the next turn is not
        held to. The registered tool names are not exposed over this protocol
        at all, and inventing them client-side would mean a second registry
        that could drift from the first.
        """
        payload = self.client.call("tools.get") or {}
        budget = payload.get("max_tool_calls")
        self.ui.line(self.ui.style.dim(f"tool budget: {payload.get('label', budget)}"))
        if argument:
            wanted = _as_int(argument)
            if wanted is None:
                self.ui.error("usage: /tools <whole number>")
                return
            result = self.client.call("tools.set", {"max_tool_calls": wanted}) or {}
            if not result.get("persisted", True):
                self.ui.warn("Changed for this session, but could not be saved.")
            self.ui.line(self.ui.style.dim(f"tool budget: {result.get('max_tool_calls')!r}"))
            self.refresh_state()

    def _cmd_plan(self, argument: str) -> None:
        """The plan, as the model itself is shown it.

        `rendered` rather than the structured items, so what is printed here is
        byte-for-byte what went into the system prompt -- two renderings of one
        state that could disagree is exactly the failure the core's own
        comment on this method warns about.
        """
        payload = self.client.call("plan.get") or {}
        rendered = str(payload.get("rendered") or "").strip()
        summary = str(payload.get("summary") or "").strip()
        if not rendered and not summary:
            self.ui.line(self.ui.style.dim("no plan"))
            return
        self.ui.blank()
        if rendered:
            for line in rendered.splitlines():
                self.ui.line(f"  {line}")
        elif summary:
            self.ui.line(f"  {summary}")
        self.ui.blank()

    def _cmd_new(self, argument: str) -> None:
        params: dict[str, Any] = {}
        if argument:
            params["title"] = argument
        self.client.call("conversations.create", params)
        self.refresh_state()
        self.ui.line(self.ui.style.dim("new conversation"))

    def _cmd_conversations(self, argument: str) -> None:
        payload = self.client.call("conversations.list") or {}
        items = payload.get("conversations") or payload.get("items") or []
        current = str(self.state.get("conversation", ""))
        self.ui.blank()
        for item in items:
            if not isinstance(item, dict):
                continue
            ident = str(item.get("id", ""))
            mark = self.ui.style.green("*") if ident == current else " "
            title = item.get("title") or "(untitled)"
            self.ui.line(f"  {mark} {title}  {self.ui.style.dim(ident[:8])}")
        self.ui.blank()

    def _cmd_usage(self, argument: str) -> None:
        payload = self.client.call("usage.summary") or {}
        self.ui.blank()
        for key, value in payload.items():
            if isinstance(value, (dict, list)):
                continue
            self.ui.line(f"  {self.ui.style.dim(key + ':'):<26} {value}")
        self.ui.blank()

    def _cmd_sandbox(self, argument: str) -> None:
        payload = self.client.call("sandbox.stats") or {}
        status = self.client.call("state") or {}
        running = (status.get("sandbox") or {}).get("status", "stopped")
        self.ui.line(self.ui.style.dim(f"sandbox: {running}"))
        for key, value in payload.items():
            if isinstance(value, (dict, list)):
                continue
            self.ui.line(f"  {self.ui.style.dim(key + ':'):<26} {value}")

    # -- startup and teardown ------------------------------------------------

    def _banner(self) -> None:
        version = self._version()
        self.ui.line(self.ui.style.cyan(f"TONYAgent {version}"))
        self.ui.line(self.ui.style.dim("terminal frontend"))
        if not self.state.get("bound"):
            self.ui.line(
                self.ui.style.yellow("No provider is bound.")
                + self.ui.style.dim(" Add a key with /key <provider> <secret>, then /model <id>.")
            )
        self.ui.line(self.ui.style.dim("/help for commands"))

    def _version(self) -> str:
        try:
            from tonyagent import __version__

            return __version__
        except Exception:  # noqa: BLE001 - a version string is not worth a crash
            return "0.0.0"


def _basename(path: str) -> str:
    """The last component of a project path, for the prompt.

    `Path.name` rather than `os.path.basename` because it returns `""` for a
    root path instead of `""`-or-the-whole-string depending on the platform,
    and the fallback below is what keeps `/` from rendering as an empty field.
    """
    return PurePath(path.rstrip("/\\")).name or path


def _as_int(text: str) -> Optional[int]:
    """Parse a whole number, or None so the caller can report it.

    Returning None rather than raising keeps "you typed a word" on the same
    path as "the server refused it", which is what `_cmd_tools` wants: both
    are the user's input being wrong, and both should read as one message.
    """
    try:
        return int(text.strip())
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------


def _install_readline() -> bool:
    """Turn on line editing and history, if this Python has them.

    Without it the prompt is raw `input()`: no arrow keys, no Ctrl-R, no
    history across sessions. On a REPL where a turn is typed in full every
    time, losing the up-arrow is the difference between fixing a typo and
    retyping a paragraph -- and `/mode chat` is exactly the kind of command
    someone types ten times a session.

    Windows is the exception. `pyreadline3` provides this there, but it is not
    a declared dependency, and importing it conditionally would make the
    feature depend on whether an unrelated package happened to be installed --
    a REPL that edits differently depending on the machine is worse than one
    that plainly does not.
    """
    if sys.platform == "win32":
        return False
    try:
        import readline  # noqa: F401  (imported for its side effect)
    except ImportError:
        # A Python built without readline. Legal, and not worth failing over.
        return False
    return True


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tony",
        description="TONYAgent in the terminal: a REPL over the headless core.",
    )
    parser.add_argument(
        "prompt",
        nargs="*",
        help="run one turn with this text and exit; omit for an interactive session",
    )
    parser.add_argument(
        "-C",
        "--cwd",
        help="the project folder to work in (default: the current directory)",
    )
    parser.add_argument(
        "--hide-reasoning",
        action="store_true",
        help="do not print the model's thinking",
    )
    parser.add_argument(
        "--raw",
        action="store_true",
        help="dump the JSONL protocol to stdout instead of rendering it",
    )
    parser.add_argument(
        "--plain",
        action="store_true",
        help="the line-mode REPL even on a terminal (no full-screen interface)",
    )
    parser.add_argument(
        "--tui",
        action="store_true",
        help="force the full-screen interface; this is the default on a terminal",
    )
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    prompt = " ".join(args.prompt).strip()

    client = CoreClient(on_event=_raw_printer() if args.raw else None)
    try:
        client.start()
    except OSError as exc:
        print(f"Could not start the core: {exc}", file=sys.stderr)
        return 1

    try:
        if args.raw:
            return _raw_session(client, prompt)

        # Which frontend, decided here rather than in either one.
        #
        # The full-screen interface is the default when stdout is a terminal,
        # because that is the case a person is actually in. It is not the
        # default when it is a pipe: alt-screen and a cursor-addressed layout
        # produce nothing usable in a file, and the line REPL is what makes
        # `tony "..." > out.txt` work at all. `--plain` and `--tui` override,
        # because "I redirected this and still got escape codes" should have an
        # answer that is a flag rather than a bug report.
        interactive = sys.stdout.isatty() and not args.raw
        use_tui = interactive and not args.plain
        if args.tui:
            use_tui = True

        if args.cwd:
            # Reported rather than assumed: the core picks the project up from
            # the trust/sandbox path, and -C says which one the user meant.
            try:
                client.call(
                    "trust.set",
                    {"project": str(Path(args.cwd).resolve()), "trusted": True},
                )
            except CoreError as exc:
                print(f"Could not set the project folder: {exc}", file=sys.stderr)

        if use_tui:
            from tonyagent.cli.tui import TonyApp

            return TonyApp(client, initial_prompt=prompt).run()

        ui = Renderer(show_reasoning=not args.hide_reasoning)
        repl = Repl(client, ui, initial_prompt=prompt)
        client.on_event = repl.handle_event
        return repl.run()
    finally:
        client.close()


def _raw_printer() -> Callable[[str, dict[str, Any]], None]:
    """Print every event as it arrives, for reading the wire format."""

    def printer(kind: str, payload: dict[str, Any]) -> None:
        import json as _json

        print(_json.dumps({"event": kind, "payload": payload}, default=str), flush=True)

    return printer


def _raw_session(client: CoreClient, prompt: str) -> int:
    """`--raw`: the protocol with no rendering, for scripts and for debugging.

    Events go to stdout as they arrive. Requests are read from stdin, one JSON
    object per line, so the whole protocol is drivable from a shell without
    this client having to model it -- which is the point of the flag.
    """
    import json as _json

    if prompt:
        client.call("send", {"text": prompt}, timeout=TURN_TIMEOUT_S)
        return 0

    try:
        for raw_line in sys.stdin:
            line = raw_line.strip()
            if not line:
                continue
            try:
                frame = _json.loads(line)
            except ValueError:
                print(
                    _json.dumps({"error": "not JSON", "line": line}),
                    flush=True,
                )
                continue
            method = str(frame.get("method", ""))
            if not method:
                continue
            try:
                result = client.call(method, frame.get("params") or {}, timeout=300)
            except CoreError as exc:
                print(
                    _json.dumps({"error": str(exc), "method": method, "code": exc.code}),
                    flush=True,
                )
            else:
                print(
                    _json.dumps({"result": result, "method": method}, default=str),
                    flush=True,
                )
    except (KeyboardInterrupt, EOFError):
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
