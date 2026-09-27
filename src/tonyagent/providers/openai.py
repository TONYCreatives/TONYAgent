"""OpenAI provider for TONYAgent.

The wire protocol (client, streaming, tool-call assembly) lives on
``OpenAICompatibleProvider`` in ``base.py`` so openrouter/groq/mistral/custom
share one real implementation instead of an abstract stub.
"""

from __future__ import annotations

from tonyagent.config.keyring import load_api_key
from tonyagent.providers.base import (
    OpenAICompatibleProvider,
    register_provider,
)


@register_provider
class OpenAIProvider(OpenAICompatibleProvider):
    key_prefix = "sk-"

    name = "openai"
    models = ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "gpt-4", "gpt-3.5-turbo"]
    supports_streaming = True
    supports_function_calling = True

    def __init__(self, api_key: str = "", model: str = "gpt-4o-mini", base_url: str = "",
                 extra_headers: dict[str, str] | None = None, timeout: int = 60, max_retries: int = 3):
        super().__init__(api_key=api_key, model=model, base_url=base_url,
                        extra_headers=extra_headers, timeout=timeout, max_retries=max_retries)

