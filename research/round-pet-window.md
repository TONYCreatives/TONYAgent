# Research brief: a genuinely round (non-rectangular) WebView2 window on Windows 11

> ## UPDATE — the rectangle is explained, and it is fixed
>
> **The answer: the region was always working; DWM draws a window's drop shadow to
> the window's *rectangle*, not to its region.** The corners the region cut away
> were being filled by the shadow, so a round pet read on screen as a dark rounded
> square with a circle drawn inside it.
>
> Measured over a pure white backdrop, with the pet 180×180 in the middle of it
> (pixels 6px and 14px outside the window's rect):
>
> | spot | window hidden | window shown | after `DWMNCRP_DISABLED` |
> |---|---|---|---|
> | rect corner | 255 | 193–241 | **255** |
> | edge midpoint (where the circle touches) | 255 | 119–211 | **255** |
>
> A circle inscribed in a square touches that square's edges at their *midpoints*
> and misses the corners entirely — so a shadow following the region would be
> strong at the midpoints and absent at the corners. It was dark at **both**, which
> is what proves the shadow is rectangular.
>
> Earlier evidence that pointed the wrong way, recorded so nobody repeats it: a
> magenta-bodied page left **zero** pixels outside the region
> (`inside_region_only: 9359`, `outside_region: 0`), so the WebView2 content is
> *not* ignoring the region — the hypothesis this brief originally led with.
>
> **Fix** — one call, `win32.no_shadow`, in `pet._shape` next to the region:
> `DwmSetWindowAttribute(hwnd, DWMWA_NCRENDERING_POLICY, DWMNCRP_DISABLED)`.
> Verified end to end through the real `DeskPet`: `region=complex`,
> `corner_inside=False`, window `180×180`, and **every pixel of the ring around it
> back to 255**, with no warnings logged.
>
> ### What is still open, and is now the only question worth a researcher's time
>
> The rim is a **hard, stepped edge**. A GDI region clips; it does not antialias —
> and with the shadow gone there is nothing soft left on the silhouette at all. So
> the remaining question is **per-pixel alpha**: Q3, Q4, Q6, Q7 and Q9 below
> (transparent WebView2 surface, composition/visual hosting, `UpdateLayeredWindow`,
> a WPF/WinUI host, or pre-rendered frames in a layered window). Everything below is
> still the right brief — just read it as "how do we get a *smooth* round window",
> not "why is there a rectangle".
>
> The two probes that produced the measurements above are checked in beside this
> file: `repro_region_vs_webview2.py` (does content survive the region, and what is
> the HWND tree) and `repro_shadow.py` (the shadow, before and after the fix).

## The ask, in one paragraph

We ship a small always-on-top desktop "pet" window: a **pywebview 6.2.1** window on
Windows, whose page draws a circle. `SetWindowRgn` with an elliptical region
**reports success** on the top-level window (`GetWindowRgn` → `COMPLEXREGION`,
`PtInRegion(0,0)` → false, centre → true), and the circle *is* visible on screen —
**but a rectangle is still painted around it in the real window.** We want either
(a) a definitive explanation of why the region does not clip the WebView2 content
plus the minimal fix, or (b) a supported alternative that yields a genuinely round
window with per-pixel-alpha edges, or (c) a well-argued fallback. Concrete code and
citations please; flag anything you could not verify.

## Environment (exact)

| | |
|---|---|
| OS | Windows 11 Pro, version 10.0.26300 (build 26300) |
| Display scaling | 100% (96 DPI), single 1920×1080 monitor |
| Python | 3.13.14 |
| pywebview | **6.2.1** (WinForms backend, WebView2) |
| pythonnet | 3.2.1 (CLR 4.0.30319) |
| WebView2 runtime | **154.0.4258.62** |
| Available for probes | Pillow 12.2.0, Playwright 1.62.0 (headless Chromium), ctypes, pythonnet |

## What the window is, and the behaviours that must survive

The pet is a fixed-size, frameless, always-on-top status window; the same React
bundle draws the app itself (`index.html`) and this card (`pet.html`), and the card
animates a small character (blink, breathe, "typing at a keyboard", sleeping).

Created like this (`src/tonyagent/window/pet.py`):

```python
webview.create_window(
    "TONYAgent",
    url=page,                       # pet.html from the same bundle
    js_api=api,                     # the host bridge
    width=180, height=180,
    min_size=(180, 180),            # see the measurement note below
    x=x, y=y,                       # bottom-right of the work area, or remembered
    frameless=True, resizable=False, easy_drag=False,
    on_top=True, focus=False,       # WS_EX_NOACTIVATE: it must never take the keyboard
    text_select=False,
    background_color="#1a1a1a",
)
```

Behaviours that must keep working:

1. **Never activates.** `focus=False` → `WS_EX_NOACTIVATE`. A status window that
   steals the keyboard on every update is unusable.
2. **Always on top**, frameless, fixed size, remembered position.
3. **Draggable by its artwork**, using the OS move loop: the page's `pointerdown`
   calls the host, which calls `ReleaseCapture()` +
   `SendMessage(hwnd, WM_NCLBUTTONDOWN, HTCAPTION, cursor_pos)`, marshalled onto the
   window's own thread. When that modal loop returns, the host reports whether the
   window actually moved; a press that moved nothing is treated as a click and
   raises the app (`give_foreground_back` / `SetForegroundWindow`). A drag must not
   become an activation.
4. **Corners are click-through.** For a round pet this is not cosmetic: a
   rectangular hit area means the invisible corners swallow clicks meant for
   whatever is behind. Today the region should be doing this and we suspect it
   isn't.
5. **Cheap.** It is a status window: a handful of DOM updates a minute. No spinning
   redraw loop, no measurable idle CPU.
6. **DPI-aware** at 96–200% (per-monitor v2). Only 96% has been tested.
7. **Nice to have:** an antialiased rim, and a soft shadow. A hard, stepped rim is
   *accepted* today (a GDI region cannot antialias), and a shadow is *accepted as
   impossible* for the same reason. Per-pixel alpha would buy both.

Non-goals: cross-platform pet window; resizable pet; a second runtime or a second
app process.

## What we have measured (do not re-derive these)

1. **`transparent=True` does nothing here.** Measured on the real window:
   `WS_EX_LAYERED` unset, `AllowTransparency` false, and the pixels beside the
   artwork came back as the WinForms control grey rather than the desktop.
2. **Setting the form's `TransparencyKey` by hand through pythonnet hung the
   window.** (Order/thread unknown; we abandoned it rather than debug it. This is
   the route Q5 below asks about.)
3. **A GDI window region is applied and reported as set:**
   ```
   region=complex  corner_inside=False  centre_inside=True
   window=(180, 180)  client=(180, 180)  asked_for=(180, 180)
   ```
   (via `SetWindowRgn(hwnd, CreateEllipticRgn(0,0,180,180), TRUE)` on
   `GetAncestor(native.Handle, GA_ROOT)`, then `GetWindowRgn` + `PtInRegion`; sizes
   via `GetWindowRect` / `GetClientRect`.)
4. **pywebview's size clamp is real and surprising.** Its WinForms backend sets
   `Form.MinimumSize` from `create_window(min_size=...)`, whose default is
   `(200, 100)`. A card asked for at 180×180 came back **200×141** until we passed
   `min_size=(180,180)`. (Source: `webview/window.py` `min_size: tuple = (200,100)`;
   `webview/platforms/winforms.py` sets `self.MinimumSize` from it.)
5. **`Window.native` does not exist at creation time.** Measured by polling: it is
   `None` when `create_window()` returns and for ~750 ms after, then appears, then
   `shown` fires (~90 ms later) and `loaded` after that. Anything needing a handle
   has to wait for `shown` / `loaded` / the page's `ready`.
6. Headless Chromium renders the page correctly (the CSS circle, all poses), so the
   problem is not the page — it is the **window/compositing** layer.

## The symptom (now explained — see the update above)

In the real window the user saw the circle, **and a rectangle around it**. It was
the window's drop shadow, drawn to the rectangle and filling the corners the region
had cut: not the page, and not the region failing.

**The leading hypothesis in the first version of this brief was wrong**, and the
measurement that killed it is worth keeping: a page whose body is pure magenta left
**no** magenta outside the region (`outside_region: 0` of 6952 sampled pixels), so
the GDI region *does* clip WebView2 content. The window tree explains why it can: the
form is a `WindowsForms10.Window…` with a **zero-sized `Chrome_WidgetWin_0` child**,
i.e. the browser paints into the form's own surface rather than into a child window
that could escape the parent's clipping.

Still untried, and the subject of the questions below: clipping the child HWNDs as
well; `CoreWebView2Controller.DefaultBackgroundColor = Transparent`;
`WS_EX_LAYERED` + `SetLayeredWindowAttributes(LWA_COLORKEY)` on the form;
`UpdateLayeredWindow`; WebView2 **visual hosting** / `CompositionController`;
hosting the page in a WPF window; pre-rendered frames in a native layered window.

## Questions

**Q1 — mechanism.** Does `SetWindowRgn` on a WebView2 host window clip the browser's
output on Windows 11 / WebView2 154? If not, exactly why: a child HWND that isn't
subject to the parent's region, a DirectComposition visual,
`WS_EX_NOREDIRECTIONBITMAP`, or something else? Cite Microsoft docs, WebView2
release notes, or GitHub issues (`MicrosoftEdge/WebView2Feedback`).

**Q2 — child-window clipping.** If a region doesn't reach the content, does applying
the same region to the WebView2 child HWND(s) work? Give exact code to enumerate
(Unicode `EnumChildWindows`, class names to expect inside a WinForms WebView2
control) and clip each, and say what breaks — e.g. WebView2 recreating its HWND on
navigation, resize, or WebView2-process restart, and whether the region needs
re-applying.

**Q3 — transparency, supported route.** What is the *supported* way to get a
transparent WebView2 surface in an HWND-hosted WinForms control today? Specifically,
does `CoreWebView2Controller.DefaultBackgroundColor = Color.Transparent` produce
real alpha (not black, not grey) in an HWND-hosted control, under which conditions,
and from which WebView2 version? Is a layered parent required?

**Q4 — visual hosting.** Is WebView2 **visual hosting**
(`ICoreWebView2Controller` + `ICoreWebView2CompositionController` +
DirectComposition target, `CoreWebView2Environment.CreateCoreWebView2CompositionController`)
reachable from pywebview's WinForms backend through pythonnet? Would it give
per-pixel alpha (i.e. an antialiased circular rim)? If yes, sketch the minimal shim.

**Q5 — colour key, safely.** Give the exact, safe sequence to put
`WS_EX_LAYERED` + `SetLayeredWindowAttributes(LWA_COLORKEY, key)` on a pywebview
WinForms form *after* it exists, without the hang we hit through
`Form.TransparencyKey`. Which thread, what order, what to do about the form being
recreated, and does WebView2 content respect the key? State the antialiasing
consequence (a binary key cannot antialias the rim) and how it looks over a
photographic wallpaper.

**Q6 — per-pixel alpha.** Is `UpdateLayeredWindow` compatible with WebView2 at all?
If it requires no child HWND, does WebView2 support windowless/host-object hosting
on WinForms (or only in WPF/WinUI)?

**Q7 — another host.** Would hosting the same page in a **WPF** window
(`AllowsTransparency=True`, or `WebView2CompositionControl`) actually yield a
transparent background on Windows 11? Can that window be created by our Python
process through pythonnet while keeping one process and one bundle? What breaks
(airspace, DPI, `WS_EX_NOACTIVATE`, the OS move-loop drag, click-through corners)?

**Q8 — prior art.** Any known-good open-source examples of an irregular (round,
blob, or otherwise non-rectangular) **WebView2** window that demonstrably works on
Windows 11 — in any language? Links please.

**Q9 — fallback, evaluated honestly.** We have Playwright available, so we could
**pre-render the pet's poses/frames to PNGs** (statically at build time, or on
demand) and display them in a native window with real per-pixel alpha
(`UpdateLayeredWindow`), bypassing WebView2 for this window entirely. Evaluate:
minimal implementation, whether it can keep always-on-top + never-activate + the
OS move-loop drag + click-through corners, the CPU cost of e.g. 8–12 fps sprite
playback, and whether a lighter middle path exists (DWM/DirectComposition target
fed by pre-rendered frames, or `WS_EX_LAYERED` + `UpdateLayeredWindow` with only a
few frames). Is there a way to keep the *live page* (React/CSS) and still get alpha?

**Q10 — the minimal patch.** For whichever approach you recommend: exact code
(C# is fine to describe; **pythonnet/ctypes calls are what we can actually ship**),
including how to reach the form and the WebView2 control from `window.native` in
**pywebview 6.2.1** specifically, how to keep `WS_EX_NOACTIVATE`/topmost/frameless,
and where in the window's lifecycle it must run (we learned `native` arrives ~750 ms
after `create_window`, on `shown`).

## What a good answer looks like

1. **A one-paragraph verdict**: which approach is the right one on this
   configuration, and why the others lose.
2. **The mechanism** for Q1 with citations — we want to understand what we hit, not
   just route around it.
3. **Minimal working code** for the recommended approach, in the form we can run
   (ctypes/pythonnet against a pywebview window), with the lifecycle hook named.
4. **A verification recipe**: the exact checks that prove a round window — e.g.
   `GetWindowRgn`/`PtInRegion`, `GetLayeredWindowAttributes`, a screenshot pixel
   probe at the corners compared against a capture of the same rect with the window
   hidden, and a `WindowFromPoint` check that the corner belongs to the window
   *behind* the pet rather than to the pet (click-through).
5. **Honest fallback ranking** if (a) is impossible without changing hosts, and a
   clear statement of what each fallback costs in fidelity (rim antialiasing,
   shadow, live DOM, CPU).
6. **Explicit "untested / uncertain" flags.** We would rather have a short certain
   answer than a long confident one.

## Appendix A — our current code (paths relative to the repo root)

* `src/tonyagent/window/pet.py` — `DeskPet`: window lifecycle, status push,
  position memory, drag (`ReleaseCapture` + `WM_NCLBUTTONDOWN`/`HTCAPTION` via
  `win32.begin_drag`), `_dress` (runs on `shown`/`loaded`/page-ready; calls `_reveal`
  then `_clip`), `_clip` → `win32.clip_to_circle`.
* `src/tonyagent/window/win32.py` — `clip_to_circle(hwnd)` (measures
  `GetWindowRect`, cuts `circle_box`), `circle_box(w,h)`, `on_window_thread`,
  `raise_without_activating`, `give_foreground_back`, `begin_drag`, ctypes bindings.
* `app/pet.html`, `app/src/petcard.tsx`, `app/src/styles/pet.css` — the card: a
  `min(100vw, 100vh)` square div with `border-radius: 50%`, no `box-shadow` (a
  region leaves nowhere to paint one).

## Appendix B — the probes we used (reproducible here)

```python
# Is a region set on the window, and is the corner inside it?
probe = gdi32.CreateRectRgn(0, 0, 1, 1)
kind  = user32.GetWindowRgn(hwnd, probe)          # 0 none, 1 empty, 2 rect, 3 complex
corner = gdi32.PtInRegion(probe, 0, 0)            # expect False for a round window
centre = gdi32.PtInRegion(probe, 90, 90)          # expect True
gdi32.DeleteObject(probe)
# NB: bind GetWindowRect's argtypes against the same RECT class you pass.

# Was anything painted in the corner? (the decisive visual check)
from PIL import ImageGrab
box = (x, y, x + 180, y + 180)
shown = ImageGrab.grab(bbox=box); pet_hide(); hidden = ImageGrab.grab(bbox=box)
# compare corner pixels of `shown` against the same pixels of `hidden`:
# equal -> nothing painted there (region or alpha is working);
# unequal and matching the page background -> the content ignores the region.
```

A cheaper variant: load a page whose `body` background is pure magenta and ask
whether any magenta pixel survives inside the window rect outside the circle.
