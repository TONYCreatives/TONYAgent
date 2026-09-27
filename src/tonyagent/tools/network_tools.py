"""Network tools for TONYAgent."""

from __future__ import annotations

import asyncio
import httpx
from typing import Any

from tonyagent.tools.base import Tool, ToolResult, ToolResultStatus, ToolCategory, register_tool
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


@register_tool
class HttpRequestTool(Tool):
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

        # SSRF guard. Deliberately keyed on tools.allow_internal_http, NOT on
        # sandbox.enable_network: the sandbox setting governs the container's
        # egress, not what the host can be told to fetch. The previous version
        # inverted this, so with the network default now False it *allowed*
        # internal hosts by default.
        from urllib.parse import urlparse

        parsed = urlparse(url)
        if _is_internal_host(parsed.hostname or ""):
            if not settings.tools.allow_internal_http:
                return ToolResult(
                    status=ToolResultStatus.ERROR,
                    error=(
                        f"Blocked request to internal address "
                        f"'{parsed.hostname}'. This blocks loopback, private, and "
                        f"link-local targets (including 169.254.169.254 cloud "
                        f"metadata). Set tools.allow_internal_http=true to allow."
                    ),
                )
        
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
                
                return ToolResult(
                    status=status,
                    output=output,
                    error=error,
                )
        except httpx.TimeoutException:
            return ToolResult(status=ToolResultStatus.ERROR, error=f"Request timed out after {timeout}s")
        except Exception as e:
            return ToolResult(status=ToolResultStatus.ERROR, error=str(e))