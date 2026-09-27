# PyInstaller spec for the TONYAgent core sidecar.
#
# Produces a single console-less executable that speaks the JSONL stdio
# protocol from `tonyagent.headless.server`. Tauri launches it as a sidecar and
# talks to it over stdin/stdout; stderr is free for logs.
#
# Build with:  python scripts/build_sidecar.py
# (which invokes this spec and copies the result to app/src-tauri/binaries/)
#
# The output is gitignored. A ~20 MB binary does not belong in history, and it
# is fully reproducible from this spec.

import glob
import os
import site
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

# PyInstaller injects SPECPATH as the absolute path of this spec's directory
# (i.e. <repo>/scripts), so the repo root is one level up from it.
ROOT = Path(SPECPATH).resolve().parent  # noqa: F821 - injected by PyInstaller
SRC = ROOT / "src"

block_cipher = None  # noqa: F841 - required by the Analysis signature

# `tomli` ships as mypyc-compiled extension modules. Each mypyc package carries
# its own hash-prefixed runtime (`<hash>__mypyc`), and that hash changes with
# every release, so naming the runtime in hiddenimports would break on the next
# upgrade. collect_all() picks up the current one automatically.
#
# Without this the sidecar dies at startup with:
#   ModuleNotFoundError: No module named '3c22db458360489351e4__mypyc'
# raised from tonyagent/config/migration.py, before a single request is served.
_tomli_datas, _tomli_binaries, _tomli_hidden = collect_all("tomli")


def _mypyc_runtimes() -> list:
    """Locate the hash-prefixed `<hash>__mypyc` shared objects mypyc emits.

    collect_all() only walks *inside* a package directory, but a mypyc runtime
    is installed as a top-level module next to it, so collect_all() cannot see
    it. The hash is regenerated per release, so it has to be discovered by
    pattern rather than named.

    Bundled whole rather than filtered to the one `tomli` needs: there are only
    a couple, they are small, and which package needs which hash is an internal
    detail that can change on upgrade.
    """
    found = []
    for base in site.getsitepackages() + [site.getusersitepackages()]:
        for path in glob.glob(os.path.join(base, "*__mypyc*.pyd")) + glob.glob(
            os.path.join(base, "*__mypyc*.so")
        ):
            name = os.path.basename(path).split(".")[0]
            found.append((path, name))
    return found


_mypyc = _mypyc_runtimes()
if not _mypyc:
    raise SystemExit(
        "no mypyc runtime found; `tomli` is mypyc-compiled and the sidecar "
        "cannot start without it"
    )

# `console=False` hides the console window. The protocol needs real stdio
# handles, which a windows-subsystem binary does not get -- a GUI subsystem app
# has no usable stdout, and the frontend would see an empty pipe. So this MUST
# stay a console binary; main() sets windows_subsystem only for the Tkinter GUI,
# never for the sidecar.

a = Analysis(
    [str(SRC / "tonyagent" / "headless" / "server.py")],
    pathex=[str(SRC)],
    binaries=_tomli_binaries + _mypyc,
    datas=_tomli_datas,
    # Every provider is OpenAI-compatible and goes through tonyagent.api.LLMClient
    # (httpx), so there are no vendor SDKs to bundle. These are the only
    # imports PyInstaller's static analysis cannot see:
    #   keyring    - resolves its platform backend at runtime via entry points
    #   tomli_w    - written to, not read from; the read path is `tomli`
    #   pydantic   - resolved through pydantic's plugin machinery at runtime
    hiddenimports=_tomli_hidden + [name for _, name in _mypyc] + [
        "keyring",
        "keyring.backends",
        "keyring.backends.Windows",
        "tomli_w",
        "loguru",
        "pydantic",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # tkinter and customtkinter are excluded on purpose. The headless core must
    # not pull in a GUI toolkit; tests/unit/test_headless_core.py enforces that
    # at runtime. If PyInstaller ever bundles them, that test's intent has been
    # violated and the sidecar has grown a GUI dependency it should not have.
    excludes=[
        "tkinter",
        "customtkinter",
        # Browser automation runs inside the Docker sandbox
        # (docker/sandbox/rpc_server.py), never on the host. Bundling the
        # Playwright driver here would add tens of MB and a Chromium download
        # path that the sidecar never takes.
        "playwright",
        "pytest",
        "mypy",
        "ruff",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)  # noqa: F821

exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="tonyagent-core",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    # Not a GUI app: it must keep a real stdout for the protocol.
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
