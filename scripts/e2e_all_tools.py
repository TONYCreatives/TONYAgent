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
        DeleteFileTool, EditTool, ListDirTool, ReadImageTool, ReadTool, WriteTool,
    )
    from tonyagent.tools.search_tools import GlobTool, GrepTool
    from tonyagent.tools.network_tools import HttpRequestTool

    print(f"[all-tools] project: {tmp}")

    r = await ReadTool().execute("hello.txt")
    record("read", r)
    assert r.status is ToolResultStatus.SUCCESS and "hello world" in r.output
    assert "1\thello world" in r.output, "read must number its lines"

    # The line window, which is the reason `read` took `offset`/`limit`.
    r = await ReadTool().execute("hello.txt", offset=2, limit=1)
    record("read(window)", r)
    assert r.status is ToolResultStatus.SUCCESS and "2\tsecond line" in r.output

    r = await WriteTool().execute("notes/new.txt", "brand new")
    record("write", r)
    assert r.status is ToolResultStatus.SUCCESS and (tmp / "notes" / "new.txt").exists()
    assert r.artifacts and r.artifacts[0]["data"]["added"] == 1

    r = await EditTool().execute("hello.txt", "second line", "SECOND LINE")
    record("edit", r)
    assert r.status is ToolResultStatus.SUCCESS and "SECOND LINE" in (tmp / "hello.txt").read_text()

    # The refusal that is the whole point of `edit` over a plain replace: two
    # matches is a guess about which one was meant, so it declines to guess and
    # names both ways out.
    (tmp / "dupes.txt").write_text("same\nx\nsame\n", encoding="utf-8")
    await expect_error(
        "edit(ambiguous)", EditTool().execute("dupes.txt", "same", "changed"), "2 times"
    )
    assert (tmp / "dupes.txt").read_text() == "same\nx\nsame\n", "a refusal edited the file"

    r = await EditTool().execute("dupes.txt", "same", "changed", replace_all=True)
    record("edit(replace_all)", r)
    assert r.status is ToolResultStatus.SUCCESS and (tmp / "dupes.txt").read_text() == "changed\nx\nchanged\n"

    r = await ListDirTool().execute(".", recursive=True, max_depth=2)
    record("list_dir", r)
    assert r.status is ToolResultStatus.SUCCESS and "deep.txt" in r.output

    r = await GrepTool().execute("TODO", include="*.py")
    record("grep", r)
    assert r.status is ToolResultStatus.SUCCESS and "app.py" in r.output

    r = await GlobTool().execute("**/*.txt")
    record("glob", r)
    assert r.status is ToolResultStatus.SUCCESS and "hello.txt" in r.output

    await expect_error("read(escape)", ReadTool().execute("../outside.txt"), "escape")

    r = await DeleteFileTool().execute("notes/new.txt")
    record("delete_file", r)
    assert r.status is ToolResultStatus.SUCCESS and not (tmp / "notes" / "new.txt").exists()

    r = await HttpRequestTool().execute("https://example.com", method="GET", timeout=15)
    record("http_request", r)
    assert r.status is ToolResultStatus.SUCCESS and r.output["status_code"] == 200

    await expect_error(
        "http_request(ssrf)", HttpRequestTool().execute("http://127.0.0.1:9/x"), "blocked"
    )

    # -- 1b. the tools added with the tool-system pass ------------------------
    from tonyagent.tools.job_tools import JobKillTool, JobListTool, JobOutputTool
    from tonyagent.tools.jobs import jobs_registry
    from tonyagent.tools.network_tools import WebFetchTool
    from tonyagent.tools.shell_tools import ExecuteCommandTool, set_host_execution

    from PIL import Image

    Image.new("RGB", (24, 16), (10, 20, 30)).save(tmp / "pic.png")

    r = await ReadImageTool().execute("pic.png")
    record("read_image", r)
    assert r.status is ToolResultStatus.SUCCESS and r.images, r.error
    assert r.images[0]["mime"] == "image/png"
    assert "24x16" in r.output
    # The pixels are deliberately not in the dict written into a conversation.
    assert "images" not in r.to_dict()

    await expect_error(
        "read_image(text)", ReadImageTool().execute("hello.txt"), "not an image"
    )

    r = await WebFetchTool().execute("https://example.com", timeout=15)
    record("web_fetch", r)
    assert r.status is ToolResultStatus.SUCCESS and "example" in r.output.lower()

    await expect_error(
        "web_fetch(ssrf)", WebFetchTool().execute("http://127.0.0.1:9/x"), "blocked"
    )

    # Background jobs live on the host, so they are exercised with host execution
    # on. The sandbox cannot hold one at all, and that refusal is asserted in the
    # sandbox section below rather than here.
    set_host_execution(True)
    try:
        # A quick job first, for the output path.
        r = await ExecuteCommandTool().execute(
            "python -c \"print('from a job')\"", background=True
        )
        record("execute_command(background)", r)
        assert r.status is ToolResultStatus.SUCCESS, r.error
        quick = jobs_registry.all()[0]

        r = await JobOutputTool().execute(quick.id, wait=True, timeout_ms=15000)
        record("job_output", r)
        assert r.status is ToolResultStatus.SUCCESS and "from a job" in r.output

        r = await JobOutputTool().execute(quick.id)
        assert "no new output" in r.output, "job_output returned the same text twice"

        # Then one that is *still running*, so the kill below is a real kill and
        # not a report that there was nothing left to stop.
        r = await ExecuteCommandTool().execute(
            "python -c \"import time; time.sleep(60)\"", background=True
        )
        assert r.status is ToolResultStatus.SUCCESS, r.error
        long_job = jobs_registry.all()[-1]

        r = await JobListTool().execute()
        record("job_list", r)
        assert r.status is ToolResultStatus.SUCCESS and long_job.id in r.output
        assert "running" in r.output

        r = await JobKillTool().execute(long_job.id)
        record("job_kill", r)
        assert "Stopped" in r.output, r.output
        assert not long_job.running, "the job survived job_kill"
    finally:
        set_host_execution(False)
        jobs_registry.shutdown()

    # -- 1c. the planning tools ----------------------------------------------
    from tonyagent.core.task_state import SessionState, set_current_state
    from tonyagent.tools.planning_tools import (
        CreateGoalTool, GetGoalTool, TodoWriteTool, UpdateGoalTool,
    )

    set_current_state(SessionState())

    r = await TodoWriteTool().execute(
        todos=[
            {"text": "read the config"},
            {"text": "change the default", "status": "in_progress"},
        ]
    )
    record("todo_write", r)
    assert r.status is ToolResultStatus.SUCCESS and "1. [ ] read the config" in r.output
    assert "2. [~] change the default" in r.output

    # The list is replaced, not merged -- which is what makes dropping a step
    # possible at all.
    r = await TodoWriteTool().execute(todos=[{"text": "read the config"}])
    assert "change the default" not in r.output, "todo_write merged instead of replacing"

    await expect_error(
        "todo_write(bad item)",
        TodoWriteTool().execute(todos=[{"text": "fine"}, {"status": "pending"}]),
        "no text",
    )

    r = await CreateGoalTool().execute(objective="Ship the retry fix")
    record("create_goal", r)
    assert r.status is ToolResultStatus.SUCCESS and "Ship the retry fix" in r.output

    await expect_error(
        "create_goal(already set)",
        CreateGoalTool().execute(objective="something else"),
        "already an active goal",
    )

    r = await GetGoalTool().execute()
    record("get_goal", r)
    assert r.status is ToolResultStatus.SUCCESS and "Ship the retry fix" in r.output

    await expect_error(
        "update_goal(blocked, no note)",
        UpdateGoalTool().execute(status="blocked"),
        "blocked on",
    )

    r = await UpdateGoalTool().execute(status="blocked", note="waiting on review")
    record("update_goal", r)
    assert r.status is ToolResultStatus.SUCCESS and "blocked" in r.output

    set_current_state(SessionState())

    # -- 1b. the tools that reach the user ------------------------------------
    # Neither needs the sandbox, and one of them is the only tool whose happy
    # path *requires* something a script cannot supply: a person. So the script
    # stands in for one -- which is the same standing-in the window does, one
    # `user.respond` away -- and then checks the two failure paths that a real
    # run hits with nobody there.
    from tonyagent.core import user_io
    from tonyagent.tools.user_tools import AskUserQuestionTool, PresentTool

    async def _answered(coro):
        """Run a tool that stops for the user, with a user who answers.

        The answer has to come from inside the loop: `await`ing the tool
        directly would suspend the very task that has to answer it.
        """
        asked: list = []
        user_io.set_callbacks(asked.append, lambda *_: None)
        task = asyncio.create_task(coro)
        try:
            for _ in range(200):
                if asked:
                    break
                await asyncio.sleep(0)
            assert asked, "the tool never asked"
            user_io.respond(asked[-1].id, "Postgres")
            return await task
        finally:
            user_io.reset()

    r = await _answered(
        AskUserQuestionTool().execute(
            question="Postgres or SQLite?", options=["Postgres", "SQLite"]
        )
    )
    record("ask_user_question", r)
    assert r.status is ToolResultStatus.SUCCESS
    assert 'The user answered: "Postgres"' in r.output

    # Nobody listening is the state a scripted or headless run is in, and the
    # tool must say so rather than wait out its timeout.
    await expect_error(
        "ask_user_question(no user)",
        AskUserQuestionTool().execute(question="Anyone there?"),
        "no user to ask",
    )

    await expect_error(
        "ask_user_question(bad options)",
        AskUserQuestionTool().execute(question="Which?", options=["a", "a"]),
        "listed twice",
    )

    asked = []
    user_io.set_callbacks(asked.append, lambda *_: None)
    task = asyncio.create_task(
        PresentTool().execute(content="I read the config and changed the default.", title="What I found")
    )
    for _ in range(200):
        if asked:
            break
        await asyncio.sleep(0)
    assert asked, "present never asked"
    user_io.respond(asked[-1].id, "skip the migration")
    r = await task
    user_io.reset()
    record("present", r)
    assert r.status is ToolResultStatus.SUCCESS
    assert 'The user responded: "skip the migration"' in r.output

    await expect_error(
        "present(no content)",
        PresentTool().execute(content="  "),
        "needs content",
    )

    # -- 1b. subagents (Phase 5) ---------------------------------------------
    #
    # The tools are turn-scoped: ``subagent`` runs real model work, so what a
    # no-provider, no-turn script can drive is the fail-closed set. The two
    # refusals a model must be able to read are "no turn is running" (the tool
    # is a turn-scoped call, not a standalone one) and the registry's unknown
    # name, which is the error either of the other two verbs produces when the
    # name is wrong. The success path is covered with a stub provider in
    # tests/unit/test_subagents.py, which is where a child's run belongs.
    from tonyagent.tools.subagent_tools import (
        InterruptAgentTool,
        ListAgentsTool,
        SubagentTool,
        subagent_registry,
    )

    subagent_registry.restart()
    try:
        await expect_error(
            "subagent(no turn)",
            SubagentTool().execute(task="summarise the project"),
            "no turn is running",
        )

        r = await ListAgentsTool().execute()
        record("list_agents", r)
        assert r.status is ToolResultStatus.SUCCESS and "No subagents" in r.output

        await expect_error(
            "interrupt_agent(unknown)",
            InterruptAgentTool().execute(name="ghost"),
            "no subagent named",
        )
    finally:
        subagent_registry.restart()

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
            # Labelled "no runtime" rather than "stopped": in --fast no runtime
            # is ever attached, and 13 of these tools are served perfectly well
            # by the local runtime. They all fail here for the same reason --
            # nothing is attached -- so the isolation-specific message is not
            # what to expect. That one is covered by test_local_sandbox.py,
            # which attaches the local runtime on purpose.
            await expect_error(
                f"{tool.name}(no runtime)", tool().execute(**kwargs), "runtime"
            )
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
