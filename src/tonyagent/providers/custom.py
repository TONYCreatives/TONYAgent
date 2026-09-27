"""Custom OpenAI-compatible endpoint provider for TONYAgent."""

from __future__ import annotations

from tonyagent.providers.base import OpenAICompatibleProvider, register_provider
from tonyagent.config.keyring import load_api_key  # noqa: F401


@register_provider
class CustomProvider(OpenAICompatibleProvider):
    key_prefix = ""

    name = "custom"
    models = []
    supports_streaming = True
    supports_function_calling = True

    def __init__(self, api_key: str = "", model: str = "", base_url: str = "",
                 extra_headers: dict[str, str] | None = None, timeout: int = 60, max_retries: int = 3):
        if not base_url:
            raise ValueError("Custom provider requires base_url")
        super().__init__(api_key=api_key, model=model, base_url=base_url,
                        extra_headers=extra_headers, timeout=timeout, max_retries=max_retries)

