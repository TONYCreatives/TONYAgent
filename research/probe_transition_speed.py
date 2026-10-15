"""Does a transition animate? Fast enough to tell, and self-validating.

Two things were wrong with the first attempts and both are fixed here:

* **Sampling was too slow.** A 700x32 strip took ~60ms per grab, which is a third of
  the animation, so a window that *did* animate could still look like a jump. The strip
  is now 320x8, which grabs in a few milliseconds.
* **A background window never animates.** DWM skips the transition for a window that is
  not foreground, so every measurement activates its subject first and reports whether
  that worked. And because an unvalidated "no animation" is worthless, every run
  measures **Notepad** first, positioned exactly like the subject: if Notepad does not
  animate in this run, the run is discarded rather than believed.

Reported per transition: how many frames after the trigger still differed from the
settled picture (`settling`, a duration in frames) and the raw distances, so a ramp and
a step are distinguishable by eye.

Run: python research/probe_transition_speed.py <variant>
     variants: plain | caption | transitions | both
"""

import ctypes
import json
import os
import pathlib
import subprocess
import sys
import threading
import time
from ctypes import wintypes

import webview

from tonyagent.window import win32

AT = (200, 140)
SIZE = (900, 620)
#: A thin strip just below the window's normal bottom edge (140 + 620 = 760) and inside
#: a maximized one, so the growing or shrinking visual passes through it.
REGION = (300, 762, 620, 770)
SIGNATURE = (160, 4)
OUT = pathlib.Path(".tmp-transition-speed.json")
WATCHDOG_SECONDS = 150
SETTLED = 1.0  # mean absolute difference, on 0-255, that counts as "the same picture"

user32 = ctypes.windll.user32
WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

WS_CAPTION = 0x00C00000
DWMWA_TRANSITIONS_FORCEDISABLED = 3

PAGE = """
<html><body style="margin:0;background:#161616;color:#eee;
font-family:Segoe UI,sans-serif;font-size:40px;padding:40px">the app's window</body></html>
"""

VARIANT = (sys.argv[1] if len(sys.argv) > 1 else "plain").lower()
notes: dict = {"variant": VARIANT}


def say(message: str) -> None:
    print(f"[{VARIANT}] {message}", flush=True)


def finish() -> None:
    OUT.write_text(json.dumps(notes, indent=2, default=str), encoding="utf-8")
    os._exit(0)


def signature() -> list:
    from PIL import ImageGrab

    return list(ImageGrab.grab(bbox=REGION, all_screens=True).convert("L").resize(SIGNATURE).getdata())


def distance(one: list, other: list) -> float:
    return sum(abs(a - b) for a, b in zip(one, other)) / len(one)


def activate(hwnd: int) -> bool:
    user32.ShowWindow(wintypes.HWND(hwnd), 9)  # SW_RESTORE
    user32.BringWindowToTop(wintypes.HWND(hwnd))
    user32.SetForegroundWindow(wintypes.HWND(hwnd))
    time.sleep(0.35)
    return int(user32.GetForegroundWindow() or 0) == int(hwnd)


def measure(subject: str, name: str, trigger, settle: float = 0.9) -> dict:
    """Trigger a transition and measure how long the screen kept changing."""
    before = signature()
    started = time.time()
    trigger()
    frames: list[list] = []
    while time.time() - started < 0.9:
        frames.append(signature())
    time.sleep(settle)
    after = signature()

    from_before = [distance(frame, before) for frame in frames]
    from_after = [distance(frame, after) for frame in frames]
    # Frames after the trigger that are still neither side of it: that run of frames
    # *is* the animation, and a jump has none.
    between = [i for i, (a, b) in enumerate(zip(from_before, from_after)) if a > 2 and b > 2]
    settled = next((i for i, value in enumerate(from_after) if value < SETTLED), len(frames))
    result = {
        "grabs": len(frames),
        "in_between": len(between),
        "settling_frames": settled,
        "from_before": [round(v, 1) for v in from_before],
        "from_after": [round(v, 1) for v in from_after],
    }
    notes.setdefault(subject, {})[name] = result
    say(
        f"{subject} {name}: {len(frames)} grabs, {len(between)} in between, "
        f"settling {settled} frames"
    )
    return result


def notepad_window() -> int:
    found = [0]

    def visit(hwnd, _lparam):
        klass = ctypes.create_unicode_buffer(64)
        user32.GetClassNameW(wintypes.HWND(hwnd), klass, 64)
        if klass.value == "Notepad" and not found[0]:
            found[0] = int(hwnd)
        return True

    user32.EnumWindows(WNDENUMPROC(visit), 0)
    return found[0]


def place(hwnd: int) -> None:
    user32.SetWindowPos(wintypes.HWND(hwnd), None, AT[0], AT[1], SIZE[0], SIZE[1], 0x0004 | 0x0010)


def main() -> None:
    threading.Timer(WATCHDOG_SECONDS, lambda: (say("watchdog"), finish())).start()
    notepad = subprocess.Popen(["notepad.exe"])
    window = webview.create_window(
        "transition speed", html=PAGE, width=SIZE[0], height=SIZE[1], min_size=(400, 300),
        resizable=True, frameless=True, easy_drag=False, shadow=True, background_color="#161616",
    )

    def run() -> None:
        try:
            hwnd = 0
            for _ in range(60):
                time.sleep(0.25)
                try:
                    hwnd = win32.root_window(int(window.native.Handle.ToInt64()))
                    break
                except Exception:  # noqa: BLE001
                    continue
            if not hwnd:
                raise RuntimeError("the probe window never came up")
            win32.round_corners(hwnd)
            win32.install_frame(hwnd)
            win32.make_resizable(hwnd)

            # --- the variant, applied ------------------------------------------
            if VARIANT in ("caption", "both"):
                style = user32.GetWindowLongW(wintypes.HWND(hwnd), -16)
                user32.SetWindowLongW(wintypes.HWND(hwnd), -16, style | WS_CAPTION)
                user32.SetWindowPos(
                    wintypes.HWND(hwnd), None, 0, 0, 0, 0,
                    0x0002 | 0x0001 | 0x0004 | 0x0010 | 0x0020,
                )
            if VARIANT in ("transitions", "both"):
                value = ctypes.c_int(0)
                ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    wintypes.HWND(hwnd), DWMWA_TRANSITIONS_FORCEDISABLED,
                    ctypes.byref(value), ctypes.sizeof(value),
                )
            notes["style"] = hex(user32.GetWindowLongW(wintypes.HWND(hwnd), -16) & 0xFFFFFFFF)
            # **Nothing may be drawn.** The caption is in the style so that DWM will
            # animate the window, not so that it will paint one, so the client area
            # must still be the whole window: equal sizes, no inset.
            window_rect = win32.RECT()
            client_rect = win32.RECT()
            user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(window_rect))
            user32.GetClientRect(wintypes.HWND(hwnd), ctypes.byref(client_rect))
            notes["window_size"] = [window_rect.right - window_rect.left, window_rect.bottom - window_rect.top]
            notes["client_size"] = [client_rect.right, client_rect.bottom]
            notes["client_is_the_whole_window"] = notes["window_size"] == notes["client_size"]
            say(f"client {notes['client_size']} vs window {notes['window_size']}: {notes['client_is_the_whole_window']}")

            # --- the control, so a "no animation" result can be trusted ---------
            control = 0
            for _ in range(40):
                time.sleep(0.25)
                control = notepad_window()
                if control:
                    break
            if control:
                place(control)
                notes["notepad_foreground"] = activate(control)
                measure("notepad", "maximize", lambda: user32.ShowWindow(wintypes.HWND(control), 3))
                measure("notepad", "minimize", lambda: user32.ShowWindow(wintypes.HWND(control), 6), 1.2)
                notepad.terminate()
            else:
                notes["notepad"] = "never appeared"

            # --- the subject ----------------------------------------------------
            win32.on_window_thread(window, lambda: place(hwnd))
            time.sleep(0.6)
            notes["foreground"] = activate(hwnd)
            say(f"subject foreground: {notes['foreground']}")
            measure("app", "maximize", window.maximize)
            measure("app", "restore", window.restore)
            measure("app", "minimize", window.minimize, settle=1.2)
            window.restore()
            time.sleep(0.4)
        except Exception as exc:  # noqa: BLE001 - a probe reports
            notes["error"] = repr(exc)
            say(f"error: {exc!r}")
        finally:
            finish()

    threading.Thread(target=run, daemon=True).start()
    webview.start()


if __name__ == "__main__":
    main()
