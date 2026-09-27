"""Sandbox base classes and protocol for TONYAgent."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional
import asyncio


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

    async def start(self, config: SandboxConfig) -> bool:
        self._config = config

        if config.type == "auto":
            config.type = await self._detect_backend()

        if config.type == "docker":
            from tonyagent.sandbox.docker_backend import DockerSandboxBackend
            self._backend = DockerSandboxBackend(config)
        elif config.type == "windows":
            from tonyagent.sandbox.wsb_backend import WsbSandboxBackend
            self._backend = WsbSandboxBackend(config)
        else:
            raise ValueError(f"Unknown sandbox type: {config.type}")

        success = await self._backend.start()
        if success:
            self._backend.status = SandboxStatus.RUNNING
        return success

    async def stop(self) -> None:
        if self._backend:
            await self._backend.stop()
            self._backend = None

    async def health_check(self) -> bool:
        if not self._backend:
            return False
        return await self._backend.health_check()

    def get_backend(self) -> Optional[SandboxBackend]:
        return self._backend

    def is_running(self) -> bool:
        """True when a backend exists and reports RUNNING."""
        return self._backend is not None and self._backend.status is SandboxStatus.RUNNING

    @staticmethod
    async def _detect_backend() -> str:
        try:
            import docker
            client = docker.from_env()
            client.ping()
            return "docker"
        except Exception:
            pass

        import sys
        if sys.platform == "win32":
            try:
                import subprocess
                result = subprocess.run(
                    ["dism", "/online", "/get-featureinfo", "/featurename:Containers-DisposableClientVM"],
                    capture_output=True, text=True, timeout=10
                )
                if "State : Enabled" in result.stdout:
                    return "windows"
            except Exception:
                pass

        return "docker"