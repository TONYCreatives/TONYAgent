"""Tests for the sandbox base-class RPC helpers (Phase 2, typed RPC)."""

from __future__ import annotations

import asyncio

import pytest

from tonyagent.sandbox.base import (
    BrowserResult,
    CommandResult,
    SandboxBackend,
    SandboxConfig,
    SandboxStatus,
)


class FakeBackend(SandboxBackend):
    """Minimal backend: answers every RPC from a canned handler."""

    def __init__(self, handler=None):
        super().__init__(SandboxConfig())
        self.handler = handler or (lambda method, params: {"ok": True})
        self.sent: list[dict] = []

    async def start(self) -> bool:
        self.status = SandboxStatus.RUNNING
        return True

    async def stop(self) -> None:
        self.status = SandboxStatus.STOPPED

    async def health_check(self) -> bool:
        return self.status is SandboxStatus.RUNNING

    async def _send_request(self, request: dict) -> None:
        self.sent.append(request)
        result = self.handler(request["method"], request["params"])
        self._handle_response({"jsonrpc": "2.0", "result": result, "id": request["id"]})


async def test_ping_allowed_while_starting():
    backend = FakeBackend(lambda m, p: {"pong": True, "pid": 123})
    backend.status = SandboxStatus.STARTING
    assert await backend.ping() == {"pong": True, "pid": 123}


async def test_rpc_rejected_when_stopped():
    backend = FakeBackend()
    backend.status = SandboxStatus.STOPPED
    with pytest.raises(RuntimeError, match="not running"):
        await backend.ping()


async def test_execute_command_returns_typed_result():
    backend = FakeBackend(
        lambda m, p: {"stdout": "hi\n", "stderr": "", "returncode": 0}
    )
    backend.status = SandboxStatus.RUNNING
    result = await backend.execute_command("echo hi")
    assert isinstance(result, CommandResult)
    assert (result.stdout, result.returncode) == ("hi\n", 0)


async def test_browser_methods_return_typed_result():
    backend = FakeBackend(
        lambda m, p: {"success": True, "data": {"title": "Example"}, "error": None}
    )
    backend.status = SandboxStatus.RUNNING
    result = await backend.browser_navigate("https://example.com")
    assert isinstance(result, BrowserResult)
    assert result.success is True
    assert result.data == {"title": "Example"}


async def test_rpc_error_surfaces_as_exception():
    class ErrBackend(FakeBackend):
        async def _send_request(self, request: dict) -> None:
            self._handle_response(
                {
                    "jsonrpc": "2.0",
                    "error": {"code": -32601, "message": "Method not found: nope"},
                    "id": request["id"],
                }
            )

    backend = ErrBackend()
    backend.status = SandboxStatus.RUNNING
    with pytest.raises(RuntimeError, match="Method not found"):
        await backend._rpc_call("nope", {})


async def test_rpc_timeout_cleans_up_pending():
    class HangBackend(FakeBackend):
        async def _send_request(self, request: dict) -> None:
            pass  # never answer

    backend = HangBackend()
    backend.status = SandboxStatus.RUNNING
    with pytest.raises(RuntimeError, match="timed out"):
        await asyncio.wait_for(backend._rpc_call("ping", {}, timeout=0.05), timeout=5)
    assert backend._pending == {}


def test_container_name_is_overridable(monkeypatch, tmp_path):
    """Two instances must be able to coexist (start evicts same-name containers)."""
    from tonyagent.sandbox.docker_backend import DockerSandboxBackend

    cfg = SandboxConfig(project_path=str(tmp_path))
    monkeypatch.delenv("TONYAGENT_SANDBOX_CONTAINER", raising=False)
    assert DockerSandboxBackend(cfg)._container_name == DockerSandboxBackend.CONTAINER_NAME

    monkeypatch.setenv("TONYAGENT_SANDBOX_CONTAINER", "tonyagent-sandbox-test")
    assert DockerSandboxBackend(cfg)._container_name == "tonyagent-sandbox-test"

    # Explicit argument wins over the environment.
    assert DockerSandboxBackend(cfg, container_name="explicit")._container_name == "explicit"


# --- Security hardening -------------------------------------------------------

def _args(tmp_path, **overrides):
    from tonyagent.sandbox.docker_backend import DockerSandboxBackend

    cfg = SandboxConfig(project_path=str(tmp_path), **overrides)
    return DockerSandboxBackend(cfg)._build_run_args(tmp_path)


def test_isolation_flags_present_by_default(tmp_path):
    """A default sandbox must not be a bare `docker run`."""
    args = _args(tmp_path)
    joined = " ".join(args)
    assert "--pids-limit" in joined
    assert "--cap-drop ALL" in joined
    assert "no-new-privileges" in joined
    assert "--ulimit nofile=1024:1024" in joined
    assert "--ulimit nproc=256:256" in joined
    assert "/tmp:rw,noexec,nosuid,size=256m" in joined
    # No swap escape hatch: memory-swap must equal memory.
    assert args[args.index("--memory-swap") + 1] == args[args.index("--memory") + 1]


def test_network_is_denied_by_default(tmp_path):
    args = _args(tmp_path)
    assert args[args.index("--network") + 1] == "none"
    # The dataclass default itself must be restrictive, not just the builder.
    assert SandboxConfig().enable_network is False


def test_network_opt_in_uses_bridge(tmp_path):
    args = _args(tmp_path, enable_network=True)
    assert args[args.index("--network") + 1] == "bridge"


def test_workspace_read_only_is_opt_in(tmp_path):
    rw = _args(tmp_path)
    assert f"{tmp_path}:/workspace" in rw
    ro = _args(tmp_path, workspace_read_only=True)
    assert f"{tmp_path}:/workspace:ro" in ro


def test_hardening_flags_can_be_disabled(tmp_path):
    """Users need an escape hatch if a flag breaks their environment."""
    args = _args(tmp_path, drop_capabilities=False, no_new_privileges=False, pids_limit=0)
    joined = " ".join(args)
    assert "--cap-drop" not in joined
    assert "no-new-privileges" not in joined
    assert "--pids-limit" not in joined


def test_tmpfs_floor_is_enforced(tmp_path):
    """A silly tmpfs size must not disable the bound entirely."""
    args = _args(tmp_path, tmpfs_size_mb=1)
    assert "size=16m" in " ".join(args)


def test_settings_defaults_are_restrictive():
    """Guard the user-facing defaults, not just the dataclass."""
    from tonyagent.config.settings import SandboxSettings

    s = SandboxSettings()
    assert s.enable_network is False
    assert s.drop_capabilities is True
    assert s.no_new_privileges is True
    assert s.pids_limit == 512
    assert s.workspace_read_only is False


def test_browser_tools_explain_network_requirement(monkeypatch):
    """With egress off, browser tools must say what to change, not fail obscurely."""
    from tonyagent.sandbox.base import SandboxStatus
    from tonyagent.tools import browser_tools

    class FakeBackend:
        status = SandboxStatus.RUNNING
        config = SandboxConfig(enable_network=False)

    manager = browser_tools.get_shared_sandbox_manager()
    monkeypatch.setattr(manager, "get_backend", lambda: FakeBackend())

    err = browser_tools._check_sandbox(needs_network=True)
    assert err and "network" in err.lower() and "Settings" in err
    # Tools that do not need egress must be unaffected.
    assert browser_tools._check_sandbox() is None
    assert browser_tools._check_sandbox(needs_network=False) is None


def test_check_sandbox_tolerates_backend_without_config(monkeypatch):
    """A third-party backend with no `config` must not raise, just pass the check."""
    from tonyagent.sandbox.base import SandboxStatus
    from tonyagent.tools import browser_tools

    class BareBackend:
        status = SandboxStatus.RUNNING  # deliberately no `config` attribute

    manager = browser_tools.get_shared_sandbox_manager()
    monkeypatch.setattr(manager, "get_backend", lambda: BareBackend())
    assert browser_tools._check_sandbox() is None
    # Unknown config -> treated as "no network", so the guidance still shows.
    assert "network" in (browser_tools._check_sandbox(needs_network=True) or "").lower()
