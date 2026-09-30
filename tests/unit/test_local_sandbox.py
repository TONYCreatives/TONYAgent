"""The Docker-free runtime, and the line between it and real isolation.

The 22 tool schemas are hand-written dicts in ``schemas.py`` that duplicate
flags declared on the Tool classes. That duplication is a drift hazard: a tool
can be marked ``sandbox_required`` on its class and not in its schema, and
nothing complains until a tool silently runs somewhere it should not. These
tests pin the two together, and pin the behaviour that actually matters -- that
having no Docker daemon costs the agent two tools, not twenty.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tonyagent.sandbox.base import SandboxConfig, SandboxManager, SandboxStatus
from tonyagent.tools.base import tool_registry
from tonyagent.tools.schemas import ALL_SCHEMAS, SCHEMAS_BY_NAME


# --- parity between the Tool classes and the hand-written schemas -----------


def _registered_tools() -> dict:
    # Importing the tool modules is what populates the registry.
    import tonyagent.tools  # noqa: F401
    import tonyagent.tools.browser_tools  # noqa: F401
    import tonyagent.tools.file_tools  # noqa: F401
    import tonyagent.tools.network_tools  # noqa: F401
    import tonyagent.tools.sandbox_file_tools  # noqa: F401
    import tonyagent.tools.search_tools  # noqa: F401
    import tonyagent.tools.shell_tools  # noqa: F401

    tools = tool_registry.get_all()
    return {t.name: t for t in tools}


def test_every_registered_tool_has_a_schema():
    registered = set(_registered_tools())
    assert registered == set(SCHEMAS_BY_NAME), (
        "the registry and schemas.py disagree about which tools exist: "
        f"only in registry {sorted(registered - set(SCHEMAS_BY_NAME))}, "
        f"only in schemas {sorted(set(SCHEMAS_BY_NAME) - registered)}"
    )


@pytest.mark.parametrize("flag", ["sandbox_required", "isolation_required"])
def test_schema_flags_match_the_tool_classes(flag):
    """The duplicated flags must not drift apart.

    Nothing at runtime reads the schema copy, so a mismatch would not fail
    loudly -- it would just make the two sources of truth disagree.
    """
    tools = _registered_tools()
    mismatched = {
        name: (getattr(tool, flag, False), SCHEMAS_BY_NAME[name].get(flag, False))
        for name, tool in tools.items()
        if bool(getattr(tool, flag, False)) != bool(SCHEMAS_BY_NAME[name].get(flag, False))
    }
    assert not mismatched, f"{flag} differs between class and schema: {mismatched}"


def test_only_code_execution_requires_isolation():
    """Exactly the two tools that run arbitrary code are gated.

    This is the assertion that keeps the Docker dependency from creeping back:
    a new tool should have to argue for itself to land on the isolated list.
    """
    gated = {s["name"] for s in ALL_SCHEMAS if s.get("isolation_required")}
    assert gated == {"execute_command", "execute_js"}


# --- the local runtime itself ------------------------------------------------


def test_detection_falls_back_to_local_when_docker_is_down(monkeypatch):
    """With no containing backend, detection must still return a usable answer.

    It used to return "docker" unconditionally here, which made a Docker-less
    machine look like a Docker problem instead of a supported configuration.
    """
    import asyncio

    import builtins

    real_import = builtins.__import__

    def no_docker(name, *args, **kwargs):
        if name == "docker":
            raise ImportError("no docker in this test")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_docker)
    monkeypatch.setattr("subprocess.run", lambda *a, **k: type(
        "R", (), {"stdout": "", "returncode": 740}
    )())

    assert asyncio.run(SandboxManager._detect_backend()) == "local"


def test_manager_start_reports_running_without_isolation(tmp_path: Path):
    """`start` succeeds on a machine with no daemon, and does not overclaim."""
    import asyncio

    manager = SandboxManager()
    ok = asyncio.run(manager.start(SandboxConfig(project_path=str(tmp_path), type="local")))
    try:
        assert ok is True
        assert manager.is_running() is True
        assert manager.is_isolated() is False
    finally:
        asyncio.run(manager.stop())


def test_local_backend_does_not_claim_isolation():
    from tonyagent.sandbox.local_backend import LocalBackend

    assert LocalBackend.provides_isolation is False


def test_docker_backend_claims_isolation():
    from tonyagent.sandbox.docker_backend import DockerSandboxBackend

    assert DockerSandboxBackend.provides_isolation is True


def test_manager_exposes_isolation_separately_from_running(tmp_path: Path):
    """A live runtime is not the same claim as a contained one."""
    manager = SandboxManager()
    manager._config = SandboxConfig(project_path=str(tmp_path))
    # Nothing started yet, so both claims are false.
    assert manager.get_runtime_backend() is None
    assert manager.is_running() is False
    assert manager.is_isolated() is False


def test_get_backend_does_not_fall_back_to_the_local_runtime():
    """The isolating accessor must stay isolating.

    If this ever returned the local backend, execute_command would run
    model-authored shell on the host while looking like it was sandboxed.
    """
    manager = SandboxManager()
    assert manager.get_backend() is None


def test_ensure_local_starts_a_usable_runtime(tmp_path: Path):
    """The whole point: a real runtime with no Docker daemon anywhere."""
    import asyncio

    import tonyagent.folder as folder_pkg

    manager = SandboxManager()
    cfg = SandboxConfig(project_path=str(tmp_path))
    ok = asyncio.run(manager.ensure_local(cfg))
    try:
        assert ok is True
        backend = manager.get_local_backend()
        assert backend is not None
        assert backend.status is SandboxStatus.RUNNING
        # It is reachable as a runtime, and refused as an isolation boundary.
        assert manager.get_runtime_backend() is backend
        assert manager.is_running() is True
        assert manager.is_isolated() is False
    finally:
        asyncio.run(manager.stop())
    assert manager.get_runtime_backend() is None


def test_local_runtime_serves_the_read_only_file_tools(tmp_path: Path):
    """End to end over the real in-process handler, with no container."""
    import asyncio

    from tonyagent.sandbox.local_backend import LocalBackend

    (tmp_path / "note.txt").write_text("local runtime works", encoding="utf-8")
    backend = LocalBackend(SandboxConfig(project_path=str(tmp_path)))

    async def go():
        assert await backend.start() is True
        assert await backend.health_check() is True
        read = await backend.read_file("note.txt")
        listed = await backend.list_files(".")
        await backend.stop()
        return read, listed

    read, listed = asyncio.run(go())
    assert "local runtime works" in str(read.data)
    assert "note.txt" in str(listed.data)


def test_local_runtime_refuses_paths_outside_the_workspace(tmp_path: Path):
    """The workspace boundary must survive being pointed at a real folder.

    Pointed at a genuine directory rather than a container path, this is the
    check that stops a model mistake from reading the user's SSH keys.
    """
    import asyncio

    from tonyagent.sandbox.local_backend import LocalBackend

    (tmp_path.parent / "escaped.txt").write_text("secret", encoding="utf-8")
    backend = LocalBackend(SandboxConfig(project_path=str(tmp_path)))

    async def go():
        assert await backend.start() is True
        try:
            return await backend.read_file("../escaped.txt")
        finally:
            await backend.stop()

    result = asyncio.run(go())
    assert result.success is False
    assert "escape" in (result.error or "").lower()


def test_local_runtime_needs_a_project_folder(monkeypatch):
    """No folder means no runtime, and the message says so.

    The folder is cleared explicitly rather than relying on there being none:
    folder_manager is process-global, so other tests having set it would
    otherwise make this one pass or fail depending on ordering.
    """
    import asyncio

    from tonyagent.folder import folder_manager
    from tonyagent.sandbox.local_backend import LocalBackend

    monkeypatch.setattr(folder_manager, "_current_folder", None)
    backend = LocalBackend(SandboxConfig(project_path=""))
    assert asyncio.run(backend.start()) is False
    assert backend.status is SandboxStatus.STOPPED


# --- the code-execution tools stay shut without a container ------------------


def test_execute_command_refuses_to_run_on_the_local_runtime(tmp_path: Path, monkeypatch):
    """The one guarantee that must never regress.

    With only the local runtime up, execute_command has to refuse -- not fall
    back to the host, and not report success.
    """
    import asyncio

    from tonyagent.sandbox import get_shared_sandbox_manager
    from tonyagent.sandbox.local_backend import LocalBackend
    from tonyagent.tools.shell_tools import ExecuteCommandTool

    manager = get_shared_sandbox_manager()
    local = LocalBackend(SandboxConfig(project_path=str(tmp_path)))
    assert asyncio.run(local.start()) is True
    monkeypatch.setattr(manager, "_local", local, raising=False)
    try:
        result = asyncio.run(ExecuteCommandTool().execute("python --version"))
        assert result.status.value == "error"
        assert "isolated sandbox" in (result.error or "").lower()
    finally:
        asyncio.run(manager.stop())


def test_execute_js_refuses_to_run_on_the_local_runtime(tmp_path: Path, monkeypatch):
    import asyncio

    from tonyagent.sandbox import get_shared_sandbox_manager
    from tonyagent.sandbox.local_backend import LocalBackend
    from tonyagent.tools.browser_tools import ExecuteJsTool

    manager = get_shared_sandbox_manager()
    local = LocalBackend(SandboxConfig(project_path=str(tmp_path)))
    assert asyncio.run(local.start()) is True
    monkeypatch.setattr(manager, "_local", local, raising=False)
    try:
        result = asyncio.run(ExecuteJsTool().execute("1+1"))
        assert result.status.value == "error"
        assert "isolated" in (result.error or "").lower()
    finally:
        asyncio.run(manager.stop())
