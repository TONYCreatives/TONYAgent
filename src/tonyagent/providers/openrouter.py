"""OpenRouter provider for TONYAgent (OpenAI-compatible)."""

from __future__ import annotations

from tonyagent.providers.base import OpenAICompatibleProvider, register_provider
from tonyagent.config.keyring import load_api_key  # noqa: F401


@register_provider
class OpenRouterProvider(OpenAICompatibleProvider):
    key_prefix = "sk-or-"
    # A real v1 key is "sk-or-v1-" + 64 hex chars = 73 characters. Checking the
    # exact length locally is what turns OpenRouter's opaque
    # "401 User not found" into a clear "the key was cut short".
    key_length = 73

    name = "openrouter"
    #: A handful of ids to seed the model field with. OpenRouter proxies
    #: hundreds more and the field takes any of them, so this is a starting
    #: point rather than the list.
    models = [
        "openrouter/auto",
        "anthropic/claude-sonnet-4.5",
        "openai/gpt-5",
        "google/gemini-2.5-pro",
        "deepseek/deepseek-chat",
    ]
    supports_streaming = True
    supports_function_calling = True

    def __init__(self, api_key: str = "", model: str = "openrouter/auto", base_url: str = "",
                 extra_headers: dict[str, str] | None = None, timeout: int = 60, max_retries: int = 3):
        headers = extra_headers or {}
        headers.setdefault("HTTP-Referer", "https://tonyagent.local")
        headers.setdefault("X-Title", "TONYAgent")
        super().__init__(api_key=api_key, model=model, base_url=base_url or "https://openrouter.ai/api/v1",
                        extra_headers=headers, timeout=timeout, max_retries=max_retries)

