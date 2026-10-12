"""Is the opaque thing the WinForms form rather than the browser?

Both probe windows came back composition-hosted (`Chrome_WidgetWin_1` with
`NOREDIRECTIONBITMAP`, an `Intermediate D3D Window`) and neither showed the backdrop at
its corners -- so the plumbing can carry alpha and something opaque is in front of it.

pywebview's `transparent=True` reaches only the *browser*: it sets
`self.browser.DefaultBackgroundColor = Color.Transparent` and leaves the form's
`BackColor` alone. A WinForms form paints its background behind and around its
children, so that alone would keep the corners opaque. This walks the control tree,
makes every control's background transparent, and measures the corners after each
step -- which says whether that is the remaining wall or not.
"""

import ctypes
import json
import os
import pathlib
import threading
import time
from ctypes import wintypes

import clr

import webview

clr.AddReference("System.Drawing")
from System.Drawing import Color  # noqa: E402

PAGE = """
<html><body style="margin:0;background:transparent">
  <div style="width:150px;height:150px;border-radius:50%;background:#101010;margin:15px auto"></div>
</body></html>
"""

SIZE = 180
BACKDROP_AT = (420, 300)
BACKDROP_SIZE = 600
TEST_AT = (520, 420)
OUT = pathlib.Path(".tmp-form-alpha.json")

user32 = ctypes.windll.user32


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


def walk(control, depth: int = 0, make_transparent: bool = False, seen: list | None = None) -> list:
    seen = [] if seen is None else seen
    entry = {"depth": depth, "type": type(control).__name__}
    try:
        entry["back_colour"] = str(control.BackColor)
    except Exception as exc:  # noqa: BLE001
        entry["back_colour"] = f"unreadable: {exc}"
    if make_transparent:
        try:
            control.BackColor = Color.Transparent
            entry["set_transparent"] = True
        except Exception as exc:  # noqa: BLE001
            entry["set_transparent"] = f"refused: {exc}"
    seen.append(entry)
    try:
        for child in control.Controls:
            walk(child, depth + 1, make_transparent, seen)
    except Exception:  # noqa: BLE001
        pass
    return seen


def main() -> None:
    notes: dict[str, object] = {}
    webview.create_window(
        "backdrop", html="<html><body style='margin:0;background:#ffffff'></body></html>",
        width=BACKDROP_SIZE, height=BACKDROP_SIZE, x=BACKDROP_AT[0], y=BACKDROP_AT[1],
        frameless=True, resizable=False, on_top=True,
    )
    test = webview.create_window(
        "form-alpha", html=PAGE, width=SIZE, height=SIZE, min_size=(SIZE, SIZE),
        x=TEST_AT[0], y=TEST_AT[1], frameless=True, resizable=False, on_top=True,
        focus=False, text_select=False, background_color="#1a1a1a", transparent=True,
    )

    def when_up() -> None:
        try:
            time.sleep(3.5)
            notes["before"] = sample()
            native = getattr(test, "native", None)
            notes["native_type"] = type(native).__name__ if native is not None else None
            notes["controls_before"] = walk(native) if native is not None else []
            if native is not None:
                notes["controls_after"] = walk(native, make_transparent=True)
            time.sleep(1.5)
            notes["after_form_transparent"] = sample()

            # And the browser control's own background, which is what pywebview sets.
            browser = getattr(native, "webview", None)
            if browser is not None:
                try:
                    browser.DefaultBackgroundColor = Color.Transparent
                    notes["browser_default_background"] = "set"
                except Exception as exc:  # noqa: BLE001
                    notes["browser_default_background"] = f"refused: {exc}"
                time.sleep(1.2)
                notes["after_browser_transparent"] = sample()
        except Exception as exc:  # noqa: BLE001 - a probe reports
            notes["error"] = repr(exc)
        finally:
            OUT.write_text(json.dumps(notes, indent=2, default=str), encoding="utf-8")
            os._exit(0)

    threading.Thread(target=when_up, daemon=True).start()
    webview.start()


if __name__ == "__main__":
    main()
