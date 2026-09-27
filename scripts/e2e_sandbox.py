"""Live end-to-end check of the Phase 1 backend against real Docker.

Usage:  python scripts/e2e_sandbox.py
Runs start -> ping -> exec -> browser_navigate -> stop against the real
tonyagent/sandbox:latest image. Needs Docker Desktop running.
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from tonyagent.sandbox.base import SandboxConfig, SandboxStatus
from tonyagent.sandbox.docker_backend import DockerSandboxBackend


async def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="tonyagent-e2e-"))
    (tmp / "probe.txt").write_text("hello-e2e", encoding="utf-8")
    backend = DockerSandboxBackend(
        SandboxConfig(type="docker", project_path=str(tmp), cpu_limit="1.0", enable_network=True)
    )
    print(f"[e2e] project: {tmp}")
    ok = await backend.start()
    print(f"[e2e] start -> {ok} (status={backend.status.value})")
    if not ok:
        return 1
    try:
        assert backend.status is SandboxStatus.RUNNING
        pong = await backend.ping()
        print(f"[e2e] ping -> {pong}")
        result = await backend.execute_command("cat /workspace/probe.txt")
        print(f"[e2e] exec -> rc={result.returncode} stdout={result.stdout.strip()!r}")
        assert result.returncode == 0 and "hello-e2e" in result.stdout
        nav = await backend.browser_navigate("https://example.com")
        print(f"[e2e] browser_navigate -> success={nav.success} data={nav.data} err={nav.error}")
        assert nav.success, nav.error
        stats = await backend.get_stats()
        print(f"[e2e] stats -> {'ok' if stats else 'unavailable'}")
        print("[e2e] ALL CHECKS PASSED")
        return 0
    except Exception as e:
        print(f"[e2e] FAILED: {type(e).__name__}: {e}")
        return 1
    finally:
        await backend.stop()
        print(f"[e2e] stopped (status={backend.status.value})")


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
