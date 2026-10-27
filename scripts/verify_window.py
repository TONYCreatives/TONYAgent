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
import json
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


#: Installs `window.__menuBox`, which reports where a menu landed.
#:
#: A menu is positioned by the stylesheet against its own trigger, so whether it
#: fits is a question only a layout engine can answer -- `menuPlacement.test.ts`
#: is arithmetic over rectangles its caller handed it, and the caller is the half
#: that can be wrong. This is the other half: the *pixels*, read out of the real
#: window, against the client rect.
#:
#: Both axes are compared, because both have been wrong here: the model picker
#: hung 320px off a chip in the title bar's right-hand cluster and was cut off by
#: the window's right edge, and a row menu opened downward from a click near the
#: floor of a short window and hid its own Delete below the client rect.
MENU_PROBE = (
    "window.__menuBox = (sel) => {"
    " const node = document.querySelector(sel);"
    " if (!node) return 'MISSING';"
    " const r = node.getBoundingClientRect();"
    " return JSON.stringify({"
    "  box: [Math.round(r.left), Math.round(r.top),"
    "        Math.round(r.right), Math.round(r.bottom)],"
    "  window: [window.innerWidth, window.innerHeight],"
    "  dir: node.dataset.dir ?? null,"
    "  align: node.dataset.align ?? null,"
    "  cap: node.style.maxHeight || 'none',"
    "  inside: r.left >= 0 && r.top >= 0"
    "   && r.right <= window.innerWidth && r.bottom <= window.innerHeight });"
    "};"
)


def menu_box(window: webview.Window, selector: str) -> str:
    """The menu's box, or an exception -- which is what `check` reports.

    Failing rather than reporting the numbers is the point: a menu half a pixel
    outside the window is the bug this file is here to catch, and a line that
    printed the box would pass the run.
    """
    raw = window.evaluate_js(f"window.__menuBox({selector!r})")
    if raw == "MISSING":
        raise AssertionError(f"{selector} is not on screen")
    data = json.loads(raw)
    if not data["inside"]:
        raise AssertionError(f"outside the window: {raw}")
    return raw


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
    # the whole distinction: since Phase 8 it is stroked in the registry's
    # frame like every other glyph (one cog outline, hub as second subpath),
    # never below 16px where the teeth would read as a sun.
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

    probe_workspace(window)
    probe_menus(window)

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


def probe_workspace(window: webview.Window) -> None:
    """The three-column shell, measured where it is actually painted.

    Phase 1 of the workspace refine is a geometry change, and geometry is the
    one thing `layout.test.ts` cannot see: it reads the cascade, not a layout
    engine. The numbers this prints are the plan's exit gate -- a centre of 824
    at 1400, 765 at 1101, 988 at 1100, 789 at 901 and 900 at 900 -- read from
    the same window the user gets.

    This runs at whatever size the window opened at, which is 1200x800 on a
    fresh install and whatever the user last dragged it to otherwise. The
    docking policy is therefore reported, not asserted against a width: a run
    at 1200 should show the nav docked at 288 and the context strip at 48, and a
    run at 1000 should show the rail at 64 with the panel as an overlay.
    """
    say("--- the workspace shell ---")
    check("columns, rows and the three panes", lambda: window.evaluate_js(
        "(() => {"
        " const app = document.querySelector('.app');"
        " if (!app) return 'MISSING';"
        " const cs = getComputedStyle(app);"
        " const box = (s) => {"
        "   const el = document.querySelector(s);"
        "   if (!el) return null;"
        "   const b = el.getBoundingClientRect();"
        "   return `${Math.round(b.left)}+${Math.round(b.width)}`;"
        " };"
        " return `view ${innerWidth}x${innerHeight};`"
        " + ` rows ${cs.gridTemplateRows}; cols ${cs.gridTemplateColumns};`"
        " + ` nav ${app.dataset.nav} rail ${box('.rail')} list ${box('.chatlist')};`"
        " + ` centre ${box('.main')}; context ${app.dataset.context} ${box('.contextdock')}`;"
        "})()"
    ))
    check("the strip spans the window, and is not the centre's child", lambda: window.evaluate_js(
        "(() => {"
        " const bar = document.querySelector('.statusbar');"
        " const app = document.querySelector('.app');"
        " if (!bar || !app) return 'MISSING';"
        " const b = bar.getBoundingClientRect();"
        " const a = app.getBoundingClientRect();"
        " return `${Math.round(b.width)} of ${Math.round(a.width)},`"
        " + ` parent .${bar.parentElement.className},`"
        " + ` ${getComputedStyle(bar).gridColumn} / ${getComputedStyle(bar).gridRow}`;"
        "})()"
    ))
    check("the run panel opens", lambda: window.evaluate_js(
        "(() => {"
        " const strip = document.querySelector('.context-strip');"
        " if (!strip) return 'MISSING';"
        " strip.click();"
        " return 'clicked';"
        "})()"
    ))
    time.sleep(0.5)
    check("and below 1400 it floats rather than taking a column", lambda: window.evaluate_js(
        "(() => {"
        " const dock = document.querySelector('.contextdock');"
        " const panel = document.querySelector('.context-panel');"
        " const centre = document.querySelector('.main');"
        " if (!dock || !panel || !centre) return 'MISSING';"
        " const p = panel.getBoundingClientRect();"
        " const c = centre.getBoundingClientRect();"
        " return `state ${dock.dataset.state}, docked ${dock.dataset.docked},`"
        " + ` panel ${Math.round(p.width)}x${Math.round(p.height)} at ${Math.round(p.left)},`"
        " + ` ${getComputedStyle(panel).position}, centre ${Math.round(c.width)}`;"
        "})()"
    ))
    check("and it closes again", lambda: window.evaluate_js(
        "(() => {"
        " const close = document.querySelector('.context-toggle');"
        " if (!close) return 'MISSING';"
        " close.click();"
        " return 'clicked';"
        "})()"
    ))
    time.sleep(0.4)


def probe_menus(window: webview.Window) -> None:
    """Where the two anchored menus land, in a real layout.

    This is the check this class of bug never had, and it is here rather than in
    the stylesheet tests because a menu is positioned by CSS *against its own
    trigger*: whether it fits is a question only a layout engine can answer, and
    both failures were found by opening one in the running window. The model
    picker is anchored to a chip in the title bar's right-hand cluster, so its
    320px panel ran from that chip's left edge off the right-hand edge of the
    window -- "the modal is cropped by the window" -- and a row menu opened
    downward from a press near the floor of a short window put its own Delete
    below the client rect.

    Both are measured now (`menuPlacement.ts`) and this reads where they landed.
    The window is resized to 640x480 -- the minimum `host.py` sets -- for the
    second half of each, because neither answer is a constant: the same menu
    opens down or up, and hangs left or right, depending on the room it finds.
    """
    say("--- the menus, measured ---")
    window.evaluate_js(MENU_PROBE)
    window.evaluate_js("document.querySelector('.modelpicker-wrap .chip')?.click()")
    time.sleep(1.0)
    check("the model menu is inside the window", lambda: menu_box(window, ".modelpicker"))

    # Opened again at the smallest window this app may be made, where the room to
    # the left of the chip is as short as it ever gets. Nothing about the
    # placement is a constant, so this is the same check with different numbers
    # rather than a second code path.
    window.evaluate_js("document.querySelector('.modelpicker-wrap .chip')?.click()")
    window.resize(640, 480)
    time.sleep(1.0)
    window.evaluate_js("document.querySelector('.modelpicker-wrap .chip')?.click()")
    time.sleep(1.0)
    check(
        "the model menu is inside a 640x480 window too",
        lambda: menu_box(window, ".modelpicker"),
    )
    window.evaluate_js("document.querySelector('.modelpicker-wrap .chip')?.click()")

    # Best effort by design: a window with no conversations has no row to press,
    # and that is not a failure of the placement.
    def open_row_menu(pointer: str) -> str:
        """`pointer` is a JS expression for the press's `clientY`.

        An expression rather than a number because the interesting points are
        relative to the row and to the window, and both are only known in there.
        """
        rows = window.evaluate_js(
            "(() => {"
            " const list = document.querySelector('.chatlist-rows');"
            " if (!list) return 0;"
            " list.scrollTop = list.scrollHeight;"
            " return list.querySelectorAll('.chatrow').length;"
            " })()"
        )
        if not rows:
            return "no conversations to open a menu on"
        y = window.evaluate_js(
            "(() => {"
            " const rows = [...document.querySelectorAll('.chatrow')];"
            " const r = rows[rows.length - 1].getBoundingClientRect();"
            f" const y = Math.round({pointer});"
            " rows[rows.length - 1].dispatchEvent(new MouseEvent('contextmenu', {"
            "  bubbles: true, clientX: Math.round(r.left + 24), clientY: y }));"
            " return y;"
            " })()"
        )
        time.sleep(0.8)
        return f"pressed at y={y}, " + menu_box(window, ".rowmenu")

    check(
        "the row menu is inside a 640x480 window",
        lambda: open_row_menu("r.bottom - 4"),
    )

    # And the same press near the window's *floor*, which is the geometry the
    # report came from and the one that has to answer `up`. Dispatched with the
    # pointer low rather than on a low row: the menu is anchored to the press, so
    # the press is the whole of the question -- and a list with three chats in it
    # has no row near the bottom to press on.
    def row_menu_above_the_floor() -> str:
        raw = open_row_menu("window.innerHeight - 60")
        if raw == "no conversations to open a menu on":
            return raw
        bottom = json.loads(raw[raw.index("{") :])["box"][3]
        floor = window.evaluate_js("window.innerHeight") - 60
        if bottom > floor:
            raise AssertionError(
                f"the menu opened below the press instead of above it: {raw}"
            )
        return raw

    check("and it opens upward from a press near the floor", row_menu_above_the_floor)


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

