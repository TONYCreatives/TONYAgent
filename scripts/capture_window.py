"""Serve the built window on loopback and drive it in headless Chrome over CDP.

The window renders hostless by design -- `bridge.ts` resolves to null without a
pywebview host, so `CoreBackend` never starts and the shell, the launchpad and
the run panel draw themselves with no core behind them. That is what makes this
script possible: it is the same `app/dist` the packaged window serves, in the
same engine (Chromium), at a viewport this script chooses.

**Why not `scripts/probe_webview.py`.** That one attaches to a *running* WebView2
window, which needs the app open, a native window on screen, and a person to
close it. This one is for the measurements the phases are accepted against: five
widths, the same build, no window. It reuses that script's WebSocket client
rather than growing a second one.

Usage:
    python scripts/capture_window.py --out design-preview/baseline
    python scripts/capture_window.py --measure
    python scripts/capture_window.py -e "document.title"

The page is served from a temporary HTTP server on 127.0.0.1 with a random port;
nothing is bound to a public interface.
"""

from __future__ import annotations

import argparse
import base64
import functools
import http.server
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from probe_webview import _recv, _send, _ws_connect  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "app" / "dist"

#: The five widths Phase 0 asked for, as (width, height, label).
SHOTS = [
    (1600, 1000, "1600x1000"),
    (1400, 900, "1400x900"),
    (1100, 800, "1100x800"),
    (900, 700, "900x700"),
    (560, 700, "560x700"),
]

CHROME_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
]


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def serve(directory: Path, port: int) -> http.server.ThreadingHTTPServer:
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(directory))

    class Quiet(http.server.ThreadingHTTPServer):
        def handle_error(self, request, client_address):  # noqa: ANN001
            pass

    httpd = Quiet(("127.0.0.1", port), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return httpd


def launch(profile: Path, port: int) -> subprocess.Popen:
    chrome = next((p for p in CHROME_CANDIDATES if Path(p).exists()), "")
    if not chrome:
        raise SystemExit("no Chrome or Edge found")
    return subprocess.Popen(
        [
            chrome,
            "--headless=new",
            f"--remote-debugging-port={port}",
            f"--user-data-dir={profile}",
            "--no-first-run",
            "--no-default-browser-check",
            "--hide-scrollbars",
            "--force-device-scale-factor=1",
            "about:blank",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def wait_for_page(port: int, timeout: float = 25.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            targets = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list"))
            pages = [t for t in targets if t.get("type") == "page"]
            if pages:
                return pages[0]
        except OSError:
            pass
        time.sleep(0.2)
    raise SystemExit("headless Chrome never offered a page")


class Session:
    """One CDP connection, with ids counted so replies can be matched."""

    def __init__(self, ws_url: str) -> None:
        self.sock = _ws_connect(ws_url)
        self.next_id = 0

    def call(self, method: str, params: dict | None = None, timeout: float = 30.0):
        self.next_id += 1
        wanted = self.next_id
        _send(self.sock, {"id": wanted, "method": method, "params": params or {}})
        deadline = time.time() + timeout
        while time.time() < deadline:
            message = _recv(self.sock, timeout=max(1.0, deadline - time.time()))
            if message is None:
                break
            try:
                parsed = json.loads(message)
            except ValueError:
                continue
            if parsed.get("id") != wanted:
                continue
            if "error" in parsed:
                raise RuntimeError(f"{method}: {parsed['error']}")
            return parsed.get("result", {})
        raise RuntimeError(f"{method}: no reply")

    def eval(self, expression: str):
        result = self.call(
            "Runtime.evaluate",
            {"expression": expression, "returnByValue": True, "awaitPromise": True},
        )
        if "exceptionDetails" in result:
            raise RuntimeError(json.dumps(result["exceptionDetails"])[:800])
        return result.get("result", {}).get("value")

    def size(self, width: int, height: int) -> None:
        self.call(
            "Emulation.setDeviceMetricsOverride",
            {
                "width": width,
                "height": height,
                "deviceScaleFactor": 1,
                "mobile": False,
            },
        )

    def shot(self, path: Path) -> None:
        data = self.call("Page.captureScreenshot", {"format": "png"})["data"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(base64.b64decode(data))


#: What the window is asked after every resize.
#:
#: Read from the live page rather than inferred from the stylesheet: the grid
#: track a browser *computed* is the number the phase gates are written in.
MEASURE = r"""
(() => {
  const app = document.querySelector('.app');
  const box = (sel) => {
    const el = document.querySelector(sel);
    if (!el) return null;
    const r = el.getBoundingClientRect();
    return { x: Math.round(r.x), w: Math.round(r.width), y: Math.round(r.y), h: Math.round(r.height) };
  };
  const centre = document.querySelector('.main');
  const cr = centre ? centre.getBoundingClientRect() : null;
  return {
    width: window.innerWidth,
    height: window.innerHeight,
    columns: app ? getComputedStyle(app).gridTemplateColumns : '',
    nav: box('.rail'),
    context: box('.contextdock'),
    centre: cr ? Math.round(cr.width) : null,
    composer: box('.composer-inner'),
    transcript: box('.transcript-inner'),
    statusbar: box('.statusbar'),
    chatlist: box('.chatlist'),
    listRows: box('.chatlist-rows'),
    project: box('.chatlist-project'),
    skills: box('.chatlist-skills'),
    foot: box('.chatlist-foot'),
    tokens: box('.statusbar-tokens'),
  };
})()
"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="", help="directory to write the five captures into")
    parser.add_argument("--measure", action="store_true", help="print the layout at five widths")
    parser.add_argument("--width", type=int, default=0)
    parser.add_argument("--height", type=int, default=0)
    parser.add_argument("--tall", action="store_true", help="also measure a 700px-tall window")
    parser.add_argument(
        "--preview",
        action="store_true",
        help="inject scripts/preview_host.js: a fake core that answers boot and replays a turn",
    )
    parser.add_argument("--send", action="store_true", help="with --preview, press Send first")
    parser.add_argument("-e", "--eval", default="", help="evaluate one expression and print it")
    args = parser.parse_args()

    if not DIST.exists():
        raise SystemExit(f"{DIST} does not exist -- run `cd app && npm run build` first")

    http_port = free_port()
    server = serve(DIST, http_port)
    profile = Path(tempfile.mkdtemp(prefix="tonyagent-cdp-"))
    debug_port = free_port()
    browser = launch(profile, debug_port)
    try:
        page = wait_for_page(debug_port)
        session = Session(page["webSocketDebuggerUrl"])
        session.call("Page.enable")
        session.call("Runtime.enable")
        if args.preview:
            source = (ROOT / "scripts" / "preview_host.js").read_text(encoding="utf-8")
            session.call(
                "Page.addScriptToEvaluateOnNewDocument",
                {"source": source},
            )
        session.size(args.width or 1400, args.height or 900)
        session.call("Page.navigate", {"url": f"http://127.0.0.1:{http_port}/index.html"})
        # The shell's boot is a handful of promise chains and one font load; a
        # fixed wait is what makes the captures deterministic.
        time.sleep(2.0)

        if args.send:
            # Press Send with the composer already holding text, which is the
            # same path a person takes: the fake core replays its turn on
            # `send`, so this is what fills the transcript and the run panel.
            session.eval(
                """
                (() => {
                  const field = document.querySelector('.composer textarea');
                  if (!field) return 'no field';
                  const setter = Object.getOwnPropertyDescriptor(
                    window.HTMLTextAreaElement.prototype, 'value').set;
                  setter.call(field, 'Refactor the provider registry so chat-only is a kind, not a flag.');
                  field.dispatchEvent(new Event('input', { bubbles: true }));
                  return 'typed';
                })()
                """
            )
            time.sleep(0.2)
            session.eval(
                """
                (() => {
                  const send = document.querySelector('.composer .send-btn, .composer button[type=submit]');
                  if (!send) return 'no button';
                  send.click();
                  return 'sent';
                })()
                """
            )
            time.sleep(2.2)

        if args.eval:
            print(json.dumps(session.eval(args.eval), indent=2))
            return 0

        shots = [(args.width, args.height, f"{args.width}x{args.height}")] if args.width else SHOTS
        rows = []
        for width, height, label in shots:
            session.size(width, height)
            time.sleep(0.45)
            if args.out:
                session.shot(Path(args.out) / f"{label}.png")
            rows.append(session.eval(MEASURE))

        if args.measure or args.out:
            for row in rows:
                print(json.dumps(row))
        if args.tall:
            session.size(1400, 700)
            time.sleep(0.45)
            print(json.dumps(session.eval(MEASURE)))
        return 0
    finally:
        browser.terminate()
        try:
            browser.wait(timeout=10)
        except subprocess.TimeoutExpired:
            browser.kill()
        server.shutdown()
        shutil.rmtree(profile, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
