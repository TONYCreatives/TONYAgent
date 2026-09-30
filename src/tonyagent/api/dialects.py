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
    """One piece of a streamed response.

    ``reasoning`` is a model's thinking, which OpenRouter streams under its own
    key rather than inside ``content``. It is kept apart deliberately: folding
    it into ``content`` would put the trace of how an answer was reached into
    the transcript AND into the message history sent back on the next turn,
    where the model would read its own scratchpad as part of what it had said.
    """

    content: str | None = None
    tool_calls: list[dict] | None = None
    finish_reason: str | None = None
    model: str = ""
    #: This chunk's slice of thinking. A string, appended as it streams.
    reasoning: str | None = None
    #: The whole ``reasoning_details`` list so far, not just this chunk's part.
    #: Returned on every chunk so the final value is always in hand, and sent
    #: back on the assistant message: it is what keeps a tool-calling turn
    #: continuous, because without it the provider sees reasoning blocks it
    #: cannot match to what it produced.
    reasoning_details: list[dict] | None = None


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    #: Billed as output tokens but reported separately, so a turn that spent
    #: everything on thinking is distinguishable from one that wrote prose.
    reasoning_tokens: int = 0

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
    reasoning: str | None = None
    reasoning_details: list[dict] | None = None


@dataclass(frozen=True)
class ReasoningSpec:
    """What a model reports about its own thinking.

    ``efforts`` is empty for a model that reasons without offering a dial, and
    the model is simply absent from the mapping for one that does not reason at
    all. Those are different facts: the first still thinks, the second cannot
    be asked to.
    """

    efforts: list[str] = field(default_factory=list)
    default_effort: str = ""
    #: Reasoning cannot be turned off, so "off" is not an option to offer and
    #: ``none`` is not a value to send.
    mandatory: bool = False

    def accepts(self, effort: str) -> bool:
        """Whether this model can be asked for exactly this effort."""
        if not effort or self.mandatory and effort == "none":
            return False
        return effort in self.efforts


def read_usage(obj: dict) -> Usage:
    """Token counts, including the reasoning that ``completion_tokens`` hides.

    A model that reasoned for 4000 tokens and wrote 200 reports 4200 as its
    completion tokens; the split only exists under
    ``completion_tokens_details``, and it is the only way to tell a long answer
    from a long think.
    """
    usage = obj.get("usage") or {}
    details = usage.get("completion_tokens_details") or {}
    return Usage(
        usage.get("prompt_tokens", 0),
        usage.get("completion_tokens", 0),
        details.get("reasoning_tokens", 0) or 0,
    )


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
            reasoning=reasoning_delta(delta),
            reasoning_details=accumulate_reasoning_details(delta, acc),
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
        return Completion(
            content=message.get("content"),
            tool_calls=tool_calls,
            finish_reason=choice.get("finish_reason"),
            model=obj.get("model", ""),
            usage=read_usage(obj),
            reasoning=message.get("reasoning") or message.get("reasoning_content"),
            reasoning_details=message.get("reasoning_details") or None,
        )

    # -- models --------------------------------------------------------------
    def parse_models(self, obj: dict) -> list[str]:
        return [m.get("id", "") for m in (obj.get("data") or []) if m.get("id")]

    def parse_model_reasoning(self, obj: dict) -> dict[str, "ReasoningSpec"]:
        """What each model says about its own thinking, keyed by model id.

        Read from the same response as the model list, because that is where
        OpenRouter reports it and a second request would be a second chance to
        be rate-limited.

        A model with no ``reasoning`` object is not one that thinks -- the
        dynamic routers (``openrouter/auto``) report nothing at all, which is
        the same thing as saying no and is treated that way. An empty
        ``supported_efforts`` with the object present is a model that thinks
        with no dial: it gets a spec, and no choice to make.
        """
        specs: dict[str, ReasoningSpec] = {}
        for model in obj.get("data") or []:
            model_id = model.get("id")
            if not model_id:
                continue
            reasoning = model.get("reasoning")
            if not isinstance(reasoning, dict):
                continue
            specs[model_id] = ReasoningSpec(
                efforts=list(reasoning.get("supported_efforts") or []),
                default_effort=reasoning.get("default_effort") or "",
                mandatory=bool(reasoning.get("mandatory")),
            )
        return specs

    def models_url(self, base_url: str) -> str:
        return f"{base_url.rstrip('/')}/models"


def current_tool_calls(acc: dict) -> list[dict] | None:
    buf = acc.get("buffer")
    return list(buf.values()) if buf else None


def reasoning_delta(delta: dict) -> str | None:
    """The thinking in one delta, under either of its two names.

    OpenRouter documents ``reasoning`` and carries ``reasoning_content`` as an
    alias for the same field, and in practice both appear in the wild depending
    on the upstream provider OpenRouter is proxying.
    """
    return delta.get("reasoning") or delta.get("reasoning_content") or None


def accumulate_reasoning_details(delta: dict, acc: dict) -> list[dict] | None:
    """Collect streamed ``reasoning_details`` into one list.

    The array arrives incrementally and its entries are typed -- a
    ``reasoning.text`` block that grows, then a ``reasoning.encrypted`` blob --
    so the last item is replaced by its newer version rather than appended
    twice. Appending blindly would send the same block back to the provider
    with two entries, which it rejects.
    """
    parts = delta.get("reasoning_details")
    if not parts:
        collected = acc.get("reasoning_details")
        return list(collected) if collected else None
    collected = acc.setdefault("reasoning_details", [])
    for part in parts:
        if not isinstance(part, dict):
            continue
        index = part.get("index")
        if index is None:
            collected.append(part)
            continue
        # Indices are sparse and arrive in order, so a missing slot is a gap
        # rather than a reason to renumber everything after it.
        while len(collected) <= index:
            collected.append({})
        collected[index] = part
    return list(collected)

