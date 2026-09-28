"""Provider factory for TONYAgent."""

from __future__ import annotations

import re
from typing import Optional

from loguru import logger

from tonyagent.providers.base import provider_registry, BaseLLMProvider
from tonyagent.config.settings import settings
from tonyagent.config.keyring import load_api_key


#: Real model ids are lowercase tokens like "gpt-4o", "claude-3-5-sonnet" or
#: "anthropic/claude-sonnet-4.6" - optionally namespaced with a "/" and allowing
#: dots, underscores, hyphens and colons. Anything outside that shape is not a
#: model id; it is a value that leaked in from somewhere else (most often an
#: unset Tk widget whose class name was stringified).
_MODEL_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")

#: A base URL must carry a scheme. httpx reports a scheme-less one as
#: "Request URL is missing an 'http://' or 'https://' protocol", which reads
#: like a network failure and is really a typo in one field.
_BASE_URL_SCHEME_RE = re.compile(r"^https?://", re.IGNORECASE)


def normalize_base_url(url: str) -> str:
    """Return a usable base URL, or raise ``ValueError`` for an unusable one.

    Empty is allowed (the caller falls back to the provider default). A
    non-empty value with no ``http://``/``https://`` scheme is not usable: the
    request goes out as ``host/v1/chat/completions`` and httpx fails with
    "Request URL is missing an 'http://' or 'https://' protocol". Rejecting
    here surfaces that at bind time, as an actionable message, instead of a
    mysterious network error on the first message. A trailing slash is removed
    so the provider does not build ``//chat/completions``.
    """
    candidate = (url or "").strip()
    if not candidate:
        return ""
    if not _BASE_URL_SCHEME_RE.match(candidate):
        raise ValueError(
            "Base URL must start with http:// or https:// "
            f"(got {candidate!r})"
        )
    return candidate.rstrip("/")


class ProviderFactory:
    @staticmethod
    def _is_valid_model_id(model: str) -> bool:
        """Reject strings that cannot be a real model id.

        Empty is allowed: the caller falls back to the provider default. This is
        the last line of defence behind the UI-level fix, so a bad value becomes
        a logged warning and a working default instead of a 400 from the API.
        """
        if not model:
            return True
        if not isinstance(model, str):
            return False
        candidate = model.strip()
        if not candidate:
            return True
        # A class name is CamelCase with no slash and usually no dot; real ids
        # always contain a separator or a lowercase token boundary.
        if candidate in {"CTkComboBox", "PillComboBox", "CTkOptionMenu"}:
            return False
        return bool(_MODEL_ID_RE.match(candidate))

    @staticmethod
    def create_provider(
        name: str,
        model: str = "",
        base_url: str = "",
        extra_headers: dict[str, str] | None = None,
        timeout: int = 60,
        max_retries: int = 3,
    ) -> Optional[BaseLLMProvider]:
        if name not in provider_registry.list_providers():
            return None

        # A model id is never a widget class name. Unset combo boxes report
        # their own class name, and passing that through produced requests
        # like "CTkComboBox is not a valid model ID". Reject anything that is
        # not a plausible model id and fall back to the provider default, so
        # a UI bug cannot become a confusing server error.
        if not ProviderFactory._is_valid_model_id(model):
            logger.warning(
                f"Ignoring implausible model id for {name!r}: {model!r}"
            )
            model = ""

        api_key = load_api_key(name)

        # Validate the caller's value first, then the configured one: a bad
        # value the user just typed should be reported even if the config has
        # a good one waiting behind it, and vice versa.
        base_url = normalize_base_url(base_url)

        if name == "custom":
            model = model or settings.custom_provider.model
            base_url = base_url or normalize_base_url(settings.custom_provider.base_url)
            extra_headers = extra_headers or settings.custom_provider.extra_headers
            api_key = api_key or load_api_key("custom")
        else:
            model = model or settings.provider.model
            base_url = base_url or normalize_base_url(settings.provider.base_url)

        return provider_registry.create(
            name, api_key=api_key, model=model, base_url=base_url,
            extra_headers=extra_headers, timeout=timeout, max_retries=max_retries,
        )

    @staticmethod
    def get_available_providers() -> list[dict]:
        result = []
        for name in provider_registry.list_providers():
            provider_class = provider_registry.get(name)
            has_key = bool(load_api_key(name))
            result.append({
                "name": name, "models": provider_class.models, "has_credentials": has_key,
                "supports_streaming": provider_class.supports_streaming,
                "supports_function_calling": provider_class.supports_function_calling,
            })
        return result

    @staticmethod
    async def test_connection(name: str) -> tuple[bool, str]:
        provider = ProviderFactory.create_provider(name)
        if not provider:
            return False, f"Unknown provider: {name}"
        try:
            valid = provider.validate_credentials()
            if not valid:
                return False, "Invalid or missing credentials"
            return True, "Connection successful"
        except Exception as e:
            return False, str(e)
