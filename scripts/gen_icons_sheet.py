"""Render the Phase 8 icon sheet: every registry glyph at every ladder size.

Reads `app/src/icons.tsx` (the weight table and the glyph bodies), writes a
static `sheet.html`, and screenshots it in headless Chrome at DPR 2 into
`design-preview/icons-sheet.png`. The sheet is the evidence Phase 8's weight
choice is argued from: the full matrix on `--bg`/`--raised`/`--chip`, a 200%
column, a 1.0px-vs-1.5px comparison at 12px, and the old solid gear beside
the new stroked one.

Usage:
    python scripts/gen_icons_sheet.py
"""

from __future__ import annotations

import base64
import functools
import http.server
import json
import re
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
SRC = ROOT / "app" / "src"
OUT = ROOT / "design-preview" / "icons-sheet.png"

CHROME_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
]

BG = "#1a1a1a"
RAISED = "#333333"
CHIP = "#3d3d3d"
FG = "#ececec"
MUTE = "#8a8a8a"

# The pre-Phase-8 gear: solid silhouette, the form the registry replaces.
OLD_GEAR = (
    "M19.14 12.94c.04-.3.06-.61.06-.94 0-.32-.02-.64-.07-.94l2.03-1.58c.18-.14.23-.41.12-.61l-1.92-3.32c-.12-.22-.37-.29-.59-.22l-2.39.96c-.5-.38-1.03-.7-1.62-.94l-.36-2.54c-.04-.24-.24-.41-.48-.41h-3.84c-.24 0-.43.17-.47.41l-.36 2.54c-.59.24-1.13.57-1.62.94l-2.39-.96c-.22-.08-.47 0-.59.22L2.74 8.87c-.12.21-.08.47.12.61l2.03 1.58c-.05.3-.09.63-.09.94s.02.64.07.94l-2.03 1.58c-.18.14-.23.41-.12.61l1.92 3.32c.12.22.37.29.59.22l2.39-.96c.5.38 1.03.7 1.62.94l.36 2.54c.05.24.24.41.48.41h3.84c.24 0 .44-.17.47-.41l.36-2.54c.59-.24 1.13-.56 1.62-.94l2.39.96c.22.08.47 0 .59-.22l1.92-3.32c.12-.22.07-.47-.12-.61l-2.01-1.58zM12 15.6c-1.98 0-3.6-1.62-3.6-3.6s1.62-3.6 3.6-3.6 3.6 1.62 3.6 3.6-1.62 3.6-3.6 3.6z"
)


def read_registry() -> tuple[dict[int, float], dict[str, str], set[str]]:
    """Parse the weight table, the glyph bodies and the solid set."""
    text = (SRC / "icons.tsx").read_text()
    table = {
        int(size): float(sw)
        for size, sw in re.findall(r"^\s*(\d+):\s*([\d.]+),?\s*$", text, re.M)
        if int(size) in (12, 14, 16, 20)
    }
    assert len(table) == 4, table
    consts = {}
    for name, body in re.findall(
        r"const (EYE_\w+) = (<path[\s\S]*?/>|<circle[\s\S]*?/>);", text
    ):
        consts[name] = body
    bodies: dict[str, str] = {}
    rec = text[text.index("const BODIES") :]
    rec = rec[: rec.index("\n};") + 1]
    for match in re.finditer(r"^\s{2}(\w+): ", rec, re.M):
        name = match.group(1)
        rest = rec[match.end() :]
        if rest.startswith("("):
            depth, i = 1, 1
            while depth:
                if rest[i] == "(":
                    depth += 1
                elif rest[i] == ")":
                    depth -= 1
                i += 1
            bodies[name] = rest[1 : i - 1].strip()
        else:
            bodies[name] = rest.split("\n")[0].rstrip(",").strip()
    for key, frag in consts.items():
        for name in bodies:
            bodies[name] = bodies[name].replace(f"{{{key}}}", frag)
    bodies = {k: v.replace("<>", "").replace("</>", "") for k, v in bodies.items()}
    solid = set(re.findall(r'new Set\(\[(.*?)\]\)', text, re.S)[0].replace('"', "").replace(",", " ").split())
    return table, bodies, solid


def svg(body: str, size: int, sw: float | None, box: int | None = None) -> str:
    box = box or size
    if sw is None:
        frame = 'fill="currentColor" stroke="none"'
    else:
        frame = f'fill="none" stroke="currentColor" stroke-width="{sw}"'
    return (
        f'<svg width="{box}" height="{box}" viewBox="0 0 24 24" {frame} '
        f'stroke-linecap="round" stroke-linejoin="round">{body}</svg>'
    )


def cell(glyph: str, label: str, bg: str) -> str:
    return f'<div class="cell" style="background:{bg}"><div class="g">{glyph}</div><div class="t">{label}</div></div>'


def build_html(table: dict[int, float], bodies: dict[str, str], solid: set[str]) -> str:
    sizes = [12, 14, 16, 20]
    names = list(bodies)
    rows = []
    for surface, bg in (("--bg", BG), ("--raised", RAISED), ("--chip", CHIP)):
        cells = "".join(
            f'<div class="row"><div class="name">{n}</div>'
            + "".join(
                cell(
                    svg(bodies[n], s, None if n in solid else table[s]),
                    f"{s}px · {'solid' if n in solid else table[s]}",
                    bg,
                )
                for s in sizes
            )
            + "</div>"
            for n in names
        )
        rows.append(f"<h2>{surface} {bg}</h2><div class='grid'>{cells}</div>")
    zoom = "".join(
        f'<div class="row"><div class="name">{n}</div>'
        + "".join(
            cell(
                svg(bodies[n], s, None if n in solid else table[s], box=s * 2),
                f"{s}px at 200%",
                BG,
            )
            for s in sizes
        )
        + "</div>"
        for n in names
    )
    compare = "".join(
        f'<div class="row"><div class="name">{n}</div>'
        + cell(svg(bodies[n], 12, 2.0), "12px · drawn 1.0", BG)
        + cell(svg(bodies[n], 12, 3.0), "12px · drawn 1.5", BG)
        + "</div>"
        for n in ("close", "plus", "search", "folder")
    )
    gear = (
        '<div class="row"><div class="name">gear 16</div>'
        + cell(f'<svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><path d="{OLD_GEAR}" /></svg>', "old solid", BG)
        + cell(svg(bodies["gear"], 16, table[16]), "new stroked", BG)
        + '</div><div class="row"><div class="name">gear 20</div>'
        + cell(f'<svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor"><path d="{OLD_GEAR}" /></svg>', "old solid", BG)
        + cell(svg(bodies["gear"], 20, table[20]), "new stroked", BG)
        + "</div>"
    )
    weights = " · ".join(f"{s}→{table[s]}" for s in sizes)
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>icons sheet</title>
<style>
  body {{ background:{BG}; color:{FG}; font:12px/1.4 "Segoe UI", system-ui, sans-serif; margin:0; padding:24px; }}
  h1 {{ font-size:20px; margin:0 0 4px; }} h2 {{ font-size:13px; color:{MUTE}; margin:28px 0 8px; text-transform:uppercase; letter-spacing:.08em; }}
  p {{ color:{MUTE}; max-width:900px; }} code {{ color:{FG}; }}
  .row {{ display:flex; gap:8px; align-items:stretch; margin-bottom:8px; }}
  .name {{ width:130px; flex:none; align-self:center; color:{MUTE}; font-size:11px; }}
  .cell {{ border-radius:8px; padding:10px 6px 6px; text-align:center; min-width:96px; color:{FG}; }}
  .g {{ height:44px; display:flex; align-items:center; justify-content:center; }}
  .t {{ font-size:10px; color:{MUTE}; margin-top:6px; }}
</style></head><body>
<h1>Icon sheet — drawn 1.5px at every size</h1>
<p>Frame 24 units, live area 21, 1.5 units padding. Weight table (frame stroke per size): <code>{weights}</code>.
Solid marks (<code>stop</code>, <code>menu</code>) carry no stroke. 200% column doubles the box with the same frame stroke.</p>
<h2>weight comparison at 12px</h2><div class="grid">{compare}</div>
<h2>gear: old solid vs new stroked</h2><div class="grid">{gear}</div>
<h2>matrix at 100% and 200% on --bg</h2><div class="grid">{zoom}</div>
{"".join(rows)}
</body></html>"""


def free_port() -> int:
    import socket as s

    with s.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def main() -> int:
    table, bodies, solid = read_registry()
    print(f"glyphs: {len(bodies)} solid: {sorted(solid)}")
    with tempfile.TemporaryDirectory(prefix="tonyagent-icons-") as tmp:
        Path(tmp, "sheet.html").write_text(build_html(table, bodies, solid))
        handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=tmp)

        class Quiet(http.server.ThreadingHTTPServer):
            def handle_error(self, *args):  # noqa: ANN002, ANN202
                pass

        port = free_port()
        httpd = Quiet(("127.0.0.1", port), handler)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()

        chrome = next((p for p in CHROME_CANDIDATES if Path(p).exists()), "")
        if not chrome:
            raise SystemExit("no Chrome or Edge found")
        profile = Path(tempfile.mkdtemp(prefix="tonyagent-icons-cdp-"))
        debug_port = free_port()
        browser = subprocess.Popen(
            [chrome, "--headless=new", f"--remote-debugging-port={debug_port}",
             f"--user-data-dir={profile}", "--no-first-run", "--no-default-browser-check",
             "--hide-scrollbars", "--force-device-scale-factor=1", "about:blank"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        try:
            deadline = time.time() + 25
            page = None
            while time.time() < deadline:
                try:
                    targets = json.load(urllib.request.urlopen(f"http://127.0.0.1:{debug_port}/json/list"))
                    pages = [t for t in targets if t.get("type") == "page"]
                    if pages:
                        page = pages[0]
                        break
                except OSError:
                    pass
                time.sleep(0.2)
            if not page:
                raise SystemExit("headless Chrome never offered a page")
            sock = _ws_connect(page["webSocketDebuggerUrl"])
            rid = 0

            def call(method, params=None, timeout=60.0):
                nonlocal rid
                rid += 1
                _send(sock, {"id": rid, "method": method, "params": params or {}})
                stop = time.time() + timeout
                while time.time() < stop:
                    message = _recv(sock, timeout=max(1.0, stop - time.time()))
                    if message is None:
                        break
                    try:
                        parsed = json.loads(message)
                    except ValueError:
                        continue
                    if parsed.get("id") != rid:
                        continue
                    if "error" in parsed:
                        raise RuntimeError(f"{method}: {parsed['error']}")
                    return parsed.get("result", {})
                raise RuntimeError(f"{method}: no reply")

            call("Page.navigate", {"url": f"http://127.0.0.1:{port}/sheet.html"})
            time.sleep(1.0)
            height = call(
                "Runtime.evaluate",
                {"expression": "document.body.scrollHeight", "returnByValue": True},
            )["result"]["value"]
            width = 1200
            call("Emulation.setDeviceMetricsOverride", {
                "width": width, "height": int(height) + 40,
                "deviceScaleFactor": 2, "mobile": False,
            })
            time.sleep(0.5)
            data = call("Page.captureScreenshot", {"format": "png"})["data"]
            OUT.parent.mkdir(parents=True, exist_ok=True)
            OUT.write_bytes(base64.b64decode(data))
            print(f"wrote {OUT} ({width}x{int(height) + 40} @2x)")
        finally:
            browser.terminate()
            try:
                browser.wait(timeout=10)
            except subprocess.TimeoutExpired:
                browser.kill()
            httpd.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
