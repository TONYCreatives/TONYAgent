"""One owner for "what is running this tool call".

A tool is a stateless singleton, so anything a tool needs to know about *the
call that reached it* has to arrive from outside it. That used to be three
separate back-channels: a module global in ``subagent_tools`` holding the
session whose turn was running, a ``ContextVar`` in ``tools/base.py`` holding
the executing ``ToolCall``, and ``folder_manager`` holding the folder. Three
owners of one question -- "what is this call part of?" -- and the workflow
phase needs all of it: a re-entrant child turn has to know which session it is
continuing and which parent call spawned the turn it is running, or its frames
cannot be drawn under the right card.

This module is that answer, in one place, as the workflow loop's context:

* ``session`` -- the ``AgentSession`` whose turn is running. Published by the
  session for the life of a turn (``AgentSession._run_turn``).
* ``call_id`` -- the tool call being executed right now. Published by the
  orchestrator around each execution.
* ``permission`` -- the permission level the call runs under. Published by the
  orchestrator around each execution, from the level pushed into it by the
  session (``ToolOrchestrator.set_permission``). It replaced *two* module
  globals pushed into ``shell_tools`` (``_ALLOWLIST_BYPASS``,
  ``_HOST_EXECUTION``), which were the same setting written twice: a tool that
  needs to know whether a command may leave the allow-list or run on the host
  now reads one object, per call, and a concurrent child session cannot see the
  parent's level. See ``shell_tools.host_execution`` for what went wrong when
  two readers disagreed about one session.

**A ContextVar, not a global.** This is the property that made the old
``ToolCall`` ContextVar worth keeping: the independent calls in one assistant
message run as concurrent tasks, and each has to see *its own* call. A plain
attribute would show a batch's last call to every member of that batch. It also
makes a child's own turn safe -- a child running inside its parent's call gets
its own context, so its tool calls publish over its own session, not the
parent's.

``folder_manager`` deliberately stays where it is for now: moving the folder
into this context means rewiring ``file_tools``, ``search_tools`` and
``shell_tools`` at once, which is its own pass. What is here is what the loop
needs, and nothing speculative beside it.
"""

from __future__ import annotations

import contextlib
from contextvars import ContextVar
from dataclasses import dataclass, replace
from typing import Any, Iterator


@dataclass(frozen=True)
class ToolContext:
    """The session and call a tool is running inside.

    Frozen because it is *published*, not mutated: a nested publisher (the
    orchestrator inside a session's turn) derives a new context from the
    current one rather than editing it, so the outer turn's view is intact the
    moment the inner one unwinds.
    """

    #: The session whose turn is running, or ``None`` outside one. Typed
    #: loosely to keep this module importable from ``tools`` without reaching
    #: for ``core.session``, which imports this package.
    session: Any | None = None
    #: The id of the tool call being executed, or ``""`` when a tool is driven
    #: directly (a test, a script) rather than by the orchestrator.
    call_id: str = ""
    #: The permission level this call runs under, or ``None`` for unrestricted
    #: (the default: nothing is set in most tests, and ``None`` reads as "no
    #: host access, no allow-list bypass", which is the safe direction).
    permission: Any | None = None


#: The empty context: no turn, no call. What a direct tool call sees.
_EMPTY = ToolContext()

_current: ContextVar[ToolContext] = ContextVar("tonyagent_tool_context", default=_EMPTY)


def current() -> ToolContext:
    """The context this task is running in. Never ``None`` -- see ``_EMPTY``."""
    return _current.get()


@contextlib.contextmanager
def use_context(**changes: Any) -> Iterator[ToolContext]:
    """Publish a context for the duration of a block.

    Nested publishers compose in the only sensible order: each field keeps
    whatever the enclosing block set unless this one overrides it. That is what
    lets the session publish ``session`` for a whole turn and the orchestrator
    publish ``call_id`` for one call inside it, without either knowing about the
    other.

    Reset in a ``finally``, so a tool that raises -- or a turn that is
    cancelled -- cannot leave the next call in this task holding its
    predecessor's context.
    """
    context = replace(current(), **changes)
    token = _current.set(context)
    try:
        yield context
    finally:
        _current.reset(token)
