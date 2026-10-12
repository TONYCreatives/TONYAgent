# RESEARCH PROMPT — a smooth (antialiased) circular WebView2 window on Windows 11

Copy everything below the line into the researcher AI.

---

**Task.** Tell me how to get a **genuinely round, smoothly antialiased, always-on-top
desktop window whose content is WebView2**, from Python, on Windows 11 — or tell me
authoritatively that it is impossible and give me the best fallback. I need exact
API names and runnable code, not options in the abstract, and you must flag
anything you could not verify.

## Environment (exact — please do not generalise away from it)

- Windows 11 Pro, 10.0.26300 (build 26300), single 1920×1080 display at 100% (96 DPI)
- Python 3.13.14
- **pywebview 6.2.1**, WinForms backend, WebView2 (runtime 154.0.4258.62)
- **pythonnet 3.2.1** (CLR 4.0.30319), so C#-shaped APIs are reachable from Python
- Available: ctypes, Pillow 12.2.0, Playwright 1.62.0 (headless Chromium for rasterising)
- One process, one React bundle serving two pages; the window in question is
  `webview.create_window(..., frameless=True, resizable=False, on_top=True,
  focus=False, easy_drag=False, width=180, height=180, min_size=(180,180))`

## What already works (do not propose these — they are done and measured)

1. **The window is cut to a circle with a GDI window region**:
   `SetWindowRgn(hwnd, CreateEllipticRgn(...), TRUE)` on the top-level HWND
   (`GetAncestor(native.Handle, GA_ROOT)`), sized from the window's real box via
   `GetWindowRect`. Verified: `GetWindowRgn` → `COMPLEXREGION`, `PtInRegion(0,0)` →
   false, centre → true, window 180×180. Clicks in the cut corners fall through to
   the desktop. WebView2 content *is* clipped by it (measured on a magenta-bodied
   page: zero pixels survived outside the region).
2. **The system drop shadow is turned off**, which was necessary because DWM draws
   a window's shadow to the window's *rectangle*, not its region — it filled the cut
   corners with a dark halo. Fix: `DwmSetWindowAttribute(hwnd,
   DWMWA_NCRENDERING_POLICY, DWMNCRP_DISABLED)`. Verified over a white backdrop:
   every pixel in the ring around the window went from 119–241 to 255.
3. Never-activating (`focus=False` → `WS_EX_NOACTIVATE`), topmost, frameless,
   fixed size; draggable by its artwork via the OS move loop
   (`ReleaseCapture()` + `SendMessage(hwnd, WM_NCLBUTTONDOWN, HTCAPTION, ...)`);
   a press that moved nothing raises the app.

**What we cannot do: the rim is a hard, stepped edge.** A GDI region clips; it does
not antialias. With the shadow also gone, there is nothing soft on the silhouette at
all. That is the entire remaining problem.

## What has already been tried and failed

- `transparent=True` on `create_window`: on this shell it leaves the form opaque —
  measured `WS_EX_LAYERED` unset, `AllowTransparency` false, and the pixels beside
  the artwork came back as the WinForms control grey, not the desktop.
- Setting the WinForms form's `TransparencyKey` by hand through pythonnet **hung the
  window**. We did not debug it; if that is the right route, tell me the correct
  order/thread so it does not hang.

## Questions

**Q1 — is per-pixel alpha reachable at all?** On this exact configuration, can a
window whose content is WebView2 have a per-pixel-alpha silhouette (i.e. an
antialiased circular rim, and ideally a soft shadow)? Yes/no, and what is the
mechanism.

**Q2 — the route, if yes.** Which of these actually works, and what is the exact
code path from Python?

  a. WebView2 **visual hosting**: `ICoreWebView2Controller` +
     `ICoreWebView2CompositionController` +
     `CreateCoreWebView2CompositionController` onto a DirectComposition target.
     Is that reachable through pywebview 6.2.1's WinForms backend via pythonnet
     (what do I get from `window.native`, and where does the WebView2 control live)?
  b. `CoreWebView2Controller.DefaultBackgroundColor = Color.Transparent` — does it
     produce real alpha (not black, not grey) in an **HWND-hosted** WinForms
     control, from which WebView2 version, and under what conditions?
  c. `WS_EX_LAYERED` + `SetLayeredWindowAttributes(LWA_COLORKEY)` on the form: the
     safe sequence and thread, and whether WebView2 content respects the key.
     (I know this cannot antialias — state what the rim looks like over a
     photographic wallpaper.)
  d. `UpdateLayeredWindow` (per-pixel alpha): is it compatible with WebView2 at all,
     or does it require windowless/host-object hosting that WinForms WebView2 does
     not offer?
  e. Hosting the page in a **WPF** window (`AllowsTransparency=True`,
     `WebView2CompositionControl`) or WinUI inside the same Python process: does that
     give a transparent background, and what breaks — airspace, DPI,
     `WS_EX_NOACTIVATE`, my OS move-loop drag, my click-through corners?
  f. Anything else that works, including a small native shim (C# via pythonnet, or
     ctypes) that I can call from the existing process.

**Q3 — if no, the fallback, ranked.** We have Playwright, so we could rasterise the
pet's poses/frames to PNGs and put them in a **native layered window**
(`UpdateLayeredWindow`) with real per-pixel alpha, bypassing WebView2 for this one
window. Evaluate that honestly: minimal implementation, CPU cost for ~8–12 fps
sprite playback, whether it keeps always-on-top + never-activate + the OS move-loop
drag + click-through corners, and whether a lighter middle path exists (e.g. a
DirectComposition target fed by pre-rendered frames). Rank it against staying with
the current hard-edged circle.

**Q4 — what a good answer looks like from you**

1. One-paragraph verdict: which route, on this configuration, and why the others lose.
2. The exact code (C# is fine to describe, but **pythonnet/ctypes calls are what I
   ship**), including the lifecycle hook — note that `Window.native` does not exist
   when `create_window()` returns; it appears ~750 ms later, and pywebview's `shown`
   event fires just after that.
3. What must be preserved: `WS_EX_NOACTIVATE` (never take focus), topmost, frameless,
   fixed size, the OS move-loop drag from a page `pointerdown`, click-through corners,
   and low idle CPU (it is a status card that updates a few times a minute).
4. A **verification recipe** — the checks that prove the rim is really antialiased:
   e.g. screenshot pixel probes across the rim (I use `PIL.ImageGrab`), `GetWindowRgn`/
   `PtInRegion`, `GetLayeredWindowAttributes`, `WindowFromPoint` for click-through.
5. Citations: Microsoft Learn, `MicrosoftEdge/WebView2Feedback` issues, WebView2
   release notes, pywebview issues/PRs, or working open-source examples of irregular
   WebView2 windows on Windows 11.
6. **Explicit "untested / uncertain" flags.** A short certain answer beats a long
   confident one.
