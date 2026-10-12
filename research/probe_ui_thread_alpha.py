"""Set the browser's background on the window's own thread -- the last wall.

`DefaultBackgroundColor` is what makes WebView2's composition surface carry alpha, and
the previous probe failed to set it for two reasons at once: it was called from a probe
thread ("CoreWebView2Controller members can only be accessed from the UI thread") and
the raw cast to `ICoreWebView2Controller2` failed.

The thread part is fixable, and this repository already has the helper for exactly
that kind of call: `win32.on_window_thread`, which posts the work to the window's own
message loop. If the background goes transparent there, then the square is finally
explained *and* the shipped pet can be fixed without a rewrite: the page paints only
the card, the compositor carries its alpha, and the desktop shows through the corners.

If it still refuses, the WebView2 route is closed and the native layered window is the
only way to a round pet.
"""

import json
import os
import pathlib
import sys
import threading
import time

import clr

import webview

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

clr.AddReference("System.Drawing")
from System.Drawing import Color  # noqa: E402

from tonyagent.window import win32  # noqa: E402

PAGE = """
<html><body style="margin:0;background:transparent">
  <div style="width:150px;height:150px;border-radius:50%;background:#101010;margin:15px auto"></div>
</body></html>
"""

SIZE = 180
BACKDROP_AT = (420, 300)
BACKDROP_SIZE = 600
TEST_AT = (520, 420)
OUT = pathlib.Path(".tmp-ui-thread-alpha.json")


def sample() -> dict:
    from PIL import ImageGrab

    grab = ImageGrab.grab(
        bbox=(TEST_AT[0], TEST_AT[1], TEST_AT[0] + SIZE, TEST_AT[1] + SIZE), all_screens=True
    ).convert("RGB")
    return {
        "corners": [
            list(grab.getpixel(p)) for p in ((3, 3), (SIZE - 4, 3), (3, SIZE - 4), (SIZE - 4, SIZE - 4))
        ],
        "centre": list(grab.getpixel((SIZE // 2, SIZE // 2))),
        "unique_colours": len(grab.getcolors(maxcolors=1 << 24) or []),
    }


def main() -> None:
    notes: dict[str, object] = {}
    webview.create_window(
        "backdrop", html="<html><body style='margin:0;background:#ffffff'></body></html>",
        width=BACKDROP_SIZE, height=BACKDROP_SIZE, x=BACKDROP_AT[0], y=BACKDROP_AT[1],
        frameless=True, resizable=False, on_top=True,
    )
    test = webview.create_window(
        "ui-thread-alpha", html=PAGE, width=SIZE, height=SIZE, min_size=(SIZE, SIZE),
        x=TEST_AT[0], y=TEST_AT[1], frameless=True, resizable=False, on_top=True,
        focus=False, text_select=False, background_color="#1a1a1a", transparent=True,
    )

    def when_up() -> None:
        try:
            time.sleep(4.0)
            notes["before"] = sample()

            def make_transparent() -> None:
                browser = getattr(test.native, "webview", None)
                if browser is None:
                    notes["browser"] = "not reachable from the form"
                    return
                try:
                    browser.DefaultBackgroundColor = Color.Transparent
                    notes["set_on_ui_thread"] = "accepted"
                except Exception as exc:  # noqa: BLE001
                    notes["set_on_ui_thread"] = f"refused: {exc}"
                try:
                    notes["controller_read_back"] = str(browser.DefaultBackgroundColor)
                except Exception as exc:  # noqa: BLE001
                    notes["controller_read_back"] = f"unreadable: {exc}"

            win32.on_window_thread(test, make_transparent)
            time.sleep(2.0)
            notes["after"] = sample()
        except Exception as exc:  # noqa: BLE001 - a probe reports
            notes["error"] = repr(exc)
        finally:
            OUT.write_text(json.dumps(notes, indent=2, default=str), encoding="utf-8")
            os._exit(0)

    threading.Thread(target=when_up, daemon=True).start()
    webview.start()


if __name__ == "__main__":
    main()
