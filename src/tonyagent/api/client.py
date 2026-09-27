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

from tonyagent.api.dialects import Chunk, Completion, Dialect, get_dialect
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
        dialect: Dialect | None = None,
        timeout: float = 60.0,
        extra_headers: dict[str, str] | None = None,
        key_prefix: str | None = None,
        key_length: int | None = None,
    ):
        self.provider = provider
        self.api_key = normalize_key(api_key)
        self.model = model
        self.dialect = dialect or get_dialect(provider)
        self.base_url = (base_url or self.dialect.default_base_url).rstrip("/")
        self.timeout = timeout
        self.extra_headers = extra_headers or {}
        # Providers differ even inside one dialect (openai=sk-, groq=gsk_,
        # openrouter=sk-or-), so the prefix belongs to the provider, not the dialect.
        self.key_prefix = key_prefix if key_prefix is not None else self.dialect.key_prefix
        # Exact expected length, when the provider knows it. A key of the right
        # shape but the wrong length is a truncated paste, and the provider will
        # report it as an opaque 401 unless we catch it here.
        self.key_length = key_length

    # -- helpers -------------------------------------------------------------
    def _headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
            **self.dialect.auth_headers(self.api_key),
            **self.extra_headers,
        }

    def _url(self, stream: bool) -> str:
        url = self.dialect.url(self.base_url, self.model, stream)
        params: list[str] = []
        if stream and self.dialect.stream_param():
            params.append(self.dialect.stream_param())
        if hasattr(self.dialect, "key_query"):
            params.append(self.dialect.key_query(self.api_key))
        return f"{url}?{'&'.join(params)}" if params else url

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
        if prefix and not self.api_key.startswith(prefix):
            raise LLMError(
                ErrorKind.AUTH,
                f"The {self.provider} key does not start with '{prefix}'.",
                provider=self.provider,
                hint="Copy the key again from the provider's dashboard.",
            )
        if len(self.api_key) < MIN_KEY_LENGTH:
            raise KeyFormatError(self.provider, len(self.api_key), prefix or "<any>")
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
        url = self.dialect.models_url(self.base_url)
        headers = self._headers()
        headers.pop("Accept", None)
        try:
            async with httpx.AsyncClient(timeout=min(self.timeout, 30.0)) as http:
                if hasattr(self.dialect, "key_query"):
                    url = f"{url}?{self.dialect.key_query(self.api_key)}"
                resp = await http.get(url, headers=headers)
        except httpx.HTTPError as exc:
            raise LLMError.network(exc, self.provider) from exc
        # A gateway may not expose a model list even with a valid key.
        if resp.status_code in (401, 403):
            raise LLMError.from_response(resp.status_code, resp.text, self.provider)
        if resp.status_code >= 400:
            return []
        try:
            return self.dialect.parse_models(resp.json())
        except ValueError:
            return []
