"""The window's palette, ported to a terminal.

Every value here is read from `app/src/styles/tokens.css`. Nothing is invented
and nothing is borrowed from another application, because the point of this
frontend is that it is the same product as the window -- a person should not
be able to tell from the colours which one they opened.

**The rule that decides everything else is in the header of that file:**

    Every one of those is achromatic -- r === g === b, with no tint. That is
    the one deliberate change of character in this file, and it is the whole
    reason the window stopped looking borrowed. [...] Here the accent is the
    only chroma on screen, so it means "this application" rather than
    "something coloured".

So there is no violet heading and no amber bold here, however good they looked
in someone else's terminal. The accent is the only colour, exactly as in the
window, and the semantic exceptions (`ok`, `danger`, `warn`, and the trajectory
add/delete pair) are the four the window already spends them on.

**Why these are truecolor and not the 256-colour cube.** The accent `#6393f0`
and the neutrals in between are chosen against measured contrast ratios on a
`#1a1a1a` field (`--fg-mute` is 5.04:1, which is why it moved off the old
`#7c807a` at 4.21:1). Snapping any of them to the nearest xterm-256 entry
moves them by up to 20 per channel, which is the same size as the gap the
ratios were chosen on -- so the palette would quietly stop being the one the
window uses. A terminal that cannot do truecolor gets the achromatic ladder
only, which is the part that survives quantisation intact.
"""

from __future__ import annotations

import os
import sys

#: The two ladders, from `tokens.css`. Depth for surfaces, legibility for text.
BG = "#1a1a1a"
SURFACE = "#202020"
CHROME = "#262626"
INPUT = "#2b2b2b"
RAISED = "#333333"
CHIP = "#3d3d3d"
HOVER = "#383838"

BORDER_SOFT = "#2e2e2e"
BORDER = "#3a3a3a"
BORDER_STRONG = "#4a4a4a"

FG = "#ececec"
FG_DIM = "#a8a8a8"
FG_MUTE = "#8a8a8a"

#: Read out of this app's own icon: the darkest ramp step that still clears
#: 4.5:1 on `--bg`. Not `#2f6feb` itself -- that is the icon's ground, and at
#: 3.81:1 it is fine as a fill and short of what text-sized accent needs.
ACCENT = "#6393f0"
ACCENT_FG = "#0b1020"
ACCENT_BRIGHT = "#97b7f5"

OK = "#a3c48a"
DANGER = "#c9705f"
DANGER_FG = "#1a0a08"
WARN = "#c9a45f"

#: The diff pair. A terminal can do a wash, so these carry as background too.
TRAJ_ADD = "#7ee2a8"
TRAJ_DEL = "#f2a0a0"


#: Every colour below is emitted as hex, always, on every terminal.
#:
#: **The first version converted to xterm-256 by hand when `COLORTERM` was
#: unset, and produced `color234`.** That is Rich's internal spelling, not a
#: value Textual's CSS parser accepts, so the whole stylesheet failed to parse
#: and the interface refused to start -- on exactly the terminals the fallback
#: was written for.
#:
#: It was also redundant. Rich quantises a hex colour to whatever the terminal
#: can actually show, at draw time: a pty with no `COLORTERM` rendered
#: `#1a1a1a` as `48;5;234` without being asked. So the conversion was doing a
#: job already done, and doing it into a syntax the parser rejects.
#:
#: Hex is therefore the only spelling here, and it is correct on a truecolor
#: terminal, on a 256-colour one, and on an 8-colour one, because in each case
#: Rich does the reduction and the palette lands as close to the window's as
#: the terminal allows.


def truecolor_supported() -> bool:
    """Whether this terminal can be sent 24-bit colour.

    Reported for diagnostics only. Nothing here branches on it: the palette is
    hex either way, because Rich reduces it at draw time. Kept because "is
    this terminal lying about colour?" is the first question when a palette
    looks wrong, and the answer should not need a debugger.
    """
    if os.environ.get("COLORTERM", "").lower() in {"truecolor", "24bit"}:
        return True
    return "256color" in os.environ.get("TERM", "")


#: The Textual CSS for the whole app, built from the tokens above.
#:
#: A generated string rather than a `.tcss` file because the values have to
#: come from one place. A stylesheet that repeated `#1a1a1a` in a dozen rules
#: would be a second place for the palette to be wrong, which is the failure
#: `tokens.css` itself documents having hit four times.
#: The marker in front of the user's own message.
#:
#: A single right-pointing angle quotation mark, rather than `>`, because the
#: two are not the same sign -- one is a quotation mark and the other an
#: arrow -- and the point is to say "this was said, by you". `prompt_marker`
#: degrades it, because a terminal that cannot draw it renders a literal `?`,
#: which is worse than an arrow.
PROMPT_MARKER = "›"  # noqa: RUF001 - guarded by `prompt_marker`


#: The bar in front of the open tab, standing in for a selected tab's
#: highlight. A terminal has no tab highlight, so this is the marker that says
#: "this one", and it degrades to `|` for the same reason the others do.
TAB_MARKER = "▌"  # noqa: RUF001 - guarded by `tab_marker`


def tab_marker() -> str:
    """The tab bar where the terminal can draw it, `|` where it cannot."""
    return TAB_MARKER if supports_unicode() else "|"


def prompt_marker() -> str:
    """The quoting mark where the terminal can draw it, `>` where it cannot."""
    return PROMPT_MARKER if supports_unicode() else ">"


def build_css() -> str:
    return f"""
    Screen {{
        background: {BG};
        color: {FG};
        layout: vertical;
    }}

    /* The open tab, at the very top: one row, always visible, above the
       transcript and the sidebar. It is the chrome's only fixed element --
       everything else moves with the session, and this is what tells you which
       session it is. */
    #topbar {{
        background: {CHROME};
        height: 1;
        color: {FG_MUTE};
    }}

    /* The transcript. `--measure` (760px) is the window's column width; a
       terminal has no px, so it becomes a character count at roughly the same
       line length, and the sidebar is hidden on narrow terminals rather than
       squeezing the messages into a column too short to read. */
    #transcript {{
        background: {BG};
        padding: 0 2;
        scrollbar-size-vertical: 1;
        overflow-y: auto;
    }}
    #transcript:focus {{
        background: {BG};
    }}

    /* A turn's body, fenced by a left rule. This is the single most important
       structural mark in the interface: it says where one exchange begins and
       ends without printing a horizontal line at every boundary. */
    .turn {{
        height: auto;
        margin: 1 0 0 0;
    }}
    .turn-rule {{
        border-left: thick {ACCENT};
        padding: 0 0 0 2;
    }}
    /* The user's own message. The window calls it a chip on `--raised`, and a
       terminal has no bubbles, so the fill is what says "this was me" --
       narrower than the prose under it, which is what makes it read as a chip
       rather than as part of the answer. */
    .prompt {{
        background: {RAISED};
        color: {FG};
        height: auto;
        margin: 0;
        padding: 0 1;
    }}
    .answer {{
        height: auto;
    }}

    /* A tool call: one dimmed line, the way a build log reads. */
    .tool {{
        color: {FG_MUTE};
        height: auto;
        text-style: none;
    }}
    .tool-done {{
        color: {FG_DIM};
    }}
    .tool-failed {{
        color: {DANGER};
    }}

    /* Reasoning is present but subordinate: the window dims it, and a terminal
       has no dim, so it is `--fg-mute` with a marker. */
    .reasoning {{
        color: {FG_MUTE};
        height: auto;
        text-style: italic;
    }}

    /* The per-turn footer: mode, model, elapsed, throughput. */
    .turn-footer {{
        color: {FG_MUTE};
        height: auto;
        margin: 0 0 1 0;
        text-style: none;
    }}

    /* The composer. In the window it is an input surface with an accent rule;
       here it is a bordered field, because a terminal has no elevation and a
       box is how it fakes one. */
    #composer {{
        background: {INPUT};
        border: tall {BORDER};
        height: 3;
        padding: 0 1;
    }}
    #composer:focus {{
        border: tall {ACCENT};
    }}

    /* The status bar: the window's `--topbar-h` equivalent, one line. */
    #status {{
        background: {CHROME};
        color: {FG_MUTE};
        height: 1;
        padding: 0 2;
    }}
    #status.bound {{
        color: {FG_DIM};
    }}

    /* The sidebar: mode, model, and the context meter. */
    #sidebar {{
        background: {SURFACE};
        border-left: solid {BORDER};
        width: 38;
        padding: 1 1;
    }}
    .side-title {{
        color: {FG};
        text-style: bold;
        height: auto;
    }}
    .side-label {{
        color: {FG_MUTE};
        height: auto;
    }}
    .side-value {{
        color: {FG_DIM};
        height: auto;
    }}
    .side-warn {{
        color: {WARN};
        height: auto;
    }}
    .side-danger {{
        color: {DANGER};
        height: auto;
    }}

    /* A confirmation is the one thing that must stop the eye. The window dims
       the page behind a modal; a terminal cannot dim, so it marks the prompt
       in the one colour it is allowed. */
    .confirm {{
        background: {SURFACE};
        border: round {WARN};
        width: 64;
        height: auto;
        padding: 1 2;
    }}
    .confirm-destructive {{
        border: round {DANGER};
    }}

    /* A confirmation is a real dialog, centred, and it takes the keyboard.
       The window dims the page behind its own; a terminal cannot dim, so it
       gets an opaque ground and a border in the one colour the state allows. */
    #confirm-dialog {{
        layer: dialog;
        width: 56;
        height: auto;
        padding: 1 2;
        background: {RAISED};
        border: round {WARN};
    }}
    #confirm-dialog.confirm-destructive {{
        border: round {DANGER};
    }}
    #confirm-dialog.hidden {{
        display: none;
    }}

    /* The inline command list, above the composer.
       *
       * Layered and docked to the bottom rather than placed in the layout,
       * because appearing in the layout would shrink the transcript by its own
       * height every time a `/` was typed -- the list would push the thing you
       * are reading. `offset` lifts it clear of the composer, the status bar
       * and the footer, which are the four rows underneath it. */
    #slash-menu {{
        layer: suggest;
        dock: bottom;
        offset: 0 -4;
        width: 100%;
        height: auto;
        max-height: 12;
        background: {RAISED};
        border: round {BORDER};
    }}
    #slash-menu.hidden {{
        display: none;
    }}
    #slash-menu > .option-list--option {{
        padding: 0 1;
    }}
    #slash-menu > .option-list--option-highlighted {{
        background: {ACCENT};
        color: {ACCENT_FG};
        text-style: bold;
    }}

    /* The pickers. Same shape as the dialog: a list the user picks from,
       rather than a value typed at a prompt and refused if it is a near miss. */
    #picker {{
        layer: dialog;
        width: 56;
        height: 18;
        background: {RAISED};
        border: round {ACCENT};
    }}
    #picker.hidden {{
        display: none;
    }}

    /* A file change. The header is the path and the counts; the diff below it
       is coloured with the same `--traj-add` / `--traj-del` pair the window
       uses, on the changed lines only -- a diff is mostly context, and
       colouring all three makes the two halves hard to find. */
    .change-head {{
        height: auto;
        margin: 0 0 0 1;
    }}
    .diff {{
        height: auto;
        margin: 0 0 0 1;
        padding: 0 0 0 1;
        background: {SURFACE};
    }}

    .error {{
        color: {DANGER};
        height: auto;
    }}
    .warn {{
        color: {WARN};
        height: auto;
    }}
    """


def supports_unicode() -> bool:
    """Whether box-drawing and spinner glyphs will render.

    ``LANG``/``LC_ALL`` unset means the C locale, and a terminal in it draws
    ``box.lite`` as literal ``?``. Textual asks the terminal rather than
    trusting the locale, but the fallback still has to be ASCII, because a
    REPL that prints ``?`` as a box is worse than one that prints ``|``.
    """
    if os.environ.get("TERM") == "dumb":
        return False
    encoding = (getattr(sys.stdout, "encoding", None) or "").lower()
    return "utf" in encoding


__all__ = [
    "ACCENT",
    "ACCENT_BRIGHT",
    "ACCENT_FG",
    "BG",
    "BORDER",
    "BORDER_SOFT",
    "BORDER_STRONG",
    "CHIP",
    "CHROME",
    "DANGER",
    "DANGER_FG",
    "FG",
    "FG_DIM",
    "FG_MUTE",
    "HOVER",
    "INPUT",
    "OK",
    "PROMPT_MARKER",
    "RAISED",
    "SURFACE",
    "TRAJ_ADD",
    "TRAJ_DEL",
    "WARN",
    "build_css",
    "prompt_marker",
    "supports_unicode",
    "truecolor_supported",
]
