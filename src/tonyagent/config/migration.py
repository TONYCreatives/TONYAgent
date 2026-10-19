"""Configuration migration utilities."""

from __future__ import annotations

import shutil
import tomli
import tomli_w
from pathlib import Path
from loguru import logger

from tonyagent.config.settings import settings


CURRENT_CONFIG_VERSION = 2


def get_config_path() -> Path:
    """Get the path to the config file."""
    return settings.get_config_dir() / "config.toml"


def get_config_version(config: dict) -> int:
    """Get the config version from a config dict."""
    return config.get("meta", {}).get("version", 0)


def migrate_config(config: dict) -> dict:
    """Migrate config from older versions to current."""
    version = get_config_version(config)

    if version == 0:
        # Version 0 -> 1: Add meta section, restructure provider config
        logger.info("Migrating config from version 0 to 1")
        config["meta"] = {"version": CURRENT_CONFIG_VERSION}

        # Move flat provider settings to nested structure
        if "provider" in config and isinstance(config["provider"], dict):
            old_provider = config["provider"]
            config["provider"] = {
                "name": old_provider.get("name", "openai"),
                "model": old_provider.get("model", ""),
                "base_url": old_provider.get("base_url", ""),
            }
            # API keys are handled by keyring migration

        # Ensure all sections exist
        defaults = {
            "sandbox": {},
            "tools": {},
            "logging": {},
            "folder": {},
            "ui": {},
        }
        for section, default in defaults.items():
            if section not in config:
                config[section] = default

        version = 1

    if version == 1:
        # Version 1 -> 2: drop the two tool lists that were written and never
        # read back.
        #
        # `[tools].command_allowlist` and `command_denylist` are the only keys
        # in this file with that history. Nothing in the core has ever written
        # them -- the old UI's exit handler wrote the whole config dict once --
        # and nothing read them either: `settings` is built from the
        # environment (`model_config` has no toml source) and the shell tools
        # ask *it*, so the copy in the file was whatever default the version
        # that wrote it happened to have.
        #
        # Left in place it would now win, because the read side is fixed in the
        # same release -- and the v1 copy is a *safety* regression rather than
        # a preference. It is missing `python3` and `pip3`, which are the
        # spellings a WSL distro actually answers to (so `python3 x.py` would
        # start being refused), and it is missing the `remove-item -recurse`,
        # `rd /s` and `curl | sh` deny patterns, so the list that stands between
        # a Full-permission turn and the machine would have got shorter.
        #
        # Removed rather than rewritten to today's default: absent means "the
        # default", so a file carries a list only once somebody has chosen one.
        logger.info("Migrating config from version 1 to 2 (dropping stale tool lists)")
        tools = config.get("tools")
        if isinstance(tools, dict):
            tools.pop("command_allowlist", None)
            tools.pop("command_denylist", None)

        version = 2

    config.setdefault("meta", {})["version"] = CURRENT_CONFIG_VERSION
    return config


def load_section(name: str):
    """One config section as a validated settings model.

    **The file is the truth; ``settings`` is only the defaults.** ``settings``
    is built from the environment (``TONYAGENT_*``) and nothing loads this file
    into it -- ``model_config`` has no toml source -- so a reader asking
    ``settings.sandbox.enable_network`` was asking for a *default*, and the
    ``[sandbox]`` and ``[tools]`` tables written into this file were read by
    nothing at all. Three things were live in that sense: the per-turn tool
    budget (``[tools].max_tool_calls``, written by the composer's budget control
    and restored from nowhere, so every launch came back on 10 whatever the file
    said), the command lists, and every sandbox field.

    Merged rather than taken whole, so a file written by an older version -- with
    fewer keys than the model has today -- still answers with the current default
    for anything it does not mention. A missing or unreadable file is the same
    case: :func:`load_config` answers with a bare config rather than raising, and
    the defaults are what a fresh install should get.

    Validated through the section's own model, so a hand-edited file gets the
    same type checking the environment path has always had -- and a section it
    cannot validate is *ignored* rather than fatal. A typo in one key must not be
    the reason the app will not start; it is logged and the defaults are used,
    which is the same answer as a file that was never written.
    """
    from tonyagent.config.settings import settings

    current = getattr(settings, name)
    stored = load_config().get(name)
    if not isinstance(stored, dict):
        return current
    try:
        return type(current)(**{**current.model_dump(), **stored})
    except Exception as exc:  # noqa: BLE001 - a bad edit must not stop a launch
        logger.warning(f"Ignoring the [{name}] section of config.toml: {exc}")
        return current


def load_config() -> dict:
    """Load and migrate configuration from file."""
    config_path = get_config_path()

    if not config_path.exists():
        return {"meta": {"version": CURRENT_CONFIG_VERSION}}

    try:
        with open(config_path, "rb") as f:
            config = tomli.load(f)

        version = get_config_version(config)
        if version < CURRENT_CONFIG_VERSION:
            config = migrate_config(config)
            save_config(config)

        return config
    except Exception as e:
        logger.error(f"Failed to load config: {e}")
        # Backup corrupted config
        backup_path = config_path.with_suffix(".toml.bak")
        shutil.copy2(config_path, backup_path)
        logger.warning(f"Backed up corrupted config to {backup_path}")
        return {"meta": {"version": CURRENT_CONFIG_VERSION}}


def save_config(config: dict) -> None:
    """Save configuration to file."""
    config_path = get_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)

    # Ensure version is set
    if "meta" not in config:
        config["meta"] = {}
    config["meta"]["version"] = CURRENT_CONFIG_VERSION

    try:
        with open(config_path, "wb") as f:
            tomli_w.dump(config, f)
        logger.debug(f"Saved config to {config_path}")
    except Exception as e:
        logger.error(f"Failed to save config: {e}")
        raise


def save_reasoning_effort(effort: str) -> None:
    """Record how hard the user wants the model to think.

    Same read-modify-write as :func:`save_provider_selection`, and for the same
    reason: the sidecar never loads ``settings``, so assembling a config dict
    from it here would write defaults over the user's real settings.

    An empty effort is written rather than removed, so switching back to "let
    the model decide" survives a restart the same way a chosen one does.
    """
    config = load_config()
    config.setdefault("provider", {})["reasoning_effort"] = effort
    save_config(config)


def save_max_tool_calls(limit: int) -> None:
    """Record how many tool calls one turn may make.

    Same read-modify-write as :func:`save_reasoning_effort`, and for the same
    reason: the sidecar never loads ``settings``, so assembling a config dict
    from it here would write defaults over the user's real tool allowlist.

    Only ``[tools].max_tool_calls`` is touched; the allowlist and denylist
    that live in the same section are carried through untouched.
    """
    config = load_config()
    # 0 is the no-limit sentinel -- see `AgentSession.set_max_tool_calls`. It is
    # the one value below the floor, and it has to survive the round trip through
    # this file or the choice would quietly become "1 per turn" on next launch.
    stored = int(limit)
    config.setdefault("tools", {})["max_tool_calls"] = stored if stored == 0 else max(1, stored)
    save_config(config)


def save_provider_selection(name: str, model: str = "", base_url: str = "") -> None:
    """Record the provider the user chose, so the next launch starts on it.

    Read-modify-write on purpose. ``save_config`` takes a whole config dict, and
    the Tkinter app builds that dict from ``settings`` -- safe for it, because
    Tk has always populated ``settings`` first. The sidecar does the opposite:
    ``settings`` never loads config.toml, so assembling a dict from it here
    would have written defaults over the user's real settings, tool allowlist
    and all, on the first bind.

    Only ``[provider]`` is touched; every other section is carried through
    untouched. The API key is deliberately never written here -- it belongs in
    the OS keyring, and a config file is one screenshot away.
    """
    config = load_config()
    provider = config.setdefault("provider", {})
    provider["name"] = name
    provider["model"] = model
    provider["base_url"] = base_url
    save_config(config)


def _keys_section(config: dict) -> dict:
    """The [keys] table, created on demand and never rebuilt.

    Kept apart from the accessors below because every one of them is the same
    read-modify-write: the file is the only place these names live (the keyring
    cannot be enumerated -- see keyring.get_all_stored_providers), so a caller
    that assembled the table from scratch would drop every name it did not
    happen to know about.
    """
    section = config.get("keys")
    if not isinstance(section, dict):
        section = {}
        config["keys"] = section
    return section


def load_key_names(provider: str) -> list[str]:
    """The key names recorded for one provider, in the order they were saved.

    A malformed entry answers with an empty list rather than raising: this runs
    on the load_api_key path, which every turn takes, and a hand-edited config
    must not be able to turn a missing name into a dead provider. The order is
    preserved because the panel draws the rows in it, and "the one I just added"
    landing in the middle of the list would move under the cursor.
    """
    config = load_config()
    section = config.get("keys")
    entry = section.get(provider) if isinstance(section, dict) else None
    names = entry.get("names") if isinstance(entry, dict) else None
    if not isinstance(names, list):
        return []
    return [name for name in names if isinstance(name, str) and name]


def get_active_key_name(provider: str) -> str:
    """The key name this provider's turns are pinned to, or "" for none.

    Empty is a real answer and not an error: it is what makes
    keyring.load_api_key fall back to "default", which is how a provider with
    one unnamed key -- every provider set up before names existed -- still
    resolves.
    """
    config = load_config()
    section = config.get("keys")
    entry = section.get(provider) if isinstance(section, dict) else None
    active = entry.get("active") if isinstance(entry, dict) else None
    return active if isinstance(active, str) else ""


def save_key_registry(provider: str, names: list[str], active: str) -> None:
    """Write one provider's key names and active name, read-modify-write.

    Same shape and same reason as save_max_tool_calls: the sidecar never loads
    settings, so assembling a whole config dict here would write defaults over
    the user's real settings. Only [keys.<provider>] is touched; every other
    section and every other provider carries through.

    The provider's entry is removed when it would be empty. Deleting the last
    key of a provider otherwise left an empty table behind in the file, which
    then answered key.list with a provider that has no keys -- and made a
    provider with stale config look "configured" to anyone reading the file.
    """
    config = load_config()
    section = _keys_section(config)
    if not names and not active:
        section.pop(provider, None)
        if not section:
            config.pop("keys", None)
        save_config(config)
        return
    section[provider] = {"names": list(names), "active": active}
    save_config(config)


def add_key_name(provider: str, name: str) -> None:
    """Record a saved key's name, keeping the active choice as it was.

    Saving does not silently switch which key a turn uses: a user adding a
    second key is not asking for it to take over. The one exception lives in the
    RPC handler (first key for a provider becomes active), because only that
    layer can tell "first ever" from "one more".
    """
    names = load_key_names(provider)
    if name not in names:
        names.append(name)
    save_key_registry(provider, names, get_active_key_name(provider))


def remove_key_name(provider: str, name: str) -> None:
    """Forget a deleted key's name, and clear it as active if it was.

    Clearing rather than promoting a neighbour is deliberate: the fallback in
    load_api_key is "default", and quietly electing another named key would mean
    a deletion changed which credential the next message spent.
    """
    names = [stored for stored in load_key_names(provider) if stored != name]
    active = get_active_key_name(provider)
    if active == name:
        active = ""
    save_key_registry(provider, names, active)


def set_active_key_name(provider: str, name: str) -> None:
    """Pin a provider's turns to one stored key.

    The name is appended when the registry does not know it yet, so an active
    pointer can never name a row the panel cannot draw. The RPC handler
    validates against the keyring before calling this; this is the backstop for
    a config that was hand-edited into disagreement with it.
    """
    names = load_key_names(provider)
    if name not in names:
        names.append(name)
    save_key_registry(provider, names, name)


def reset_config() -> None:
    """Reset configuration to defaults."""
    config_path = get_config_path()
    if config_path.exists():
        config_path.unlink()
    logger.info("Configuration reset to defaults")


def save_folder(current: str, recent: list[str] | None = None) -> None:
    """Record the project folder the user chose, so the next launch opens it.

    **`folder_manager.set_folder` assigns to the in-memory `settings` model and
    that is not enough.** The model is never written back on attribute
    assignment, so the choice worked for the session and then vanished: the
    sidebar still showed the project, because a conversation records its own
    `project` on disk, while every tool reported "No project folder selected",
    because the folder itself came back empty. The window and the gate
    disagreeing about which project is open, which is the same failure as the
    one `_bind_project` fixes -- only across a restart instead of within one.

    Same read-modify-write as :func:`save_max_tool_calls`, and for the same
    reason: the sidecar never loads ``settings``, so assembling a config dict
    from it here would write defaults over the user's real settings.

    Both ``current`` and ``recent`` are written together because they are one
    decision. ``FolderManager`` updates them in the same call, and writing only
    ``current`` would leave the recent list describing a folder that is no
    longer the one in use.
    """
    config = load_config()
    section = config.setdefault("folder", {})
    section["current"] = str(current or "")
    if recent is not None:
        section["recent"] = [str(p) for p in recent]
    save_config(config)
