"""`diagnostics.get`: the facts a bug report needs, as the core knows them.

The card on the App tab draws the build, where it runs from and where its
files live. All six answers come from the core rather than from constants in
the window, for one reason: the config path depends on the platform and on
which APPDATA this process sees, and a path the window guessed at is how a
user ends up looking for logs in a folder that was never written to.

Two properties are pinned here:

* **The version and author are the package's own.** The version lives in
  exactly one place (`tonyagent.__version__`), and the card must say that
  number rather than one copied into a second spot that goes stale.
* **The read creates nothing.** The log directory is the config path's parent
  plus `logs` -- the same directory `settings.get_logs_dir()` answers -- but
  answered without the `mkdir`, because a read with a side effect is a read
  that changes what it reports.
"""

from __future__ import annotations

import asyncio
import io
import json
import platform
import sys

import pytest

import tonyagent
from tonyagent.config import migration
from tonyagent.core.events import EventBus
from tonyagent.core.session import AgentSession
from tonyagent.headless.server import StdioServer

# Spelled out so the literal newline never has to survive an escape layer.
NEWLINE = chr(10)


@pytest.fixture
def isolated_config(tmp_path, monkeypatch):
    """Redirect the config path itself, so the real one is never touched."""
    path = tmp_path / "TONYAgent" / "config.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(migration, "get_config_path", lambda: path)
    return path


def _call(method: str, params: dict | None = None) -> dict:
    """Send one request over the real server and return its reply frame."""
    session = AgentSession(bus=EventBus())
    request = {"id": 1, "method": method, "params": params or {}}
    stdin = io.StringIO(json.dumps(request) + NEWLINE)
    stdout = io.StringIO()
    asyncio.run(StdioServer(session, stdin, stdout).serve())
    frames = [json.loads(line) for line in stdout.getvalue().splitlines() if line.strip()]
    return next(frame for frame in frames if frame.get("id") == 1)


def test_the_facts_come_from_the_package_itself(isolated_config):
    info = _call("diagnostics.get")["result"]

    assert info["version"] == tonyagent.__version__
    assert info["author"] == tonyagent.__author__
    assert info["python"] == platform.python_version()
    assert info["frozen"] is False, "a test run is not the frozen bundle"


def test_frozen_is_a_boolean_not_a_string(isolated_config, monkeypatch):
    """The card branches on it, and `"False"` is truthy."""
    monkeypatch.setattr(sys, "frozen", True, raising=False)

    assert _call("diagnostics.get")["result"]["frozen"] is True


def test_the_paths_are_the_file_and_its_sibling(isolated_config):
    info = _call("diagnostics.get")["result"]

    assert info["config_path"] == str(isolated_config)
    assert info["log_dir"] == str(isolated_config.parent / "logs")


def test_the_read_creates_nothing(isolated_config):
    _call("diagnostics.get")

    assert not isolated_config.exists(), "the read wrote the config file"
    assert not (isolated_config.parent / "logs").exists(), "the read made the log folder"
