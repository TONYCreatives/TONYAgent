"""The internal-address guard must hold for the whole request, not its first hop.

Measured, before this file existed: ``web_fetch`` and ``http_request`` both
refused ``http://127.0.0.1:8123/`` outright, and both returned the body of that
same address when it was reached through
``https://httpbin.org/redirect-to?url=http%3A%2F%2F127.0.0.1%3A8123%2Fsecret``.
The guard was asked once, about the URL the model typed; the client was then
told to follow redirects, and the address that was actually read was never
checked. A guard anyone who can serve a 302 can walk around is not a guard.

These tests drive the real tools against the **real client** -- same
``follow_redirects`` and same request hook the module builds -- with only the
transport replaced by a scripted one. That matters: patching the client factory
instead would let the test supply its own hook, which is the property under
test. A call site that drops the hook fails here.

The positive control (a redirect between two public hosts still works) is part
of the set on purpose: "fixed" by no longer following redirects at all would
otherwise pass.
"""

from __future__ import annotations

from types import SimpleNamespace

import httpx as real_httpx
import pytest

import tonyagent.tools  # noqa: F401  -- importing registers every tool
from tonyagent.tools import tool_registry
from tonyagent.tools.base import ToolResultStatus

SECRET = "INTERNAL-SECRET-TOKEN-12345"
START = "https://docs.example/start"
MIDDLE = "https://cdn.example/hop"
LOOPBACK = "http://127.0.0.1:8123/secret"


def tool(name: str):
    found = tool_registry.get(name)
    assert found is not None, f"{name} is not registered"
    return found


@pytest.fixture
def net(monkeypatch):
    """Scripted responses, keyed by URL, with the requests that were made.

    ``install`` takes a mapping of ``url -> (status, body, headers)`` and
    returns the list of URLs that were actually requested. The injected client
    subclasses the real one and only fills in a transport, so everything the
    production code configured -- redirect following and the request hook --
    still runs.
    """
    from tonyagent.tools import network_tools

    calls: list[str] = []

    def install(routes):
        def handler(request: real_httpx.Request) -> real_httpx.Response:
            calls.append(str(request.url))
            status, body, headers = routes[str(request.url)]
            return real_httpx.Response(
                status, text=body, headers=headers or {}, request=request
            )

        class _Injected(real_httpx.AsyncClient):
            def __init__(self, *args, **kwargs):
                kwargs.setdefault("transport", real_httpx.MockTransport(handler))
                super().__init__(*args, **kwargs)

        monkeypatch.setattr(
            network_tools,
            "httpx",
            SimpleNamespace(
                AsyncClient=_Injected,
                TimeoutException=real_httpx.TimeoutException,
            ),
        )
        return calls

    return install


@pytest.fixture(autouse=True)
def _guard_on(monkeypatch):
    """The default, asserted rather than assumed: a user's config could not set it here."""
    from tonyagent.config.settings import settings

    monkeypatch.setattr(settings.tools, "allow_internal_http", False)


async def test_a_redirect_to_loopback_is_refused_before_the_hop_is_made(net):
    calls = net(
        {
            START: (302, "", {"location": LOOPBACK}),
            LOOPBACK: (200, SECRET, {}),
        }
    )

    result = await tool("web_fetch").execute(url=START)

    assert result.status is ToolResultStatus.ERROR, result.error
    assert "Blocked request to internal address" in result.error
    assert "127.0.0.1" in result.error
    assert SECRET not in (result.output or ""), "the internal body reached the model"
    assert calls == [START], (
        f"the refused hop was requested anyway: {calls}. The guard has to run "
        "before the request goes out, not after the body came back."
    )


async def test_both_network_tools_refuse_the_same_redirect_in_the_same_words(net):
    """Two tools, one guard -- so one refusal, not two explanations of it."""
    routes = {START: (302, "", {"location": LOOPBACK}), LOOPBACK: (200, SECRET, {})}
    net(routes)

    fetched = await tool("web_fetch").execute(url=START)
    requested = await tool("http_request").execute(url=START)

    assert fetched.status is ToolResultStatus.ERROR
    assert requested.status is ToolResultStatus.ERROR
    assert fetched.error == requested.error


async def test_a_chain_is_refused_at_the_hop_that_turns_internal(net):
    """The check is per hop, so the hop that matters is the one it stops on."""
    calls = net(
        {
            START: (302, "", {"location": MIDDLE}),
            MIDDLE: (302, "", {"location": LOOPBACK}),
            LOOPBACK: (200, SECRET, {}),
        }
    )

    result = await tool("web_fetch").execute(url=START)

    assert result.status is ToolResultStatus.ERROR
    assert calls == [START, MIDDLE], (
        f"a public hop was refused, or the internal one was followed: {calls}"
    )


async def test_a_redirect_between_public_hosts_is_still_followed(net):
    """The positive control, with a **relative** ``Location``.

    Without this, deleting ``follow_redirects`` would pass every test above --
    and a tool that cannot follow ``http://example.com`` to ``https://`` is a
    tool that reports a 301 to the model as though it were the page. The
    relative location is the common shape in the wild and the one the hook can
    get wrong, since the URL it is handed has to have been resolved against the
    page that answered.
    """
    hop = "https://docs.example/hop"
    calls = net(
        {
            START: (302, "", {"location": "/hop"}),
            hop: (200, "the docs say so", {}),
        }
    )

    result = await tool("web_fetch").execute(url=START)

    assert result.status is ToolResultStatus.SUCCESS, result.error
    assert "the docs say so" in result.output
    assert calls == [START, hop], f"a relative Location was not resolved: {calls}"


async def test_a_redirect_loop_is_an_error_not_a_hang(net):
    """A page that redirects to itself must come back, not spin.

    Boundary of the same change: the guard runs per hop now, so the hop budget
    is what stops a loop. httpx still owns it (20) and still raises for it, and
    the tool has to turn that into something the model can read.
    """
    calls = net({START: (302, "", {"location": START})})

    result = await tool("web_fetch").execute(url=START)

    assert result.status is ToolResultStatus.ERROR
    assert "redirect" in (result.error or "").lower(), result.error
    assert len(calls) > 1, "the redirect was not followed at all"


# --- the spellings, which the guard must read the way a resolver would -----------
#
# Found by an adversarial pass over the tool surface, with a socket as the
# oracle: every case below was checked against what `socket.create_connection`
# actually does with it. Three were *allowed* by the guard and are refused now,
# for the reason printed in each docstring -- and one of those
# (`100.100.100.200`) is a cloud metadata service in RFC 6598 space, which is
# the range `ipaddress` calls neither private nor reserved.

#: Hosts that must be refused, whatever the local resolver thinks of them.
INTERNAL_SPELLINGS = [
    "http://127.0.0.1/",              # the plain one, as a control
    "http://127.0.0.1./",             # an absolute-FQDN spelling of the same host
    "http://localhost./",             # ditto, and it *connects* (measured)
    "http://0177.0.0.1/",             # octal, which glibc's inet_aton reads as 127.0.0.1
    "http://0x7f000001/",             # hex, same
    "http://127.0.0.01/",             # a leading zero on the last octet
    "http://2130706433/",             # decimal, caught by the parse
    "http://[::ffff:7f00:1]/",        # IPv4-mapped IPv6
    "http://[0:0:0:0:0:ffff:7f00:1]/",  # the same address spelled out
    "http://100.64.0.1/",             # RFC 6598 carrier-grade NAT
    "http://100.100.100.200/",        # Alibaba Cloud metadata, in that same range
    "http://169.254.169.254/",        # the metadata address the docstring names
]


@pytest.mark.parametrize("url", INTERNAL_SPELLINGS)
async def test_the_guard_refuses_every_spelling_of_an_internal_address(url):
    """One table, both tools, no transport: the refusal comes before any request.

    Measured against the three that used to pass: the guard resolved the
    hostname and allowed whatever the resolver declined to resolve, so on a
    machine whose resolver refused the octal and hex spellings they went
    through untouched -- a guard that depends on the *failure* of another
    component is not a guard. The shapes are refused now, before resolution.
    """
    fetched = await tool("web_fetch").execute(url=url)
    requested = await tool("http_request").execute(url=url)

    assert fetched.status is ToolResultStatus.ERROR, (url, fetched.status)
    assert requested.status is ToolResultStatus.ERROR, (url, requested.status)
    assert "Blocked request" in (fetched.error or ""), (url, fetched.error)
    assert fetched.error == requested.error, (
        "the two tools describe the same address differently"
    )


#: Public addresses and names, which must keep working. The negative control.
PUBLIC_TARGETS = [
    "http://93.184.216.34/",   # a public IP: no resolver involved
    "http://8.8.8.8/",
    "https://cdn.example/hop",  # a public name; `.example` cannot resolve private
]


@pytest.mark.parametrize("url", PUBLIC_TARGETS)
async def test_a_public_target_is_not_refused(url, net):
    """Not a fetch -- a *refusal* check, and the direction matters.

    A guard that refused everything would pass every test above. These URLs are
    handed to a transport that answers 200, so what is asserted is that the
    request was actually made.
    """
    calls = net({url: (200, "public body", {})})

    result = await tool("web_fetch").execute(url=url)

    assert result.status is ToolResultStatus.SUCCESS, (url, result.error)
    assert calls == [url], f"{url} was refused before the request: {calls}"


async def test_a_name_that_does_not_resolve_is_left_to_the_transport():
    """The documented fail-open, pinned so it is a decision rather than a hole.

    An unresolvable name is not an internal address, and refusing it would mean
    ``web_fetch`` reports "internal address" whenever the machine is offline --
    a wrong reason in front of a user. The ways *around* this branch are the
    numeric spellings above, which no longer reach it.
    """
    relay = ["http://does-not-exist.invalid/", "http://also-not-a-host.invalid/"]

    for url in relay:
        result = await tool("web_fetch").execute(url=url, timeout=1)

        assert result.status is ToolResultStatus.ERROR
        assert "Blocked request" not in (result.error or ""), (
            f"{url} was called an internal address: {result.error!r}"
        )


MALFORMED_URLS = ["http://evi[l]/", "http://[::1/", "http://[]/", "http://[a:b]/"]


@pytest.mark.parametrize("url", MALFORMED_URLS)
async def test_a_url_the_guard_cannot_parse_is_refused_rather_than_raised(url):
    """`urlparse` raises on some spellings, and a raise is not a refusal.

    Measured before this: ``http://evi[l]/`` came back to the model as ``Tool
    execution failed: Invalid IPv6 URL`` -- the orchestrator's paraphrase of the
    ``ValueError``, which names no address and offers no fix -- and inside the
    httpx request hook the same exception would surface on a *redirect hop*, as
    an error about the transport. The guard reads a URL it cannot parse as a
    URL it will not fetch, in words that say which of the two happened.
    """
    fetched = await tool("web_fetch").execute(url=url)

    assert fetched.status is ToolResultStatus.ERROR, (url, fetched.status)
    assert "Blocked request" in (fetched.error or ""), (url, fetched.error)
    assert "not a URL this guard can read" in (fetched.error or ""), (
        "a malformed URL was reported as an internal address, which it is not"
    )
