"""Ollama provider for TONYAgent (local).

Ollama exposes an OpenAI-compatible endpoint at /v1, so this reuses the shared
client and dialect rather than carrying a second streaming implementation.
"""

from __future__ import annotations

from tonyagent.providers.base import OpenAICompatibleProvider, register_provider


@register_provider
class OllamaProvider(OpenAICompatibleProvider):
    key_prefix = ""

    name = "ollama"
    dialect = "openai"
    models = ["llama3.1", "llama3.2", "codellama", "mistral", "phi3"]
    supports_streaming = True
    supports_function_calling = False

    def __init__(self, api_key: str = "", model: str = "llama3.1", base_url: str = "",
                 extra_headers: dict[str, str] | None = None, timeout: int = 60, max_retries: int = 3):
        super().__init__(api_key=api_key, model=model,
                         base_url=base_url or "http://localhost:11434/v1",
                         extra_headers=extra_headers, timeout=timeout, max_retries=max_retries)

