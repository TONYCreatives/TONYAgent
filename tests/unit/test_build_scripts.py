"""The build scripts are logic, and none of it is exercised by building.

``scripts/build_state.ps1`` decides what to build and ``Build TONYAgent.bat``
acts on that decision. Both were wrong in ways that only running them showed,
and every one of those bugs was invisible to the rest of the suite because none
of it touches the build:

- the stage list was read with ``%`` on some lines and ``!`` on others, so
  "Building:" printed nothing and then dispatched on a list that was not empty;
- the file had LF endings, so cmd lost a ``goto`` label outright;
- ``call "Build TONYAgent.bat"`` silently did not resolve, so a launcher
  introduced to rebuild things rebuilt nothing;
- ``__pycache__`` counted as a source, so running the tests made every launch
  rebuild something nobody had edited.

So these run the real scripts against a fake tree in a temporary directory. The
batch file is copied with its one build command replaced by an echo, so the stage
selection is exercised for what it costs: no vite, no npm, no minutes. The rest
of the file -- the dispatch, the ``/q`` switch, the error branches, the CRLF
endings -- is the real thing.

**The stage count changed, and the shape of this file changed with it.** There
used to be three stages and a dependency chain between them: the bundle, a frozen
Python core, and a Rust shell that embedded both. There is one stage now --
``app/dist`` -- because ``python -m tonyagent.window`` reads the bundle at
runtime instead of embedding it. That is what the new tests are really pinning:
editing a Python file must *not* rebuild the frontend, because nothing about the
frontend depends on it any more.

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

pytestmark = pytest.mark.skipif(
    sys.platform != "win32",
    reason="the build scripts are a .bat file and Windows PowerShell",
)

# Every path build_state.ps1 knows about, with the mtimes a tree that is entirely
# current would have: sources older than the output they produce.
SOURCES = (
    "app/src/Composer.tsx",
    "app/index.html",
    "app/package.json",
    "app/vite.config.ts",
)
OUTPUT = "app/dist/index.html"

#: Paths the frontend does *not* depend on, so touching one must change nothing.
#: The Python core is the interesting entry: it was stage 2's input, and the
#: window reads it at runtime now, so a rebuild would be pure waste.
NOT_SOURCES = (
    "src/tonyagent/core/conversations.py",
    "src/tonyagent/window/host.py",
    "pyproject.toml",
    "tests/unit/test_build_scripts.py",
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
    """A repository in which nothing needs building.

    The *output* is backdated as well as the sources, and that is a fix for a
    real flake rather than tidiness. `_write`ing an "edit" leaves its timestamp a
    few milliseconds after the output's, and that is close enough for the two to
    compare equal -- at which point `-gt` says the tree is current and a test
    that expects a rebuild fails. It failed a different handful of times each
    run, which is what a millisecond-wide margin looks like from the outside.

    An hour of separation in the direction the test needs is a fact rather than a
    coin toss.
    """
    for relative in SOURCES:
        _write(root / relative)
    _write(root / OUTPUT)
    for relative in SOURCES:
        _age(root / relative, 3 * AN_HOUR)
    _age(root / OUTPUT, AN_HOUR)
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


def test_an_empty_tree_needs_the_frontend(tmp_path):
    assert _stages(tmp_path) == ["frontend"]


def test_an_edited_react_file_needs_the_frontend(tmp_path):
    root = _make_current(tmp_path)
    _write(root / "app/src/Composer.tsx", "edited")

    assert _stages(root) == ["frontend"]


def test_an_edited_index_html_needs_the_frontend(tmp_path):
    # The page is an input in its own right: the CSP lives in it, so a change
    # there is a change to the window and not merely to the bundle.
    root = _make_current(tmp_path)
    _write(root / "app/index.html", "edited")

    assert _stages(root) == ["frontend"]


def test_a_missing_bundle_needs_the_frontend(tmp_path):
    root = _make_current(tmp_path)
    (root / OUTPUT).unlink()

    assert _stages(root) == ["frontend"]


def test_the_python_core_is_not_an_input_any_more(tmp_path):
    """The one-stage change, stated as a test.

    The core was stage 2's input and the shell embedded its output, so editing a
    Python file used to cost a PyInstaller freeze and a Rust relink. The window
    runs the core from source as a child process and reads the bundle off disk,
    so neither depends on the other, and a Python edit must build nothing.
    """
    root = _make_current(tmp_path)
    for relative in NOT_SOURCES:
        _write(root / relative, "edited")

    assert _stages(root) == []


def test_bytecode_and_caches_are_not_sources(tmp_path):
    """The .pyc regression, kept because the trap moved rather than closed.

    Running the test suite rewrites ``__pycache__`` under ``src/``, which made a
    stage look stale after every pytest run. ``src/`` is not an input any more,
    but the same trap is one directory away: ``node_modules`` is rewritten by any
    install and ``app/.tmp`` by the test suite itself, and both sit under paths
    this script does read.
    """
    root = _make_current(tmp_path)
    _write(root / "src/tonyagent/core/__pycache__/conversations.cpython-313.pyc")
    _write(root / ".pytest_cache/CACHEDIR.TAG")
    _write(root / "app/src/__pycache__/stray.pyc")

    assert _stages(root) == []


# --------------------------------------------------------------------------
# Build TONYAgent.bat: the dispatch
# --------------------------------------------------------------------------

#: The one command that actually builds anything, replaced by an echo.
_BUILD_COMMANDS = {"call npm run build": "echo STUB-frontend"}


def _stub(text: str, fail_frontend: bool = False) -> str:
    for real, stub in _BUILD_COMMANDS.items():
        assert real in text, f"the build script no longer runs {real!r}"
        text = text.replace(real, "cmd /c exit 3" if fail_frontend else stub)
    return text


def _bat_fixture(root: Path, fail_frontend: bool = False) -> Path:
    """A repository the batch scripts can run in without building anything.

    The real build_state.ps1, so the decision under test is the real one, and a
    stubbed `npm run build`, so the test needs neither Node nor a bundle.
    """
    _make_current(root)

    scripts = root / "scripts"
    scripts.mkdir(exist_ok=True)
    shutil.copy(BUILD_STATE, scripts / "build_state.ps1")

    # Bytes, not text: reading as text would normalise the CRLF endings that cmd
    # needs in order to find a goto label, and the stub would then fail for a
    # reason that has nothing to do with what it is testing.
    stubbed = _stub(BUILD_BATCH.read_bytes().decode("utf-8"), fail_frontend)
    # Two names for one stub: the spaced one is what the launcher calls, which is
    # the whole point of testing it there, and the plain one keeps the quoting
    # out of cmd's way for the direct runs.
    (root / "Build TONYAgent.bat").write_bytes(stubbed.encode("utf-8"))
    (root / "build.bat").write_bytes(stubbed.encode("utf-8"))
    return root


def _launcher_fixture(root: Path, fail_frontend: bool = False) -> Path:
    _bat_fixture(root, fail_frontend)

    launcher = LAUNCHER.read_bytes().decode("utf-8")
    for fragment in (
        'call "%~dp0Build TONYAgent.bat" /q',
        'python -c "import webview" >nul 2>&1',
        'start "" pythonw -m tonyagent.window',
    ):
        assert fragment in launcher, f"the launcher no longer contains {fragment!r}"

    # The pre-flight is stubbed to succeed rather than removed: the branch it
    # guards is real, and one test below exercises it by failing it on purpose.
    launcher = launcher.replace('python -c "import webview" >nul 2>&1', "cmd /c exit 0")
    # Starting the real application is not this test's business; everything up to
    # that point is. `pythonw` and not `python`, because the launcher starts the
    # app without a console now -- a `python` here would be a stub that matched a
    # line the launcher does not have, which is what this fixture's own assertion
    # above exists to catch.
    launcher = launcher.replace('start "" pythonw -m tonyagent.window', "echo STUB-start")
    path = root / "launcher.bat"
    path.write_bytes(launcher.encode("utf-8"))
    return path


def _run(batch: Path, *args: str) -> subprocess.CompletedProcess[str]:
    # ".\name" rather than "name": cmd only searches the current directory when
    # the path says so, and answers "is not recognized" otherwise.
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


def test_the_batch_builds_the_frontend_when_it_is_stale(tmp_path):
    root = _bat_fixture(tmp_path)
    _write(root / "app/src/Composer.tsx", "edited")

    done = _run(root / "build.bat")

    assert done.returncode == 0, done.stdout + done.stderr
    assert "STUB-frontend" in done.stdout


def test_the_batch_does_not_rebuild_the_frontend_for_a_python_edit(tmp_path):
    """The other half of the one-stage change, seen from the batch file.

    The old script had a stage whose input was ``src/``, and this is the case
    that would quietly reintroduce it: a stale report that sends a Python-only
    edit through vite.
    """
    root = _bat_fixture(tmp_path)
    _write(root / "src/tonyagent/window/host.py", "edited")

    done = _run(root / "build.bat")

    assert done.returncode == 0, done.stdout + done.stderr
    assert "Everything is up to date" in done.stdout
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


def test_a_failed_stage_keeps_the_previous_bundle(tmp_path):
    """If the build breaks there is still a build to run."""
    root = _bat_fixture(tmp_path, fail_frontend=True)
    bundle = root / OUTPUT
    before = bundle.stat().st_mtime_ns
    _write(root / "app/src/Composer.tsx", "edited")

    done = _run(root / "build.bat", "/q")

    assert done.returncode == 1
    assert "The build failed" in done.stdout
    assert "The previous bundle is still in place" in done.stdout
    assert bundle.exists()
    assert bundle.stat().st_mtime_ns == before


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
    # `window` explicitly, because every test in this section asserts the window
    # path: the pywebview pre-flight, `Started.`, and a stubbed `pythonw`. The
    # launcher's no-argument default is the terminal interface, which the fixture
    # does not stub -- it runs the real `python -m tonyagent.cli --tui`, and a
    # forced full-screen interface on a captured stdout never returns.
    done = _run(_launcher_fixture(tmp_path), "window")

    assert done.returncode == 0, done.stdout + done.stderr
    assert "STUB-start" in done.stdout
    assert "STUB-" not in done.stdout.replace("STUB-start", "")
    assert "Started." in done.stdout


def test_the_launcher_rebuilds_what_is_stale_before_starting(tmp_path):
    """The regression: `call "Build TONYAgent.bat"` did not resolve, so the
    launcher printed nothing about a rebuild, started the old build, and the
    user was none the wiser."""
    root = _launcher_fixture(tmp_path).parent
    _write(root / "app/src/Composer.tsx", "edited")

    done = _run(root / "launcher.bat", "window")

    assert done.returncode == 0, done.stdout + done.stderr
    assert "The frontend is behind the source" in done.stdout
    assert "STUB-frontend" in done.stdout
    assert "STUB-start" in done.stdout
    assert "Started." in done.stdout


def test_the_launcher_still_starts_the_previous_build_when_the_rebuild_fails(tmp_path):
    """Losing the ability to run the app at all is the worse outcome."""
    root = _launcher_fixture(tmp_path, fail_frontend=True).parent
    _write(root / "app/src/Composer.tsx", "edited")

    done = _run(root / "launcher.bat", "window")

    assert done.returncode == 0, done.stdout + done.stderr
    assert "The rebuild failed" in done.stdout
    assert "STUB-start" in done.stdout
    assert "This is the previous build" in done.stdout


def test_the_launcher_says_so_when_there_is_no_frontend(tmp_path):
    root = _launcher_fixture(tmp_path).parent
    (root / OUTPUT).unlink()

    done = _run(root / "launcher.bat", "window")

    # The stub "rebuilds" and still produces nothing, because the bundle it would
    # have produced is not this test's business. The launcher has to notice that
    # rather than start nothing and report success.
    assert "STUB-frontend" in done.stdout
    assert "STUB-start" not in done.stdout
    assert "There is no built frontend" in done.stdout
    assert done.returncode == 1


def test_the_launcher_says_so_when_the_window_library_is_missing(tmp_path):
    """The other pre-flight, which is the failure a fresh clone actually hits."""
    root = _launcher_fixture(tmp_path).parent
    launcher = (root / "launcher.bat").read_bytes().decode("utf-8")
    launcher = launcher.replace("cmd /c exit 0", "cmd /c exit 1")
    (root / "launcher.bat").write_bytes(launcher.encode("utf-8"))

    done = _run(root / "launcher.bat", "window")

    assert "STUB-start" not in done.stdout
    assert "pip install pywebview" in done.stdout
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
    # Split by line, not by whitespace: one of these names contains a space.
    #
    # `ls-files` reads the index, which still lists a file that has been deleted
    # from the tree but not staged -- "Start TONYAgent (Tauri).bat" is exactly
    # that, so a missing path is skipped rather than opened. Asserting on a file
    # that is on its way out would be a test that fails for the one reason that
    # is not a defect.
    return [
        REPO / line
        for line in done.stdout.splitlines()
        if line.strip() and (REPO / line).exists()
    ]


def test_every_batch_file_has_crlf_endings():
    """Not a style preference. See .gitattributes for the measurement.

    With LF endings cmd's label search fails in narrow windows positioned by byte
    offsets, so a ``goto`` that has resolved all day stops resolving after an
    edit anywhere above it. Five of six paths through the same file behave
    identically either way, which is what makes this worth a test rather than a
    note: the file looks fine right up until one label stops resolving.
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
