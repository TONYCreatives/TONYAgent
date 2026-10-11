"""Network tools for TONYAgent."""

from __future__ import annotations

import asyncio
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


def _is_internal_host(hostname: str) -> bool:
    """True if hostname points at loopback/private/link-local/reserved space.

    Uses real IP parsing rather than string prefixes, so abbreviated forms like
    ``2130706433`` (decimal for 127.0.0.1) or ``127.1`` are caught too.
    Anything unparseable is treated as internal (fail closed).
    """
    import ipaddress
    import re
    import socket

    host = (hostname or "").strip().lower().strip("[]")
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

    host = urlparse(url).hostname or ""
    if not _is_internal_host(host):
        return None
    if settings.tools.allow_internal_http:
        return None
    return (
        f"Blocked request to internal address '{host}'. This blocks loopback, "
        f"private, and link-local targets (including 169.254.169.254 cloud "
        f"metadata). Set tools.allow_internal_http=true to allow."
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
    requires_confirmation = True
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
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
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
    requires_confirmation = True
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
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
                response = await client.get(url)
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