"""Providers package for TONYAgent."""

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

# Imported for their side effect: `@register_provider` runs at import time, so a
# provider nobody imports is a provider the window cannot see.
#
# Two, and both of them aggregators. The five OpenAI-shaped vendors that were
# here are gone: they answered `/models` with an id and nothing else, so every
# piece of the catalogue work would have needed a second implementation that
# returned "unknown" for most fields. OpenRouter and OpenCode Go both publish
# real metadata, which is what makes keeping two of them the easier case.
from tonyagent.providers import opencode_go, openrouter

__all__ = [
    "LLMProvider", "ChatMessage", "ToolSchema", "ToolChoice",
    "ChatCompletionChunk", "ChatCompletion", "ProviderRegistry",
    "register_provider", "provider_registry", "ProviderFactory",
]
