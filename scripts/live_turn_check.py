"""One live turn against the loopback provider, for the Phase 7 gate.

Binds airllm (no key; the server ignores auth) in Chat mode, runs a turn with
no tools involved, and prints the response plus the turn's usage. Nothing is
written to config or the keyring.

The response and usage are read from the finished session rather than from the
event bus: the bus is the frontends' stream, and this script is a gate, so it
reads the record.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from tonyagent.core.events import EventBus  # noqa: E402
from tonyagent.core.session import AgentSession  # noqa: E402
from tonyagent.providers import local_airllm  # noqa: F401 - registers airllm
from tonyagent.providers.factory import CHAT_MODE  # noqa: E402


async def main() -> int:
    session = AgentSession(bus=EventBus())
    session.set_mode(CHAT_MODE)
    bound = session.bind_provider("airllm", model="deepseek-v4.1-flash")
    if bound is None:
        print("BIND FAILED")
        return 1
    print(f"bound: {session.provider_name} / {session.model}")
    await session.run_turn("Reply with exactly this word and nothing else: pinecone")
    for message in session.messages:
        print(f"{message.role}: {message.content!r}")
    print(f"usage: {session._turn_usage}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
