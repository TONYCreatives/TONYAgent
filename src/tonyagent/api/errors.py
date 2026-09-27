"""Structured errors for the LLM API layer.

Every failure surfaces as a :class:`LLMError` with a machine-readable ``kind``
and a message written for the person using the app. The old provider layer
raised bare SDK exceptions whose ``str()`` was either empty or an opaque
one-liner, which is why the UI could only ever show "Error: ".
"""

from __future__ import annotations

from enum import Enum


class ErrorKind(str, Enum):
    AUTH = "auth"
    RATE_LIMIT = "rate_limit"
    BAD_REQUEST = "bad_request"
    NOT_FOUND = "not_found"
    SERVER = "server"
    NETWORK = "network"
    CONFIG = "config"


class LLMError(Exception):
    """An API failure with enough context to tell the user what to do."""

    def __init__(
        self,
        kind: ErrorKind,
        message: str,
        *,
        status: int | None = None,
        body: str | None = None,
        provider: str = "",
        hint: str = "",
    ):
        super().__init__(message)
        self.kind = kind
        self.message = message
        self.status = status
        self.body = body
        self.provider = provider
        self.hint = hint

    @classmethod
    def from_response(cls, status: int, body: str, provider: str = "") -> "LLMError":
        """Classify an HTTP failure and pull the provider's own message out."""
        detail = _extract_message(body)
        if status in (401, 403):
            kind = ErrorKind.AUTH
            hint = (
                "The key was rejected. Copy the FULL key again - a truncated key "
                "looks valid locally but the provider has never seen it."
            )
        elif status == 429:
            kind = ErrorKind.RATE_LIMIT
            hint = "Rate limited or out of credit. Wait a moment, or check billing."
        elif status == 404:
            kind = ErrorKind.NOT_FOUND
            hint = "Unknown model or endpoint. Check the model name."
        elif status >= 500:
            kind = ErrorKind.SERVER
            hint = f"The provider returned {status}. This is their side, retry later."
        else:
            kind = ErrorKind.BAD_REQUEST
            hint = (
                "The request was rejected. If it mentions tools or function "
                "calling, this model does not support it."
            )
        return cls(
            kind,
            detail or f"HTTP {status}",
            status=status,
            body=body[:2000] if body else None,
            provider=provider,
            hint=hint,
        )

    @classmethod
    def network(cls, exc: Exception, provider: str = "") -> "LLMError":
        return cls(
            ErrorKind.NETWORK,
            f"Could not reach the provider: {exc}",
            provider=provider,
            hint="Check your internet connection, VPN, or firewall.",
        )

    def user_message(self) -> str:
        """A short, actionable message for the UI (no raw body dump)."""
        parts = [self.message]
        if self.hint:
            parts.append(self.hint)
        return "\n\n".join(parts)


def _extract_message(body: str) -> str:
    """Pull a human message out of whatever the provider returned."""
    import json

    if not body:
        return ""
    try:
        data = json.loads(body)
    except (ValueError, TypeError):
        return body.strip()[:300]
    if isinstance(data, dict):
        err = data.get("error")
        if isinstance(err, dict):
            for key in ("message", "detail", "type"):
                if err.get(key):
                    return str(err[key])[:300]
        if isinstance(err, str):
            return err[:300]
        for key in ("message", "detail"):
            if data.get(key):
                return str(data[key])[:300]
    return body.strip()[:300]


class KeyLengthError(LLMError):
    """The key has the right prefix but the wrong length, so it is truncated.

    Separate from :class:`KeyFormatError` because the diagnosis is specific and
    the fix is specific: re-copy the whole key. This is the single most useful
    message the app can show, because the provider's own reply to a truncated
    key ("User not found") looks like a wrong account rather than a bad paste.
    """

    def __init__(self, provider: str, got_length: int, expected_length: int):
        self.got_length = got_length
        self.expected_length = expected_length
        missing = expected_length - got_length
        direction = "incomplete" if missing > 0 else "too long"
        super().__init__(
            ErrorKind.AUTH,
            f"The stored {provider} key is {got_length} characters; a real one is "
            f"{expected_length} ({direction}).",
            provider=provider,
            hint=(
                "This key was cut short when it was copied. Open the provider's "
                "API keys page, select the whole key, and copy it again - the "
                f"paste needs {missing} more character(s). Click 'Forget saved "
                "key' first so the truncated value cannot be reused."
            ),
        )


class KeyFormatError(LLMError):
    """The stored key cannot possibly be valid for this provider.

    Caught locally before spending a request: a truncated key is the single
    most common setup mistake and looks fine until the provider rejects it.
    """

    def __init__(self, provider: str, got_length: int, expected_prefix: str):
        super().__init__(
            ErrorKind.AUTH,
            f"The stored {provider} key is only {got_length} characters, which is "
            f"too short to be a real key.",
            provider=provider,
            hint=(
                f"It should start with '{expected_prefix}' and be considerably "
                f"longer. A key that was cut short when copied will be rejected - "
                f"re-copy the whole thing from the provider's dashboard."
            ),
        )
