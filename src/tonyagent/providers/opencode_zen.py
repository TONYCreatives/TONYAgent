"""OpenCode Zen, OpenAI-compatible. See `vendors` for what is and is not asserted.

Zen is OpenCode's pay-as-you-go gateway over the same curated model set its Go
subscription serves. It is a separate service with its own key, its own balance
and a *different* catalogue from Go -- Go returns 37 ids, Zen returns 86 -- so
it is a provider here rather than a second base URL on the Go one.

**A Go subscription key does not carry Zen credit.** Sending one is accepted and
then answered `402 Insufficient account funds`, because the two bill separately.
That is worth writing down because it is the obvious thing to try: the key you
already have authenticates, the catalogue loads, and every request fails for a
reason that looks like a bug in here rather than an empty balance.

**The free models cannot be reached from here at all, by design.** Every `-free`
id -- `space-bunny-free`, `cat-jam-free`, `longcat-2.5-preview-free` -- answers:

    403 {"type":"FreeTierError","message":"OpenCode's free tier can only be
         used from within OpenCode."}

That is not a missing header or an absent key: it was the same with no
credentials at all, and the same with a valid one. The free tier is a funnel
into OpenCode's own client, so the honest thing is to leave those ids in the
live catalogue and let the provider's own 403 stand, rather than filtering them
out here and making the list look complete while the models cannot run.

`models` is empty for the reason it is empty on the Go provider: the ids are
published only by `/models`, and a display name is not an id.
"""

from __future__ import annotations

from tonyagent.providers.base import register_provider
from tonyagent.providers.vendors import OpenAICompatibleVendor


@register_provider
class OpenCodeZenProvider(OpenAICompatibleVendor):
    #: `zen`, not `opencode`, because the path is `/zen/v1` and the service
    #: calls itself Zen. The config stores it as-is, so this is also the string
    #: the picker shows -- and it needs to be distinguishable from `opencode-go`
    #: at a glance, because they are different services with different bills.
    name = "opencode-zen"
    base_url = "https://opencode.ai/zen/v1"
    #: Zen asks clients for the same stable session id as Go, for routing and
    #: prompt caching. Harmless if it is not required, and the id is always
    #: present -- see `session_header` in `base`.
    session_header = "x-opencode-session"
    #: Empty, for the same reason as on Go: a default id would have to be
    #: guessed from a display name.
    default_model = ""
    models: list[str] = []
