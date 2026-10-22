"""Test-session-wide guards.

The config file is the user's own, at ``%APPDATA%/TONYAgent/config.toml``, and
``bind_provider`` writes to it. That made a test which drives the real handler
an accidental writer: driving ``bind_provider`` with a base_url of
``https://gateway.internal/v1`` overwrote the user's saved model with a
provider default and pointed their next launch at a host that does not exist --
silently, because a passing test suite is the opposite of a warning.

Redirecting the path once, for the whole session, makes that impossible rather
than relying on each file remembering to patch it. Tests that want to inspect
the file patch it again themselves; this is the floor, not the mechanism.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True, scope="session")
def _isolate_config_path(tmp_path_factory):
    """Point every config read and write at a throwaway directory."""
    from tonyagent.config import migration

    directory = tmp_path_factory.mktemp("tonyagent-config")
    path = directory / "config.toml"
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(migration, "get_config_path", lambda: path)
        yield path


@pytest.fixture(autouse=True)
def _drop_the_user_hooks():
    """Unlisten for questions between tests.

    ``AgentSession`` publishes its question and presentation callbacks into
    ``core.user_io`` when it is built, and that module is process-global on
    purpose: one window, one session, one place for a question to arrive. The cost
    is that *constructing a session* is a side effect which outlives the test that
    did it. Once any earlier test has built one, every later ask finds a listener,
    waits out the whole ``ASK_TIMEOUT_S``, and the two tools that ask the user cost
    a minute each.

    **That is not a slow test, it is an order-dependent one**, and the difference
    matters for anyone reading a timing number. Measured:

        test_tool_orchestrator_path.py alone ..................   1.9s
        the same file after one that builds a session ......... 122.2s

    In the full suite the ordering puts session-building files first, so three
    tests stall for 60s each (240s of a 281s run), and a runner with an outer
    timeout kills the process at roughly the two-minute mark -- which is what
    "dies without a traceback at about 64%" was, and why running the suite in
    halves appeared to fix it.

    The same guard as ``_isolate_config_path`` above, for the same reason: a test
    that drives the real handler is an accidental *writer* there and an accidental
    *listener* here.
    """
    from tonyagent.core import user_io

    user_io.reset()
    yield
    user_io.reset()


@pytest.fixture(autouse=True)
def _restore_the_global_orchestrator():
    """Put the process-global tool orchestrator's mode and permission back.

    ``AgentSession.set_mode`` and ``set_permission`` push the restriction down
    to a module-level orchestrator, because that is the layer which actually
    runs the tools. So a test that switches modes changes the world for every
    test after it: a file that leaves the orchestrator in Chat mode makes the
    next file's mutating tools unpermitted, and its failures read like a
    problem with the code under test rather than with the test that ran
    before it.

    The same guard as the two above, for the same reason -- a side effect that
    outlives the test that caused it is the thing worth containing.
    """
    from tonyagent.tools.orchestrator import tool_orchestrator

    mode = tool_orchestrator._mode
    permission = tool_orchestrator._permission
    yield
    tool_orchestrator.set_mode(mode)
    tool_orchestrator.set_permission(permission)
