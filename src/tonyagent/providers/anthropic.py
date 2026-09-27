"""Anthropic provider for TONYAgent."""

from __future__ import annotations

from tonyagent.providers.base import (
    OpenAICompatibleProvider,
    register_provider,
)
from tonyagent.config.keyring import load_api_key

@register_provider
class AnthropicProvider(OpenAICompatibleProvider):
    key_prefix = "sk-ant-"

    name = "anthropic"
    dialect = "anthropic"
    models = ["claude-3-5-sonnet-20241022", "claude-3-5-haiku-20241022", "claude-3-opus-20240229"]
    supports_streaming = True
    supports_function_calling = True

    def __init__(self, api_key: str = "", model: str = "claude-3-5-sonnet-20241022", base_url: str = "",
                 extra_headers: dict[str, str] | None = None, timeout: int = 60, max_retries: int = 3):
        super().__init__(api_key=api_key, model=model, base_url=base_url,
                        extra_headers=extra_headers, timeout=timeout, max_retries=max_retries)

    def validate_credentials(self) -> bool:
        """Local shape check; use check_connection() for a real round-trip."""
        key = self.api_key or load_api_key("anthropic") or ""
        return key.startswith("sk-ant-") and len(key) >= 20

