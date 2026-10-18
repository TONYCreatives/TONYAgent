"""Logging configuration for TONYAgent."""

from __future__ import annotations

import sys
from pathlib import Path
from loguru import logger

from tonyagent.config.settings import settings


def setup_logging(*, colorize: bool = True) -> None:
    """Configure application logging.

    **Called by the core, which is the process whose failures need a file.** It
    used to be exported and called by nothing at all: the host has its own
    ``window.log`` for startup failures, and the core's stderr goes to the app's
    log strip, which is a strip in a window rather than something to read after
    the fact. So a keyring warning, a provider error or a turn that died left
    nothing on disk -- and diagnosing the keyring problem this release fixes
    took a temporary probe and two rebuilds for exactly that reason.

    ``colorize`` is off for the core. Its stderr is a pipe the app reads, not a
    terminal, so ANSI codes would arrive in the log strip as literal escapes.
    """
    # Remove default handler
    logger.remove()

    # Console handler with colors
    log_level = settings.logging.level
    logger.add(
        sys.stderr,
        level=log_level,
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
            "<level>{message}</level>"
        ),
        colorize=colorize,
        backtrace=True,
        diagnose=True,
    )

    # File handler with rotation
    log_dir = settings.get_logs_dir()
    log_file = log_dir / "tonyagent_{time:YYYY-MM-DD}.log"

    logger.add(
        log_file,
        level=log_level,
        format=(
            "{time:YYYY-MM-DD HH:mm:ss.SSS} | "
            "{level: <8} | "
            "{name}:{function}:{line} | "
            "{message}"
        ),
        rotation=f"{settings.logging.file_max_mb} MB",
        retention=f"{settings.logging.file_count} days",
        compression="zip",
        backtrace=True,
        diagnose=True,
    )

    # JSONL handler for structured logging (optional)
    if settings.logging.json_format:
        json_log = log_dir / "tonyagent_{time:YYYY-MM-DD}.jsonl"
        logger.add(
            json_log,
            level=log_level,
            format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level} | {name} | {message}",
            serialize=True,
            rotation=f"{settings.logging.file_max_mb} MB",
            retention=f"{settings.logging.file_count} days",
            compression="zip",
        )

    logger.info("Logging initialized")


def get_logger(name: str):
    """Get a logger instance with the given name."""
    return logger.bind(name=name)


class LogContext:
    """Context manager for adding contextual information to logs."""

    def __init__(self, **kwargs):
        self.context = kwargs
        self.token = None

    def __enter__(self):
        self.token = logger.contextualize(**self.context)
        self.token.__enter__()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.token:
            self.token.__exit__(exc_type, exc_val, exc_tb)