"""Tests for the chat-only provider gate.

A local model on this machine's CPU is a plain chat model: it answers a
person, it does not act. Every mode except Chat exists to have the model
*act*, so the local provider is offered in Chat mode and nowhere else.

The gate has three parts and all three are tested here, because each of them
can fail on its own:

- the **list** the picker draws omits it outside Chat mode,
- the **bind** refuses it outside Chat mode,
- the **mode change** unbinds it when the session leaves Chat.

And a fourth, which is the reason for the whole arrangement: a chat-only
provider is sent **no tool schemas at all**. The tool catalogue is 6,646
tokens and prefill on a CPU is the bottleneck, so a local model would spend
a minute reading schemas before it read the question.
"""

from __future__ import annotations

import pytest

from tonyagent.core.modes import MODE_ORDER
from tonyagent.core.session import AgentSession
from tonyagent.providers.base import provider_registry
from tonyagent.providers.factory import (
    CHAT_MODE,
    ProviderFactory,
    provider_allowed_in_mode,
)


def _airllm():
    """The local provider class, or skip if this build has none."""
    from tonyagent.providers import local_airllm  # noqa: F401 - registers it

    cls = provider_registry.get("airllm")
    if cls is None:
        pytest.skip("this build registers no airllm provider")
    return cls


def _names(mode: str) -> list[str]:
    return [e["name"] for e in ProviderFactory.get_available_providers(mode)]


# -- the capability itself -------------------------------------------------

def test_airllm_is_declared_chat_only():
    assert _airllm().chat_only is True


def test_hosted_providers_are_not_chat_only():
    """The gate must not swallow the providers that can actually act."""
    for name in provider_registry.list_providers():
        if name == "airllm":
            continue
        assert provider_registry.get(name).chat_only is False, name


def test_provider_allowed_in_mode_without_a_mode_allows_everything():
    """An empty mode means "what exists", not "what works here"."""
    assert provider_allowed_in_mode(_airllm(), "") is True


# -- the list --------------------------------------------------------------

def test_airllm_is_listed_in_chat_mode():
    assert "airllm" in _names(CHAT_MODE)


@pytest.mark.parametrize("mode", [m for m in MODE_ORDER if m != CHAT_MODE])
def test_airllm_is_not_listed_outside_chat_mode(mode):
    """Every other mode hides it, rather than listing it and refusing it."""
    assert "airllm" not in _names(mode)


def test_other_providers_are_listed_in_every_mode():
    """Only the local provider is gated. The rest must survive the filter."""
    for mode in MODE_ORDER:
        listed = _names(mode)
        assert "opencode-go" in listed, mode


def test_the_list_carries_the_chat_only_flag():
    entry = next(e for e in ProviderFactory.get_available_providers(CHAT_MODE)
                 if e["name"] == "airllm")
    assert entry["chat_only"] is True


def test_an_unfiltered_list_still_reports_chat_only():
    """`all` asks what exists; the flag still has to come with it."""
    entry = next(e for e in ProviderFactory.get_available_providers("")
                 if e["name"] == "airllm")
    assert entry["chat_only"] is True


# -- the bind --------------------------------------------------------------

def test_binding_in_chat_mode_succeeds():
    session = AgentSession()
    session.set_mode(CHAT_MODE)
    provider = session.bind_provider("airllm")
    assert provider is not None
    assert session.provider_name == "airllm"


def test_binding_outside_chat_mode_is_refused():
    session = AgentSession()
    session.set_mode("build")
    with pytest.raises(ValueError) as exc:
        session.bind_provider("airllm")
    # The message has to name the fix, or the user cannot act on it.
    assert "Chat mode" in str(exc.value)


def test_a_refused_bind_leaves_the_previous_provider_alone():
    """A refusal must not unbind what was already working."""
    session = AgentSession()
    session.set_mode(CHAT_MODE)
    session.bind_provider("airllm")
    session.set_mode("build")  # this drops it, so bind a hosted one first
    session.bind_provider("opencode-go")
    with pytest.raises(ValueError):
        session.bind_provider("airllm")
    assert session.provider_name == "opencode-go"


# -- the mode change -------------------------------------------------------

def test_leaving_chat_mode_unbinds_the_local_provider():
    session = AgentSession()
    session.set_mode(CHAT_MODE)
    session.bind_provider("airllm")
    session.set_mode("build")
    assert session.provider is None
    assert session.provider_name == ""


def test_leaving_chat_mode_reports_what_it_disconnected():
    """A provider that vanishes silently reads as the app forgetting it."""
    session = AgentSession()
    session.set_mode(CHAT_MODE)
    session.bind_provider("airllm")
    session.set_mode("build")
    assert session.last_disconnected_provider == "airllm"


def test_entering_chat_mode_leaves_a_hosted_provider_alone():
    session = AgentSession()
    session.set_mode("build")
    session.bind_provider("opencode-go")
    session.set_mode(CHAT_MODE)
    assert session.provider_name == "opencode-go"
    assert session.last_disconnected_provider == ""


def test_the_disconnection_is_reported_only_for_the_last_change():
    session = AgentSession()
    session.set_mode(CHAT_MODE)
    session.bind_provider("airllm")
    session.set_mode("build")
    assert session.last_disconnected_provider == "airllm"
    session.set_mode("plan")
    assert session.last_disconnected_provider == ""


# -- no tools --------------------------------------------------------------

def test_a_chat_only_provider_is_sent_no_tool_schemas():
    """The reason the gate exists, measured in prefill."""
    session = AgentSession()
    session.set_mode(CHAT_MODE)
    session.bind_provider("airllm")
    assert session._tool_schemas() == []


def test_a_hosted_provider_still_gets_chat_mode_tools():
    """The gate must not take the tools away from everyone else."""
    session = AgentSession()
    session.set_mode(CHAT_MODE)
    session.bind_provider("opencode-go")
    assert session._tool_schemas()


def test_chat_mode_alone_is_not_the_same_as_a_chat_only_provider():
    """Chat mode has read-only tools. A chat-only provider gets none.

    These are different things, and the difference is the point: a hosted
    model in Chat mode is still shown the dozen read-only tools Chat allows.
    """
    session = AgentSession()
    session.set_mode(CHAT_MODE)
    session.bind_provider("opencode-go")
    hosted = len(session._tool_schemas())
    session.bind_provider("airllm")
    assert len(session._tool_schemas()) == 0
    assert hosted > 0
