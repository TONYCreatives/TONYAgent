"""Folder management for TONYAgent."""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Callable
from threading import Lock

from loguru import logger

from tonyagent.config.settings import settings


class FolderManager:
    """Manages the current working folder and locking state."""

    def __init__(self):
        self._current_folder: Optional[Path] = None
        self._locked: bool = False
        self._lock_reason: str = ""
        self._lock_callbacks: list[Callable[[bool, str], None]] = []
        self._lock = Lock()

        restored = self._restored_folder()
        if restored:
            path = Path(restored)
            if path.exists() and path.is_dir():
                self._current_folder = path
            else:
                # Worth saying out loud. A folder that has been moved or renamed
                # leaves the tools with no workspace at all, and every one of
                # them answers "No project folder selected" -- which reads as
                # "you never picked one" rather than "the one you picked is
                # gone". The recent list still has it, and the user can re-pick.
                logger.warning(
                    f"The last project folder is no longer there: {restored}"
                )

    @staticmethod
    def _restored_folder() -> str:
        """The last chosen folder, from wherever it was actually written.

        **The config file is the source of truth, not `settings`.**
        `settings.folder.current` is only ever assigned by `set_folder`, which
        updates this process and nothing else -- nothing loads config.toml into
        the settings model. So reading it here returned "" on every launch and
        the restore never once worked, however many times the user picked a
        folder.

        Reading the file directly is what the sidecar already does for the saved
        provider (`headless/server.py`), for the same reason: the sidecar never
        populates `settings` from disk. A folder chosen last week survived a
        restart in the config file and was still ignored.

        The model is consulted as well, because the Tkinter path populates it,
        and either source agreeing is harmless.
        """
        if settings.folder.current:
            return settings.folder.current
        try:
            from tonyagent.config.migration import load_config

            section = load_config().get("folder") or {}
            return str(section.get("current") or "").strip()
        except Exception as exc:  # noqa: BLE001 - no config is not an error
            logger.warning(f"Could not read the saved project folder: {exc}")
            return ""

    @property
    def current_folder(self) -> Optional[Path]:
        """Get the current folder."""
        return self._current_folder

    @property
    def is_locked(self) -> bool:
        """Check if folder is locked."""
        return self._locked

    @property
    def lock_reason(self) -> str:
        """Get the lock reason."""
        return self._lock_reason

    def set_folder(self, path: Path) -> bool:
        """Set the current folder."""
        with self._lock:
            if self._locked:
                logger.warning("Cannot change folder while locked")
                return False

            path = path.resolve()
            if not path.exists() or not path.is_dir():
                logger.error(f"Invalid folder: {path}")
                return False

            self._current_folder = path
            self._update_recent_folders(path)
            settings.folder.current = str(path)
            # Written to disk as well as to the model. Assigning to `settings`
            # only updates this process: nothing writes config.toml on attribute
            # assignment, so without this the choice worked for the session and
            # then evaporated on the next launch. What the user saw after that
            # was the worst version of it -- the sidebar still showed the
            # project, because a conversation records its own `project` on disk,
            # while every tool answered "No project folder selected", because the
            # folder itself came back empty.
            #
            # Best-effort, and deliberately not fatal: a read-only config file
            # must not stop the user working in the folder they just opened.
            # The choice holds for this session either way.
            try:
                from tonyagent.config.migration import save_folder

                save_folder(str(path), settings.folder.recent)
            except Exception as exc:  # noqa: BLE001 - the folder still works
                logger.warning(f"Could not remember the chosen folder: {exc}")
            logger.info(f"Set current folder: {path}")
            return True

    def _update_recent_folders(self, path: Path) -> None:
        """Update the recent folders list."""
        recent = settings.folder.recent
        path_str = str(path)

        if path_str in recent:
            recent.remove(path_str)

        recent.insert(0, path_str)
        settings.folder.recent = recent[: settings.folder.max_recent]

    def lock(self, reason: str = "AI generation in progress") -> None:
        """Lock the folder picker."""
        with self._lock:
            if self._locked:
                logger.warning(f"Folder already locked: {self._lock_reason}")
                return

            self._locked = True
            self._lock_reason = reason
            logger.info(f"Folder locked: {reason}")
            self._notify_lock_change()

    def unlock(self) -> None:
        """Unlock the folder picker."""
        with self._lock:
            if not self._locked:
                return

            self._locked = False
            self._lock_reason = ""
            logger.info("Folder unlocked")
            self._notify_lock_change()

    def register_lock_callback(self, callback: Callable[[bool, str], None]) -> None:
        """Register a callback for lock state changes."""
        if callback not in self._lock_callbacks:
            self._lock_callbacks.append(callback)

    def unregister_lock_callback(self, callback: Callable[[bool, str], None]) -> None:
        """Unregister a lock callback."""
        if callback in self._lock_callbacks:
            self._lock_callbacks.remove(callback)

    def _notify_lock_change(self) -> None:
        """Notify all callbacks of lock state change."""
        for callback in self._lock_callbacks:
            try:
                callback(self._locked, self._lock_reason)
            except Exception as e:
                logger.error(f"Lock callback error: {e}")

    def get_recent_folders(self) -> list[Path]:
        """Get list of recent folders."""
        return [Path(p) for p in settings.folder.recent if Path(p).exists()]

    def clear_recent_folders(self) -> None:
        """Clear recent folders list."""
        settings.folder.recent = []


# Global folder manager instance
folder_manager = FolderManager()