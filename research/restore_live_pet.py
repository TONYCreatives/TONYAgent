"""Put the live pet's window chain back the way it was.

`clip_painting_window.py` gave every descendant of the running pet an elliptic region
to test whether that would clip the square. It did not, so those regions are removed
again: they were an experiment on a live window, and only the top-level one (which the
app itself sets) should carry one.

Safe to run at any time: it clears a region only from windows below the top level.
"""

import ctypes
from ctypes import wintypes

WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32

REGIONS = {0: "none", 1: "empty", 2: "rect", 3: "complex"}
SIZE = 180


def find_pet() -> int:
    found: list[int] = []

    def visit(hwnd, _lparam):
        title = ctypes.create_unicode_buffer(128)
        user32.GetWindowTextW(wintypes.HWND(hwnd), title, 128)
        box = wintypes.RECT()
        user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(box))
        if title.value == "TONYAgent" and (box.right - box.left, box.bottom - box.top) == (SIZE, SIZE):
            found.append(int(hwnd))
        return True

    user32.EnumWindows(WNDENUMPROC(visit), 0)
    if not found:
        raise SystemExit("the pet window is not on screen")
    return found[0]


def region_of(hwnd: int) -> str:
    probe = gdi32.CreateRectRgn(0, 0, 1, 1)
    kind = user32.GetWindowRgn(wintypes.HWND(hwnd), probe)
    gdi32.DeleteObject(probe)
    return REGIONS.get(kind, str(kind))


def main() -> None:
    pet = find_pet()
    print(f"pet {pet}: region={region_of(pet)} (left alone: the app sets this one)")
    found: list[int] = []

    def visit(child, _lparam):
        found.append(int(child))
        return True

    user32.EnumChildWindows(wintypes.HWND(pet), WNDENUMPROC(visit), 0)
    for child in found:
        klass = ctypes.create_unicode_buffer(128)
        user32.GetClassNameW(wintypes.HWND(child), klass, 128)
        before = region_of(child)
        if before != "none":
            user32.SetWindowRgn(wintypes.HWND(child), None, True)
        print(f"  {child} {klass.value[:26]:26} region {before} -> {region_of(child)}")


if __name__ == "__main__":
    main()
