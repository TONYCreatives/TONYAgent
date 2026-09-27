import os
os.makedirs('c:/Users/iig2y/Desktop/TONYAgent/src/tonyagent/providers', exist_ok=True)

# Factory
with open('c:/Users/iig2y/Desktop/TONYAgent/src/tonyagent/providers/factory.py', 'w') as f:
    f.write('''"""Provider factory for TONYAgent."""

from __future__ import annotations

from typing import Optional

from tonyagent.providers.base import provider_registry, BaseLLMProvider
from tonyagent.config.settings import settings
from tonyagent.config.keyring import load_api_key


class ProviderFactory:
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

        api_key = load_api_key(name)

        if name == "custom":
            model = model or settings.custom_provider.model
            base_url = base_url or settings.custom_provider.base_url
            extra_headers = extra_headers or settings.custom_provider.extra_headers
            api_key = api_key or load_api_key("custom")
        else:
            model = model or settings.provider.model
            base_url = base_url or settings.provider.base_url

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
''')
print('factory.py written')

# __init__.py
with open('c:/Users/iig2y/Desktop/TONYAgent/src/tonyagent/providers/__init__.py', 'w') as f:
    f.write('''"""Providers package for TONYAgent."""

from tonyagent.providers.base import (
    LLMProvider,
    ChatMessage,
    ToolSchema,
    ToolChoice,
    ChatCompletionChunk,
    ChatCompletion,
    ProviderRegistry,
    register_provider,
    provider_registry,
)
from tonyagent.providers.factory import ProviderFactory

from tonyagent.providers import openai, anthropic, gemini, mistral, groq, openrouter, ollama, custom

__all__ = [
    "LLMProvider", "ChatMessage", "ToolSchema", "ToolChoice",
    "ChatCompletionChunk", "ChatCompletion", "ProviderRegistry",
    "register_provider", "provider_registry", "ProviderFactory",
]
''')
print('__init__.py written')