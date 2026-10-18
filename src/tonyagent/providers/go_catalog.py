"""Curated facts for OpenCode Go models.

Go's `/models` endpoint answers with bare ids only -- no names, no context
sizes, no modalities -- so a picker built from the wire alone can say nothing
beside each id. These facts fill that gap: display name, wire protocol,
context window, max output tokens and input modalities per model id.

**Source and freshness.** Extracted 2026-10-18 from the model catalog shipped
inside the DeepSeek Harness desktop app (which carries the same per-model
facts for the same gateway) and cross-checked against OpenCode's own endpoint
tables, where Muse Spark / GPT Luna / Grok serve `/responses`, MiniMax M3 and
the Qwen entries serve Anthropic `/messages`, and the rest serve
`/chat/completions`. Numbers go stale -- a context window can be raised
without notice -- so this file is enrichment, never authority: the live
`/models` reply decides which ids exist, and an id missing here still lists,
with zeros where a fact would be. The one field that must never be guessed
from here is price, which is why there is none: a stale token count
under-reports a window, but a stale price misquotes money.
"""

from __future__ import annotations

#: Protocol each model serves: "chat" (`/chat/completions`), "responses"
#: (`/responses`), or "messages" (Anthropic `/messages`, which this app does
#: not speak -- listed so the picker can say so instead of failing at send).
GO_MODEL_FACTS: dict[str, dict] = {
    "claude-haiku-5-5": {
        "name": "Claude Haiku 5.5",
        "protocol": "messages",
        "context_window": 1000000,
        "max_tokens": 128000,
        "input_modalities": ["text", "image"],
        "supports_reasoning": True,
    },
    "deepseek-v4-flash": {
        "name": "DeepSeek V4 Flash",
        "protocol": "chat",
        "context_window": 1000000,
        "max_tokens": 384000,
        "input_modalities": ["text"],
        "supports_reasoning": True,
    },
    "deepseek-v4-flash-vision-exp": {
        "name": "DeepSeek V4 Flash Vision Exp",
        "protocol": "chat",
        "context_window": 1000000,
        "max_tokens": 384000,
        "input_modalities": ["text", "image"],
        "supports_reasoning": True,
    },
    "deepseek-v4-pro": {
        "name": "DeepSeek V4 Pro",
        "protocol": "chat",
        "context_window": 1000000,
        "max_tokens": 384000,
        "input_modalities": ["text"],
        "supports_reasoning": True,
    },
    "deepseek-v4.1-flash": {
        "name": "DeepSeek V4.1 Flash",
        "protocol": "chat",
        "context_window": 1000000,
        "max_tokens": 384000,
        "input_modalities": ["text", "image"],
        "supports_reasoning": True,
    },
    "glm-5.2": {
        "name": "GLM-5.2",
        "protocol": "chat",
        "context_window": 1000000,
        "max_tokens": 131072,
        "input_modalities": ["text"],
        "supports_reasoning": True,
    },
    "glm-5.3": {
        "name": "GLM-5.3",
        "protocol": "chat",
        "context_window": 1000000,
        "max_tokens": 131072,
        "input_modalities": ["text"],
        "supports_reasoning": True,
    },
    "glm-5.3-flash": {
        "name": "GLM-5.3-Flash",
        "protocol": "chat",
        "context_window": 1000000,
        "max_tokens": 131072,
        "input_modalities": ["text", "image"],
        "supports_reasoning": True,
    },
    "gpt-5.6-luna": {
        "name": "GPT-5.6 Luna",
        "protocol": "responses",
        "context_window": 1050000,
        "max_tokens": 128000,
        "input_modalities": ["text", "image"],
        "supports_reasoning": True,
    },
    "gpt-6-luna": {
        "name": "GPT-6 Luna",
        "protocol": "responses",
        "context_window": 1050000,
        "max_tokens": 128000,
        "input_modalities": ["text", "image"],
        "supports_reasoning": True,
    },
    "grok-4.6": {
        "name": "Grok 4.6",
        "protocol": "responses",
        "context_window": 500000,
        "max_tokens": 500000,
        "input_modalities": ["text", "image"],
        "supports_reasoning": True,
    },
    "grok-4.7": {
        "name": "Grok 4.7",
        "protocol": "responses",
        "context_window": 500000,
        "max_tokens": 500000,
        "input_modalities": ["text", "image"],
        "supports_reasoning": True,
    },
    "hy3": {
        "name": "Hy3",
        "protocol": "chat",
        "context_window": 256000,
        "max_tokens": 128000,
        "input_modalities": ["text"],
        "supports_reasoning": True,
    },
    "hy4-preview": {
        "name": "Hy4 preview",
        "protocol": "chat",
        "context_window": 1024000,
        "max_tokens": 64000,
        "input_modalities": ["text"],
        "supports_reasoning": True,
    },
    "kimi-k2.7-code": {
        "name": "Kimi K2.7 Code",
        "protocol": "chat",
        "context_window": 262144,
        "max_tokens": 262144,
        "input_modalities": ["text", "image"],
        "supports_reasoning": True,
    },
    "kimi-k3": {
        "name": "Kimi K3",
        "protocol": "chat",
        "context_window": 1048576,
        "max_tokens": 131072,
        "input_modalities": ["text", "image"],
        "supports_reasoning": True,
    },
    "longcat-2.0": {
        "name": "LongCat-2.0",
        "protocol": "chat",
        "context_window": 1000000,
        "max_tokens": 131072,
        "input_modalities": ["text"],
        "supports_reasoning": True,
    },
    "longcat-2.5-preview-free": {
        "name": "LongCat 2.5 Preview Free",
        "protocol": "chat",
        "context_window": 1000000,
        "max_tokens": 131072,
        "input_modalities": ["text", "image"],
        "supports_reasoning": True,
    },
    "mimo-v2.5": {
        "name": "MiMo V2.5",
        "protocol": "chat",
        "context_window": 1000000,
        "max_tokens": 128000,
        "input_modalities": ["text", "image"],
        "supports_reasoning": True,
    },
    "mimo-v2.5-pro": {
        "name": "MiMo V2.5 Pro",
        "protocol": "chat",
        "context_window": 1048576,
        "max_tokens": 128000,
        "input_modalities": ["text"],
        "supports_reasoning": True,
    },
    "mimo-v2.6-flash": {
        "name": "MiMo-V2.6-Flash",
        "protocol": "chat",
        "context_window": 1048576,
        "max_tokens": 131072,
        "input_modalities": ["text", "image"],
        "supports_reasoning": True,
    },
    "mimo-v2.6-pro": {
        "name": "MiMo-V2.6-Pro",
        "protocol": "chat",
        "context_window": 1048576,
        "max_tokens": 131072,
        "input_modalities": ["text", "image"],
        "supports_reasoning": True,
    },
    "minimax-m2.7": {
        "name": "MiniMax-M2.7",
        "protocol": "chat",
        "context_window": 204800,
        "max_tokens": 131072,
        "input_modalities": ["text"],
        "supports_reasoning": True,
    },
    "minimax-m3": {
        "name": "MiniMax-M3",
        "protocol": "messages",
        "context_window": 1000000,
        "max_tokens": 131072,
        "input_modalities": ["text", "image"],
        "supports_reasoning": True,
    },
    "muse-spark-1.2-contributor": {
        "name": "Muse Spark 1.2 Contributor",
        "protocol": "responses",
        "context_window": 1048576,
        "max_tokens": 131072,
        "input_modalities": ["text", "image"],
        "supports_reasoning": True,
    },
    "muse-spark-1.3-contributor": {
        "name": "Muse Spark 1.3 Contributor",
        "protocol": "responses",
        "context_window": 1048576,
        "max_tokens": 131072,
        "input_modalities": ["text", "image"],
        "supports_reasoning": True,
    },
    "qwen3.7-plus": {
        "name": "Qwen3.7 Plus",
        "protocol": "messages",
        "context_window": 1000000,
        "max_tokens": 65536,
        "input_modalities": ["text", "image"],
        "supports_reasoning": True,
    },
    "qwen3.8-flash": {
        "name": "Qwen3.8 Flash",
        "protocol": "messages",
        "context_window": 1000000,
        "max_tokens": 131072,
        "input_modalities": ["text", "image"],
        "supports_reasoning": True,
    },
    "qwen3.8-max": {
        "name": "Qwen3.8 Max",
        "protocol": "messages",
        "context_window": 1000000,
        "max_tokens": 131072,
        "input_modalities": ["text", "image"],
        "supports_reasoning": True,
    },
    "space-bunny": {
        "name": "Space Bunny",
        "protocol": "chat",
        "context_window": 1048576,
        "max_tokens": 524288,
        "input_modalities": ["text", "image"],
        "supports_reasoning": True,
    },
}
