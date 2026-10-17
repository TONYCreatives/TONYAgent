"""Capture the app's window without disturbing whoever is using the machine.

Why this exists, and why the two obvious answers are wrong:

  * `PrintWindow` on a WebView2 window paints only the regions the app has
    recently invalidated, so it returns bands of black that read as a broken
    layout. `probe_webview.py` already says so.
  * Copying the screen needs the window on top of everything else. That is fine
    on an idle machine and wrong on a working one: the window has to be raised,
    focused and left in front of whatever the person was actually doing, and the
    capture is of the desktop rather than of the page.

`Page.captureScreenshot` asks the compositor for the frame it has already
rendered. Nothing has to be raised, focused, or even on screen, so this starts
an instance with the debug port open, parks its window out of the way, and
gives the keyboard back to whoever had it.

**The profile, and why it is not optional.** WebView2 keeps one browser process
per user-data folder, and a second instance asking for *different* browser
arguments cannot join the first: it fails with `0x8007139F`, "the group or
resource is not in the correct state", and the port never opens. That is what
happens when the app is already running from the shortcut and this script asks
for a debugging port. `WEBVIEW2_USER_DATA_FOLDER` gives the capture instance a
profile of its own, so it gets its own browser process and can run beside a
normal instance instead of being refused by it.

Usage:

    python scripts/capture_app.py                     # home screen, one shot
    python scripts/capture_app.py --widths 760,900,1280
    python scripts/capture_app.py --eval "document.title"
    python scripts/capture_app.py --keep              # leave the instance up
    python scripts/capture_app.py --stop              # shut a kept one down

With `--keep` the first run pays a brief flash while the window appears and is
parked. Every run after that attaches to the instance already listening, so it
is silent: no window, no focus change, no pixels moved.

Screenshots land in `.shots/` (gitignored) as `<tag>-<width>.png`.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

# `probe_webview` owns the minimal WebSocket client -- the stdlib has none, and
# this repository's point is that the protocol is testable without extra
# tooling. Imported rather than copied so there is one client, not two.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import probe_webview as cdp  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SHOTS = ROOT / ".shots"
#: Where a kept instance's process id is written, so `--stop` can end it.
#: `Browser.close` over CDP shuts the WebView2 browser down and leaves the
#: Python host running: the window is parked off-screen, so there is no taskbar
#: button to close it with and nothing to find it by. The pid is the handle.
PID_FILE = SHOTS / ".capture-app.pid"
DEFAULT_PORT = 9333

#: Far enough off the left edge that no arrangement of monitors reaches it. The
#: window keeps rendering there -- it is off-screen, not minimised, and a
#: minimised WebView2 stops compositing, which would give a black frame.
PARK_X = -20000

_user32 = ctypes.windll.user32  # type: ignore[attr-defined]

_next_id = 0


# --- CDP --------------------------------------------------------------------


def call(sock, method: str, params: dict | None = None, timeout: float = 25.0) -> dict:
    """One CDP round trip, skipping events and other replies."""
    global _next_id  # noqa: PLW0603 - a request id is a counter, not state
    _next_id += 1
    mid = _next_id
    cdp._send(sock, {"id": mid, "method": method, "params": params or {}})
    deadline = time.time() + timeout
    while time.time() < deadline:
        message = cdp._recv(sock, timeout=max(0.5, deadline - time.time()))
        if message is None:
            continue
        try:
            parsed = json.loads(message)
        except ValueError:
            continue
        if parsed.get("id") != mid:
            continue
        if "error" in parsed:
            raise RuntimeError(f"{method}: {parsed['error']}")
        return parsed.get("result", {})
    raise TimeoutError(f"{method} did not answer in {timeout}s")


def page_target(port: int) -> dict | None:
    try:
        with urllib.request.urlopen(f"http://localhost:{port}/json/list", timeout=2) as handle:
            targets = json.load(handle)
    except (urllib.error.URLError, TimeoutError, ValueError):
        return None
    pages = [t for t in targets if t.get("type") == "page"]
    return pages[0] if pages else None


# --- the window -------------------------------------------------------------


def hwnd_for(pid: int) -> int:
    """The first visible titled window belonging to `pid`, or 0."""
    found: list[int] = []
    proc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    def visit(hwnd, _):
        owner = ctypes.c_ulong()
        _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == pid and _user32.IsWindowVisible(hwnd):
            if _user32.GetWindowTextLengthW(hwnd):
                found.append(hwnd)
        return True

    _user32.EnumWindows(proc(visit), 0)
    return found[0] if found else 0


def park(hwnd: int) -> None:
    """Move it off-screen without activating it.

    SWP_NOACTIVATE is the whole point: `SetWindowPos` will otherwise bring the
    window forward as a side effect of moving it, which is the interruption this
    script exists to avoid.
    """
    SWP_NOSIZE, SWP_NOACTIVATE, SWP_NOZORDER = 0x0001, 0x0010, 0x0004
    _user32.SetWindowPos(hwnd, 0, PARK_X, 0, 0, 0, SWP_NOSIZE | SWP_NOACTIVATE | SWP_NOZORDER)


# --- the instance -----------------------------------------------------------


def launch(port: int, profile: Path) -> subprocess.Popen:
    env = dict(os.environ)
    env["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = f"--remote-debugging-port={port}"
    # Its own browser process, so this instance can carry a debugging port while
    # a normal one is already running. See the module docstring.
    env["WEBVIEW2_USER_DATA_FOLDER"] = str(profile)
    env["PYTHONPATH"] = str(ROOT / "src")
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.Popen(
        [sys.executable, "-m", "tonyagent.window"],
        cwd=str(ROOT),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def wait_for_page(port: int, timeout: float = 45.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        target = page_target(port)
        if target:
            return target
        time.sleep(0.4)
    raise TimeoutError(f"no page on port {port} after {timeout}s")


def give_the_keyboard_back(previous: int) -> None:
    """Restore whatever was in front before the app appeared.

    The app itself does this for the desktop pet -- `foreground_window` and
    `give_foreground_back` in `tonyagent/window/win32.py` -- for the same
    reason: asking for attention must not take the keyboard. This is the same
    move, from outside.
    """
    if not previous:
        return
    try:
        _user32.SetForegroundWindow(ctypes.c_void_p(previous))
    except Exception:  # noqa: BLE001 - focus is best-effort, never fatal
        pass


# --- capture ----------------------------------------------------------------


def shoot(sock, path: Path) -> None:
    result = call(sock, "Page.captureScreenshot", {"format": "png"})
    data = result.get("data")
    if not data:
        raise RuntimeError("no image data in the reply")
    import base64

    path.write_bytes(base64.b64decode(data))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--tag", default="home", help="name the files after this")
    parser.add_argument("--out", default=str(SHOTS))
    parser.add_argument("--widths", default="", help="comma-separated CSS widths")
    parser.add_argument("--height", type=int, default=900)
    parser.add_argument("--eval", dest="expression", default="", help="JS to run, printed as JSON")
    parser.add_argument("--keep", action="store_true", help="leave the instance running")
    parser.add_argument("--stop", action="store_true", help="shut down a kept instance")
    parser.add_argument(
        "--profile",
        default=str(Path(os.environ.get("TEMP", ".")) / "tonyagent-capture-profile"),
        help="WebView2 user-data folder for the capture instance",
    )
    args = parser.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    running = page_target(args.port) is not None
    proc: subprocess.Popen | None = None
    previous = 0

    if args.stop:
        # The pid first: it is the only handle on a process whose window is
        # parked where nobody can click it.
        stopped = False
        if PID_FILE.exists():
            try:
                pid = int(PID_FILE.read_text().strip())
            except ValueError:
                pid = 0
            if pid:
                try:
                    subprocess.run(
                        ["taskkill", "/PID", str(pid), "/F"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        check=False,
                    )
                    stopped = True
                except OSError:
                    stopped = False
            PID_FILE.unlink(missing_ok=True)
        if stopped:
            print("stopped the capture instance")
            return 0
        if not running:
            print("nothing listening; no instance to stop")
            return 0
        target = page_target(args.port)
        sock = cdp._ws_connect(target["webSocketDebuggerUrl"])
        try:
            call(sock, "Browser.close", timeout=5)
        except Exception:  # noqa: BLE001 - closing is best-effort
            pass
        finally:
            sock.close()
        print("asked the instance to close (no pid file; check for a leftover process)")
        return 0

    if not running:
        previous = _user32.GetForegroundWindow()
        proc = launch(args.port, Path(args.profile))
        PID_FILE.parent.mkdir(parents=True, exist_ok=True)
        PID_FILE.write_text(str(proc.pid), encoding="utf-8")
        print(f"started pid {proc.pid}, waiting for the page")
        try:
            target = wait_for_page(args.port)
        except TimeoutError as exc:
            proc.terminate()
            print(f"failed: {exc}", file=sys.stderr)
            return 1
        # Park it as soon as it exists, then hand the keyboard back. Both are
        # best-effort: a capture that works is worth more than a tidy desktop.
        time.sleep(0.8)
        hwnd = hwnd_for(proc.pid)
        if hwnd:
            park(hwnd)
        give_the_keyboard_back(previous)
        print(f"parked at x={PARK_X} and returned focus")
    else:
        target = page_target(args.port)
        print(f"attaching to the instance already on port {args.port}")

    sock = cdp._ws_connect(target["webSocketDebuggerUrl"])
    widths = [int(w) for w in args.widths.split(",") if w.strip()] or [0]
    try:
        for width in widths:
            if width:
                # Emulation, not a window resize: the page is told its viewport
                # changed, so the app's own media queries fire without a pixel of
                # the real window moving.
                call(
                    sock,
                    "Emulation.setDeviceMetricsOverride",
                    {
                        "width": width,
                        "height": args.height,
                        "deviceScaleFactor": 1,
                        "mobile": False,
                    },
                )
                time.sleep(0.5)

            if args.expression:
                result = call(
                    sock,
                    "Runtime.evaluate",
                    {
                        "expression": args.expression,
                        "returnByValue": True,
                        "awaitPromise": True,
                    },
                )
                if "exceptionDetails" in result:
                    print(json.dumps(result["exceptionDetails"])[:2000], file=sys.stderr)
                    return 1
                if len(widths) > 1:
                    print(f"--- width {width} ---")
                print(json.dumps(result.get("result", {}).get("value"), indent=2)[:8000])
                continue

            name = f"{args.tag}-{width}.png" if width else f"{args.tag}.png"
            path = out / name
            shoot(sock, path)
            print(f"wrote {path.relative_to(ROOT)}")

        if widths != [0]:
            call(sock, "Emulation.clearDeviceMetricsOverride")
    finally:
        sock.close()

    if proc is not None and not args.keep:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        PID_FILE.unlink(missing_ok=True)
        print("instance stopped")
    elif proc is not None:
        print(f"left running on port {args.port}; stop it with --stop")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
