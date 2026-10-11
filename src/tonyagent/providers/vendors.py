"""Vendors that speak the OpenAI chat-completions shape.

Each of these is a provider that needs a name, a base URL and a seed model list,
and nothing else: `OpenAICompatibleProvider` already carries the request, the
streaming parse and the credential check, and every vendor below answers the
same shape. A vendor that does *not* -- Anthropic, Google -- would need its own
dialect rather than a subclass here, which is why neither is in this file.

**No key format is asserted.** The OpenRouter provider checks an exact 73-character
length, because a truncated paste there is answered with an opaque "401 User not
found" and the length is known. None of these lengths are known here, and a guess
at a vendor's format that turns out wrong refuses a key that works -- strictly
worse than the 401 this defers to. `key_prefix = ""` is what says that: nothing
is refused locally, and the provider stays the authority on its own credentials.
"""

from __future__ import annotations

from tonyagent.providers.base import OpenAICompatibleProvider


class OpenAICompatibleVendor(OpenAICompatibleProvider):
    """One OpenAI-shaped vendor, minus everything the vendor does not decide."""

    #: The empty prefix: see the module docstring. A subclass overriding this
    #: is making a claim about its vendor that has to be checked against a real
    #: key first.
    key_prefix = ""

    #: Used when a caller asks for no particular model.
    default_model: str = ""

    def __init__(
        self,
        api_key: str = "",
        model: str = "",
        base_url: str = "",
        extra_headers: dict[str, str] | None = None,
        timeout: int = 60,
        max_retries: int = 3,
    ):
        # `self.base_url` is read before `__init__` overwrites it: the class
        # attribute is the vendor's endpoint, and the parameter is an override.
        super().__init__(
            api_key=api_key,
            model=model or self.default_model,
            base_url=base_url or self.base_url,
            extra_headers=extra_headers,
            timeout=timeout,
            max_retries=max_retries,
        )
