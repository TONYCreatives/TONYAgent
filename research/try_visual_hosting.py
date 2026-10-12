"""Does forcing window-to-visual hosting give us a per-pixel-alpha WebView2 window?

The research answer says the route is WebView2's *visual hosting* mode, forced with
`COREWEBVIEW2_FORCED_HOSTING_MODE` before the control initialises, plus a transparent
controller background. pywebview already does the second half itself -- with
`transparent=True` it calls `self.browser.DefaultBackgroundColor = Color.Transparent`
-- which is why that flag appeared to do nothing: in the default *windowed* hosting
mode a transparent browser background has nowhere to composite.

This runs the experiment and checks it against the fingerprint measured on Tencent
Yuanbao's pet, which is known to work:

    Chrome_WidgetWin_1   ex=0x200000  [NOREDIRECTIONBITMAP]     <- the alpha surface
    Intermediate D3D Window  ex=0x280024  [TRANSPARENT, LAYERED, NOREDIRECTIONBITMAP]

and against the acceptance test from the brief: across the rim there must be pixels
*strictly between* the card's colour and the backdrop's.

Writes .tmp-visual-hosting.json and exits.
"""

import json
import os
import pathlib
import threading
import time
from ctypes import wintypes

# **First, before anything touches WebView2.** The runtime reads this when it creates
# the environment, and pywebview creates that inside the window construction -- so
# setting it here is early enough, and setting it later would not be.
os.environ["COREWEBVIEW2_FORCED_HOSTING_MODE"] = "COREWEBVIEW2_HOSTING_MODE_WINDOW_TO_VISUAL"

import ctypes  # noqa: E402

import webview  # noqa: E402

SIZE = 180
BACKDROP_AT = (80, 80)
BACKDROP_SIZE = 420
TEST_AT = (BACKDROP_AT[0] + 120, BACKDROP_AT[1] + 120)
OUT = pathlib.Path(".tmp-visual-hosting.json")

PAGE = """
<html><body style="margin:0;background:transparent">
  <div style="width:140px;height:140px;border-radius:50%;background:#101010;margin:20px auto"></div>
</body></html>
"""

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32
WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

EXFLAGS = {
    "TRANSPARENT": 0x20,
    "LAYERED": 0x80000,
    "NOREDIRECTIONBITMAP": 0x200000,
    "NOACTIVATE": 0x8000000,
    "TOPMOST": 0x8,
}


def tree(hwnd: int, depth: int = 0, out: list | None = None) -> list:
    out = [] if out is None else out
    found: list[int] = []

    def visit(child, _lparam):
        found.append(int(child))
        return True

    user32.EnumChildWindows(wintypes.HWND(hwnd), WNDENUMPROC(visit), 0)
    for child in found:
        klass = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(wintypes.HWND(child), klass, 256)
        ex = user32.GetWindowLongW(wintypes.HWND(child), -20)
        out.append(
            {
                "depth": depth,
                "class": klass.value,
                "ex": hex(ex & 0xFFFFFFFF),
                "flags": [name for name, bit in EXFLAGS.items() if ex & bit],
            }
        )
        tree(child, depth + 1, out)
    return out


def rim_probe() -> dict:
    """Pixels across the circle's rim, classified against the two known colours.

    The circle is #101010 on a pure white backdrop. A hard-clipped window shows only
    those two colours; per-pixel alpha leaves a run of blends between them.
    """
    from PIL import ImageGrab

    left, top = TEST_AT
    image = ImageGrab.grab(
        bbox=(left, top, left + SIZE, top + SIZE), all_screens=True
    ).convert("RGB")

    # A horizontal line through the circle's centre crosses the rim twice.
    y = SIZE // 2
    row = [image.getpixel((x, y)) for x in range(SIZE)]
    blends = [
        1
        for r, g, b in row
        if 40 < (r + g + b) / 3 < 230 and abs(r - g) < 6 and abs(g - b) < 6
    ]
    corners = [
        image.getpixel((2, 2)),
        image.getpixel((SIZE - 3, 2)),
        image.getpixel((2, SIZE - 3)),
        image.getpixel((SIZE - 3, SIZE - 3)),
    ]
    centre = image.getpixel((SIZE // 2, SIZE // 2))
    unique = len(image.getcolors(maxcolors=1 << 24) or [])
    return {
        "circle_centre": list(centre),
        "corners": [list(c) for c in corners],
        "blend_pixels_on_the_midline": blends,
        "unique_colours": unique,
        "row_sample": [list(row[i]) for i in range(0, SIZE, 12)],
    }


def main() -> None:
    from loguru import logger

    logged: list[str] = []
    logger.add(lambda message: logged.append(message.strip()), level="INFO")

    notes: dict[str, object] = {"forced_hosting": os.environ.get("COREWEBVIEW2_FORCED_HOSTING_MODE")}
    webview.create_window(
        "backdrop",
        html="<html><body style='margin:0;background:#ffffff'></body></html>",
        width=BACKDROP_SIZE,
        height=BACKDROP_SIZE,
        x=BACKDROP_AT[0],
        y=BACKDROP_AT[1],
        frameless=True,
        resizable=False,
        on_top=True,
    )
    # `transparent=True` is pywebview's own path: it sets the browser's
    # DefaultBackgroundColor to transparent and lets the control's back colour be
    # transparent. It is a no-op in windowed hosting, which is the thing being tested.
    test = webview.create_window(
        "visual-hosting-probe",
        html=PAGE,
        width=SIZE,
        height=SIZE,
        min_size=(SIZE, SIZE),
        x=TEST_AT[0],
        y=TEST_AT[1],
        frameless=True,
        resizable=False,
        on_top=True,
        focus=False,
        transparent=True,
    )

    def when_up() -> None:
        try:
            hwnd = 0
            for _ in range(60):
                time.sleep(0.25)
                native = getattr(test, "native", None)
                if native is None:
                    continue
                hwnd = int(native.Handle.ToInt64())
                if hwnd:
                    break
            top = user32.GetAncestor(wintypes.HWND(hwnd), 2) or hwnd
            notes["hwnd"] = top
            box = wintypes.RECT()
            user32.GetWindowRect(wintypes.HWND(top), ctypes.byref(box))
            notes["rect"] = [box.left, box.top, box.right - box.left, box.bottom - box.top]
            notes["tree"] = tree(top)

            # What the page object has to say about its own WebView2 control, so a
            # later implementation knows what it can reach from Python.
            try:
                form = test.native
                names = [name for name in dir(form) if "web" in name.lower() or "browser" in name.lower()]
                notes["form_members"] = names
                control = getattr(form, "webview", None) or getattr(form, "browser", None)
                if control is not None:
                    notes["control_type"] = type(control).__name__
                    notes["control_members"] = [
                        name
                        for name in dir(control)
                        if "background" in name.lower() or "controller" in name.lower()
                    ]
            except Exception as exc:  # noqa: BLE001 - the probe reports
                notes["introspection_error"] = repr(exc)

            time.sleep(2.0)
            notes["rim"] = rim_probe()
        except Exception as exc:  # noqa: BLE001 - a probe reports, it does not raise
            notes["error"] = repr(exc)
        finally:
            notes["log"] = logged
            OUT.write_text(json.dumps(notes, indent=2, default=str), encoding="utf-8")
            os._exit(0)

    threading.Thread(target=when_up, daemon=True).start()
    webview.start()


if __name__ == "__main__":
    main()
