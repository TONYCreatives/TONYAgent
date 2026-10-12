"""Which window in the pet's chain is painting the rectangle?

The live pet reports a complex region with its corner outside of it, yet those same
corner pixels read `[32,32,32]` -- the card's own colour. That can only be a closer
window painting, and a region does not necessarily clip a *child*: the child is
clipped to its parent's client rectangle, which the region does not change.

So: walk the chain around the live pet and report each window's class, box, region and
extended style, which is where the culprit has to be.
"""

import ctypes
from ctypes import wintypes

WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32

REGIONS = {0: "none", 1: "empty", 2: "rect", 3: "complex"}
EXFLAGS = {"TOPMOST": 0x8, "TRANSPARENT": 0x20, "TOOLWINDOW": 0x80,
           "LAYERED": 0x80000, "NOACTIVATE": 0x8000000, "NOREDIRECTIONBITMAP": 0x200000}
PET = 788474


def describe(hwnd: int, depth: int) -> None:
    klass = ctypes.create_unicode_buffer(256)
    title = ctypes.create_unicode_buffer(128)
    user32.GetClassNameW(wintypes.HWND(hwnd), klass, 256)
    user32.GetWindowTextW(wintypes.HWND(hwnd), title, 128)
    box = wintypes.RECT()
    user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(box))
    region = gdi32.CreateRectRgn(0, 0, 1, 1)
    kind = user32.GetWindowRgn(wintypes.HWND(hwnd), region)
    corner = bool(gdi32.PtInRegion(region, 0, 0)) if kind else None
    gdi32.DeleteObject(region)
    ex = user32.GetWindowLongW(wintypes.HWND(hwnd), -20)
    style = user32.GetWindowLongW(wintypes.HWND(hwnd), -16)
    print(
        f"{'  ' * depth}hwnd={hwnd:<9} {klass.value[:26]:26} "
        f"rect=({box.left},{box.top},{box.right - box.left}x{box.bottom - box.top}) "
        f"region={REGIONS.get(kind, kind):<7} corner_in={corner} "
        f"ex=[{','.join(n for n, b in EXFLAGS.items() if ex & b)}] "
        f"ws_child={bool(style & 0x40000000)} ws_visible={bool(style & 0x10000000)}"
        f" title={title.value[:16]!r}"
    )


def main() -> None:
    print("--- ancestors ---")
    chain = []
    current = PET
    while current:
        chain.append(current)
        current = user32.GetParent(wintypes.HWND(current))
    for hwnd in reversed(chain):
        describe(int(hwnd), len(chain) - 1 - chain.index(hwnd))

    print("--- descendants (EnumChildWindows enumerates all of them) ---")
    found: list[int] = []

    def visit(child, _lparam):
        found.append(int(child))
        return True

    user32.EnumChildWindows(wintypes.HWND(PET), WNDENUMPROC(visit), 0)
    for child in found:
        describe(child, 1)
    if not found:
        print("  (no children)")

    print("--- who owns the corner pixel? ---")
    point = wintypes.POINT(1611, 192)  # 3px inside the pet's top-left corner
    owner = user32.WindowFromPoint(point)
    print("  WindowFromPoint(1611,192) =", int(owner or 0))
    if owner:
        describe(int(owner), 0)
        box = wintypes.RECT()
        user32.GetWindowRect(wintypes.HWND(owner), ctypes.byref(box))
        print(f"  that window spans ({box.left},{box.top})..({box.right},{box.bottom})")


if __name__ == "__main__":
    main()
