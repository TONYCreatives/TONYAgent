import os
os.makedirs('c:/Users/iig2y/Desktop/TONYAgent/src/tonyagent/providers', exist_ok=True)

# Mistral
with open('c:/Users/iig2y/Desktop/TONYAgent/src/tonyagent/providers/mistral.py', 'w') as f:
    f.write('''"""Mistral provider for TONYAgent (OpenAI-compatible)."""

from __future__ import annotations

from tonyagent.providers.base import OpenAICompatibleProvider, register_provider
from tonyagent.config.keyring import load_api_key


@register_provider
class MistralProvider(OpenAICompatibleProvider):
    name = "mistral"
    models = ["mistral-large-latest", "mistral-medium-latest", "mistral-small-latest", "mistral-tiny"]
    supports_streaming = True
    supports_function_calling = True

    def __init__(self, api_key: str = "", model: str = "mistral-large-latest", base_url: str = "",
                 extra_headers: dict[str, str] | None = None, timeout: int = 60, max_retries: int = 3):
        super().__init__(api_key=api_key, model=model, base_url=base_url or "https://api.mistral.ai/v1",
                        extra_headers=extra_headers, timeout=timeout, max_retries=max_retries)

    def validate_credentials(self) -> bool:
        api_key = self.api_key or load_api_key("mistral")
        return bool(api_key)

    async def chat_completion(self, messages, tools=None, tool_choice=None, stream=False, **kwargs):
        return await super().chat_completion(messages, tools, tool_choice, stream, **kwargs)
''')
print('mistral.py written')

# Groq
with open('c:/Users/iig2y/Desktop/TONYAgent/src/tonyagent/providers/groq.py', 'w') as f:
    f.write('''"""Groq provider for TONYAgent (OpenAI-compatible)."""

from __future__ import annotations

from tonyagent.providers.base import OpenAICompatibleProvider, register_provider
from tonyagent.config.keyring import load_api_key


@register_provider
class GroqProvider(OpenAICompatibleProvider):
    name = "groq"
    models = ["llama-3.1-70b-versatile", "llama-3.1-8b-instant", "mixtral-8x7b-32768", "gemma2-9b-it"]
    supports_streaming = True
    supports_function_calling = True

    def __init__(self, api_key: str = "", model: str = "llama-3.1-70b-versatile", base_url: str = "",
                 extra_headers: dict[str, str] | None = None, timeout: int = 60, max_retries: int = 3):
        super().__init__(api_key=api_key, model=model, base_url=base_url or "https://api.groq.com/openai/v1",
                        extra_headers=extra_headers, timeout=timeout, max_retries=max_retries)

    def validate_credentials(self) -> bool:
        api_key = self.api_key or load_api_key("groq")
        return bool(api_key and api_key.startswith("gsk_"))

    async def chat_completion(self, messages, tools=None, tool_choice=None, stream=False, **kwargs):
        return await super().chat_completion(messages, tools, tool_choice, stream, **kwargs)
''')
print('groq.py written')

# OpenRouter
with open('c:/Users/iig2y/Desktop/TONYAgent/src/tonyagent/providers/openrouter.py', 'w') as f:
    f.write('''"""OpenRouter provider for TONYAgent (OpenAI-compatible)."""

from __future__ import annotations

from tonyagent.providers.base import OpenAICompatibleProvider, register_provider
from tonyagent.config.keyring import load_api_key


@register_provider
class OpenRouterProvider(OpenAICompatibleProvider):
    name = "openrouter"
    models = ["openrouter/auto", "anthropic/claude-3.5-sonnet", "openai/gpt-4o", "google/gemini-pro-1.5"]
    supports_streaming = True
    supports_function_calling = True

    def __init__(self, api_key: str = "", model: str = "openrouter/auto", base_url: str = "",
                 extra_headers: dict[str, str] | None = None, timeout: int = 60, max_retries: int = 3):
        headers = extra_headers or {}
        headers.setdefault("HTTP-Referer", "https://tonyagent.local")
        headers.setdefault("X-Title", "TONYAgent")
        super().__init__(api_key=api_key, model=model, base_url=base_url or "https://openrouter.ai/api/v1",
                        extra_headers=headers, timeout=timeout, max_retries=max_retries)

    def validate_credentials(self) -> bool:
        api_key = self.api_key or load_api_key("openrouter")
        return bool(api_key and api_key.startswith("sk-or-"))

    async def chat_completion(self, messages, tools=None, tool_choice=None, stream=False, **kwargs):
        return await super().chat_completion(messages, tools, tool_choice, stream, **kwargs)
''')
print('openrouter.py written')