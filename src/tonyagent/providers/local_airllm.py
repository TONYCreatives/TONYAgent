"""AirLLM, running locally on this machine. See `vendors` for the shared shape.

This is the one provider that does not talk to somebody else's server: it
talks to `airllm_server.py`, an OpenAI-compatible front end for AirLLM that
runs on this machine's CPU.

**It is a local endpoint, so the base URL is `http://` and loopback.** The
registry's blanket "every provider declares an https endpoint" assertion is
relaxed for this one, and only for loopback hosts, in the test that checks it.

**No key, and none needed.** The server ignores the `Authorization` header.
The client, though, refuses to send a request without an API key -- an empty
key is a configuration error, not a free pass -- so this provider supplies a
placeholder of its own. Nothing is stored in the keyring, because there is no
secret to store: asking the user to paste one would be asking for a lie.

**Chat mode only.** These models run on this machine's CPU, and they are small
enough that asking one to pick a tool and call it correctly is asking for
something they cannot do. Every mode except Chat exists to have the model
*act*. So this provider is `chat_only`: it appears in Chat mode, it is
refused in the others, and it is sent no tool schemas at all. That last part
is not only correct but necessary -- the tool catalogue is 6,646 tokens, and
prefill on this machine is the bottleneck, so a local model would spend a
minute reading schemas before it read the question.

**The timeout is long on purpose.** AirLLM streams a model from disk and
computes on the CPU. A prompt with a full tool catalogue takes over a minute
to prefill, and a hosted gateway's 60 second default would abort the request
before the model had finished reading the question.

**`models` is a short list rather than empty.** The server answers `/models`
with the one model it has loaded, so the picker can be seeded from the same
list the server would report. The free-text field still works.
"""

from __future__ import annotations

from tonyagent.providers.base import register_provider
from tonyagent.providers.vendors import OpenAICompatibleVendor

#: The client refuses to send a request with no API key: an empty key is a
#: configuration error, not a free pass. This server ignores the header
#: entirely, so a placeholder satisfies the client without meaning anything.
#: It has to be long enough to clear the client's minimum-length check.
_PLACEHOLDER_KEY = "airllm-local-no-key-required"


@register_provider
class AirLLMProvider(OpenAICompatibleVendor):
    #: The name the config stores and the picker shows.
    name = "airllm"
    #: Loopback on purpose: the server runs on this machine.
    base_url = "http://127.0.0.1:8765/v1"
    #: Nothing is refused locally. The server ignores the header, but the
    #: client refuses to send a request with no key at all, so a placeholder
    #: has to exist in the keyring.
    key_prefix = ""
    #: The models this machine has available, fastest first.
    default_model = "Qwen/Qwen2.5-Coder-0.5B-Instruct"
    models: list[str] = [
        "Qwen/Qwen2.5-Coder-0.5B-Instruct",
        "Qwen/Qwen2.5-Coder-1.5B-Instruct",
        "Qwen/Qwen2.5-Coder-3B-Instruct",
        "Qwen/Qwen2.5-0.5B-Instruct",
    ]
    #: The server answers SSE and returns tool calls in OpenAI's shape, so
    #: both are true of it.
    supports_streaming = True
    supports_function_calling = True
    #: Chat mode only, and no tool schemas are sent to it. See the module
    #: docstring: the other modes need a model that can act, and these cannot.
    chat_only = True

    def __init__(
        self,
        api_key: str = "",
        model: str = "",
        base_url: str = "",
        extra_headers: dict[str, str] | None = None,
        timeout: int = 1800,
        max_retries: int = 1,
    ):
        # The defaults differ from `OpenAICompatibleVendor` on purpose: a
        # minute is not enough for a CPU model to read a tool catalogue, and a
        # retry of a request that was already half-answered is a second wait
        # for the same answer.
        super().__init__(
            api_key=api_key,
            model=model or self.default_model,
            base_url=base_url or self.base_url,
            extra_headers=extra_headers,
            timeout=timeout,
            max_retries=max_retries,
        )
        # No key is stored for this provider and none is needed. The client
        # will not send a request without one, so the placeholder goes here
        # rather than into the keyring: there is no secret to paste, and
        # asking the user for one would be asking for a lie.
        if not self.api_key:
            self.api_key = _PLACEHOLDER_KEY

    def validate_credentials(self) -> bool:
        """Always true: there are no credentials to check.

        The server ignores the ``Authorization`` header. Whether it is
        actually running is a different question, and ``check_connection``
        is the thing that answers it.
        """
        return True
