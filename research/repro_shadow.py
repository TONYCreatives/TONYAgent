"""Is the rectangle a DWM shadow drawn to the window's rect instead of its region?

The circular region works -- measured: no page content survives outside it. So the
rectangle the user sees is not the page. The candidate this tests is the window's
own shadow: Windows draws one for a top-level window, and if it follows the
window's *rectangle* rather than the region, a round pet sits inside a faint
rectangular halo -- which is exactly what "a rectangle window outside that circle"
looks like.

The discriminator is where the shadow falls. A circle inscribed in a square touches
the square's edges at their midpoints, so just outside the rect:

* at an **edge midpoint** the circle is right there -> a circular shadow would fall;
* at a **corner** the circle is ~30px away -> only a *rectangular* shadow reaches.

So the pet is placed over a pure white window (so any darkening is unambiguous) and
the pixels just outside the rect are read at three corners and three edge midpoints.
Equal darkening at both -> the shadow is rectangular.

Run with: python research/repro_shadow.py -- writes .tmp-shadow.json and exits.
"""

import ctypes
import json
import pathlib
import threading
import time

import webview

from tonyagent.window import win32

SIZE = 180
WHITE_AT = (60, 60)
WHITE_SIZE = 420
PET_AT = (WHITE_AT[0] + 120, WHITE_AT[1] + 120)
OUT = pathlib.Path(".tmp-shadow.json")

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32
dwmapi = ctypes.windll.dwmapi

#: `DwmSetWindowAttribute` attribute ids, from `dwmapi.h`.
DWMWA_NCRENDERING_POLICY = 2
DWMNCRP_DISABLED = 1


def disable_nc_rendering(hwnd: int) -> str:
    """Turn off DWM's non-client rendering -- which is what draws the shadow."""
    value = ctypes.c_int(DWMNCRP_DISABLED)
    result = dwmapi.DwmSetWindowAttribute(
        ctypes.wintypes.HWND(hwnd),
        ctypes.c_uint(DWMWA_NCRENDERING_POLICY),
        ctypes.byref(value),
        ctypes.sizeof(value),
    )
    return f"hr={result}"


def sample_around(radii: tuple[int, ...] = (6, 14)) -> dict[str, list[int]]:
    """Pixel values at the corners and edge midpoints, `radii` px outside the rect."""
    from PIL import ImageGrab

    left, top = PET_AT
    right, bottom = left + SIZE, top + SIZE
    middle_x, middle_y = left + SIZE // 2, top + SIZE // 2
    spots: dict[str, tuple[int, int]] = {}
    for gap in radii:
        spots[f"corner_tl_{gap}"] = (left - gap, top - gap)
        spots[f"corner_tr_{gap}"] = (right + gap, top - gap)
        spots[f"corner_bl_{gap}"] = (left - gap, bottom + gap)
        spots[f"edge_left_{gap}"] = (left - gap, middle_y)
        spots[f"edge_top_{gap}"] = (middle_x, top - gap)
        spots[f"edge_right_{gap}"] = (right + gap, middle_y)
        spots[f"edge_bottom_{gap}"] = (middle_x, bottom + gap)

    grab = ImageGrab.grab(
        bbox=(left - 40, top - 40, right + 40, bottom + 40), all_screens=True
    )
    origin = (left - 40, top - 40)
    return {
        name: list(grab.getpixel((x - origin[0], y - origin[1]))[:3])
        for name, (x, y) in spots.items()
    }


def main() -> None:
    import os

    notes: dict[str, object] = {"pet_at": PET_AT, "white_at": WHITE_AT}
    backdrop = webview.create_window(
        "backdrop",
        html="<html><body style='margin:0;background:#ffffff'></body></html>",
        width=WHITE_SIZE,
        height=WHITE_SIZE,
        x=WHITE_AT[0],
        y=WHITE_AT[1],
        frameless=True,
        resizable=False,
        on_top=False,
    )
    pet = webview.create_window(
        "shadow-probe",
        html=(
            "<html><body style='margin:0;background:#202020'>"
            "<div style='width:180px;height:180px;border-radius:50%;background:#202020'>"
            "</div></body></html>"
        ),
        width=SIZE,
        height=SIZE,
        min_size=(SIZE, SIZE),
        x=PET_AT[0],
        y=PET_AT[1],
        frameless=True,
        resizable=False,
        on_top=True,
        focus=False,
    )

    def when_up() -> None:
        try:
            hwnd = 0
            for _ in range(60):
                time.sleep(0.25)
                native = getattr(pet, "native", None)
                if native is None:
                    continue
                hwnd = win32.root_window(int(native.Handle.ToInt64()))
                if hwnd:
                    break
            win32.clip_to_circle(hwnd)
            notes["hwnd"] = hwnd
            probe = gdi32.CreateRectRgn(0, 0, 1, 1)
            notes["region"] = {0: "none", 1: "empty", 2: "rect", 3: "complex"}.get(
                user32.GetWindowRgn(ctypes.wintypes.HWND(hwnd), probe)
            )
            gdi32.DeleteObject(probe)
            time.sleep(2.0)  # let the shadow settle and the page paint
            notes["around_visible"] = sample_around()
            # The candidate fix: DWM's non-client rendering is what draws the shadow,
            # and it follows the window's rectangle rather than its region.
            notes["nc_rendering"] = disable_nc_rendering(hwnd)
            time.sleep(1.0)
            notes["around_after_nc_disabled"] = sample_around()
            pet.hide()
            time.sleep(1.5)
            notes["around_hidden"] = sample_around()
        except Exception as exc:  # noqa: BLE001 - a probe reports, it does not raise
            notes["error"] = repr(exc)
        finally:
            OUT.write_text(json.dumps(notes, indent=2, default=str), encoding="utf-8")
            os._exit(0)

    threading.Thread(target=when_up, daemon=True).start()
    webview.start()


if __name__ == "__main__":
    main()
