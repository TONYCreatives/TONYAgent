# Why the square is still there, and why it cannot be fixed in the WebView2 pet

Asked after `811b421`, which removed the rectangular *shadow*. The shadow is gone. The
square is not the shadow, and every explanation below is a measurement.

## What is actually at the corners

On the live pet (`hwnd=788474`, `region=complex`, `PtInRegion(0,0)` false):

| sample | value | meaning |
|---|---|---|
| 3px **inside** the rect, at all four corners | `[32,32,32]` | painted, and not by the wallpaper |
| 4px **outside** the rect | `[142,173,70]`, `[53,70,15]`, … | green wallpaper: **the shadow is gone** |

So the halo outside is fixed and the rectangle is being painted from *inside* the
window's own rectangle. The region says it should not be.

## The window chain says why

```
788474  WindowsForms10.Window.8.app   180x180  region=complex  corner_in=False   <- the region
  264228 WindowsForms10.Window.8.app  180x180  region=none     ex=TRANSPARENT    <- what paints
    329744 Chrome_WidgetWin_0                  region=none
      395212 Chrome_WidgetWin_1                region=none  [NOREDIRECTIONBITMAP]
        264326 Chrome_RenderWidgetHostHWND     region=none  [TRANSPARENT]
        264148 Intermediate D3D Window         region=none  [TRANSPARENT,LAYERED,NOREDIRECTIONBITMAP]
```

The region is on the *wrapper*; the window that paints is its **child**, and a parent's
region does not clip a child (the parent's *client rectangle* does that). And the chain
below is the fingerprint of **DirectComposition hosting** — `WS_EX_NOREDIRECTIONBITMAP`
on `Chrome_WidgetWin_1`, and an `Intermediate D3D Window` marked
`TRANSPARENT|LAYERED|NOREDIRECTIONBITMAP`. The page is presented as a composition
visual, not drawn into a GDI surface.

**And a GDI region does not clip a composition visual.** Measured: applying the same
elliptic region to the form and to *every* window in the chain changed the corner pixels
by nothing at all — `[32,32,32]` before, `[32,32,32]` after.

(An earlier magenta probe concluded the opposite, that regions *do* clip WebView2
content. That probe's window was hosted the other way — its chain had no
`NOREDIRECTIONBITMAP` — so it measured the windowed path. Both results are true, of
different hosting modes.)

## And transparency cannot be turned on here either

| attempt | result |
|---|---|
| `transparent=True` (pywebview sets the browser background) | corners `[32,32,32]`; the control chain is composition-hosted either way |
| A/B against a white backdrop: opaque vs transparent window, same page | neither ever shows the backdrop at its corners (`[18,18,18]` vs `[32,32,32]`) |
| `BrowserForm.BackColor = Color.Transparent` | accepted — corners become `[240,240,240]`, the form's *Control* grey, so the form does paint |
| `WebView2.BackColor = Color.Transparent` | **refused**: "Control does not support transparent background colors" |
| `DefaultBackgroundColor = Color.Transparent` on the **UI thread** | **accepted**, reads back `Color [A=0, R=255, G=255, B=255]` — and the corners stay `[32,32,32]` |

The last row is the one that settles it. With the browser's own background at alpha 0
and the page's `body` transparent, the presented surface is still opaque — `[32,32,32]`
is Chromium's dark base background. The composition surface this host gets is simply not
alpha-bearing.

## What this means

**The WebView2 pet cannot be round.** Two independent walls: a region cannot clip a
composition visual, and the surface it composites is opaque. `no_shadow` was worth
keeping (the halo outside is gone), and the region still does its *input* job — the
corners are click-through, they are just not invisible.

That is not a claim that WebView2 cannot do this. Tencent Yuanbao's pet does it on this
machine — but it is a Tauri/wry host driving `CoreWebView2CompositionController` itself,
where the host owns the visual and its alpha mode. pywebview's WinForms wrapper gets
window-to-visual hosting and no say in the surface. Matching Yuanbao means replacing the
host for that window.

**Which is why the native layered window is the fix rather than the nicer option.** It
has no WebView2 in it at all: its pixels are ours, handed to the compositor by
`UpdateLayeredWindow` with per-pixel alpha, which is exactly what the prototype showed
and what `src/tonyagent/window/layered.py` (commit `bfdf74b`) now implements.

## Reproducing

- `research/inspect_live_pet.py` — the live window: region, styles, corner and ring pixels.
- `research/inspect_live_chain.py` — the whole chain, class by class, with regions and styles.
- `research/clip_painting_window.py` — clips the form, then every descendant, measuring each time.
- `research/probe_alpha_page.py` — the transparent/opaque A/B over a white backdrop.
- `research/probe_form_alpha.py` — the WinForms `BackColor` attempts.
- `research/probe_ui_thread_alpha.py` — `DefaultBackgroundColor` on the window's own thread.
- `research/restore_live_pet.py` — clears the regions those experiments set on a running pet.
