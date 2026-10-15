"""A ledger of API requests, and the aggregates the dashboard draws.

Every completion the window makes is one line in ``usage.jsonl`` under the
config directory. A ledger rather than running counters, because the questions
the dashboard asks are all *windows* -- today, the last 3 days, the last 7, the
last 30, ever -- and a counter cannot answer a window question after the fact: a
day's total can be recomputed from lines, and cannot be recovered from a number.

Append-only, and never rewritten. The file is the record; every shape the
dashboard needs is derived on read, which is what keeps ``record`` cheap enough
to sit inside the request path.

**Nothing here stores a key, or any part of one.** See `fingerprint`.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterator

from loguru import logger

from tonyagent.config.settings import settings


#: The windows the dashboard offers, as the number of calendar days each
#: includes, counting today. ``None`` is everything the ledger holds.
#:
#: Calendar days rather than a rolling N*24 hours: every window is drawn as one
#: bar per day, and a rolling window would draw today as a half-height bar next
#: to six full ones.
WINDOWS: dict[str, int | None] = {
    "today": 1,
    "3d": 3,
    "7d": 7,
    "30d": 30,
    "all": None,
}

#: The most day-buckets a summary will return. A ledger a year old would
#: otherwise send 365 bars to a chart that is 300px wide, most of them empty.
MAX_BUCKETS = 60


def fingerprint(provider: str, api_key: str) -> str:
    """A stable name for a key, derived from it rather than being it.

    The ledger is plaintext and outlives any one session, so the one thing it
    must never contain is the key. A digest answers every question the dashboard
    asks -- *is this the same key as yesterday* -- without being usable as a
    credential, and without the trailing characters a last-four label would
    leave lying in the file.

    The provider is mixed in so that one key used on two providers is two
    entries: the same secret against a different endpoint is a different thing
    being metered.
    """
    if not api_key:
        return ""
    seed = f"{provider}\x00{api_key}".encode("utf-8")
    return hashlib.sha256(seed).hexdigest()[:8]


def _midnight(moment: datetime) -> datetime:
    return moment.replace(hour=0, minute=0, second=0, microsecond=0)


def window_start(window: str, now: float | None = None) -> float | None:
    """The earliest timestamp ``window`` includes, or None for "all".

    Arithmetic on local calendar days, not on 86400-second blocks, so that a
    window that spans a daylight-saving change still starts at midnight.
    """
    now = time.time() if now is None else now
    days = WINDOWS.get(window, 7)
    if days is None:
        return None
    start = _midnight(datetime.fromtimestamp(now)) - timedelta(days=days - 1)
    return start.timestamp()


@dataclass
class UsageRecord:
    """One API request."""

    ts: float
    provider: str
    key_id: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    ok: bool = True
    duration_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        # Short keys on purpose: this is one line per request, forever, and the
        # names would be most of the file.
        return {
            "ts": round(self.ts, 3),
            "provider": self.provider,
            "key_id": self.key_id,
            "model": self.model,
            "in": self.input_tokens,
            "out": self.output_tokens,
            "reasoning": self.reasoning_tokens,
            "ok": self.ok,
            "ms": self.duration_ms,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "UsageRecord":
        return cls(
            ts=float(data.get("ts") or 0.0),
            provider=str(data.get("provider") or ""),
            key_id=str(data.get("key_id") or ""),
            model=str(data.get("model") or ""),
            input_tokens=int(data.get("in") or 0),
            output_tokens=int(data.get("out") or 0),
            reasoning_tokens=int(data.get("reasoning") or 0),
            ok=bool(data.get("ok", True)),
            duration_ms=int(data.get("ms") or 0),
        )

    @property
    def total_tokens(self) -> int:
        """Input plus output. Reasoning is *inside* output, never added to it.

        Providers bill reasoning as completion tokens, which is why the split
        lives under `completion_tokens_details` -- so adding it again here would
        count the thinking twice.
        """
        return self.input_tokens + self.output_tokens


class UsageLedger:
    """The ledger file, and the reads the dashboard makes of it."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def record(self, record: UsageRecord) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            # One short append per request. There is one writer -- the core
            # serving one window -- so this needs no read-modify-write, and a
            # dashboard read that races an append sees a whole file or a file
            # with one line fewer.
            #
            # The one byte that is read first is what keeps a tear to a single
            # line. A hard exit can leave a half-written record with no newline
            # after it, and appending straight onto that glues the *next*
            # request onto the broken one -- so one damaged line silently eats
            # the one behind it too. Measured: a torn line plus a following
            # record read back as zero of the two.
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(self._separator() + json.dumps(record.to_dict(), separators=(",", ":")) + "\n")
        except OSError as exc:
            logger.warning(f"Could not write the usage ledger: {exc}")

    def _separator(self) -> str:
        """A newline unless the file already ends in one, or is empty."""
        try:
            if not self.path.exists() or self.path.stat().st_size == 0:
                return ""
            with self.path.open("rb") as handle:
                handle.seek(-1, os.SEEK_END)
                return "" if handle.read(1) == b"\n" else "\n"
        except OSError:
            # Unreadable is not a reason to refuse to write; a separator that
            # was not needed costs an empty line, which `read` skips.
            return ""

    def read(self) -> Iterator[UsageRecord]:
        """Every readable record, oldest first."""
        if not self.path.exists():
            return
        try:
            text = self.path.read_text(encoding="utf-8")
        except OSError as exc:
            logger.warning(f"Could not read the usage ledger: {exc}")
            return
        for line in text.splitlines():
            if not line.strip():
                continue
            try:
                yield UsageRecord.from_dict(json.loads(line))
            except (ValueError, TypeError):
                # A torn line -- a half-written last record after a hard exit --
                # must cost that one line, not the history behind it.
                continue

    def summary(self, window: str = "7d", now: float | None = None) -> dict[str, Any]:
        """Everything the dashboard draws for one window, in one reply.

        One method rather than five, because the five answers are all derived
        from the same pass over the same records and are always wanted together.
        """
        now = time.time() if now is None else now
        since = window_start(window, now)
        everything = list(self.read())
        records = [r for r in everything if since is None or r.ts >= since]

        totals = {
            "requests": len(records),
            "failed": sum(0 if r.ok else 1 for r in records),
            "input_tokens": sum(r.input_tokens for r in records),
            "output_tokens": sum(r.output_tokens for r in records),
            "reasoning_tokens": sum(r.reasoning_tokens for r in records),
            "total_tokens": sum(r.total_tokens for r in records),
            "duration_ms": sum(r.duration_ms for r in records),
        }

        return {
            "window": window,
            "since": since,
            "totals": totals,
            "buckets": self._buckets(records, since, now),
            "by_key": self._group(records, lambda r: (r.provider, r.key_id)),
            "by_provider": self._group(records, lambda r: (r.provider, "")),
            "by_model": self._group(records, lambda r: (r.provider, r.model)),
            "tracking_since": min((r.ts for r in everything), default=None),
        }

    def _buckets(self, records: list[UsageRecord], since: float | None, now: float) -> list[dict]:
        """One entry per calendar day in the window, empty days included.

        Empty days are the point: a bar chart that skips them draws Tuesday
        beside Thursday and reads as a continuous week.
        """
        today = _midnight(datetime.fromtimestamp(now))
        if since is None:
            first = min((r.ts for r in records), default=now)
            start = _midnight(datetime.fromtimestamp(first))
            if (today - start).days + 1 > MAX_BUCKETS:
                start = today - timedelta(days=MAX_BUCKETS - 1)
        else:
            start = _midnight(datetime.fromtimestamp(since))

        days: list[dict] = []
        cursor = start
        while cursor <= today:
            days.append(
                {
                    "day": cursor.strftime("%Y-%m-%d"),
                    "requests": 0,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "total_tokens": 0,
                }
            )
            cursor += timedelta(days=1)

        by_day = {d["day"]: d for d in days}
        for record in records:
            key = datetime.fromtimestamp(record.ts).strftime("%Y-%m-%d")
            bucket = by_day.get(key)
            if bucket is None:
                continue
            bucket["requests"] += 1
            bucket["input_tokens"] += record.input_tokens
            bucket["output_tokens"] += record.output_tokens
            bucket["total_tokens"] += record.total_tokens
        return days

    @staticmethod
    def _group(records: list[UsageRecord], key) -> list[dict]:
        """Requests and tokens per distinct `key`, busiest first."""
        grouped: dict[tuple, dict] = {}
        for record in records:
            name, detail = key(record)
            entry = grouped.get((name, detail))
            if entry is None:
                entry = grouped[(name, detail)] = {
                    "provider": name,
                    "detail": detail,
                    "requests": 0,
                    "failed": 0,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "total_tokens": 0,
                    "last_ts": 0.0,
                }
            entry["requests"] += 1
            entry["failed"] += 0 if record.ok else 1
            entry["input_tokens"] += record.input_tokens
            entry["output_tokens"] += record.output_tokens
            entry["total_tokens"] += record.total_tokens
            entry["last_ts"] = max(entry["last_ts"], record.ts)
        # Busiest first, then by name so equal counts do not reorder between
        # two reads of the same file.
        return sorted(grouped.values(), key=lambda e: (-e["requests"], e["provider"], e["detail"]))

    def clear(self) -> None:
        """Forget everything. Not reachable from the window; for tests."""
        try:
            self.path.unlink(missing_ok=True)
        except OSError as exc:
            logger.warning(f"Could not clear the usage ledger: {exc}")


_LEDGER: UsageLedger | None = None


def ledger() -> UsageLedger:
    """The window's ledger, built on first use.

    Lazy rather than at import, because the path resolves through a config
    directory that `settings` creates on demand -- importing this module should
    not touch the filesystem.
    """
    global _LEDGER
    if _LEDGER is None:
        _LEDGER = UsageLedger(settings.get_config_dir() / "usage.jsonl")
    return _LEDGER


def current_context(model: str = "") -> dict[str, Any]:
    """How full the conversation is right now, as the core can honestly say.

    **The numerator is the last request's `input_tokens`,** which is a real
    measurement rather than an estimate: every turn resends the whole
    transcript, so the input side of the most recent request *is* the context
    as the provider saw it. Nothing here counts characters or guesses at a
    tokenizer, because both would be a different number from the one the
    provider will actually bill and truncate on.

    **Only the most recent request counts,** and only for this model. Summing
    the window would be spend, not context, and the two differ by orders of
    magnitude -- which is exactly the confusion a "context" label invites, so
    this returns a plain dict with named fields rather than a percentage that
    would have to be taken on trust.

    `input_tokens` is 0 when the provider reported no usage for the last
    request. That is reported as ``used: 0`` with ``known: False`` rather than
    as a guess, because a bar showing 0% for a long conversation is worse than
    no bar: it is confidently wrong.
    """
    if not model:
        return {"model": "", "used": 0, "known": False}

    latest: UsageRecord | None = None
    try:
        for record in ledger().read():
            if record.model == model and record.input_tokens > 0:
                latest = record
    except Exception as exc:  # noqa: BLE001 - a missing meter is not a failure
        logger.warning(f"Could not read the usage ledger for context: {exc}")
        return {"model": model, "used": 0, "known": False}

    if latest is None:
        return {"model": model, "used": 0, "known": False}
    return {"model": model, "used": latest.input_tokens, "known": True}


def record_request(
    *,
    provider: str,
    key_id: str,
    model: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
    reasoning_tokens: int = 0,
    ok: bool = True,
    duration_ms: int = 0,
) -> None:
    """Note one API request. Never raises.

    Called from inside the request path, so it is deliberately incapable of
    failing a request: a ledger problem is a missing bar on a chart, and that is
    not worth an error where the user expected an answer.
    """
    try:
        ledger().record(
            UsageRecord(
                ts=time.time(),
                provider=provider,
                key_id=key_id,
                model=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                reasoning_tokens=reasoning_tokens,
                ok=ok,
                duration_ms=duration_ms,
            )
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"Could not record API usage: {exc}")
