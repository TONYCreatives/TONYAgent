"""The shell's own preferences: a JSON file beside ``config.toml``.

The core has settings of its own -- provider, model, permissions -- and they are
the core's business. This is the other half: what the *window* remembers about
itself across restarts, which is not something the core has any opinion about. Put
them together and the shell would be writing into the core's config file, and the
next core migration would have to know about the pet.

**One file rather than one per setting**, so there is one place to look and one
lock to take, and so a preference that is added later cannot end up in a second
file with a second set of failure modes.

**A missing or broken file is not an error.** Every read is a default, and a
write that cannot land is logged and otherwise ignored: a pet that failed to
remember itself is a pet that is not where it was, which is a long way from a
window that will not open.
"""

from __future__ import annotations

import json
import threading
from typing import Any

from loguru import logger

#: Guards read-modify-write. The window's worker threads can each ask for a
#: different preference at the same moment, and a lost update here is a setting
#: that silently reverts on the next launch.
_LOCK = threading.Lock()

FILENAME = "window.json"


def _path() -> Any:
    from tonyagent.config.settings import settings

    return settings.get_config_dir() / FILENAME


def get(name: str, default: Any = None) -> Any:
    """The stored value, or `default` when there is nothing readable."""
    try:
        path = _path()
        if not path.is_file():
            return default
        return json.loads(path.read_text(encoding="utf-8")).get(name, default)
    except Exception as exc:  # noqa: BLE001 - see the module docstring
        logger.debug(f"Could not read the window preferences: {exc}")
        return default


def set(name: str, value: Any) -> bool:  # noqa: A001 - `set` reads as the noun here
    """Store one value, keeping the others. Returns whether it landed."""
    try:
        with _LOCK:
            path = _path()
            current: dict[str, Any] = {}
            if path.is_file():
                try:
                    current = json.loads(path.read_text(encoding="utf-8"))
                except ValueError:
                    # A file we cannot parse is replaced rather than refused: the
                    # alternative is a preference that can never be set again.
                    current = {}
            current[name] = value
            path.write_text(json.dumps(current, indent=2), encoding="utf-8")
        return True
    except Exception as exc:  # noqa: BLE001 - see the module docstring
        logger.warning(f"Could not save the window preference {name!r}: {exc}")
        return False
