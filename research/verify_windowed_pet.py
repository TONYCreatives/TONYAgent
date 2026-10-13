"""Does the card come up as a real window -- rounded corners and a shadow?

The bet is that `WS_THICKFRAME` plus "no non-client area" is what makes DWM round a
window and shadow it, the way it does for the app's own window. That bet is about a
window with `WS_EX_NOACTIVATE` and `WS_EX_TOPMOST` and no activate-on-show, which the
app's window is *not*, so it is worth measuring rather than assuming.

Opens the real `DeskPet` -- the real code path, real styles -- over a pure white
topmost backdrop, with an opaque page so the three things are distinguishable:

* the card's own colour, `#202020`, if the corners are still square;
* the backdrop's white, if DWM has rounded the corner away;
* anything darker than both, just outside the box, if DWM has painted the shadow.
"""

import ctypes
import json
import os
import pathlib
import threading
import time
from ctypes import wintypes

import webview

from tonyagent.window import pet as pet_module
from tonyagent.window import win32

SIZE = 180
CARD = (32, 32, 32)  # #202020
PAGE = "<html><body style='margin:0;background:#202020'></body></html>"
BACKDROP_AT = (60, 60)
BACKDROP_SIZE = 420
PET_AT = (BACKDROP_AT[0] + 120, BACKDROP_AT[1] + 120)

OUT = pathlib.Path(".tmp-windowed-pet.json")

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32

WS_THICKFRAME = 0x00040000
REGIONS = {0: "none", 1: "empty", 2: "rect", 3: "complex"}
EXFLAGS = {"TOPMOST": 0x8, "TOOLWINDOW": 0x80, "LAYERED": 0x80000, "NOACTIVATE": 0x8000000}


def main() -> None:
    notes: dict[str, object] = {}
    webview.create_window(
        "backdrop",
        html="<html><body style='margin:0;background:#ffffff'></body></html>",
        width=BACKDROP_SIZE,
        height=BACKDROP_SIZE,
        x=BACKDROP_AT[0],
        y=BACKDROP_AT[1],
        frameless=True,
        resizable=False,
        on_top=True,
    )
    # `html=` rather than a `data:` URL: the first version of this probe passed the
    # colour in a data URL and the page came up *white*, which on a white backdrop
    # cannot tell a rounded corner from a square one. The card colour has to be the
    # one thing that is certain.
    card = webview.create_window(
        "card",
        html=PAGE,
        width=SIZE,
        height=SIZE,
        min_size=(SIZE, SIZE),
        x=PET_AT[0],
        y=PET_AT[1],
        frameless=True,
        resizable=False,
        on_top=True,
        focus=False,
        text_select=False,
        background_color="#1a1a1a",
    )
    notes["opened"] = bool(card)

    def when_up() -> None:
        try:
            hwnd = 0
            for _ in range(80):
                time.sleep(0.25)
                hwnd = pet_module._handle(card) if card else 0
                if hwnd:
                    break
            notes["hwnd"] = hwnd
            notes["dressed"] = pet_module._windowed(card)
            if not hwnd:
                raise RuntimeError("the card never came up")

            style = user32.GetWindowLongW(wintypes.HWND(hwnd), -16)
            ex = user32.GetWindowLongW(wintypes.HWND(hwnd), -20)
            probe = gdi32.CreateRectRgn(0, 0, 1, 1)
            notes["region"] = REGIONS.get(user32.GetWindowRgn(wintypes.HWND(hwnd), probe))
            gdi32.DeleteObject(probe)
            notes["has_thick_frame"] = bool(style & WS_THICKFRAME)
            notes["styles"] = [n for n, b in EXFLAGS.items() if ex & b]
            box = win32.RECT()
            user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(box))
            notes["rect"] = [box.left, box.top, box.right - box.left, box.bottom - box.top]
            notes["minimum_size"] = [
                card.native.MinimumSize.Width,
                card.native.MinimumSize.Height,
            ]
            notes["maximum_size"] = [
                card.native.MaximumSize.Width,
                card.native.MaximumSize.Height,
            ]

            from PIL import ImageGrab

            time.sleep(2.0)
            left, top = box.left, box.top
            grab = ImageGrab.grab(
                bbox=(left - 12, top - 12, left + SIZE + 12, top + SIZE + 12), all_screens=True
            ).convert("RGB")

            def at(x: int, y: int) -> list:
                return list(grab.getpixel((x + 12, y + 12)))

            corners = [at(2, 2), at(SIZE - 3, 2), at(2, SIZE - 3), at(SIZE - 3, SIZE - 3)]
            edges = [at(SIZE // 2, 2), at(2, SIZE // 2), at(SIZE - 3, SIZE // 2), at(SIZE // 2, SIZE - 3)]
            ring = [at(-5, -5), at(SIZE + 4, -5), at(-5, SIZE + 4), at(SIZE + 4, SIZE + 4)]
            notes["pixels"] = {
                "card_colour": list(CARD),
                "corners": corners,
                "edge_midpoints": edges,
                "just_outside": ring,
                "centre": at(SIZE // 2, SIZE // 2),
            }
            # **The test, stated properly.** A rounded rectangle keeps its colour at
            # the edge midpoints and loses it at the corners, where what shows is
            # whatever DWM put behind the window -- here its own shadow over the
            # backdrop. A square card keeps its colour at the corners too, which is
            # exactly what the old one measured: `[32,32,32]` at all four.
            def not_the_card(colour: list) -> bool:
                return max(abs(channel - CARD[0]) for channel in colour) > 60

            edges_are_the_card = sum(1 for c in edges if not not_the_card(c)) >= 3
            corners_are_cut = sum(1 for c in corners if not_the_card(c)) >= 3
            notes["verdict"] = (
                "rounded: the corners are cut by DWM and the edges still meet the card"
                if edges_are_the_card and corners_are_cut
                else "still square: the corners are the card's own colour"
            )
            notes["shadow_outside"] = all(sum(c) / 3 < 250 for c in ring)
        except Exception as exc:  # noqa: BLE001 - a probe reports
            notes["error"] = repr(exc)
        finally:
            OUT.write_text(json.dumps(notes, indent=2, default=str), encoding="utf-8")
            os._exit(0)

    threading.Thread(target=when_up, daemon=True).start()
    webview.start()


if __name__ == "__main__":
    main()
