"""Named API keys: the keyring scheme, the config registry, and every RPC.

The feature is one idea in three places -- a name maps to a keyring field, the
names live in config.toml because the keyring cannot be listed, and five RPCs
move them around -- so these tests are grouped the same way. Nothing here
touches the real credential store or the real config file: the fixture below
replaces the keyring module, and the config path is redirected to tmp_path.

No test prints or asserts on a real key. The values below are obviously fake
and are only ever compared to themselves.
"""

from __future__ import annotations

import asyncio
import io
import json

import pytest
import tomli

from tonyagent.config.keyring import (
    KeyringError,
    delete_api_key,
    get_all_stored_providers,
    load_api_key,
    normalize_key_name,
    save_api_key,
    stored_key_names,
)
from tonyagent.config.migration import (
    add_key_name,
    get_active_key_name,
    load_config,
    load_key_names,
    remove_key_name,
    save_key_registry,
    save_max_tool_calls,
    save_provider_selection,
    set_active_key_name,
)
from tonyagent.core.events import EventBus
from tonyagent.core.session import AgentSession
from tonyagent.headless.server import StdioServer


# Obviously fake, provider-shaped values. Lengths only ever matter in the
# report, never in an assertion that could print one.
_KEY_A = "sk-or-v1-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
_KEY_B = "sk-or-v1-bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"


class _FakeKeyring:
    """In-memory stand-in for the keyring module. Never the OS store."""

    def __init__(self) -> None:
        self.store: dict[tuple[str, str], str] = {}

    def set_password(self, service: str, key: str, value: str) -> None:
        self.store[(service, key)] = value

    def get_password(self, service: str, key: str) -> str | None:
        return self.store.get((service, key))

    def delete_password(self, service: str, key: str) -> None:
        self.store.pop((service, key), None)


@pytest.fixture
def fake_keyring(monkeypatch):
    """Every keyring call lands in a dict, so no OS credential store is read."""
    import tonyagent.config.keyring as keyring_mod

    fake = _FakeKeyring()
    monkeypatch.setattr(keyring_mod, "keyring", fake)
    return fake


@pytest.fixture
def config_file(monkeypatch, tmp_path):
    """A throwaway config.toml for one test, and its path.

    conftest already redirects the session, so this is not what keeps the real
    file safe. It is what makes the file inspectable per test: the registry is
    the part of this feature that lives on disk, and a test that could not read
    it back would be testing a dict rather than the feature.
    """
    from tonyagent.config import migration

    path = tmp_path / "config.toml"
    monkeypatch.setattr(migration, "get_config_path", lambda: path)
    return path


# --- the naming scheme ------------------------------------------------------
def test_a_name_becomes_a_lowercase_dash_separated_slug():
    assert normalize_key_name("Work Key") == "work-key"
    assert normalize_key_name("  Personal  ") == "personal"
    assert normalize_key_name("my_key.v2") == "my-key-v2"


def test_the_empty_and_default_names_both_mean_the_historical_slot():
    # key.save's name is optional, and every key saved before names existed is
    # stored under the default slot. Both spellings have to land there.
    assert normalize_key_name(None) == "default"
    assert normalize_key_name("") == "default"
    assert normalize_key_name("Default") == "default"


def test_a_name_with_no_letters_or_digits_is_refused():
    # It would slug to the empty string, which is the default field -- so
    # accepting it would let "!!!" overwrite the legacy key.
    with pytest.raises(KeyringError):
        normalize_key_name("!!!")


def test_a_named_key_is_stored_under_its_slug(fake_keyring, config_file):
    save_api_key("openrouter", _KEY_A, "Work Key")
    assert fake_keyring.store[("TONYAgent", "openrouter:key:work-key")] == _KEY_A


def test_the_default_name_keeps_the_old_keyring_field(fake_keyring, config_file):
    # The compatibility rule the whole design rests on: no migration, no
    # orphaned keys. A key written by the previous build is read by this one.
    save_api_key("openrouter", _KEY_B, "default")
    assert fake_keyring.store[("TONYAgent", "openrouter:api_key")] == _KEY_B
    assert ("TONYAgent", "openrouter:key:default") not in fake_keyring.store


def test_a_pre_existing_key_loads_with_no_name_and_no_migration(fake_keyring, config_file):
    fake_keyring.store[("TONYAgent", "openrouter:api_key")] = _KEY_A
    # No registry entry at all -- exactly the state an older install is in.
    assert load_api_key("openrouter") == _KEY_A
    assert stored_key_names("openrouter") == ["default"]


def test_load_with_no_name_follows_the_active_key(fake_keyring, config_file):
    save_api_key("openrouter", _KEY_A)
    save_api_key("openrouter", _KEY_B, "work")
    add_key_name("openrouter", "work")
    set_active_key_name("openrouter", "work")

    assert load_api_key("openrouter") == _KEY_B
    # The default is still there, named explicitly.
    assert load_api_key("openrouter", "default") == _KEY_A


def test_load_with_no_name_falls_back_to_default(fake_keyring, config_file):
    save_api_key("openrouter", _KEY_A)
    assert get_active_key_name("openrouter") == ""
    assert load_api_key("openrouter") == _KEY_A


def test_stored_names_include_the_unregistered_default(fake_keyring, config_file):
    fake_keyring.store[("TONYAgent", "openrouter:api_key")] = _KEY_A
    save_api_key("openrouter", _KEY_B, "work")
    add_key_name("openrouter", "work")
    # Default first: it is the legacy slot and the fallback the panel explains.
    assert stored_key_names("openrouter") == ["default", "work"]


def test_delete_removes_only_the_named_key(fake_keyring, config_file):
    save_api_key("openrouter", _KEY_A)
    save_api_key("openrouter", _KEY_B, "work")
    delete_api_key("openrouter", "work")
    assert load_api_key("openrouter", "work") is None
    assert load_api_key("openrouter", "default") == _KEY_A


def test_users_can_see_a_provider_that_only_has_a_named_key(fake_keyring, config_file):
    save_api_key("openrouter", _KEY_A, "work")
    add_key_name("openrouter", "work")
    assert "openrouter" in get_all_stored_providers()


# --- the registry in config.toml -------------------------------------------
def test_the_registry_round_trips_through_the_config_file(config_file):
    assert load_key_names("openrouter") == []
    assert get_active_key_name("openrouter") == ""

    save_key_registry("openrouter", ["default", "work"], "work")

    assert load_key_names("openrouter") == ["default", "work"]
    assert get_active_key_name("openrouter") == "work"
    raw = tomli.loads(config_file.read_text(encoding="utf-8"))
    assert raw["keys"]["openrouter"]["names"] == ["default", "work"]
    assert raw["keys"]["openrouter"]["active"] == "work"


def test_the_registry_write_leaves_every_other_section_alone(config_file):
    # The read-modify-write contract save_max_tool_calls established: a key
    # name must not be able to reset the tool budget or the bound endpoint.
    save_max_tool_calls(7)
    save_provider_selection("openrouter", "a/b", "https://gateway.internal/v1")

    add_key_name("openrouter", "work")

    config = load_config()
    assert config["tools"]["max_tool_calls"] == 7
    assert config["provider"]["model"] == "a/b"
    assert config["provider"]["base_url"] == "https://gateway.internal/v1"
    assert load_key_names("openrouter") == ["work"]


def test_two_providers_keep_their_own_names(config_file):
    add_key_name("openrouter", "a")
    add_key_name("opencode-go", "b")
    assert load_key_names("openrouter") == ["a"]
    assert load_key_names("opencode-go") == ["b"]


def test_adding_a_key_does_not_steal_the_active_choice(config_file):
    add_key_name("openrouter", "work")
    add_key_name("openrouter", "personal")
    set_active_key_name("openrouter", "work")
    add_key_name("openrouter", "third")
    assert get_active_key_name("openrouter") == "work"
    assert load_key_names("openrouter") == ["work", "personal", "third"]


def test_removing_the_active_key_clears_the_pointer_rather_than_promoting(config_file):
    add_key_name("openrouter", "work")
    set_active_key_name("openrouter", "work")
    remove_key_name("openrouter", "work")
    # Empty means load_api_key falls back to "default"; silently electing the
    # next name would change which credential the next message spent.
    assert get_active_key_name("openrouter") == ""


def test_removing_the_last_key_prunes_the_provider_table(config_file):
    add_key_name("openrouter", "work")
    remove_key_name("openrouter", "work")
    assert "keys" not in load_config()


# --- the RPCs ---------------------------------------------------------------
class _StubProvider:
    """Enough of a provider for a server that never runs a turn."""

    model = "stub-model"

    async def chat_completion(self, *args, **kwargs):  # pragma: no cover
        raise AssertionError("a key RPC must never run a turn")


def _drive(requests):
    """Push requests through a real StdioServer and return parsed frames."""
    session = AgentSession(bus=EventBus())
    session.provider = _StubProvider()
    session.model = "stub-model"
    session.provider_name = "openrouter"
    stdin = io.StringIO("\n".join(json.dumps(r) for r in requests) + "\n")
    stdout = io.StringIO()
    asyncio.run(StdioServer(session, stdin, stdout).serve())
    return [json.loads(line) for line in stdout.getvalue().splitlines() if line.strip()]


def _save(provider, api_key, name=None):
    params = {"provider": provider, "api_key": api_key}
    if name is not None:
        params["name"] = name
    return {"id": 1, "method": "key.save", "params": params}


def test_key_save_with_a_name_stores_and_registers_it(fake_keyring, config_file):
    frames = _drive([_save("openrouter", _KEY_A, "Work Key")])
    assert frames[0]["result"] == {
        "provider": "openrouter",
        "name": "work-key",
        "saved": True,
        "listed": True,
    }
    assert fake_keyring.store[("TONYAgent", "openrouter:key:work-key")] == _KEY_A
    assert load_key_names("openrouter") == ["work-key"]
    raw = tomli.loads(config_file.read_text(encoding="utf-8"))
    assert raw["keys"]["openrouter"]["names"] == ["work-key"]


def test_the_first_key_a_provider_gets_becomes_active(fake_keyring, config_file):
    # Otherwise a user saves their only key and every later turn fails: the
    # active name is "default", and this key is not it.
    _drive([_save("openrouter", _KEY_A, "work")])
    assert get_active_key_name("openrouter") == "work"
    assert load_api_key("openrouter") == _KEY_A


def test_a_later_key_does_not_take_over(fake_keyring, config_file):
    _drive([_save("openrouter", _KEY_A)])
    _drive([_save("openrouter", _KEY_B, "work")])
    assert get_active_key_name("openrouter") == "default"
    assert load_api_key("openrouter") == _KEY_A


def test_saving_a_name_twice_overwrites_one_row(fake_keyring, config_file):
    _drive([_save("openrouter", _KEY_A, "Work Key")])
    _drive([_save("openrouter", _KEY_B, "work-key")])
    assert load_key_names("openrouter") == ["work-key"]
    assert load_api_key("openrouter", "work-key") == _KEY_B


def test_key_list_reports_every_row_and_marks_the_active_one(fake_keyring, config_file):
    _drive([
        _save("openrouter", _KEY_A),
        _save("openrouter", _KEY_B, "work"),
        {"id": 3, "method": "key.activate",
         "params": {"provider": "openrouter", "name": "work"}},
    ])
    frames = _drive([{"id": 1, "method": "key.list"}])
    rows = frames[0]["result"]
    assert isinstance(rows, list)
    active = {(row["provider"], row["name"]): row["active"] for row in rows}
    assert active == {
        ("openrouter", "default"): False,
        ("openrouter", "work"): True,
    }
    # The list is a list of names. Neither value may appear anywhere in it.
    wire = json.dumps(frames)
    assert _KEY_A not in wire and _KEY_B not in wire


def test_key_list_can_be_scoped_to_one_provider(fake_keyring, config_file):
    _drive([_save("openrouter", _KEY_A), _save("opencode-go", _KEY_B, "go")])
    frames = _drive([{"id": 1, "method": "key.list", "params": {"provider": "openrouter"}}])
    assert [row["provider"] for row in frames[0]["result"]] == ["openrouter"]


def test_key_reveal_by_name_returns_that_row(fake_keyring, config_file):
    _drive([_save("openrouter", _KEY_A), _save("openrouter", _KEY_B, "work")])
    frames = _drive([
        {"id": 1, "method": "key.reveal",
         "params": {"provider": "openrouter", "name": "work"}},
    ])
    assert frames[0]["result"] == {
        "provider": "openrouter",
        "name": "work",
        "api_key": _KEY_B,
    }


def test_key_reveal_without_a_name_returns_the_active_key(fake_keyring, config_file):
    _drive([
        _save("openrouter", _KEY_A),
        _save("openrouter", _KEY_B, "work"),
        {"id": 3, "method": "key.activate",
         "params": {"provider": "openrouter", "name": "work"}},
    ])
    frames = _drive([{"id": 1, "method": "key.reveal", "params": {"provider": "openrouter"}}])
    assert frames[0]["result"]["name"] == "work"
    assert frames[0]["result"]["api_key"] == _KEY_B


def test_key_reveal_is_still_the_only_method_that_returns_a_key(fake_keyring, config_file):
    _drive([_save("openrouter", _KEY_A, "work")])
    for method in (
        {"id": 1, "method": "state"},
        {"id": 1, "method": "providers.list"},
        {"id": 1, "method": "key.list"},
    ):
        frames = _drive([method])
        assert _KEY_A not in json.dumps(frames), method["method"]


def test_key_delete_removes_the_named_key_and_its_registry_entry(fake_keyring, config_file):
    _drive([_save("openrouter", _KEY_A), _save("openrouter", _KEY_B, "work")])
    frames = _drive([
        {"id": 1, "method": "key.delete",
         "params": {"provider": "openrouter", "name": "work"}},
    ])
    assert frames[0]["result"] == {
        "provider": "openrouter",
        "name": "work",
        "deleted": True,
    }
    assert load_api_key("openrouter", "work") is None
    assert load_key_names("openrouter") == ["default"]
    assert load_api_key("openrouter") == _KEY_A


def test_key_delete_requires_a_name(fake_keyring, config_file):
    # No name is a destructive default: it could remove a key the caller did
    # not name. The old one-argument form is gone on purpose.
    frames = _drive([
        {"id": 1, "method": "key.delete", "params": {"provider": "openrouter"}},
    ])
    assert frames[0]["error"]["code"] == "rejected"


def test_key_activate_changes_which_key_a_turn_would_use(fake_keyring, config_file):
    _drive([_save("openrouter", _KEY_A), _save("openrouter", _KEY_B, "work")])
    frames = _drive([
        {"id": 1, "method": "key.activate",
         "params": {"provider": "openrouter", "name": "work"}},
    ])
    assert frames[0]["result"] == {
        "provider": "openrouter",
        "name": "work",
        "active": True,
    }
    assert get_active_key_name("openrouter") == "work"
    assert load_api_key("openrouter") == _KEY_B


def test_key_activate_refuses_a_name_nothing_is_stored_under(fake_keyring, config_file):
    # Pointing the provider at an empty slot would fail on the next message
    # while this reply claimed success.
    _drive([_save("openrouter", _KEY_A)])
    frames = _drive([
        {"id": 1, "method": "key.activate",
         "params": {"provider": "openrouter", "name": "ghost"}},
    ])
    assert frames[0]["error"]["code"] == "rejected"
    assert get_active_key_name("openrouter") == "default"


def test_key_save_rejects_a_name_made_only_of_punctuation(fake_keyring, config_file):
    frames = _drive([_save("openrouter", _KEY_A, "!!!")])
    assert frames[0]["error"]["code"] == "rejected"
    assert fake_keyring.store == {}


def test_a_named_save_never_puts_the_key_on_the_wire(fake_keyring, config_file):
    frames = _drive([_save("openrouter", _KEY_A, "work"), {"id": 2, "method": "state"}])
    wire = json.dumps(frames)
    assert _KEY_A not in wire
    assert _KEY_A[:16] not in wire and _KEY_A[-16:] not in wire
