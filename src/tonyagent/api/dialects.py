"""Wire-format translation for the LLM API layer.

A :class:`Dialect` knows three things and nothing else: how to turn our neutral
message/tool objects into a provider's JSON, how to turn a streaming event into
a neutral chunk, and how to read the model list. Everything above this layer
stays vendor-agnostic.

This replaces the previous arrangement, where each provider subclass carried its
own copy of streaming and tool-call assembly - which is how five providers ended
up silently returning ``None``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Iterable


@dataclass
class Chunk:
    """One piece of a streamed response."""

    content: str | None = None
    tool_calls: list[dict] | None = None
    finish_reason: str | None = None
    model: str = ""


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass
class Completion:
    content: str | None = None
    tool_calls: list[dict] | None = None
    finish_reason: str | None = None
    model: str = ""
    usage: Usage = field(default_factory=Usage)


def tool_to_openai(tools: list[dict] | None) -> list[dict] | None:
    if not tools:
        return None
    out = []
    for t in tools:
        fn = t.get("function", t)
        out.append(
            {
                "type": "function",
                "function": {
                    "name": fn.get("name", ""),
                    "description": fn.get("description", ""),
                    "parameters": fn.get("parameters") or {"type": "object", "properties": {}},
                },
            }
        )
    return out


class Dialect:
    """Base dialect: the OpenAI-compatible wire format."""

    name = "openai"
    default_base_url = "https://api.openai.com/v1"
    key_prefix = ""
    supports_tools = True

    def build_request(self, model, messages, tools=None, tool_choice=None, stream=False, **extra):
        payload: dict[str, Any] = {"model": model, "messages": messages}
        built = tool_to_openai(tools)
        if built and self.supports_tools:
            payload["tools"] = built
            if tool_choice:
                payload["tool_choice"] = tool_choice
        if stream:
            payload["stream"] = True
        payload.update(extra)
        return payload

    def url(self, base_url: str, model: str, stream: bool) -> str:
        return f"{base_url.rstrip('/')}/chat/completions"

    def auth_headers(self, api_key: str) -> dict:
        return {"Authorization": f"Bearer {api_key}"}

    def stream_param(self) -> str | None:
        """Query parameter that enables streaming, if the vendor needs one."""
        return None

    # -- streaming -----------------------------------------------------------
    def parse_stream_event(self, event: str, data: str, acc: dict) -> Chunk | None:
        if not data or data == "[DONE]":
            return None
        try:
            obj = json.loads(data)
        except ValueError:
            return None
        if obj.get("error"):
            return Chunk(finish_reason="error")
        choices = obj.get("choices") or []
        if not choices:
            return None
        choice = choices[0]
        delta = choice.get("delta") or {}
        self.accumulate_tool_calls(delta.get("tool_calls"), acc)
        return Chunk(
            content=delta.get("content"),
            tool_calls=current_tool_calls(acc),
            finish_reason=choice.get("finish_reason"),
            model=obj.get("model", ""),
        )

    @staticmethod
    def accumulate_tool_calls(parts: Iterable[dict] | None, acc: dict) -> None:
        """Tool calls arrive in fragments keyed by index; stitch them back."""
        if not parts:
            return
        buf = acc.setdefault("buffer", {})
        for part in parts:
            slot = buf.setdefault(
                part.get("index", 0),
                {"id": "", "type": "function", "function": {"name": "", "arguments": ""}},
            )
            if part.get("id"):
                slot["id"] = part["id"]
            fn = part.get("function") or {}
            if fn.get("name"):
                slot["function"]["name"] = fn["name"]
            if fn.get("arguments"):
                slot["function"]["arguments"] += fn["arguments"]

    # -- non-streaming -------------------------------------------------------
    def parse_completion(self, obj: dict) -> Completion:
        choices = obj.get("choices") or []
        if not choices:
            return Completion(content="", model=obj.get("model", ""))
        choice = choices[0]
        message = choice.get("message") or {}
        tool_calls = None
        if message.get("tool_calls"):
            tool_calls = [
                {
                    "id": tc.get("id", ""),
                    "type": "function",
                    "function": {
                        "name": (tc.get("function") or {}).get("name", ""),
                        "arguments": (tc.get("function") or {}).get("arguments", ""),
                    },
                }
                for tc in message["tool_calls"]
            ]
        usage = obj.get("usage") or {}
        return Completion(
            content=message.get("content"),
            tool_calls=tool_calls,
            finish_reason=choice.get("finish_reason"),
            model=obj.get("model", ""),
            usage=Usage(usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0)),
        )

    # -- models --------------------------------------------------------------
    def parse_models(self, obj: dict) -> list[str]:
        return [m.get("id", "") for m in (obj.get("data") or []) if m.get("id")]

    def models_url(self, base_url: str) -> str:
        return f"{base_url.rstrip('/')}/models"


def current_tool_calls(acc: dict) -> list[dict] | None:
    buf = acc.get("buffer")
    return list(buf.values()) if buf else None


class AnthropicDialect(Dialect):
    """Anthropic Messages API."""

    name = "anthropic"
    default_base_url = "https://api.anthropic.com/v1"
    key_prefix = "sk-ant-"

    def build_request(self, model, messages, tools=None, tool_choice=None, stream=False, **extra):
        system = "\n".join(m["content"] for m in messages if m.get("role") == "system")
        payload: dict[str, Any] = {
            "model": model,
            "messages": [
                {"role": m["role"], "content": m["content"]}
                for m in messages
                if m.get("role") != "system"
            ],
            "max_tokens": extra.pop("max_tokens", 4096),
        }
        if system:
            payload["system"] = system
        built = tool_to_openai(tools)
        if built:
            payload["tools"] = [
                {
                    "name": t["function"]["name"],
                    "description": t["function"]["description"],
                    "input_schema": t["function"]["parameters"],
                }
                for t in built
            ]
        payload.update(extra)
        return payload

    def url(self, base_url, model, stream):
        return f"{base_url.rstrip('/')}/messages"

    def auth_headers(self, api_key):
        return {"x-api-key": api_key, "anthropic-version": "2023-06-01"}

    def stream_param(self):
        return "stream"

    def parse_stream_event(self, event, data, acc):
        if not data:
            return None
        try:
            obj = json.loads(data)
        except ValueError:
            return None
        etype = obj.get("type")
        if etype == "content_block_delta":
            delta = obj.get("delta") or {}
            if delta.get("type") == "text_delta":
                return Chunk(content=delta.get("text"))
            if delta.get("type") == "input_json_delta":
                buf = acc.setdefault("buffer", {})
                slot = buf.setdefault(
                    obj.get("index", 0),
                    {"id": "", "type": "function", "function": {"name": "", "arguments": ""}},
                )
                slot["function"]["arguments"] += delta.get("partial_json", "")
                return Chunk(tool_calls=list(buf.values()))
            return None
        if etype == "content_block_start":
            block = obj.get("content_block") or {}
            if block.get("type") == "tool_use":
                acc.setdefault("buffer", {})[obj.get("index", 0)] = {
                    "id": block.get("id", ""),
                    "type": "function",
                    "function": {"name": block.get("name", ""), "arguments": ""},
                }
                return Chunk(tool_calls=list(acc["buffer"].values()))
            return None
        if etype == "message_delta":
            return Chunk(finish_reason=(obj.get("delta") or {}).get("stop_reason"))
        return None

    def parse_completion(self, obj):
        text, tool_calls = [], []
        for block in obj.get("content") or []:
            if block.get("type") == "text":
                text.append(block.get("text", ""))
            elif block.get("type") == "tool_use":
                tool_calls.append(
                    {
                        "id": block.get("id", ""),
                        "type": "function",
                        "function": {
                            "name": block.get("name", ""),
                            "arguments": json.dumps(block.get("input", {})),
                        },
                    }
                )
        usage = obj.get("usage") or {}
        return Completion(
            content="".join(text) or None,
            tool_calls=tool_calls or None,
            finish_reason=obj.get("stop_reason"),
            model=obj.get("model", ""),
            usage=Usage(usage.get("input_tokens", 0), usage.get("output_tokens", 0)),
        )

class GeminiDialect(Dialect):
    """Google Gemini generateContent API."""

    name = "gemini"
    default_base_url = "https://generativelanguage.googleapis.com/v1beta"
    key_prefix = "AIza"

    def url(self, base_url, model, stream):
        verb = "streamGenerateContent" if stream else "generateContent"
        name = model if model.startswith("models/") else f"models/{model}"
        return f"{base_url.rstrip('/')}/{name}:{verb}"

    def auth_headers(self, api_key):
        return {}  # Gemini authenticates by query parameter.

    def key_query(self, api_key: str) -> str:
        return f"key={api_key}"

    def stream_param(self):
        return "alt=sse"

    def build_request(self, model, messages, tools=None, tool_choice=None, stream=False, **extra):
        contents, system = [], []
        for m in messages:
            if m.get("role") == "system":
                system.append(m.get("content", ""))
                continue
            contents.append(
                {
                    "role": "model" if m.get("role") == "assistant" else "user",
                    "parts": [{"text": m.get("content", "")}],
                }
            )
        payload: dict[str, Any] = {"contents": contents}
        if system:
            payload["systemInstruction"] = {"parts": [{"text": "\n".join(system)}]}
        built = tool_to_openai(tools)
        if built:
            payload["tools"] = [
                {
                    "functionDeclarations": [
                        {
                            "name": t["function"]["name"],
                            "description": t["function"]["description"],
                            "parameters": t["function"]["parameters"],
                        }
                        for t in built
                    ]
                }
            ]
        payload.update(extra)
        return payload

    def parse_stream_event(self, event, data, acc):
        if not data:
            return None
        try:
            obj = json.loads(data)
        except ValueError:
            return None
        cands = obj.get("candidates") or []
        if not cands:
            return None
        parts = (cands[0].get("content") or {}).get("parts") or []
        return Chunk(
            content="".join(p.get("text", "") for p in parts if p.get("text")) or None,
            tool_calls=[_gemini_call(p) for p in parts if p.get("functionCall")] or None,
            finish_reason=cands[0].get("finishReason"),
        )

    def parse_completion(self, obj):
        cands = obj.get("candidates") or []
        if not cands:
            return Completion(content="")
        parts = (cands[0].get("content") or {}).get("parts") or []
        usage = obj.get("usageMetadata") or {}
        return Completion(
            content="".join(p.get("text", "") for p in parts if p.get("text")) or None,
            tool_calls=[_gemini_call(p) for p in parts if p.get("functionCall")] or None,
            finish_reason=cands[0].get("finishReason"),
            model=obj.get("modelVersion", ""),
            usage=Usage(usage.get("promptTokenCount", 0), usage.get("candidatesTokenCount", 0)),
        )

    def parse_models(self, obj):
        return [m.get("name", "").replace("models/", "") for m in (obj.get("models") or [])]

    def models_url(self, base_url):
        return f"{base_url.rstrip('/')}/models"


def _gemini_call(part: dict) -> dict:
    fc = part["functionCall"]
    return {
        "id": fc.get("name", ""),
        "type": "function",
        "function": {"name": fc.get("name", ""), "arguments": json.dumps(fc.get("args", {}))},
    }


DIALECTS: dict[str, type[Dialect]] = {
    "openai": Dialect,
    "anthropic": AnthropicDialect,
    "gemini": GeminiDialect,
}


def get_dialect(name: str) -> Dialect:
    return DIALECTS.get(name, Dialect)()


