"""Ask the *running* app's window what DWM is doing with its corners.

Attaches by window title, so this measures the shipped path -- the real
`python -m tonyagent.window`, started by the launcher -- rather than a harness's
re-implementation of it.

Two instruments, because one is not enough:

* `DwmGetWindowAttribute(DWMWA_WINDOW_CORNER_PREFERENCE)` says what DWM actually
  holds. It read **0** (default) for the whole time `shadow` was `False`, which
  is how the first bug was found: `DwmSetWindowAttribute` had returned success
  and been discarded.
* the screen grab says whether that preference reached the pixels. The grab is
  the whole screen and the crop is by the window's own rect, because an earlier
  version cropped to a rectangle that was not where the window was and reported
  a flat colour as if it were a measurement.
"""

from __future__ import annotations

import ctypes
import time

from PIL import ImageGrab

user32 = ctypes.windll.user32
dwmapi = ctypes.windll.dwmapi

user32.SetProcessDPIAware()
user32.FindWindowW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p]
user32.FindWindowW.restype = ctypes.c_void_p
dwmapi.DwmGetWindowAttribute.argtypes = [
    ctypes.c_void_p,
    ctypes.c_uint,
    ctypes.c_void_p,
    ctypes.c_uint,
]
dwmapi.DwmGetWindowAttribute.restype = ctypes.c_long


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


def main() -> int:
    hwnd = user32.FindWindowW(None, "TONYAgent")
    if not hwnd:
        print("the TONYAgent window is not running")
        return 1
    print(f"hwnd {hwnd}")

    preference = ctypes.c_int(-1)
    hr = dwmapi.DwmGetWindowAttribute(hwnd, 33, ctypes.byref(preference), 4)
    print(f"corner preference: hr={hr} value={preference.value}"
          "   (0=default 1=donotround 2=round 3=roundsmall)")

    rect = RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    width = rect.right - rect.left
    height = rect.bottom - rect.top
    print(f"rect {rect.left},{rect.top} {width}x{height}")

    # Topmost, so the grab cannot catch whatever the console is showing.
    user32.SetWindowPos(hwnd, -1, 0, 0, 0, 0, 0x0002 | 0x0001 | 0x0010)
    time.sleep(1.0)

    screen = ImageGrab.grab()
    print(f"screen {screen.size}")

    def px(x: int, y: int) -> str:
        return "#{:02x}{:02x}{:02x}".format(*screen.getpixel((x, y))[:3])

    print("  diagonal from the window's top-left, 12px in:")
    print("    " + " ".join(px(rect.left + i, rect.top + i) for i in range(12)))
    print(f"  control 200px inside the window: {px(rect.left + 200, rect.top + 200)}")
    print(f"  control  60px up and left of it: {px(rect.left - 60, rect.top - 60)}")

    # The picture. `#` is the window's own chrome, `.` is anything else -- so a
    # square corner is a solid block and a rounded one is a quarter circle.
    # Sampled 60px in on the top bar, which is chrome wherever it is.
    bar = screen.getpixel((rect.left + 60, rect.top + 30))[:3]
    print(f"  the bar's own colour, sampled 60px in: {px(rect.left + 60, rect.top + 30)}")
    print("  the corner, 24x24 physical px ('#' = within 8 of that colour):")
    for y in range(24):
        row = ""
        for x in range(24):
            pixel = screen.getpixel((rect.left + x, rect.top + y))[:3]
            row += "#" if all(abs(pixel[i] - bar[i]) <= 8 for i in range(3)) else "."
        print("    " + row)

    print("")
    print("  Rounded  => a quarter circle of '.' in the top-left.")
    print("  Square   => the whole block is '#'.")

    user32.SetWindowPos(hwnd, -2, 0, 0, 0, 0, 0x0002 | 0x0001 | 0x0010)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
