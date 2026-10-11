"""Secure API key storage using OS keyring.

Named keys, and the one rule that makes them compatible with what is already
stored: the name "default" is the historical field, api_key. Everything else is
key:<slug>. There is no migration step, and there cannot be one -- a keyring
cannot be enumerated, so a rewrite would have to guess names it was never told.
Leaving "default" where it is means a key saved before names existed is still
the key a fresh install resolves to.
"""

from __future__ import annotations

import re

import keyring
from loguru import logger

from tonyagent.api.client import normalize_key


SERVICE_NAME = "TONYAgent"

#: The name a provider uses when the user did not give one. It is not just a
#: label: it selects the historical api_key field, which is why callers can talk
#: about "the default key" and existing keyrings keep working.
DEFAULT_KEY_NAME = "default"

#: What a name is allowed to become. Anything else becomes a dash, which is what
#: turns "Work Key" and "work key" into the same, listable identifier instead of
#: two rows that map to one keyring entry.
_SLUG_RE = re.compile(r"[^a-z0-9]+")


class KeyringError(Exception):
    """Keyring operation failed."""

    pass


def _get_keyring_key(provider: str, field: str = "api_key") -> str:
    """Generate a keyring key for a provider field."""
    return f"{provider}:{field}"


def normalize_key_name(name: str | None) -> str:
    """Canonicalise a user-facing key name into the registry's spelling.

    Lower-case and dash-separated because the name is also the panel's row
    label: two rows that were "Work Key" and "work-key" would be one keyring
    entry drawn twice, and neither the user nor key.delete could tell which.

    An empty name is the default rather than an error: key.save's name is
    optional, and "I did not name it" means the historical slot. A name made
    only of punctuation becomes an empty slug and is refused, because it would
    otherwise collide with the default field.
    """
    candidate = ("" if name is None else str(name)).strip()
    if not candidate or candidate.lower() == DEFAULT_KEY_NAME:
        return DEFAULT_KEY_NAME
    slug = _SLUG_RE.sub("-", candidate.lower()).strip("-")
    if not slug:
        raise KeyringError("a key name needs at least one letter or digit")
    return slug


def _key_field(name: str | None) -> str:
    """The keyring field for one name.

    "default" keeps the OLD field name on purpose. Renaming it to key:default
    would orphan every key already in a user's credential manager, and nothing
    can read those back out in bulk to re-save them.
    """
    resolved = normalize_key_name(name)
    return "api_key" if resolved == DEFAULT_KEY_NAME else f"key:{resolved}"


def active_key_name(provider: str) -> str:
    """Which stored name this provider's turns use.

    The registry is the only thing that knows, and an unreadable or absent
    config is not fatal: it answers "default", which is exactly what a provider
    with one unnamed key needs. Reading the file per call is accepted because it
    is one small file and load_api_key is already on the request path -- a cache
    here would be a cache that disagrees with an activation the user just made.
    """
    try:
        from tonyagent.config.migration import get_active_key_name

        return get_active_key_name(provider) or DEFAULT_KEY_NAME
    except Exception as exc:  # noqa: BLE001 - a missing name must not break a turn
        logger.warning(f"Could not read the active key name for {provider}: {exc}")
        return DEFAULT_KEY_NAME


def resolve_key_name(provider: str, name: str | None = None) -> str:
    """The concrete name a request refers to, active when none was given."""
    if name is None:
        return active_key_name(provider)
    return normalize_key_name(name)


def save_api_key(provider: str, api_key: str, name: str | None = None) -> None:
    """Save an API key to the system keyring under a name.

    The value is normalised first. Storing the raw paste means a key that
    arrived with a trailing newline is stored *and* resent with that newline,
    which the provider rejects with a bare 401. Normalising at the boundary
    keeps what we store identical to what we send.

    name is optional and means "default", matching key.save's contract; the
    two-argument call sites that predate names keep working unchanged.
    """
    try:
        resolved = normalize_key_name(name)
        key = _get_keyring_key(provider, _key_field(resolved))
        cleaned = normalize_key(api_key)
        if not cleaned:
            raise KeyringError(f"Refusing to save an empty key for {provider}")
        keyring.set_password(SERVICE_NAME, key, cleaned)
        logger.debug(f"Saved API key for provider: {provider} (name: {resolved})")
    except Exception as e:
        logger.error(f"Failed to save API key for {provider}: {e}")
        raise KeyringError(f"Failed to save API key: {e}") from e


def load_api_key(provider: str, name: str | None = None) -> str | None:
    """Load an API key from the system keyring.

    name=None resolves to the provider's active name, falling back to
    "default". That fallback is the whole backwards-compatibility story: every
    call site that predates this parameter passes no name, and the answer it
    gets is the key it always got, unless the user has explicitly activated
    another one.
    """
    try:
        resolved = resolve_key_name(provider, name)
        key = _get_keyring_key(provider, _key_field(resolved))
        api_key = keyring.get_password(SERVICE_NAME, key)
        if api_key:
            logger.debug(f"Loaded API key for provider: {provider} (name: {resolved})")
        return api_key
    except Exception as e:
        logger.warning(f"Failed to load API key for {provider}: {e}")
        return None


def delete_api_key(provider: str, name: str | None = None) -> None:
    """Delete one named API key from the system keyring.

    Like save_api_key, a missing name means "default" rather than "the active
    one": key.delete names the key it is deleting, and a delete that silently
    followed the active pointer could remove a key the user did not point at.
    """
    try:
        resolved = normalize_key_name(name)
        key = _get_keyring_key(provider, _key_field(resolved))
        keyring.delete_password(SERVICE_NAME, key)
        logger.debug(f"Deleted API key for provider: {provider} (name: {resolved})")
    except keyring.errors.PasswordDeleteError:
        # Key doesn't exist, that's fine
        pass
    except Exception as e:
        logger.error(f"Failed to delete API key for {provider}: {e}")
        raise KeyringError(f"Failed to delete API key: {e}") from e


def stored_key_names(provider: str) -> list[str]:
    """Every name the provider has a key under, default first.

    The names the user typed come from the config registry, because the keyring
    has no list operation. "default" is the exception: it predates the registry,
    so a key saved before names existed would otherwise be invisible here -- and
    an invisible key is one the user cannot delete and the panel would claim is
    not there.

    The default probe reads the field directly rather than through
    load_api_key(provider), which would resolve to the active name and answer
    "is the active key stored", not "is there a default key".
    """
    names: list[str] = []
    try:
        from tonyagent.config.migration import load_key_names

        names = list(load_key_names(provider))
    except Exception as exc:  # noqa: BLE001 - an unreadable registry is "no names"
        logger.warning(f"Could not read the key registry for {provider}: {exc}")

    if DEFAULT_KEY_NAME not in names and load_api_key(provider, DEFAULT_KEY_NAME):
        names.insert(0, DEFAULT_KEY_NAME)
    return names


def get_all_stored_providers() -> list[str]:
    """Providers that have at least one API key in the keyring.

    The keyring has no list operation, so this asks about each provider that
    exists. It reads the registry rather than repeating the names, because a
    hardcoded list here is a list that goes stale the moment a provider lands.

    "At least one" rather than "the active one loads": a provider with a
    registered but not-yet-activated key is still a provider with a key, and
    reporting otherwise would hide the row the user just added.
    """
    from tonyagent.providers.base import provider_registry

    return [name for name in provider_registry.list_providers() if stored_key_names(name)]


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
                # The old file only ever held one key per provider, and that
                # key is the default slot. Asking load_api_key() here without a
                # name would ask about the ACTIVE key instead, so an activated
                # named key would make this think a default already existed and
                # skip the import.
                if api_key and not load_api_key(provider_name, DEFAULT_KEY_NAME):
                    save_api_key(provider_name, api_key)
                    migrated += 1
                    logger.info(f"Migrated API key for {provider_name} to keyring")
    except FileNotFoundError:
        pass
    except Exception as e:
        logger.error(f"Failed to migrate keys from config: {e}")
    return migrated
