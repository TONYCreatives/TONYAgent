"""Base provider protocol and types for TONYAgent."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Protocol
from enum import Enum

from tonyagent.api import LLMClient, MIN_KEY_LENGTH, get_dialect, normalize_key
from tonyagent.config.keyring import load_api_key


class MessageRole(str, Enum):
    """Message roles for chat."""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


@dataclass
class ChatMessage:
    """A chat message.

    ``role`` accepts either a :class:`MessageRole` or its plain string value.
    The UI constructs messages with ``role="user"`` / ``role="assistant"`` /
    ``role="tool"``, so normalising here keeps callers from having to remember
    which form is expected (it previously raised
    "'str' object has no attribute 'value'" on the first API call).
    """

    role: MessageRole | str
    content: str | None = None
    tool_calls: list[dict] | None = None
    tool_call_id: str | None = None
    name: str | None = None

    def __post_init__(self) -> None:
        # Accept "user" as well as MessageRole.USER.
        if isinstance(self.role, str):
            self.role = MessageRole(self.role)

    @property
    def role_value(self) -> str:
        """The role as a plain string, whatever form it was given in."""
        return self.role.value if isinstance(self.role, MessageRole) else str(self.role)

    def to_dict(self) -> dict:
        """Convert to dictionary for API."""
        result = {"role": self.role_value}
        if self.content is not None:
            result["content"] = self.content
        if self.tool_calls:
            result["tool_calls"] = self.tool_calls
        if self.tool_call_id:
            result["tool_call_id"] = self.tool_call_id
        if self.name:
            result["name"] = self.name
        return result

    @classmethod
    def from_dict(cls, data: dict) -> ChatMessage:
        """Create from dictionary."""
        return cls(
            role=MessageRole(data["role"]),
            content=data.get("content"),
            tool_calls=data.get("tool_calls"),
            tool_call_id=data.get("tool_call_id"),
            name=data.get("name"),
        )
@dataclass
class ToolSchema:
    """JSON schema for a tool/function."""

    name: str
    description: str
    parameters: dict[str, Any]
    required: list[str] = field(default_factory=list)

    @classmethod
    def from_tool_schema_dict(cls, schema: dict[str, Any]) -> "ToolSchema":
        """Build from an ALL_SCHEMAS entry.

        Those dicts carry UI-only metadata (``category``, ``destructive``,
        ``requires_confirmation``, ``sandbox_required``) that this dataclass does
        not declare, so a bare ``ToolSchema(**schema)`` raised
        "unexpected keyword argument 'category'" and every chat turn failed
        before the request was ever sent.
        """
        parameters = schema.get("parameters") or {}
        return cls(
            name=schema.get("name", ""),
            description=schema.get("description", ""),
            parameters=parameters,
            required=list(parameters.get("required", []) or []),
        )

    def to_openai_format(self) -> dict:
        """Convert to OpenAI function format."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": self.parameters,
                    "required": self.required,
                    "additionalProperties": False,
                },
            },
        }


class ToolChoice(str, Enum):
    """Tool choice options."""

    NONE = "none"
    AUTO = "auto"
    REQUIRED = "required"


@dataclass
class ChatCompletionChunk:
    """A chunk of a streaming chat completion."""

    content: str | None = None
    tool_calls: list[dict] | None = None
    finish_reason: str | None = None
    model: str | None = None
    usage: dict | None = None


@dataclass
class ChatCompletion:
    """A complete chat completion response."""

    content: str | None = None
    tool_calls: list[dict] | None = None
    finish_reason: str | None = None
    model: str | None = None
    usage: dict | None = None


class LLMProvider(Protocol):
    """Protocol for LLM providers."""

    name: str
    models: list[str]
    supports_streaming: bool
    supports_function_calling: bool

    @abstractmethod
    async def chat_completion(
        self,
        messages: list[ChatMessage],
        tools: list[ToolSchema] | None = None,
        tool_choice: ToolChoice | None = None,
        stream: bool = False,
        **kwargs
    ) -> AsyncIterator[ChatCompletionChunk] | ChatCompletion:
        """Generate a chat completion."""
        ...

    @abstractmethod
    def validate_credentials(self) -> bool:
        """Validate API credentials."""
        ...

    @abstractmethod
    def estimate_tokens(self, messages: list[ChatMessage]) -> int:
        """Estimate token count for messages."""
        ...


class BaseLLMProvider(ABC):
    """Base class for LLM providers."""

    name: str = ""
    models: list[str] = []
    supports_streaming: bool = True
    supports_function_calling: bool = True

    def __init__(
        self,
        api_key: str = "",
        model: str = "",
        base_url: str = "",
        extra_headers: dict[str, str] | None = None,
        timeout: int = 60,
        max_retries: int = 3,
    ):
        self.api_key = api_key
        self.model = model
        self.base_url = base_url
        self.extra_headers = extra_headers or {}
        self.timeout = timeout
        self.max_retries = max_retries

    @abstractmethod
    async def chat_completion(
        self,
        messages: list[ChatMessage],
        tools: list[ToolSchema] | None = None,
        tool_choice: ToolChoice | None = None,
        stream: bool = False,
        **kwargs
    ) -> AsyncIterator[ChatCompletionChunk] | ChatCompletion:
        """Generate a chat completion."""
        ...

    @abstractmethod
    def validate_credentials(self) -> bool:
        """Validate API credentials."""
        ...

    def estimate_tokens(self, messages: list[ChatMessage]) -> int:
        """Estimate token count (rough approximation)."""
        total_chars = sum(len(m.content or "") for m in messages)
        return total_chars // 4
class OpenAICompatibleProvider(BaseLLMProvider):
    """Base class for OpenAI-compatible providers."""

    def _get_headers(self) -> dict[str, str]:
        headers = {"Authorization": f"Bearer {self.api_key}"}
        headers.update(self.extra_headers)
        return headers

    def _get_base_url(self) -> str:
        return self.base_url or "https://api.openai.com/v1"

    def _build_messages(self, messages: list[ChatMessage]) -> list[dict]:
        return [m.to_dict() for m in messages]

    def _build_tools(self, tools: list[ToolSchema] | None) -> list[dict] | None:
        if not tools:
            return None
        return [t.to_openai_format() for t in tools]

    def _build_tool_choice(self, tool_choice: ToolChoice | None) -> str | dict | None:
        if not tool_choice:
            return None
        if tool_choice == ToolChoice.AUTO:
            return "auto"
        if tool_choice == ToolChoice.REQUIRED:
            return "required"
        if tool_choice == ToolChoice.NONE:
            return "none"
        return {"type": "function", "function": {"name": tool_choice.value}}

    # --- OpenAI-compatible transport (shared by every OpenAI-style gateway) ---
    #
    # The wire logic lives in tonyagent.api now. Keeping it here means the
    # provider classes stay thin config, and there is exactly ONE streaming
    # implementation instead of one per provider subclass (which is how five of
    # them came to silently return None).

    def http_client(self) -> "LLMClient":
        if getattr(self, "_http", None) is None:
            self._http = LLMClient(
                provider=self.name,
                api_key=self.api_key or load_api_key(self.name) or "",
                model=self.model,
                base_url=self.base_url,
                dialect=get_dialect(getattr(self, "dialect", "openai")),
                timeout=self.timeout,
                extra_headers=self.extra_headers,
                key_prefix=getattr(self, "key_prefix", None),
                key_length=getattr(self, "key_length", None),
            )
        return self._http

    async def chat_completion(
        self,
        messages: list[ChatMessage],
        tools: list[ToolSchema] | None = None,
        tool_choice: ToolChoice | None = None,
        stream: bool = False,
        **kwargs,
    ) -> AsyncIterator[ChatCompletionChunk] | ChatCompletion:
        client = self.http_client()
        client.model = self.model  # follow later model changes
        api_messages = [m.to_dict() for m in messages]
        api_tools = self._build_tools(tools)
        choice = self._build_tool_choice(tool_choice)
        if stream:
            return self._stream_as_chunks(client, api_messages, api_tools, choice, **kwargs)
        return await self._complete(client, api_messages, api_tools, choice, **kwargs)

    async def _complete(self, client, messages, tools, tool_choice, **kwargs) -> ChatCompletion:
        result = await client.complete(messages, tools, tool_choice, **kwargs)
        return ChatCompletion(
            content=result.content,
            tool_calls=result.tool_calls,
            finish_reason=result.finish_reason,
            model=result.model or self.model,
            usage=result.usage.total or None,
        )

    async def _stream_as_chunks(self, client, messages, tools, tool_choice, **kwargs):
        async for chunk in client.stream(messages, tools, tool_choice, **kwargs):
            yield ChatCompletionChunk(
                content=chunk.content,
                tool_calls=chunk.tool_calls,
                finish_reason=chunk.finish_reason,
                model=chunk.model or self.model,
            )
            if chunk.finish_reason:
                break

    async def check_connection(self):
        """Real round-trip health check (was: a startswith() string test)."""
        return await self.http_client().check()

    async def fetch_models(self) -> list[str]:
        return await self.http_client().list_models()

    def validate_credentials(self) -> bool:
        """Local shape check only. Use ``check_connection`` for a real test."""
        key = normalize_key(self.api_key or load_api_key(self.name) or "")
        if not key:
            return False
        prefix = getattr(self, "key_prefix", "")
        if prefix and not key.startswith(prefix):
            return False
        # An empty prefix means "any key is fine" (Ollama, custom endpoints),
        # so only apply length rules to providers that expect a real key.
        if not prefix:
            return True
        # Exact length when the provider declares one. A 35-character key with
        # the right prefix is still broken, and this is the only place that
        # knows it before a request is spent.
        expected = getattr(self, "key_length", None)
        if expected:
            return len(key) == expected
        return len(key) >= MIN_KEY_LENGTH


class ProviderRegistry:
    """Registry for LLM providers."""

    def __init__(self):
        self._providers: dict[str, type[BaseLLMProvider]] = {}

    def register(self, provider_class: type[BaseLLMProvider]) -> type[BaseLLMProvider]:
        """Register a provider class."""
        if not provider_class.name:
            raise ValueError("Provider must have a name")
        self._providers[provider_class.name] = provider_class
        return provider_class

    def get(self, name: str) -> type[BaseLLMProvider] | None:
        """Get a provider class by name."""
        return self._providers.get(name)

    def create(
        self,
        name: str,
        api_key: str = "",
        model: str = "",
        **kwargs
    ) -> BaseLLMProvider | None:
        """Create a provider instance.

        An empty ``model`` is *omitted* rather than passed as ``""``. Every
        provider but ``custom`` declares a sensible default in its constructor
        (openrouter -> ``openrouter/auto``, openai -> ``gpt-4o-mini``, ...), and
        passing the empty string explicitly clobbered it: the request then went
        out with no model at all and the provider answered "No models
        provided". Omitting the keyword lets the class default stand.
        """
        provider_class = self.get(name)
        if not provider_class:
            return None
        if model:
            return provider_class(api_key=api_key, model=model, **kwargs)
        return provider_class(api_key=api_key, **kwargs)

    def list_providers(self) -> list[str]:
        """List all registered provider names."""
        return list(self._providers.keys())

    def get_models(self, name: str) -> list[str]:
        """Get available models for a provider."""
        provider_class = self.get(name)
        if not provider_class:
            return []
        return provider_class.models


# Global registry instance
provider_registry = ProviderRegistry()


def register_provider(provider_class: type[BaseLLMProvider]) -> type[BaseLLMProvider]:
    """Decorator to register a provider."""
    return provider_registry.register(provider_class)
