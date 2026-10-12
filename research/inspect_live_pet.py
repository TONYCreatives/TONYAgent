"""Why is there still a square around the live pet?

Two candidate explanations, and they are distinguishable by measurement:

1. **The window paints its whole rectangle** -- the region is missing, so the page's
   own background (or the shadow) fills the corners. The tell is that pixels *inside*
   the window's rect but outside its circle are dark.
2. **Something outside the rect is darkening it** -- a DWM shadow, which is drawn to
   the rectangle and therefore shows up *outside* the rect, in the ring around it.

Also reported: which process is showing the pet, when it started, and what the repo's
last pet commit was -- because a running app that predates the fix looks exactly like
a fix that did not work.
"""

import ctypes
import json
import pathlib
import subprocess
import sys
from ctypes import wintypes

from PIL import ImageGrab

WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32
kernel32 = ctypes.windll.kernel32

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
REGIONS = {0: "none", 1: "empty", 2: "rect", 3: "complex"}
EXFLAGS = {
    "LAYERED": 0x80000,
    "NOACTIVATE": 0x8000000,
    "TOPMOST": 0x8,
    "TOOLWINDOW": 0x80,
    "NOREDIRECTIONBITMAP": 0x200000,
}


def process_of(pid: int) -> dict:
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return {"path": "", "started": ""}
    try:
        buffer = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(len(buffer))
        kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size))
        created = wintypes.FILETIME()
        exited = wintypes.FILETIME()
        kernel = wintypes.FILETIME()
        user = wintypes.FILETIME()
        kernel32.GetProcessTimes(
            handle, ctypes.byref(created), ctypes.byref(exited),
            ctypes.byref(kernel), ctypes.byref(user),
        )
        # FILETIME is 100ns since 1601; this is only for a human to compare by eye.
        ticks = (created.dwHighDateTime << 32) | created.dwLowDateTime
        return {"path": buffer.value, "started": str(ticks)}
    finally:
        kernel32.CloseHandle(handle)


def main() -> None:
    found: list[dict] = []

    def visit(hwnd, _lparam):
        if not user32.IsWindowVisible(wintypes.HWND(hwnd)):
            return True
        title = ctypes.create_unicode_buffer(256)
        klass = ctypes.create_unicode_buffer(256)
        user32.GetWindowTextW(wintypes.HWND(hwnd), title, 256)
        user32.GetClassNameW(wintypes.HWND(hwnd), klass, 256)
        box = wintypes.RECT()
        user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(box))
        width, height = box.right - box.left, box.bottom - box.top
        if title.value != "TONYAgent" and "WindowsForms10" not in klass.value:
            return True
        if not (120 <= width <= 260 and 120 <= height <= 260):
            return True

        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(wintypes.HWND(hwnd), ctypes.byref(pid))
        region = gdi32.CreateRectRgn(0, 0, 1, 1)
        kind = user32.GetWindowRgn(wintypes.HWND(hwnd), region)
        ex = user32.GetWindowLongW(wintypes.HWND(hwnd), -20)
        entry = {
            "hwnd": int(hwnd),
            "pid": pid.value,
            "rect": [box.left, box.top, width, height],
            "region": REGIONS.get(kind, kind),
            "corner_inside": bool(gdi32.PtInRegion(region, 0, 0)) if kind else None,
            "centre_inside": bool(gdi32.PtInRegion(region, width // 2, height // 2)) if kind else None,
            "ex_style": hex(ex & 0xFFFFFFFF),
            "styles": [name for name, bit in EXFLAGS.items() if ex & bit],
            **process_of(pid.value),
        }
        gdi32.DeleteObject(region)
        found.append(entry)
        return True

    user32.EnumWindows(WNDENUMPROC(visit), 0)

    for entry in found:
        left, top, width, height = entry["rect"]
        reference = ImageGrab.grab(bbox=(left, top + height + 220, left + 20, top + height + 240), all_screens=True)
        far = reference.getpixel((10, 10))[:3]
        grab = ImageGrab.grab(
            bbox=(left - 16, top - 16, left + width + 16, top + height + 16), all_screens=True
        ).convert("RGB")

        def at(x: int, y: int) -> list:
            return list(grab.getpixel((x + 16, y + 16)))

        inside_corners = [at(3, 3), at(width - 4, 3), at(3, height - 4), at(width - 4, height - 4)]
        just_outside = [at(-4, -4), at(width + 3, -4), at(width + 3, height + 3), at(-4, height + 3)]
        far_outside = [at(-14, -14), at(width + 13, height + 13)]
        entry["pixels"] = {
            "corners_inside_the_rect": inside_corners,
            "just_outside_the_rect": just_outside,
            "further_outside": far_outside,
            "wallpaper_far_below": list(far),
            "centre": at(width // 2, height // 2),
        }
        dark_inside = sum(1 for c in inside_corners if sum(c) / 3 < 90)
        entry["verdict"] = (
            "the window paints its rectangle (region missing or ignored)"
            if dark_inside
            else "the rectangle is outside the window (a shadow, if anything is dark there)"
        )

    repo = pathlib.Path(__file__).resolve().parents[1]
    last = subprocess.run(
        ["git", "log", "-1", "--format=%h %ci %s", "--", "src/tonyagent/window/pet.py"],
        cwd=repo, capture_output=True, text=True,
    ).stdout.strip()

    out = pathlib.Path(".tmp-live-pet.json")
    out.write_text(json.dumps({"windows": found, "last_pet_commit": last}, indent=2), encoding="utf-8")
    for entry in found:
        print(f"hwnd={entry['hwnd']} pid={entry['pid']} rect={entry['rect']} region={entry['region']} "
              f"corner_in={entry['corner_inside']} styles={entry['styles']}")
        print(f"   process: {entry['path']} started={entry['started']}")
        print(f"   pixels : corners_in={entry['pixels']['corners_inside_the_rect']} "
              f"just_out={entry['pixels']['just_outside_the_rect']}")
        print(f"   far_out={entry['pixels']['further_outside']} wallpaper={entry['pixels']['wallpaper_far_below']}")
        print(f"   verdict: {entry['verdict']}")
    print(f"last pet.py commit: {last}")
    if not found:
        print("no live pet window found")
        sys.exit(0)


if __name__ == "__main__":
    main()
