"""OpenCode Go, OpenAI-compatible. See `vendors` for what is and is not asserted.

Go is a subscription gateway over a curated set of open coding models -- the
same shape as OpenRouter, which is why the pair of them is a coherent set to
keep: both are aggregators that publish model metadata, so the catalogue work
has two implementations rather than six, and neither is an OpenAI-shaped vendor
that answers `/models` with an id and nothing else.

`/chat/completions` is the endpoint used here. The service also offers
`/messages` (Anthropic-shaped) and `/responses`, and neither is a reason to
write a second dialect: this app speaks chat-completions, and Go serves it.

**`models` is empty, and that is not an oversight.** Go's model ids are only
published by its own `/models` endpoint, which is behind the subscription key --
the documentation lists the models by *display* name ("Kimi K3", "Qwen3.8 Max"),
and a display name is not an id. Slugifying them would produce a list of
plausible identifiers that fail only when someone tried to send a message, so
the seed stays empty and the field's free text is the way in until a key is
available to read the real list. The composer's picker is unaffected: it fetches
the live list rather than reading this.
"""

from __future__ import annotations

from tonyagent.providers.base import register_provider
from tonyagent.providers.vendors import OpenAICompatibleVendor


@register_provider
class OpenCodeGoProvider(OpenAICompatibleVendor):
    #: Hyphenated, matching the path in the endpoint and the name the service
    #: uses for itself. The config stores it as-is, so it is also the string a
    #: user sees in the picker.
    name = "opencode-go"
    base_url = "https://opencode.ai/zen/go/v1"
    #: **Required by this gateway, and the reason it answers 400 without it.**
    #: Go's documentation asks each client to "send a stable session ID in
    #: `x-opencode-session` for each conversation so we can optimize routing and
    #: prompt caching", and a request without one is rejected rather than merely
    #: routed worse. `BaseLLMProvider` supplies a stable per-process id from the
    #: first request and `set_session` narrows it to the conversation, so this
    #: header is never absent; see `session_header` there.
    session_header = "x-opencode-session"
    #: Empty for the same reason `models` is: a default model id would have to
    #: be guessed from a display name. A turn sent without a model fails with
    #: the provider's own complaint, which is the honest outcome.
    default_model = ""
    models: list[str] = []
