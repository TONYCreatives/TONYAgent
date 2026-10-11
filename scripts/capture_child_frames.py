"""Regenerate the subagent frame fixture in ``app/src/events.test.ts``.

A child session emits its own ``turn.started`` .. ``turn.finished`` on the same
bus as its parent, under its own turn id (Phase 5). The frontend test that
pins how the window treats those frames replays a *captured* sequence rather
than a hand-written one, because a hand-written sequence is exactly how a
test ends up asserting a shape the core never sends.

This script runs one real parent turn -- whose stub provider calls
``subagent`` and then answers -- with a child that runs one real tool
(``list_agents``) and then answers, and prints every frame the window would
receive, in wire order. Run it from the repo root and paste the frames into
``SUBAGENT_RUN``:

    python scripts/capture_child_frames.py

The turn ids and text differ on every run; the fixture in the test keeps one
capture's values, because ids only need to *differ* to carry the property. The
attribution fields (``subagent``, ``parent_call_id``) are copied verbatim:
they are the link the nested view is built on.
"""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import tonyagent.tools  # noqa: E402,F401  -- registers every tool

from tonyagent.core.events import EventBus  # noqa: E402
from tonyagent.core.session import AgentSession  # noqa: E402
from tonyagent.providers import ChatCompletionChunk  # noqa: E402


class _StubProvider:
    """Answers the parent, the child, and the parent's second pass.

    The child shares the parent's provider object -- that is the design -- so
    the stub tells them apart by the conversation it is handed: the child's
    only message besides the system prompt is the seed.
    """

    model = "stub-model"

    def estimate_tokens(self, messages):
        return 1

    async def chat_completion(self, messages=None, tools=None, tool_choice=None,
                              stream=False, **kw):
        messages = messages or []
        in_child = any(
            m.role_value == "user" and m.content == "child work" for m in messages
        )
        last = messages[-1]

        async def gen():
            if in_child:
                if last.role_value == "tool":
                    yield ChatCompletionChunk(content="child answer", finish_reason="stop")
                else:
                    yield ChatCompletionChunk(
                        tool_calls=[{
                            "id": "kid-1",
                            "function": {"name": "list_agents", "arguments": "{}"},
                        }],
                        finish_reason="tool_calls",
                    )
            elif last.role_value == "tool":
                yield ChatCompletionChunk(content="parent answer", finish_reason="stop")
            else:
                yield ChatCompletionChunk(
                    tool_calls=[{
                        "id": "sub-1",
                        "function": {
                            "name": "subagent",
                            "arguments": json.dumps(
                                {"task": "child work", "name": "probe"}
                            ),
                        },
                    }],
                    finish_reason="tool_calls",
                )

        return gen()


async def main() -> None:
    bus = EventBus()
    session = AgentSession(bus=bus)
    session.provider = _StubProvider()
    session.model = "stub-model"
    frames: list = []
    bus.subscribe(lambda e: frames.append({"event": True, **e.to_dict()}))
    await session.run_turn("delegate this")
    for frame in frames:
        # `seq` is a per-process counter, not part of the shape a test needs.
        frame.pop("seq", None)
    print(json.dumps(frames, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
