"""The usage ledger: what it stores, what it must never store, and how it counts.

The dashboard reads all of this, so the arithmetic is pinned here rather than
eyeballed in a chart: an off-by-one in the window or a double-counted reasoning
token is invisible in a bar and wrong in the number beside it.
"""

from __future__ import annotations

import asyncio
import io
import json
import time
from datetime import datetime, timedelta

import pytest

import tonyagent.core.usage as usage_mod
from tonyagent.api.dialects import Dialect
from tonyagent.core.usage import (
    MAX_BUCKETS,
    UsageLedger,
    UsageRecord,
    fingerprint,
    window_start,
)


def _noon(days_ago: float = 0) -> float:
    """Local noon, `days_ago` days back.

    Noon rather than midnight so that a test cannot pass by being accidentally
    on the boundary it is meant to be testing.
    """
    moment = datetime.fromtimestamp(time.time()).replace(
        hour=12, minute=0, second=0, microsecond=0
    )
    return (moment - timedelta(days=days_ago)).timestamp()


@pytest.fixture
def ledger(tmp_path) -> UsageLedger:
    return UsageLedger(tmp_path / "usage.jsonl")


def _add(ledger, ts, **kw) -> None:
    ledger.record(
        UsageRecord(
            ts=ts,
            provider=kw.pop("provider", "openrouter"),
            key_id=kw.pop("key_id", "ab12cd34"),
            model=kw.pop("model", "some/model"),
            **kw,
        )
    )


# --- the key is never written down -----------------------------------------
def test_the_fingerprint_is_stable_and_is_not_the_key():
    key = "sk-or-v1-0123456789abcdef"
    first = fingerprint("openrouter", key)
    assert first == fingerprint("openrouter", key)
    assert first != fingerprint("anthropic", key), "the same key on two endpoints is two keys"
    assert key not in first
    assert not any(part and part in key for part in [first])


def test_no_record_ever_contains_the_key(ledger):
    """The load-bearing one: this file is plaintext and outlives the session."""
    key = "sk-or-v1-0123456789abcdef"
    _add(ledger, _noon(), input_tokens=10, output_tokens=20)
    written = (ledger.path).read_text(encoding="utf-8")
    assert key not in written
    assert key[-8:] not in written, "a last-four label would have left these here"


# --- windows ---------------------------------------------------------------
def test_today_starts_at_local_midnight():
    start = window_start("today")
    moment = datetime.fromtimestamp(start)
    assert (moment.hour, moment.minute, moment.second) == (0, 0, 0)


def test_a_seven_day_window_is_seven_calendar_days_including_today():
    start = datetime.fromtimestamp(window_start("7d"))
    today = datetime.fromtimestamp(time.time()).replace(hour=0, minute=0, second=0, microsecond=0)
    assert (today - start).days == 6


def test_all_has_no_lower_bound():
    assert window_start("all") is None


def test_a_window_excludes_what_came_before_it(ledger):
    _add(ledger, _noon(10), input_tokens=1)
    _add(ledger, _noon(1), input_tokens=2)
    assert ledger.summary("7d")["totals"]["requests"] == 1
    assert ledger.summary("30d")["totals"]["requests"] == 2
    assert ledger.summary("all")["totals"]["requests"] == 2


def test_the_day_series_covers_the_whole_window_empty_days_included(ledger):
    """A chart that skipped empty days would draw Tuesday beside Thursday."""
    _add(ledger, _noon(3))
    buckets = ledger.summary("7d")["buckets"]
    assert len(buckets) == 7
    assert sum(b["requests"] for b in buckets) == 1
    assert [b["requests"] for b in buckets].count(0) == 6


def test_all_time_is_capped_so_one_chart_is_not_a_year_of_bars(ledger):
    _add(ledger, _noon(400))
    _add(ledger, _noon())
    assert len(ledger.summary("all")["buckets"]) == MAX_BUCKETS


def test_an_empty_ledger_is_an_empty_week_not_an_error(ledger):
    summary = ledger.summary("7d")
    assert summary["totals"]["requests"] == 0
    assert len(summary["buckets"]) == 7
    assert summary["tracking_since"] is None


# --- counting --------------------------------------------------------------
def test_reasoning_tokens_are_not_counted_twice(ledger):
    """The provider bills reasoning inside completion tokens; adding it again
    would report a long think as a bigger bill than it was."""
    _add(ledger, _noon(), input_tokens=100, output_tokens=500, reasoning_tokens=400)
    totals = ledger.summary("7d")["totals"]
    assert totals["output_tokens"] == 500
    assert totals["reasoning_tokens"] == 400
    assert totals["total_tokens"] == 600


def test_a_failed_request_is_still_a_request(ledger):
    _add(ledger, _noon())
    _add(ledger, _noon(), ok=False)
    totals = ledger.summary("7d")["totals"]
    assert totals["requests"] == 2
    assert totals["failed"] == 1


def test_by_key_separates_providers_and_rotated_keys(ledger):
    _add(ledger, _noon(), key_id="aaaaaaaa", model="m")
    _add(ledger, _noon(), key_id="aaaaaaaa", model="m")
    _add(ledger, _noon(), key_id="bbbbbbbb", model="m")
    _add(ledger, _noon(), provider="anthropic", key_id="aaaaaaaa", model="m")
    by_key = ledger.summary("7d")["by_key"]
    assert [(e["provider"], e["detail"], e["requests"]) for e in by_key] == [
        ("openrouter", "aaaaaaaa", 2),
        ("anthropic", "aaaaaaaa", 1),
        ("openrouter", "bbbbbbbb", 1),
    ]


def test_a_torn_line_costs_itself_and_not_the_history(ledger):
    """A hard exit can leave half a line on the end of the file."""
    _add(ledger, _noon(), input_tokens=5)
    with ledger.path.open("a", encoding="utf-8") as handle:
        handle.write('{"ts": 123, "provider": "openr')
    _add(ledger, _noon(), input_tokens=7)
    assert ledger.summary("7d")["totals"]["input_tokens"] == 12


# --- streaming usage -------------------------------------------------------
def test_a_streamed_request_asks_for_its_usage():
    """Without this the dashboard records every request it ever sees as 0 tokens."""
    payload = Dialect().build_request("m", [], stream=True)
    assert payload["stream_options"] == {"include_usage": True}


def test_the_usage_chunk_is_captured_even_though_it_carries_no_choices():
    dialect = Dialect()
    acc: dict = {}
    chunk = dialect.parse_stream_event(
        "", '{"choices":[],"usage":{"prompt_tokens":11,"completion_tokens":22}}', acc
    )
    assert chunk is None, "the usage chunk is not part of the answer"
    assert acc["usage"].input_tokens == 11
    assert acc["usage"].output_tokens == 22

# --- the request path records itself ---------------------------------------
class _Response:
    def __init__(self, status: int = 200, body: dict | None = None) -> None:
        self.status_code = status
        self._body = body or {}
        self.text = json.dumps(self._body)

    def json(self) -> dict:
        return self._body


class _HTTP:
    """A stand-in for `httpx.AsyncClient` that answers every request the same."""

    def __init__(self, response: _Response) -> None:
        self._response = response

    async def __aenter__(self) -> "_HTTP":
        return self

    async def __aexit__(self, *exc) -> bool:
        return False

    async def post(self, *args, **kwargs) -> _Response:
        return self._response


# Long enough to clear the local length guard, which has its own tests.
TEST_KEY = "sk-test-" + "a" * 40


def _client(monkeypatch, response: _Response):
    from tonyagent.api import client as client_mod

    monkeypatch.setattr(client_mod.httpx, "AsyncClient", lambda **kw: _HTTP(response))
    # Empty prefix and length: this is about the ledger, not about local key
    # validation.
    return client_mod.LLMClient(
        provider="openrouter",
        api_key=TEST_KEY,
        model="some/model",
        base_url="https://example.test/v1",
        key_prefix="",
    )


def _no_network(monkeypatch) -> list[dict]:
    calls: list[dict] = []
    monkeypatch.setattr(usage_mod, "record_request", lambda **kw: calls.append(kw))
    return calls


def test_a_completion_is_recorded_with_its_tokens(monkeypatch):
    calls = _no_network(monkeypatch)
    client = _client(monkeypatch, _Response(200, {
        "choices": [{"message": {"content": "hi"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 11, "completion_tokens": 22},
        "model": "some/model",
    }))
    asyncio.run(client.complete([]))
    assert len(calls) == 1
    assert calls[0]["ok"] is True
    assert calls[0]["input_tokens"] == 11
    assert calls[0]["output_tokens"] == 22
    assert calls[0]["model"] == "some/model"


def test_a_refused_request_is_recorded_too(monkeypatch):
    """A dashboard that only counted the ones that worked would under-report."""
    calls = _no_network(monkeypatch)
    client = _client(monkeypatch, _Response(429, {"error": {"message": "slow down"}}))
    with pytest.raises(Exception):
        asyncio.run(client.complete([]))
    assert len(calls) == 1
    assert calls[0]["ok"] is False
    assert calls[0]["input_tokens"] == 0


def test_what_is_recorded_identifies_the_key_without_being_it(monkeypatch):
    calls = _no_network(monkeypatch)
    client = _client(monkeypatch, _Response(200, {"choices": [], "model": "some/model"}))
    asyncio.run(client.complete([]))
    assert calls[0]["key_id"] == fingerprint("openrouter", TEST_KEY)
    assert TEST_KEY not in json.dumps(calls[0])


# --- the protocol ----------------------------------------------------------
def _drive(requests: list[dict]) -> list[dict]:
    from tonyagent.core.events import EventBus
    from tonyagent.core.session import AgentSession
    from tonyagent.headless.server import StdioServer

    stdin = io.StringIO("\n".join(json.dumps(r) for r in requests) + "\n")
    stdout = io.StringIO()
    asyncio.run(StdioServer(AgentSession(bus=EventBus()), stdin, stdout).serve())
    return [json.loads(line) for line in stdout.getvalue().splitlines() if line.strip()]


def test_usage_summary_answers_the_whole_dashboard_in_one_reply(monkeypatch, tmp_path):
    led = UsageLedger(tmp_path / "u.jsonl")
    _add(led, _noon(), input_tokens=10, output_tokens=5)
    monkeypatch.setattr(usage_mod, "_LEDGER", led)

    frames = _drive([{"id": 1, "method": "usage.summary", "params": {"window": "7d"}}])
    result = frames[0]["result"]
    assert result["window"] == "7d"
    assert result["totals"]["requests"] == 1
    assert result["totals"]["total_tokens"] == 15
    assert len(result["buckets"]) == 7
    assert len(result["by_key"]) == 1
    assert result["tracking_since"] is not None


def test_usage_summary_defaults_to_a_week(monkeypatch, tmp_path):
    monkeypatch.setattr(usage_mod, "_LEDGER", UsageLedger(tmp_path / "u.jsonl"))
    frames = _drive([{"id": 1, "method": "usage.summary"}])
    assert frames[0]["result"]["window"] == "7d"


def test_an_unknown_window_is_refused_rather_than_quietly_defaulted(monkeypatch, tmp_path):
    monkeypatch.setattr(usage_mod, "_LEDGER", UsageLedger(tmp_path / "u.jsonl"))
    frames = _drive([{"id": 1, "method": "usage.summary", "params": {"window": "yesterday"}}])
    assert frames[0]["error"]["code"] == "rejected"
