"""The confirmation gate: it must refuse rather than skip, and it must end.

Three measured holes lived here, and every one of them was invisible to the
suite because each test either installed a bridge or called the tool directly:

1. **It skipped when there was nobody to ask.** ``_request_confirmation``
   returned ``None`` with no callback installed, and the caller reads ``None``
   as "approved" -- so ``delete_file`` ran with no prompt and no user. Measured:
   status ``success``, the file gone. The window always installs a bridge,
   which is why it never showed up in front of anyone.
2. **A cancelled prompt leaked.** The cleanup was a statement after the wait
   rather than a ``finally``, so cancelling the turn left the entry in
   ``_pending_confirmations`` for the life of the process.
3. **A stopped turn kept its dialog.** Nothing published
   ``confirmation.resolved`` when a prompt was abandoned, and Stop did not
   release the tool at all -- it sat out its full 60-second timeout before the
   turn could end. Measured, on the real session: the dialog stayed up and the
   turn took a minute to stop.

The gate is checked on the path the agent actually uses
(``execute_tool_async``) rather than by calling the tool, for the same reason
``test_tool_orchestrator_path.py`` exists.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

import tonyagent.tools  # noqa: F401  -- importing registers every tool
from tonyagent.folder import folder_manager
from tonyagent.tools.base import ToolResultStatus
from tonyagent.tools.orchestrator import ToolCall, ToolOrchestrator


@pytest.fixture
def project(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(folder_manager, "_current_folder", tmp_path)
    return tmp_path


async def _approve(orch, request) -> None:
    """Answer a prompt a tick later, as the window does."""
    await asyncio.sleep(0)
    orch.respond_to_confirmation(request.tool_call.id, True)


def _answering(orch) -> None:
    orch.set_confirmation_callback(
        lambda request: asyncio.get_running_loop().create_task(_approve(orch, request))
    )


async def test_a_destructive_tool_is_refused_when_nothing_can_ask(project):
    """No bridge is not permission. The call is refused, and nothing happens."""
    (project / "a.txt").write_text("hello", encoding="utf-8")
    orch = ToolOrchestrator()
    assert orch._confirmation_callback is None, "this test is about the no-bridge case"

    logged: list[str] = []
    orch.set_log_callback(lambda message, level: logged.append(message))

    result = await orch.execute_tool_async(
        ToolCall(id="d1", name="delete_file", arguments={"path": "a.txt"})
    )

    assert result.status is ToolResultStatus.ERROR, result.status
    assert "delete_file" in (result.error or ""), (
        "the refusal has to name the tool the model asked for"
    )
    assert "not run" in (result.error or "")
    assert (project / "a.txt").exists(), "the file was deleted anyway"
    assert not any("Executing delete_file" in line for line in logged), (
        "the tool was executed; the gate refused after it had already run"
    )


async def test_the_same_call_runs_once_a_user_says_yes(project):
    """The negative of the test above -- proving it is a gate, not a broken tool."""
    (project / "a.txt").write_text("hello", encoding="utf-8")
    orch = ToolOrchestrator()
    _answering(orch)

    result = await orch.execute_tool_async(
        ToolCall(id="d2", name="delete_file", arguments={"path": "a.txt"})
    )

    assert result.status is ToolResultStatus.SUCCESS, result.error
    assert not (project / "a.txt").exists()


async def test_a_cancelled_prompt_leaves_nothing_behind(project):
    """The leak, exercised: cancel while the dialog is up."""
    (project / "a.txt").write_text("hello", encoding="utf-8")
    orch = ToolOrchestrator()
    asked: list[str] = []
    orch.set_confirmation_callback(lambda request: asked.append(request.tool_call.id))

    task = asyncio.create_task(
        orch.execute_tool_async(
            ToolCall(id="d3", name="delete_file", arguments={"path": "a.txt"})
        )
    )
    for _ in range(200):
        if asked:
            break
        await asyncio.sleep(0)
    assert asked == ["d3"], "the prompt never went up"

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert orch._pending_confirmations == {}, (
        "a prompt nobody can answer outlived the call it belonged to"
    )
    assert (project / "a.txt").exists(), "a cancelled prompt still deleted the file"


# --- the same contract, on the real session ----------------------------------


class _Provider:
    """Answers the first turn with a destructive call, then with text."""

    model = "stub"

    def __init__(self, arguments: dict):
        self.arguments = arguments
        self._asked = False

    def validate_credentials(self) -> bool:
        return True

    def estimate_tokens(self, messages) -> int:
        return 1

    async def chat_completion(self, messages=None, tools=None, tool_choice=None,
                              stream=False, **kw):
        from tonyagent.providers import ChatCompletionChunk

        async def gen():
            if not self._asked:
                self._asked = True
                yield ChatCompletionChunk(
                    tool_calls=[
                        {
                            "id": "call-1",
                            "function": {
                                "name": "write",
                                "arguments": json.dumps(self.arguments),
                            },
                        }
                    ],
                    finish_reason="tool_calls",
                )
            else:
                yield ChatCompletionChunk(content="done", finish_reason="stop")

        return gen()


async def test_a_prompt_nobody_answers_is_refused_when_the_wait_runs_out(
    project, monkeypatch
):
    """The likeliest real case: the user walked away.

    The timeout path publishes nothing on its own, so before this the window's
    dialog stayed up over a call that had already been refused -- the answer
    never came and nothing said so. The wait itself is shortened rather than sat
    out; the constant is one knob for exactly this reason.
    """
    from tonyagent.core.events import EventBus, EventType
    from tonyagent.core.session import AgentSession
    from tonyagent.tools import orchestrator as orchestrator_module
    from tonyagent.tools.orchestrator import tool_orchestrator

    monkeypatch.setattr(orchestrator_module, "CONFIRMATION_TIMEOUT_S", 0.05)
    previous = tool_orchestrator._confirmation_callback
    session = AgentSession(bus=EventBus())
    session.provider = _Provider({"path": "kept.txt", "content": "x"})
    session.model = "stub"
    session.install_confirmation_bridge()

    seen: list = []
    session.bus.subscribe(seen.append)
    try:
        await asyncio.wait_for(session.run_turn("write it"), timeout=5)
    finally:
        tool_orchestrator.set_confirmation_callback(previous)

    def ids(event_type):
        return [e.payload["id"] for e in seen if e.type is event_type]

    assert ids(EventType.CONFIRMATION_REQUESTED), "the prompt never reached the window"
    assert ids(EventType.CONFIRMATION_RESOLVED) == ids(EventType.CONFIRMATION_REQUESTED), (
        "the dialog was left up after the wait ran out"
    )
    assert not (project / "kept.txt").exists()
    assert tool_orchestrator._pending_confirmations == {}
    assert session._open_confirmations == set()


async def test_stop_answers_the_prompt_and_releases_the_tool(project):
    """Stop during a destructive prompt ends it there, not 60 seconds later.

    Measured before the fix: the dialog stayed up (nothing published
    ``confirmation.resolved``) and the tool sat on its timeout, so the turn took
    the full minute to come back -- for a turn the user had already stopped.
    """
    from tonyagent.core.events import EventBus, EventType
    from tonyagent.core.session import AgentSession
    from tonyagent.tools.orchestrator import tool_orchestrator

    previous = tool_orchestrator._confirmation_callback
    session = AgentSession(bus=EventBus())
    session.provider = _Provider({"path": "kept.txt", "content": "x"})
    session.model = "stub"
    session.install_confirmation_bridge()

    seen: list = []
    session.bus.subscribe(seen.append)
    asked_ids: list[str] = []
    session.bus.subscribe(
        lambda event: asked_ids.append(event.payload.get("id", ""))
        if event.type is EventType.CONFIRMATION_REQUESTED
        else None
    )

    loop = asyncio.get_running_loop()
    started = loop.time()
    turn = asyncio.create_task(session.run_turn("write it"))
    try:
        for _ in range(400):
            if asked_ids:
                break
            await asyncio.sleep(0.005)
        assert asked_ids, "the prompt never reached the window"

        session.cancel()
        await asyncio.wait_for(turn, timeout=5)
    finally:
        tool_orchestrator.set_confirmation_callback(previous)

    elapsed = loop.time() - started
    resolved = [e for e in seen if e.type is EventType.CONFIRMATION_RESOLVED]
    assert [e.payload["id"] for e in resolved] == asked_ids, (
        "the dialog's call was never resolved, so it stays on screen"
    )
    assert any(
        e.type is EventType.TURN_FINISHED and e.payload.get("cancelled")
        for e in seen
    ), "the turn did not report the stop as a stop"
    assert elapsed < 5, (
        f"Stop took {elapsed:.1f}s -- the tool sat out its confirmation timeout "
        "instead of being released"
    )
    assert not (project / "kept.txt").exists(), "a stopped turn still wrote the file"
    assert tool_orchestrator._pending_confirmations == {}
    assert session._open_confirmations == set()
