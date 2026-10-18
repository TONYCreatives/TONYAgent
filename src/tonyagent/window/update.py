"""Run the installer the core downloaded, and get out of its way.

**This is the only place in the app that starts a program it did not write.**
Everything about it is therefore narrow on purpose:

* It runs an MSI from exactly one directory -- `core.update.download_dir()`,
  beside `config.toml` -- and refuses a path from anywhere else. The page cannot
  name a file for it to run, for the same reason `account.VIEWS` is a closed set
  rather than a URL the page hands over.
* It only ever runs the *newest* MSI in that directory, and only one whose name
  matches the pattern the downloader writes. A directory with two installers in
  it is not a reason to pick either.
* The file was already verified against the digest GitHub published for the
  release, in the core, before it landed there. This module does not re-verify,
  and it does not need to: it will not run anything the core did not put there.

**The wait is the interesting part.** Windows Installer cannot replace a running
executable, and this *is* that executable -- the host and the core are one file.
So the installer is started by a detached helper that first waits for this
process to exit, and the window then closes itself. Launching `msiexec` directly
and hoping the user spends long enough on the UAC prompt would work on most
machines and fail on the ones where it matters.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

from loguru import logger

#: The name the downloader writes. Anchored, so `../evil.msi` and `notes.msi.txt`
#: both fail -- this is a pattern the file must match, not a hint.
_NAME = "TONYAgent-"

#: Suppress the console window the helper would otherwise flash.
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def newest_installer(directory: Path) -> Path | None:
    """The most recently written installer in `directory`, or None.

    Sorted by modification time rather than by name: two installers in the
    directory means the version strings disagree with the filesystem, and the
    one that was downloaded last is the one the user asked for.
    """
    try:
        candidates = [
            path
            for path in directory.glob("*.msi")
            if path.is_file() and path.name.startswith(_NAME) and path.suffix == ".msi"
        ]
    except Exception as exc:  # noqa: BLE001 - an unreadable directory is not fatal
        logger.debug(f"Could not look for an installer: {exc}")
        return None
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime)


def install(directory: Path, pid: int) -> dict[str, Any]:
    """Start the installer once this process is gone. Returns whether it began.

    The helper is PowerShell rather than a bare `msiexec` call because of the
    ordering: `Wait-Process` on our own pid, then the installer. `-Verb RunAs`
    is deliberately absent -- a per-machine MSI raises its own UAC prompt, and
    asking twice is a worse experience than asking once at the right moment.
    """
    installer = newest_installer(directory)
    if installer is None:
        return {"started": False, "reason": "no_installer", "path": ""}

    # Quoted for the PowerShell string and again for msiexec, because the path
    # contains spaces (`C:\Users\...\AppData\Roaming\TONYAgent\update\...`) and
    # a bare path would be read as several arguments.
    script = (
        f"Wait-Process -Id {int(pid)} -ErrorAction SilentlyContinue; "
        f"Start-Process msiexec -ArgumentList '/i', '\"{installer}\"', '/passive', "
        f"'/norestart'"
    )
    try:
        subprocess.Popen(  # noqa: S603 - the argv is built here, not by a user
            [
                "powershell",
                "-NoProfile",
                "-WindowStyle",
                "Hidden",
                "-Command",
                script,
            ],
            creationflags=_NO_WINDOW,
            close_fds=True,
        )
    except Exception as exc:  # noqa: BLE001 - reported, not raised
        logger.warning(f"Could not start the installer: {exc}")
        return {"started": False, "reason": "launch_failed", "path": str(installer)}

    logger.info(f"The installer will run once this process exits: {installer}")
    return {"started": True, "reason": "", "path": str(installer)}


def supported() -> bool:
    """Whether this platform can apply an update in place.

    Windows only, and honestly so: the installer is an MSI, and a source
    checkout updates with `git pull`. Everywhere else the answer is a link to
    the release page rather than a download nobody can run.
    """
    return sys.platform == "win32"
