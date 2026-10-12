"""What is the Yuanbao pet, exactly? Look at it and list all its windows.

The first pass found a `Tauri Window` (WRY_WEBVIEW -> Chrome_WidgetWin_1: Tauri with
WebView2) but the pixel probe of the smallest candidate came back light blue and
white, which is not the green creature the screen shows. So: screenshot the area and
list *every* window that process owns, visible or not, and let the picture say which
window is which.
"""

import ctypes
import pathlib
from ctypes import wintypes

from PIL import ImageGrab

WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32

GWL_EXSTYLE = -20
WS_EX_FLAGS = {
    "topmost": 0x00000008,
    "transparent": 0x00000020,
    "toolwindow": 0x00000080,
    "layered": 0x00080000,
    "noactivate": 0x08000000,
    "noredirectionbitmap": 0x00200000,
    "composited": 0x02000000,
}
REGIONS = {0: "none", 1: "empty", 2: "rect", 3: "complex"}
PID = 3536
AREA = (1600, 80, 1860, 300)


def main() -> None:
    print(f"--- every window of pid {PID} ---")
    found: list[int] = []

    def visit(hwnd, _lparam):
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(wintypes.HWND(hwnd), ctypes.byref(pid))
        if pid.value == PID:
            found.append(int(hwnd))
        return True

    user32.EnumWindows(WNDENUMPROC(visit), 0)
    for hwnd in found:
        box = wintypes.RECT()
        user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(box))
        klass = ctypes.create_unicode_buffer(256)
        title = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(wintypes.HWND(hwnd), klass, 256)
        user32.GetWindowTextW(wintypes.HWND(hwnd), title, 256)
        ex = user32.GetWindowLongW(wintypes.HWND(hwnd), GWL_EXSTYLE)
        probe = gdi32.CreateRectRgn(0, 0, 4, 4)
        region = user32.GetWindowRgn(wintypes.HWND(hwnd), probe)
        # Where does the region actually allow? (0,0) of a clipped window is out.
        corner_in = bool(gdi32.PtInRegion(probe, 0, 0)) if region else None
        corner_in2 = bool(gdi32.PtInRegion(probe, 1, 1)) if region else None
        gdi32.DeleteObject(probe)
        print(
            f"hwnd={hwnd:<9} visible={bool(user32.IsWindowVisible(wintypes.HWND(hwnd)))!s:<5} "
            f"class={klass.value[:28]:28} rect=({box.left},{box.top},{box.right - box.left}x{box.bottom - box.top}) "
            f"styles={[n for n, b in WS_EX_FLAGS.items() if ex & b]} region={REGIONS.get(region, region)} corner={corner_in}"
        )

    image = ImageGrab.grab(bbox=AREA, all_screens=True)
    out = pathlib.Path(".tmp-yuanbao-pet.png")
    image.resize((image.width * 3, image.height * 3), 0).save(out)
    print(f"--- saved {out} ({AREA}) ---")
    print("corner of the grab:", image.getpixel((0, 0))[:3], "centre:", image.getpixel((image.width // 2, image.height // 2))[:3])


if __name__ == "__main__":
    main()
