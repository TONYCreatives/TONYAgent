"""Live smoke test: run every registered tool for real.

Usage:
    python scripts/e2e_all_tools.py            # full run, needs Docker Desktop
    python scripts/e2e_all_tools.py --fast     # skip tools that need the sandbox

Starts the sandbox through the SHARED manager (same object the tools use) so
the sandbox_required tools run exactly as they would in the app. Destructive
tools are called via their execute() directly (this script IS the user); the
orchestrator's confirmation bridge is deliberately not in the loop here.
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from tonyagent.folder.manager import folder_manager
from tonyagent.sandbox import get_shared_sandbox_manager
from tonyagent.sandbox.base import SandboxConfig
from tonyagent.tools.base import ToolResultStatus

FAST = "--fast" in sys.argv

RESULTS: list[tuple[str, str, str]] = []  # (name, verdict, detail)


def record(name: str, result) -> None:
    status = result.status.value
    if result.status is ToolResultStatus.SUCCESS:
        verdict = "PASS"
    elif FAST and "sandbox" in str(result.error or "").lower():
        # In --fast mode a sandbox-refusal is the expected outcome, not a failure.
        verdict = "SKIP"
    else:
        verdict = "FAIL"
    detail = (result.error or str(result.output or "")).replace("\n", " ")[:110]
    RESULTS.append((name, verdict if verdict != "SKIP" else "PASS(refusal)", detail))
    print(f"  {verdict:14} {name:22} [{status:9}] {detail}")


async def expect_error(name: str, coro, needle: str) -> None:
    """A tool call that MUST fail, failing for the right reason."""
    result = await coro
    ok = result.status is ToolResultStatus.ERROR and needle.lower() in str(result.error or "").lower()
    RESULTS.append((name, "PASS" if ok else "FAIL", str(result.error or "")[:110]))
    print(f"  {'PASS' if ok else 'FAIL':14} {name:22} [error    ] {str(result.error or '')[:110]}")


async def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="tonyagent-all-tools-"))
    (tmp / "hello.txt").write_text("hello world\nsecond line\n", encoding="utf-8")
    (tmp / "app.py").write_text("print('hi')\n# TODO find me\n", encoding="utf-8")
    (tmp / "sub").mkdir()
    (tmp / "sub" / "deep.txt").write_text("deep file\n", encoding="utf-8")
    folder_manager._current_folder = tmp

    # -- 1. tools that need no sandbox --------------------------------------
    from tonyagent.tools.file_tools import (
        DeleteFileTool, EditFileTool, ListDirTool, ReadFileTool, WriteFileTool,
    )
    from tonyagent.tools.search_tools import GlobTool, GrepTool
    from tonyagent.tools.network_tools import HttpRequestTool

    print(f"[all-tools] project: {tmp}")

    r = await ReadFileTool().execute("hello.txt")
    record("read_file", r)
    assert r.status is ToolResultStatus.SUCCESS and "hello world" in r.output

    r = await WriteFileTool().execute("notes/new.txt", "brand new")
    record("write_file", r)
    assert r.status is ToolResultStatus.SUCCESS and (tmp / "notes" / "new.txt").exists()
    assert r.artifacts and r.artifacts[0]["data"]["added"] == 1

    r = await EditFileTool().execute("hello.txt", "second line", "SECOND LINE")
    record("edit_file", r)
    assert r.status is ToolResultStatus.SUCCESS and "SECOND LINE" in (tmp / "hello.txt").read_text()

    r = await ListDirTool().execute(".", recursive=True, max_depth=2)
    record("list_dir", r)
    assert r.status is ToolResultStatus.SUCCESS and "deep.txt" in r.output

    r = await GrepTool().execute("TODO", include="*.py")
    record("grep", r)
    assert r.status is ToolResultStatus.SUCCESS and "app.py" in r.output

    r = await GlobTool().execute("**/*.txt")
    record("glob", r)
    assert r.status is ToolResultStatus.SUCCESS and "hello.txt" in r.output

    await expect_error("read_file(escape)", ReadFileTool().execute("../outside.txt"), "escape")

    r = await DeleteFileTool().execute("notes/new.txt")
    record("delete_file", r)
    assert r.status is ToolResultStatus.SUCCESS and not (tmp / "notes" / "new.txt").exists()

    r = await HttpRequestTool().execute("https://example.com", method="GET", timeout=15)
    record("http_request", r)
    assert r.status is ToolResultStatus.SUCCESS and r.output["status_code"] == 200

    await expect_error(
        "http_request(ssrf)", HttpRequestTool().execute("http://127.0.0.1:9/x"), "blocked"
    )

    # -- 2. sandbox_required tools -------------------------------------------
    from tonyagent.tools.shell_tools import ExecuteCommandTool
    from tonyagent.tools.sandbox_file_tools import SandboxListFilesTool, SandboxReadFileTool
    from tonyagent.tools.browser_tools import (
        BrowserClickTool, BrowserEvalTool, BrowserGetTextTool, BrowserNavigateTool,
        BrowserScrollTool, BrowserScreenshotTool, BrowserSnapshotTool, BrowserTypeTool,
        BrowserWaitForTool, ExecuteJsTool, SetViewportSizeTool,
    )

    if FAST:
        # Fail-closed check: every sandbox tool must refuse with a clear message.
        print("[all-tools] --fast: asserting sandbox refusals only")
        for tool, kwargs in (
            (ExecuteCommandTool, {"command": "python --version"}),
            (SandboxReadFileTool, {"path": "hello.txt"}),
            (SandboxListFilesTool, {}),
            (BrowserNavigateTool, {"url": "https://example.com"}),
            (BrowserClickTool, {"selector": "a"}),
            (BrowserTypeTool, {"selector": "input", "text": "x"}),
            (BrowserEvalTool, {"script": "1+1"}),
            (BrowserSnapshotTool, {}),
            (SetViewportSizeTool, {"width": 100, "height": 100}),
            (BrowserGetTextTool, {}),
            (BrowserWaitForTool, {"state": "load"}),
            (BrowserScrollTool, {}),
            (BrowserScreenshotTool, {}),
            (ExecuteJsTool, {"script": "console.log(1)"}),
        ):
            await expect_error(f"{tool.name}(stopped)", tool().execute(**kwargs), "sandbox")
        return _summary()

    manager = get_shared_sandbox_manager()
    # Network ON: browser_navigate legitimately needs egress (same as e2e_tools.py).
    ok = await manager.start(
        SandboxConfig(type="docker", project_path=str(tmp), cpu_limit="1.0", enable_network=True)
    )
    print(f"[all-tools] sandbox start -> {ok}")
    if not ok:
        return _summary("sandbox failed to start; sandbox_required tools untested")

    try:
        r = await ExecuteCommandTool().execute("python -c \"print(open('hello.txt').read())\"", timeout=20)
        record("execute_command", r)
        assert r.status is ToolResultStatus.SUCCESS and "hello world" in r.output["stdout"]

        await expect_error(
            "execute_command(deny)",
            ExecuteCommandTool().execute("shutdown /s"),
            "not allowed",
        )

        r = await SandboxReadFileTool().execute("hello.txt")
        record("sandbox_read_file", r)
        assert r.status is ToolResultStatus.SUCCESS and "hello world" in r.output

        r = await SandboxListFilesTool().execute(".")
        record("sandbox_list_files", r)
        assert r.status is ToolResultStatus.SUCCESS and "hello.txt" in r.output

        r = await BrowserNavigateTool().execute("https://example.com")
        record("browser_navigate", r)
        assert r.status is ToolResultStatus.SUCCESS, r.error

        r = await BrowserSnapshotTool().execute()
        record("browser_snapshot", r)
        assert r.status is ToolResultStatus.SUCCESS and "example" in r.output.lower()

        r = await BrowserGetTextTool().execute()  # whole page; no assumption about tags
        record("browser_get_text", r)
        assert r.status is ToolResultStatus.SUCCESS and "example" in r.output.lower()

        r = await BrowserEvalTool().execute("document.title")
        record("browser_eval", r)
        assert r.status is ToolResultStatus.SUCCESS and "example" in str(r.output).lower()

        r = await BrowserClickTool().execute("a")  # example.com's "More information..." link
        record("browser_click", r)
        assert r.status is ToolResultStatus.SUCCESS, r.error

        r = await BrowserWaitForTool().execute(state="load", timeout=10000)
        record("browser_wait_for", r)
        assert r.status is ToolResultStatus.SUCCESS, r.error

        r = await BrowserScrollTool().execute("down", amount=400)
        record("browser_scroll", r)
        assert r.status is ToolResultStatus.SUCCESS, r.error

        r = await SetViewportSizeTool().execute(390, 844)
        record("set_viewport_size", r)
        assert r.status is ToolResultStatus.SUCCESS and "390x844" in r.output

        r = await SetViewportSizeTool().execute(0, 0, reset=True)
        record("set_viewport_size(reset)", r)
        assert r.status is ToolResultStatus.SUCCESS

        # A deterministic form to type into: example.com has no input element,
        # and "expected element missing" is Playwright's 30s timeout, not a
        # quick check. A data: URL gives the browser a page we fully control.
        r = await BrowserNavigateTool().execute(
            'data:text/html,<input id="q"><button id="go">Go</button>'
        )
        record("browser_navigate(form)", r)
        assert r.status is ToolResultStatus.SUCCESS, r.error

        r = await BrowserTypeTool().execute("#q", "tonyagent")
        record("browser_type", r)
        assert r.status is ToolResultStatus.SUCCESS, r.error

        r = await BrowserEvalTool().execute("document.getElementById('q').value")
        record("browser_type(verify)", r)
        assert r.status is ToolResultStatus.SUCCESS and "tonyagent" in str(r.output)

        r = await BrowserScreenshotTool().execute("shot.png")
        record("browser_screenshot", r)
        assert r.status is ToolResultStatus.SUCCESS, r.error

        r = await ExecuteJsTool().execute("console.log(40+2)", timeout=10)
        record("execute_js", r)
        assert r.status is ToolResultStatus.SUCCESS and "42" in str(r.output)
    finally:
        if manager.get_backend() is not None:
            await manager.stop()
    return _summary()


def _summary(note: str = "") -> int:
    print()
    passed = sum(1 for _, v, _ in RESULTS if v.startswith("PASS"))
    failed = sum(1 for _, v, _ in RESULTS if v == "FAIL")
    print(f"[all-tools] {passed} passed, {failed} failed  (of {len(RESULTS)} checks)")
    if note:
        print(f"[all-tools] NOTE: {note}")
    for name, verdict, detail in RESULTS:
        if verdict == "FAIL":
            print(f"[all-tools]   FAIL {name}: {detail}")
    return 1 if failed else 0


if __name__ == "__main__":
    t0 = time.time()
    code = asyncio.run(main())
    print(f"[all-tools] total {time.time() - t0:.1f}s")
    raise SystemExit(code)
