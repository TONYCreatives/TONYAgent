"""Persisting the provider the user chose.

The Tauri sidecar never wrote provider settings anywhere: ``save_config`` was
only ever called from the Tkinter app's exit handler. So every launch came back
on a default provider *name* with no provider object behind it, and the first
message failed with "no provider configured" -- which reads, from the UI, exactly
like a key that was never saved.

These tests pin the write as a read-modify-write. The hazard is specific and
silent: ``save_config`` takes a whole config dict, and building one from
``settings`` would write defaults over the user's real settings, because the
sidecar never loads config.toml into ``settings`` in the first place.
"""

from __future__ import annotations

import pytest
import tomli
import tomli_w

from tonyagent.config import migration


@pytest.fixture
def isolated_config(tmp_path, monkeypatch):
    """Redirect the config path itself, so the real one is never touched.

    Patched where it is computed rather than by setting APPDATA: an
    environment variable can be read before the patch lands, and a test that
    rewrites the user's real config.toml is not a failure mode worth keeping.
    """
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


def test_saving_a_model_updates_only_the_provider(isolated_config):
    _write(isolated_config, {"provider": {"name": "openrouter", "model": "old/model"}})
    migration.save_provider_selection("openrouter", "stealth/space-bunny-alpha", "")
    assert _read(isolated_config)["provider"]["model"] == "stealth/space-bunny-alpha"


def test_every_other_section_survives(isolated_config):
    """The regression this guards is a config file full of defaults.

    Asserted on parsed values, not on file text: ``tomli_w`` reflows lists and
    spacing, so a string comparison would pass on a file that lost data and
    fail on one that kept it.
    """
    seeded = {
        "provider": {"name": "openrouter", "model": "old", "base_url": ""},
        "tools": {"command_allowlist": ["python", "node", "git"], "max_output_size": 12345},
        "sandbox": {"enable_network": True, "memory_limit": "4g"},
        "ui": {"theme": "dark", "font_size": 13},
        "meta": {"version": 1},
    }
    _write(isolated_config, seeded)
    migration.save_provider_selection("openrouter", "stealth/space-bunny-alpha", "")
    after = _read(isolated_config)

    for section, key in (
        ("tools", "command_allowlist"),
        ("tools", "max_output_size"),
        ("sandbox", "enable_network"),
        ("sandbox", "memory_limit"),
        ("ui", "theme"),
        ("ui", "font_size"),
    ):
        assert after[section][key] == seeded[section][key], f"{section}.{key} was lost"


def test_the_api_key_is_never_written_to_the_config(isolated_config):
    """A config file is one screenshot away; the keyring is the right place.

    ``ProviderSettings.api_key`` exists in the model and is documented as
    keyring-only, so this is the assertion that keeps it that way.
    """
    _write(isolated_config, {"provider": {"name": "openrouter"}})
    migration.save_provider_selection("openrouter", "m", "")
    assert "api_key" not in _read(isolated_config)["provider"]
    assert "api_key" not in isolated_config.read_text(encoding="utf-8")


def test_a_missing_config_file_is_created(isolated_config):
    # First run ever: the directory exists but config.toml does not.
    assert not isolated_config.exists()
    migration.save_provider_selection("openrouter", "stealth/space-bunny-alpha", "")
    assert _read(isolated_config)["provider"]["model"] == "stealth/space-bunny-alpha"


def test_a_corrupt_config_file_does_not_lose_the_selection(isolated_config):
    """``load_config`` backs up an unreadable file and starts fresh.

    The selection still has to land, or the user is left with a config that
    has neither their settings nor their model.
    """
    isolated_config.write_text("this is not toml [[[", encoding="utf-8")
    migration.save_provider_selection("openrouter", "stealth/space-bunny-alpha", "")
    assert _read(isolated_config)["provider"]["model"] == "stealth/space-bunny-alpha"
    # And the unreadable original is kept rather than silently destroyed.
    assert isolated_config.with_suffix(".toml.bak").exists()


def test_a_typed_model_id_round_trips(isolated_config):
    """The model field is free text, not a closed list.

    A namespaced id like ``stealth/space-bunny-alpha`` is exactly what a
    provider suggests but never enumerates, and it must survive a save/load
    cycle unchanged or the user's choice is meaningless.
    """
    typed = "stealth/space-bunny-alpha"
    _write(isolated_config, {"provider": {"name": "openrouter"}})
    migration.save_provider_selection("openrouter", typed, "")
    assert migration.load_config()["provider"]["model"] == typed
