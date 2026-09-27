"""Groq provider for TONYAgent (OpenAI-compatible)."""

from __future__ import annotations

from tonyagent.providers.base import OpenAICompatibleProvider, register_provider
from tonyagent.config.keyring import load_api_key  # noqa: F401


@register_provider
class GroqProvider(OpenAICompatibleProvider):
    key_prefix = "gsk_"

    name = "groq"
    models = ["llama-3.1-70b-versatile", "llama-3.1-8b-instant", "mixtral-8x7b-32768", "gemma2-9b-it"]
    supports_streaming = True
    supports_function_calling = True

    def __init__(self, api_key: str = "", model: str = "llama-3.1-70b-versatile", base_url: str = "",
                 extra_headers: dict[str, str] | None = None, timeout: int = 60, max_retries: int = 3):
        super().__init__(api_key=api_key, model=model, base_url=base_url or "https://api.groq.com/openai/v1",
                        extra_headers=extra_headers, timeout=timeout, max_retries=max_retries)

