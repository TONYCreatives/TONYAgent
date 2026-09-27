import os
os.makedirs('c:/Users/iig2y/Desktop/TONYAgent/src/tonyagent/providers', exist_ok=True)

# Ollama
with open('c:/Users/iig2y/Desktop/TONYAgent/src/tonyagent/providers/ollama.py', 'w') as f:
    f.write('''"""Ollama provider for TONYAgent (local)."""

from __future__ import annotations

from typing import AsyncIterator
import httpx

from tonyagent.providers.base import (
    BaseLLMProvider,
    ChatMessage,
    ToolSchema,
    ToolChoice,
    ChatCompletionChunk,
    ChatCompletion,
    register_provider,
)


@register_provider
class OllamaProvider(BaseLLMProvider):
    name = "ollama"
    models = ["llama3.1", "llama3.2", "codellama", "mistral", "phi3"]
    supports_streaming = True
    supports_function_calling = False

    def __init__(self, api_key: str = "", model: str = "llama3.1", base_url: str = "",
                 extra_headers: dict[str, str] | None = None, timeout: int = 60, max_retries: int = 3):
        super().__init__(api_key=api_key, model=model, base_url=base_url or "http://localhost:11434",
                        extra_headers=extra_headers, timeout=timeout, max_retries=max_retries)
        self._client: httpx.AsyncClient | None = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout)
        return self._client

    def validate_credentials(self) -> bool:
        return True

    def estimate_tokens(self, messages: list[ChatMessage]) -> int:
        total_chars = sum(len(m.content or "") for m in messages)
        return total_chars // 4

    async def chat_completion(self, messages, tools=None, tool_choice=None, stream=False, **kwargs):
        client = self._get_client()
        ollama_messages = [{"role": m.role.value, "content": m.content or ""} for m in messages]
        payload = {"model": self.model, "messages": ollama_messages, "stream": stream, "options": {"num_predict": kwargs.get("max_tokens", 4096)}}
        if stream:
            return self._stream_completion(client, payload, **kwargs)
        else:
            return await self._complete(client, payload, **kwargs)

    async def _complete(self, client, payload, **kwargs):
        response = await client.post("/api/chat", json=payload)
        response.raise_for_status()
        data = response.json()
        content = data.get("message", {}).get("content", "")
        return ChatCompletion(content=content, finish_reason="stop", model=self.model, usage={})

    async def _stream_completion(self, client, payload, **kwargs):
        async with client.stream("POST", "/api/chat", json=payload) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if line.strip():
                    import json
                    data = json.loads(line)
                    if data.get("message", {}).get("content"):
                        yield ChatCompletionChunk(content=data["message"]["content"])
                    if data.get("done"):
                        yield ChatCompletionChunk(finish_reason="stop", model=self.model)
                        break
''')
print('ollama.py written')

# Custom
with open('c:/Users/iig2y/Desktop/TONYAgent/src/tonyagent/providers/custom.py', 'w') as f:
    f.write('''"""Custom OpenAI-compatible endpoint provider for TONYAgent."""

from __future__ import annotations

from tonyagent.providers.base import OpenAICompatibleProvider, register_provider
from tonyagent.config.keyring import load_api_key


@register_provider
class CustomProvider(OpenAICompatibleProvider):
    name = "custom"
    models = []
    supports_streaming = True
    supports_function_calling = True

    def __init__(self, api_key: str = "", model: str = "", base_url: str = "",
                 extra_headers: dict[str, str] | None = None, timeout: int = 60, max_retries: int = 3):
        if not base_url:
            raise ValueError("Custom provider requires base_url")
        super().__init__(api_key=api_key, model=model, base_url=base_url,
                        extra_headers=extra_headers, timeout=timeout, max_retries=max_retries)

    def validate_credentials(self) -> bool:
        return bool(self.base_url and (self.api_key or load_api_key("custom")))

    async def chat_completion(self, messages, tools=None, tool_choice=None, stream=False, **kwargs):
        return await super().chat_completion(messages, tools, tool_choice, stream, **kwargs)
''')
print('custom.py written')