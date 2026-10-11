"""Sandbox package for TONYAgent."""

from tonyagent.sandbox.base import (
    SandboxBackend,
    SandboxConfig,
    SandboxStatus,
    CommandResult,
    BrowserResult,
    SandboxManager,
)
from tonyagent.sandbox.docker_backend import DockerSandboxBackend
from tonyagent.sandbox.local_backend import LocalBackend
from tonyagent.sandbox.wsb_backend import WsbSandboxBackend
from tonyagent.sandbox.wsl_backend import WslSandboxBackend, detect_wsl_distro

__all__ = [
    "SandboxBackend",
    "SandboxConfig",
    "SandboxStatus",
    "CommandResult",
    "BrowserResult",
    "SandboxManager",
    "DockerSandboxBackend",
    "LocalBackend",
    "WsbSandboxBackend",
    "WslSandboxBackend",
    "detect_wsl_distro",
    "shared_sandbox_manager",
    "get_shared_sandbox_manager",
]

# One shared manager so the UI (which starts/stops the sandbox) and the tools
# (which execute inside it) always see the same backend. Without this, tools
# create their own SandboxManager and can never find the running sandbox.
_shared_sandbox_manager = SandboxManager()


def get_shared_sandbox_manager() -> SandboxManager:
    """Return the process-wide shared SandboxManager."""
    return _shared_sandbox_manager


# Backwards-compat alias for ``from tonyagent.sandbox import shared_sandbox_manager``.
shared_sandbox_manager = _shared_sandbox_manager
