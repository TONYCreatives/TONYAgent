"""What the installed app needs that a source checkout hands it for free.

Two properties of the frozen build are invisible to every import graph and to
every test that runs out of the source tree, and both were found the same way --
by running the installed app and watching it fail.

**Files the code opens by path.** ``docker/sandbox/rpc_server.py`` is a script
rather than a library: the container runs it as its main process, the local
runtime execs it inside the agent's own process, and the WSL backend stages it
into the distro. All three find it through ``local_backend.find_rpc_server``.
Nothing *imports* it, so PyInstaller never copied it, so the installed app had
no runtime at all -- and the project-folder picker reads "no runtime" as "the
folder did not take", which is why picking one looked like it did nothing.

**Console programs spawned by a windowed process.** The core has no console of
its own, so Windows gives every console program it spawns a fresh console
*window*. The host's own spawns asked not to show one (``window/core.py``,
``window/update.py``); the sandbox's did not, so a folder change put fourteen
windows on screen -- seven ``wsl.exe`` runs, each with a Windows Terminal window
and a console host window -- appearing and vanishing over about eight seconds.

Neither is observable from the checkout, which is the whole reason for this
file: ``python.exe`` has a console to share, and the script is right there on
disk. The tests below assert the two facts that do not survive the freeze --
where the spec puts the script, and what every spawn in the sandbox asks for.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SPEC = REPO / "packaging" / "TONYAgent.spec"
SANDBOX = REPO / "src" / "tonyagent" / "sandbox"
RPC_SERVER_SOURCE = REPO / "docker" / "sandbox" / "rpc_server.py"

#: Calls that start a program. Every one of these in the sandbox package runs
#: inside the core, which is a windowed process.
SPAWN_CALLS = frozenset(
    {"subprocess.run", "subprocess.Popen", "asyncio.create_subprocess_exec"}
)

#: The one backend the console rule does not apply to.
#:
#: `wsb_backend` is a documented stub -- "NOT IMPLEMENTED. Every transport method
#: below is a `pass` ... so this cannot start and cannot serve a request" -- and
#: what it spawns is `wt.exe`, a *GUI* terminal. `CREATE_NO_WINDOW` suppresses
#: the console Windows gives a console program; it does nothing to a window a
#: GUI program opens for itself, so adding the flag there would look like a fix
#: and change nothing. Left alone rather than half-fixed: finishing that backend
#: is the job, and the window question belongs to whoever finishes it.
STUB_BACKENDS = frozenset({"wsb_backend.py"})


# --- the file the bundle has to carry ---------------------------------------


def _bundle_dir_for_rpc_server(monkeypatch) -> str:
    """The bundle-relative directory ``find_rpc_server`` looks in.

    Read out of ``_candidate_paths`` rather than written here. The bug was the
    spec and that list disagreeing, so a literal in both would let them drift
    together and still pass -- which is the one thing this test must not do.
    """
    from tonyagent.sandbox import local_backend

    # A `sys._MEIPASS` that cannot exist, so the candidate is recognisable and
    # nothing on this machine answers to it.
    frozen_root = Path("Z:/tonyagent-bundle-that-is-not-there")
    monkeypatch.setattr(local_backend.sys, "_MEIPASS", str(frozen_root), raising=False)

    under_meipass = [
        candidate
        for candidate in local_backend._candidate_paths()
        if frozen_root in candidate.parents
    ]
    assert under_meipass, (
        "find_rpc_server no longer looks under sys._MEIPASS, so a frozen build "
        "has no path to the script the bundle is supposed to carry"
    )
    relative = under_meipass[0].relative_to(frozen_root)
    assert relative.name == "rpc_server.py"
    return relative.parent.as_posix()


def test_the_rpc_server_is_a_file_on_disk():
    """The spec maps a real file, not a path that used to be one."""
    assert RPC_SERVER_SOURCE.is_file(), (
        "docker/sandbox/rpc_server.py is gone. The Dockerfile runs it, the "
        "local runtime execs it and the WSL backend stages it; moving it means "
        "moving the path in packaging/TONYAgent.spec with it."
    )


def test_the_spec_carries_the_rpc_server_where_the_code_looks_for_it(monkeypatch):
    destination = _bundle_dir_for_rpc_server(monkeypatch)

    entry = re.search(
        r"\(\s*str\(ROOT\s*/\s*\"docker\"\s*/\s*\"sandbox\"\s*/\s*\"rpc_server\.py\"\)"
        r"\s*,\s*\"([^\"]+)\"\s*\)",
        SPEC.read_text(encoding="utf-8"),
    )
    assert entry, (
        "packaging/TONYAgent.spec no longer ships docker/sandbox/rpc_server.py. "
        "Nothing imports that file, so PyInstaller cannot discover it, and "
        "without it the installed app cannot start the local or WSL runtime -- "
        "which is a folder picker that silently keeps the old folder."
    )
    assert entry.group(1) == destination, (
        f"the spec installs the rpc server into {entry.group(1)!r} but "
        f"find_rpc_server looks in {destination!r} when frozen"
    )


# --- the children that must not get a console -------------------------------


def _dotted(node: ast.expr) -> str:
    """``subprocess.run`` for the AST of ``subprocess.run(...)``."""
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))


def _spawn_calls(path: Path) -> list[ast.Call]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and _dotted(node.func) in SPAWN_CALLS
    ]


def test_every_console_program_the_sandbox_spawns_is_asked_not_to_show_one():
    """The audit, rather than a list of the sites that were fixed.

    A hand-written list of call sites is only as good as the last person who
    remembered to update it -- the same argument as
    `app/src/reducedMotion.test.ts` -- so this walks the package instead. A new
    spawn that forgets the flag is a black rectangle appearing and vanishing on
    somebody's screen, once per folder change, and nothing else would say so.
    """
    checked: list[str] = []
    missing: list[str] = []

    for path in sorted(SANDBOX.glob("*.py")):
        if path.name in STUB_BACKENDS:
            continue
        for call in _spawn_calls(path):
            where = f"{path.name}:{call.lineno}"
            checked.append(where)
            flag = next(
                (kw.value for kw in call.keywords if kw.arg == "creationflags"), None
            )
            if not (isinstance(flag, ast.Name) and flag.id == "NO_WINDOW"):
                missing.append(where)

    assert len(checked) >= 6, (
        f"the audit found {len(checked)} spawns, which is fewer than the package "
        f"has: {checked}. A renamed helper would silence this test rather than "
        "fail it."
    )
    assert not missing, (
        "these spawns do not pass creationflags=NO_WINDOW, so the installed app "
        "shows a console window for each one: " + ", ".join(missing)
    )


def test_the_flag_is_the_windows_one():
    """``NO_WINDOW`` is a real constant, not a zero that quietly does nothing.

    On Windows the value is `CREATE_NO_WINDOW`; on POSIX the same expression is
    0, which is the correct "no such thing to suppress" rather than a bug. This
    pins the Windows side so a typo in the constant's name cannot pass on the
    platform it exists for.
    """
    import subprocess

    from tonyagent.sandbox.base import NO_WINDOW

    expected = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    assert NO_WINDOW == expected
    if hasattr(subprocess, "CREATE_NO_WINDOW"):
        assert NO_WINDOW != 0
