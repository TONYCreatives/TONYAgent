"""What governs the maximize/minimize transition, measured on this machine.

The animation is DWM's, so it can be vetoed in a few different places and they are
distinguishable:

1. **The system setting.** `MinAnimate` / `SPI_GETANIMATION` -- if the user has turned
   animation effects off, *no* window animates and no code in this app can change that.
2. **The window's own opt-out.** `DWMWA_TRANSITIONS_FORCEDISABLED` is per window, and
   a window that has it set is skipped by DWM whatever the system says.
3. **The window's style word.** Windows decides what kind of thing it is animating
   from the frame bits, so a custom-framed window that dropped `WS_CAPTION` while
   keeping `WS_THICKFRAME` is a different case from a normal window.

This prints all three for a known-animating control (Notepad, spawned and closed
here), for the app's own window if it is running, and for a window built with the
app's exact recipe -- so the difference, if there is one, is visible as a row.
"""

import ctypes
import subprocess
import time
from ctypes import wintypes

user32 = ctypes.windll.user32
WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

SPI_GETANIMATION = 0x0048
SPI_GETCLIENTAREAANIMATION = 0x1042
SPI_GETUIEFFECTS = 0x103E
DWMWA_TRANSITIONS_FORCEDISABLED = 3
DWMWA_NCRENDERING_ENABLED = 1
DWMWA_WINDOW_CORNER_PREFERENCE = 33
DWMWA_SYSTEMBACKDROP_TYPE = 38

STYLE_BITS = {
    "WS_CAPTION": 0x00C00000,
    "WS_THICKFRAME": 0x00040000,
    "WS_SYSMENU": 0x00080000,
    "WS_MINIMIZEBOX": 0x00020000,
    "WS_MAXIMIZEBOX": 0x00010000,
    "WS_POPUP": 0x80000000,
    "WS_CHILD": 0x40000000,
    "WS_VISIBLE": 0x10000000,
    "WS_CLIPSIBLINGS": 0x04000000,
    "WS_CLIPCHILDREN": 0x02000000,
    "WS_BORDER": 0x00800000,
    "WS_DLGFRAME": 0x00400000,
}
EX_BITS = {
    "TOPMOST": 0x8,
    "LAYERED": 0x80000,
    "TOOLWINDOW": 0x80,
    "NOACTIVATE": 0x8000000,
    "NOREDIRECTIONBITMAP": 0x200000,
    "APPWINDOW": 0x40000,
}


class ANIMATIONINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("iMinAnimate", ctypes.c_int)]


def system_settings() -> dict:
    info = ANIMATIONINFO()
    info.cbSize = ctypes.sizeof(ANIMATIONINFO)
    got = user32.SystemParametersInfoW(SPI_GETANIMATION, info.cbSize, ctypes.byref(info), 0)
    client = wintypes.BOOL()
    client_ok = user32.SystemParametersInfoW(
        SPI_GETCLIENTAREAANIMATION, 0, ctypes.byref(client), 0
    )
    effects = wintypes.BOOL()
    effects_ok = user32.SystemParametersInfoW(SPI_GETUIEFFECTS, 0, ctypes.byref(effects), 0)
    return {
        "min_animate": info.iMinAnimate if got else f"unreadable ({ctypes.GetLastError()})",
        "client_area_animation": bool(client.value) if client_ok else "unreadable",
        "ui_effects": bool(effects.value) if effects_ok else "unreadable",
    }


def dwm(hwnd: int, attribute: int) -> object:
    value = ctypes.c_int(-999)
    result = ctypes.windll.dwmapi.DwmGetWindowAttribute(
        wintypes.HWND(hwnd), wintypes.DWORD(attribute), ctypes.byref(value), ctypes.sizeof(value)
    )
    return value.value if result == 0 else f"hr={result}"


def describe(label: str, hwnd: int) -> dict:
    style = user32.GetWindowLongW(wintypes.HWND(hwnd), -16) & 0xFFFFFFFF
    ex = user32.GetWindowLongW(wintypes.HWND(hwnd), -20) & 0xFFFFFFFF
    title = ctypes.create_unicode_buffer(128)
    klass = ctypes.create_unicode_buffer(128)
    user32.GetWindowTextW(wintypes.HWND(hwnd), title, 128)
    user32.GetClassNameW(wintypes.HWND(hwnd), klass, 128)
    return {
        "label": label,
        "hwnd": hwnd,
        "title": title.value,
        "class": klass.value,
        "styles": [name for name, bit in STYLE_BITS.items() if style & bit],
        "ex_styles": [name for name, bit in EX_BITS.items() if ex & bit],
        "transitions_forcedisabled": dwm(hwnd, DWMWA_TRANSITIONS_FORCEDISABLED),
        "nc_rendering_enabled": dwm(hwnd, DWMWA_NCRENDERING_ENABLED),
        "corner_preference": dwm(hwnd, DWMWA_WINDOW_CORNER_PREFERENCE),
        "backdrop": dwm(hwnd, DWMWA_SYSTEMBACKDROP_TYPE),
    }


def find_app_window() -> int:
    """The app's own top-level window, if it is running: biggest, titled, not ours."""
    best = [0, 0]

    def visit(hwnd, _lparam):
        if not user32.IsWindowVisible(wintypes.HWND(hwnd)):
            return True
        title = ctypes.create_unicode_buffer(128)
        user32.GetWindowTextW(wintypes.HWND(hwnd), title, 128)
        box = wintypes.RECT()
        user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(box))
        area = (box.right - box.left) * (box.bottom - box.top)
        if title.value == "TONYAgent" and area > best[0] and box.right - box.left > 300:
            best[0], best[1] = area, int(hwnd)
        return True

    user32.EnumWindows(WNDENUMPROC(visit), 0)
    return best[1]


def main() -> None:
    print("--- system settings ---")
    for name, value in system_settings().items():
        print(f"  {name}: {value}")

    rows = []
    notepad = subprocess.Popen(["notepad.exe"])
    try:
        hwnd = 0
        for _ in range(40):
            time.sleep(0.25)
            candidate = find_app_window() or 0
            # Notepad's own window, by class, so the control is unambiguous.
            found = [0]

            def visit(handle, _lparam):
                klass = ctypes.create_unicode_buffer(64)
                user32.GetClassNameW(wintypes.HWND(handle), klass, 64)
                if klass.value in ("Notepad", "ApplicationFrameWindow") and not found[0]:
                    found[0] = int(handle)
                return True

            user32.EnumWindows(WNDENUMPROC(visit), 0)
            if found[0]:
                hwnd = found[0]
                break
        if hwnd:
            rows.append(describe("notepad (animates normally)", hwnd))
    finally:
        notepad.terminate()

    app = find_app_window()
    if app:
        rows.append(describe("the app's window", app))
    else:
        print("\n(the app is not running; its recipe is measured below instead)")

    print("\n--- windows ---")
    for row in rows:
        print(f"\n{row['label']}  hwnd={row['hwnd']} class={row['class']} title={row['title']!r}")
        print(f"  styles                : {row['styles']}")
        print(f"  ex styles             : {row['ex_styles']}")
        print(f"  transitions disabled  : {row['transitions_forcedisabled']}")
        print(f"  nc rendering enabled  : {row['nc_rendering_enabled']}")
        print(f"  corner preference     : {row['corner_preference']}  backdrop: {row['backdrop']}")


if __name__ == "__main__":
    main()
