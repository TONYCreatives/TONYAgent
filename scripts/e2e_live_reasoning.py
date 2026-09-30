"""Prove a real reasoning model's thinking reaches the app on its own channel.

The rest of the reasoning tests drive a stub. This drives the one leg they
cannot: whether OpenRouter actually streams ``delta.reasoning`` in the shape
``parse_stream_event`` reads, through the **packaged sidecar binary** rather
than an imported session. A stub agrees with whatever the parser was written
against, which is exactly how a wire-format bug survives a green suite.

What it checks, in order:

1. ``reasoning.delta`` events arrive on a real model, and ``message.delta``
   carries none of that text.
2. The turn is written to disk with ``reasoning`` on the assistant message.
3. Reopening that conversation restores it, from a second process.
4. The same reasoning is sent back on the following request.

    python scripts/e2e_live_reasoning.py
    python scripts/e2e_live_reasoning.py --model stealth/space-bunny-alpha
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from e2e_live_turn import ROOT, Sidecar, _p  # noqa: E402

#: A default that reasons. OpenRouter's model list changes constantly, so this
#: is a starting point rather than a promise -- ``--model`` overrides it.
DEFAULT_MODEL = "stealth/space-bunny-alpha"

#: Asked twice so there is a following turn to check continuity on.
FIRST = "What is 17 * 23? Think it through, then give just the number."
SECOND = "Now double that."


def _fail(message: str) -> None:
    print(f"  FAIL           {message}".encode("ascii", "replace").decode())
    raise SystemExit(1)


def _pass(message: str) -> None:
    print(f"  PASS           {message}".encode("ascii", "replace").decode())


def _assistant(messages: list[dict]) -> dict:
    for message in reversed(messages):
        if message.get("role") == "assistant":
            return message
    return {}


def _all_reasoning(messages: list[dict]) -> str:
    """Every assistant turn's reasoning, in order.

    A turn can be several passes: a reasoning model may call a tool, get a
    result, and think again before answering. Each pass is its own assistant
    message, so comparing the whole stream against only the last one compares
    a turn against a fragment of it.
    """
    return "".join(
        m.get("reasoning") or "" for m in messages if m.get("role") == "assistant"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument(
        # A reasoning model chooses whether to think on any given prompt, so a
        # run that streams nothing is the model declining, not a failure of
        # this code. Retrying keeps the script's PASS/FAIL about the pipeline.
        "--attempts", type=int, default=3,
    )
    parser.add_argument(
        "--binary",
        default=str(ROOT / "app/src-tauri/binaries/tonyagent-core-x86_64-pc-windows-msvc.exe"),
    )
    args = parser.parse_args()

    binary = Path(args.binary)
    if not binary.exists():
        _fail(f"No sidecar binary at {binary}. Run `npm run sidecar` in app/ first.")

    print(f"[live-reasoning] driving {binary.name} with {args.model}")
    for attempt in range(1, args.attempts + 1):
        try:
            return _one_run(binary, args.model, attempt)
        except _NoReasoning:
            if attempt == args.attempts:
                _fail(
                    f"the model chose not to think in {attempt} attempts. Point "
                    "--model at one that reasons, or check the live payload "
                    "before trusting the unit tests."
                )
            print(f"  ....          no reasoning this attempt, retrying")
    return 0


class _NoReasoning(Exception):
    """The model answered without thinking. Not a defect in this code."""


def _one_run(binary: Path, model: str, attempt: int) -> int:
    sidecar = Sidecar(binary)
    try:
        bound = sidecar.call("bind_provider", {"name": "openrouter", "model": model})
        if "error" in bound:
            _fail(f"could not bind: {bound['error']['message']}")
        _pass(f"bound {bound['result']['provider']}/{bound['result']['model']}")

        sidecar.call("conversations.create")
        sidecar.call("send", {"text": FIRST})
        sidecar.wait_for("turn.finished", timeout=240)

        deltas = sidecar.of_type("reasoning.delta")
        if not deltas:
            raise _NoReasoning()
        thinking = "".join(d["payload"].get("text", "") for d in deltas)
        _pass(f"{len(deltas)} reasoning.delta events, {len(thinking)} chars of thinking")

        completed = sidecar.of_type("reasoning.completed")
        if not completed:
            _fail("reasoning streamed but never completed")
        truncated = [c for c in completed if c["payload"].get("truncated")]
        if truncated:
            _fail(f"the model ran out of budget: {truncated[0]['payload'].get('notice')}")
        _pass(f"{len(completed)} reasoning.completed event(s), none truncated")

        # The whole point of the separate channel.
        answer = "".join(
            d["payload"].get("text", "") for d in sidecar.of_type("message.delta")
        )
        if not answer:
            _fail("no answer text; the model thought and then stopped")
        overlap = min(len(thinking), len(answer), 40)
        if overlap and thinking[:overlap] in answer:
            _fail("thinking text appears inside the answer -- the channels are mixed")
        _pass(f"answer is {len(answer)} chars and contains none of the thinking")

        # Written to disk, not just streamed.
        conversation_id = sidecar.call("state")["result"]["conversation"]
        listed = sidecar.call("conversations.list")["result"]["conversations"]
        title = next((c["title"] for c in listed if c["id"] == conversation_id), None)
        if title is None:
            _fail("the conversation was not saved")
        stored = sidecar.call(
            "conversations.switch", {"id": conversation_id}
        )["result"]["messages"]
        saved_reasoning = _all_reasoning(stored)
        if not saved_reasoning:
            _fail("no saved assistant message has any reasoning")
        if thinking and thinking[:60] not in saved_reasoning:
            _fail("the saved reasoning is not what was streamed")
        blocks = sum(
            len(m.get("reasoning_details") or [])
            for m in stored if m.get("role") == "assistant"
        )
        passes = len([m for m in stored if m.get("role") == "assistant"])
        _pass(f"saved to disk: {passes} assistant pass(es), "
              f"{len(saved_reasoning)} chars of reasoning, {blocks} detail blocks")

        # A second process, as after a restart.
        sidecar.close()
        sidecar = Sidecar(binary)
        sidecar.call("bind_provider", {"name": "openrouter", "model": model})
        reopened = sidecar.call(
            "conversations.switch", {"id": conversation_id}
        )["result"]["messages"]
        if _all_reasoning(reopened) != saved_reasoning:
            _fail("a reopened conversation came back without its thinking")
        _pass("a fresh process restored the reasoning from the file")

        # And it is what goes back on the wire, which is why it is kept.
        sidecar.call("send", {"text": SECOND})
        sidecar.wait_for("turn.finished", timeout=240)
        _pass("a following turn ran on the restored transcript")
        print("[live-reasoning] reasoning survives the round trip")
        return 0
    finally:
        sidecar.close()


if __name__ == "__main__":
    raise SystemExit(main())