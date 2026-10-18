"""Tests for the rewritten LLM API layer (tonyagent.api)."""

from __future__ import annotations

import json

import pytest

from tonyagent.api import Dialect, LLMClient, normalize_key
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
    """Regression: widget class names must not be valid model IDs.

    An unset combo box reports its own class name from get(),
    and that string must never be used as the model id.
    """
    from tonyagent.providers.factory import ProviderFactory

    for bad in ("CTkComboBox", "PillComboBox", "CTkOptionMenu", ".!pillcombobox", "has space"):
        assert ProviderFactory._is_valid_model_id(bad) is False, bad


def test_real_model_ids_pass_validation():
    from tonyagent.providers.factory import ProviderFactory

    for good in (
        "openai/gpt-4o-mini",
        "anthropic/claude-sonnet-4.5",
        "google/gemini-2.5-pro",
        "deepseek/deepseek-r1:free",
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


def test_an_omitted_model_falls_back_to_the_provider_default():
    """Regression: an empty model was sent as-is and the API answered
    "No models provided".

    Binding a provider without choosing a model must use the provider's own
    default, not an empty string.
    """
    from tonyagent.providers.factory import ProviderFactory

    prov = ProviderFactory.create_provider("openrouter", model="")
    assert prov is not None
    assert prov.model == "openrouter/auto"


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


async def test_the_model_list_needs_a_key_before_it_needs_a_socket():
    """**This path forgot the guard the other two take.**

    `auth_headers` spells the key into `Authorization: Bearer <key>`, so with no
    key it builds `Bearer ` -- and httpx refuses that with "Illegal header value
    b'Bearer '", which names neither the provider nor the missing key. The window
    showed exactly that sentence, and twice, because the session wrapped the
    client's own error in a second "Could not reach the provider".

    `complete` and `stream` both call `check_key` before they touch the network;
    `_fetch_model_entries` was the one that went without, so the model menu --
    the first thing a user opens after pasting a key -- was where a key problem
    arrived as a protocol error. Asserted on the kind and the wording, because
    "it raised something" is true of the wrong answer too.
    """
    c = LLMClient("openrouter", "", "m", "https://openrouter.ai/api/v1", key_prefix="sk-or-")

    with pytest.raises(LLMError) as raised:
        await c.list_models()

    assert raised.value.kind is ErrorKind.CONFIG
    assert "no api key" in raised.value.message.lower()
    assert "openrouter" in raised.value.message
    # And the hint is the fix, not a guess about the network.
    assert "keyring" in raised.value.user_message().lower()


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

def test_the_dialect_builds_the_expected_request():
    d = Dialect()
    payload = d.build_request("gpt-4o", [{"role": "user", "content": "hi"}],
                              tools=[{"name": "read_file", "description": "r",
                                      "parameters": {"type": "object"}}],
                              tool_choice="auto", stream=True)
    assert payload["model"] == "gpt-4o"
    assert payload["stream"] is True
    assert payload["tools"][0]["function"]["name"] == "read_file"
    assert payload["tool_choice"] == "auto"


def test_tool_call_fragments_are_reassembled():
    d = Dialect()
    acc: dict = {}
    d.parse_stream_event("", json.dumps({"choices": [{"delta": {"tool_calls": [
        {"index": 0, "id": "c1", "function": {"name": "read_file", "arguments": "{\"p"}}]}}]}), acc)
    d.parse_stream_event("", json.dumps({"choices": [{"delta": {"tool_calls": [
        {"index": 0, "function": {"arguments": "ath\": \"x\"}"}}]}}]}), acc)
    chunk = d.parse_stream_event("", json.dumps({"choices": [{"delta": {}}]}), acc)
    assert chunk.tool_calls[0]["function"]["name"] == "read_file"
    assert json.loads(chunk.tool_calls[0]["function"]["arguments"]) == {"path": "x"}


def test_streaming_yields_content_chunks():
    d = Dialect()
    acc: dict = {}
    for piece in ("Hel", "lo"):
        obj = {"choices": [{"delta": {"content": piece}}], "model": "m"}
        c = d.parse_stream_event("", json.dumps(obj), acc)
        assert c.content == piece


def test_completion_parsing():
    d = Dialect()
    comp = d.parse_completion({"choices": [{"message": {"content": "hi"},
                                            "finish_reason": "stop"}],
                               "usage": {"prompt_tokens": 5, "completion_tokens": 3}})
    assert comp.content == "hi"
    assert comp.usage.total == 8


# --- provider wiring ----------------------------------------------------------

def test_the_registry_is_exactly_these_providers():
    """Naming them is how one gets added without anyone deciding it should.

    This has said `["openrouter"]` (single-provider on purpose), then six, and
    now two. The two are the point: both are aggregators that publish model
    metadata, so the catalogue work has one shape rather than one per vendor.

    An endpoint is required of every provider. A seed model list is not --
    OpenCode Go publishes its ids only behind its own `/models`, so asserting a
    non-empty list would be asserting that someone guessed them.
    """
    import tonyagent.providers  # noqa: F401
    from tonyagent.providers.base import provider_registry

    assert provider_registry.list_providers() == [
        "opencode-go",
        "opencode-zen",
        "openrouter",
    ]
    for name in provider_registry.list_providers():
        cls = provider_registry.get(name)
        assert cls.base_url.startswith("https://"), f"{name} declares no endpoint"


def test_zen_and_go_are_separate_services_not_one_provider_twice():
    """Two base URLs, two keys, two bills -- so they must not collapse.

    Zen is not Go with a different path. Measured: Go's `/models` answers with
    37 ids and Zen's with 86, and a Go subscription key authenticates against
    Zen and is then refused with `402 Insufficient account funds`, because the
    balance lives on the Zen account. Registering Zen as another `base_url` on
    the Go provider would have hidden that behind one row in the picker.
    """
    import tonyagent.providers  # noqa: F401
    from tonyagent.providers.base import provider_registry

    go = provider_registry.get("opencode-go")
    zen = provider_registry.get("opencode-zen")
    assert go.base_url != zen.base_url
    assert zen.base_url == "https://opencode.ai/zen/v1"
    assert go.base_url == "https://opencode.ai/zen/go/v1"
    # Both are aggregators that publish a real catalogue, which is why the
    # catalogue work has two implementations rather than six.
    assert zen.models == [] and go.models == []


def test_a_provider_added_without_a_key_asserts_no_format():
    """A guess at a provider's format refuses a key that works.

    OpenRouter checks an exact 73-character length because that length is known
    and a truncated paste there earns an opaque 401. OpenCode Go's keys are
    only issuable with a subscription, so nothing is known about them and the
    refusal is left to the service.
    """
    import tonyagent.providers  # noqa: F401
    from tonyagent.providers.base import provider_registry

    cls = provider_registry.get("opencode-go")
    assert cls.key_prefix == "", "opencode-go checks a prefix nobody verified"
    assert cls.key_length is None, "opencode-go checks a length nobody verified"

    zen = provider_registry.get("opencode-zen")
    assert zen.key_prefix == "", "opencode-zen checks a prefix nobody verified"
    assert zen.key_length is None, "opencode-zen checks a length nobody verified"


def test_a_vendor_falls_back_to_its_own_endpoint():
    """The arguments are overrides; a bare construction picks the vendor's own."""
    import tonyagent.providers  # noqa: F401
    from tonyagent.providers.base import provider_registry

    provider = provider_registry.get("opencode-go")(api_key="x")
    assert provider.base_url == "https://opencode.ai/zen/go/v1"
    # No default model: Go's ids are behind its subscription, so an empty one is
    # the honest answer rather than a slugified display name.
    assert provider.model == ""

    overridden = provider_registry.get("opencode-go")(api_key="x", model="m",
                                                base_url="https://example.test/v1")
    assert overridden.base_url == "https://example.test/v1"
    assert overridden.model == "m"


def test_the_client_names_itself_and_not_the_http_library():
    """**OpenCode Go's own rule, and a request can be refused for breaking it.**

    Its documentation asks each client to "identify itself with its own user agent,
    such as ``my-coding-agent/1.0``, rather than a generic SDK or HTTP-library name".
    httpx sends its own name unless told otherwise, so this is asserted rather than
    assumed -- the failure is invisible from inside the app.
    """
    from tonyagent.api.client import LLMClient, USER_AGENT

    client = LLMClient(
        provider="opencode-go", api_key="k", model="m", base_url="https://x/v1", key_prefix=""
    )
    agent = client._headers()["User-Agent"]
    assert agent == USER_AGENT
    assert agent.startswith("TONYAgent/"), agent
    assert "httpx" not in agent.lower(), "the HTTP library is introducing us"


def test_opencode_go_always_sends_a_session_id_and_other_gateways_do_not():
    """**This is the header whose absence rejected the request.**

    Go routes and caches per session, and a request without `x-opencode-session` is
    answered with a rejection rather than merely routed worse. A stable id exists
    from the first request because the conversation is not known when the provider is
    built -- the app binds a provider when the settings change and switches
    conversations far more often -- and `set_session` narrows it afterwards.
    """
    import tonyagent.providers  # noqa: F401
    from tonyagent.providers.base import provider_registry

    go = provider_registry.get("opencode-go")(api_key="k")
    headers = go.http_client()._headers()
    assert headers["x-opencode-session"], "opencode-go sent no session id"
    first = headers["x-opencode-session"]

    # Stable across requests: a value that changed per call would defeat the routing
    # and caching it exists for, which is worse than sending none.
    assert go.http_client()._headers()["x-opencode-session"] == first

    # And it follows the conversation once one is known.
    go.set_session("conversation-abc")
    assert go.http_client()._headers()["x-opencode-session"] == "conversation-abc"

    # A gateway that never asked for a session id is not told one: the header's name
    # is the vendor's business, and inventing one for everyone tells them something
    # they did not ask for.
    other = provider_registry.get("openrouter")(api_key="k")
    assert "x-opencode-session" not in other.http_client()._headers()
    assert other.http_client()._headers()["User-Agent"].startswith("TONYAgent/")


def test_a_configured_session_header_wins_over_the_generated_one():
    """`extra_headers` is a settings field: someone who set this by hand meant it."""
    import tonyagent.providers  # noqa: F401
    from tonyagent.providers.base import provider_registry

    provider = provider_registry.get("opencode-go")(
        api_key="k", extra_headers={"x-opencode-session": "mine"}
    )
    assert provider.http_client()._headers()["x-opencode-session"] == "mine"


def test_no_provider_delegates_to_an_abstract_stub():
    """The bug that made five providers silently return None."""
    from tonyagent.providers.base import OpenAICompatibleProvider, provider_registry
    import tonyagent.providers  # noqa: F401

    assert "chat_completion" in OpenAICompatibleProvider.__dict__
    for name in provider_registry.list_providers():
        cls = provider_registry.get(name)
        owner = next(c for c in cls.__mro__ if "chat_completion" in c.__dict__)
        assert owner is OpenAICompatibleProvider, f"{name} -> {owner.__name__}"


def test_providers_expose_a_real_health_check():
    from tonyagent.providers.base import provider_registry
    import tonyagent.providers  # noqa: F401

    for name in provider_registry.list_providers():
        cls = provider_registry.get(name)
        assert hasattr(cls, "check_connection"), name
        assert hasattr(cls, "fetch_models"), name
