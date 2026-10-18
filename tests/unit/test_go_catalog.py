"""Curated Go facts: shape, protocol-routing agreement, catalog overlay."""

import pytest

from tonyagent.api.client import LLMClient, RESPONSES_DIRECT_PREFIXES
from tonyagent.providers.go_catalog import GO_MODEL_FACTS


def _client(provider="opencode-go", model="kimi-k3"):
    return LLMClient(
        provider=provider, api_key="k" * 40, model=model,
        base_url="https://x/v1", key_prefix="",
    )


def test_every_fact_has_the_fields_a_picker_reads():
    assert len(GO_MODEL_FACTS) >= 30
    for model_id, facts in GO_MODEL_FACTS.items():
        assert facts["name"], model_id
        assert facts["protocol"] in ("chat", "responses", "messages"), model_id
        assert facts["context_window"] > 0, model_id
        assert facts["max_tokens"] > 0, model_id
        assert facts["input_modalities"], model_id


def test_responses_models_agree_with_request_routing():
    """The catalog and the client's direct-routing list must name the same set.

    Two sources of protocol truth already caused one outage (Muse Spark sent
    to chat/completions); this pins them together so the next catalog edit
    cannot reintroduce it silently.
    """
    catalog_responses = sorted(
        m for m, f in GO_MODEL_FACTS.items() if f["protocol"] == "responses"
    )
    for model_id in catalog_responses:
        assert model_id.lower().startswith(RESPONSES_DIRECT_PREFIXES), model_id
    for prefix in ("muse-spark-", "grok-4.7", "gpt-6-luna", "gpt-5.6-luna"):
        assert any(m.startswith(prefix) for m in catalog_responses), prefix


async def test_catalog_enriches_bare_go_ids():
    client = _client()
    client._model_entries_cache = {
        "kimi-k3": {"id": "kimi-k3"},
        "some-future-model": {"id": "some-future-model"},
    }
    catalog = await client.model_catalog()
    by_id = {m["id"]: m for m in catalog}
    kimi = by_id["kimi-k3"]
    assert kimi["name"] == "Kimi K3"
    assert kimi["context_length"] == 1048576
    assert kimi["max_tokens"] == 131072
    assert kimi["input_modalities"] == ["text", "image"]
    assert kimi["protocol"] == "chat"
    # Unknown to the facts: listed, with zeros -- never a neighbour's numbers.
    future = by_id["some-future-model"]
    assert future["context_length"] == 0
    assert future["max_tokens"] == 0
    assert future["input_modalities"] == []
    assert future["protocol"] == ""


async def test_catalog_overlay_is_scoped_to_go():
    client = _client(provider="openrouter", model="x")
    client._model_entries_cache = {
        "kimi-k3": {"id": "kimi-k3", "name": "Kimi", "context_length": 100},
    }
    (row,) = await client.model_catalog()
    assert row["name"] == "Kimi"
    assert row["context_length"] == 100
    assert row["max_tokens"] == 0
    assert row["protocol"] == ""


async def test_context_window_falls_back_to_facts():
    client = _client(model="muse-spark-1.3-contributor")
    client._model_entries_cache = {"muse-spark-1.3-contributor": {"id": "x"}}
    assert await client.model_context_window() == 1048576
    missing = _client(model="some-future-model")
    missing._model_entries_cache = {"some-future-model": {"id": "x"}}
    assert await missing.model_context_window() == 0
