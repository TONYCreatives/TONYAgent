"""Docker sandbox backend for TONYAgent."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Optional

import docker

from tonyagent.sandbox.base import (
    SandboxBackend,
class DockerSandboxBackend(SandboxBackend):
    """Docker-based sandbox backend."""

    def __init__(self, config):
        super().__init__(config)
        self._client = None
        self._container = None
async def start(self):
        try:
            self.status = SandboxStatus.STARTING
            project_path = self.config.project_path
            if not project_path:
                project_path = str(folder_manager.current_folder) if folder_manager.current_folder else "."
            project_path = Path(project_path).resolve()
            if not project_path.exists():
                logger.error(f"Project path does not exist: {project_path}")
                return False

            import docker
            self._client = docker.from_env()
            await self._ensure_image()

            self._container = self._client.containers.run(
                image=self.config.docker_image,
                command=["python", "-m", "tonyagent_sandbox.rpc_server"],
                detach=True,
                stdin_open=True,
                tty=True,
                volumes={str(project_path): {"bind": "/workspace", "mode": "rw"}},
                working_dir="/workspace",
                mem_limit=self.config.memory_limit,
                cpu_count=int(float(self.config.cpu_limit)),
                network_mode="bridge" if self.config.enable_network else "none",
                remove=True,
                environment={"SANDBOX_TIMEOUT": str(self.config.timeout), "PYTHONUNBUFFERED": "1"},
            )

            self._container_id = self._container.id[:12]
            import loguru
            logger.info(f"Started sandbox container: {self._container_id}")

            import asyncio
            await asyncio.sleep(2)
            self._process = await self._connect_to_container()
            asyncio.create_task(self._read_responses())

            for _ in range(10):
                if await self.health_check():
                    self.status = SandboxStatus.RUNNING
                    logger.info(f"Sandbox {self._container_id} is ready")
                    return True
async def _connect_to_container(self):
        import asyncio
        proc = await asyncio.create_subprocess_exec("docker", "exec", "-i", self._container_id, "python", "-m", "tonyagent_sandbox.rpc_server", stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        return proc

    async def _read_responses(self):
        while self.status == SandboxStatus.RUNNING:
            line = await self._process.stdout.readline()
            if not line: break
            line = line.decode("utf-8").strip()
            if not line: continue
            try:
                response = json.loads(line)
                if "id" in response: self._handle_response(response)
                else: self._handle_notification(response)
            except json.JSONDecodeError:
                logger.warning(f"Invalid JSON from sandbox: {line}")

    async def _send_request(self, request):
        data = json.dumps(request) + "\n"
        self._process.stdin.write(data.encode("utf-8"))
        await self._process.stdin.drain()

    async def stop(self):
        self.status = SandboxStatus.STOPPING
        if self._process:
            try:
                self._process.terminate()
                await asyncio.wait_for(self._process.wait(), timeout=5)
            except asyncio.TimeoutError:
                self._process.kill()
                await self._process.wait()
        if self._container:
            self._container.stop(timeout=5)
        self.status = SandboxStatus.STOPPED

    async def health_check(self):
        try:
            result = await self.execute_command("echo health", timeout=5)
            return result.returncode == 0 and "health" in result.stdout
        except:
            return False
                await asyncio.sleep(1)

            logger.error("Sandbox health check failed")
            await self.stop()
            return False
        except Exception as e:
            logger.exception("Failed to start Docker sandbox")
            await self.stop()
            return False

    async def _ensure_image(self):
        try:
            self._client.images.get(self.config.docker_image)
        except docker.errors.ImageNotFound:
            await self._build_image()

    async def _build_image(self):
        import asyncio
        dockerfile_path = Path(__file__).parent.parent.parent.parent / "docker" / "sandbox"
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, lambda: self._client.images.build(path=str(dockerfile_path), tag=self.config.docker_image, rm=True, forcerm=True))
        self._container_id = ""
    SandboxConfig,
    SandboxStatus,
    CommandResult,
    BrowserResult,
)
from tonyagent.config.settings import settings
from tonyagent.folder.manager import folder_manager
from loguru import logger