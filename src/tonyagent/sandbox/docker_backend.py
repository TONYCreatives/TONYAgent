"""Docker sandbox backend for TONYAgent.

Phase 1 design: one process, one channel. The container's main process IS the
RPC server (``python /home/sandbox/rpc_server.py`` per the Dockerfile CMD), and
the host talks to it over the ``docker run -i`` stdin/stdout pipes held open
for the container's lifetime. No ``docker exec`` second server.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
from pathlib import Path
from typing import Optional

from tonyagent.sandbox.base import (
    SandboxBackend,
    SandboxConfig,
    SandboxStatus,
    CommandResult,
)
from tonyagent.folder.manager import folder_manager
from loguru import logger


class DockerSandboxBackend(SandboxBackend):
    """Docker backend speaking JSON-RPC to the container over stdio."""

    #: Default name so the SDK can resolve the same container for stats.
    CONTAINER_NAME = "tonyagent-sandbox"

    #: How long to wait for the first ping reply before giving up.
    STARTUP_TIMEOUT = 60.0
    PING_INTERVAL = 2.0

    def __init__(self, config: SandboxConfig, container_name: Optional[str] = None):
        super().__init__(config)
        self._client = None
        self._container_id: str = ""
        self._reader_task: Optional[asyncio.Task] = None
        self._stderr_task: Optional[asyncio.Task] = None
        # Two instances sharing one name would evict each other's container
        # (start removes the "stale" one), so the name is overridable.
        self._container_name = (
            container_name
            or os.environ.get("TONYAGENT_SANDBOX_CONTAINER")
            or self.CONTAINER_NAME
        )

    # Backwards-compat alias: the UI reads ``backend._container_id``.
    @property
    def container_id(self) -> str:
        return self._container_id

    async def start(self) -> bool:
        try:
            self.status = SandboxStatus.STARTING

            project_path = self.config.project_path
            if not project_path:
                project_path = str(folder_manager.current_folder) if folder_manager.current_folder else "."
            project_path = Path(project_path).resolve()
            if not project_path.exists():
                logger.error(f"Project path does not exist: {project_path}")
                self.status = SandboxStatus.STOPPED
                return False

            if shutil.which("docker") is None:
                logger.error("Docker CLI not found on PATH")
                self.status = SandboxStatus.STOPPED
                return False

            import docker

            self._client = docker.from_env()
            await self._ensure_image()

            # Remove any stale container left behind by a previous crash,
            # otherwise ``--name`` collides.
            await self._remove_stale_container()

            args = self._build_run_args(project_path)
            logger.info(f"Starting sandbox container: {' '.join(args)}")
            self._process = await asyncio.create_subprocess_exec(
                *args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            # Start the response reader BEFORE any RPC so ping replies land.
            self._reader_task = asyncio.get_running_loop().create_task(self._read_responses())
            self._stderr_task = asyncio.get_running_loop().create_task(self._drain_stderr())

            # Readiness = ping reply, not the self-deadlocking health_check.
            import time

            deadline = time.monotonic() + self.STARTUP_TIMEOUT
            while time.monotonic() < deadline:
                try:
                    pong = await self.ping(timeout=5)
                    if pong.get("pong"):
                        self.status = SandboxStatus.RUNNING
                        logger.info(f"Sandbox ready (pid in container: {pong.get('pid')})")
                        return True
                except Exception as e:
                    logger.debug(f"Sandbox ping not ready yet: {e}")
                if self._process and self._process.returncode is not None:
                    logger.error(f"Sandbox process exited early with code {self._process.returncode}")
                    break
                await asyncio.sleep(self.PING_INTERVAL)

            logger.error("Sandbox failed to become ready (no ping reply)")
            await self.stop()
            return False
        except Exception:
            logger.exception("Failed to start Docker sandbox")
            await self.stop()
            return False

    def _build_run_args(self, project_path: Path) -> list[str]:
        """Build the ``docker run`` argv for a locked-down sandbox.

        Kept separate from ``start()`` so the isolation flags are unit-testable
        without launching anything. Every flag here is a containment measure:

        * ``--pids-limit``        - caps fork bombs
        * ``--cap-drop=ALL``      - no Linux capabilities (rootless in practice)
        * ``--security-opt=no-new-privileges`` - setuid binaries gain nothing
        * ``--ulimit``            - bounds file descriptors and processes
        * ``--tmpfs``             - bounded, memory-backed scratch space, so a
          runaway write cannot fill the host disk
        * ``--network none``      - no egress unless explicitly enabled
        * ``ro`` bind             - optional read-only project mount
        """
        cfg = self.config
        args = [
            "docker", "run", "-i", "--rm",
            "--name", self._container_name,
            "-v", f"{project_path}:/workspace{':ro' if cfg.workspace_read_only else ''}",
            "-w", "/workspace",
            # --- resource bounds ---
            "--memory", str(cfg.memory_limit),
            "--memory-swap", str(cfg.memory_limit),  # no swap escape hatch
            f"--cpus={max(0.01, float(cfg.cpu_limit))}",
        ]

        if cfg.pids_limit and cfg.pids_limit > 0:
            args += ["--pids-limit", str(int(cfg.pids_limit))]

        if cfg.drop_capabilities:
            args += ["--cap-drop", "ALL"]

        if cfg.no_new_privileges:
            args += ["--security-opt", "no-new-privileges"]

        if cfg.ulimit_nofile and cfg.ulimit_nofile > 0:
            args += ["--ulimit", f"nofile={int(cfg.ulimit_nofile)}:{int(cfg.ulimit_nofile)}"]
        if cfg.ulimit_nproc and cfg.ulimit_nproc > 0:
            args += ["--ulimit", f"nproc={int(cfg.ulimit_nproc)}:{int(cfg.ulimit_nproc)}"]

        # Bounded scratch space: writable, noexec, nosuid, size-capped.
        tmp_mb = max(16, int(cfg.tmpfs_size_mb or 256))
        args += [
            "--tmpfs", f"/tmp:rw,noexec,nosuid,size={tmp_mb}m",
            "--tmpfs", f"/run:rw,noexec,nosuid,size=8m",
        ]

        # Egress only when explicitly enabled (browser tools need it).
        args += ["--network", "bridge" if cfg.enable_network else "none"]

        args += [
            self.config.docker_image,
            "python", "/home/sandbox/rpc_server.py",
        ]
        return args

    async def _ensure_image(self) -> None:
        import docker

        assert self._client is not None
        try:
            self._client.images.get(self.config.docker_image)
        except docker.errors.ImageNotFound:
            await self._build_image()

    async def _build_image(self) -> None:
        dockerfile_path = Path(__file__).parent.parent.parent.parent / "docker" / "sandbox"
        loop = asyncio.get_running_loop()
        assert self._client is not None
        await loop.run_in_executor(
            None,
            lambda: self._client.images.build(
                path=str(dockerfile_path), tag=self.config.docker_image, rm=True, forcerm=True
            ),
        )

    async def _remove_stale_container(self) -> None:
        """Best-effort removal of a leftover named container (silent if absent)."""
        loop = asyncio.get_running_loop()
        assert self._client is not None
        try:
            await loop.run_in_executor(
                None, lambda: self._client.containers.get(self._container_name).remove(force=True)
            )
            logger.info(f"Removed stale container {self._container_name}")
        except Exception:
            pass  # Absent is the common case.

    def _resolve_container(self):
        """Resolve the live container object by name (for stats)."""
        if self._client is None:
            return None
        try:
            return self._client.containers.get(self._container_name)
        except Exception:
            return None

    async def get_stats(self) -> Optional[dict]:
        """Return a ``docker stats`` snapshot (stream=False), or None."""
        container = self._resolve_container()
        if container is None:
            return None
        loop = asyncio.get_running_loop()
        try:
            return await loop.run_in_executor(None, lambda: container.stats(stream=False))
        except Exception as e:
            logger.debug(f"Container stats failed: {e}")
            return None

    async def _read_responses(self) -> None:
        if not self._process or not self._process.stdout:
            return
        while True:
            try:
                line = await self._process.stdout.readline()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"Sandbox reader error: {e}")
                break
            if not line:
                break  # EOF: container exited.
            text = line.decode("utf-8", errors="replace").strip()
            if not text:
                continue
            try:
                response = json.loads(text)
                if "id" in response:
                    self._handle_response(response)
                else:
                    self._handle_notification(response)
            except json.JSONDecodeError:
                logger.warning(f"Invalid JSON from sandbox: {text}")
        # EOF with outstanding calls: fail them so callers don't hang.
        for request_id, future in list(self._pending.items()):
            self._pending.pop(request_id, None)
            if not future.done():
                future.set_exception(RuntimeError("Sandbox connection closed"))

    async def _drain_stderr(self) -> None:
        """Drain container stderr so logs can't block the pipe."""
        if not self._process or not self._process.stderr:
            return
        while True:
            try:
                line = await self._process.stderr.readline()
            except asyncio.CancelledError:
                break
            except Exception:
                break
            if not line:
                break
            logger.debug(f"[sandbox stderr] {line.decode('utf-8', errors='replace').rstrip()}")

    async def _send_request(self, request: dict) -> None:
        if not self._process or not self._process.stdin:
            raise RuntimeError("Sandbox process has no stdin")
        data = json.dumps(request) + "\n"
        try:
            self._process.stdin.write(data.encode("utf-8"))
            await self._process.stdin.drain()
        except (BrokenPipeError, ConnectionResetError) as e:
            raise RuntimeError(f"Sandbox connection broken: {e}") from e

    async def stop(self) -> None:
        self.status = SandboxStatus.STOPPING
        if self._reader_task:
            self._reader_task.cancel()
            self._reader_task = None
        if self._stderr_task:
            self._stderr_task.cancel()
            self._stderr_task = None
        if self._process:
            try:
                try:
                    self._process.terminate()
                except ProcessLookupError:
                    pass
                await asyncio.wait_for(self._process.wait(), timeout=5)
            except asyncio.TimeoutError:
                try:
                    self._process.kill()
                except ProcessLookupError:
                    pass
                await self._process.wait()
            except Exception as e:
                logger.debug(f"Error stopping sandbox process: {e}")
            finally:
                self._process = None
        # Belt and suspenders: --rm usually reaps it, but a crash can orphan it.
        try:
            await self._remove_stale_container()
        except Exception:
            pass
        self._container_id = ""
        self.status = SandboxStatus.STOPPED

    async def health_check(self) -> bool:
        try:
            result = await self.execute_command("echo health", timeout=5)
            return (
                isinstance(result, CommandResult)
                and result.returncode == 0
                and "health" in result.stdout
            )
        except Exception:
            return False
