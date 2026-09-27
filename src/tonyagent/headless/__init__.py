"""Headless entry points: run the agent core with no display attached.

This package is the Python side of the future Tauri frontend. It is also
usable on its own, which is how the core is tested without a GUI.
"""

from tonyagent.headless.server import PROTOCOL_VERSION, StdioServer, run

__all__ = ["StdioServer", "run", "PROTOCOL_VERSION"]
