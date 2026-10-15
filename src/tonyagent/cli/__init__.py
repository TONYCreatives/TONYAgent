"""The terminal frontend: a REPL over the headless core's JSONL protocol.

`tonyagent.window` and this package are two frontends of one core. Neither owns
the agent: the loop, the tools, the gates and the event bus all live in
`tonyagent.core` and are reached the same way -- over newline-delimited JSON on
a pipe. That is why this can exist at all without touching the core, and why it
is a frontend rather than a second implementation.

**What this is for.** The window costs a webview: a few hundred MB of resident
memory and the React render pass on every token, on a machine where the turn
itself is waiting on the network anyway. Removing it makes startup immediate and
leaves the terminal free for everything else. It also makes the agent usable
over SSH or in a container with no display, which the window cannot be at all.

**What this is not.** It is not faster *at the agent*. The core was already a
child process with no display attached; the window was never in the critical
path of a turn. A call to a model takes the same time here as it does there.

The deliberate omissions, so they are decisions rather than gaps: no project
explorer (the CLI has a real filesystem, and `ls` beats a TUI tree), no code
editor with syntax highlighting (`$EDITOR` is better at it), and no image
thumbnails (a terminal cannot show one usefully).
"""

from tonyagent.cli.repl import main

__all__ = ["main"]
