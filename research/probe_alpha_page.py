"""Can this WebView2 window carry alpha at all? An A/B over a white backdrop.

The live pet's corners are `[32,32,32]` -- the page's own background -- and clipping
every window in its chain changed nothing, because the content is presented through
DirectComposition (`Chrome_WidgetWin_1` with `NOREDIRECTIONBITMAP`, plus an
`Intermediate D3D Window`), and a GDI region cannot clip a composition visual.

That leaves two possibilities, and they are one experiment apart:

* **The compositor can carry alpha** (Yuanbao's pet proves it can on this machine), in
  which case the page's opaque background is the only thing in the way and the fix is
  a transparent page plus `DefaultBackgroundColor = Transparent`.
* **It cannot**, in which case no amount of CSS helps and the native layered window --
  with no WebView2 in it at all -- is the only route to a round pet.

Two probe windows over one topmost white backdrop: same page, same flags, differing
only in pywebview's `transparent`. The opaque one is the control. If transparency
works, that window's corners are the backdrop's white; if it does not, they are the
page's own colour, exactly as the live pet's are.
"""

import ctypes
import json
import os
import pathlib
import threading
import time
from ctypes import wintypes

import webview

PAGE = """
<html><body style="margin:0;background:transparent">
  <div style="width:150px;height:150px;border-radius:50%;background:#101010;margin:15px auto"></div>
</body></html>
"""

SIZE = 180
BACKDROP_AT = (420, 300)
BACKDROP_SIZE = 600
CONTROL_AT = (470, 400)
TEST_AT = (470, 400 + SIZE + 40)
OUT = pathlib.Path(".tmp-alpha-ab.json")

user32 = ctypes.windll.user32
WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
EXFLAGS = {"TRANSPARENT": 0x20, "LAYERED": 0x80000, "NOREDIRECTIONBITMAP": 0x200000,
           "NOACTIVATE": 0x8000000, "TOPMOST": 0x8}
REGIONS = {0: "none", 1: "empty", 2: "rect", 3: "complex"}


def chain(hwnd: int) -> list[dict]:
    out: list[dict] = []

    def describe(handle: int, depth: int) -> None:
        klass = ctypes.create_unicode_buffer(128)
        user32.GetClassNameW(wintypes.HWND(handle), klass, 128)
        ex = user32.GetWindowLongW(wintypes.HWND(handle), -20)
        probe = ctypes.windll.gdi32.CreateRectRgn(0, 0, 1, 1)
        kind = user32.GetWindowRgn(wintypes.HWND(handle), probe)
        ctypes.windll.gdi32.DeleteObject(probe)
        out.append({"depth": depth, "class": klass.value, "ex": hex(ex & 0xFFFFFFFF),
                    "flags": [n for n, b in EXFLAGS.items() if ex & b],
                    "region": REGIONS.get(kind, kind)})

    describe(hwnd, 0)
    found: list[int] = []

    def visit(child, _lparam):
        found.append(int(child))
        return True

    user32.EnumChildWindows(wintypes.HWND(hwnd), WNDENUMPROC(visit), 0)
    for child in found:
        describe(child, 1)
    return out


def sample(left: int, top: int) -> dict:
    from PIL import ImageGrab

    grab = ImageGrab.grab(bbox=(left, top, left + SIZE, top + SIZE), all_screens=True).convert("RGB")
    return {
        "corners": [list(grab.getpixel(p)) for p in ((3, 3), (SIZE - 4, 3), (3, SIZE - 4), (SIZE - 4, SIZE - 4))],
        "centre": list(grab.getpixel((SIZE // 2, SIZE // 2))),
        "unique_colours": len(grab.getcolors(maxcolors=1 << 24) or []),
    }


def main() -> None:
    notes: dict[str, object] = {}
    webview.create_window(
        "backdrop", html="<html><body style='margin:0;background:#ffffff'></body></html>",
        width=BACKDROP_SIZE, height=BACKDROP_SIZE, x=BACKDROP_AT[0], y=BACKDROP_AT[1],
        frameless=True, resizable=False, on_top=True,
    )
    common = dict(width=SIZE, height=SIZE, min_size=(SIZE, SIZE), frameless=True,
                  resizable=False, on_top=True, focus=False, text_select=False)
    control = webview.create_window("control", html=PAGE, x=CONTROL_AT[0], y=CONTROL_AT[1],
                                    background_color="#1a1a1a", **common)
    test = webview.create_window("transparent", html=PAGE, x=TEST_AT[0], y=TEST_AT[1],
                                 background_color="#1a1a1a", transparent=True, **common)

    def when_up() -> None:
        try:
            time.sleep(4.0)
            for name, window, at in (("control", control, CONTROL_AT), ("transparent", test, TEST_AT)):
                native = getattr(window, "native", None)
                hwnd = int(native.Handle.ToInt64()) if native is not None else 0
                top = int(user32.GetAncestor(wintypes.HWND(hwnd), 2)) if hwnd else 0
                entry = {"hwnd": top, "chain": chain(top) if top else [], "pixels": sample(*at)}
                # The test: is the corner the page's colour, or the white behind it?
                corner = entry["pixels"]["corners"][0]
                entry["corner_is_page_background"] = corner == [16, 16, 16] or corner == [26, 26, 26]
                entry["corner_is_backdrop"] = corner == [255, 255, 255]
                entry["corner"] = corner
                notes[name] = entry
        except Exception as exc:  # noqa: BLE001 - a probe reports
            notes["error"] = repr(exc)
        finally:
            OUT.write_text(json.dumps(notes, indent=2, default=str), encoding="utf-8")
            os._exit(0)

    threading.Thread(target=when_up, daemon=True).start()
    webview.start()


if __name__ == "__main__":
    main()
