"""The desktop window, in Python.

The shell that used to be Rust. ``python -m tonyagent.window`` opens a native
window around the built frontend, starts the core as a child process, and
carries messages between them.

Imported for ``main`` alone, so the entry point is one name no matter how it is
reached -- the module, the launcher, or a frozen build.
"""

from tonyagent.window.host import main

__all__ = ["main"]
