"""Utilities package for TONYAgent."""

from tonyagent.utils.logging import setup_logging, get_logger, LogContext
from tonyagent.utils.threading import (
    get_thread_pool,
    set_ui_root,
    run_in_background,
    run_async,
    schedule_on_ui,
    process_ui_queue,
    start_ui_queue_processor,
    stop_ui_queue_processor,
    run_on_ui_thread,
    run_in_executor,
    AsyncTkinter,
    CancellationToken,
    shutdown_thread_pool,
)
from tonyagent.utils.paths import (
    get_project_root,
    normalize_path,
    is_safe_path,
    get_relative_path,
    ensure_directory,
    get_temp_dir,
    get_app_data_dir,
    get_cache_dir,
)

__all__ = [
    # Logging
    "setup_logging",
    "get_logger",
    "LogContext",
    # Threading
    "get_thread_pool",
    "set_ui_root",
    "run_in_background",
    "run_async",
    "schedule_on_ui",
    "process_ui_queue",
    "start_ui_queue_processor",
    "stop_ui_queue_processor",
    "run_on_ui_thread",
    "run_in_executor",
    "AsyncTkinter",
    "CancellationToken",
    "shutdown_thread_pool",
    # Paths
    "get_project_root",
    "normalize_path",
    "is_safe_path",
    "get_relative_path",
    "ensure_directory",
    "get_temp_dir",
    "get_app_data_dir",
    "get_cache_dir",
]