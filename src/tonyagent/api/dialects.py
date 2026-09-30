"""Wire-format translation for the LLM API layer.

A :class:`Dialect` knows three things and nothing else: how to turn our neutral
message/tool objects into a provider's JSON, how to turn a streaming event into
a neutral chunk, and how to read the model list. Everything above this layer
stays vendor-agnostic.

There is one dialect and it speaks the OpenAI-compatible shape, which is what
OpenRouter accepts for every model it proxies. The class was not collapsed into
the client because that module is HTTP transport and this one is vocabulary:
a provider that did not speak OpenAI's shape would change the four methods
below and nothing else.
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
    """The OpenAI-compatible wire format."""

    #: Used only when a caller passes no base_url. OpenRouter is the sole
    #: provider, so this is its endpoint rather than a vendor-agnostic guess.
    default_base_url = "https://openrouter.ai/api/v1"

    def build_request(self, model, messages, tools=None, tool_choice=None, stream=False, **extra):
        payload: dict[str, Any] = {"model": model, "messages": messages}
        built = tool_to_openai(tools)
        if built:
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

