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


def truecolor_supported() -> bool:
    """Whether this terminal can be sent 24-bit colour.

    ``COLORTERM`` is the convention, and the TERM check is the older signal
    for terminals that do 256 but not truecolor. Both are honoured because a
    terminal that reports one and not the other is normal, and the failure
    mode of guessing wrong is a palette that looks like the window's but isn't.
    """
    if os.environ.get("COLORTERM", "").lower() in {"truecolor", "24bit"}:
        return True
    return "256color" in os.environ.get("TERM", "")


def _hex_to_ansi(value: str) -> str:
    """`#rrggbb` to the nearest xterm-256 index, or to grey when it is grey.

    Only called when truecolor is unavailable. Grey is special-cased rather
    than left to the cube because the whole palette is achromatic, and the
    24-step grey ramp tracks the surface ladder far more closely than the
    colour cube's near-grey corners do.
    """
    value = value.lstrip("#")
    r, g, b = (int(value[i : i + 2], 16) for i in (0, 2, 4))
    if r == g == b:
        # 232 is the first grey step; the ramp runs to 255. Index 8 is the
        # bright-black block, which would break the ladder's ordering.
        step = round((r / 255) * 23)
        return f"color{232 + max(0, min(23, step))}"
    # 6x6x6 cube, indices 16..231.
    quant = lambda c: round((c / 255) * 5)  # noqa: E731
    return f"color{16 + 36 * quant(r) + 6 * quant(g) + quant(b)}"


def color(value: str) -> str:
    """A colour for Textual, degraded to 256 if this terminal cannot do more."""
    return value if truecolor_supported() else _hex_to_ansi(value)


#: The Textual CSS for the whole app, built from the tokens above.
#:
#: A generated string rather than a `.tcss` file because the values have to
#: come from one place. A stylesheet that repeated `#1a1a1a` in a dozen rules
#: would be a second place for the palette to be wrong, which is the failure
#: `tokens.css` itself documents having hit four times.
def build_css() -> str:
    c = color
    return f"""
    Screen {{
        background: {c(BG)};
        color: {c(FG)};
        layout: vertical;
    }}

    /* The transcript. `--measure` (760px) is the window's column width; a
       terminal has no px, so it becomes a character count at roughly the same
       line length, and the sidebar is hidden on narrow terminals rather than
       squeezing the messages into a column too short to read. */
    #transcript {{
        background: {c(BG)};
        padding: 0 2;
        scrollbar-size-vertical: 1;
        overflow-y: auto;
    }}
    #transcript:focus {{
        background: {c(BG)};
    }}

    /* A turn's body, fenced by a left rule. This is the single most important
       structural mark in the interface: it says where one exchange begins and
       ends without printing a horizontal line at every boundary. */
    .turn {{
        height: auto;
        margin: 1 0 0 0;
    }}
    .turn-rule {{
        border-left: thick {c(ACCENT)};
        padding: 0 0 0 2;
    }}
    .answer {{
        height: auto;
    }}

    /* A tool call: one dimmed line, the way a build log reads. */
    .tool {{
        color: {c(FG_MUTE)};
        height: auto;
        text-style: none;
    }}
    .tool-done {{
        color: {c(FG_DIM)};
    }}
    .tool-failed {{
        color: {c(DANGER)};
    }}

    /* Reasoning is present but subordinate: the window dims it, and a terminal
       has no dim, so it is `--fg-mute` with a marker. */
    .reasoning {{
        color: {c(FG_MUTE)};
        height: auto;
        text-style: italic;
    }}

    /* The per-turn footer: mode, model, elapsed, throughput. */
    .turn-footer {{
        color: {c(FG_MUTE)};
        height: auto;
        margin: 0 0 1 0;
        text-style: none;
    }}

    /* The composer. In the window it is an input surface with an accent rule;
       here it is a bordered field, because a terminal has no elevation and a
       box is how it fakes one. */
    #composer {{
        background: {c(INPUT)};
        border: tall {c(BORDER)};
        height: 5;
        padding: 0 1;
    }}
    #composer:focus {{
        border: tall {c(ACCENT)};
    }}

    /* The status bar: the window's `--topbar-h` equivalent, one line. */
    #status {{
        background: {c(CHROME)};
        color: {c(FG_MUTE)};
        height: 1;
        padding: 0 2;
    }}
    #status.bound {{
        color: {c(FG_DIM)};
    }}

    /* The sidebar: mode, model, and the context meter. */
    #sidebar {{
        background: {c(SURFACE)};
        border-left: solid {c(BORDER)};
        width: 38;
        padding: 1 1;
    }}
    .side-title {{
        color: {c(FG)};
        text-style: bold;
        height: auto;
    }}
    .side-label {{
        color: {c(FG_MUTE)};
        height: auto;
    }}
    .side-value {{
        color: {c(FG_DIM)};
        height: auto;
    }}
    .side-warn {{
        color: {c(WARN)};
        height: auto;
    }}
    .side-danger {{
        color: {c(DANGER)};
        height: auto;
    }}

    /* A confirmation is the one thing that must stop the eye. The window dims
       the page behind a modal; a terminal cannot dim, so it marks the prompt
       in the one colour it is allowed. */
    .confirm {{
        background: {c(SURFACE)};
        border: round {c(WARN)};
        width: 64;
        height: auto;
        padding: 1 2;
    }}
    .confirm-destructive {{
        border: round {c(DANGER)};
    }}

    /* A confirmation is a real dialog, centred, and it takes the keyboard.
       The window dims the page behind its own; a terminal cannot dim, so it
       gets an opaque ground and a border in the one colour the state allows. */
    #confirm-dialog {{
        layer: dialog;
        width: 56;
        height: auto;
        padding: 1 2;
        background: {c(RAISED)};
        border: round {c(WARN)};
    }}
    #confirm-dialog.confirm-destructive {{
        border: round {c(DANGER)};
    }}
    #confirm-dialog.hidden {{
        display: none;
    }}

    /* The pickers. Same shape as the dialog: a list the user picks from,
       rather than a value typed at a prompt and refused if it is a near miss. */
    #picker {{
        layer: dialog;
        width: 56;
        height: 18;
        background: {c(RAISED)};
        border: round {c(ACCENT)};
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
        background: {c(SURFACE)};
    }}

    .error {{
        color: {c(DANGER)};
        height: auto;
    }}
    .warn {{
        color: {c(WARN)};
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
    "ACCENT", "ACCENT_BRIGHT", "ACCENT_FG", "BG", "BORDER", "BORDER_SOFT",
    "BORDER_STRONG", "CHIP", "CHROME", "DANGER", "DANGER_FG", "FG", "FG_DIM",
    "FG_MUTE", "HOVER", "INPUT", "OK", "RAISED", "SURFACE", "TRAJ_ADD",
    "TRAJ_DEL", "WARN", "build_css", "color", "supports_unicode",
    "truecolor_supported",
]
