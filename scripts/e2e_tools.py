"""Live Phase 3 check: tools execute inside the real sandbox via the shared manager.

Usage:  python scripts/e2e_tools.py
Starts the sandbox through the SHARED manager (same object the tools use),
then runs execute_command + browser_navigate + execute_js as real Tool calls.
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from tonyagent.folder.manager import folder_manager
from tonyagent.sandbox import get_shared_sandbox_manager
from tonyagent.sandbox.base import SandboxConfig, SandboxStatus
from tonyagent.tools.base import ToolResultStatus


async def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="tonyagent-tools-e2e-"))
    (tmp / "probe.txt").write_text("hello-tools-e2e", encoding="utf-8")
    folder_manager._current_folder = tmp

    manager = get_shared_sandbox_manager()
    # Network ON: this script exercises browser_navigate, which legitimately needs egress.
    ok = await manager.start(
        SandboxConfig(type="docker", project_path=str(tmp), cpu_limit="1.0", enable_network=True)
    )
    print(f"[e2e-tools] start -> {ok}")
    if not ok or not manager.is_running():
        print("[e2e-tools] FAILED to start sandbox")
        return 1
    try:
        from tonyagent.tools.shell_tools import ExecuteCommandTool
        from tonyagent.tools.browser_tools import (
            BrowserNavigateTool,
            ExecuteJsTool,
            _check_sandbox,
        )

        assert _check_sandbox() is None, "guard should pass while running"

        shell = ExecuteCommandTool()
        r1 = await shell.execute("python -c \"print(open('probe.txt').read())\"", cwd=".", timeout=15)
        print(f"[e2e-tools] execute_command -> {r1.status.value} {r1.output} {r1.error}")
        assert r1.status is ToolResultStatus.SUCCESS and "hello-tools-e2e" in r1.output["stdout"], r1

        # Prove cwd mapping: run from a subdir, read the parent file relatively.
        (tmp / "sub").mkdir(exist_ok=True)
        r1b = await shell.execute("python -c \"print(open('../probe.txt').read())\"", cwd="sub", timeout=15)
        print(f"[e2e-tools] execute_command(subdir) -> {r1b.status.value} {r1b.output}")
        assert r1b.status is ToolResultStatus.SUCCESS and "hello-tools-e2e" in r1b.output["stdout"], r1b

        nav = BrowserNavigateTool()
        r2 = await nav.execute("https://example.com")
        print(f"[e2e-tools] browser_navigate -> {r2.status.value} {r2.output} {r2.error}")
        assert r2.status is ToolResultStatus.SUCCESS, r2

        js = ExecuteJsTool()
        r3 = await js.execute("console.log(40+2)", timeout=10)
        print(f"[e2e-tools] execute_js -> {r3.status.value} {r3.output} {r3.error}")
        assert r3.status is ToolResultStatus.SUCCESS and "42" in str(r3.output), r3

        # Fail-closed: stop the sandbox, command must error (not run on host).
        await manager.stop()
        assert manager.get_backend() is None
        r4 = await shell.execute("python --version")
        print(f"[e2e-tools] post-stop execute -> {r4.status.value} {r4.error}")
        assert r4.status is ToolResultStatus.ERROR and "sandbox" in r4.error.lower(), r4

        print("[e2e-tools] ALL CHECKS PASSED")
        return 0
    except Exception as e:
        print(f"[e2e-tools] FAILED: {type(e).__name__}: {e}")
        return 1
    finally:
        if manager.get_backend() is not None:
            await manager.stop()
        print(f"[e2e-tools] backend after stop: {manager.get_backend()}")


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
