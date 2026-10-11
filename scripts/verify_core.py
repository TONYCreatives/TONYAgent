"""The core process and the pump, with no window in the way.

This is the half of the host that the GUI cannot help verify. It spawns the real
core with the real argv and environment, sends one frame, and waits for the
answer to come back through the reader thread and the pump.

No pywebview import at all: a webview is the wrong instrument for testing a
subprocess, and the last two runs showed that mixing them turns a passing test
into a hang that says nothing.
"""

from __future__ import annotations

import json
import time

from tonyagent.window.core import CoreProcess, default_argv, source_env

frames: list[str] = []
logs: list[str] = []


def main() -> int:
    print(f"argv: {default_argv()}", flush=True)
    core = CoreProcess(
        default_argv(),
        frames.extend,
        on_stderr=logs.append,
        env=source_env(),
    )
    started = time.time()
    core.start()
    print("spawned; sending ping", flush=True)
    core.write(json.dumps({"id": 1, "method": "ping"}))

    for _ in range(120):
        if frames:
            break
        time.sleep(0.25)
    elapsed = time.time() - started

    print(f"alive={core.alive} answered_after={elapsed:.1f}s frames={len(frames)}", flush=True)
    for frame in frames[:4]:
        print(f"  <- {frame[:200]}", flush=True)
    print(f"stderr lines={len(logs)}", flush=True)
    for line in logs[:3]:
        print(f"  !! {line[:160]}", flush=True)

    ok = bool(frames) and any('"id": 1' in f or '"id":1' in f for f in frames)
    print(f"ROUND TRIP {'OK' if ok else 'FAILED'}", flush=True)

    core.stop()
    print(f"stopped; alive={core.alive}", flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
