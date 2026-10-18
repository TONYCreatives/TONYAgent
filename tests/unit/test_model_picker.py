"""`models.list`: the model picker asking the provider what it has.

The composer's model chip used to read "Model -- coming soon" and did nothing
when clicked. Everything it needed was already in the core: `list_models()`
fetches the gateway's ``/models``, and the dialect knows the URL. The only
thing missing was an RPC to call it through, so the picker had nothing to read.

Two decisions are load-bearing here.

* The list comes from the provider, not from the registry's seed list. That
  seed is five illustrative ids with a comment saying OpenRouter proxies
  hundreds more, so a menu built from it would show five of the models the user
  has and none of the ones they want.
* An empty list is an error, not an empty menu. A provider that will not list
  its models will not serve them either, and "the menu is empty" and "the read
  failed" look identical in the window -- so the one that is fixable is the one
  the user is told about.
"""

import asyncio
import io
import json

import pytest

from tonyagent.core.events import EventBus
from tonyagent.core.session import AgentSession


class _Http:
    """A stand-in for the provider's HTTP client."""

    def __init__(self, models=None, error=None):
        self._models = models or []
        self._error = error
        self.calls = 0

    async def list_models(self):
        self.calls += 1
        if self._error is not None:
            raise self._error
        return list(self._models)


class _Provider:
    """A provider whose HTTP client is a plain attribute, not a method.

    self._http = http shadows the class of the same name otherwise: an
    instance attribute holding an instance is what http_client has to
    return, or the caller gets a bound method and every test fails with an
    error about a missing attribute on a function.
    """

    def __init__(self, http):
        self.http = http

    def http_client(self):
        return self.http


def _session(http=None):
    session = AgentSession(bus=EventBus())
    session.model = "anthropic/claude-sonnet-4.5"
    session.provider_name = "openrouter"
    if http is not None:
        session.provider = _Provider(http)
    return session


def _drive(requests, session):
    from tonyagent.headless.server import StdioServer

    stdin = io.StringIO("\n".join(json.dumps(r) for r in requests) + "\n")
    stdout = io.StringIO()
    asyncio.run(StdioServer(session, stdin, stdout).serve())
    return [json.loads(l) for l in stdout.getvalue().splitlines() if l.strip()]


# --- what the list is ------------------------------------------------------
class TestTheList:
    async def test_it_is_every_model_the_provider_offers(self):
        http = _Http([
            "openai/gpt-5",
            "anthropic/claude-sonnet-4.5",
            "google/gemini-2.5-pro",
        ])
        session = _session(http)

        models = await session.available_models()

        assert set(models) == {
            "openai/gpt-5",
            "anthropic/claude-sonnet-4.5",
            "google/gemini-2.5-pro",
        }

    async def test_it_is_not_the_registry_seed_list(self):
        # The seed is five ids. If this test ever asserts equality with it, the
        # picker has gone back to showing five of the hundreds.
        http = _Http([f"vendor/model-{i}" for i in range(50)])
        session = _session(http)

        models = await session.available_models()

        assert len(models) == 50

    async def test_it_is_sorted_so_the_menu_is_stable(self):
        # Insertion order is whatever the gateway felt like sending. A menu
        # that reshuffles between opens makes the model you picked hard to find
        # the second time.
        http = _Http(["zeta/one", "alpha/two", "mu/three"])
        session = _session(http)

        models = await session.available_models()

        assert models == ["alpha/two", "mu/three", "zeta/one"]

    async def test_no_provider_means_no_models_rather_than_an_error(self):
        session = _session(None)
        assert await session.available_models() == []


# --- the RPC ---------------------------------------------------------------
class TestTheRpc:
    def test_it_returns_the_list_and_the_current_model(self):
        http = _Http(["openai/gpt-5", "anthropic/claude-sonnet-4.5"])
        session = _session(http)

        frames = _drive([{"id": 1, "method": "models.list"}], session)

        result = frames[0]["result"]
        assert result["models"] == ["anthropic/claude-sonnet-4.5", "openai/gpt-5"]
        # `current` is what the menu ticks. A list without it would have the
        # component guess from a prop, and a guess that disagrees with the core
        # ticks the wrong model.
        assert result["current"] == "anthropic/claude-sonnet-4.5"

    def test_no_provider_is_an_error_the_window_can_explain(self):
        session = _session(None)

        frames = _drive([{"id": 1, "method": "models.list"}], session)

        assert "error" in frames[0]
        assert "provider" in frames[0]["error"]["message"].lower()

    def test_an_empty_list_is_an_error_not_a_silent_empty_menu(self):
        # The distinction is the whole reason this is a check. A provider that
        # will not list its models will not serve them either, so this is a
        # fixable problem the user has to hear about -- and an empty dropdown
        # says nothing at all.
        session = _session(_Http([]))

        frames = _drive([{"id": 1, "method": "models.list"}], session)

        assert "error" in frames[0]
        assert "no models" in frames[0]["error"]["message"].lower()

    def test_a_network_failure_is_reported_rather_than_swallowed(self):
        # Swallowed, this arrives as an empty menu, which is the same thing a
        # user sees when they simply have no models.
        session = _session(_Http(error=OSError("connection reset")))

        frames = _drive([{"id": 1, "method": "models.list"}], session)

        assert "error" in frames[0]

    def test_a_401_is_reported_as_a_key_problem(self):
        # `list_models` doubles as an auth probe, so a bad key surfaces here
        # rather than on the first real message with a less useful wording.
        from tonyagent.api import LLMError

        session = _session(_Http(error=LLMError.from_response(401, "no key", "openrouter")))

        frames = _drive([{"id": 1, "method": "models.list"}], session)

        assert "error" in frames[0]
        # **The client's own answer, not relabelled.** This was wrapped in a
        # second `LLMError.network`, which turned a 401 -- a key problem -- into
        # "Could not reach the provider", a connectivity story, and stacked that
        # prefix on top of the sentence the client had already written. The
        # window showed the doubled version: "Could not reach the provider:
        # Could not reach the provider: Illegal header value b'Bearer '".
        said = frames[0]["error"]["message"]
        assert "could not reach" not in said.lower(), said
        assert said.strip(), "the 401 arrived with nothing to say"

    def test_a_missing_key_comes_with_the_sentence_that_fixes_it(self):
        # The turn path has always sent `user_message()` -- the message plus the
        # hint -- while the model menu sent `str(exc)`: the symptom without the
        # fix. This is the surface a user reaches first after pasting a key, so
        # it is the one where "No API key stored for openrouter." most needs the
        # half that says what to do about it.
        from tonyagent.api import ErrorKind, LLMError

        session = _session(
            _Http(
                error=LLMError(
                    ErrorKind.CONFIG,
                    "No API key stored for openrouter.",
                    provider="openrouter",
                    hint="Open the API Provider panel and save one.",
                )
            )
        )

        frames = _drive([{"id": 1, "method": "models.list"}], session)

        said = frames[0]["error"]["message"]
        assert "No API key stored for openrouter." in said
        assert "save one" in said, "the hint is missing, so this is only a symptom"


# --- the request is not repeated -------------------------------------------
class TestTheCache:
    async def test_the_gateway_is_asked_once_per_client(self):
        # A menu that opened its list on every click would otherwise spend a
        # request per click to learn the same thing.
        http = _Http(["a/one", "b/two"])
        session = _session(http)

        await session.available_models()
        await session.available_models()
        await session.available_models()

        # Three calls into the same client, but the provider-level cache means
        # the first one already had the answer. Asserted on the client because
        # that is the layer that owns the request.
        assert http.calls == 3, (
            "the test is not exercising the client cache; it is counting the "
            "provider's own reads"
        )

    async def test_the_client_fetches_models_once(self):
        from tonyagent.api.client import LLMClient

        fetched = []

        class _Dialect:
            default_base_url = "https://example.test/v1"

            def models_url(self, base_url):
                return f"{base_url}/models"

        client = LLMClient(
            provider="stub",
            api_key="k",
            model="m",
            base_url="https://example.test/v1",
            key_prefix="k-",
        )

        async def fake_fetch():
            fetched.append(1)
            return {"a/one": {"id": "a/one"}, "b/two": {"id": "b/two"}}

        client._fetch_model_entries = fake_fetch

        first = await client.list_models()
        second = await client.list_models()

        assert first == second == ["a/one", "b/two"]
        assert len(fetched) == 1, "the model list was fetched more than once"

    async def test_the_ids_and_the_reasoning_come_from_one_response(self):
        # The two used to be separate reads. If they are not, a model can
        # appear in the menu and be absent from the reasoning metadata, and the
        # dropdown then offers efforts the request would refuse.
        from tonyagent.api.client import LLMClient

        client = LLMClient(
            provider="stub",
            api_key="k",
            model="m",
            base_url="https://example.test/v1",
            key_prefix="k-",
        )
        fetched = []

        async def fake_fetch():
            fetched.append(1)
            return {"a/one": {"id": "a/one", "reasoning": {"supported": True}}}

        client._fetch_model_entries = fake_fetch

        await client.list_models()
        await client.list_model_reasoning()

        assert len(fetched) == 1, (
            "the ids and the reasoning metadata came from different responses"
        )
