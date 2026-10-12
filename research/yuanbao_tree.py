"""Which layer of the Yuanbao pet window carries the transparency?

The top-level `Tauri Window` has no `WS_EX_LAYERED` and no
`WS_EX_NOREDIRECTIONBITMAP`, yet the app's text behind it shows through to the
creature's silhouette -- so the alpha is coming from somewhere. This walks the whole
window tree of that process and reports each window's raw extended style, its
layered attributes, and its region, which is where the mechanism has to be.
"""

import ctypes
from ctypes import wintypes

WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32

GWL_EXSTYLE = -20
GWL_STYLE = -16
FLAGS = {
    "TOPMOST": 0x00000008,
    "TRANSPARENT": 0x00000020,
    "TOOLWINDOW": 0x00000080,
    "LAYERED": 0x00080000,
    "NOACTIVATE": 0x08000000,
    "NOREDIRECTIONBITMAP": 0x00200000,
    "COMPOSITED": 0x02000000,
}
STYLE_FLAGS = {"WS_POPUP": 0x80000000, "WS_CHILD": 0x40000000, "WS_VISIBLE": 0x10000000}
REGIONS = {0: "none", 1: "empty", 2: "rect", 3: "complex"}
PET = 198122

#: `DwmGetWindowAttribute` ids worth reading on a window that is claiming alpha.
DWMWA_EXTENDED_FRAME_BOUNDS = 9
DWMWA_CLOAKED = 14


def layered(hwnd: int) -> str:
    key = wintypes.DWORD()
    alpha = wintypes.BYTE()
    flags = wintypes.DWORD()
    if not user32.GetLayeredWindowAttributes(
        wintypes.HWND(hwnd), ctypes.byref(key), ctypes.byref(alpha), ctypes.byref(flags)
    ):
        return "unreadable"
    parts = []
    if flags.value & 0x1:
        parts.append(f"colorkey={hex(key.value)}")
    if flags.value & 0x2:
        parts.append(f"alpha={alpha.value}")
    return ", ".join(parts) or "no flags"


def describe(hwnd: int, depth: int) -> None:
    klass = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(wintypes.HWND(hwnd), klass, 256)
    ex = user32.GetWindowLongW(wintypes.HWND(hwnd), GWL_EXSTYLE)
    style = user32.GetWindowLongW(wintypes.HWND(hwnd), GWL_STYLE)
    box = wintypes.RECT()
    user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(box))
    probe = gdi32.CreateRectRgn(0, 0, 1, 1)
    region = user32.GetWindowRgn(wintypes.HWND(hwnd), probe)
    corner = bool(gdi32.PtInRegion(probe, 0, 0)) if region else None
    gdi32.DeleteObject(probe)
    frame = ctypes.c_int * 4
    bounds = frame(0, 0, 0, 0)
    dwm = ctypes.windll.dwmapi.DwmGetWindowAttribute(
        wintypes.HWND(hwnd), DWMWA_EXTENDED_FRAME_BOUNDS, ctypes.byref(bounds), ctypes.sizeof(bounds)
    )
    print(
        f"{'  ' * depth}hwnd={hwnd:<9} {klass.value[:26]:26} "
        f"rect=({box.left},{box.top},{box.right - box.left}x{box.bottom - box.top}) "
        f"region={REGIONS.get(region, region):<7} corner={corner} "
        f"ex={hex(ex & 0xFFFFFFFF)} [{','.join(n for n, b in FLAGS.items() if ex & b)}] "
        f"style=[{','.join(n for n, b in STYLE_FLAGS.items() if style & b)}] "
        f"layered={layered(hwnd)} dwm_frame_hr={dwm}"
    )


def walk(hwnd: int, depth: int = 0) -> None:
    describe(hwnd, depth)

    def visit(child, _lparam):
        walk(int(child), depth + 1)
        return True

    user32.EnumChildWindows(wintypes.HWND(hwnd), WNDENUMPROC(visit), 0)


if __name__ == "__main__":
    walk(PET)
