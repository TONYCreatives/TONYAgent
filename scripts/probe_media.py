"""Drive the webview with an emulated prefers-reduced-motion, then measure.

`probe_webview.py` only sends `Runtime.evaluate`, and emulated media is a
separate CDP domain whose setting lives on the connection that set it -- so a
second probe run would evaluate against a page whose media features had been
dropped. Both halves have to happen on one socket, which is what this does.

Usage:
    python scripts/probe_media.py <file-with-js-expression>
    python scripts/probe_media.py --normal <file-with-js-expression>

`--normal` runs the same expression with the feature explicitly OFF, which is
the control: the interesting reading is the difference between the two.
"""

from __future__ import annotations

import json
import sys

from probe_webview import PORT, _recv, _send, _ws_connect  # noqa: E402

import urllib.request  # noqa: E402


def _target() -> str:
    targets = json.load(urllib.request.urlopen(f"http://localhost:{PORT}/json/list"))
    pages = [t for t in targets if t.get("type") == "page"]
    if not pages:
        raise SystemExit("no webview page found; is the app running with the debug port?")
    return pages[0]["webSocketDebuggerUrl"]


def _roundtrip(sock, message_id: int, method: str, params: dict) -> dict:
    """Send one command and return its reply, ignoring interleaved events."""
    _send(sock, {"id": message_id, "method": method, "params": params})
    for _ in range(40):
        raw = _recv(sock)
        if raw is None:
            raise SystemExit(f"timed out waiting for {method}")
        try:
            parsed = json.loads(raw)
        except ValueError:
            continue
        if parsed.get("id") == message_id:
            return parsed
    raise SystemExit(f"no reply to {method}")


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__, file=sys.stderr)
        return 2

    if sys.argv[1] == "--normal":
        reduce_motion = False
        expression_file = sys.argv[2]
    else:
        reduce_motion = True
        expression_file = sys.argv[1]

    expression = open(expression_file, encoding="utf-8").read()

    sock = _ws_connect(_target())
    try:
        # Both features are set explicitly. Leaving `media` unset keeps the
        # document type alone, and the second feature is pinned so a host that
        # reports one preference cannot make this run look like the other.
        reply = _roundtrip(
            sock,
            1,
            "Emulation.setEmulatedMedia",
            {
                "media": "",
                "features": [
                    {"name": "prefers-reduced-motion", "value": "reduce" if reduce_motion else "no-preference"},
                ],
            },
        )
        if "error" in reply:
            print("setEmulatedMedia rejected:", json.dumps(reply["error"]), file=sys.stderr)
            return 1

        evaluated = _roundtrip(
            sock,
            2,
            "Runtime.evaluate",
            {"expression": expression, "returnByValue": True, "awaitPromise": True},
        )
        result = evaluated.get("result", {})
        if "exceptionDetails" in result:
            print("EXCEPTION:", json.dumps(result["exceptionDetails"])[:2000], file=sys.stderr)
            return 1
        print(json.dumps(result.get("result", {}).get("value"), indent=2)[:6000])
        return 0
    finally:
        sock.close()


if __name__ == "__main__":
    raise SystemExit(main())
