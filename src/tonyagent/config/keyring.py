"""Secure API key storage using OS keyring."""

from __future__ import annotations

import keyring
from loguru import logger

from tonyagent.api.client import normalize_key
from tonyagent.config.settings import settings


SERVICE_NAME = "TONYAgent"


class KeyringError(Exception):
    """Keyring operation failed."""

    pass


def _get_keyring_key(provider: str, field: str = "api_key") -> str:
    """Generate a keyring key for a provider field."""
    return f"{provider}:{field}"


def save_api_key(provider: str, api_key: str) -> None:
    """Save an API key to the system keyring.

    The value is normalised first. Storing the raw paste means a key that
    arrived with a trailing newline is stored *and* resent with that newline,
    which the provider rejects with a bare 401. Normalising at the boundary
    keeps what we store identical to what we send.
    """
    try:
        key = _get_keyring_key(provider)
        cleaned = normalize_key(api_key)
        if not cleaned:
            raise KeyringError(f"Refusing to save an empty key for {provider}")
        keyring.set_password(SERVICE_NAME, key, cleaned)
        logger.debug(f"Saved API key for provider: {provider}")
    except Exception as e:
        logger.error(f"Failed to save API key for {provider}: {e}")
        raise KeyringError(f"Failed to save API key: {e}") from e


def load_api_key(provider: str) -> str | None:
    """Load an API key from the system keyring."""
    try:
        key = _get_keyring_key(provider)
        api_key = keyring.get_password(SERVICE_NAME, key)
        if api_key:
            logger.debug(f"Loaded API key for provider: {provider}")
        return api_key
    except Exception as e:
        logger.warning(f"Failed to load API key for {provider}: {e}")
        return None


def delete_api_key(provider: str) -> None:
    """Delete an API key from the system keyring."""
    try:
        key = _get_keyring_key(provider)
        keyring.delete_password(SERVICE_NAME, key)
        logger.debug(f"Deleted API key for provider: {provider}")
    except keyring.errors.PasswordDeleteError:
        # Key doesn't exist, that's fine
        pass
    except Exception as e:
        logger.error(f"Failed to delete API key for {provider}: {e}")
        raise KeyringError(f"Failed to delete API key: {e}") from e


def save_custom_endpoint_key(api_key: str) -> None:
    """Save custom endpoint API key."""
    save_api_key("custom", api_key)


def load_custom_endpoint_key() -> str | None:
    """Load custom endpoint API key."""
    return load_api_key("custom")


def delete_custom_endpoint_key() -> None:
    """Delete custom endpoint API key."""
    delete_api_key("custom")


def get_all_stored_providers() -> list[str]:
    """Get list of providers with stored API keys."""
    # keyring doesn't have a list function, so we check known providers
    known_providers = [
        "openai",
        "anthropic",
        "gemini",
        "mistral",
        "groq",
        "openrouter",
        "ollama",
        "custom",
    ]
    stored = []
    for provider in known_providers:
        if load_api_key(provider):
            stored.append(provider)
    return stored


def migrate_from_config_file(config_path: str) -> int:
    """Migrate API keys from old config file to keyring."""
    import tomli

    migrated = 0
    try:
        with open(config_path, "rb") as f:
            config = tomli.load(f)
        providers = config.get("provider", {})
        for provider_name, provider_config in providers.items():
            if isinstance(provider_config, dict):
                api_key = provider_config.get("api_key", "")
                if api_key and not load_api_key(provider_name):
                    save_api_key(provider_name, api_key)
                    migrated += 1
                    logger.info(f"Migrated API key for {provider_name} to keyring")
    except FileNotFoundError:
        pass
    except Exception as e:
        logger.error(f"Failed to migrate keys from config: {e}")
    return migrated