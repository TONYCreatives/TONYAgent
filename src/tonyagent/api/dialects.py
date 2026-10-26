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
    #: What the gateway says the request cost, in its own currency (OpenRouter
    #: bills in USD). ``None`` when it said nothing: the price of a model is a
    #: fact only the gateway has, and a local estimate would be a different
    #: number from the one on the invoice.
    cost: float | None = None

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
        _as_cost(usage),
    )


def _as_cost(usage: dict) -> float | None:
    """The gateway's own cost for the request, if it published one.

    Two names, because two shapes carry it: OpenRouter's own replies put it at
    ``usage.cost``, and some OpenAI-compatible gateways repeat it as
    ``total_cost``. Neither is invented when both are absent -- a zero would
    read as "this turn was free", which is a claim the provider did not make.
    """
    for key in ("cost", "total_cost"):
        value = usage.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
    return None


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
            # Ask for the token counts as a final chunk. Without it a streamed
            # answer reports no usage at all -- the counts are only sent when
            # they are asked for -- and the dashboard would record every
            # streamed request, which is all of them, as zero tokens.
            payload["stream_options"] = {"include_usage": True}
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
        # The usage chunk arrives last and carries no choices, so it has to be
        # read *before* the guard below drops it. It is stored rather than
        # yielded: it is not part of the answer, it is the bill for it.
        if obj.get("usage"):
            acc["usage"] = read_usage(obj)
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


class ResponsesDialect:
    """The OpenAI Responses wire format (``/responses``).

    Muse Spark (and a few other Go models) only serve this endpoint: sending
    them to ``/chat/completions`` is answered with 400 "Model does not support
    this protocol". The app keeps its neutral ``ChatMessage``/``ToolSchema``
    model everywhere above this layer, so this class translates in both
    directions and the session never learns a second shape: text and tool
    calls come out as the same :class:`Completion`/:class:`Chunk` the chat
    dialect produces.
    """

    def build_request(self, model, messages, tools=None, tool_choice=None, stream=False, **extra):
        payload: dict[str, Any] = {
            "model": model,
            "input": messages_to_responses_input(messages),
        }
        built = responses_tools(tools)
        if built:
            payload["tools"] = built
            if tool_choice:
                payload["tool_choice"] = responses_tool_choice(tool_choice)
        if stream:
            payload["stream"] = True
        payload.update(extra)
        return payload

    def url(self, base_url: str, model: str, stream: bool) -> str:
        return f"{base_url.rstrip('/')}/responses"

    def auth_headers(self, api_key: str) -> dict:
        return {"Authorization": f"Bearer {api_key}"}

    def models_url(self, base_url: str) -> str:
        return f"{base_url.rstrip('/')}/models"

    def parse_models(self, obj: dict) -> list[str]:
        return [m.get("id", "") for m in (obj.get("data") or []) if m.get("id")]

    def parse_model_reasoning(self, obj: dict) -> dict[str, "ReasoningSpec"]:
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

    def parse_completion(self, obj: dict) -> Completion:
        text, tool_calls = responses_output(obj.get("output") or [])
        usage = obj.get("usage") or {}
        return Completion(
            content=text or None,
            tool_calls=tool_calls,
            finish_reason="tool_calls" if tool_calls else "stop",
            model=obj.get("model", ""),
            usage=Usage(
                usage.get("input_tokens", 0),
                usage.get("output_tokens", 0),
            ),
        )

    def parse_stream_event(self, event: str, data: str, acc: dict) -> Chunk | None:
        if not data or data == "[DONE]":
            return None
        try:
            obj = json.loads(data)
        except ValueError:
            return None
        kind = obj.get("type") or event
        if kind == "response.output_text.delta":
            return Chunk(content=obj.get("delta"))
        if kind == "response.output_item.added":
            responses_note_item(obj.get("item") or {}, acc)
            return None
        if kind == "response.function_call_arguments.delta":
            responses_add_delta(obj, acc)
            return Chunk(tool_calls=responses_current_tool_calls(acc))
        if kind == "response.function_call_arguments.done":
            responses_finish_item(obj, acc)
            return Chunk(tool_calls=responses_current_tool_calls(acc))
        if kind == "response.output_item.done":
            item = obj.get("item") or {}
            if item.get("type") == "function_call":
                responses_note_item(item, acc, done=True)
                return Chunk(tool_calls=responses_current_tool_calls(acc))
            return None
        if kind == "response.completed":
            response = obj.get("response") or {}
            usage = response.get("usage") or {}
            if usage:
                acc["usage"] = Usage(
                    usage.get("input_tokens", 0),
                    usage.get("output_tokens", 0),
                )
            calls = responses_current_tool_calls(acc)
            if calls is None:
                _, calls = responses_output(response.get("output") or [])
            return Chunk(
                finish_reason="tool_calls" if calls else "stop",
                tool_calls=calls,
                model=response.get("model", ""),
            )
        if kind in ("response.failed", "response.incomplete", "error"):
            return Chunk(finish_reason="error")
        if obj.get("error"):
            return Chunk(finish_reason="error")
        return None


def responses_tools(tools: list[dict] | None) -> list[dict] | None:
    """Chat-shaped tools to Responses-shaped tools.

    The chat dialect carries ``{"type": "function", "function": {...}}``;
    Responses wants the inner object flattened with the type beside it.
    """
    if not tools:
        return None
    out = []
    for t in tools:
        fn = t.get("function", t)
        out.append(
            {
                "type": "function",
                "name": fn.get("name", ""),
                "description": fn.get("description", ""),
                "parameters": fn.get("parameters")
                or {"type": "object", "properties": {}},
            }
        )
    return out or None


def responses_tool_choice(choice) -> str | dict | None:
    """Chat tool-choice values to their Responses equivalents."""
    if not choice:
        return None
    value = getattr(choice, "value", choice)
    if value in ("auto", "none", "required"):
        return value
    return {"type": "function", "name": value}


def messages_to_responses_input(messages: list[dict]) -> list[dict]:
    """Neutral chat messages to a Responses ``input`` list.

    History is re-sent every turn (there is no ``previous_response_id``
    chaining), so every role the session can produce is mapped: system and
    user become input messages, assistant tool calls become ``function_call``
    items, and tool replies become ``function_call_output`` items. Anything
    unrecognised is dropped rather than guessed at: sending a malformed item
    fails the whole turn.
    """
    import json as _json

    items: list[dict] = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        role = message.get("role", "")
        content = message.get("content")
        tool_calls = message.get("tool_calls")
        if role == "tool":
            call_id = message.get("tool_call_id") or ""
            output = content if isinstance(content, str) else _json.dumps(content)
            items.append(
                {"type": "function_call_output", "call_id": call_id, "output": output or ""}
            )
            continue
        if tool_calls:
            text = content if isinstance(content, str) and content else ""
            if text:
                items.append({"role": "assistant", "content": text})
            for call in tool_calls:
                fn = (call.get("function") or {}) if isinstance(call, dict) else {}
                call_id = (call.get("id") or "") if isinstance(call, dict) else ""
                items.append(
                    {
                        "type": "function_call",
                        "call_id": call_id,
                        "name": fn.get("name", ""),
                        "arguments": fn.get("arguments", "") or "",
                    }
                )
            continue
        if role == "system":
            text = content if isinstance(content, str) else ""
            if text:
                items.append({"role": "system", "content": text})
            continue
        if role in ("user", "assistant", "developer"):
            if isinstance(content, str):
                if content:
                    items.append({"role": role, "content": content})
            elif isinstance(content, list):
                parts = chat_parts_to_responses_content(content)
                if parts:
                    items.append({"role": role, "content": parts})
            continue
    return items


def chat_parts_to_responses_content(parts: list) -> list[dict]:
    """OpenAI content parts to Responses input content parts."""
    out: list[dict] = []
    for part in parts:
        if not isinstance(part, dict):
            continue
        kind = part.get("type", "")
        if kind == "text":
            text = part.get("text", "")
            if text:
                out.append({"type": "input_text", "text": text})
        elif kind == "input_text":
            if part.get("text"):
                out.append({"type": "input_text", "text": part["text"]})
        elif kind == "image_url":
            image = part.get("image_url")
            url = image.get("url", "") if isinstance(image, dict) else part.get("url", "")
            if url:
                out.append({"type": "input_image", "image_url": url})
        elif kind == "input_image":
            if part.get("image_url"):
                out.append(part)
    return out


def responses_output(output: list) -> tuple[str, list[dict] | None]:
    """A Responses ``output`` list to (text, chat-shaped tool calls)."""
    texts: list[str] = []
    calls: list[dict] = []
    for item in output:
        if not isinstance(item, dict):
            continue
        kind = item.get("type", "")
        if kind == "message":
            for part in item.get("content") or []:
                if not isinstance(part, dict):
                    continue
                if part.get("type") == "output_text" and part.get("text"):
                    texts.append(part["text"])
                elif part.get("type") == "refusal" and part.get("refusal"):
                    texts.append(part["refusal"])
        elif kind == "function_call":
            call_id = item.get("call_id") or item.get("id") or ""
            calls.append(
                {
                    "id": call_id,
                    "type": "function",
                    "function": {
                        "name": item.get("name", ""),
                        "arguments": item.get("arguments", "") or "",
                    },
                }
            )
    return ("".join(texts), calls or None)


def responses_note_item(item: dict, acc: dict, done: bool = False) -> None:
    """Record a streamed ``function_call`` item under its id."""
    if item.get("type") != "function_call":
        return
    buf = acc.setdefault("fc", {})
    key = str(item.get("id") or item.get("call_id") or len(buf))
    slot = buf.setdefault(key, {"id": "", "call_id": "", "name": "", "arguments": ""})
    if item.get("id"):
        slot["id"] = item["id"]
    if item.get("call_id"):
        slot["call_id"] = item["call_id"]
    if item.get("name"):
        slot["name"] = item["name"]
    if done and item.get("arguments"):
        slot["arguments"] = item["arguments"]


def responses_add_delta(obj: dict, acc: dict) -> None:
    """Append one ``function_call_arguments.delta`` fragment."""
    item_id = str(obj.get("item_id") or "")
    delta = obj.get("delta") or ""
    if not item_id:
        return
    buf = acc.setdefault("fc", {})
    slot = buf.setdefault(
        item_id, {"id": item_id, "call_id": item_id, "name": "", "arguments": ""}
    )
    slot["arguments"] += delta


def responses_finish_item(obj: dict, acc: dict) -> None:
    """Finalize one function call when its ``done`` event arrives."""
    item_id = str(obj.get("item_id") or "")
    buf = acc.setdefault("fc", {})
    slot = None
    if item_id and item_id in buf:
        slot = buf[item_id]
    elif buf:
        slot = next(reversed(buf.values()))
    if slot is None:
        return
    if obj.get("arguments"):
        slot["arguments"] = obj["arguments"]
    if obj.get("name"):
        slot["name"] = obj["name"]
    if obj.get("call_id"):
        slot["call_id"] = obj["call_id"]


def responses_current_tool_calls(acc: dict) -> list[dict] | None:
    """Buffered function calls as chat-shaped tool calls, or None."""
    buf = acc.get("fc")
    if not buf:
        return None
    calls = []
    for slot in buf.values():
        if not slot.get("name") and not slot.get("arguments"):
            continue
        call_id = slot.get("call_id") or slot.get("id") or ""
        calls.append(
            {
                "id": call_id,
                "type": "function",
                "function": {
                    "name": slot.get("name", ""),
                    "arguments": slot.get("arguments", "") or "",
                },
            }
        )
    return calls or None


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

