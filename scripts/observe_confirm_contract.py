"""Observe the core half of the confirmation, end to end.

The React test covers what the dialog does with a confirmation. This covers
where the confirmation comes from and what answering it does, because the two
halves meet in one payload and nothing in either suite proves they agree.

Drives the real `ToolOrchestrator` and the real `write_file` tool -- no mocks
of the tool, no fake callback -- and asserts:

  1. an untrusted destructive call raises exactly one confirmation request
  2. the request the callback receives carries the five fields the dialog reads
  3. answering `confirmed=True` runs the tool, and the file appears
  4. answering again changes nothing (the future is done; exactly once)
  5. `confirmed=False` cancels without touching the filesystem
  6. the payload the session publishes on the bus has the same five keys, which
     is what `events.ts` maps into `pendingConfirm`

Run:  python scripts/observe_confirm_contract.py
"""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from tonyagent.core.events import EventType  # noqa: E402
from tonyagent.folder.manager import folder_manager  # noqa: E402
from tonyagent.tools.base import ToolResultStatus  # noqa: E402
from tonyagent.tools.orchestrator import ToolCall, ToolOrchestrator  # noqa: E402

# The keys ConfirmDialog reads, and the keys events.ts pulls out of the payload.
EXPECTED_KEYS = {"id", "name", "arguments", "description", "destructive"}

failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    print(f"  {'ok  ' if condition else 'FAIL'}  {label}{'' if condition else f'  <- {detail}'}")
    if not condition:
        failures.append(label)


async def raise_confirmation(orch: ToolOrchestrator, approved: bool):
    """Run one write_file call that has to ask, and answer it from the callback.

    The callback is the same hook `session.install_confirmation_bridge` uses, so
    this is the real request object on its way to the event bus.
    """
    requests: list = []

    def on_request(request):
        requests.append(request)
        # Answer from a callback, exactly as the UI's click handler does -- the
        # future must be resolvable from outside the awaiting coroutine.
        orch.respond_to_confirmation(request.tool_call.id, approved)

    orch.set_confirmation_callback(on_request)
    with tempfile.TemporaryDirectory() as tmp:
        folder_manager._current_folder = Path(tmp)
        result = await orch.execute_tool_async(
            ToolCall(
                id="call-1",
                name="write_file",
                arguments={"path": "notes.txt", "content": "hello"},
            )
        )
        wrote = (Path(tmp) / "notes.txt").exists()
        content = (Path(tmp) / "notes.txt").read_text() if wrote else ""
    orch.set_confirmation_callback(None)
    folder_manager._current_folder = None
    return requests, result, wrote, content


async def main() -> int:
    print("1. approved: one request, tool runs, file written")
    orch = ToolOrchestrator()
    requests, result, wrote, content = await raise_confirmation(orch, True)
    check("exactly one confirmation was raised", len(requests) == 1, f"got {len(requests)}")
    check("the tool succeeded", result.status is ToolResultStatus.SUCCESS, str(result.error))
    check("the file exists", wrote)
    check("the content is what was asked for", content == "hello", repr(content))

    request = requests[0]
    check("the request names the tool", request.tool_call.name == "write_file", request.tool_call.name)
    check("the request carries the call id", request.tool_call.id == "call-1", request.tool_call.id)
    check("the request carries the arguments", request.tool_call.arguments.get("path") == "notes.txt")
    check("the tool is marked destructive", request.tool.destructive is True)
    check("the tool has a description for the payload", bool(request.tool.description))

    print("\n2. answering twice runs nothing twice")
    orch = ToolOrchestrator()
    seen: list = []

    def collect(req):
        seen.append(req)
        orch.respond_to_confirmation(req.tool_call.id, True)
        # A second answer for the same call, as a double-click or a retried
        # request would produce.
        orch.respond_to_confirmation(req.tool_call.id, False)

    orch.set_confirmation_callback(collect)
    with tempfile.TemporaryDirectory() as tmp:
        folder_manager._current_folder = Path(tmp)
        result = await orch.execute_tool_async(
            ToolCall(id="call-2", name="write_file", arguments={"path": "twice.txt", "content": "x"})
        )
        wrote = (Path(tmp) / "twice.txt").exists()
    orch.set_confirmation_callback(None)
    folder_manager._current_folder = None
    check("the first answer decided it", result.status is ToolResultStatus.SUCCESS, str(result.error))
    check("the second answer did not re-decide it", wrote, "the file was not written")

    print("\n3. denied: cancelled, filesystem untouched")
    requests, result, wrote, _ = await raise_confirmation(ToolOrchestrator(), False)
    check("exactly one confirmation was raised", len(requests) == 1, f"got {len(requests)}")
    check("the result is cancelled, not an error", result.status is ToolResultStatus.CANCELLED, str(result.status))
    check("nothing was written", not wrote)

    print("\n4. the payload the session publishes matches what the dialog reads")
    from tonyagent.core.session import AgentSession

    session = AgentSession()
    published: list = []
    session.bus.subscribe(published.append)
    session._on_confirmation_requested(request)
    events = [e for e in published if e.type is EventType.CONFIRMATION_REQUESTED]
    check("one confirmation.requested was published", len(events) == 1, f"got {len(events)}")
    payload = events[0].payload
    check("the payload has exactly the five keys the dialog reads", set(payload) == EXPECTED_KEYS, str(sorted(payload)))
    check("id", payload["id"] == "call-1", str(payload["id"]))
    check("name", payload["name"] == "write_file", str(payload["name"]))
    check("destructive", payload["destructive"] is True, str(payload["destructive"]))
    check("arguments is the raw dict the reducer formats", isinstance(payload["arguments"], dict))

    print("\n   wire payload as the frontend receives it:")
    print("   " + json.dumps({"type": "confirmation.requested", "payload": payload}, default=str))

    print()
    if failures:
        print(f"{len(failures)} FAILED: {failures}")
        return 1
    print("all core-side confirmation behaviour observed as expected")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
