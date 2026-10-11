"""The WSL backend: what it builds, what it parses, what it refuses.

The live path (boot the distro, round-trip a command) is in
``tests/integration/test_wsl_backend.py`` and needs a real WSL2 install,
so it is opt-in. Everything here is the logic around it: the argv the
sandbox server is started with, the distro detection, the ``/workspace``
translation the tool layer's contract requires, and the one capability
question worth asking before a call rather than after.
"""

from __future__ import annotations

import asyncio
import subprocess
from types import SimpleNamespace

import pytest

from tonyagent.sandbox.base import SandboxConfig
from tonyagent.sandbox.wsl_backend import (
    CONTRACT_ROOT,
    NON_USER_DISTROS,
    WslSandboxBackend,
    _decode_wsl_listing,
    detect_wsl_distro,
)


def _backend(**overrides) -> WslSandboxBackend:
    config = SandboxConfig(**overrides)
    backend = WslSandboxBackend(config)
    backend._distro = "Ubuntu-24.04"
    backend._workspace_wsl = "/mnt/c/Users/iig2y/Desktop/TONYAgent"
    return backend


# --- argv ----------------------------------------------------------------------


def test_the_argv_runs_the_server_inside_the_namespaces():
    args = _backend()._build_argv()
    joined = " ".join(args)

    assert args[0].lower().endswith("wsl.exe")
    assert "-d" in args and "Ubuntu-24.04" in args
    assert "-u" in args and "root" in args
    # Network is denied by default, and the mount is PID-namespace'd.
    assert "unshare -n -p -f --mount-proc" in joined
    assert "TONYAGENT_WORKSPACE='/mnt/c/Users/iig2y/Desktop/TONYAgent'" in joined


def test_network_opt_in_drops_the_network_namespace():
    """The one container setting the namespaces mirror, direction included.

    With egress on, ``unshare -n`` is *absent*: the browser tools need the
    network, and a sandbox that cannot load a page is a sandbox that breaks
    the feature it was started for.
    """
    joined = " ".join(_backend(enable_network=True)._build_argv())

    assert "unshare -p -f --mount-proc" in joined
    assert "unshare -n" not in joined


def test_a_path_with_spaces_is_quoted():
    """``cd /mnt/c/Users/Some Name/project`` is two words to a shell."""
    backend = _backend()
    backend._workspace_wsl = "/mnt/c/Users/Some Name/project"
    joined = " ".join(backend._build_argv())

    assert "cd '/mnt/c/Users/Some Name/project'" in joined
    assert "TONYAGENT_WORKSPACE='/mnt/c/Users/Some Name/project'" in joined


def test_the_nproc_bound_is_guarded():
    """dash's ``ulimit`` has no ``-u``; the distro's sh is dash half the time.

    A distro that cannot take the bound must lose the bound, not the
    sandbox -- which is why the statement is a guarded group rather than a
    bare ``ulimit -u`` the shell would exit on.
    """
    joined = " ".join(_backend(ulimit_nproc=256)._build_argv())
    assert "ulimit -u 256" in joined
    assert joined.count("|| true") == 1

    no_limit = " ".join(_backend(ulimit_nproc=0)._build_argv())
    assert "ulimit" not in no_limit


# --- the contract path, translated ---------------------------------------------


def test_the_workspace_contract_path_is_translated():
    backend = _backend()
    assert backend._translate_path(CONTRACT_ROOT) == "/mnt/c/Users/iig2y/Desktop/TONYAgent"
    assert (
        backend._translate_path("/workspace/src/pkg")
        == "/mnt/c/Users/iig2y/Desktop/TONYAgent/src/pkg"
    )
    # Not a simulated path: a path from anywhere else is passed through.
    assert backend._translate_path("/home/sandbox/thing") == "/home/sandbox/thing"
    assert backend._translate_path("") == ""
    # The one-liner that follows a translated path is exact, not a prefix.
    assert not backend._translate_path("/workspace-evil/x").endswith("TONYAgent/workspace-evil/x")


async def test_execute_command_translates_the_contract_cwd(monkeypatch):
    """The tool layer spells ``/workspace``; this backend must not send it.

    ``/workspace`` exists in a container because Docker mounts it. A WSL
    distro has no such directory, so the spelling travels as far as the
    backend and no further.
    """
    backend = _backend()
    seen: dict = {}

    async def fake_super(self, command, cwd, timeout):
        seen.update(command=command, cwd=cwd, timeout=timeout)
        from tonyagent.sandbox.base import CommandResult

        return CommandResult(stdout="ok", stderr="", returncode=0)

    monkeypatch.setattr(
        type(backend).__mro__[1], "execute_command", fake_super, raising=True
    )
    await backend.execute_command("echo hi", cwd="/workspace/src", timeout=5)
    assert seen["cwd"] == "/mnt/c/Users/iig2y/Desktop/TONYAgent/src"


# --- detection -----------------------------------------------------------------


def _listing(*rows: tuple[bool, str, str, str]) -> bytes:
    lines = ["  NAME                   STATE       VERSION"]
    for default, name, state, version in rows:
        marker = "*" if default else " "
        lines.append(f"{marker} {name:<22} {state:<11} {version}")
    return "\r\n".join(lines).encode("utf-16")


def test_the_default_distro_is_the_one_marked_default(monkeypatch):
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(
            returncode=0,
            stdout=_listing(
                (False, "docker-desktop", "Stopped", "2"),
                (True, "Ubuntu-24.04", "Stopped", "2"),
                (False, "Alpine", "Stopped", "2"),
            ),
        ),
    )
    assert detect_wsl_distro() == "Ubuntu-24.04"


def test_dockers_own_distro_is_never_the_answer(monkeypatch):
    """A helper distro with no shell user is not "a Linux environment"."""
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(
            returncode=0,
            stdout=_listing(
                (True, "docker-desktop", "Stopped", "2"),
                (False, "Ubuntu-22.04", "Stopped", "2"),
            ),
        ),
    )
    assert detect_wsl_distro() == "Ubuntu-22.04"


def test_without_a_default_the_first_user_distro_is_taken(monkeypatch):
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(
            returncode=0,
            stdout=_listing(
                (False, "docker-desktop", "Stopped", "2"),
                (False, "Fedora-39", "Stopped", "2"),
                (False, "Debian", "Stopped", "2"),
            ),
        ),
    )
    assert detect_wsl_distro() == "Fedora-39"


def test_a_distro_name_with_spaces_survives_the_parse(monkeypatch):
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(
            returncode=0,
            stdout=_listing((True, "Ubuntu 22.04 LTS", "Stopped", "2")),
        ),
    )
    assert detect_wsl_distro() == "Ubuntu 22.04 LTS"


def test_no_distros_at_all_is_none(monkeypatch):
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(
            returncode=0, stdout=_listing()  # header only
        ),
    )
    assert detect_wsl_distro() is None


def test_a_failing_wsl_exe_is_none(monkeypatch):
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(returncode=1, stdout=b""),
    )
    assert detect_wsl_distro() is None


def test_a_wsl_exe_that_is_not_on_path_is_none(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: None)
    assert detect_wsl_distro() is None


def test_the_listing_decoder_handles_utf16_and_utf8():
    # wsl.exe prints UTF-16LE; a WSL build that prints UTF-8 still parses.
    assert _decode_wsl_listing("Ubuntu Stopped 2\r\n".encode("utf-16")) == ["Ubuntu Stopped 2"]
    assert _decode_wsl_listing("Ubuntu Stopped 2\r\n".encode("utf-8")) == ["Ubuntu Stopped 2"]


def test_the_listing_decoder_survives_utf16_without_a_bom():
    """Measured under a test runner: the same command arrives *without* its BOM.

    A console-attached ``wsl -l -v`` writes the BOM; a process with no
    console writes UTF-16LE bare. A decoder that required the BOM decoded
    the second form as mojibake full of NULs, and the NULs then reached
    ``create_subprocess_exec`` as "embedded null character" -- a start
    failure that names neither the cause nor the listing.
    """
    raw = "* Ubuntu-24.04                Stopped         2\r\n".encode("utf-16-le")
    assert not raw.startswith(b"\xff\xfe"), "the fixture must be the bare form"
    assert _decode_wsl_listing(raw) == ["* Ubuntu-24.04                Stopped         2"]


def test_the_helper_distros_are_named():
    assert "docker-desktop" in NON_USER_DISTROS


# --- the capability question ----------------------------------------------------


async def test_execute_js_refuses_readably_without_node():
    """A distro without Node says so, rather than ENOENT from a spawn.

    The probe at start asks the question once; the answer travels on the
    tool result, which is where the user reads it.
    """
    from tonyagent.sandbox.base import BrowserResult

    backend = _backend()
    backend._has_node = False
    result = await backend.execute_js("1+1")

    assert isinstance(result, BrowserResult)
    assert result.success is False
    assert "Node.js is not installed" in result.error
    assert "Ubuntu-24.04" in result.error


async def test_execute_js_reaches_the_server_when_node_is_there(monkeypatch):
    from tonyagent.sandbox.base import BrowserResult

    backend = _backend()
    backend._has_node = True

    seen: dict = {}

    async def fake_execute_js(self, script, timeout=10):
        seen.update(script=script, timeout=timeout)
        return BrowserResult(success=True, data="2", error=None)

    monkeypatch.setattr(
        type(backend).__mro__[1], "execute_js", fake_execute_js, raising=True
    )
    result = await backend.execute_js("1+1")
    assert result.success and seen["script"] == "1+1"


# --- configuration plumbing -----------------------------------------------------


def test_the_config_carries_the_distro():
    assert SandboxConfig().wsl_distro == ""
    assert SandboxConfig(wsl_distro="Debian").wsl_distro == "Debian"


def test_the_settings_name_the_distro_and_the_type():
    from tonyagent.config.settings import SandboxSettings

    settings = SandboxSettings()
    assert settings.type == "auto"
    assert settings.wsl_distro == ""
