"""Tests for the rewritten LLM API layer (tonyagent.api)."""

from __future__ import annotations

import json

import pytest

from tonyagent.api import Dialect, LLMClient, get_dialect, normalize_key
from tonyagent.api.dialects import Chunk
from tonyagent.api.errors import ErrorKind, KeyFormatError, KeyLengthError, LLMError


def test_normalize_key_strips_copy_paste_junk():
    """A trailing newline must not be stored or sent."""
    assert normalize_key("  sk-or-v1-abc\n") == "sk-or-v1-abc"
    assert normalize_key('"sk-or-v1-abc"') == "sk-or-v1-abc"
    assert normalize_key("'sk-or-v1-abc'") == "sk-or-v1-abc"
    assert normalize_key("  plain  ") == "plain"
    assert normalize_key(None) == ""
    assert normalize_key("") == ""


def test_truncated_openrouter_key_is_caught_locally():
    """Regression: the real 35-character key reached the network as a 401.

    It had the correct prefix and was long enough for the old 20-character
    floor, so the only defence left is an exact length check.
    """
    truncated = "sk-or-v1-" + "a" * 26  # 35 chars, the value actually stored
    c = LLMClient("openrouter", truncated, "m", "https://openrouter.ai/api/v1",
                  key_prefix="sk-or-", key_length=73)
    with pytest.raises(KeyLengthError) as exc:
        c.check_key()
    assert exc.value.kind is ErrorKind.AUTH
    assert "35 characters" in exc.value.message
    assert "73" in exc.value.message
    # The hint must name the actual fix, not just "invalid key".
    assert "cut short" in exc.value.hint


def test_correct_length_key_passes():
    c = LLMClient("openrouter", "sk-or-v1-" + "a" * 64, "m",
                  "https://openrouter.ai/api/v1", key_prefix="sk-or-", key_length=73)
    c.check_key()  # must not raise


def test_truncated_key_is_normalised_before_measuring():
    """Whitespace must not change the verdict, and must not fake a match."""
    padded = "  sk-or-v1-" + "a" * 64 + "\n"
    c = LLMClient("openrouter", padded, "m", "https://openrouter.ai/api/v1",
                  key_prefix="sk-or-", key_length=73)
    c.check_key()  # trailing newline cleaned, so the 73 check still holds


def test_overlong_key_is_rejected():
    """A key with a trailing copy artefact must not slip through."""
    c = LLMClient("openrouter", "sk-or-v1-" + "a" * 64 + "X", "m",
                  "https://openrouter.ai/api/v1", key_prefix="sk-or-", key_length=73)
    with pytest.raises(KeyLengthError):
        c.check_key()


def test_provider_declares_openrouter_key_length():
    """The provider must pass its exact length down to the client."""
    from tonyagent.providers.openrouter import OpenRouterProvider

    p = OpenRouterProvider(api_key="sk-or-v1-" + "a" * 26, model="m")
    assert p.http_client().key_length == 73
    assert p.validate_credentials() is False

    good = OpenRouterProvider(api_key="sk-or-v1-" + "a" * 64, model="m")
    assert good.validate_credentials() is True


def test_validate_credentials_rejects_truncated_key():
    from tonyagent.providers.openrouter import OpenRouterProvider

    p = OpenRouterProvider(api_key="sk-or-v1-" + "a" * 26, model="m")
    assert p.validate_credentials() is False, "a truncated key must not validate"


# --- model id validation ----------------------------------------------------
def test_widget_class_names_are_not_valid_model_ids():
    """Regression: "CTkComboBox is not a valid model ID" came back from the API.

    An unset customtkinter combo box reports its own class name from get(),
    and that string was used as the model id.
    """
    from tonyagent.providers.factory import ProviderFactory

    for bad in ("CTkComboBox", "PillComboBox", "CTkOptionMenu", ".!pillcombobox", "has space"):
        assert ProviderFactory._is_valid_model_id(bad) is False, bad


def test_real_model_ids_pass_validation():
    from tonyagent.providers.factory import ProviderFactory

    for good in (
        "openai/gpt-4o-mini",
        "anthropic/claude-sonnet-4.6",
        "gemini-1.5-pro",
        "llama3.1",
        "o1",
        "",
    ):
        assert ProviderFactory._is_valid_model_id(good) is True, good


def test_factory_never_passes_a_widget_name_as_the_model():
    """The factory must fall back to the default, not forward a bad value."""
    from tonyagent.providers.factory import ProviderFactory

    prov = ProviderFactory.create_provider("openrouter", model="CTkComboBox")
    assert prov is not None
    assert prov.model != "CTkComboBox"
    assert "CTkComboBox" not in str(prov.model)


# --- key validation (the bug that caused the 401 confusion) -------------------

def test_truncated_key_is_rejected_locally():
    """A cut-short key looks fine until the provider rejects it. Catch it first."""
    c = LLMClient("openrouter", "sk-or-v1-abc", "m", "https://openrouter.ai/api/v1",
                  key_prefix="sk-or-")
    with pytest.raises(KeyFormatError) as exc:
        c.check_key()
    assert "too short" in str(exc.value)


def test_wrong_prefix_is_rejected():
    c = LLMClient("openrouter", "sk-proj-" + "a" * 60, "m", "https://openrouter.ai/api/v1",
                  key_prefix="sk-or-")
    with pytest.raises(LLMError) as exc:
        c.check_key()
    assert exc.value.kind is ErrorKind.AUTH


def test_valid_key_passes():
    c = LLMClient("openrouter", "sk-or-v1-" + "a" * 64, "m", "https://openrouter.ai/api/v1",
                  key_prefix="sk-or-")
    c.check_key()  # must not raise


def test_missing_key_is_a_config_error():
    c = LLMClient("openrouter", "", "m", "https://openrouter.ai/api/v1", key_prefix="sk-or-")
    with pytest.raises(LLMError) as exc:
        c.check_key()
    assert exc.value.kind is ErrorKind.CONFIG


def test_ollama_needs_no_key_shape_check():
    c = LLMClient("ollama", "", "llama3.1", "http://localhost:11434/v1", key_prefix="")
    # Empty prefix means "any key is fine", so this must NOT raise a format error.
    with pytest.raises(LLMError) as exc:
        c.check_key()
    assert exc.value.kind is ErrorKind.CONFIG  # missing, not malformed


# --- error classification ----------------------------------------------------

@pytest.mark.parametrize("status,kind", [
    (401, ErrorKind.AUTH), (403, ErrorKind.AUTH), (429, ErrorKind.RATE_LIMIT),
    (404, ErrorKind.NOT_FOUND), (400, ErrorKind.BAD_REQUEST), (500, ErrorKind.SERVER),
])
def test_http_status_maps_to_a_kind(status, kind):
    err = LLMError.from_response(status, '{"error":{"message":"nope"}}', "openrouter")
    assert err.kind is kind
    assert err.user_message()


def test_openrouter_error_body_is_understood():
    body = '{"error":{"message":"User not found.","code":401}}'
    err = LLMError.from_response(401, body, "openrouter")
    assert "User not found." in err.message
    assert "truncated" in err.hint.lower()


# --- dialect wire translation -------------------------------------------------

def test_openai_dialect_builds_the_expected_request():
    d = get_dialect("openai")
    payload = d.build_request("gpt-4o", [{"role": "user", "content": "hi"}],
                              tools=[{"name": "read_file", "description": "r",
                                      "parameters": {"type": "object"}}],
                              tool_choice="auto", stream=True)
    assert payload["model"] == "gpt-4o"
    assert payload["stream"] is True
    assert payload["tools"][0]["function"]["name"] == "read_file"
    assert payload["tool_choice"] == "auto"


def test_anthropic_dialect_splits_system_out():
    d = get_dialect("anthropic")
    payload = d.build_request("claude", [
        {"role": "system", "content": "be nice"},
        {"role": "user", "content": "hi"},
    ])
    assert payload["system"] == "be nice"
    assert all(m["role"] != "system" for m in payload["messages"])
    assert "max_tokens" in payload


def test_gemini_dialect_uses_content_parts():
    d = get_dialect("gemini")
    payload = d.build_request("gemini-1.5-pro", [{"role": "user", "content": "hi"}])
    assert payload["contents"][0]["parts"][0]["text"] == "hi"
    assert "gemini-1.5-pro" in d.url("https://x/v1beta", "gemini-1.5-pro", False)


def test_tool_call_fragments_are_reassembled():
    d = get_dialect("openai")
    acc: dict = {}
    d.parse_stream_event("", json.dumps({"choices": [{"delta": {"tool_calls": [
        {"index": 0, "id": "c1", "function": {"name": "read_file", "arguments": "{\"p"}}]}}]}), acc)
    d.parse_stream_event("", json.dumps({"choices": [{"delta": {"tool_calls": [
        {"index": 0, "function": {"arguments": "ath\": \"x\"}"}}]}}]}), acc)
    chunk = d.parse_stream_event("", json.dumps({"choices": [{"delta": {}}]}), acc)
    assert chunk.tool_calls[0]["function"]["name"] == "read_file"
    assert json.loads(chunk.tool_calls[0]["function"]["arguments"]) == {"path": "x"}


def test_streaming_yields_content_chunks():
    d = get_dialect("openai")
    acc: dict = {}
    for piece in ("Hel", "lo"):
        obj = {"choices": [{"delta": {"content": piece}}], "model": "m"}
        c = d.parse_stream_event("", json.dumps(obj), acc)
        assert c.content == piece


def test_anthropic_stream_events():
    d = get_dialect("anthropic")
    acc: dict = {}
    c = d.parse_stream_event("content_block_delta", json.dumps(
        {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "hi"}}), acc)
    assert c.content == "hi"


def test_gemini_stream_events():
    d = get_dialect("gemini")
    acc: dict = {}
    c = d.parse_stream_event("", json.dumps(
        {"candidates": [{"content": {"parts": [{"text": "hi"}]}}]}), acc)
    assert c.content == "hi"


def test_completion_parsing_openai():
    d = get_dialect("openai")
    comp = d.parse_completion({"choices": [{"message": {"content": "hi"},
                                            "finish_reason": "stop"}],
                               "usage": {"prompt_tokens": 5, "completion_tokens": 3}})
    assert comp.content == "hi"
    assert comp.usage.total == 8


# --- provider wiring ----------------------------------------------------------

@pytest.mark.parametrize("name,prefix,dialect", [
    ("openai", "sk-", "openai"), ("openrouter", "sk-or-", "openai"),
    ("anthropic", "sk-ant-", "anthropic"), ("gemini", "AIza", "gemini"),
    ("groq", "gsk_", "openai"), ("ollama", "", "openai"),
])
def test_every_provider_has_a_prefix_and_dialect(name, prefix, dialect):
    import tonyagent.providers  # noqa: F401
    from tonyagent.providers.base import provider_registry

    cls = provider_registry.get(name)
    assert cls is not None, name
    assert getattr(cls, "key_prefix", None) == prefix, name
    assert get_dialect(getattr(cls, "dialect", "openai")).name == dialect


def test_no_provider_delegates_to_an_abstract_stub():
    """The bug that made five providers silently return None."""
    from tonyagent.providers.base import OpenAICompatibleProvider, provider_registry
    import tonyagent.providers  # noqa: F401

    assert "chat_completion" in OpenAICompatibleProvider.__dict__
    for name in ("openai", "openrouter", "groq", "mistral", "custom",
                 "anthropic", "gemini", "ollama"):
        cls = provider_registry.get(name)
        owner = next(c for c in cls.__mro__ if "chat_completion" in c.__dict__)
        assert owner is OpenAICompatibleProvider, f"{name} -> {owner.__name__}"


def test_providers_expose_a_real_health_check():
    from tonyagent.providers.base import provider_registry
    import tonyagent.providers  # noqa: F401

    for name in ("openrouter", "openai", "anthropic", "gemini"):
        cls = provider_registry.get(name)
        assert hasattr(cls, "check_connection"), name
        assert hasattr(cls, "fetch_models"), name
