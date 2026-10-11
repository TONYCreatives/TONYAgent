"""The browser tools may only be pointed at the web.

Measured, before this file existed: ``browser_navigate`` handed the model's
URL straight to ``page.goto``, which will open ``file:///...`` and will just
as happily request ``http://169.254.169.254/`` or ``http://127.0.0.1:PORT``.
The network tools have carried an internal-address guard since an adversarial
pass measured those URLs being fetched and their bodies returned to the
model; the browser tools had none, which left every address that guard
closes with a second door open beside it -- and without Docker installed the
browser is a real Chromium on the host with the host's network (see
``local_backend``: ``has_network`` is always True there).

These tests drive the real tool against the **real** guard: same client, same
resolution, same refusal wording ``http_request`` and ``web_fetch`` produce,
because the guard is the network tools' own function rather than a copy. Only
the backend is a fake, so what is asserted is the URL decision and not a
mock's behaviour.
"""

from __future__ import annotations

import pytest

import tonyagent.tools  # noqa: F401  -- importing registers every tool
from tonyagent.config.settings import settings
from tonyagent.sandbox.base import BrowserResult, SandboxConfig, SandboxStatus
from tonyagent.tools.base import ToolResultStatus
from tonyagent.tools.browser_tools import _navigate_refusal, get_sandbox_manager


class FakeBackend:
    """A running, networked runtime that records where it was sent."""

    provides_isolation = True
    status = SandboxStatus.RUNNING
    config = SandboxConfig(enable_network=True)

    def __init__(self):
        self.navigated: list[str] = []

    @property
    def has_network(self) -> bool:
        return bool(self.config.enable_network)

    async def browser_navigate(self, url: str) -> BrowserResult:
        self.navigated.append(url)
        return BrowserResult(success=True, data={"url": url, "title": "Fake"})


@pytest.fixture
def net(monkeypatch):
    """A fake runtime installed where the tools look for it."""
    manager = get_sandbox_manager()
    backend = FakeBackend()
    monkeypatch.setattr(manager, "get_runtime_backend", lambda: backend)
    # The default, asserted rather than assumed.
    monkeypatch.setattr(settings.tools, "allow_internal_http", False)
    return backend


def tool(name: str):
    from tonyagent.tools import tool_registry

    found = tool_registry.get(name)
    assert found is not None, f"{name} is not registered"
    return found


# --- schemes: the browser loads web pages and nothing else --------------------

NON_WEB_SCHEMES = [
    "file:///C:/Users/me/.ssh/id_rsa",     # a host file, outside the project
    "file:///etc/passwd",
    "data:text/html,<script>fetch('http://127.0.0.1')</script>",
    "about:blank",
    "chrome://settings",
    "ftp://files.example/x",
]


@pytest.mark.parametrize("url", NON_WEB_SCHEMES)
async def test_a_url_that_is_not_a_web_page_is_refused(url, net):
    """``page.goto`` opens all of these, and none of them is a page.

    ``file:`` is the dangerous one: the browser reads it, ``browser_get_text``
    reports it, and the workspace boundary that every file tool enforces is
    quietly gone. Refused on its own terms -- this is not an address
    question, so the internal-address guard and its opt-in do not apply.
    """
    result = await tool("browser_navigate").execute(url=url)

    assert result.status is ToolResultStatus.ERROR, (url, result.status)
    assert "not an http:// or https:// URL" in (result.error or ""), result.error
    assert net.navigated == [], f"{url} was loaded anyway: {net.navigated}"


# --- internal addresses: the network guard's rule, imported not restated -------

INTERNAL_URLS = [
    "http://127.0.0.1:8123/secret",
    "http://localhost:8080/",
    "http://169.254.169.254/latest/meta-data/",
    "http://100.100.100.200/",              # Alibaba metadata, RFC 6598 space
    "http://192.168.1.1/",
    "http://0x7f000001/",                   # hex spelling of 127.0.0.1
]


@pytest.mark.parametrize("url", INTERNAL_URLS)
async def test_an_internal_address_is_refused(url, net):
    """Same rule as ``web_fetch``: loopback, private, link-local, metadata.

    With the local runtime (no Docker) the browser is the user's own machine,
    so this is the guard standing between a fetched page and every service
    listening on their loopback and LAN. Inside a container with egress
    enabled it is the same rule from the same vantage class.
    """
    result = await tool("browser_navigate").execute(url=url)

    assert result.status is ToolResultStatus.ERROR, (url, result.status)
    assert "Blocked request" in (result.error or ""), result.error
    assert net.navigated == [], f"{url} was loaded anyway: {net.navigated}"


async def test_the_browser_refuses_in_the_same_words_as_the_network_tools(net):
    """One guard, three tools -- so one refusal, not three explanations.

    The property that matters is that the wording is *the same string*: the
    model reads it, the user sees it, and a URL cannot be refused by one
    tool and loaded by another.
    """
    from tonyagent.tools.network_tools import _internal_host_refusal

    for url in INTERNAL_URLS:
        navigated = await tool("browser_navigate").execute(url=url)
        assert navigated.error == _internal_host_refusal(url), url


async def test_a_public_page_still_loads(net):
    """The positive control: a guard that refused everything would pass above."""
    result = await tool("browser_navigate").execute(url="https://example.com/docs")

    assert result.status is ToolResultStatus.SUCCESS, result.error
    assert net.navigated == ["https://example.com/docs"]
    assert "example.com" in result.output


async def test_the_refusal_precedes_the_runtime_question(monkeypatch):
    """A URL the browser must not load is refused even with no sandbox at all.

    Order matters: asking the runtime first would report a broken sandbox as
    the reason a ``file://`` URL was declined -- a wrong reason in front of a
    user, about a condition they did not ask about.
    """
    manager = get_sandbox_manager()
    monkeypatch.setattr(manager, "get_runtime_backend", lambda: None)

    result = await tool("browser_navigate").execute(url="file:///etc/shadow")

    assert result.status is ToolResultStatus.ERROR
    assert "not an http:// or https:// URL" in (result.error or "")
    assert "sandbox" not in (result.error or "").lower(), result.error


async def test_the_documented_door_is_the_network_setting(monkeypatch, net):
    """"Open my dev server on localhost:3000" is a real workflow.

    It is not a hole: the same setting, for the same reason, with the same
    words the network tools' guard uses. What it must never become is
    ``file:`` -- the scheme refusal is not part of that setting.
    """
    monkeypatch.setattr(settings.tools, "allow_internal_http", True)

    local = await tool("browser_navigate").execute(url="http://127.0.0.1:3000/")
    assert local.status is ToolResultStatus.SUCCESS, local.error

    still_refused = await tool("browser_navigate").execute(url="file:///etc/passwd")
    assert still_refused.status is ToolResultStatus.ERROR
    assert "not an http:// or https:// URL" in (still_refused.error or "")


async def test_the_helper_is_the_rule(net):
    """The pure form, pinned so the scheme half is testable without a backend."""
    assert _navigate_refusal("https://example.com/") is None
    assert _navigate_refusal("http://example.com/") is None
    for url in NON_WEB_SCHEMES + INTERNAL_URLS:
        assert _navigate_refusal(url) is not None, url
