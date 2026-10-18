"""HTTP transport for the LLM API layer.

One client, no vendor SDKs. Everything provider-specific lives in a
:class:`~tonyagent.api.dialects.Dialect`, so a new gateway is a config entry
rather than a new class with a copy-pasted streaming loop.

The client also owns the two checks the old layer never had:

* :meth:`check_key` - rejects an obviously-truncated key locally, before
  spending a request and confusing the user with a bare 401.
* :meth:`check` - a real network round-trip, so the UI can say "connected" only
  when the provider has actually accepted the key. The old
  ``validate_credentials()`` only did a ``str.startswith()`` test, which is why
  the status bar said "Connected" while every request returned 401.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, AsyncIterator

import httpx

from tonyagent import __version__ as VERSION
from tonyagent.api.dialects import (
    Chunk,
    Completion,
    Dialect,
    ReasoningSpec,
    ResponsesDialect,
    Usage,
)
from tonyagent.api.errors import ErrorKind, KeyFormatError, KeyLengthError, LLMError

#: **Who is asking.** Some gateways refuse traffic that arrives as a generic SDK or
#: HTTP-library user agent. OpenCode Go says so explicitly -- a client should
#: "identify itself with its own user agent, such as ``my-coding-agent/1.0``, rather
#: than a generic SDK or HTTP-library name" -- and an unattributable request is one
#: they cannot tell apart from a scraper, which is a thing they are entitled to
#: refuse. Sent on every request, to every provider, because there is no gateway that
#: is helped by being lied to about this.
USER_AGENT = f"TONYAgent/{VERSION}"

# Fallback length floor for providers that do not declare an exact length.
# This is deliberately low: it is a last-resort sanity check, not the real
# defence. The real defence is ``key_length`` on each provider.
#
# Why this matters: a 20-char floor happily accepted a 35-character OpenRouter
# key, so the app spent a request and showed a bare "401 User not found" for a
# key that was never complete. A truncated key must be caught locally.
MIN_KEY_LENGTH = 20


def normalize_key(raw: str | None) -> str:
    """Strip the things a copy/paste leaves behind.

    A trailing newline, a stray leading/trailing space, or a key that arrived
    still wrapped in quotes all pass the prefix check and all get rejected by
    the provider. Normalising here means the stored key and the sent key are
    the same value, and the local checks see what the server will see.
    """
    if not raw:
        return ""
    key = raw.strip()
    # Some dashboards hand back keys wrapped in quotes; unwrap once.
    if len(key) >= 2 and key[0] == key[-1] and key[0] in ("'", '"'):
        key = key[1:-1].strip()
    return key


def _as_int(value: Any) -> int:
    """An integer, or 0 when the field is absent or unparseable.

    Gateways are inconsistent about types -- `context_length` arrives as a
    number from OpenRouter and as a string from some others -- so this accepts
    both. 0 means "not stated", which the frontend is expected to render as no
    label rather than as a number.
    """
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return max(0, value)
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return 0


def _read_pricing(raw: Any) -> dict[str, float]:
    """The input and output prices, in dollars per million tokens.

    **Per-token to per-million is the only arithmetic here**, and it is the
    multiplication by a million that providers quote in already -- OpenRouter
    publishes `"0.000003"` and everyone reads it as $3/M.

    Both sides are returned, and a missing side is 0 rather than an error: a
    free tier publishes zeros for both, and some gateways omit `completion`.
    The distinction the frontend has to keep is between *zero* (it is free) and
    *absent* (nobody said), so an entry with no `pricing` block at all comes
    back empty rather than as two zeros.
    """
    if not isinstance(raw, dict) or not raw:
        return {}
    out: dict[str, float] = {}
    for key, field in (("prompt", "input"), ("completion", "output")):
        value = raw.get(key)
        if isinstance(value, bool) or value is None:
            continue
        try:
            price = float(value)
        except (TypeError, ValueError):
            continue
        if price < 0:
            continue
        out[field] = round(price * 1_000_000, 6)
    return out


def _is_protocol_mismatch(exc: LLMError) -> bool:
    """Whether ``exc`` is a gateway refusing the wire format, not the content.

    Go answers a Responses-only model sent to ``/chat/completions`` (and vice
    versa) with 400 "Model does not support this protocol". That is a routing
    fact, so the client retries the same request through the other dialect
    once instead of showing it. Any other 400 is a real bad request and is
    raised as-is.
    """
    return (
        exc.status == 400
        and bool(exc.body)
        and "does not support this protocol" in exc.body.lower()
    )


#: Models known from Go's endpoint table to serve ``/responses`` rather than
#: ``/chat/completions``. Matched by prefix so future siblings (``muse-spark-1.4``)
#: route correctly without a code change; anything unlisted still works, it just
#: spends one failed chat request before the fallback catches it.
RESPONSES_DIRECT_PREFIXES = ("muse-spark-", "grok-4.7", "grok-4.6", "gpt-6-luna", "gpt-5.6-luna")


@dataclass
class Health:
    """Result of a real connectivity check."""

    ok: bool
    message: str
    kind: ErrorKind | None = None
    models: list[str] | None = None


class LLMClient:
    """Stateless HTTP client for one provider."""

    def __init__(
        self,
        provider: str,
        api_key: str,
        model: str,
        base_url: str,
        key_prefix: str,
        timeout: float = 60.0,
        extra_headers: dict[str, str] | None = None,
        key_length: int | None = None,
        user_agent: str = "",
        session_header: str = "",
        session_id: str = "",
    ):
        self.provider = provider
        self.api_key = normalize_key(api_key)
        self.model = model
        self.dialect = Dialect()
        self.responses_dialect = ResponsesDialect()
        self.base_url = (base_url or self.dialect.default_base_url).rstrip("/")
        self.timeout = timeout
        self.extra_headers = extra_headers or {}
        # The key prefix is a property of the account, not of the wire format,
        # so it arrives from the provider rather than from the dialect.
        self.key_prefix = key_prefix
        # Exact expected length, when the provider knows it. A key of the right
        # shape but the wrong length is a truncated paste, and the provider will
        # report it as an opaque 401 unless we catch it here.
        self.key_length = key_length
        # **Who is asking, by name.** Some gateways refuse traffic from a generic
        # SDK or HTTP-library user agent -- OpenCode Go says so in as many words
        # ("identify itself with its own user agent") -- and a request that cannot
        # be attributed is one they cannot tell from a scraper.
        self.user_agent = user_agent or USER_AGENT
        # **Which conversation this is.** A gateway that routes and caches per
        # session asks for a stable id per conversation; the header's *name* is the
        # gateway's business, so it arrives from the provider and nothing is sent
        # when the provider did not ask. `session_id` is an attribute rather than a
        # constructor argument only because the useful value -- the conversation --
        # is known after the provider is built; see `set_session`.
        self.session_header = session_header
        self.session_id = session_id
        # The gateway's model list, fetched at most once per client. OpenRouter
        # answers it with several hundred entries, and a model picker that
        # opened its menu on every click would otherwise spend a request per
        # click to learn the same thing. Cached per client rather than
        # globally so a rebind, or a second base_url, reads its own list.
        self._model_entries_cache: dict[str, dict] | None = None

    # -- helpers -------------------------------------------------------------
    def set_session(self, session_id: str) -> None:
        """Point this client at a conversation, for gateways that route per session.

        Called when the conversation changes rather than when the provider is built,
        because the provider outlives any one conversation: the app re-binds a
        provider when the *settings* change, and switches conversations far more
        often than that.
        """
        self.session_id = session_id or ""

    def _headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
            # Named, not a library default: see `user_agent` above.
            "User-Agent": self.user_agent,
            **self.dialect.auth_headers(self.api_key),
            **self.extra_headers,
        }
        if self.session_header and self.session_id:
            # An explicitly configured header wins: `extra_headers` is a settings
            # field, and someone who set this one by hand meant it.
            configured = {name.lower() for name in headers}
            if self.session_header.lower() not in configured:
                headers[self.session_header] = self.session_id
        return headers

    def _url(self, stream: bool, dialect=None) -> str:
        return (dialect or self.dialect).url(self.base_url, self.model, stream)

    def _dialect_order(self):
        """Chat first, unless the model is a known Responses-only id.

        Unknown models still work: the first attempt fails with the gateway's
        protocol message and the client retries through the other dialect once.
        """
        model = (self.model or "").lower()
        if model.startswith(RESPONSES_DIRECT_PREFIXES):
            return (self.responses_dialect, self.dialect)
        return (self.dialect, self.responses_dialect)

    def check_key(self) -> None:
        """Fail fast on a missing or clearly truncated key."""
        if not self.api_key:
            raise LLMError(
                ErrorKind.CONFIG,
                f"No API key stored for {self.provider}.",
                provider=self.provider,
                hint="Open the API Provider panel, paste the key, and press Save to Keyring.",
            )
        prefix = self.key_prefix
        if not self.api_key.startswith(prefix):
            raise LLMError(
                ErrorKind.AUTH,
                f"The {self.provider} key does not start with '{prefix}'.",
                provider=self.provider,
                hint="Copy the key again from the provider's dashboard.",
            )
        if len(self.api_key) < MIN_KEY_LENGTH:
            raise KeyFormatError(self.provider, len(self.api_key), prefix)
        # Exact-length check. This is the check that would have caught the
        # 35-character OpenRouter key: right prefix, plausible length, but the
        # body was 28 hex chars where 64 are required. Without it the user only
        # ever saw the provider's "401 User not found".
        if self.key_length and len(self.api_key) != self.key_length:
            raise KeyLengthError(self.provider, len(self.api_key), self.key_length)

    def _record(self, *, ok: bool, started: float, usage: Usage | None = None) -> None:
        """Note this request in the usage ledger.

        Called on every path out of `complete` and `stream`, including the
        failing ones: a request that was refused still happened, and a dashboard
        that only counted the ones that worked would answer "how much have I
        used" with a number that only ever went up.
        """
        # Imported at the point of use, not at module scope. `config` imports
        # this module for `normalize_key`, so a module-level import of anything
        # that reaches `settings` closes the loop and breaks the import graph --
        # measured, not theorised: it was a circular-import error the moment this
        # went in at the top. The cost is one dict lookup per request.
        from tonyagent.core.usage import fingerprint, record_request

        record_request(
            provider=self.provider,
            key_id=fingerprint(self.provider, self.api_key),
            model=self.model,
            input_tokens=usage.input_tokens if usage else 0,
            output_tokens=usage.output_tokens if usage else 0,
            reasoning_tokens=usage.reasoning_tokens if usage else 0,
            ok=ok,
            duration_ms=int((time.monotonic() - started) * 1000),
        )

    # -- requests ------------------------------------------------------------
    async def complete(self, messages, tools=None, tool_choice=None, **extra) -> Completion:
        self.check_key()
        last_mismatch: LLMError | None = None
        for dialect in self._dialect_order():
            payload = dialect.build_request(
                self.model, messages, tools, tool_choice, stream=False, **extra
            )
            started = time.monotonic()
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as http:
                    resp = await http.post(
                        self._url(False, dialect), headers=self._headers(), json=payload
                    )
            except httpx.HTTPError as exc:
                self._record(ok=False, started=started)
                raise LLMError.network(exc, self.provider) from exc
            if resp.status_code >= 400:
                self._record(ok=False, started=started)
                exc = LLMError.from_response(resp.status_code, resp.text, self.provider)
                if _is_protocol_mismatch(exc):
                    last_mismatch = exc
                    continue
                raise exc
            result = dialect.parse_completion(resp.json())
            self._record(ok=True, started=started, usage=result.usage)
            return result
        assert last_mismatch is not None
        raise last_mismatch

    async def _stream_with(self, dialect, payload) -> AsyncIterator[Chunk]:
        """Yield chunks for one dialect. Raises LLMError on HTTP failure."""
        started = time.monotonic()
        ok = False
        acc: dict = {}
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as http:
                async with http.stream(
                    "POST", self._url(True, dialect), headers=self._headers(), json=payload
                ) as resp:
                    if resp.status_code >= 400:
                        body = (await resp.aread()).decode("utf-8", "replace")
                        raise LLMError.from_response(resp.status_code, body, self.provider)
                    event = ""
                    async for line in resp.aiter_lines():
                        if line.startswith("event:"):
                            event = line[6:].strip()
                            continue
                        if not line.startswith("data:"):
                            continue
                        data = line[5:].strip()
                        if data == "[DONE]":
                            break
                        chunk = dialect.parse_stream_event(event, data, acc)
                        if chunk is not None:
                            yield chunk
                            if chunk.finish_reason:
                                break
                        event = ""
            ok = True
        except httpx.HTTPError as exc:
            raise LLMError.network(exc, self.provider) from exc
        finally:
            # `finally` rather than the success path. A stream abandoned part
            # way -- the user pressed Stop, the turn was cancelled -- still
            # spent a request, and it is the case a ledger that only counted
            # clean finishes would miss by the most.
            self._record(ok=ok, started=started, usage=acc.get("usage"))

    async def stream(self, messages, tools=None, tool_choice=None, **extra) -> AsyncIterator[Chunk]:
        """Yield chunks as they arrive. Always raises LLMError on failure."""
        self.check_key()
        order = self._dialect_order()
        first_payloads = [
            dialect.build_request(
                self.model, messages, tools, tool_choice, stream=True, **extra
            )
            for dialect in order
        ]
        try:
            async for chunk in self._stream_with(order[0], first_payloads[0]):
                yield chunk
            return
        except LLMError as exc:
            if not _is_protocol_mismatch(exc) or len(order) < 2:
                raise
            async for chunk in self._stream_with(order[1], first_payloads[1]):
                yield chunk
            return

    # -- health --------------------------------------------------------------
    async def check(self) -> Health:
        """A real round-trip. Never a local string test."""
        try:
            self.check_key()
        except LLMError as exc:
            return Health(False, exc.user_message(), exc.kind)
        try:
            models = await self.list_models()
        except LLMError as exc:
            return Health(False, exc.user_message(), exc.kind)
        return Health(
            True,
            f"Connected to {self.provider} ({len(models)} models available).",
            models=models,
        )

    async def list_models(self) -> list[str]:
        """Fetch the live model list. Also serves as an auth probe."""
        return [model_id for model_id, _ in (await self._model_entries()).items()]

    async def model_catalog(self) -> list[dict]:
        """Every model with the numbers a picker wants beside its name.

        **A separate method rather than extra fields on `list_models`**, which
        is the window's contract: it iterates that result expecting ids, and
        widening the reply would oblige every reader to know about fields it
        does not use. `plan.get` records the same reasoning for `state`.

        **Nothing here is derived from the id and nothing is guessed.** The
        context length is the provider's own `context_length` and the prices are
        its own `pricing` block, converted from per-token to per-million because
        that is the unit providers quote and the unit a person compares. A
        model whose entry carries neither is reported with zeros and empty
        prices, and the frontend draws no label for it -- which is *not* the
        same as drawing "Free", because a gateway that omits pricing is not
        telling you the model costs nothing.

        OpenCode Go publishes bare ids, so its rows are enriched from the
        curated facts in `providers/go_catalog.py` (display name, protocol,
        context window, max output tokens, input modalities). The live reply
        still decides which ids exist: a model with no facts keeps zeros and
        empty lists rather than inheriting a neighbour's numbers.
        """
        # Local import: `providers` reaches back into this module for
        # `normalize_key`, so a top-level import closes the loop. The catalog
        # itself imports nothing, which is what keeps this one-directional.
        from tonyagent.providers.go_catalog import GO_MODEL_FACTS

        catalog: list[dict] = []
        for model_id, entry in (await self._model_entries()).items():
            facts = GO_MODEL_FACTS.get(model_id) if self.provider == "opencode-go" else None
            window = _as_int(
                entry.get("context_length")
                or entry.get("context_window")
                or entry.get("max_context_tokens")
            )
            catalog.append(
                {
                    "id": model_id,
                    "name": str(entry.get("name") or (facts or {}).get("name") or ""),
                    "context_length": window or int((facts or {}).get("context_window") or 0),
                    "pricing": _read_pricing(entry.get("pricing")),
                    "max_tokens": int((facts or {}).get("max_tokens") or 0),
                    "input_modalities": list((facts or {}).get("input_modalities") or []),
                    "protocol": str((facts or {}).get("protocol") or ""),
                    "supports_reasoning": bool((facts or {}).get("supports_reasoning", False)),
                }
            )
        catalog.sort(key=lambda model: str(model["id"]))
        return catalog

    async def model_context_window(self) -> int:
        """The bound model's context window, or 0 when the provider is silent.

        Read out of the ``/models`` entry that `_model_entries` already
        fetched and cached, so this costs no request. OpenRouter reports
        `context_length` on every model; before this existed the field arrived
        in the response and was discarded, which left "how full is the context"
        unanswerable even though the answer was sitting in the one response the
        model picker already makes.

        **0 means unknown, not zero.** A provider that omits the field, or a
        dialect that names it differently, gives 0 here, and a caller that drew
        a 0% bar from it would be confidently wrong. The window is a property of
        the model rather than of the conversation, so it is cached separately
        from the context size and does not change between turns.
        """
        model = self.model
        if not model:
            return 0
        entries = await self._model_entries()
        entry = entries.get(model)
        if entry is None:
            return 0
        for key in ("context_length", "context_window", "max_context_tokens"):
            value = entry.get(key)
            if isinstance(value, int) and value > 0:
                return value
            # Some gateways report it as a string.
            if isinstance(value, str) and value.isdigit():
                return int(value)
        # Go publishes no sizes on the wire; the curated facts are the only
        # source, and 0 stays the answer when they have none either.
        if self.provider == "opencode-go":
            from tonyagent.providers.go_catalog import GO_MODEL_FACTS

            facts = GO_MODEL_FACTS.get(model)
            if facts and int(facts.get("context_window") or 0) > 0:
                return int(facts["context_window"])
        return 0

    async def list_model_reasoning(self) -> dict[str, ReasoningSpec]:
        """What each listed model reports about its own thinking."""
        specs: dict[str, ReasoningSpec] = {}
        for model_id, entry in (await self._model_entries()).items():
            parsed = self.dialect.parse_model_reasoning({"data": [entry]})
            if model_id in parsed:
                specs[model_id] = parsed[model_id]
        return specs

    async def _model_entries(self) -> dict[str, dict]:
        """The raw ``/models`` entries, keyed by id.

        The reasoning metadata and the id list come from the same response, so
        asking for both is one request rather than two, and a model that
        appears in one cannot be missing from the other.

        Cached per client. OpenRouter answers this with several hundred
        entries, so a menu that opened the list on every click would spend a
        request per click to learn the same thing -- and the ids and the
        reasoning metadata would come from two different responses that are
        not guaranteed to agree, which is the failure this method existed to
        prevent.
        """
        if self._model_entries_cache is not None:
            return self._model_entries_cache
        entries = await self._fetch_model_entries()
        self._model_entries_cache = entries
        return entries

    async def _fetch_model_entries(self) -> dict[str, dict]:
        """One request to the gateway's model list."""
        # **Before the headers are built.** `auth_headers` spells the key into
        # `Authorization: Bearer <key>`, so with no key it produces `Bearer ` --
        # and `httpx` refuses that with "Illegal header value b'Bearer '", which
        # says nothing about the key being the problem. `check_key` answers
        # "No API key stored for <provider>" with the hint that fixes it, and it
        # is the same guard `complete` and `stream` already take before they
        # touch the network. This path was the one that went without.
        self.check_key()
        url = self.dialect.models_url(self.base_url)
        headers = self._headers()
        headers.pop("Accept", None)
        try:
            async with httpx.AsyncClient(timeout=min(self.timeout, 30.0)) as http:
                resp = await http.get(url, headers=headers)
        except httpx.HTTPError as exc:
            raise LLMError.network(exc, self.provider) from exc
        # A gateway may not expose a model list even with a valid key.
        if resp.status_code in (401, 403):
            raise LLMError.from_response(resp.status_code, resp.text, self.provider)
        if resp.status_code >= 400:
            return {}
        try:
            data = (resp.json() or {}).get("data") or []
        except ValueError:
            return {}
        return {m["id"]: m for m in data if isinstance(m, dict) and m.get("id")}
