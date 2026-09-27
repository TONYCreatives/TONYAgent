#!/usr/bin/env python
"""Build the core sidecar and install it where Tauri expects to find it.

PyInstaller alone drops the exe in ``dist/``, but Tauri resolves
``externalBin`` entries from ``app/src-tauri/binaries/`` with a
``-<target-triple>`` suffix. Getting that name wrong produces a build that
succeeds and an app that cannot spawn its backend, so the rename is done here
rather than left to whoever runs it by hand.

``tauri.conf.json`` is updated to match. Tauri matches the ``externalBin`` entry
against the filename in ``binaries/`` literally, so the entry must carry the
same ``-<target-triple>`` suffix as the file. Hardcoding one triple in the
committed config would work on the machine that wrote it and fail everywhere
else, so the entry is derived from the host at build time instead.

Usage::

    python scripts/build_sidecar.py          # build and install
    python scripts/build_sidecar.py --clean  # discard build dirs first

The output is gitignored; it is a reproducible build product, not source.
"""

from __future__ import annotations

import argparse
import json
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPEC = ROOT / "scripts" / "sidecar.spec"
BINARIES = ROOT / "app" / "src-tauri" / "binaries"
TAURI_CONF = ROOT / "app" / "src-tauri" / "tauri.conf.json"
EXE_NAME = "tonyagent-core.exe" if platform.system() == "Windows" else "tonyagent-core"


def target_triple() -> str:
    """The Rust target triple this host builds for.

    Tauri names sidecars ``<name>-<triple>``. Rather than hand-maintaining a
    table, reuse cargo's own answer so the two can never drift.
    """
    result = subprocess.run(
        ["rustc", "-vV"],
        capture_output=True,
        text=True,
        check=True,
    )
    for line in result.stdout.splitlines():
        if line.startswith("host:"):
            return line.split(":", 1)[1].strip()
    raise RuntimeError("could not determine the host target triple from rustc -vV")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--clean",
        action="store_true",
        help="remove build/ and dist/ before building",
    )
    args = parser.parse_args()

    if args.clean:
        for name in ("build", "dist"):
            shutil.rmtree(ROOT / name, ignore_errors=True)
        # The spec lives in scripts/, so PyInstaller puts its scratch dirs
        # beside it rather than at the repo root.
        shutil.rmtree(ROOT / "scripts" / "build", ignore_errors=True)

    # Fixed working directory: the spec reads src/ relative to itself, and a
    # stable cwd keeps the PyInstaller cache in one place across runs.
    print(f"building sidecar from {SPEC}")
    result = subprocess.run(
        [sys.executable, "-m", "PyInstaller", "--noconfirm", str(SPEC)],
        cwd=str(ROOT),
    )
    if result.returncode != 0:
        print("PyInstaller failed", file=sys.stderr)
        return result.returncode

    built = ROOT / "dist" / EXE_NAME
    if not built.exists():
        print(f"expected {built} to exist, but it does not", file=sys.stderr)
        return 1

    triple = target_triple()
    BINARIES.mkdir(parents=True, exist_ok=True)
    destination = BINARIES / f"tonyagent-core-{triple}.exe"
    shutil.copy2(built, destination)

    # `externalBin` takes the BARE sidecar name -- Tauri appends
    # `-<target-triple>.exe` itself when resolving the file. Writing the triple
    # into the config instead produces
    #   resource path `binaries	onyagent-core-<triple>-<triple>.exe` doesn't exist
    # at build time. Verified against tauri 2.12.
    ensure_external_bin()

    size_mb = destination.stat().st_size / (1024 * 1024)
    print(f"installed {destination.relative_to(ROOT)} ({size_mb:.1f} MB)")
    return 0


def update_external_bin(triple: str) -> None:
    """Rewrite bundle.externalBin to name this host's sidecar."""
    config = json.loads(TAURI_CONF.read_text(encoding="utf-8"))
    config.setdefault("bundle", {})["externalBin"] = [f"binaries/tonyagent-core-{triple}"]
    TAURI_CONF.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    print(f"externalBin -> binaries/tonyagent-core-{triple}")


if __name__ == "__main__":
    raise SystemExit(main())
