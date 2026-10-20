"""Docker-free sandbox runtime.

The *same* ``docker/sandbox/rpc_server.py`` the container runs, loaded into this
process instead of into a container. For most of the sandbox tools this is not
a downgrade at all: a headless browser and a read of a workspace file are not
shell escapes, and they behave identically with no daemon, no image build and
no container to pull.

What this backend deliberately does NOT provide is containment, and it says so
by leaving ``provides_isolation`` False. The two tools that can execute
arbitrary code -- ``execute_command`` and ``execute_js`` -- are gated on that
flag, so they keep requiring a real boundary instead of quietly running on the
user's machine. That split is the whole point of this module: it removes the
Docker requirement from the 13 tools that never needed it, without pretending
the remaining 2 are safe without it.

Dispatch is in-process rather than over a pipe. A subprocess would need a
second interpreter, and in the packaged sidecar ``sys.executable`` is the
PyInstaller binary itself, which does not run a script passed to it. Calling
``handle_request`` directly sidesteps that entirely while keeping the identical
handler code, so the container and the host still share one implementation.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, Optional

from loguru import logger

from tonyagent.folder import folder_manager
from tonyagent.sandbox.base import (
    SandboxBackend,
    SandboxConfig,
    SandboxStatus,
)


def _candidate_paths() -> list[Path]:
    """Every place the rpc_server module may live, best first.

    The packaged sidecar has no repository: PyInstaller unpacks bundled data
    into ``sys._MEIPASS``, so that is checked before the source tree, which only
    exists in a development checkout.
    """
    candidates: list[Path] = []
    override = os.environ.get("TONYAGENT_RPC_SERVER")
    if override:
        candidates.append(Path(override))
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(Path(meipass) / "tonyagent_sandbox" / "rpc_server.py")
    # src/tonyagent/sandbox/local_backend.py -> repo root is four levels up.
    candidates.append(
        Path(__file__).resolve().parents[3] / "docker" / "sandbox" / "rpc_server.py"
    )
    return candidates


def find_rpc_server() -> Path:
    """Locate rpc_server.py, or explain where it was looked for."""
    tried: list[str] = []
    for candidate in _candidate_paths():
        if candidate.is_file():
            return candidate
        tried.append(str(candidate))
    raise FileNotFoundError(
        "rpc_server.py not found. Looked in: " + ", ".join(tried) + ". "
        "Set TONYAGENT_RPC_SERVER to its path."
    )


def _load_rpc_server() -> ModuleType:
    """Import rpc_server.py under a private module name.

    Loaded by path rather than by import because it lives outside the package:
    it is a script the container runs, not a library the core imports.

    **The import path is checked after the load.** This module runs *inside
    the agent's process* on the local runtime, so anything it did to
    ``sys.path`` is an import-hijack primitive for the whole agent -- a
    project file named ``json.py`` would shadow the stdlib for every later
    import. It used to prepend the workspace there; that line is gone, and
    this check is what makes its reintroduction fail the runtime startup
    instead of quietly handing the agent's process to the project.
    """
    path = find_rpc_server()
    spec = importlib.util.spec_from_file_location("tonyagent_rpc_server", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {path}")
    module = importlib.util.module_from_spec(spec)
    # Registered before exec so a module that recurses (or that a traceback
    # formats) resolves by name instead of raising KeyError.
    sys.modules[spec.name] = module
    before = list(sys.path)
    spec.loader.exec_module(module)
    added = [entry for entry in sys.path if entry not in before]
    if added:
        raise RuntimeError(
            f"{path} modified sys.path ({added}); on the local runtime that "
            "runs inside the agent's own process, so it is refused."
        )
    return module


class LocalBackend(SandboxBackend):
    """Runs the sandbox RPC server in this process, with no container."""

    kind = "local"

    provides_isolation = False

    @property
    def has_network(self) -> bool:
        """Always True: the browser runs on the host and uses the host's network.

        The container default (``--network none``) exists to keep a compromised
        sandbox from reaching out. There is nothing to protect here, so the
        network gate that stops browser tools from failing obscurely must not
        apply to this runtime.
        """
        return True

    def __init__(self, config: SandboxConfig):
        super().__init__(config)
        self._module: Optional[ModuleType] = None
        self._workspace: Optional[Path] = None

    # -- lifecycle ---------------------------------------------------------
    def _resolve_workspace(self) -> Path:
        """The project folder, which becomes this runtime's /workspace."""
        project = self.config.project_path or str(folder_manager.current_folder or "")
        if not project:
            raise RuntimeError("No project folder selected")
        path = Path(project).resolve()
        if not path.is_dir():
            raise RuntimeError(f"Not a folder: {path}")
        return path

    async def start(self) -> bool:
        self.status = SandboxStatus.STARTING
        try:
            workspace = self._resolve_workspace()
            module = _load_rpc_server()
            # The module reads WORKSPACE at call time, so rebinding it here is
            # enough to repoint a running runtime at a new project folder --
            # no reload, and no window where the two disagree.
            module.WORKSPACE = workspace
            self._module = module
            self._workspace = workspace
            self.status = SandboxStatus.RUNNING
            logger.info(f"Local sandbox runtime ready (workspace: {workspace})")
            return True
        except Exception as exc:
            logger.error(f"Local sandbox runtime failed to start: {exc}")
            self._module = None
            self.status = SandboxStatus.STOPPED
            return False

    async def stop(self) -> None:
        self.status = SandboxStatus.STOPPING
        module, self._module = self._module, None
        if module is not None:
            # Release the headless browser and its driver. Without this every
            # folder change would strand a Chromium process for the session.
            try:
                await module.close_browser()
            except Exception as exc:
                logger.debug(f"Browser close during local stop failed: {exc}")
        self._workspace = None
        self.status = SandboxStatus.STOPPED

    async def health_check(self) -> bool:
        if self._module is None or self.status is not SandboxStatus.RUNNING:
            return False
        try:
            result = await self._module.ping()
            return bool(result.get("pong"))
        except Exception:
            return False

    # -- transport ---------------------------------------------------------
    async def _send_request(self, request: dict) -> None:
        """Hand the request to the in-process handler and feed back the reply.

        This is the only method that differs from the Docker backend, and it is
        deliberately the whole of it: framing, id correlation and timeouts all
        live in the base class and are therefore shared, not duplicated.
        """
        if self._module is None:
            raise RuntimeError("Local sandbox runtime is not loaded")
        response: dict[str, Any] = await self._module.handle_request(request)
        self._handle_response(response)

    # -- introspection -----------------------------------------------------
    @property
    def workspace(self) -> Optional[Path]:
        return self._workspace
