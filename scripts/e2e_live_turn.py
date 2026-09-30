"""Prove a live model calls tools with the argument names we sent it.

Everything else in this repo tests the pipeline up to the HTTP request. This
drives the one leg nothing else can: a real model reading our tool schemas and
emitting a call back. The wire-format bug fixed in `28d8ca3` was invisible to
every unit test precisely because it lived on that leg -- each tool reached the
model as a single parameter named ``type``, and the model dutifully called
tools that no longer matched the code running them.

It speaks to the **packaged sidecar binary** over stdio, not to an imported
session, because the interesting failures are process-level: the config path a
packaged app resolves, the keyring, the frozen bytecode.

    python scripts/e2e_live_turn.py
    python scripts/e2e_live_turn.py --binary app/src-tauri/binaries/tonyagent-core-x86_64-pc-windows-msvc.exe
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

#: A task that cannot be answered without opening a file. If the model replies
#: from memory, the schemas never reached it and the run proves nothing.
PROMPT = (
    "In this project, what is the name of the function that decides where the "
    "config file lives? Look it up with the tools and quote the line."
)


class Sidecar:
    """The stdio protocol, driven from both ends at once.

    Requests go in on stdin while events come out on stdout, so a reader thread
    is not optional: writing the request and *then* reading would deadlock on a
    turn that streams deltas before its reply.
    """

    def __init__(self, binary: Path) -> None:
        self.proc = subprocess.Popen(
            [str(binary)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=str(ROOT),
        )
        self.events: list[dict] = []
        self.replies: dict[int, dict] = {}
        self._next_id = 0
        self._lock = threading.Lock()
        self.logs: list[str] = []
        self._readers = [
            threading.Thread(target=self._read_stdout, daemon=True),
            threading.Thread(target=self._read_stderr, daemon=True),
        ]
        for reader in self._readers:
            reader.start()

    def _read_stdout(self) -> None:
        for line in self.proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                frame = json.loads(line)
            except ValueError:
                continue
            with self._lock:
                if frame.get("event") is True:
                    self.events.append(frame)
                elif "id" in frame:
                    self.replies[frame["id"]] = frame

    def _read_stderr(self) -> None:
        for line in self.proc.stderr:
            self.logs.append(line.rstrip())

    def call(self, method: str, params: dict | None = None, timeout: float = 60) -> dict:
        """Send one request and wait for its reply."""
        with self._lock:
            self._next_id += 1
            request_id = self._next_id
        payload = {"id": request_id, "method": method, "params": params or {}}
        self.proc.stdin.write(json.dumps(payload) + "\n")
        self.proc.stdin.flush()

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self._lock:
                if request_id in self.replies:
                    return self.replies.pop(request_id)
            time.sleep(0.05)
        raise TimeoutError(f"{method} did not reply within {timeout}s")

    def wait_for(self, event_type: str, timeout: float = 180) -> dict:
        """Block until an event of this type arrives."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            for event in list(self.events):
                if event.get("type") == event_type:
                    return event
            time.sleep(0.1)
        raise TimeoutError(f"never saw a {event_type} event")

    def of_type(self, event_type: str) -> list[dict]:
        return [e for e in self.events if e.get("type") == event_type]

    def close(self) -> None:
        try:
            self.proc.stdin.close()
        except Exception:
            pass
        try:
            self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.proc.kill()


def _p(text: str) -> None:
    print(str(text).encode("ascii", "replace").decode())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", type=Path, default=None)
    parser.add_argument("--folder", type=Path, default=ROOT)
    parser.add_argument("--timeout", type=float, default=180.0)
    args = parser.parse_args()

    binary = args.binary or (
        ROOT / "app" / "src-tauri" / "binaries" /
        "tonyagent-core-x86_64-pc-windows-msvc.exe"
    )
    if not binary.exists():
        _p(f"sidecar binary not found: {binary}\nbuild it with: cd app && npm run sidecar")
        return 2

    _p(f"sidecar: {binary}")
    sidecar = Sidecar(binary)
    failures: list[str] = []
    try:
        state = sidecar.call("state")
        if state.get("error"):
            _p(f"FAIL  state: {state['error']}")
            return 1
        _p(f"state  provider={state['result'].get('provider')!r} "
           f"model={state['result'].get('model')!r} bound={state['result'].get('bound')}")
        if not state["result"].get("bound"):
            failures.append("the sidecar came up with no provider bound")

        started = sidecar.call("sandbox.start", {"path": str(args.folder)}, timeout=90)
        _p(f"runtime running={started.get('result', {}).get('running')} "
           f"isolated={started.get('result', {}).get('isolated')}")

        reply = sidecar.call("send", {"text": PROMPT})
        if reply.get("error"):
            _p(f"FAIL  send: {reply['error'].get('message')}")
            return 1

        sidecar.wait_for("turn.finished", timeout=args.timeout)

        calls = sidecar.of_type("tool.started")
        results = sidecar.of_type("tool.completed")
        answer = "".join(
            e.get("payload", {}).get("text", "") for e in sidecar.of_type("message.delta")
        )

        _p("")
        _p(f"tool calls : {len(calls)}")
        for call in calls:
            payload = call.get("payload", {})
            _p(f"  - {payload.get('name')}({json.dumps(payload.get('arguments'), default=str)})")

        _p("")
        _p(f"tool results: {len(results)}")
        for result in results:
            payload = result.get("payload", {})
            body = payload.get("result", {})
            _p(f"  - {payload.get('name')}: {body.get('status')} {str(body.get('output'))[:90]!r}")

        _p("")
        _p(f"answer: {answer.strip()[:300]}")

        # The load-bearing assertions. Each names the specific way this has
        # failed before, because "a tool was called" alone passes on a call the
        # orchestrator rejected.
        if not calls:
            failures.append("the model answered without calling a tool")

        schema_keywords = {"type", "properties", "required", "items", "enum"}
        for call in calls:
            name = call.get("payload", {}).get("name")
            arguments = call.get("payload", {}).get("arguments") or {}
            if not arguments:
                failures.append(f"{name}: called with no arguments")
            for key in arguments:
                if key in schema_keywords:
                    failures.append(
                        f"{name}: argument named {key!r} -- a JSON Schema keyword leaked "
                        "through as a parameter name"
                    )

        failed = sidecar.of_type("turn.failed")
        if failed:
            failures.append("the turn failed: " + str(failed[0].get("payload", {}).get("message")))

        succeeded = [r for r in results if (r.get("payload", {}).get("result") or {}).get("status") == "success"]
        if calls and not succeeded:
            failures.append("every tool call the model made was rejected")

        _p("")
        if failures:
            for failure in failures:
                _p(f"FAIL  {failure}")
            return 1
        _p("PASS  a live model read our tool schemas and called them correctly")
        return 0
    finally:
        sidecar.close()


if __name__ == "__main__":
    sys.exit(main())