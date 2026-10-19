"""The config file's own sections, which nothing read.

``settings`` is built from the environment (``TONYAGENT_*``) and
``model_config`` has no toml source, so ``settings.tools.command_allowlist`` and
``settings.sandbox.enable_network`` were *defaults* -- and the ``[tools]`` and
``[sandbox]`` tables written into config.toml were read by nothing at all. Three
settings were live in that sense, and all three are pinned here:

* the per-turn tool budget, written by the composer's budget control and
  restored from nowhere -- a budget of 200 looked saved, and every launch came
  back on 10;
* the command allow and deny lists, which the shell gate asked the model for;
* every sandbox field, so choosing a backend, a distro or egress changed
  nothing unless the process happened to be started with the matching
  environment variable.

``load_section`` is the read side. These tests are about the ways it can be
wrong: answering with a default when the file said something, and letting a
hand-edited file take the app down.
"""

from __future__ import annotations

import asyncio

import pytest
import tomli
import tomli_w

from tonyagent.config import migration
from tonyagent.config.migration import load_section
from tonyagent.config.settings import ToolsSettings
from tonyagent.core.events import EventBus
from tonyagent.core.session import AgentSession, _default_max_tool_calls
from tonyagent.tools.shell_tools import (
    _is_command_allowed,
    denylist_reason,
    effective_command_lists,
)


@pytest.fixture
def isolated_config(tmp_path, monkeypatch):
    """Redirect the config path itself, so the real one is never touched."""
    path = tmp_path / "TONYAgent" / "config.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(migration, "get_config_path", lambda: path)
    return path


def _write(path, data: dict) -> None:
    with open(path, "wb") as handle:
        tomli_w.dump(data, handle)


def _read(path) -> dict:
    with open(path, "rb") as handle:
        return tomli.load(handle)


# --- the read side ------------------------------------------------------------


def test_the_file_wins_over_the_model(isolated_config):
    """The bug, stated as one assertion.

    `settings` is environment-only, so a reader that asked it got the code's
    default no matter what the file said. The file is what the app wrote.
    """
    _write(
        isolated_config,
        {"tools": {"command_allowlist": ["node"]}, "meta": {"version": 2}},
    )
    assert load_section("tools").command_allowlist == ["node"]


def test_a_key_the_file_omits_keeps_the_current_default(isolated_config):
    """Merged, not taken whole.

    A file written by an older version has fewer keys than the model has today,
    and the answer for one it does not mention has to be today's default rather
    than a missing value.
    """
    _write(
        isolated_config,
        {"tools": {"command_allowlist": ["node"]}, "meta": {"version": 2}},
    )
    section = load_section("tools")
    assert section.command_denylist == ToolsSettings().command_denylist
    assert section.max_tool_calls == ToolsSettings().max_tool_calls


def test_a_missing_file_answers_with_the_defaults(tmp_path, monkeypatch):
    monkeypatch.setattr(migration, "get_config_path", lambda: tmp_path / "nothing.toml")
    assert load_section("sandbox").type == "auto"


def test_a_section_that_cannot_be_validated_is_ignored(isolated_config):
    """A typo must not be the reason the app will not start.

    The environment path has always had pydantic's type checking behind it; the
    file now goes through the same model, and a section it rejects is ignored
    rather than raised -- which is the same answer as a file never written.
    """
    _write(
        isolated_config,
        {"sandbox": {"type": "podman"}, "meta": {"version": 2}},
    )
    assert load_section("sandbox").type == "auto"


# --- the three settings that were written and never read ----------------------


def test_the_tool_budget_comes_back_from_the_file(isolated_config):
    """What the composer's budget control wrote. It was never read back."""
    _write(
        isolated_config,
        {"tools": {"max_tool_calls": 200}, "meta": {"version": 2}},
    )
    assert _default_max_tool_calls() == 200


def test_a_zero_budget_still_means_no_limit(isolated_config):
    """The sentinel survives the round trip, or "no limit" becomes "one"."""
    _write(
        isolated_config,
        {"tools": {"max_tool_calls": 0}, "meta": {"version": 2}},
    )
    assert _default_max_tool_calls() == 0


def test_a_budget_below_one_is_corrected_to_the_floor(isolated_config):
    """Zero is a choice; below it is a mistake, and one is the floor."""
    _write(
        isolated_config,
        {"tools": {"max_tool_calls": -5}, "meta": {"version": 2}},
    )
    assert _default_max_tool_calls() == 1


def test_the_shell_gate_allows_what_the_file_allows(isolated_config):
    """The allow list the user chose is the one the tool consults."""
    _write(
        isolated_config,
        {"tools": {"command_allowlist": ["git"]}, "meta": {"version": 2}},
    )
    allowed, _reason = _is_command_allowed("git status")
    assert allowed

    refused, reason = _is_command_allowed("python -c 'print(1)'")
    assert not refused
    assert "not in allowlist" in reason


def test_a_deny_pattern_added_by_hand_is_in_force(isolated_config):
    _write(
        isolated_config,
        {"tools": {"command_denylist": [r"\bcurl\b"]}, "meta": {"version": 2}},
    )
    assert denylist_reason("curl https://example.com") == r"\bcurl\b"


def test_a_hand_written_deny_list_cannot_shorten_the_floor(isolated_config):
    """A deny list is a floor, not a preference.

    At Full it is the only thing between the agent and the machine, so the file
    can add to it and cannot cut it. Asserted through the reader, because that
    is where the union happens.
    """
    _write(
        isolated_config,
        {"tools": {"command_denylist": [r"\bcurl\b"]}, "meta": {"version": 2}},
    )
    _allow, deny = effective_command_lists()
    assert r"\bcurl\b" in deny, "the hand-written pattern is in force"
    assert deny[: len(ToolsSettings().command_denylist)] == ToolsSettings().command_denylist


def test_a_chosen_backend_reaches_the_sandbox(isolated_config, tmp_path, monkeypatch):
    """The settings page's whole purpose: a choice that is actually used."""
    _write(
        isolated_config,
        {
            "sandbox": {
                "type": "wsl",
                "wsl_distro": "Ubuntu-24.04",
                "enable_network": True,
            },
            "meta": {"version": 2},
        },
    )

    seen: dict = {}

    class FakeManager:
        async def start(self, config):
            seen["config"] = config
            return True

        def is_isolated(self) -> bool:
            return True

    import tonyagent.sandbox as sandbox_package

    monkeypatch.setattr(
        sandbox_package, "get_shared_sandbox_manager", lambda: FakeManager()
    )

    session = AgentSession(bus=EventBus())
    assert asyncio.run(session.start_sandbox(str(tmp_path)))

    assert seen["config"].type == "wsl"
    assert seen["config"].wsl_distro == "Ubuntu-24.04"
    assert seen["config"].enable_network is True


# --- the migration that clears the stale copies -------------------------------


def test_a_v1_file_loses_the_two_stale_lists_and_keeps_everything_else(isolated_config):
    """The lists in a v1 file are a default from whichever build wrote them.

    Left in place they would now win, and the v1 copy is a safety regression
    rather than a preference: it is missing `python3` and `pip3` (the spellings
    a WSL distro answers to) and missing three of the deny patterns. Everything
    else in the section -- including the budget -- is carried through.
    """
    _write(
        isolated_config,
        {
            "meta": {"version": 1},
            "tools": {
                "command_allowlist": ["python"],
                "command_denylist": ["shutdown"],
                "max_tool_calls": 200,
            },
            "sandbox": {"type": "docker", "memory_limit": "4g"},
        },
    )

    migration.load_config()

    after = _read(isolated_config)
    assert "command_allowlist" not in after["tools"]
    assert "command_denylist" not in after["tools"]
    assert after["tools"]["max_tool_calls"] == 200
    assert after["sandbox"]["type"] == "docker"
    assert after["sandbox"]["memory_limit"] == "4g"
    assert after["meta"]["version"] == migration.CURRENT_CONFIG_VERSION


def test_a_v0_file_still_migrates_all_the_way(isolated_config):
    """The v0 step now hands over to the v1 step rather than jumping the gun.

    It used to stamp the *current* version inside the v0 branch, which meant a
    v0 file skipped every later step. Nothing noticed while there was only one.
    """
    _write(isolated_config, {"provider": {"name": "openai", "model": "gpt-4o"}})

    config = migration.load_config()

    assert config["provider"]["name"] == "openai"
    assert config["meta"]["version"] == migration.CURRENT_CONFIG_VERSION
    for section in ("sandbox", "tools", "logging", "folder", "ui"):
        assert section in config
