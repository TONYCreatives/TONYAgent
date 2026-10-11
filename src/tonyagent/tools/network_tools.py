"""Network tools for TONYAgent."""

from __future__ import annotations

import ipaddress
import re

import httpx
from typing import Any

from tonyagent.tools.base import (
    Tool,
    ToolResult,
    ToolResultStatus,
    ToolCategory,
    output_excerpt,
    register_tool,
)
from tonyagent.config.settings import settings


#: RFC 6598 carrier-grade NAT space, which is neither public internet nor
#: covered by ``ipaddress``'s ``is_private``.
#:
#: Added after an adversarial pass measured ``http://100.64.0.1/`` and
#: ``http://100.100.100.200/`` (Alibaba Cloud's metadata service) being
#: **allowed**: ``is_private`` is False and ``is_reserved`` is False for the
#: whole /10, and the stdlib only reports it as not ``is_global`` -- a predicate
#: this check cannot switch to wholesale, because NAT64's ``64:ff9b::/96`` is
#: ``is_global`` True *and* ``is_reserved`` True, so a ``not is_global`` rule
#: would stop covering it. One named range is the honest fix.
_SHARED_ADDRESS_SPACE = ipaddress.ip_network("100.64.0.0/10")


#: Host spellings that are an address to somebody but not to ``ip_address``.
#:
#: ``inet_aton`` -- which glibc's ``getaddrinfo`` consults -- reads
#: ``0x7f000001``, ``017700000001`` and ``0177.0.0.1`` as 127.0.0.1, while
#: ``ipaddress.ip_address`` rejects every one of them. Nothing legitimate is
#: named this way, so the *shape* is refused instead of interpreted: a guard
#: that leaned on the resolver to expand these was allowing them on any machine
#: whose resolver declined to (measured: Windows refuses all three, so the
#: resolution branch never fired and all three sailed through).
_NUMERIC_HOST_RE = re.compile(r"\d+(\.\d+){0,3}")
_HEX_HOST_RE = re.compile(r"0[xX][0-9a-fA-F]+")


def _is_unparseable_numeric(host: str) -> bool:
    """Whether this host is a number spelled in a non-standard notation."""
    if _HEX_HOST_RE.fullmatch(host):
        return True
    if not _NUMERIC_HOST_RE.fullmatch(host):
        return False
    # A leading zero on any octet is the classic octal ambiguity: "0177.0.0.1"
    # is 127.0.0.1 to inet_aton and would be 177.0.0.1 if read as decimal.
    return any(len(part) > 1 and part.startswith("0") for part in host.split("."))


def _is_internal_host(hostname: str) -> bool:
    """True if hostname points at loopback/private/link-local/reserved space.

    Uses real IP parsing rather than string prefixes, so abbreviated forms like
    ``2130706433`` (decimal for 127.0.0.1) or ``127.1`` are caught too.
    Anything unparseable is treated as internal (fail closed).
    """
    import socket

    host = (hostname or "").strip().lower().strip("[]")
    # A trailing dot is a legal way to write an absolute name, and the resolver
    # treats "localhost." as localhost (measured: it connects to 127.0.0.1).
    # Stripped before the name comparisons so this guard sees the same host the
    # resolver does.
    host = host.rstrip(".")
    if not host:
        return True
    # "localhost" and friends, including subdomains.
    if host == "localhost" or host.endswith(".localhost") or host.endswith(".local"):
        return True

    # Strip a trailing port if the caller passed host:port.
    if host.count(":") == 1 and not host.endswith(":"):
        maybe_host, _, maybe_port = host.rpartition(":")
        if maybe_port.isdigit():
            host = maybe_host

    if _is_unparseable_numeric(host):
        return True

    candidates = [host]
    # Alternative numeric encodings that ip_address rejects but sockets accept:
    # "127.1" (short form) and "2130706433" (decimal for 127.0.0.1).
    if host.isdigit():
        try:
            candidates.append(str(ipaddress.ip_address(int(host))))
        except ValueError:
            pass
    elif re.fullmatch(r"\d+(\.\d+){1,2}", host):
        octets = [int(o) for o in host.split(".")]
        octets += [0] * (4 - len(octets))  # "127.1" -> 127.1.0.0
        if all(0 <= o <= 255 for o in octets):
            candidates.append(".".join(str(o) for o in octets))
    # Resolve names so "metadata.google.internal" style aliases are caught.
    try:
        infos = socket.getaddrinfo(host, None)
        candidates += [info[4][0] for info in infos]
    except Exception:
        pass

    for candidate in candidates:
        try:
            ip = ipaddress.ip_address(candidate)
        except ValueError:
            # Non-IP hostname: if it resolved above we have IPs, else fail closed.
            continue
        if (
            ip.is_loopback
            or ip.is_private
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
            # CGNAT and cloud metadata in the shared range; see the constant.
            or (ip.version == 4 and ip in _SHARED_ADDRESS_SPACE)
        ):
            return True
    # Unresolvable and not obviously internal -> allow (will just fail to connect).
    return False


def _internal_host_refusal(url: str) -> str | None:
    """The reason this URL must not be fetched, or ``None`` if it is fine.

    One home for the guard *and* its wording. Both network tools ask, and the
    point of sharing the check is that they cannot end up telling the user two
    different things about the same address -- the class of failure that
    ``runtime_access`` was created to end.

    Keyed on ``tools.allow_internal_http`` and NOT on ``sandbox.enable_network``:
    the sandbox setting governs the container's egress, not what the host can be
    told to fetch. An earlier version inverted that, so with the network default
    at False it *allowed* internal hosts.
    """
    from urllib.parse import urlparse

    try:
        host = urlparse(url).hostname or ""
    except ValueError as exc:
        # ``urlparse`` raises on a handful of hostile spellings -- `http://evi[l]/`
        # and `http://[::1/` both end in "Invalid IPv6 URL". A URL this guard
        # cannot read is not one it may wave through, and it is not an internal
        # address either, so it is refused in its own words. Measured before
        # this: the ValueError escaped both tools' own error handling and
        # reached the orchestrator, which reported it as a tool *crash*
        # ("Tool execution failed: Invalid IPv6 URL") rather than a refusal --
        # and inside the httpx request hook it would have surfaced as a
        # transport error on a redirect hop, where nobody would look for it.
        return (
            f"Blocked request: {url!r} is not a URL this guard can read "
            f"({exc}). The address needs fixing before it can be fetched."
        )
    if not _is_internal_host(host):
        return None
    if settings.tools.allow_internal_http:
        return None
    return (
        f"Blocked request to internal address '{host}'. This blocks loopback, "
        f"private, and link-local targets (including 169.254.169.254 cloud "
        f"metadata). Set tools.allow_internal_http=true to allow."
    )


class BlockedTarget(Exception):
    """A request the guard refuses, with ``_internal_host_refusal``'s wording.

    Raised from the request hook below rather than returned, because httpx is
    what follows the redirects: by the time a hop is refused the caller is
    inside ``client.request``, so the refusal has to come out the same way any
    other transport failure does.
    """


async def _refuse_internal_target(request: httpx.Request) -> None:
    """Refuse an internal target, for the request httpx is about to send.

    **Why a hook and not a check on the caller's URL.** The guard used to be
    asked once, about the URL the model typed, while the client was told
    ``follow_redirects=True`` -- so a public page that answered with
    ``Location: http://127.0.0.1:...`` had its body fetched and handed to the
    model, and the address that was actually read was never checked. httpx
    calls a request hook for *every* request it makes, redirect hops included,
    and before the request goes out (``_send_handling_redirects`` awaits the
    hooks ahead of each ``_send_single_request``; verified against httpx
    0.28.1), so one hook covers the whole chain instead of its first hop.

    Async because that loop awaits the hooks -- a plain function here fails at
    the first request with ``object NoneType can't be used in 'await'
    expression``, which is how this was found.

    This is deliberately not a *second* copy of the rule: it calls
    ``_internal_host_refusal``, so both the pre-flight check and every hop get
    the same answer in the same words.
    """
    refusal = _internal_host_refusal(str(request.url))
    if refusal:
        raise BlockedTarget(refusal)


def _guarded_client(timeout: float) -> httpx.AsyncClient:
    """The one place a network tool builds a client, guard included.

    A single constructor rather than two ``AsyncClient(...)`` calls with the
    same three arguments: the hook is the security property, and a call site
    that forgot it would look exactly like one that did not.
    """
    return httpx.AsyncClient(
        timeout=timeout,
        follow_redirects=True,
        event_hooks={"request": [_refuse_internal_target]},
    )


@register_tool
class HttpRequestTool(Tool):
    """Make an HTTP request.

    The one tool that does not need a project folder, and the one with a
    network-shaped guard: loopback, private and link-local addresses are
    refused by default. Without that, "fetch the docs" is a one-token pivot
    into the user's own services, so the refusal names the setting that opens
    it rather than just saying no.
    """

    name = "http_request"
    description = "Make an HTTP request to a URL."
    category = ToolCategory.NETWORK
    parameters = {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "URL to request"},
            "method": {"type": "string", "enum": ["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD"], "default": "GET"},
            "headers": {"type": "object", "description": "HTTP headers", "additionalProperties": {"type": "string"}},
            "body": {"type": "string", "description": "Request body"},
            "timeout": {"type": "integer", "description": "Timeout in seconds", "default": 30},
        },
        "required": ["url"],
        "additionalProperties": False,
    }
    destructive = False
    # ``requires_confirmation`` was declared True once and was inert: the
    # orchestrator's gate is ``destructive and requires_confirmation``, so a
    # non-destructive tool is never asked about. The flag was a claim nothing
    # enforced, which is worse than no flag. Dropped rather than the gate
    # widened -- the gate as it stands is what keeps the one prompt a turn
    # meaningful. See ``tests/unit/test_local_sandbox.py::
    # test_no_tool_claims_confirmation_without_destructive``, which pins the
    # invariant so a seventh tool cannot join this mistake.
    # Needs no project folder: nothing here reads or writes the workspace. Was
    # previously special-cased by name in the orchestrator.
    folder_required = False

    async def execute(
        self,
        url: str,
        method: str = "GET",
        headers: dict[str, str] | None = None,
        body: str | None = None,
        timeout: int = 30,
    ) -> ToolResult:
        # Basic URL validation
        if not url.startswith(("http://", "https://")):
            return ToolResult(status=ToolResultStatus.ERROR, error="URL must start with http:// or https://")

        # The guard is shared with `web_fetch` rather than restated here, so the
        # two cannot end up describing the same refusal two different ways.
        refusal = _internal_host_refusal(url)
        if refusal:
            return ToolResult(status=ToolResultStatus.ERROR, error=refusal)
        
        try:
            async with _guarded_client(timeout) as client:
                response = await client.request(
                    method=method,
                    url=url,
                    headers=headers or {},
                    content=body,
                )
                
                # Limit response size
                content = response.text
                max_size = settings.tools.max_output_size
                if len(content) > max_size:
                    content = content[:max_size] + "\n... (truncated)"
                
                output = {
                    "status_code": response.status_code,
                    "headers": dict(response.headers),
                    "body": content,
                }
                
                status = ToolResultStatus.SUCCESS if 200 <= response.status_code < 400 else ToolResultStatus.ERROR
                error = f"HTTP {response.status_code}" if response.status_code >= 400 else None
                
                # The card's one line. `output` is a status-code-and-headers
                # envelope, which the window will not render, so the summary is
                # what a reader actually sees.
                excerpt = output_excerpt(content)
                summary = f"HTTP {response.status_code}"
                if excerpt:
                    summary += f" \u00b7 {excerpt}"
                return ToolResult(
                    status=status,
                    output=output,
                    summary=summary,
                    error=error,
                )
        except BlockedTarget as exc:
            return ToolResult(status=ToolResultStatus.ERROR, error=str(exc))
        except httpx.TimeoutException:
            return ToolResult(status=ToolResultStatus.ERROR, error=f"Request timed out after {timeout}s")
        except Exception as e:
            return ToolResult(status=ToolResultStatus.ERROR, error=str(e))


@register_tool
class WebFetchTool(Tool):
    """Fetch a URL and read what it says.

    Deliberately narrower than ``http_request``: GET, no body, no method to
    choose, and the page comes back as text rather than as a status-code-and-
    headers envelope. That is the shape the work actually has -- read this page
    -- and keeping it separate means the common case does not have to describe an
    HTTP method in order to get at a paragraph.

    **It shares ``http_request``'s guard instead of restating it.** Refusing
    loopback, private and link-local addresses is the difference between "fetch
    the docs" and a one-token pivot into the user's own services, and two copies
    of that rule would eventually disagree about which addresses it covers.

    No project folder is required, for the same reason ``http_request`` needs
    none: fetching a URL neither reads nor writes the workspace.
    """

    name = "web_fetch"
    description = (
        "Fetch a URL and return its text. Read-only: GET only, with no request "
        "body, for reading a page rather than driving an API."
    )
    category = ToolCategory.NETWORK
    parameters = {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "URL to fetch"},
            "timeout": {"type": "integer", "description": "Timeout in seconds", "default": 30},
        },
        "required": ["url"],
        "additionalProperties": False,
    }
    destructive = False
    # Inert ``requires_confirmation`` dropped, for the same reason and with the
    # same pin as `http_request` above.
    folder_required = False

    async def execute(self, url: str, timeout: int = 30) -> ToolResult:
        if not url.startswith(("http://", "https://")):
            return ToolResult(
                status=ToolResultStatus.ERROR,
                error="URL must start with http:// or https://",
            )

        refusal = _internal_host_refusal(url)
        if refusal:
            return ToolResult(status=ToolResultStatus.ERROR, error=refusal)

        try:
            async with _guarded_client(timeout) as client:
                response = await client.get(url)
        except BlockedTarget as exc:
            # A redirect this guard refused, or the URL itself. Same wording
            # either way -- the model reads it and the user sees it.
            return ToolResult(status=ToolResultStatus.ERROR, error=str(exc))
        except httpx.TimeoutException:
            return ToolResult(
                status=ToolResultStatus.ERROR,
                error=f"Request timed out after {timeout}s",
            )
        except Exception as e:
            return ToolResult(status=ToolResultStatus.ERROR, error=str(e))

        if response.status_code >= 400:
            return ToolResult(
                status=ToolResultStatus.ERROR,
                error=f"HTTP {response.status_code} fetching {url}",
            )

        content = response.text
        # A truncation the model is not told about is a model that reasons about
        # half a page as though it were the whole thing, so the marker is part of
        # the output rather than a detail left in a log.
        if len(content) > settings.tools.max_output_size:
            content = content[: settings.tools.max_output_size] + "\n... (truncated)"
        return ToolResult(
            status=ToolResultStatus.SUCCESS,
            output=f"{url} -> HTTP {response.status_code}\n\n{content}",
        )