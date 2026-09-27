"""Evaluate JavaScript inside the running TONYAgent webview over CDP.

The app is launched with WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS pointing at a
remote debugging port. Screenshot capture of a WebView2 window is unreliable
(bands of unpainted black), so reading the live DOM is the dependable way to
check what the UI is actually doing.

Usage:
    python scripts/probe_webview.py <file-with-js-expression>
    python scripts/probe_webview.py -e "document.title"
    python scripts/probe_webview.py --screenshot out.png
"""

from __future__ import annotations

import base64
import json
import os
import socket
import struct
import sys
import urllib.request

PORT = 9333


def _ws_connect(url: str) -> socket.socket:
    """Minimal WebSocket client. The stdlib has no one, and this avoids adding a
    dependency to a repo whose whole point is that the protocol is testable
    without extra tooling."""
    assert url.startswith("ws://"), url
    hostport, path = url[len("ws://") :].split("/", 1)
    host, port = hostport.split(":")
    sock = socket.create_connection((host, int(port)), timeout=10)
    key = base64.b64encode(os.urandom(16)).decode()
    sock.sendall(
        (
            f"GET /{path} HTTP/1.1\r\nHost: {hostport}\r\n"
            f"Upgrade: websocket\r\nConnection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n"
        ).encode()
    )
    buf = b""
    while b"\r\n\r\n" not in buf:
        chunk = sock.recv(4096)
        if not chunk:
            raise RuntimeError("websocket handshake closed early")
        buf += chunk
    return sock


def _send(sock: socket.socket, payload: dict) -> None:
    data = json.dumps(payload).encode()
    header = bytearray([0x81])
    mask = os.urandom(4)
    size = len(data)
    if size < 126:
        header.append(0x80 | size)
    elif size < 65536:
        header.append(0x80 | 126)
        header += struct.pack(">H", size)
    else:
        header.append(0x80 | 127)
        header += struct.pack(">Q", size)
    header += mask
    header += bytes(b ^ mask[i % 4] for i, b in enumerate(data))
    sock.sendall(bytes(header))


def _recv(sock: socket.socket, timeout: float = 25.0):
    sock.settimeout(timeout)
    try:
        _, second = sock.recv(2)
    except OSError:
        return None
    length = second & 0x7F
    if length == 126:
        length = struct.unpack(">H", sock.recv(2))[0]
    elif length == 127:
        length = struct.unpack(">Q", sock.recv(8))[0]
    data = b""
    while len(data) < length:
        data += sock.recv(length - len(data))
    return data.decode("utf-8", "replace")


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__, file=sys.stderr)
        return 2

    want_screenshot = sys.argv[1] == "--screenshot"
    if want_screenshot:
        # Screenshot mode takes no JS expression; the target page is found below.
        expression = ""
    elif sys.argv[1] == "-e":
        expression = sys.argv[2] if len(sys.argv) > 2 else ""
    else:
        expression = open(sys.argv[1], encoding="utf-8").read()

    targets = json.load(urllib.request.urlopen(f"http://localhost:{PORT}/json/list"))
    pages = [t for t in targets if t.get("type") == "page"]
    if not pages:
        print("no webview page found; is the app running with the debug port?", file=sys.stderr)
        return 1

    sock = _ws_connect(pages[0]["webSocketDebuggerUrl"])
    try:
        if want_screenshot:
            return _screenshot(sock, sys.argv[2] if len(sys.argv) > 2 else "webview.png")
        _send(
            sock,
            {
                "id": 1,
                "method": "Runtime.evaluate",
                "params": {
                    "expression": expression,
                    "returnByValue": True,
                    "awaitPromise": True,
                },
            },
        )
        for _ in range(40):
            message = _recv(sock)
            if message is None:
                print("timed out waiting for the expression", file=sys.stderr)
                return 1
            try:
                parsed = json.loads(message)
            except ValueError:
                continue
            if parsed.get("id") != 1:
                continue
            result = parsed.get("result", {})
            if "exceptionDetails" in result:
                print("EXCEPTION:", json.dumps(result["exceptionDetails"])[:2000], file=sys.stderr)
                return 1
            print(json.dumps(result.get("result", {}).get("value"), indent=2)[:6000])
            return 0
    finally:
        sock.close()
    return 1


def _screenshot(sock: socket.socket, path: str) -> int:
    """Capture via the compositor rather than PrintWindow.

    Win32 PrintWindow on a WebView2 window only paints regions the app has
    recently invalidated, so it returns large black bands and looks like a
    broken layout. Page.captureScreenshot asks the compositor for the real
    frame, which is what a user sees.
    """
    _send(sock, {"id": 1, "method": "Page.captureScreenshot", "params": {"format": "png"}})
    for _ in range(40):
        message = _recv(sock)
        if message is None:
            print("timed out waiting for the screenshot", file=sys.stderr)
            return 1
        try:
            parsed = json.loads(message)
        except ValueError:
            continue
        if parsed.get("id") != 1:
            continue
        import base64 as _b64

        data = parsed.get("result", {}).get("data")
        if not data:
            print("no image data in the response", file=sys.stderr)
            return 1
        with open(path, "wb") as handle:
            handle.write(_b64.b64decode(data))
        print(f"wrote {path}")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
