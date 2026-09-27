"""Google Gemini provider for TONYAgent."""

from __future__ import annotations

from tonyagent.providers.base import (
    OpenAICompatibleProvider,
    register_provider,
)
from tonyagent.config.keyring import load_api_key

@register_provider
class GeminiProvider(OpenAICompatibleProvider):
    key_prefix = "AIza"

    name = "gemini"
    dialect = "gemini"
    models = ["gemini-1.5-pro", "gemini-1.5-flash", "gemini-1.0-pro"]
    supports_streaming = True
    supports_function_calling = True

    def __init__(self, api_key: str = "", model: str = "gemini-1.5-pro", base_url: str = "",
                 extra_headers: dict[str, str] | None = None, timeout: int = 60, max_retries: int = 3):
        super().__init__(api_key=api_key, model=model, base_url=base_url,
                        extra_headers=extra_headers, timeout=timeout, max_retries=max_retries)
        self._model = None

    def validate_credentials(self) -> bool:
        """Local shape check; use check_connection() for a real round-trip."""
        key = self.api_key or load_api_key("gemini") or ""
        return key.startswith("AIza") and len(key) >= 20


