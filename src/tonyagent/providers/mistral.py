"""Mistral provider for TONYAgent (OpenAI-compatible)."""

from __future__ import annotations

from tonyagent.providers.base import OpenAICompatibleProvider, register_provider
from tonyagent.config.keyring import load_api_key  # noqa: F401


@register_provider
class MistralProvider(OpenAICompatibleProvider):
    key_prefix = ""

    name = "mistral"
    models = ["mistral-large-latest", "mistral-medium-latest", "mistral-small-latest", "mistral-tiny"]
    supports_streaming = True
    supports_function_calling = True

    def __init__(self, api_key: str = "", model: str = "mistral-large-latest", base_url: str = "",
                 extra_headers: dict[str, str] | None = None, timeout: int = 60, max_retries: int = 3):
        super().__init__(api_key=api_key, model=model, base_url=base_url or "https://api.mistral.ai/v1",
                        extra_headers=extra_headers, timeout=timeout, max_retries=max_retries)

