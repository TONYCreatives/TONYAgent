"""Core application package.

``TONYAgentApp`` is intentionally NOT imported here. It pulls in customtkinter
and Tkinter, and importing it meant that *any* ``tonyagent.core.*`` import -
including the headless session and the sidecar server - dragged in a GUI
toolkit and made the core unusable without a display.

Import it explicitly where it is needed::

    from tonyagent.core.app import TONYAgentApp
"""

__all__ = ["TONYAgentApp"]


def __getattr__(name: str):
    """Lazily expose TONYAgentApp without importing Tkinter eagerly.

    Keeps ``from tonyagent.core import TONYAgentApp`` working for existing
    callers while leaving the headless path free of GUI dependencies.
    """
    if name == "TONYAgentApp":
        from tonyagent.core.app import TONYAgentApp

        return TONYAgentApp
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")