"""Threading and async utilities."""

from __future__ import annotations

import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor, Future
from contextvars import ContextVar
from typing import Any, Callable, TypeVar, Coroutine
from functools import wraps

from loguru import logger

# Global thread pool for background tasks
_thread_pool: ThreadPoolExecutor | None = None

# Context variable for correlation IDs
correlation_id_var: ContextVar[str | None] = ContextVar("correlation_id", default=None)


def get_thread_pool() -> ThreadPoolExecutor:
    """Get or create the global thread pool."""
    global _thread_pool
    if _thread_pool is None or _thread_pool._shutdown:
        _thread_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="tonyagent-")
    return _thread_pool


def run_in_background(func: Callable[..., Any], *args, **kwargs) -> Future:
    """Run a function in the background thread pool."""
    pool = get_thread_pool()
    return pool.submit(func, *args, **kwargs)


def run_async(coro: Coroutine[Any, Any, Any]) -> Future:
    """Run an async coroutine in the background thread pool."""
    def _run_coro():
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    return run_in_background(_run_coro)


def schedule_on_ui(func: Callable[..., Any], *args, **kwargs) -> None:
    """Run a callback immediately.

    The Tauri frontend communicates over stdio, so there is no UI thread to
    marshal onto. Callbacks run directly.
    """
    func(*args, **kwargs)


def run_on_ui_thread(func: Callable[..., Any]) -> Callable[..., Any]:
    """Decorator to run a function on the UI thread."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        if threading.current_thread() is threading.main_thread():
            return func(*args, **kwargs)
        else:
            future = asyncio.Future()
            def _run():
                try:
                    result = func(*args, **kwargs)
                    schedule_on_ui(future.set_result, result)
                except Exception as e:
                    schedule_on_ui(future.set_exception, e)
            run_in_background(_run)
            return future
    return wrapper


T = TypeVar("T")


async def run_in_executor(func: Callable[..., T], *args, **kwargs) -> T:
    """Run a blocking function in the thread pool."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(get_thread_pool(), lambda: func(*args, **kwargs))


class CancellationToken:
    """Token for cooperative cancellation."""

    def __init__(self):
        self._event = threading.Event()
        self._callbacks: list[Callable[[], None]] = []

    def cancel(self) -> None:
        """Signal cancellation."""
        self._event.set()
        for cb in self._callbacks:
            try:
                cb()
            except Exception:
                logger.exception("Cancellation callback failed")

    def is_cancelled(self) -> bool:
        """Check if cancellation was requested."""
        return self._event.is_set()

    def add_callback(self, callback: Callable[[], None]) -> None:
        """Add a callback to be called on cancellation."""
        self._callbacks.append(callback)

    def remove_callback(self, callback: Callable[[], None]) -> None:
        """Remove a cancellation callback."""
        if callback in self._callbacks:
            self._callbacks.remove(callback)

    def throw_if_cancelled(self) -> None:
        """Raise CancelledError if cancelled."""
        if self.is_cancelled():
            raise asyncio.CancelledError("Operation cancelled")

    async def wait_async(self) -> None:
        """Wait for cancellation asynchronously."""
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._event.wait)


def shutdown_thread_pool() -> None:
    """Shutdown the global thread pool."""
    global _thread_pool
    if _thread_pool:
        _thread_pool.shutdown(wait=True)
        _thread_pool = None