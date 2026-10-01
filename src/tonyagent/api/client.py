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

from dataclasses import dataclass
from typing import Any, AsyncIterator

import httpx

from tonyagent.api.dialects import Chunk, Completion, Dialect, ReasoningSpec
from tonyagent.api.errors import ErrorKind, KeyFormatError, KeyLengthError, LLMError

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
    ):
        self.provider = provider
        self.api_key = normalize_key(api_key)
        self.model = model
        self.dialect = Dialect()
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
        # The gateway's model list, fetched at most once per client. OpenRouter
        # answers it with several hundred entries, and a model picker that
        # opened its menu on every click would otherwise spend a request per
        # click to learn the same thing. Cached per client rather than
        # globally so a rebind, or a second base_url, reads its own list.
        self._model_entries_cache: dict[str, dict] | None = None

    # -- helpers -------------------------------------------------------------
    def _headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
            **self.dialect.auth_headers(self.api_key),
            **self.extra_headers,
        }

    def _url(self, stream: bool) -> str:
        return self.dialect.url(self.base_url, self.model, stream)

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

    # -- requests ------------------------------------------------------------
    async def complete(self, messages, tools=None, tool_choice=None, **extra) -> Completion:
        self.check_key()
        payload = self.dialect.build_request(
            self.model, messages, tools, tool_choice, stream=False, **extra
        )
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as http:
                resp = await http.post(self._url(False), headers=self._headers(), json=payload)
        except httpx.HTTPError as exc:
            raise LLMError.network(exc, self.provider) from exc
        if resp.status_code >= 400:
            raise LLMError.from_response(resp.status_code, resp.text, self.provider)
        return self.dialect.parse_completion(resp.json())

    async def stream(self, messages, tools=None, tool_choice=None, **extra) -> AsyncIterator[Chunk]:
        """Yield chunks as they arrive. Always raises LLMError on failure."""
        self.check_key()
        payload = self.dialect.build_request(
            self.model, messages, tools, tool_choice, stream=True, **extra
        )
        acc: dict = {}
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as http:
                async with http.stream(
                    "POST", self._url(True), headers=self._headers(), json=payload
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
                        chunk = self.dialect.parse_stream_event(event, data, acc)
                        if chunk is not None:
                            yield chunk
                            if chunk.finish_reason:
                                break
                        event = ""
        except httpx.HTTPError as exc:
            raise LLMError.network(exc, self.provider) from exc

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
