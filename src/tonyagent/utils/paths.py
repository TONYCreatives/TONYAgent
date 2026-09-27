"""Path utilities for TONYAgent."""

from __future__ import annotations

import os
from pathlib import Path


def get_project_root() -> Path:
    """Get the project root directory."""
    # Check for marker file
    current = Path.cwd()
    for parent in [current] + list(current.parents):
        if (parent / ".tonyagent").exists() or (parent / "pyproject.toml").exists():
            return parent
    return current


def normalize_path(path: str | Path, base: Path | None = None) -> Path:
    """Normalize a path, resolving relative components."""
    base = base or Path.cwd()
    if isinstance(path, str):
        path = Path(path)
    if not path.is_absolute():
        path = base / path
    return path.resolve()


def is_safe_path(path: Path, base: Path) -> bool:
    """Check if a path is within the base directory (no traversal)."""
    try:
        path.resolve().relative_to(base.resolve())
        return True
    except ValueError:
        return False


def get_relative_path(path: Path, base: Path) -> Path:
    """Get relative path from base, raising if not within base."""
    if not is_safe_path(path, base):
        raise ValueError(f"Path {path} is not within {base}")
    return path.resolve().relative_to(base.resolve())


def ensure_directory(path: Path) -> Path:
    """Ensure a directory exists."""
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_temp_dir() -> Path:
    """Get a temporary directory for the application."""
    import tempfile
    temp_dir = Path(tempfile.gettempdir()) / "tonyagent"
    temp_dir.mkdir(parents=True, exist_ok=True)
    return temp_dir


def get_app_data_dir() -> Path:
    """Get the application data directory."""
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", "")) / "TONYAgent"
    else:
        base = Path.home() / ".local" / "share" / "tonyagent"
    base.mkdir(parents=True, exist_ok=True)
    return base


def get_cache_dir() -> Path:
    """Get the cache directory."""
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", "")) / "TONYAgent" / "Cache"
    else:
        base = Path.home() / ".cache" / "tonyagent"
    base.mkdir(parents=True, exist_ok=True)
    return base