"""Configuration migration utilities."""

from __future__ import annotations

import shutil
import tomli
import tomli_w
from pathlib import Path
from loguru import logger

from tonyagent.config.settings import settings


CURRENT_CONFIG_VERSION = 1


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

    return config


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


def reset_config() -> None:
    """Reset configuration to defaults."""
    config_path = get_config_path()
    if config_path.exists():
        config_path.unlink()
    logger.info("Configuration reset to defaults")