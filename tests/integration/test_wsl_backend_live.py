"""The WSL backend, driven for real: boot a distro and round-trip work.

Skipped unless both ``wsl.exe`` is on PATH *and* ``TONYAGENT_TEST_WSL=1``
is set: this starts a real sandbox in a real distro, which is a machine
fact, not a test-fixture one. Run it where you are changing the backend::

    set TONYAGENT_TEST_WSL=1
    pytest tests/integration/test_wsl_backend.py

What it proves that the unit tests cannot: that the transport round-trips,
that the containment is real (no egress), that the workspace is live rather
than copied (a file written from inside lands on the host), and that the
PID namespace makes the server PID 1.
"""

from __future__ import annotations

import asyncio
import os
import shutil

import pytest

from tonyagent.sandbox.base import SandboxConfig, SandboxStatus
from tonyagent.sandbox.wsl_backend import (
    CONTRACT_ROOT,
    RPC_SERVER_REMOTE,
    WslSandboxBackend,
    detect_wsl_distro,
)

pytestmark = [
    pytest.mark.skipif(
        shutil.which("wsl.exe") is None, reason="wsl.exe not on PATH"
    ),
    pytest.mark.skipif(
        os.environ.get("TONYAGENT_TEST_WSL") != "1",
        reason="set TONYAGENT_TEST_WSL=1 to run the live WSL sandbox tests",
    ),
]


@pytest.fixture
async def sandbox(tmp_path):
    """A started WSL sandbox over a throwaway project folder."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "hello.py").write_text("print('hi')\n", encoding="utf-8")
    backend = WslSandboxBackend(SandboxConfig(project_path=str(tmp_path)))
    started = await backend.start()
    assert started, "the WSL sandbox did not start"
    assert backend.status is SandboxStatus.RUNNING
    try:
        yield backend, tmp_path
    finally:
        await backend.stop()


async def test_detection_finds_the_machine_default_distro():
    """Not a unit-test double: the real ``wsl -l -v`` on this machine."""
    distro = detect_wsl_distro()
    assert distro, "no user distro detected"
    assert distro.lower() != "docker-desktop"


async def test_ping_and_execution_round_trip(sandbox):
    backend, project = sandbox

    assert (await backend.ping())["pong"] is True

    ran = await backend.execute_command(
        "python3 -c \"import os; print(os.getcwd())\"",
        cwd=CONTRACT_ROOT,
        timeout=30,
    )
    assert ran.returncode == 0, ran.stderr
    assert "/mnt/c/" in ran.stdout, ran.stdout
    assert os.path.basename(str(project)) in ran.stdout


async def test_the_server_is_pid_one_of_its_own_pid_namespace(sandbox):
    """PID 1 inside its own namespace -- the server, not one of its children.

    ``ping`` reports the *server's* pid, which is the fact that matters:
    when it goes, the kernel takes the namespace with it, so nothing the
    sandbox spawned outlives it. (``echo $$`` inside ``exec_command`` is
    the child's pid, and reading that as the server's is a test measuring
    the wrong process.)
    """
    backend, _ = sandbox
    assert (await backend.ping())["pid"] == 1


async def test_egress_is_refused_by_default(sandbox):
    backend, _ = sandbox
    # A connect that would succeed on the host must fail inside the ns.
    blocked = await backend.execute_command(
        "python3 -c \"import socket; socket.setdefaulttimeout(3); "
        "socket.create_connection(('1.1.1.1', 443)); print('REACHED')\"",
        timeout=20,
    )
    assert "REACHED" not in blocked.stdout + blocked.stderr


async def test_the_workspace_is_live_not_copied(sandbox):
    backend, project = sandbox
    made = project / "written-from-inside.txt"
    # The path the *distro* uses for the same file: a Windows path handed
    # to Linux python is the same category of mistake in both directions.
    from_inside = f"{backend._workspace_wsl}/written-from-inside.txt"

    await backend.execute_command(
        f"python3 -c \"import pathlib; pathlib.Path({from_inside!r}).write_text('from the distro')\"",
        timeout=20,
    )
    # The host sees the file without any copy step: the mount is the mount.
    assert made.exists(), "a file written inside the sandbox never reached the host"
    assert made.read_text(encoding="utf-8") == "from the distro"


async def test_the_contract_cwd_reaches_the_project_not_the_host_root(sandbox):
    """``/workspace`` is the spelling; the project's files answer it."""
    backend, project = sandbox
    ran = await backend.execute_command("ls src/hello.py", cwd=CONTRACT_ROOT, timeout=15)
    assert ran.returncode == 0, ran.stderr
    assert "hello.py" in ran.stdout
    # And the distro's own root is not what got listed.
    assert "usr" not in ran.stdout and "bin" not in ran.stdout


async def test_read_file_sees_the_project(sandbox):
    backend, project = sandbox
    (project / "note.md").write_text("hello from the host\n", encoding="utf-8")
    read = await backend.read_file("note.md", max_bytes=64)
    assert read.success, read.error
    assert "hello from the host" in (read.data or {}).get("content", "")


async def test_the_rpc_server_is_staged_in_the_distro(sandbox):
    backend, _ = sandbox
    staged = await backend._run_in_distro(f"ls -la {RPC_SERVER_REMOTE}", timeout=15)
    assert RPC_SERVER_REMOTE in staged


async def test_stop_actually_stops(sandbox):
    backend, project = sandbox
    await backend.stop()
    assert backend.status is SandboxStatus.STOPPED
    with pytest.raises(RuntimeError):
        await backend.ping()
