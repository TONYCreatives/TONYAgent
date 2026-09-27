import os
os.makedirs('c:/Users/iig2y/Desktop/TONYAgent/src/tonyagent/providers', exist_ok=True)

with open('c:/Users/iig2y/Desktop/TONYAgent/src/tonyagent/providers/gemini.py', 'w') as f:
    f.write('''"""Google Gemini provider for TONYAgent."""

from __future__ import annotations

from typing import AsyncIterator

import google.generativeai as genai

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
class GeminiProvider(BaseLLMProvider):
    name = "gemini"
    models = ["gemini-1.5-pro", "gemini-1.5-flash", "gemini-1.0-pro"]
    supports_streaming = True
    supports_function_calling = True

    def __init__(self, api_key: str = "", model: str = "gemini-1.5-pro", base_url: str = "",
                 extra_headers: dict[str, str] | None = None, timeout: int = 60, max_retries: int = 3):
        super().__init__(api_key=api_key, model=model, base_url=base_url,
                        extra_headers=extra_headers, timeout=timeout, max_retries=max_retries)
        self._model = None

    def _get_model(self):
        if self._model is None:
            api_key = self.api_key or load_api_key("gemini") or ""
            genai.configure(api_key=api_key)
            self._model = genai.GenerativeModel(self.model)
        return self._model

    def validate_credentials(self) -> bool:
        api_key = self.api_key or load_api_key("gemini")
        return bool(api_key)

    def estimate_tokens(self, messages) -> int:
        try:
            model = self._get_model()
            total = 0
            for msg in messages:
                if msg.content:
                    total += model.count_tokens(msg.content).total_tokens
            return total
        except Exception:
            return super().estimate_tokens(messages)

    async def chat_completion(self, messages, tools=None, tool_choice=None, stream=False, **kwargs):
        model = self._get_model()
        contents = []
        system = ""
        for msg in messages:
            if msg.role.value == "system": system = msg.content or ""
            else: contents.append({"role": msg.role.value, "parts": [msg.content] or []})
        genai_tools = None
        if tools:
            genai_tools = [{"function_declarations": [tool.to_openai_format()["function"]]} for tool in tools]
        if stream:
            return self._stream_completion(model, contents, system, genai_tools, tool_choice, **kwargs)
        else:
            return await self._complete(model, contents, system, genai_tools, tool_choice, **kwargs)

    async def _complete(self, model, contents, system, tools, tool_choice, **kwargs):
        response = await model.generate_content_async(
            contents=contents, system_instruction=system if system else None,
            tools=tools, generation_config=genai.GenerationConfig(max_output_tokens=kwargs.get("max_tokens", 4096)), stream=False)
        content = response.text if response.text else None
        tool_calls = None
        if response.candidates and response.candidates[0].content.parts:
            for part in response.candidates[0].content.parts:
                if hasattr(part, "function_call") and part.function_call:
                    fc = part.function_call
                    if tool_calls is None: tool_calls = []
                    tool_calls.append({"id": fc.name, "type": "function", "function": {"name": fc.name, "arguments": str(fc.args)}})
        return ChatCompletion(content=content, tool_calls=tool_calls, finish_reason="stop", model=self.model, usage={})

    async def _stream_completion(self, model, contents, system, tools, tool_choice, **kwargs):
        stream = await model.generate_content_async(
            contents=contents, system_instruction=system if system else None,
            tools=tools, generation_config=genai.GenerationConfig(max_output_tokens=kwargs.get("max_tokens", 4096)), stream=True)
        async for chunk in stream:
            if chunk.text:
                yield ChatCompletionChunk(content=chunk.text)
            if chunk.candidates and chunk.candidates[0].content.parts:
                for part in chunk.candidates[0].content.parts:
                    if hasattr(part, "function_call") and part.function_call:
                        fc = part.function_call
                        yield ChatCompletionChunk(tool_calls=[{"id": fc.name, "type": "function", "function": {"name": fc.name, "arguments": str(fc.args)}}])
        yield ChatCompletionChunk(finish_reason="stop", model=self.model)
''')
print('gemini.py written')