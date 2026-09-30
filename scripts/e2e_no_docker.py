"""Live check: the agent with no Docker daemon anywhere.

Docker is the thing this project used to require, so the claim worth testing is
the boring one -- an agent that reads, writes, searches, fetches and drives a
browser on a machine with no daemon, while the two tools that execute code stay
shut.

Run with Docker genuinely stopped, or this passes for the wrong reason::

    python scripts/e2e_no_docker.py
"""

from __future__ import annotations

import asyncio
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from tonyagent.folder import folder_manager  # noqa: E402
from tonyagent.sandbox import get_shared_sandbox_manager  # noqa: E402
from tonyagent.sandbox.base import SandboxConfig  # noqa: E402
from tonyagent.tools.browser_tools import (  # noqa: E402
    BrowserGetTextTool,
    BrowserNavigateTool,
    BrowserSnapshotTool,
    ExecuteJsTool,
)
from tonyagent.tools.file_tools import (  # noqa: E402
    ListDirTool,
    ReadFileTool,
    WriteFileTool,
)
from tonyagent.tools.network_tools import HttpRequestTool  # noqa: E402
from tonyagent.tools.sandbox_file_tools import (  # noqa: E402
    SandboxListFilesTool,
    SandboxReadFileTool,
)
from tonyagent.tools.search_tools import GrepTool  # noqa: E402
from tonyagent.tools.shell_tools import ExecuteCommandTool  # noqa: E402

passed = 0
failed = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global passed, failed
    # The Windows console here is cp949 and page text is not always encodable
    # in it; a detail string must never be what fails a run.
    safe = detail.encode("ascii", "replace").decode()
    if ok:
        passed += 1
        print(f"  PASS           {label:<34} {safe}")
    else:
        failed += 1
        print(f"  FAIL           {label:<34} {safe}")


def docker_is_up() -> bool:
    try:
        import docker

        docker.from_env().ping()
        return True
    except Exception:
        return False


async def main() -> int:
    project = Path(tempfile.mkdtemp(prefix="tonyagent-nodocker-"))
    print(f"[no-docker] project: {project}")

    if docker_is_up():
        print(
            "[no-docker] WARNING: a Docker daemon is reachable, so a pass here "
            "would not prove anything. Stop Docker and re-run.",
        )
    else:
        print("[no-docker] confirmed: no Docker daemon reachable")

    folder_manager.set_folder(project)
    manager = get_shared_sandbox_manager()

    # --- the runtime comes up with no daemon ------------------------------
    started = await manager.ensure_local(SandboxConfig(project_path=str(project)))
    check("local runtime starts", started)
    check("reports running", manager.is_running() is True)
    check("reports NOT isolated", manager.is_isolated() is False)
    check("isolating accessor is empty", manager.get_backend() is None)

    # --- the 8 tools that never needed Docker -----------------------------
    write = await WriteFileTool().execute(path="notes/plan.md", content="# local\n\n- a\n- b\n")
    check("write_file", write.status.value == "success", str(write.error or write.output or "")[:40])

    read = await ReadFileTool().execute(path="notes/plan.md")
    check("read_file", read.status.value == "success" and "# local" in str(read.output))

    listing = await ListDirTool().execute(path="notes")
    check("list_dir", listing.status.value == "success" and "plan.md" in str(listing.output))

    grep = await GrepTool().execute(pattern="local", path="notes")
    check("grep", grep.status.value == "success", str(grep.error or "")[:40])

    sandboxed = await SandboxReadFileTool().execute(path="notes/plan.md")
    check(
        "sandbox_read_file (local runtime)",
        sandboxed.status.value == "success" and "# local" in str(sandboxed.output or ""),
        str(sandboxed.error or "")[:40],
    )

    files = await SandboxListFilesTool().execute(path=".")
    check(
        "sandbox_list_files (local runtime)",
        files.status.value == "success" and "notes" in str(files.output or ""),
        str(files.error or "")[:40],
    )

    http = await HttpRequestTool().execute(url="https://example.com", method="GET")
    check("http_request", http.status.value == "success", str(http.error or "")[:40])

    # --- browser tools, against a real page --------------------------------
    nav = await BrowserNavigateTool().execute(url="https://example.com")
    check("browser_navigate", nav.status.value == "success", str(nav.error or "")[:60])

    if nav.status.value == "success":
        text = await BrowserGetTextTool().execute()
        # Asserted on substance, not on English: example.com serves whatever
        # locale the network hands back (Arabic on this machine), and a
        # string match would fail for a reason that has nothing to do with the
        # tool.
        body = str(text.output or "")
        check(
            "browser_get_text",
            text.status.value == "success" and len(body) > 200,
            f"{len(body)} chars extracted",
        )
        snap = await BrowserSnapshotTool().execute()
        check("browser_snapshot", snap.status.value == "success", str(snap.error or "")[:40])

    # --- the two that must stay shut ---------------------------------------
    shell = await ExecuteCommandTool().execute("python --version")
    check(
        "execute_command refused",
        shell.status.value == "error" and "isolated sandbox" in (shell.error or "").lower(),
        (shell.error or "")[:50],
    )
    js = await ExecuteJsTool().execute("1+1")
    check(
        "execute_js refused",
        js.status.value == "error" and "isolated" in (js.error or "").lower(),
        (js.error or "")[:50],
    )

    await manager.stop()
    check("stopped cleanly", manager.get_runtime_backend() is None)

    shutil.rmtree(project, ignore_errors=True)
    print(f"\n[no-docker] {passed} passed, {failed} failed  (of {passed + failed} checks)")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
