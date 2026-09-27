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

        # Load last used folder from settings
        if settings.folder.current:
            path = Path(settings.folder.current)
            if path.exists() and path.is_dir():
                self._current_folder = path

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