"""End-to-end check of the new window host, against the real build.

Drives exactly the objects ``python -m tonyagent.window`` drives -- the asset
server, the core process, the bridge and the window -- and probes the page from
the host side.

Written the way ``diag.py`` is, because the first version of this file hung and
left nothing behind to say why: faulthandler on, every line flushed to a file
the instant it is written, and a watchdog that closes the window whether the
probe finished or not. A verification script that can only report success is
worse than no verification script.
"""

from __future__ import annotations

import faulthandler
import sys
import threading
import time

faulthandler.enable()

import webview  # noqa: E402 - after faulthandler, deliberately

from tonyagent.window import win32  # noqa: E402
from tonyagent.window.assets import AssetServer  # noqa: E402
from tonyagent.window.bridge import Bridge  # noqa: E402
from tonyagent.window.core import CoreProcess, default_argv, source_env  # noqa: E402
from tonyagent.window.host import DRAG_CLASS, build_window, default_dist  # noqa: E402

LOG = open("verify.log", "w", buffering=1, encoding="utf-8")  # noqa: SIM115 - lives for the process

#: Set by ``main`` from ``--no-core``.
WITH_CORE = True

#: Every request the *app* sent through the bridge, in order. Filled by the
#: wrapper ``main`` puts around ``Bridge.send``, which is the only place a
#: request from the page is visible from out here.
SENT: list[str] = []


def say(message: str) -> None:
    LOG.write(f"{time.strftime('%H:%M:%S')} {message}\n")
    LOG.flush()


def check(label: str, fn: object) -> None:
    try:
        say(f"  [OK]   {label}: {fn()}")  # type: ignore[operator]
    except Exception as exc:  # noqa: BLE001 - the failure is the result
        say(f"  [FAIL] {label}: {type(exc).__name__}: {exc}")


def probe(window: webview.Window, core: CoreProcess, bridge: Bridge) -> None:
    # Wait for the page, not for a duration.
    #
    # This is the one trap in the whole host, and it cost two hung runs to find:
    # `evaluate_js` before the document is ready *deadlocks*. The script is
    # handed to the webview, the result callback never fires, and the semaphore
    # `evaluate_js` waits on is never released -- so the calling thread is stuck
    # forever with no error and no timeout. A fixed sleep only makes it likely
    # to be late enough, and the first version of this file slept 2.5s while the
    # core was importing its SDKs and the page took longer than that to load.
    #
    # `Bridge` is built around this: frames are buffered until the page calls
    # `ready()`, which it can only do once it is running. That is not tidiness,
    # it is the difference between a slow start and a hung window.
    # A bounded sleep rather than `window.events.loaded.wait()`.
    #
    # The wait is bounded too, but a thread blocked inside pywebview's own event
    # plumbing looks exactly like one blocked in `evaluate_js`, and this file
    # exists to tell those apart. Eight seconds is well past the ~3s this page
    # takes to load, even with the core importing its SDKs at the same time.
    time.sleep(8.0)
    say("--- the page ---")
    check("title", lambda: window.evaluate_js("document.title"))
    check("origin", lambda: window.evaluate_js("location.origin"))
    check("react mounted", lambda: window.evaluate_js(
        "document.getElementById('root').childElementCount"
    ))
    check("inter loaded", lambda: window.evaluate_js("document.fonts.check('14px Inter')"))

    say("--- the bridge ---")
    check("pywebview global", lambda: window.evaluate_js("typeof window.pywebview"))
    check("api object", lambda: window.evaluate_js("typeof window.pywebview.api"))
    check("api.send", lambda: window.evaluate_js("typeof window.pywebview.api.send"))
    check("api.ready", lambda: window.evaluate_js("typeof window.pywebview.api.ready"))
    check("api.pick_folder", lambda: window.evaluate_js(
        "typeof window.pywebview.api.pick_folder"
    ))
    check("api.window_control", lambda: window.evaluate_js(
        "typeof window.pywebview.api.window_control"
    ))

    say("--- the window ---")
    check("native handle", lambda: int(window.native.Handle.ToInt64()))
    check("root window", lambda: win32.root_window(int(window.native.Handle.ToInt64())))
    check("rounded corners", lambda: win32.round_corners(
        win32.root_window(int(window.native.Handle.ToInt64()))
    ))
    check("maximized", lambda: win32.is_maximized(
        win32.root_window(int(window.native.Handle.ToInt64()))
    ))
    check("drag regions in the page", lambda: window.evaluate_js(
        f"document.querySelectorAll('.{DRAG_CLASS}').length"
    ))
    # Where the mark actually lands, in CSS pixels from the window's own corner.
    # The interesting number is `left`/`top`: the mark is the window's top-left
    # corner or it is not, and no assertion in the stylesheet tests can see that.
    check("the mark's corner", lambda: window.evaluate_js(
        "(() => {"
        " const m = document.querySelector('.topbar-mark');"
        " if (!m) return 'MISSING';"
        " const r = m.getBoundingClientRect();"
        " const g = m.querySelector('svg').getBoundingClientRect();"
        " return `box ${Math.round(r.left)},${Math.round(r.top)}`"
        " + ` ${Math.round(r.width)}x${Math.round(r.height)}`"
        " + ` / glyph ${Math.round(g.width)}px at ${Math.round(g.left)}`;"
        "})()"
    ))

    # And the rail has no mark of its own.
    #
    # It carried one until the mark moved to this corner, and that copy stayed
    # behind -- so the window drew the same drawing twice, 22px here and 32px
    # there, 64px apart, which is what made the rail's one read as a second logo.
    # Asserted as an *absence*, because the failure is the presence of a second
    # one: a check that the rail draws the right glyph would pass with the glyph
    # in the wrong place, and the wrong place is the whole failure.
    #
    # `rect` rather than a class, for the second half: every glyph the rail does
    # draw is a `path` -- the toggle, search and stop are stroked outlines and the
    # gear is one filled silhouette -- so a `rect` inside the strip can only be
    # the mark's two strokes, wherever they are put.
    check("the rail draws no mark", lambda: window.evaluate_js(
        "(() => {"
        " const logo = document.querySelectorAll('.rail-logo').length;"
        " const rects = document.querySelectorAll('.rail svg rect').length;"
        " const corner = document.querySelectorAll('.topbar-mark svg rect').length;"
        " const empty = document.querySelectorAll('.empty-mark rect').length;"
        " return `corner ${corner} rects, first-run ${empty},`"
        " + ` rail ${rects} rects in ${logo} .rail-logo box(es)`;"
        "})()"
    ))

    # And the strip is a strip: tabs cut out of the bar's full height, each with a
    # close glyph, and a "+" after them. The radius is reported as the browser
    # computes it, which is the only way to see that the lower two corners are
    # square -- `0px` never appears in the stylesheet's own text.
    check("the tab strip", lambda: window.evaluate_js(
        "(() => {"
        " const el = document.querySelector('.tab');"
        " const bar = document.querySelector('.topbar').getBoundingClientRect();"
        " const tab = el?.getBoundingClientRect();"
        " if (!tab) return 'MISSING';"
        " return `${document.querySelectorAll('.tab').length} tab(s),`"
        " + ` first ${Math.round(tab.left)},${Math.round(tab.top)}`"
        " + ` ${Math.round(tab.width)}x${Math.round(tab.height)}`"
        " + ` in bar ..${Math.round(bar.bottom)}:`"
        " + ` ${Math.round(bar.bottom - tab.bottom)}px from the bottom,`"
        " + ` radius ${getComputedStyle(el).borderRadius},`"
        " + ` ${document.querySelectorAll('.tab-close').length} close(s),`"
        " + ` ${document.querySelectorAll('.tab-new').length} new`;"
        "})()"
    ))

    # The settings gear in both places, as the page has it. `fill`/`stroke` is
    # the whole distinction: it is the one glyph here that is filled rather than
    # stroked, because at 17px an outline gear reads as a sun.
    window.evaluate_js("document.querySelector('.rail-toggle')?.click()")
    time.sleep(0.8)
    check("the settings gear", lambda: window.evaluate_js(
        "(() => {"
        " const pick = (sel) => {"
        "  const e = document.querySelector(sel);"
        "  if (!e) return 'MISSING';"
        "  return e.getAttribute('fill') + '/' + e.getAttribute('stroke')"
        "   + '/' + e.getAttribute('fill-rule')"
        "   + '/' + e.querySelectorAll('path').length + ' path';"
        " };"
        " return 'rail: ' + pick('.rail-btn[aria-label=\"Settings\"] svg')"
        "  + ' ; sidebar: ' + pick('.chatlist-act[aria-label=\"Settings\"] svg');"
        "})()"
    ))

    # And the foot is at the panel's *bottom*, which is the other thing no
    # stylesheet test can see.
    #
    # With an empty conversation list -- which is what a fresh window has --
    # `.chatlist-rows` is not rendered at all, so the only thing that can push the
    # foot down is `.chatlist-empty`, and it had nothing to push with. Measured
    # before the fix: the foot sat 218px into a 712px panel, which is what "the
    # settings button is not at the bottom of the sidebar" looks like.
    check("the sidebar's foot is at its bottom", lambda: window.evaluate_js(
        "(() => {"
        " const p = document.querySelector('.chatlist')?.getBoundingClientRect();"
        " const f = document.querySelector('.chatlist-foot')?.getBoundingClientRect();"
        " if (!p || !f) return 'MISSING';"
        " return `foot ${Math.round(f.top)}..${Math.round(f.bottom)}`"
        " + ` in panel ..${Math.round(p.bottom)}:`"
        " + ` ${Math.round(p.bottom - f.bottom)}px from the bottom`;"
        "})()"
    ))

    # And the list above the foot is one folder's chats, named.
    #
    # The grouping is gone entirely: there is no `.chatproj` in the page at all,
    # and the heading is the folder itself -- a *control*, because the folder is
    # what the list is scoped to and therefore what has to be changeable from
    # here. A heading that is not a button would leave the pane with no way to
    # change folders.
    check("the list is scoped to one folder", lambda: window.evaluate_js(
        "(() => {"
        " const folder = document.querySelector('.chatlist-folder');"
        " const groups = document.querySelectorAll('.chatproj').length;"
        " if (!folder) return 'MISSING';"
        " const name = folder.querySelector('.chatlist-folder-name');"
        " return `heading '${name?.textContent ?? ''}' over`"
        " + ` ${document.querySelectorAll('.chatrow').length} row(s),`"
        " + ` title ${folder.title ? 'set' : 'EMPTY'},`"
        " + ` ${groups} project group(s)`;"
        "})()"
    ))

    # And the composer's focus is said once.
    #
    # **A text input matches `:focus-visible` on a mouse click** -- the browser's
    # heuristic, not this app's -- so the field drew the global ring inside a card
    # that already takes its own border to `--accent`. Clicking a chat in the
    # sidebar focuses the composer, so that was the blue rectangle: measured at
    # 758x63 with `outline-offset: 2px`, two blue boxes saying one thing.
    check("the composer's focus is said once", lambda: window.evaluate_js(
        "(() => {"
        " const card = document.querySelector('.composer-inner');"
        " const field = document.querySelector('.composer textarea');"
        " if (!card || !field) return 'MISSING';"
        " field.focus();"
        " return 'focused';"
        "})()"
    ))
    # Read on its own, after the border-color transition has run. The two calls are
    # not tidiness: read inline, this reported the *unfocused* border on a card
    # that was about to have the right one.
    time.sleep(0.5)
    check("and the card's own border says so", lambda: window.evaluate_js(
        "(() => {"
        " const card = document.querySelector('.composer-inner');"
        " const field = document.querySelector('.composer textarea');"
        " const cs = getComputedStyle(field);"
        " const ring = cs.outlineStyle === 'none' ? 'no ring' : `ring ${cs.outline}`;"
        " return `${ring}, focus-visible ${field.matches(':focus-visible')},`"
        " + ` within ${card.matches(':focus-within')},`"
        " + ` card border ${getComputedStyle(card).borderColor}`;"
        "})()"
    ))

    say("--- the core, the whole way round ---")
    if not WITH_CORE:
        say("  [SKIP] no core was started for this run")
        window.destroy()
        return
    check("core alive", lambda: core.alive)

    # The strongest check in this file, and the only one that exercises the
    # whole seam: the *app* calls `state` on mount through its own backend, so a
    # request arriving in `SENT` means bridge.ts, `whenHostReady`, the transport
    # and the JSONL framing above it all worked together. Nothing here tells the
    # page to do anything -- if the seam is broken, the app sits on
    # "disconnected" and `SENT` stays empty.
    for _ in range(60):
        if SENT:
            break
        time.sleep(0.25)
    check("requests the app sent", lambda: [line[:60] for line in SENT])

    # And the replies came back: the push path is what puts the core's answer
    # into the page, and the app's own state is the evidence that it arrived.
    time.sleep(2.0)
    check("what the window says now", lambda: window.evaluate_js(
        "document.body.innerText.replace(/\\s+/g, ' ').slice(0, 260)"
    ))
    check("model picker filled in", lambda: window.evaluate_js(
        "document.querySelectorAll('.modelpicker, .composer, .statusbar').length"
    ))
    window.destroy()


def watchdog(window: webview.Window) -> None:
    time.sleep(20)
    say("[watchdog] closing the window")
    try:
        window.destroy()
    except Exception as exc:  # noqa: BLE001
        say(f"[watchdog] destroy failed: {exc}")


def main() -> None:
    global WITH_CORE  # noqa: PLW0603 - one flag for the run, set once
    WITH_CORE = "--no-core" not in sys.argv
    say(f"python {sys.version.split()[0]}, with_core={WITH_CORE}")

    server = AssetServer(default_dist())
    origin = server.start()
    say(f"serving {origin}")

    bridge = Bridge()
    core = CoreProcess(
        default_argv(),
        bridge._frames,
        on_stderr=bridge._log,
        on_exit=bridge._core_exit,
        env=source_env(),
    )
    if WITH_CORE:
        core.start()
        say("core started")

    # Wrap `send` *before* the window exists. pywebview reads the js_api's
    # methods when the page loads, so an attribute patched after that would
    # never be the one it calls.
    original_send = bridge.send

    def counting_send(line: str) -> object:
        SENT.append(line)
        return original_send(line)

    bridge.send = counting_send  # type: ignore[method-assign]

    window = build_window(f"{origin}/index.html", bridge)
    bridge._attach(core, window)
    say("window created")

    threading.Thread(target=probe, args=(window, core, bridge), daemon=True).start()
    threading.Thread(target=watchdog, args=(window,), daemon=True).start()

    say("entering the GUI loop")
    webview.start()
    say("GUI loop returned")

    core.stop()
    server.stop()
    say("clean exit")


if __name__ == "__main__":
    main()

