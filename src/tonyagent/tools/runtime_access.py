"""One place that answers "which backend serves this tool?".

These three helpers used to live in ``browser_tools.py``, with a second,
near-identical copy of one of them in ``sandbox_file_tools.py``. That is not a
style complaint: when the copies disagreed about the wording, ``execute_command``
told the user one thing and ``execute_js`` told them another about the same
cause, and the harness had to be special-cased to accept both. One home means
one message.

The distinction the helpers encode is the one from ``tonyagent.sandbox``: a
*runtime* can serve a tool that only needs to read a file or drive a browser,
while only an *isolating* backend may serve a tool that executes model-authored
code.
"""

from __future__ import annotations

from tonyagent.sandbox import get_shared_sandbox_manager
from tonyagent.sandbox.base import SandboxBackend, SandboxStatus

#: Shown whenever nothing is attached at all. One sentence, because it is the
#: single most common state in a fresh window and the fix is always the same.
NO_RUNTIME = (
    "The sandbox runtime is not running. Choose a project folder in Settings first."
)

#: Shown when a runtime exists but does not contain what the tool would run.
NEEDS_ISOLATION = (
    "This tool runs arbitrary code, so it needs an isolated sandbox and only "
    "the local runtime is available. Start Docker, then pick the project folder "
    "again."
)


def check_runtime(needs_network: bool = False, needs_isolation: bool = False) -> str | None:
    """Return None if a usable runtime exists, else an error string.

    ``needs_network`` is for the tools that genuinely load pages. The container
    runs with egress off by default, so without this they would fail deep
    inside Playwright with a DNS error instead of saying what to change; the
    local runtime uses the host network, so it is never gated.

    ``needs_isolation`` is for the tools that execute arbitrary code. They must
    refuse the local runtime rather than run on the user's machine.
    """
    backend = get_shared_sandbox_manager().get_runtime_backend()
    if backend is None:
        return NO_RUNTIME
    if needs_isolation and not getattr(backend, "provides_isolation", False):
        return NEEDS_ISOLATION
    if needs_network and not getattr(backend, "has_network", False):
        return (
            "Browser tools need network access, but the sandbox is running with "
            "--network none. Enable it in Settings > Sandbox > 'Allow network "
            "access', restart the sandbox, then try again."
        )
    return None


def running_backend() -> SandboxBackend:
    """The runtime for a tool that does not need containment, or raise."""
    backend = get_shared_sandbox_manager().get_runtime_backend()
    if backend is None:
        raise RuntimeError(NO_RUNTIME)
    return backend


def isolated_backend() -> SandboxBackend:
    """The runtime for a tool that must not run uncontained, or raise."""
    backend = get_shared_sandbox_manager().get_backend()
    if backend is None or backend.status is not SandboxStatus.RUNNING:
        raise RuntimeError(
            "This tool runs arbitrary code, so it needs an isolated sandbox. "
            "Start Docker and pick the project folder again."
        )
    if not getattr(backend, "provides_isolation", False):
        raise RuntimeError(NEEDS_ISOLATION)
    return backend
