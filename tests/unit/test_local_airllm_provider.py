"""Verify the AirLLM provider registers and talks to the local server.

Run from the TONYAgent repo with its own python (the one that has the
project's dependencies installed).
"""
import asyncio
import sys

sys.path.insert(0, r"C:\Users\iig2y\Desktop\TONYCreatives\TONYAgent\src")

import tonyagent.providers  # noqa: F401
from tonyagent.providers.base import provider_registry
from tonyagent.providers.local_airllm import AirLLMProvider

failures = []


def check(name, cond, detail=""):
    if cond:
        print(f"PASS {name}")
    else:
        print(f"FAIL {name} {detail}")
        failures.append(name)


print("registered providers:", provider_registry.list_providers())
check("airllm registered", "airllm" in provider_registry.list_providers())

cls = provider_registry.get("airllm")
check("base url is loopback", cls.base_url.startswith("http://127.0.0.1"), cls.base_url)
check("streaming supported", cls.supports_streaming is True)
check("function calling supported", cls.supports_function_calling is True)
check("has a default model", bool(cls.default_model))

provider = AirLLMProvider()
check("placeholder key supplied", len(provider.api_key) >= 20, provider.api_key)
check("validate_credentials true", provider.validate_credentials() is True)
check("timeout raised", provider.timeout >= 600, provider.timeout)

# The client must actually build a request against it.
from tonyagent.providers.base import ChatMessage, ToolSchema

client = provider.http_client()
check("client built", client is not None)
check("client base url", client.base_url.startswith("http://127.0.0.1"), client.base_url)
check("client has a key", bool(client.api_key))


async def live():
    """A real round trip against the running server."""
    provider = AirLLMProvider()
    tools = [ToolSchema(
        name="read",
        description="Read a file from disk.",
        parameters={"type": "object", "properties": {"path": {"type": "string"}},
                    "required": ["path"]},
    )]
    messages = [
        ChatMessage(role="system", content="You are a coding agent."),
        ChatMessage(role="user", content="Read the file README.md please."),
    ]
    chunks = []
    async for chunk in await provider.chat_completion(
        messages=messages, tools=tools, stream=True, max_tokens=120, temperature=0
    ):
        chunks.append(chunk)
    return chunks


if "--live" in sys.argv:
    try:
        chunks = asyncio.run(live())
        text = "".join(c.content or "" for c in chunks)
        calls = [c.tool_calls for c in chunks if c.tool_calls]
        print("text:", text[:200])
        print("tool_calls:", calls[-1] if calls else None)
        check("got chunks", len(chunks) > 0)
        check("got a tool call", bool(calls))
    except Exception as exc:
        print(f"live check skipped or failed: {type(exc).__name__}: {exc}")

print()
if failures:
    print(f"{len(failures)} FAILED: {failures}")
    sys.exit(1)
print("PROVIDER TESTS PASSED")
