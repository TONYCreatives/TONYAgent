"""bind_provider must persist, through the real RPC handler.

The unit test beside this covers the file write; this one covers the call the
app actually makes. They can disagree -- the handler is where the reply is
built, and a reply that omits the outcome is how a failed save would have
stayed invisible.
"""

from __future__ import annotations

import io
import json

import pytest
import tomli

from tonyagent.config import migration
from tonyagent.core.events import EventBus
from tonyagent.core.session import AgentSession
from tonyagent.headless.server import StdioServer

# Spelled out so the literal newline never has to survive an escape layer.
NEWLINE = chr(10)


@pytest.fixture
def isolated_config(tmp_path, monkeypatch):
    """Redirect the config path itself, not just the environment.

    Setting APPDATA is not enough to rely on: the keyring and provider factory
    both read the real user profile during the same test, and a test that wrote
    to the user's actual config.toml would be a very unpleasant surprise. The
    path is patched where it is computed, so nothing downstream can escape it.
    """
    path = tmp_path / "TONYAgent" / "config.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(migration, "get_config_path", lambda: path)
    return path


def _bind(name, model, base_url="") -> dict:
    """Send one bind_provider over the wire and return the reply."""
    import asyncio

    session = AgentSession(bus=EventBus())
    request = {
        "id": 1,
        "method": "bind_provider",
        "params": {"name": name, "model": model, "base_url": base_url},
    }
    stdin = io.StringIO(json.dumps(request) + NEWLINE)
    stdout = io.StringIO()
    asyncio.run(StdioServer(session, stdin, stdout).serve())
    frames = [json.loads(l) for l in stdout.getvalue().splitlines() if l.strip()]
    return next(f for f in frames if f.get("id") == 1)


def test_bind_provider_persists_the_typed_model(isolated_config):
    reply = _bind("openrouter", "stealth/space-bunny-alpha")
    assert "result" in reply, reply
    with open(isolated_config, "rb") as handle:
        saved = tomli.load(handle)["provider"]
    assert saved["name"] == "openrouter"
    assert saved["model"] == "stealth/space-bunny-alpha"


def test_bind_provider_reports_that_it_persisted(isolated_config):
    """Silence here is what made the original bug survive so long.

    The bind works either way, so a save that quietly failed would leave the
    user with a configured app that forgets on restart and no way to know.
    """
    reply = _bind("openrouter", "stealth/space-bunny-alpha")
    assert reply["result"].get("persisted") is True


def test_a_failed_save_is_reported_but_does_not_fail_the_bind(monkeypatch):
    def boom(*args, **kwargs):
        raise OSError("disk is full")

    # The handler does `from tonyagent.config import save_provider_selection`
    # inside the function, so the package namespace is what must be patched.
    monkeypatch.setattr("tonyagent.config.save_provider_selection", boom)
    reply = _bind("openrouter", "stealth/space-bunny-alpha")
    assert "result" in reply, "the bind must still succeed"
    assert reply["result"].get("persisted") is False
