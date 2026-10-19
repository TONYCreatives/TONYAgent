"""Sandbox base classes and protocol for TONYAgent."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Optional
import asyncio
import subprocess

from tonyagent.folder import folder_manager


#: Suppress a child's console window.
#:
#: **The core is a windowed process, so its console children get windows of
#: their own.** The core runs as a child of the host's GUI process and is built
#: for the window subsystem, so it has no console to inherit. Windows answers
#: that by giving every console program it spawns a *new* console, which it
#: opens as a window and closes when the child exits. The user sees a black
#: rectangle appear and vanish, once per spawn.
#:
#: A folder change spawns several before a sandbox is up. The distro probe, the
#: host-to-distro path translation, the RPC server staging, the server itself, a
#: capability probe and the teardown are seven ``wsl.exe`` runs, and Windows puts
#: *two* windows on screen for each one -- Windows Terminal's and the console
#: host's -- so a single folder change was measured at fourteen shown windows,
#: appearing and vanishing over about eight seconds. That is the "cmd window
#: appears and closes several times" on the project-folder picker, and it is also
#: why the picker looked like it did nothing: the flashes were the only sign of
#: work.
#:
#: The host's own two spawns already asked for this (`window/core.py`,
#: `window/update.py`); the sandbox did not. A spawn in this package that omits
#: it is a regression -- `tests/unit/test_frozen_bundle.py` walks the package
#: and fails on one.
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class SandboxStatus(str, Enum):
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    UNHEALTHY = "unhealthy"
    STOPPING = "stopping"


@dataclass
class SandboxConfig:
    type: str = "auto"
    docker_image: str = "tonyagent/sandbox:latest"
    memory_limit: str = "2g"
    cpu_limit: str = "2.0"
    timeout: int = 300
    enable_network: bool = False
    project_path: str = ""
    working_dir: str = "/workspace"

    # --- Container isolation. Defaults mirror SandboxSettings (restrictive) ---
    pids_limit: int = 512
    no_new_privileges: bool = True
    drop_capabilities: bool = True
    tmpfs_size_mb: int = 256
    ulimit_nofile: int = 1024
    ulimit_nproc: int = 256
    workspace_read_only: bool = False
    #: See ``SandboxSettings.container_user``. Empty is the image default
    #: (root); on POSIX hosts the docker backend fills in the project owner.
    container_user: str = ""
    #: Named WSL distro for the WSL backend; empty means the default distro
    #: from ``wsl -l -v`` (skipping Docker Desktop's).
    wsl_distro: str = ""


@dataclass
class CommandResult:
    stdout: str
    stderr: str
    returncode: int
    duration_ms: float = 0.0


@dataclass
class BrowserResult:
    success: bool
    data: Any = None
    error: str | None = None
class SandboxBackend(ABC):
    #: Whether this backend actually *contains* what runs inside it.
    #:
    #: This is the distinction the whole module turns on, and conflating it
    #: with "is there a sandbox" is what made Docker look mandatory. A local
    #: subprocess is a perfectly good runtime for a headless browser or for a
    #: read of a workspace file -- neither of those is a shell escape. It is
    #: NOT a boundary for code that can execute arbitrary commands, so the
    #: tools that can are gated on this flag rather than on mere liveness.
    provides_isolation: bool = False

    @property
    def has_network(self) -> bool:
        """Whether this backend can reach the network.

        Asked rather than inferred from ``provides_isolation``: a container can
        be isolated *and* offline (``--network none``), and the local runtime is
        the reverse. Deriving one from the other would block the browser tools
        on the runtime that can actually load a page.
        """
        return bool(getattr(self.config, "enable_network", False))

    def __init__(self, config: SandboxConfig):
        self.config = config
        self.status = SandboxStatus.STOPPED
        self._process: Optional[asyncio.subprocess.Process] = None
        self._request_id = 0
        self._pending: dict[int, asyncio.Future] = {}

    @abstractmethod
    async def start(self) -> bool:
        pass

    @abstractmethod
    async def stop(self) -> None:
        pass

    @abstractmethod
    async def health_check(self) -> bool:
        pass

    async def ping(self, timeout: int = 10) -> dict[str, Any]:
        """Liveness probe. Allowed while STARTING; used for readiness."""
        result = await self._rpc_call("ping", {}, timeout=timeout)
        if not isinstance(result, dict):
            raise RuntimeError(f"Bad ping response: {result!r}")
        return result

    async def execute_command(self, command: str, cwd: str = "/workspace", timeout: int = 30) -> CommandResult:
        data = await self._rpc_call("exec_command", {"command": command, "cwd": cwd, "timeout": timeout})
        if isinstance(data, CommandResult):
            return data
        if not isinstance(data, dict):
            raise RuntimeError(f"Bad exec_command response: {data!r}")
        return CommandResult(
            stdout=str(data.get("stdout", "")),
            stderr=str(data.get("stderr", "")),
            returncode=int(data.get("returncode", -1)),
        )

    async def browser_navigate(self, url: str) -> BrowserResult:
        return self._to_browser_result(await self._rpc_call("browser_navigate", {"url": url}))

    async def browser_click(self, selector: str) -> BrowserResult:
        return self._to_browser_result(await self._rpc_call("browser_click", {"selector": selector}))

    async def browser_type(self, selector: str, text: str) -> BrowserResult:
        return self._to_browser_result(await self._rpc_call("browser_type", {"selector": selector, "text": text}))

    async def browser_eval(self, script: str) -> BrowserResult:
        return self._to_browser_result(await self._rpc_call("browser_eval", {"script": script}))

    async def browser_snapshot(self, interactive_only: bool = True, max_elements: int = 100) -> BrowserResult:
        """Text description of the page (ARIA tree + actionable elements)."""
        return self._to_browser_result(
            await self._rpc_call(
                "browser_snapshot",
                {"interactive_only": interactive_only, "max_elements": max_elements},
            )
        )

    async def set_viewport_size(self, width: int, height: int, reset: bool = False) -> BrowserResult:
        """Resize the browser viewport (responsive testing)."""
        return self._to_browser_result(
            await self._rpc_call(
                "set_viewport_size", {"width": width, "height": height, "reset": reset}
            )
        )

    async def browser_get_text(self, selector: str = "", max_chars: int = 20000) -> BrowserResult:
        """Read visible page text, optionally scoped to a CSS selector."""
        return self._to_browser_result(
            await self._rpc_call("browser_get_text", {"selector": selector, "max_chars": max_chars})
        )

    async def browser_wait_for(
        self, selector: str = "", state: str = "visible", timeout: int = 10000
    ) -> BrowserResult:
        """Wait for a selector state, or for the page load state."""
        return self._to_browser_result(
            await self._rpc_call(
                "browser_wait_for", {"selector": selector, "state": state, "timeout": timeout}
            )
        )

    async def browser_scroll(
        self, direction: str = "down", amount: int = 800, selector: str = ""
    ) -> BrowserResult:
        """Scroll the page (or an element) by a pixel amount."""
        return self._to_browser_result(
            await self._rpc_call(
                "browser_scroll", {"direction": direction, "amount": amount, "selector": selector}
            )
        )

    async def browser_screenshot(self, path: str = "") -> BrowserResult:
        return self._to_browser_result(await self._rpc_call("browser_screenshot", {"path": path}))

    async def execute_js(self, script: str, timeout: int = 10) -> BrowserResult:
        return self._to_browser_result(
            await self._rpc_call("execute_js", {"script": script, "timeout": timeout})
        )

    async def read_file(self, path: str, max_bytes: int = 1048576) -> BrowserResult:
        """Read a workspace file from inside the container (read-only)."""
        return self._to_browser_result(
            await self._rpc_call("read_file", {"path": path, "max_bytes": max_bytes})
        )

    async def list_files(self, path: str = ".", max_depth: int = 3) -> BrowserResult:
        """List a workspace directory from inside the container (read-only)."""
        return self._to_browser_result(
            await self._rpc_call("list_files", {"path": path, "max_depth": max_depth})
        )

    @staticmethod
    def _to_browser_result(data: Any) -> BrowserResult:
        if isinstance(data, BrowserResult):
            return data
        if not isinstance(data, dict):
            raise RuntimeError(f"Bad browser response: {data!r}")
        return BrowserResult(
            success=bool(data.get("success", False)),
            data=data.get("data"),
            error=data.get("error"),
        )

    async def _rpc_call(self, method: str, params: dict, timeout: int | None = None) -> Any:
        if self.status not in (SandboxStatus.RUNNING, SandboxStatus.STARTING):
            raise RuntimeError(f"Sandbox not running (status: {self.status})")

        self._request_id += 1
        request_id = self._request_id

        future = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future

        request = {"jsonrpc": "2.0", "method": method, "params": params, "id": request_id}

        await self._send_request(request)

        wait_timeout = timeout if timeout is not None else params.get("timeout", 30) + 5
        try:
            response = await asyncio.wait_for(future, timeout=wait_timeout)
            return response
        except asyncio.TimeoutError:
            self._pending.pop(request_id, None)
            raise RuntimeError(f"RPC call {method} timed out")

    @abstractmethod
    async def _send_request(self, request: dict) -> None:
        pass

    def _handle_response(self, response: dict) -> None:
        request_id = response.get("id")
        if request_id in self._pending:
            future = self._pending.pop(request_id)
            if "error" in response:
                future.set_exception(RuntimeError(response["error"].get("message", "Unknown error")))
            else:
                future.set_result(response.get("result"))

    def _handle_notification(self, notification: dict) -> None:
        pass


class SandboxManager:
    def __init__(self):
        self._backend: Optional[SandboxBackend] = None
        self._config: Optional[SandboxConfig] = None
        self._local: Optional[SandboxBackend] = None

    async def start(self, config: SandboxConfig) -> bool:
        """Start the local runtime, then the isolating backend if one is asked for.

        Returns True when a *runtime* is available, which is deliberately a
        weaker promise than "a container is running". The browser and
        read-only file tools need the former; only the two code-execution tools
        need the latter, and they check ``provides_isolation`` themselves. So a
        machine with no Docker daemon still gets a working agent, and the
        difference is reported rather than thrown away.
        """
        self._config = config

        local_ok = await self.ensure_local(config)

        if config.type == "auto":
            config.type = await self._detect_backend()

        if config.type == "docker":
            from tonyagent.sandbox.docker_backend import DockerSandboxBackend
            self._backend = DockerSandboxBackend(config)
        elif config.type == "wsl":
            from tonyagent.sandbox.wsl_backend import WslSandboxBackend
            self._backend = WslSandboxBackend(config, distro=config.wsl_distro)
        elif config.type == "windows":
            from tonyagent.sandbox.wsb_backend import WsbSandboxBackend
            self._backend = WsbSandboxBackend(config)
        elif config.type == "local":
            # Explicitly asking for no isolation: the local runtime is it.
            self._backend = None
            return local_ok
        else:
            raise ValueError(f"Unknown sandbox type: {config.type}")

        success = await self._backend.start()
        if success:
            self._backend.status = SandboxStatus.RUNNING
        # Isolation is an upgrade, not a precondition.
        return bool(success or local_ok)

    async def ensure_local(self, config: Optional[SandboxConfig] = None) -> bool:
        """Start (or re-point) the Docker-free runtime. Cheap and synchronous-ish.

        Safe to call repeatedly: an already-running runtime bound to the same
        project folder is left alone, so the tools can ask for it without
        paying for a reload.
        """
        from tonyagent.sandbox.local_backend import LocalBackend

        cfg = config or self._config or SandboxConfig()
        if self._local is not None and self._local.status is SandboxStatus.RUNNING:
            current = getattr(self._local, "workspace", None)
            target = cfg.project_path or str(folder_manager.current_folder or "")
            if not target or (current is not None and Path(target).resolve() == current):
                return True
            await self._local.stop()
            self._local = None

        backend = LocalBackend(cfg)
        if not await backend.start():
            self._local = None
            return False
        self._local = backend
        return True

    async def stop(self) -> None:
        if self._backend:
            await self._backend.stop()
            self._backend = None
        if self._local is not None:
            await self._local.stop()
            self._local = None

    async def health_check(self) -> bool:
        if not self._backend:
            return False
        return await self._backend.health_check()

    def get_backend(self) -> Optional[SandboxBackend]:
        """The *isolating* backend, or None. Unchanged meaning, on purpose.

        Callers that only need a runtime should use ``get_runtime_backend``;
        keeping the two apart is what stops a tool from picking up a
        non-isolating backend by accident.
        """
        return self._backend

    def get_local_backend(self) -> Optional[SandboxBackend]:
        """The Docker-free runtime, or None if it could not start."""
        return self._local

    def get_runtime_backend(self) -> Optional[SandboxBackend]:
        """The best RUNNING backend for a tool that does not need isolation.

        Prefers the container when it is up, so turning Docker on is still an
        upgrade rather than a change of which code runs.
        """
        if self._backend is not None and self._backend.status is SandboxStatus.RUNNING:
            return self._backend
        if self._local is not None and self._local.status is SandboxStatus.RUNNING:
            return self._local
        return None

    def is_isolated(self) -> bool:
        """True when code the agent generates is actually contained."""
        return (
            self._backend is not None
            and self._backend.status is SandboxStatus.RUNNING
            and self._backend.provides_isolation
        )

    def is_running(self) -> bool:
        """True when any runtime is available, isolated or not."""
        return self.get_runtime_backend() is not None

    @staticmethod
    async def _detect_backend() -> str:
        """Pick an isolating backend, or say plainly that there is not one.

        The order is the preference, and it is not arbitrary:

        1. **docker** -- the strongest containment available (cgroup limits,
           nothing mounted but the workspace), chosen when a daemon actually
           answers.
        2. **wsl** -- the Docker-free answer: a real kernel boundary from a
           WSL2 distro, which every modern Windows install has and nothing
           has to start. Probed for ``wsl.exe`` *and* a user distro, because
           a probe that accepted Docker Desktop's helper distro would "find
           an environment" that cannot start a shell.
        3. **windows** -- Windows Sandbox, when it is installed and enabled.
           The DISM probe for the optional feature needs an elevated shell:
           without one it returns error 740, so a normal user can never get
           "windows" here even on a machine that has it.

        "local" is still a working answer when there is no containing
        backend: the browser and read-only file tools run on it, and only
        the two code-execution tools are refused. Failing here instead would
        take all 22 away.
        """
        try:
            import docker
            client = docker.from_env()
            client.ping()
            return "docker"
        except Exception:
            pass

        try:
            from tonyagent.sandbox.wsl_backend import (
                detect_wsl_distro,
                wsl_available,
            )

            if wsl_available() and detect_wsl_distro():
                return "wsl"
        except Exception:
            pass

        import sys
        if sys.platform == "win32":
            try:
                result = subprocess.run(
                    ["dism", "/online", "/get-featureinfo", "/featurename:Containers-DisposableClientVM"],
                    capture_output=True, text=True, timeout=10,
                    creationflags=NO_WINDOW,
                )
                if "State : Enabled" in result.stdout:
                    return "windows"
            except Exception:
                pass

        # No containing backend. "local" is still a working answer: the browser
        # and read-only file tools run on it, and only the two code-execution
        # tools are refused. Failing here instead would take all 22 away.
        return "local"