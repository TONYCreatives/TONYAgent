"""The build scripts are logic, and until now none of it was tested.

``scripts/build_state.ps1`` decides what to build and ``Build TONYAgent.bat``
acts on that decision. Both were wrong in ways that only running them showed,
and every one of those bugs was invisible to the 580 other tests because none
of them touch the build:

- the resource compiler was found on some runs and not others, with ``where
  rc.exe`` answering in the same shell moments earlier;
- the stage list was read with ``%`` on some lines and ``!`` on others, so
  "Building:" printed nothing and then dispatched on a list that was not empty;
- the file had LF endings, so cmd lost a ``goto`` label outright;
- ``call "Build TONYAgent.bat"`` silently did not resolve, so a launcher
  introduced to rebuild things rebuilt nothing;
- ``__pycache__`` counted as a source, so running the tests made every launch
  re-freeze 45 MB of Python.

So these run the real scripts against a fake tree in a temporary directory.
The batch file is copied with its three build commands replaced by echoes, so
the stage selection is exercised for what it costs: no vite, no PyInstaller,
no cargo. The rest of the file -- the dispatch, the ``/q`` switch, the error
branches, the CRLF endings -- is the real thing.

Windows only, because a .bat file is.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
BUILD_STATE = REPO / "scripts" / "build_state.ps1"
BUILD_BATCH = REPO / "Build TONYAgent.bat"
LAUNCHER = REPO / "Start TONYAgent (Prebuilt).bat"
TAURI_LAUNCHER = REPO / "Start TONYAgent (Tauri).bat"

pytestmark = pytest.mark.skipif(
    sys.platform != "win32",
    reason="the build scripts are a .bat file and Windows PowerShell",
)

# Every path build_state.ps1 knows about, with the mtimes a tree that is
# entirely current would have: sources older than the outputs they produce.
SOURCES = (
    "app/src/Composer.tsx",
    "app/index.html",
    "app/package.json",
    "app/vite.config.ts",
    "src/tonyagent/core/conversations.py",
    "pyproject.toml",
    "scripts/sidecar.spec",
    "docker/Dockerfile",
    "app/src-tauri/src/main.rs",
    "app/src-tauri/tauri.conf.json",
    "app/src-tauri/Cargo.toml",
    "app/src-tauri/build.rs",
    "app/src-tauri/capabilities/default.json",
)
OUTPUTS = (
    "app/dist/index.html",
    # The name is globbed, not hardcoded: the target triple is read off the host.
    "app/src-tauri/binaries/tonyagent-core-x86_64-pc-windows-msvc.exe",
    "app/src-tauri/target/release/tonyagent-app.exe",
)

AN_HOUR = 3600


def _write(path: Path, text: str = "x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _age(path: Path, seconds: float) -> None:
    """Backdate a file, so "newer than" is a fact rather than a hope."""
    when = os.stat(path).st_mtime - seconds
    os.utime(path, (when, when))


def _make_current(root: Path) -> Path:
    """A repository in which nothing needs building."""
    for relative in SOURCES:
        _write(root / relative)
    for relative in OUTPUTS:
        _write(root / relative)
    for relative in SOURCES:
        _age(root / relative, 2 * AN_HOUR)
    return root


def _stages(root: Path) -> list[str]:
    """Ask the real script what is stale in this tree."""
    done = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(BUILD_STATE),
            "-Root",
            str(root),
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert done.returncode == 0, done.stderr
    return done.stdout.split()


# --------------------------------------------------------------------------
# scripts/build_state.ps1: the decision
# --------------------------------------------------------------------------


def test_a_current_tree_needs_nothing(tmp_path):
    assert _stages(_make_current(tmp_path)) == []


def test_a_deleted_exe_needs_the_app(tmp_path):
    root = _make_current(tmp_path)
    (root / "app/src-tauri/target/release/tonyagent-app.exe").unlink()

    assert _stages(root) == ["app"]


def test_an_empty_tree_needs_every_stage_in_dependency_order(tmp_path):
    # The order is the caller's contract: it runs the list top to bottom.
    assert _stages(tmp_path) == ["frontend", "sidecar", "app"]


def test_an_edited_react_file_needs_the_frontend_and_the_app(tmp_path):
    root = _make_current(tmp_path)
    _write(root / "app/src/Composer.tsx", "edited")

    assert _stages(root) == ["frontend", "app"]


def test_an_edited_python_file_needs_the_sidecar_and_the_app(tmp_path):
    root = _make_current(tmp_path)
    _write(root / "src/tonyagent/core/conversations.py", "edited")

    assert _stages(root) == ["sidecar", "app"]


def test_an_edited_rust_file_needs_only_the_app(tmp_path):
    root = _make_current(tmp_path)
    _write(root / "app/src-tauri/src/main.rs", "edited")

    assert _stages(root) == ["app"]


def test_bytecode_is_not_a_source(tmp_path):
    """The .pyc regression.

    Running the test suite rewrites ``__pycache__`` under ``src/``, which made
    the sidecar look stale after every pytest run -- so every launch re-froze
    45 MB of Python to pick up changes nobody had made.
    """
    root = _make_current(tmp_path)
    _write(root / "src/tonyagent/core/__pycache__/conversations.cpython-313.pyc")
    _write(root / ".pytest_cache/CACHEDIR.TAG")

    assert _stages(root) == []


def test_a_bundle_nothing_has_embedded_needs_the_app(tmp_path):
    """`tauri build` embeds app/dist, so a newer bundle is not in the binary.

    Skipping stage 3 here is the bug this guards: the app starts, the file on
    disk is fresh, and the application is still the previous build.
    """
    root = _make_current(tmp_path)
    _write(root / "app/dist/index.html", "rebuilt")

    assert _stages(root) == ["app"]


def test_a_sidecar_nothing_has_copied_needs_the_app(tmp_path):
    """`tauri build` is what puts the sidecar next to the exe.

    Measured, not theorised: after a sidecar-only run the file in binaries/
    was minutes old and the one the app spawns was a day old, and the build
    script had said it was finished.
    """
    root = _make_current(tmp_path)
    _write(root / "app/src-tauri/binaries/tonyagent-core-x86_64-pc-windows-msvc.exe", "rebuilt")

    assert _stages(root) == ["app"]


def test_a_missing_sidecar_binary_needs_the_sidecar_and_the_app(tmp_path):
    root = _make_current(tmp_path)
    (root / "app/src-tauri/binaries/tonyagent-core-x86_64-pc-windows-msvc.exe").unlink()

    assert _stages(root) == ["sidecar", "app"]


# --------------------------------------------------------------------------
# Build TONYAgent.bat: the dispatch
# --------------------------------------------------------------------------

_BUILD_COMMANDS = {
    "call npm run build": "echo STUB-frontend",
    "python scripts\\build_sidecar.py": "echo STUB-sidecar",
    "call npm run tauri:build": "echo STUB-app",
}


def _stub(text: str, fail_frontend: bool = False) -> str:
    for real, stub in _BUILD_COMMANDS.items():
        assert real in text, f"the build script no longer runs {real!r}"
        text = text.replace(real, "cmd /c exit 3" if fail_frontend and real.startswith("call npm") else stub)
    return text


def _bat_fixture(root: Path, fail_frontend: bool = False) -> Path:
    """A repository the batch scripts can run in without building anything.

    The real build_state.ps1, so the decision under test is the real one, and a
    stand-in for the Windows SDK, so the test does not need one installed.
    """
    _make_current(root)

    scripts = root / "scripts"
    scripts.mkdir(exist_ok=True)
    shutil.copy(BUILD_STATE, scripts / "build_state.ps1")

    rc = root / "fake-sdk" / "rc.exe"
    _write(rc)
    (scripts / "find_windows_sdk.ps1").write_text(
        f'Write-Output "{rc}"\n', encoding="utf-8"
    )

    # Bytes, not text: reading as text would normalise the CRLF endings that
    # cmd needs to find a goto label, and the stub would fail for a reason
    # that has nothing to do with what it is testing.
    stubbed = _stub(BUILD_BATCH.read_bytes().decode("utf-8"), fail_frontend)
    # Two names for one stub: the spaced one is what the launcher calls, which
    # is the whole point of testing it there, and the plain one keeps Python
    # out of cmd's quoting rules for the direct runs.
    (root / "Build TONYAgent.bat").write_bytes(stubbed.encode("utf-8"))
    (root / "build.bat").write_bytes(stubbed.encode("utf-8"))
    return root


def _launcher_fixture(root: Path, fail_frontend: bool = False) -> Path:
    _bat_fixture(root, fail_frontend)

    launcher = LAUNCHER.read_bytes().decode("utf-8")
    for fragment in ('start "" "%APP%"', 'call "%~dp0Build TONYAgent.bat" /q'):
        assert fragment in launcher, f"the launcher no longer contains {fragment!r}"
    # The launcher would start the real application, which is not this test's
    # business; everything up to that point is.
    launcher = launcher.replace('start "" "%APP%"', 'echo STUB-start "%APP%"')
    path = root / "launcher.bat"
    path.write_bytes(launcher.encode("utf-8"))
    return path


def _run(batch: Path, *args: str) -> subprocess.CompletedProcess[str]:
    # ".\name" rather than "name": cmd only searches the current directory
    # when the path says so, and answers "is not recognized" otherwise.
    return subprocess.run(
        ["cmd", "/c", f".\\{batch.name}", *args],
        cwd=batch.parent,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=300,
    )


def test_the_batch_builds_nothing_when_the_tree_is_current(tmp_path):
    done = _run(_bat_fixture(tmp_path) / "build.bat")

    assert done.returncode == 0, done.stdout + done.stderr
    assert "Everything is up to date" in done.stdout
    assert "STUB-" not in done.stdout


def test_the_batch_runs_the_frontend_and_the_app_but_not_the_sidecar(tmp_path):
    root = _bat_fixture(tmp_path)
    _write(root / "app/src/Composer.tsx", "edited")

    done = _run(root / "build.bat")

    assert done.returncode == 0, done.stdout + done.stderr
    assert "STUB-frontend" in done.stdout
    assert "STUB-app" in done.stdout
    assert "STUB-sidecar" not in done.stdout


def test_the_batch_runs_the_sidecar_and_the_app_but_not_the_frontend(tmp_path):
    root = _bat_fixture(tmp_path)
    _write(root / "src/tonyagent/core/conversations.py", "edited")

    done = _run(root / "build.bat")

    assert done.returncode == 0, done.stdout + done.stderr
    assert "STUB-sidecar" in done.stdout
    assert "STUB-app" in done.stdout
    assert "STUB-frontend" not in done.stdout


def test_the_batch_waits_for_a_key_by_default(tmp_path):
    """Someone who double-clicked it is standing in front of it."""
    root = _bat_fixture(tmp_path)
    _write(root / "app/src/Composer.tsx", "edited")

    done = _run(root / "build.bat")

    assert "Press any key" in done.stdout


def test_the_batch_does_not_wait_for_a_key_when_asked_to_be_quiet(tmp_path):
    """The launcher calls it with /q and has a window of its own to close."""
    root = _bat_fixture(tmp_path)
    _write(root / "app/src/Composer.tsx", "edited")

    done = _run(root / "build.bat", "/q")

    assert done.returncode == 0, done.stdout + done.stderr
    assert "Press any key" not in done.stdout


def test_a_failed_stage_keeps_the_previous_binary(tmp_path):
    """If the build breaks there is still a build to run."""
    root = _bat_fixture(tmp_path, fail_frontend=True)
    exe = root / "app/src-tauri/target/release/tonyagent-app.exe"
    before = exe.stat().st_mtime_ns
    _write(root / "app/src/Composer.tsx", "edited")

    done = _run(root / "build.bat", "/q")

    assert done.returncode == 1
    assert "The build failed" in done.stdout
    assert "The previous build is still in place" in done.stdout
    assert exe.exists()
    assert exe.stat().st_mtime_ns == before


def test_the_batch_finishes_by_pointing_at_the_launcher(tmp_path):
    # Not /q: that closing hint belongs to the person who double-clicked the
    # build script, and the launcher is already on its way to starting it.
    root = _bat_fixture(tmp_path)
    _write(root / "app/src/Composer.tsx", "edited")

    done = _run(root / "build.bat")

    assert 'Start it with "Start TONYAgent (Prebuilt).bat"' in done.stdout


# --------------------------------------------------------------------------
# Start TONYAgent (Prebuilt).bat: the wiring
# --------------------------------------------------------------------------


def test_the_launcher_starts_without_building_when_the_tree_is_current(tmp_path):
    done = _run(_launcher_fixture(tmp_path))

    assert done.returncode == 0, done.stdout + done.stderr
    assert "STUB-start" in done.stdout
    assert "STUB-" not in done.stdout.replace("STUB-start", "")
    assert "Started." in done.stdout


def test_the_launcher_rebuilds_what_is_stale_before_starting(tmp_path):
    """The regression: `call "Build TONYAgent.bat"` did not resolve, so the
    launcher printed nothing about a rebuild, started the old build, and the
    user was none the wiser."""
    root = _launcher_fixture(tmp_path).parent
    _write(root / "src/tonyagent/core/conversations.py", "edited")

    done = _run(root / "launcher.bat")

    assert done.returncode == 0, done.stdout + done.stderr
    assert "The build is behind the source" in done.stdout
    assert "STUB-sidecar" in done.stdout
    assert "STUB-app" in done.stdout
    assert "STUB-start" in done.stdout
    assert "Started." in done.stdout


def test_the_launcher_still_starts_the_previous_build_when_the_rebuild_fails(tmp_path):
    """Losing the ability to run the app at all is the worse outcome."""
    root = _launcher_fixture(tmp_path, fail_frontend=True).parent
    _write(root / "app/src/Composer.tsx", "edited")

    done = _run(root / "launcher.bat")

    assert done.returncode == 0, done.stdout + done.stderr
    assert "The rebuild failed" in done.stdout
    assert "STUB-start" in done.stdout
    assert "Started the previous build" in done.stdout


def test_the_launcher_reports_when_there_is_nothing_to_start(tmp_path):
    root = _launcher_fixture(tmp_path).parent
    (root / "app/src-tauri/target/release/tonyagent-app.exe").unlink()

    done = _run(root / "launcher.bat")

    # With no exe at all the app stage is stale, so the stub "rebuilds" and
    # still produces nothing. The launcher must say so rather than start
    # nothing and report success.
    assert "STUB-app" in done.stdout
    assert "STUB-start" not in done.stdout
    assert "There is nothing to start" in done.stdout
    assert done.returncode == 1


# --------------------------------------------------------------------------
# Line endings, which are part of correctness and not formatting
# --------------------------------------------------------------------------


def _tracked_batch_files() -> list[Path]:
    git = shutil.which("git")
    if git is None:
        pytest.skip("git is not on PATH")
    done = subprocess.run(
        [git, "ls-files", "*.bat"], cwd=REPO, capture_output=True, text=True, timeout=60
    )
    assert done.returncode == 0, done.stderr
    # Split by line, not by whitespace: two of these names contain a space.
    return [REPO / line for line in done.stdout.splitlines() if line.strip()]


def test_every_batch_file_has_crlf_endings():
    """Not a style preference. See .gitattributes for the measurement.

    With LF endings the build script resolves :build_frontend and :build_app
    but not :build_sidecar, so the sidecar leg stops dead after printing
    "Building: sidecar app" and the only complaint lands on stderr. Five of
    the six paths through the same file behave identically either way, which
    is what makes it worth a test rather than a note: the file looks fine
    right up until a particular label stops resolving.
    """
    offenders = []
    for path in _tracked_batch_files():
        data = path.read_bytes()
        bare = data.count(b"\n") - data.count(b"\r\n")
        if bare:
            offenders.append(f"{path.name}: {bare} bare LF")

    assert offenders == []


def test_the_repository_pins_batch_line_endings():
    """Because whether the file above is right depends on the machine."""
    git = shutil.which("git")
    if git is None:
        pytest.skip("git is not on PATH")

    for path in _tracked_batch_files():
        done = subprocess.run(
            [git, "check-attr", "eol", "--", path.relative_to(REPO).as_posix()],
            cwd=REPO,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert done.returncode == 0, done.stderr
        assert done.stdout.strip().endswith(": crlf"), done.stdout


def test_the_tauri_launcher_walks_every_label(tmp_path):
    """The other launcher, which had thirteen gotos and no coverage at all.

    It is the dev loop, so it cannot be exercised for real here -- `tauri dev`
    would sit there running -- but the parts that break silently are the
    label chain and the prerequisite checks, and both are reachable with the
    two commands stubbed out.
    """
    cargo = shutil.which("cargo")
    if cargo is None:
        fallback = Path(os.environ.get("USERPROFILE", "")) / ".cargo/bin/cargo.exe"
        if not fallback.exists():
            pytest.skip("cargo is not installed, so the launcher stops early by design")
        cargo = str(fallback)

    for tool in ("python", "node", "npm"):
        if shutil.which(tool) is None:
            pytest.skip(f"{tool} is not on PATH, so the launcher stops early by design")

    root = _make_current(tmp_path)
    root = _bat_fixture(root)

    launcher = TAURI_LAUNCHER.read_bytes().decode("utf-8")
    for real, stub in (
        ("python scripts\\build_sidecar.py", "rem stubbed"),
        ("call npm run tauri:dev", "echo STUB-dev"),
    ):
        assert real in launcher, f"the launcher no longer contains {real!r}"
        launcher = launcher.replace(real, stub)
    launcher = launcher.replace("\npause", "\nrem pause")
    path = root / "tauri.bat"
    path.write_bytes(launcher.encode("utf-8"))

    environment = dict(os.environ)
    environment["PATH"] = str(Path(cargo).parent) + os.pathsep + environment["PATH"]
    done = subprocess.run(
        ["cmd", "/c", ".\\tauri.bat"],
        cwd=root,
        env=environment,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert done.returncode == 0, done.stdout + done.stderr
    assert "STUB-dev" in done.stdout
    assert "cannot find the batch label" not in done.stderr