"""Clip the window that paints, not the wrapper around it.

The live pet's region sits on the top-level wrapper (`788474`, `region=complex`,
corner outside) while the window that actually paints is its child
(`264228`, `region=none`). A region constrains a window's own surface; it is the
parent's *client rectangle* that clips a child, and a region does not change that. So
the child paints its full rectangle over the corners and the card looks square -- with
the shadow (the earlier cause) already gone, since the pixels outside the rect are
wallpaper now.

This applies the same ellipse to the whole chain and measures the corner pixels after
each step, which says both whether the diagnosis is right and which windows need it.
It edits a *running* window's region: cosmetic, undone by a restart, and restored by
`SetWindowRgn(hwnd, None, TRUE)`.
"""

import ctypes
import sys
from ctypes import wintypes

from PIL import ImageGrab

WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32

REGIONS = {0: "none", 1: "empty", 2: "rect", 3: "complex"}
SIZE = 180


def find_pet() -> tuple[int, tuple[int, int, int, int]]:
    found: list[tuple[int, tuple[int, int, int, int]]] = []

    def visit(hwnd, _lparam):
        title = ctypes.create_unicode_buffer(256)
        user32.GetWindowTextW(wintypes.HWND(hwnd), title, 256)
        box = wintypes.RECT()
        user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(box))
        if title.value == "TONYAgent" and (box.right - box.left, box.bottom - box.top) == (SIZE, SIZE):
            found.append((int(hwnd), (box.left, box.top, box.right, box.bottom)))
        return True

    user32.EnumWindows(WNDENUMPROC(visit), 0)
    if not found:
        raise SystemExit("the pet window is not on screen")
    return found[0]


def descendants(hwnd: int) -> list[int]:
    found: list[int] = []

    def visit(child, _lparam):
        found.append(int(child))
        return True

    user32.EnumChildWindows(wintypes.HWND(hwnd), WNDENUMPROC(visit), 0)
    return found


def corners(left: int, top: int) -> list[list[int]]:
    grab = ImageGrab.grab(
        bbox=(left, top, left + SIZE, top + SIZE), all_screens=True
    ).convert("RGB")
    return [list(grab.getpixel(p)) for p in ((3, 3), (SIZE - 4, 3), (3, SIZE - 4), (SIZE - 4, SIZE - 4))]


def clip(hwnd: int) -> str:
    region = gdi32.CreateEllipticRgn(0, 0, SIZE, SIZE)
    ok = user32.SetWindowRgn(wintypes.HWND(hwnd), region, True)
    return "set" if ok else f"refused ({ctypes.GetLastError()})"


def region_of(hwnd: int) -> str:
    probe = gdi32.CreateRectRgn(0, 0, 1, 1)
    kind = user32.GetWindowRgn(wintypes.HWND(hwnd), probe)
    gdi32.DeleteObject(probe)
    return REGIONS.get(kind, str(kind))


def names(hwnds: list[int]) -> list[str]:
    out = []
    for hwnd in hwnds:
        klass = ctypes.create_unicode_buffer(128)
        user32.GetClassNameW(wintypes.HWND(hwnd), klass, 128)
        out.append(f"{hwnd}:{klass.value[:18]}")
    return out


def main() -> None:
    pet, (left, top, _right, _bottom) = find_pet()
    chain = descendants(pet)
    print(f"pet={pet} at ({left},{top}) region={region_of(pet)}")
    print("chain:", names(chain))
    print("corners before:", corners(left, top), "-> " + str("square" if corners(left, top)[0][0] < 90 else "round"))

    # Step 1: the painting form only. It is the WindowsForms child, not the wrapper.
    forms = [
        hwnd for hwnd in chain
        if ctypes.create_unicode_buffer(128) is not None
        and (lambda k=ctypes.create_unicode_buffer(128), h=hwnd: (
            user32.GetClassNameW(wintypes.HWND(h), k, 128), "WindowsForms10" in k.value
        )[1])()
    ]
    print("\nWindowsForms children:", names(forms))
    for hwnd in forms:
        print(f"  clipping {hwnd}: {clip(hwnd)}")
    after_form = corners(left, top)
    print("corners after clipping the form:", after_form)

    if after_form[0][0] < 90:
        # Step 2: the whole chain, since a child is clipped by its parent's *client
        # rect* and the grandchildren paint too.
        for hwnd in chain:
            clip(hwnd)
        after_all = corners(left, top)
        print("corners after clipping every descendant:", after_all)
        if after_all[0][0] < 90:
            print("still square: the painting window is not in this chain")
            sys.exit(1)
    print("\nround. The region belongs on the window that paints.")


if __name__ == "__main__":
    main()
