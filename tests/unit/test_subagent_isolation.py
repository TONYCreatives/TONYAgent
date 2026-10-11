"""Groundwork for Phase 5 (subagents): the globals a child session breaks.

``AgentSession.__init__`` ends with ``set_current_state(self.state)``, which
repoints the process-global ``task_state._current``. That is correct for the one
session-per-process world the core was built in -- but a subagent *is* an
``AgentSession`` (NEXT_SESSION § "Phase 5"), and a child constructed naively
would silently take over the parent's plan: the parent's next turn would render
the child's todo list into its system prompt, and every planning tool would
write to the child's state.

That is the sharpest of the three process-globals the phase must make explicit
(``task_state``, ``user_io``, ``jobs_registry``), and the fix is already
modelled: the question bridge is an *explicit* method the host calls rather
than a side effect of building the session. So the contract pinned here is:

  * constructing a session does **not** change the current state;
  * adopting a plan for the session in front of the user *does* -- through the
    explicit ``set_state``, which is what ``server.py`` calls -- so nothing
    changes for the one-session world until Phase 5 gives a child its own
    publication path.

These tests fail at the time of writing: ``__init__`` still repoints the
global. They are the failing test NEXT_SESSION asked for *before* any
subagent tool is written.
"""

from __future__ import annotations

import pytest

import tonyagent.tools  # noqa: F401  -- importing registers every tool
from tonyagent.core.session import AgentSession
from tonyagent.core.task_state import SessionState, current_state


def _fresh_session() -> AgentSession:
    """A no-provider session, the way a test builds one."""
    session = AgentSession(provider_name="openrouter", model="openrouter/auto")
    session.provider = None
    return session


@pytest.fixture(autouse=True)
def _keep_task_state_clean():
    """Restore whatever state was current, whatever the test did."""
    before = current_state()
    yield
    current_state()  # touch nothing; use set_current_state to restore
    from tonyagent.core.task_state import set_current_state

    set_current_state(before)


def test_construction_does_not_repoint_the_global_state():
    """Building a child session must not take over the parent's plan.

    This is the test NEXT_SESSION asked for: a child session constructed
    naively repoints ``task_state._current``, so the parent's next turn would
    carry the child's task list and every ``todo_write`` in the parent would
    land in the child's state.
    """
    parent_state = SessionState()
    from tonyagent.core.task_state import set_current_state

    set_current_state(parent_state)

    child = _fresh_session()

    assert current_state() is parent_state, (
        "constructing a session repointed the process-global task_state; "
        "a subagent would silently steal the parent's plan"
    )
    # And the two objects stay distinct, so nothing was shared by accident.
    assert child.state is not parent_state


def test_set_state_is_still_the_explicit_adopt_path():
    """Adopting a plan in front of the user goes through ``set_state``.

    The one-session world must keep working: the host calls ``set_state`` to
    publish the state the tools write to, and that call -- not construction --
    is what may change the global.
    """
    parent_state = SessionState()
    from tonyagent.core.task_state import set_current_state

    set_current_state(parent_state)

    session = _fresh_session()
    own_state = SessionState()
    session.set_state(own_state)

    assert session.state is own_state
    assert current_state() is own_state
