# How a shipping desktop pet does it: Tencent Yuanbao, measured on this machine

A live specimen was running next to our own pet, so it was interrogated directly.
Nothing here is from documentation or guesswork: every line is a Win32 read or a
screenshot pixel. It **answers the research question empirically**, which turns the
brief from "is this possible?" into "confirm this route and write it for pywebview".

## The finding

Yuanbao's pet is a **Tauri window (Rust) hosting WebView2**, and it has **true
per-pixel alpha**: the app's text behind the creature is legible right up to its
silhouette (see the screenshot evidence below). The alpha does **not** come from the
top-level window, which is ordinary:

```
Tauri Window                  ex=0x40118  [TOPMOST]                        region=rect
└── WRY_WEBVIEW               ex=0x0      []                               (fills it)
    └── Chrome_WidgetWin_0    ex=0x0      []
        └── Chrome_WidgetWin_1  ex=0x200000  [NOREDIRECTIONBITMAP]  ←────── the mechanism
            ├── Chrome_RenderWidgetHostHWND  ex=0x20 [TRANSPARENT]
            └── Intermediate D3D Window      ex=0x280024
                                             [TRANSPARENT, LAYERED, NOREDIRECTIONBITMAP]
```

**`WS_EX_NOREDIRECTIONBITMAP` on `Chrome_WidgetWin_1`** is the answer: that window has
no GDI redirection surface, so its pixels come from a DirectComposition/swap-chain
present with **premultiplied alpha**. `Intermediate D3D Window` adds `WS_EX_LAYERED`
(legal on a child window since Windows 8) and `WS_EX_TRANSPARENT`. The top-level
window paints nothing at all, so what DWM composites is the child's alpha surface.

That is **multi-plane overlay / visual hosting**, and in WebView2 it is the
**composition (visual hosting) mode** — `ICoreWebView2Controller` +
`ICoreWebView2CompositionController` (`CreateCoreWebView2CompositionController`)
plus a DirectComposition target — with the page's
`CoreWebView2Controller.DefaultBackgroundColor` set to transparent. Tauri/wry uses
exactly that on Windows for `transparent: true`.

## Measured facts

| | |
|---|---|
| Process | `yuanbao.exe`, 166 modules loaded, incl. `EmbeddedBrowserWebView.dll`, `d3d11`, `d2d1`, `d3d9/10` |
| Window classes | `Tauri Window` → `WRY_WEBVIEW` → `Chrome_WidgetWin_0/1` → `Chrome_RenderWidgetHostHWND` + `Intermediate D3D Window` |
| Top-level ex-styles | `TOPMOST` only — **no `WS_EX_LAYERED`, no `WS_EX_NOREDIRECTIONBITMAP`** |
| Top-level region | `SIMPLEREGION` (a plain rectangle — a no-op shape) |
| Child ex-styles | `NOREDIRECTIONBITMAP` on `Chrome_WidgetWin_1`; `TRANSPARENT,LAYERED,NOREDIRECTIONBITMAP` on the D3D window |
| Pet window size | 116×116, absolutely positioned, `WS_VISIBLE`, `WS_POPUP`-less (top level) |
| Transparency proof | app text visible through the window, immediately left/right of the creature; the pixel sampled at the window's own top-left corner is a ClearType-tinted white **text** pixel from the window behind, not a card colour |

## What this means for us

1. **It is possible, and it does not need a region.** Yuanbao has no shape region at
   all: the silhouette is alpha, so the rim is antialiased for free — which is exactly
   the acceptance test our brief asks for ("pixels strictly between the card and the
   backdrop").
2. **pywebview's WinForms WebView2 control is the blocker, not WebView2.** The default
   control hosts the browser in **windowed (HWND) mode**, which is why
   `transparent=True` does nothing on our window and why we ended up with a GDI region.
   Composition hosting is exposed in .NET only for WinUI/WPF
   (`WebView2CompositionControl`); through raw COM it is available to anyone.
3. **The narrowed research question** is therefore no longer "is there a way?" but:
   *confirm that `CreateCoreWebView2CompositionController` +
   `DefaultBackgroundColor = Transparent` is what produces the tree above, and give the
   smallest correct sequence of pythonnet/COM calls to do it against a plain Win32 or
   WinForms window from Python* — including whether pywebview can be made to use it, or
   whether this one window should be hosted by something else (a tiny C#/Rust host,
   invoked from Python, would match what Yuanbao already proves works).
4. Note what Yuanbao gives up: its pet window carries `TOPMOST` only — no
   `WS_EX_NOACTIVATE`. Ours must keep that, plus the OS move-loop drag and
   click-through corners, so the alpha route has to be checked against those.

## Reproducing these reads

`research/inspect_yuanbao_pet.py` (windows, process, modules, edge pixels),
`research/yuanbao_tree.py` (the whole tree with raw extended styles and regions), and
`research/look_at_yuanbao.py` (lists the process's windows and saves a magnified
screenshot of the pet). They read a *running* third-party app and poke nothing.
