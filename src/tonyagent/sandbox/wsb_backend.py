"""Windows Sandbox backend for TONYAgent."""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
import subprocess
from pathlib import Path
from typing import Any, Optional

from tonyagent.sandbox.base import (
    SandboxBackend,
    SandboxConfig,
    SandboxStatus,
    CommandResult,
    BrowserResult,
)
from tonyagent.folder.manager import folder_manager
from loguru import logger


class WsbSandboxBackend(SandboxBackend):
    """Windows Sandbox backend using .wsb configuration.

    NOT IMPLEMENTED. Every transport method below is a ``pass`` and the
    ``LogonCommand`` it writes names a ``tonyagent_sandbox.rpc_server`` module
    that does not exist, so this cannot start and cannot serve a request.

    It is left in place, rather than deleted, only so the gap is visible in the
    source. Two things follow from it, and both were true before this class was
    written:

    * ``SandboxManager._detect_backend`` can never return ``"windows"``, because
      its DISM probe needs an elevated shell and every non-elevated run falls
      through to ``"docker"``.
    * ``provides_isolation`` is deliberately left False. A stub that cannot
      contain anything must not be selectable as the thing that does.

    If you are here to finish it: the local runtime is the transport, not this.
    ``LocalBackend`` already solves "run the sandbox RPC server somewhere
    else", and pointing a ``.wsb`` config at a copy of that server is a much
    smaller job than wiring up named pipes from scratch.
    """

    #: Must stay False until a request can actually round-trip.
    provides_isolation = False

    def __init__(self, config: SandboxConfig):
        super().__init__(config)
        self._wsb_process: Optional[subprocess.Popen] = None
        self._pipe_name = r"\\.\pipe\tonyagent-sandbox"
        self._pipe_handle: Optional[int] = None

    async def start(self) -> bool:
        try:
            self.status = SandboxStatus.STARTING

            project_path = self.config.project_path
            if not project_path:
                project_path = str(folder_manager.current_folder) if folder_manager.current_folder else "."
            
            project_path = Path(project_path).resolve()
            if not project_path.exists():
                logger.error(f"Project path does not exist: {project_path}")
                return False

            # Create .wsb config file
            wsb_config = self._create_wsb_config(project_path)
            wsb_file = Path(tempfile.gettempdir()) / f"tonyagent_{os.getpid()}.wsb"
            wsb_file.write_text(wsb_config, encoding="utf-8")

            # Start Windows Sandbox
            self._wsb_process = subprocess.Popen(
                ["wt.exe", "-d", ".", "cmd", "/c", f"wsb.exe {wsb_file}"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            # Wait for sandbox to start and connect to named pipe
            await asyncio.sleep(5)
            
            # Connect to named pipe
            await self._connect_pipe()
            
            # Start response reader
            asyncio.create_task(self._read_responses())

            # Health check
            for _ in range(10):
                if await self.health_check():
                    self.status = SandboxStatus.RUNNING
                    logger.info("Windows Sandbox is ready")
                    return True
                await asyncio.sleep(2)

            logger.error("Windows Sandbox health check failed")
            await self.stop()
            return False

        except Exception as e:
            logger.exception("Failed to start Windows Sandbox")
            await self.stop()
            return False

    def _create_wsb_config(self, project_path: Path) -> str:
        """Create Windows Sandbox configuration."""
        # Map project folder to sandbox
        mapped_folder = f"""
<MappedFolders>
    <MappedFolder>
        <HostFolder>{project_path}</HostFolder>
        <SandboxFolder>C:\\workspace</SandboxFolder>
        <ReadOnly>false</ReadOnly>
    </MappedFolder>
</MappedFolders>"""

        # Network config
        network = "<Networking>Default</Networking>" if self.config.enable_network else "<Networking>Disable</Networking>"

        # Memory/CPU (approximate)
        memory_mb = int(self.config.memory_limit.replace("g", "")) * 1024 if self.config.memory_limit.endswith("g") else 2048

        return f"""<Configuration>
    <VGpu>Enable</VGpu>
    {network}
    <MemoryInMB>{memory_mb}</MemoryInMB>
    {mapped_folder}
    <LogonCommand>
        <Command>cmd /c python -m tonyagent_sandbox.rpc_server</Command>
    </LogonCommand>
    <ProtectedClient>true</ProtectedClient>
    <PrinterRedirection>Disable</PrinterRedirection>
    <AudioRedirection>Disable</AudioRedirection>
    <VideoRedirection>Disable</VideoRedirection>
</Configuration>"""

    async def _connect_pipe(self) -> None:
        """Connect to Windows named pipe."""
        # In Python, we'll use a file-like approach
        # For simplicity, we'll use stdin/stdout of the WSB process
        if self._wsb_process:
            # WSB doesn't easily support pipe communication from host
            # For now, we'll fall back to file-based communication
            pass

    async def _read_responses(self) -> None:
        """Read responses from sandbox."""
        # This would read from named pipe or file
        pass

    async def _send_request(self, request: dict) -> None:
        """Send request to sandbox via named pipe."""
        pass

    async def stop(self) -> None:
        self.status = SandboxStatus.STOPPING
        
        if self._wsb_process:
            self._wsb_process.terminate()
            try:
                await asyncio.wait_for(
                    asyncio.get_event_loop().run_in_executor(None, self._wsb_process.wait),
                    timeout=10
                )
            except asyncio.TimeoutError:
                self._wsb_process.kill()
        
        self.status = SandboxStatus.STOPPED

    async def health_check(self) -> bool:
        # Windows Sandbox health check is complex
        # For now, return True if process is running
        return self._wsb_process is not None and self._wsb_process.poll() is None