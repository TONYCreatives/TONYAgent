"""Real-Docker integration test for the Phase 1 backend (opt-in).

Run:  pytest tests/integration/test_docker_backend.py -m docker
Skipped by default (no Docker in CI).
"""

from __future__ import annotations

import shutil

import pytest

from tonyagent.sandbox.base import SandboxConfig, SandboxStatus
from tonyagent.sandbox.docker_backend import DockerSandboxBackend

pytestmark = pytest.mark.docker


@pytest.fixture
def config(tmp_path):
    (tmp_path / "probe.txt").write_text("hello", encoding="utf-8")
    return SandboxConfig(
        type="docker",
        project_path=str(tmp_path),
        cpu_limit="1.0",
        enable_network=True,  # browser_navigate in this test needs egress
    )


@pytest.mark.skipif(shutil.which("docker") is None, reason="docker CLI not on PATH")
async def test_start_ping_exec_stop(config):
    backend = DockerSandboxBackend(config)
    assert await backend.start() is True
    assert backend.status is SandboxStatus.RUNNING
    try:
        pong = await backend.ping()
        assert pong.get("pong") is True

        result = await backend.execute_command("cat /workspace/probe.txt")
        assert result.returncode == 0
        assert "hello" in result.stdout

        nav = await backend.browser_navigate("https://example.com")
        assert nav.success, nav.error
    finally:
        await backend.stop()
    assert backend.status is SandboxStatus.STOPPED
