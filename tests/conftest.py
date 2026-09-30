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