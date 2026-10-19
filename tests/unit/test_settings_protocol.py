"""The settings a window may write.

`settings.get` and `settings.set` are the pair the settings page uses to change
something in config.toml. They exist because the file is the store: `settings`
is environment-only (see `migration.load_section`), so a control that wrote the
model would change nothing, and a control that wrote the file without a read
side would have changed nothing either.

Three properties are pinned here, and they are the three ways this pair can be
wrong:

* **The whitelist.** The same file holds `[keys.*]` and the provider the window
  is bound to. A method that wrote any key it was given would be a way to change
  things no control on the page asked for.
* **The reply is what is in force.** A panel that echoed the value it sent would
  show a rule the core is not holding anyone to the moment a write fails.
* **The deny list is not writable.** It is a floor -- the code's patterns plus
  whatever the file adds -- and the page reports it rather than editing it.
"""

from __future__ import annotations

import asyncio
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


def _read(path) -> dict:
    with open(path, "rb") as handle:
        return tomli.load(handle)


# --- reading ------------------------------------------------------------------


def test_get_reports_the_allow_list_the_gate_will_use(isolated_config):
    reply = _call("settings.get")
    listed = reply["result"]["tools"]["command_allowlist"]
    assert "python" in listed
    assert "python3" in listed, "the Unix spelling is in the code's default"


def test_get_reports_the_defaults_beside_the_current_list(isolated_config):
    """What "Restore defaults" goes back to, without the panel owning a list."""
    _call("settings.set", {"key": "tools.command_allowlist", "value": ["git"]})
    listed = _call("settings.get")["result"]["tools"]
    assert listed["command_allowlist"] == ["git"]
    assert "python3" in listed["command_allowlist_defaults"]


def test_get_reports_the_deny_list_as_the_union(isolated_config):
    """The floor survives a file that names only one pattern.

    This is the read the page draws its safety read-out from, so it has to be
    the list a turn is held to rather than the file's half of it.
    """
    migration.save_section_value("tools", "command_denylist", [r"\bcurl\b"])
    deny = _call("settings.get")["result"]["tools"]["command_denylist"]
    assert r"\bcurl\b" in deny
    assert any("remove-item" in pattern for pattern in deny)


# --- writing ------------------------------------------------------------------


def test_set_writes_the_allow_list_to_the_file(isolated_config):
    reply = _call(
        "settings.set", {"key": "tools.command_allowlist", "value": ["git", "npm"]}
    )
    assert reply["result"]["persisted"] is True
    assert _read(isolated_config)["tools"]["command_allowlist"] == ["git", "npm"]


def test_set_reply_is_the_value_in_force(isolated_config):
    """Read back through the same reader, not echoed from the request."""
    reply = _call(
        "settings.set", {"key": "tools.command_allowlist", "value": [" git ", "GIT"]}
    )
    assert reply["result"]["value"] == ["git"]


def test_the_gate_uses_what_the_window_just_wrote(isolated_config):
    """The whole point of the pair: a choice that is actually in force."""
    from tonyagent.tools.shell_tools import _is_command_allowed

    _call("settings.set", {"key": "tools.command_allowlist", "value": ["git"]})

    allowed, _reason = _is_command_allowed("git status")
    assert allowed

    refused, reason = _is_command_allowed("python -c 'print(1)'")
    assert not refused
    assert "not in allowlist" in reason


def test_unset_removes_the_key_and_goes_back_to_the_default(isolated_config):
    """`null` is the panel's "Restore defaults".

    Removing rather than writing today's default, so the file does not freeze a
    copy of a list the core owns -- see `save_section_value`.
    """
    _call("settings.set", {"key": "tools.command_allowlist", "value": ["git"]})
    reply = _call("settings.set", {"key": "tools.command_allowlist", "value": None})

    assert reply["result"]["persisted"] is True
    assert "command_allowlist" not in _read(isolated_config)["tools"]
    assert reply["result"]["value"] == _call("settings.get")["result"]["tools"][
        "command_allowlist"
    ]
    assert "python3" in reply["result"]["value"]


def test_a_failed_save_is_reported_and_the_reply_is_the_old_value(
    isolated_config, monkeypatch
):
    """A write that fails changes nothing, and the panel has to be able to say so.

    For these settings the file *is* the store, so unlike `tools.set` there is no
    in-memory copy that took the change anyway.
    """

    def boom(*args, **kwargs):
        raise OSError("disk is full")

    _call("settings.set", {"key": "tools.command_allowlist", "value": ["git"]})
    monkeypatch.setattr("tonyagent.config.migration.save_section_value", boom)

    reply = _call("settings.set", {"key": "tools.command_allowlist", "value": ["npm"]})
    assert reply["result"]["persisted"] is False
    assert reply["result"]["value"] == ["git"], "the reply is what is still in force"


# --- the whitelist ------------------------------------------------------------


def test_an_unknown_key_is_refused(isolated_config):
    reply = _call("settings.set", {"key": "provider.model", "value": "evil"})
    assert "provider.model" in reply["error"]["message"]


def test_the_deny_list_is_not_writable(isolated_config):
    """It is a floor, not a preference -- so there is no way to cut it."""
    reply = _call("settings.set", {"key": "tools.command_denylist", "value": []})
    assert "tools.command_denylist" in reply["error"]["message"]


def test_the_key_registry_is_not_writable(isolated_config):
    """`key.activate` owns which key a turn spends, not a generic setter."""
    reply = _call("settings.set", {"key": "keys.openrouter.active", "value": "mine"})
    assert "keys.openrouter.active" in reply["error"]["message"]


# --- validation ---------------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    [
        "python",
        [3],
        [""],
        ["  "],
        ["/usr/bin/git"],
        ["C:\\Python\\python.exe"],
        ["python -c"],
    ],
)
def test_a_name_that_could_never_match_is_refused(isolated_config, value):
    """A row that quietly does nothing is the failure this page must not ship.

    An entry is matched exactly against the program's name, so a path or a
    command line can never match anything.
    """
    reply = _call("settings.set", {"key": "tools.command_allowlist", "value": value})
    assert "error" in reply, value


def test_duplicates_are_folded_case_insensitively(isolated_config):
    """The match is case-insensitive, so two rows are one rule written twice."""
    reply = _call(
        "settings.set",
        {"key": "tools.command_allowlist", "value": ["Git", "git", "GIT", "npm"]},
    )
    assert reply["result"]["value"] == ["Git", "npm"]


def test_an_empty_list_is_allowed(isolated_config):
    """A real, if extreme, choice: nothing runs outside the deny list.

    Refusing it would be this page overruling the user about their own machine.
    What keeps it recoverable is that "Restore defaults" is always there.
    """
    reply = _call("settings.set", {"key": "tools.command_allowlist", "value": []})
    assert reply["result"]["persisted"] is True
    assert reply["result"]["value"] == []
