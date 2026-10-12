"""Reproducer: is the region set on the window, and does the content obey it?

Two questions, both answerable without eyes on the screen:

1. **What is the window tree?** If WebView2 hosts its content in a child HWND, the
   class names will show it and a region could be applied there too. If there is no
   child HWND at all, the content is being composited by something that a GDI region
   cannot reach -- which decides the whole investigation.
2. **Was anything painted in the corner?** The page's body is painted pure magenta,
   so any magenta left inside the window rect after the circular region is applied
   is content that ignored the region. The window's own background colour (#1a1a1a)
   and the circle are both dark, so magenta cannot appear by accident.

Run with: python research/repro_region_vs_webview2.py
Writes .tmp-region-repro.json and exits (never waits for a window to close).
"""

import ctypes
import json
import pathlib
import threading
import time
from ctypes import wintypes

import webview

from tonyagent.window import pet as pet_module
from tonyagent.window import win32

SIZE = 180
AT = (120, 120)
OUT = pathlib.Path(".tmp-region-repro.json")

# Magenta body, dark circle: anything magenta surviving the region is content that
# ignored it.
PAGE = """
<html><body style="margin:0;background:#ff00ff">
  <div style="width:140px;height:140px;border-radius:50%;background:#101010;margin:20px auto"></div>
</body></html>
"""

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32

# Declared here rather than added to `win32.py`: this is a diagnostic, and the two
# style bits are only being *read*.
GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
WS_EX_NOACTIVATE = 0x08000000

WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


def window_tree(root: int, depth: int = 0, out: list | None = None) -> list:
    """Every descendant HWND, with its class, rect, and whether it is layered."""
    out = [] if out is None else out
    for hwnd in _children(root):
        name = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(wintypes.HWND(hwnd), name, 256)
        box = win32.RECT()
        user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(box))
        ex = user32.GetWindowLongW(wintypes.HWND(hwnd), GWL_EXSTYLE)
        probe = gdi32.CreateRectRgn(0, 0, 1, 1)
        region = user32.GetWindowRgn(wintypes.HWND(hwnd), probe)
        gdi32.DeleteObject(probe)
        out.append(
            {
                "depth": depth,
                "hwnd": hwnd,
                "class": name.value,
                "rect": [box.left, box.top, box.right, box.bottom],
                "ex_style": hex(ex),
                "layered": bool(ex & WS_EX_LAYERED),
                "noactivate": bool(ex & WS_EX_NOACTIVATE),
                "region": {0: "none", 1: "empty", 2: "rect", 3: "complex"}.get(region, region),
            }
        )
        window_tree(hwnd, depth + 1, out)
    return out


def _children(parent: int) -> list[int]:
    found: list[int] = []

    def visit(hwnd, _lparam):
        found.append(int(hwnd))
        return True

    user32.EnumChildWindows(wintypes.HWND(parent), WNDENUMPROC(visit), 0)
    return found


def pixels():
    """Where the page's magenta survives, by distance from the window's centre.

    The whole question is *where* content that ignores the region is painted, so the
    samples are classified by radius against the two circles that matter:

    * ``inside_page_circle`` (r < 70): the page's own dark circle -- magenta here
      would mean the page is not drawing what it says;
    * ``inside_region_only`` (70 <= r < 90): **inside the region, outside the page's
      circle**. The page's body background belongs here, and this is where magenta
      is *expected* if the region is honoured;
    * ``outside_region`` (r >= 90): outside the window entirely. **Magenta here is
      the bug** -- content painted where the region says the window is not, which is
      the rectangle the user can see.

    A ring *around* the window is also sampled, for a DWM shadow drawn to the
    window's rectangle rather than to its region.
    """
    from PIL import ImageGrab

    x, y = AT
    image = ImageGrab.grab(bbox=(x, y, x + SIZE, y + SIZE), all_screens=True)
    centre = SIZE / 2 - 0.5

    def magenta_at(px: int, py: int) -> bool:
        r, g, b = image.getpixel((px, py))[:3]
        return r > 200 and b > 200 and g < 80

    bands = {"inside_page_circle": 0, "inside_region_only": 0, "outside_region": 0}
    totals = {"inside_page_circle": 0, "inside_region_only": 0, "outside_region": 0}
    for px in range(SIZE):
        for py in range(SIZE):
            radius = ((px - centre) ** 2 + (py - centre) ** 2) ** 0.5
            if radius < 70:
                band = "inside_page_circle"
            elif radius < 90:
                band = "inside_region_only"
            else:
                band = "outside_region"
            totals[band] += 1
            if magenta_at(px, py):
                bands[band] += 1

    ring = ImageGrab.grab(
        bbox=(x - 10, y - 10, x + SIZE + 10, y + SIZE + 10), all_screens=True
    )
    corners = {
        "outside_tl": ring.getpixel((2, 2))[:3],
        "outside_tr": ring.getpixel((SIZE + 17, 2))[:3],
        "outside_bl": ring.getpixel((2, SIZE + 17))[:3],
    }
    return {
        "magenta_by_band": bands,
        "pixels_in_band": totals,
        "probe_corners_of_window": {
            "top_left": image.getpixel((2, 2))[:3],
            "top_right": image.getpixel((SIZE - 3, 2))[:3],
            "bottom_left": image.getpixel((2, SIZE - 3))[:3],
            "centre": image.getpixel((SIZE // 2, SIZE // 2))[:3],
        },
        "ring_around_window": corners,
    }


def main() -> None:
    import os

    notes: dict[str, object] = {"at": AT, "size": SIZE}
    window = webview.create_window(
        "repro",
        html=PAGE,
        width=SIZE,
        height=SIZE,
        min_size=(SIZE, SIZE),
        x=AT[0],
        y=AT[1],
        frameless=True,
        resizable=False,
        on_top=True,
        focus=False,
        text_select=False,
        background_color="#1a1a1a",
    )

    def when_up() -> None:
        try:
            hwnd = 0
            for _ in range(60):
                time.sleep(0.25)
                native = getattr(window, "native", None)
                if native is None:
                    continue
                hwnd = win32.root_window(int(native.Handle.ToInt64()))
                if hwnd:
                    break
            notes["hwnd"] = hwnd
            win32.clip_to_circle(hwnd)
            probe = gdi32.CreateRectRgn(0, 0, 1, 1)
            notes["root_region"] = {
                0: "none",
                1: "empty",
                2: "rect",
                3: "complex",
            }.get(user32.GetWindowRgn(wintypes.HWND(hwnd), probe), "?")
            notes["corner_inside"] = bool(gdi32.PtInRegion(probe, 0, 0))
            notes["centre_inside"] = bool(gdi32.PtInRegion(probe, SIZE // 2, SIZE // 2))
            gdi32.DeleteObject(probe)
            # This thread is not the window's thread; the tree is only being read.
            notes["tree"] = window_tree(hwnd)
            time.sleep(1.5)  # let the page paint before looking at pixels
            notes["pixels"] = pixels()
        except Exception as exc:  # noqa: BLE001 - a repro reports, it does not raise
            notes["error"] = repr(exc)
        finally:
            OUT.write_text(json.dumps(notes, indent=2, default=str), encoding="utf-8")
            os._exit(0)

    window.events.shown += lambda *a: None
    threading.Thread(target=when_up, daemon=True).start()
    webview.start()


if __name__ == "__main__":
    main()
