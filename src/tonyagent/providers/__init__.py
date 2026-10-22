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
# Three. Two of them are aggregators: the five OpenAI-shaped vendors that were
# here are gone, they answered `/models` with an id and nothing else, so every
# piece of the catalogue work would have needed a second implementation that
# returned "unknown" for most fields. OpenRouter and OpenCode Go both publish
# real metadata, which is what makes keeping two of them the easier case.
#
# The third is not an aggregator but a local one: AirLLM runs on this machine
# and answers the same wire format, which is the only reason it is here at all.
from tonyagent.providers import local_airllm, opencode_go, opencode_zen, openrouter

__all__ = [
    "LLMProvider", "ChatMessage", "ToolSchema", "ToolChoice",
    "ChatCompletionChunk", "ChatCompletion", "ProviderRegistry",
    "register_provider", "provider_registry", "ProviderFactory",
]
