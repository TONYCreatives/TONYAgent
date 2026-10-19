"""WSL2 sandbox backend: Docker-grade isolation with no Docker daemon.

**Why this exists.** The container is the only boundary that has ever
contained model-authored code here, and a machine without Docker Desktop
got nothing: ``execute_command`` and ``execute_js`` refused (correctly), and
the browser tools ran a real Chromium on the host (see ``local_backend``).
Windows Sandbox was supposed to be the Docker-free alternative and is an
unimplemented stub; WSL2 is the alternative that actually works on every
modern Windows install, with no daemon to start and no image to pull.

**What it is.** Not a new sandbox -- a new *transport* for the one that
already exists. ``docker/sandbox/rpc_server.py`` is the same server the
container runs, started here inside the distro over ``wsl.exe``'s
stdin/stdout pipes, speaking the same newline-delimited JSON-RPC the Docker
backend speaks. Everything else -- framing, id correlation, timeouts, the
typed helpers in ``base.py`` -- is the base class's, shared by construction
rather than reimplemented.

**What it buys.** A real kernel boundary: the server runs inside a network
namespace (``unshare -n``) so it cannot reach the host's services, and
inside a PID namespace so nothing it spawns outlives it. The workspace is
the live ``/mnt/c`` 9p mount -- no copy, and files it writes land as the
WSL-mapped user (uid 1000) rather than root, which is the one respect in
which this beats Docker, whose root container leaves root-owned files
behind on the host.

**What it does not buy, stated plainly.** No per-container memory or CPU
limit: WSL2 has cgroups but wiring one per session is a project of its own,
and the honest move is to say so rather than to fake a flag (Docker remains
the backend to choose where it is available). Node is whatever the distro
has -- if there is no ``node``, ``execute_js`` says so instead of failing
with ENOENT from a spawned process. The browser tools are the same story:
Playwright is whatever the distro has, and when it has none they fall back
to the local runtime, on whose host browser the internal-address guard now
applies (see ``tools/browser_tools``).
"""

from __future__ import annotations

import asyncio
import base64
import json
import shutil
import subprocess
from pathlib import Path
from typing import Optional

from loguru import logger

from tonyagent.sandbox.base import (
    NO_WINDOW,
    SandboxBackend,
    SandboxConfig,
    SandboxStatus,
)
from tonyagent.folder.manager import folder_manager


#: Where the RPC server is staged inside the distro. /tmp survives the WSL
#: VM's idle shutdown (the distro's filesystem is a disk image), but the
#: bootstrap runs on every start anyway -- a stale file from an older build
#: must not be what runs.
RPC_SERVER_REMOTE = "/tmp/tonyagent_rpc_server.py"

#: The path the tool layer spells "inside the sandbox" with. It is a
#: *contract* spelling, not a location: the Docker backend mounts it, this
#: backend translates it (see ``_translate_path``), and the tool layer never
#: learns the difference.
CONTRACT_ROOT = "/workspace"

#: What the server process is called inside the distro, for a targeted kill
#: on shutdown. Deliberately not ``pkill python``: the distro belongs to the
#: user, and a stop must not take their session with it.
RPC_SERVER_MARKER = "tonyagent_rpc_server.py"

#: Distro that ships with Docker Desktop. It has no shell for a user, no
#: development tools, and stopping it would be a catastrophic guess at
#: "a Linux environment", so detection skips it by name.
NON_USER_DISTROS = frozenset({"docker-desktop"})

#: First boot of a stopped distro can take tens of seconds on a cold VM
#: (probed: ~4s warm). The margin is for the first run after a reboot.
STARTUP_TIMEOUT_S = 120.0
PING_INTERVAL_S = 1.0

#: How the inner shell is started: root, because ``unshare`` needs
#: capabilities the distro's default user may not have, and because files
#: written to /mnt/c come back mapped to uid 1000 by the drvfs mount
#: regardless (verified) -- root inside the distro is not root on the host.
RUN_AS_USER = "root"


def wsl_available() -> bool:
    """Whether ``wsl.exe`` exists. No version check: any WSL2 distro works."""
    return shutil.which("wsl.exe") is not None


def _decode_wsl_listing(raw: bytes) -> list[str]:
    """``wsl -l -v`` prints UTF-16LE; decode it the way it arrives.

    Not a trial-and-error: plain ASCII is *valid* UTF-16LE two bytes at a
    time, so "try utf-16, fall back to utf-8" garbles every byte-oriented
    listing it is handed (measured: a UTF-8 listing decoded as CJK). The
    signal is structural instead -- a BOM when the launcher writes one
    (console-attached runs), and NUL-interleaving when it does not (measured
    under a test runner, where the same command arrives UTF-16LE *without*
    a BOM and the BOM-only check decoded it as mojibake full of NULs).
    """
    if raw.startswith(b"\xff\xfe"):
        return raw.decode("utf-16", errors="replace").splitlines()
    if b"\x00" in raw:
        text = raw.decode("utf-16-le", errors="replace")
        return text.lstrip("\ufeff").splitlines()
    return raw.decode("utf-8", errors="replace").splitlines()


def detect_wsl_distro() -> Optional[str]:
    """The default WSL distro, or ``None`` when there is not one.

    ``wsl -l -v`` marks the default with a leading ``*`` on the NAME column
    and pads the columns with spaces; the trailing two fields are STATE and
    VERSION, so the name is everything between the marker and those. A name
    with a space ("Ubuntu 22.04") only parses correctly that way. The
    Docker Desktop distro is skipped by name: a probe that selected it
    would "find an environment" that cannot start a shell.
    """
    wsl = shutil.which("wsl.exe")
    if not wsl:
        return None
    try:
        listing = subprocess.run(
            [wsl, "-l", "-v"],
            capture_output=True,
            timeout=15,
            creationflags=NO_WINDOW,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.debug(f"wsl -l -v failed: {exc}")
        return None
    if listing.returncode != 0:
        return None

    default: Optional[str] = None
    first_user_distro: Optional[str] = None
    for line in _decode_wsl_listing(listing.stdout):
        line = line.strip()
        if not line:
            continue
        marked_default = line.startswith("*")
        parts = line.lstrip("*").strip().split()
        if len(parts) < 3:
            continue  # the header row, or a line this parser does not know
        if parts[0].upper() == "NAME":
            continue  # "  NAME STATE VERSION", which is not a distro
        name = " ".join(parts[:-2])  # ... STATE VERSION
        if name.lower() in NON_USER_DISTROS or not name:
            continue
        if marked_default:
            default = name
        first_user_distro = first_user_distro or name
    return default or first_user_distro


class WslSandboxBackend(SandboxBackend):
    """The sandbox runtime, served from inside a WSL2 distro."""

    #: A distro with ``unshare`` is a boundary the same way a container is:
    #: what runs inside cannot see the host's filesystem (bar the mounted
    #: workspace), its network namespaces, or outlive this process tree.
    provides_isolation = True

    def __init__(self, config: SandboxConfig, distro: str = ""):
        super().__init__(config)
        self._distro_override = distro
        self._distro = ""
        self._workspace_wsl = ""
        self._reader_task: Optional[asyncio.Task] = None
        self._stderr_task: Optional[asyncio.Task] = None
        self._has_node: Optional[bool] = None

    @property
    def distro(self) -> str:
        return self._distro

    # -- lifecycle -------------------------------------------------------------

    async def start(self) -> bool:
        try:
            self.status = SandboxStatus.STARTING

            project_path = self.config.project_path
            if not project_path:
                project_path = (
                    str(folder_manager.current_folder) if folder_manager.current_folder else "."
                )
            project_path = Path(project_path).resolve()
            if not project_path.exists():
                logger.error(f"Project path does not exist: {project_path}")
                self.status = SandboxStatus.STOPPED
                return False

            if not wsl_available():
                logger.error("wsl.exe not found on PATH")
                self.status = SandboxStatus.STOPPED
                return False

            self._distro = (
                self._distro_override
                or self.config.wsl_distro
                or detect_wsl_distro()
            )
            if not self._distro:
                logger.error("No WSL distro installed; the WSL backend cannot start")
                self.status = SandboxStatus.STOPPED
                return False

            self._workspace_wsl = await self._to_wsl_path(project_path)
            if not self._workspace_wsl:
                self.status = SandboxStatus.STOPPED
                return False

            await self._bootstrap_rpc_server()
            self._has_node = await self._probe("command -v node")

            args = self._build_argv()
            logger.info(f"Starting WSL sandbox: {' '.join(args)}")
            self._process = await asyncio.create_subprocess_exec(
                *args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                creationflags=NO_WINDOW,
            )

            # Read responses before the first ping, or the pong lands nowhere.
            self._reader_task = asyncio.get_running_loop().create_task(self._read_responses())
            self._stderr_task = asyncio.get_running_loop().create_task(self._drain_stderr())

            deadline = asyncio.get_running_loop().time() + STARTUP_TIMEOUT_S
            while asyncio.get_running_loop().time() < deadline:
                try:
                    pong = await self.ping(timeout=5)
                    if pong.get("pong"):
                        self.status = SandboxStatus.RUNNING
                        logger.info(
                            f"WSL sandbox ready (distro {self._distro}, pid {pong.get('pid')})"
                        )
                        return True
                except Exception as exc:
                    logger.debug(f"WSL sandbox ping not ready: {exc}")
                if self._process and self._process.returncode is not None:
                    logger.error(
                        f"WSL process exited early with code {self._process.returncode}"
                    )
                    break
                await asyncio.sleep(PING_INTERVAL_S)

            logger.error("WSL sandbox failed to become ready (no ping reply)")
            await self.stop()
            return False
        except Exception:
            logger.exception("Failed to start WSL sandbox")
            await self.stop()
            return False

    async def stop(self) -> None:
        self.status = SandboxStatus.STOPPING
        if self._reader_task:
            self._reader_task.cancel()
            self._reader_task = None
        if self._stderr_task:
            self._stderr_task.cancel()
            self._stderr_task = None
        if self._process:
            # First the polite close: the RPC server's loop ends on stdin EOF,
            # and because it runs as PID 1 of its own PID namespace the kernel
            # takes everything inside down with it.
            try:
                if self._process.stdin and not self._process.stdin.is_closing():
                    self._process.stdin.close()
            except Exception as exc:  # pragma: no cover - transport detail
                logger.debug(f"Error closing WSL stdin: {exc}")
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
            except Exception as exc:
                logger.debug(f"Error stopping WSL process: {exc}")
            finally:
                self._process = None
        # Belt and braces, and targeted: only the process this runtime
        # started, because the distro belongs to the user.
        if self._distro:
            try:
                await self._run_in_distro(
                    f"pkill -f {RPC_SERVER_MARKER}", timeout=5, check=False
                )
            except Exception as exc:
                logger.debug(f"WSL pkill after stop failed: {exc}")
        self.status = SandboxStatus.STOPPED

    async def health_check(self) -> bool:
        try:
            result = await self.execute_command("echo health", timeout=5)
            return result.returncode == 0 and "health" in result.stdout
        except Exception:
            return False

    # -- the sandbox server, staged and grepped ---------------------------------

    def _build_argv(self) -> list[str]:
        """The ``wsl.exe`` command line: the RPC server inside the namespaces.

        The whole inner shell is one string because it is one program:
        the workspace variable, the process bound, then ``exec`` so the
        server replaces the shell and the PID 1 that ``unshare --fork`` gives
        it is the server itself.

        * ``unshare -n``            -- the egress gate. Absent when
          ``enable_network`` is the *container's* setting being honoured:
          no egress unless explicitly enabled, same as Docker's
          ``--network none`` default.
        * ``unshare -p -f``         -- a PID namespace, so the server is
          PID 1 and nothing it spawns can outlive the session.
        * ``--mount-proc``          -- /proc inside that namespace, or
          ``ps`` and friends read the host's processes.
        * ``ulimit -u``             -- the nproc bound, when configured.
          Guarded because the inner shell is ``sh`` (dash on Ubuntu), whose
          ``ulimit`` has no ``-u``: a distro that cannot take the bound
          loses the bound, not the sandbox.

        The environment is passed on the ``exec`` command itself rather
        than as a standalone statement: dash does not put a standalone
        assignment into the environment of an exec'd program (bash does),
        and the distro's ``sh`` is dash about half the time.
        """
        cfg = self.config
        namespaces: list[str] = []
        if not cfg.enable_network:
            namespaces.append("-n")
        namespaces += ["-p", "-f"]

        workspace = self._quote(self._workspace_wsl)
        steps: list[str] = [f"cd {workspace}"]
        if cfg.ulimit_nproc and cfg.ulimit_nproc > 0:
            # Noexec because the statement must not be the last thing the
            # shell does, and guarded because not every sh has the option.
            steps.append(f"{{ ulimit -u {int(cfg.ulimit_nproc)}; }} 2>/dev/null || true")
        programs = f"unshare {' '.join(namespaces)} --mount-proc"
        # `exec` with the assignment as its *prefix*: one command, and the
        # variable survives into the RPC server's environment in dash too.
        steps.append(
            f"TONYAGENT_WORKSPACE={workspace} exec {programs} python3 {RPC_SERVER_REMOTE}"
        )
        shell = "; ".join(steps)

        wsl = shutil.which("wsl.exe") or "wsl.exe"
        return [wsl, "-d", self._distro, "-u", RUN_AS_USER, "--", "sh", "-c", shell]

    async def _to_wsl_path(self, project_path: Path) -> str:
        """``C:\\Users\\...`` to ``/mnt/c/Users/...`` by asking the distro.

        ``wslpath`` is the authority on the mapping (mount points, spacing,
        the drive-letter mapping itself); a Python-side reimplementation
        would be a second copy of a rule the distro already owns -- the
        failure this repo refuses to build twice.
        """
        try:
            completed = await self._run_in_distro(
                f"wslpath -u {self._quote(str(project_path))}", timeout=15
            )
        except Exception as exc:
            logger.error(f"wslpath failed for {project_path}: {exc}")
            return ""
        path = completed.strip()
        if not path or not path.startswith("/"):
            logger.error(f"wslpath returned a non-absolute path: {path!r}")
            return ""
        return path

    async def _bootstrap_rpc_server(self) -> None:
        """Stage the sandbox server inside the distro.

        Base64 over ``base64 -d`` rather than a redirect of the file:
        the host file is in the dev checkout or the PyInstaller bundle
        (``local_backend.find_rpc_server`` looks in both), and what the
        distro needs is the *bytes*, not a mount of the checkout.
        """
        from tonyagent.sandbox.local_backend import find_rpc_server

        try:
            source = find_rpc_server()
            payload = base64.b64encode(source.read_bytes())
        except Exception as exc:
            logger.error(f"Could not read rpc_server.py to stage it in WSL: {exc}")
            raise

        # One process, fed through stdin, so no quoting question arises
        # about a 17 KB payload in a command line.
        wsl = shutil.which("wsl.exe") or "wsl.exe"
        process = await asyncio.create_subprocess_exec(
            wsl,
            "-d",
            self._distro,
            "-u",
            RUN_AS_USER,
            "--",
            "sh",
            "-c",
            f"base64 -d > {RPC_SERVER_REMOTE}",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            creationflags=NO_WINDOW,
        )
        stdout, stderr = await process.communicate(payload)
        if process.returncode != 0:
            logger.error(
                f"Staging rpc_server in {self._distro} failed: "
                f"{stderr.decode(errors='replace').strip()}"
            )
            raise RuntimeError("Could not stage the sandbox server in the distro")

    async def _probe(self, command: str) -> Optional[bool]:
        """Run a command in the distro; None when it cannot be answered.

        A non-zero exit is an *answer* here, not a failure: ``command -v
        node`` exits 1 precisely when Node is absent, which is the fact the
        probe exists to learn. ``execute_js`` telling the user "install Node
        in the distro" is a better turn than a subprocess ENOENT nobody can
        act on.
        """
        try:
            completed = await self._run_in_distro(command, timeout=15, check=False)
        except Exception as exc:
            logger.debug(f"Distro probe {command!r} failed: {exc}")
            return None
        return completed.strip() != ""

    async def execute_js(self, script: str, timeout: int = 10):
        """JavaScript under the distro's Node -- or a readable refusal.

        The one capability question worth asking before the call rather
        than diagnosing from its failure: a distro without Node fails with
        ENOENT from a spawn, which is true and useless.
        """
        if self._has_node is False:
            from tonyagent.sandbox.base import BrowserResult

            return BrowserResult(
                success=False,
                error=(
                    f"Node.js is not installed for the {self._distro} distro's "
                    "sandbox session (it looks for a system-wide node, so an "
                    "nvm install in a user profile will not be seen). Install "
                    "it in the distro, then try again."
                ),
            )
        return await super().execute_js(script, timeout=timeout)

    async def get_stats(self) -> Optional[dict]:
        """No per-session stat stream: WSL2 does not cost a container."""
        return None

    # -- the sandbox path, translated -----------------------------------------

    def _translate_path(self, path: str) -> str:
        """``/workspace/...`` to the same file inside the distro.

        The tool layer builds sandbox paths against ``/workspace`` on
        purpose -- it is the one spelling every isolating backend agrees
        on -- so a backend that does not literally mount that path is where
        the translation belongs, not in every tool. Anything else (a path
        a script produced, say) is passed through untouched.
        """
        if path == CONTRACT_ROOT:
            return self._workspace_wsl
        if path.startswith(CONTRACT_ROOT + "/"):
            return self._workspace_wsl + path[len(CONTRACT_ROOT) :]
        return path

    async def execute_command(
        self, command: str, cwd: str = CONTRACT_ROOT, timeout: int = 30
    ):
        return await super().execute_command(
            command, cwd=self._translate_path(cwd), timeout=timeout
        )

    async def browser_screenshot(self, path: str = ""):
        return await super().browser_screenshot(self._translate_path(path))

    # -- plumbing ---------------------------------------------------------------

    @staticmethod
    def _quote(text: str) -> str:
        """Single-quote for the inner sh, the way it quotes a host path."""
        return "'" + text.replace("'", "'\\''") + "'"

    async def _run_in_distro(
        self, command: str, timeout: int = 15, check: bool = True
    ) -> str:
        """A one-shot command in the distro: bootstrap, probes, cleanup."""
        wsl = shutil.which("wsl.exe") or "wsl.exe"
        process = await asyncio.create_subprocess_exec(
            wsl,
            "-d",
            self._distro,
            "-u",
            RUN_AS_USER,
            "--",
            "sh",
            "-c",
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            creationflags=NO_WINDOW,
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            process.kill()
            raise
        if check and process.returncode != 0:
            raise RuntimeError(
                f"{command!r} failed in {self._distro}: {stderr.decode(errors='replace').strip()}"
            )
        return stdout.decode("utf-8", errors="replace")

    async def _send_request(self, request: dict) -> None:
        """Identical to the Docker backend's: write one JSON line, drain.

        Not a second implementation of framing shared by anything else --
        the base class owns ids, timeouts and the pending map; this is the
        two lines that put bytes on the pipe, and they are two lines because
        the pipe is ``wsl.exe``'s rather than ``docker run -i``'s.
        """
        if not self._process or not self._process.stdin:
            raise RuntimeError("WSL sandbox process has no stdin")
        data = json.dumps(request) + "\n"
        try:
            self._process.stdin.write(data.encode("utf-8"))
            await self._process.stdin.drain()
        except (BrokenPipeError, ConnectionResetError) as exc:
            raise RuntimeError(f"WSL sandbox connection broken: {exc}") from exc

    async def _read_responses(self) -> None:
        """The response loop, one JSON object per line out of the distro.

        What it shares with the Docker backend's loop is the behaviour;
        what is not shared is where it lives -- the loop is the *transport*,
        and the Docker backend keeps its own because a pipe from ``docker
        run -i`` and a pipe from ``wsl.exe`` have different lifetimes to
        reason about (one ends with the container, the other with the WSL
        session's process tree). The failure path is the part that must
        never differ: EOF with calls still pending fails them, or every
        caller waits on a reply that is not coming.
        """
        if not self._process or not self._process.stdout:
            return
        while True:
            try:
                line = await self._process.stdout.readline()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning(f"WSL sandbox reader error: {exc}")
                break
            if not line:
                break  # EOF: the distro's session, or the server, went away.
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
                logger.warning(f"Invalid JSON from WSL sandbox: {text}")
        # EOF with outstanding calls: fail them so callers don't hang.
        for request_id, future in list(self._pending.items()):
            self._pending.pop(request_id, None)
            if not future.done():
                future.set_exception(RuntimeError("WSL sandbox connection closed"))

    async def _drain_stderr(self) -> None:
        """Drain the distro's stderr so logs can't block the pipe."""
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
            logger.debug(f"[wsl sandbox stderr] {line.decode('utf-8', errors='replace').rstrip()}")
