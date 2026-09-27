import os
os.makedirs('c:/Users/iig2y/Desktop/TONYAgent/src/tonyagent/providers', exist_ok=True)

# Anthropic
with open('c:/Users/iig2y/Desktop/TONYAgent/src/tonyagent/providers/anthropic.py', 'w') as f:
    f.write('''"""Anthropic provider for TONYAgent."""

from __future__ import annotations

from typing import AsyncIterator

import anthropic

from tonyagent.providers.base import (
    BaseLLMProvider,
    ChatMessage,
    ToolSchema,
    ToolChoice,
    ChatCompletionChunk,
    ChatCompletion,
    register_provider,
)
from tonyagent.config.keyring import load_api_key


@register_provider
class AnthropicProvider(BaseLLMProvider):
    name = "anthropic"
    models = ["claude-3-5-sonnet-20241022", "claude-3-5-haiku-20241022", "claude-3-opus-20240229"]
    supports_streaming = True
    supports_function_calling = True

    def __init__(self, api_key: str = "", model: str = "claude-3-5-sonnet-20241022", base_url: str = "",
                 extra_headers: dict[str, str] | None = None, timeout: int = 60, max_retries: int = 3):
        super().__init__(api_key=api_key, model=model, base_url=base_url,
                        extra_headers=extra_headers, timeout=timeout, max_retries=max_retries)
        self._client = None

    def _get_client(self):
        if self._client is None:
            api_key = self.api_key or load_api_key("anthropic") or ""
            self._client = anthropic.AsyncAnthropic(
                api_key=api_key, base_url=self.base_url or None,
                default_headers=self.extra_headers, timeout=self.timeout, max_retries=self.max_retries)
        return self._client

    def validate_credentials(self) -> bool:
        api_key = self.api_key or load_api_key("anthropic")
        return bool(api_key and api_key.startswith("sk-ant-"))

    async def chat_completion(self, messages, tools=None, tool_choice=None, stream=False, **kwargs):
        client = self._get_client()
        system = ""
        anthropic_messages = []
        for msg in messages:
            if msg.role.value == "system": system = msg.content or ""
            else: anthropic_messages.append(msg.to_dict())
        anthropic_tools = [tool.to_openai_format()["function"] for tool in tools] if tools else None
        if stream:
            return self._stream_completion(client, system, anthropic_messages, anthropic_tools, tool_choice, **kwargs)
        else:
            return await self._complete(client, system, anthropic_messages, anthropic_tools, tool_choice, **kwargs)

    async def _complete(self, client, system, messages, tools, tool_choice, **kwargs):
        response = await client.messages.create(
            model=self.model, system=system, messages=messages, tools=tools,
            tool_choice=tool_choice.value if tool_choice and tool_choice != ToolChoice.NONE else None,
            max_tokens=kwargs.get("max_tokens", 4096), stream=False)
        content = None; tool_calls = None
        for block in response.content:
            if block.type == "text": content = block.text
            elif block.type == "tool_use":
                if tool_calls is None: tool_calls = []
                tool_calls.append({"id": block.id, "type": "function", "function": {"name": block.name, "arguments": str(block.input)}})
        return ChatCompletion(content=content, tool_calls=tool_calls, finish_reason=response.stop_reason,
            model=response.model, usage={"input_tokens": response.usage.input_tokens, "output_tokens": response.usage.output_tokens})

    async def _stream_completion(self, client, system, messages, tools, tool_choice, **kwargs):
        stream = await client.messages.create(model=self.model, system=system, messages=messages, tools=tools,
            tool_choice=tool_choice.value if tool_choice and tool_choice != ToolChoice.NONE else None,
            max_tokens=kwargs.get("max_tokens", 4096), stream=True)
        tool_calls_buffer = {}
        async for chunk in stream:
            if chunk.type == "content_block_delta":
                if chunk.delta.type == "text_delta":
                    yield ChatCompletionChunk(content=chunk.delta.text)
                elif chunk.delta.type == "input_json_delta":
                    index = chunk.index
                    if index not in tool_calls_buffer:
                        tool_calls_buffer[index] = {"id": f"call_{index}", "type": "function", "function": {"name": "", "arguments": ""}}
                    tool_calls_buffer[index]["function"]["arguments"] += chunk.delta.partial_json
                    yield ChatCompletionChunk(tool_calls=list(tool_calls_buffer.values()))
            elif chunk.type == "content_block_start" and chunk.content_block.type == "tool_use":
                index = chunk.index
                tool_calls_buffer[index] = {"id": chunk.content_block.id, "type": "function", "function": {"name": chunk.content_block.name, "arguments": ""}}
            elif chunk.type == "message_delta":
                if chunk.delta.stop_reason:
                    yield ChatCompletionChunk(finish_reason=chunk.delta.stop_reason, model=self.model)
                    break
''')
print('anthropic.py written')