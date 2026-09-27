import os
os.makedirs('c:/Users/iig2y/Desktop/TONYAgent/src/tonyagent/providers', exist_ok=True)
content = '''"""OpenAI provider for TONYAgent."""

from __future__ import annotations

from typing import AsyncIterator

from openai import AsyncOpenAI

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
class OpenAIProvider(BaseLLMProvider):
    name = "openai"
    models = ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "gpt-4", "gpt-3.5-turbo"]
    supports_streaming = True
    supports_function_calling = True

    def __init__(self, api_key: str = "", model: str = "gpt-4o-mini", base_url: str = "",
                 extra_headers: dict[str, str] | None = None, timeout: int = 60, max_retries: int = 3):
        super().__init__(api_key=api_key, model=model, base_url=base_url,
                        extra_headers=extra_headers, timeout=timeout, max_retries=max_retries)
        self._client: AsyncOpenAI | None = None

    def _get_client(self) -> AsyncOpenAI:
        if self._client is None:
            api_key = self.api_key or load_api_key("openai") or ""
            self._client = AsyncOpenAI(
                api_key=api_key,
                base_url=self.base_url or None,
                default_headers=self.extra_headers or None,
                timeout=self.timeout,
                max_retries=self.max_retries,
            )
        return self._client

    def validate_credentials(self) -> bool:
        api_key = self.api_key or load_api_key("openai")
        return bool(api_key and api_key.startswith("sk-"))

    def estimate_tokens(self, messages: list[ChatMessage]) -> int:
        try:
            import tiktoken
            encoding = tiktoken.encoding_for_model(self.model)
            total = 0
            for msg in messages:
                total += len(encoding.encode(msg.content or ""))
                if msg.tool_calls:
                    for tc in msg.tool_calls:
                        total += len(encoding.encode(str(tc)))
            return total
        except ImportError:
            return super().estimate_tokens(messages)

    async def chat_completion(self, messages: list[ChatMessage], tools: list[ToolSchema] | None = None,
                              tool_choice: ToolChoice | None = None, stream: bool = False, **kwargs):
        client = self._get_client()
        openai_messages = [msg.to_dict() for msg in messages]
        openai_tools = [tool.to_openai_format() for tool in tools] if tools else None
        openai_tool_choice = None
        if tool_choice:
            if tool_choice == ToolChoice.AUTO:
                openai_tool_choice = "auto"
            elif tool_choice == ToolChoice.REQUIRED:
                openai_tool_choice = "required"
            elif tool_choice == ToolChoice.NONE:
                openai_tool_choice = "none"
            else:
                openai_tool_choice = {"type": "function", "function": {"name": tool_choice.value}}

        if stream:
            return self._stream_completion(client, openai_messages, openai_tools, openai_tool_choice, **kwargs)
        else:
            return await self._complete(client, openai_messages, openai_tools, openai_tool_choice, **kwargs)

    async def _complete(self, client: AsyncOpenAI, messages: list[dict], tools: list[dict] | None,
                        tool_choice: str | dict | None, **kwargs):
        response = await client.chat.completions.create(
            model=self.model, messages=messages, tools=tools, tool_choice=tool_choice, stream=False, **kwargs)
        choice = response.choices[0]
        return ChatCompletion(
            content=choice.message.content,
            tool_calls=[{"id": tc.id, "type": tc.type, "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                       for tc in (choice.message.tool_calls or [])] if choice.message.tool_calls else None,
            finish_reason=choice.finish_reason, model=response.model,
            usage=response.usage.model_dump() if response.usage else None)

    async def _stream_completion(self, client: AsyncOpenAI, messages: list[dict], tools: list[dict] | None,
                                 tool_choice: str | dict | None, **kwargs):
        stream = await client.chat.completions.create(model=self.model, messages=messages, tools=tools,
                          tool_choice=tool_choice, stream=True, **kwargs)
        tool_calls_buffer: dict[int, dict] = {}
        async for chunk in stream:
            if not chunk.choices: continue
            choice = chunk.choices[0]; delta = choice.delta
            content = delta.content; tool_calls = None
            if delta.tool_calls:
                for tc in delta.tool_calls:
                    index = tc.index
                    if index not in tool_calls_buffer:
                        tool_calls_buffer[index] = {"id": tc.id, "type": "function", "function": {"name": "", "arguments": ""}}
                    if tc.function.name:
                        tool_calls_buffer[index]["function"]["name"] = tc.function.name
                    if tc.function.arguments:
                        tool_calls_buffer[index]["function"]["arguments"] += tc.function.arguments
                tool_calls = list(tool_calls_buffer.values())
            yield ChatCompletionChunk(content=content, tool_calls=tool_calls, finish_reason=choice.finish_reason, model=chunk.model)
            if choice.finish_reason: break
'''
with open('c:/Users/iig2y/Desktop/TONYAgent/src/tonyagent/providers/openai.py', 'w') as f:
    f.write(content)
print('openai.py written')