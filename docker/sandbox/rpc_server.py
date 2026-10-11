#!/usr/bin/env python3
"""RPC server for TONYAgent sandbox."""

import asyncio
import json
import os
import sys
import traceback
from pathlib import Path
from typing import Any

# The workspace root.
#
# This server is not container-only: the host also runs it as a plain
# subprocess (see tonyagent.sandbox.local_backend) so the browser and
# read-only file tools work with no Docker daemon. The container passes
# /workspace, the host passes the real project folder. Hardcoding the
# Linux path is what made the Docker dependency unavoidable.
WORKSPACE = Path(os.environ.get("TONYAGENT_WORKSPACE", "/workspace")).resolve()

# The workspace used to be prepended to this process's ``sys.path``. In the
# container that was pointless; on the host -- where this module is imported
# into the *agent's own process*, not a container subprocess -- it was an
# import-hijack primitive: any lazily imported name (``json.py`` at the root
# of a checked-out repo, a planted ``playwright.py`` for the browser tools'
# own import) shadows the real module and runs in the agent's process, with
# the user's full privileges. Scripts that need the project on their path can
# put it there themselves -- ``python script.py`` and ``python -m`` already
# add the script's directory, and ``exec_command`` runs in a fresh shell
# whose ``cwd`` is the workspace.
#
# Do not reintroduce this. The test in tests/unit/test_sandbox_rpc.py that
# imports this module through the local backend and asserts the workspace is
# absent from ``sys.path`` is what keeps it out.


async def exec_command(command: str, cwd: str = "", timeout: int = 30) -> dict:
    """Execute a shell command."""
    cwd = cwd or str(WORKSPACE)
    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            limit=1024 * 1024,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return {
            "stdout": stdout.decode("utf-8", errors="replace"),
            "stderr": stderr.decode("utf-8", errors="replace"),
            "returncode": proc.returncode,
        }
    except asyncio.TimeoutError:
        # wait_for only cancels communicate(); without an explicit kill the
        # child keeps running orphaned inside the container.
        try:
            proc.kill()
            await proc.wait()
        except ProcessLookupError:
            pass
        return {"stdout": "", "stderr": f"Timeout after {timeout}s", "returncode": -1}
    except Exception as e:
        return {"stdout": "", "stderr": str(e), "returncode": -1}


async def execute_js(script: str, timeout: int = 10) -> dict:
    """Execute JavaScript using Node.js."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "node", "-e", script,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return {
            "success": proc.returncode == 0,
            "data": stdout.decode("utf-8", errors="replace"),
            "error": stderr.decode("utf-8", errors="replace") if proc.returncode != 0 else None,
        }
    except asyncio.TimeoutError:
        try:
            proc.kill()
            await proc.wait()
        except ProcessLookupError:
            pass
        return {"success": False, "error": f"Timeout after {timeout}s"}
    except Exception as e:
        return {"success": False, "error": str(e)}


# Browser automation with Playwright
_browser = None
_page = None
#: The driver handle must be kept, not left as a local in the function that
#: starts it. Playwright runs a separate driver process; dropping the last
#: reference to the handle is what stops it from ever being shut down, so the
#: container leaked one per session before this was a module global.
_playwright = None

#: Launch channels, tried in order. The system browser comes first because it
#: is the only option that needs no ~150 MB download: Edge ships with Windows
#: and Chrome is near-universal. The bundled Chromium is the last resort, and
#: in the container it is the only one that exists.
_BROWSER_CHANNELS = ("msedge", "chrome", None)


async def _ensure_browser():
    """Launch a browser once and return it, or raise a readable error."""
    global _browser, _page, _playwright
    from playwright.async_api import async_playwright

    if _browser is None:
        _playwright = await async_playwright().start()
        errors = []
        for channel in _BROWSER_CHANNELS:
            try:
                _browser = await _playwright.chromium.launch(headless=True, channel=channel)
                break
            except Exception as exc:  # try the next channel
                errors.append(f"{channel or 'bundled chromium'}: {exc}")
        if _browser is None:
            raise RuntimeError(
                "No usable browser. Tried " + "; ".join(errors)
                + ". Install Microsoft Edge or Chrome, or run "
                "`playwright install chromium`."
            )
        _page = await _browser.new_page()
    return _browser, _page


async def close_browser() -> dict:
    """Release the browser and its driver. Safe to call more than once."""
    global _browser, _page, _playwright
    try:
        if _browser is not None:
            await _browser.close()
    except Exception:
        pass
    try:
        if _playwright is not None:
            await _playwright.stop()
    except Exception:
        pass
    _browser = _page = _playwright = None
    return {"success": True}


async def browser_navigate(url: str) -> dict:
    try:
        # _ensure_browser assigns the module-level _page the other handlers read.
        _, page = await _ensure_browser()
        await page.goto(url, wait_until="networkidle")
        return {"success": True, "data": {"url": page.url, "title": await page.title()}}
    except Exception as e:
        return {"success": False, "error": str(e)}


async def browser_click(selector: str) -> dict:
    global _page
    try:
        await _page.click(selector)
        return {"success": True, "data": {"selector": selector}}
    except Exception as e:
        return {"success": False, "error": str(e)}


async def browser_type(selector: str, text: str) -> dict:
    global _page
    try:
        await _page.fill(selector, text)
        return {"success": True, "data": {"selector": selector, "text": text}}
    except Exception as e:
        return {"success": False, "error": str(e)}


async def browser_eval(script: str) -> dict:
    global _page
    try:
        result = await _page.evaluate(script)
        return {"success": True, "data": result}
    except Exception as e:
        return {"success": False, "error": str(e)}


async def browser_snapshot(interactive_only: bool = True, max_elements: int = 100) -> dict:
    """Return a text description of the page: ARIA tree + actionable elements.

    The point is to let a text-only model "see" the page. It does not need a
    vision model or pixel screenshots - it needs to know which elements exist,
    what they are called, and how to address them.

    Note: ``page.accessibility.snapshot()`` was REMOVED in Playwright 1.63; the
    supported path is ``locator.aria_snapshot()`` (verified in-container).
    """
    global _page
    try:
        if _page is None:
            return {"success": False, "error": "No page open. Call browser_navigate first."}

        cap = max(1, min(int(max_elements or 100), 500))

        # 1) Interactive elements with ready-to-use CSS selectors. This is the
        #    part the model actually acts on.
        rows = await _page.evaluate(
            """(cap) => {
                const sel = 'a[href], button, input, select, textarea, '
                          + '[role=button], [role=link], [role=checkbox], '
                          + '[role=tab], [role=menuitem], [onclick], summary';
                const out = [];
                const seen = new Set();
                for (const el of document.querySelectorAll(sel)) {
                    if (out.length >= cap) break;
                    const r = el.getBoundingClientRect();
                    const style = window.getComputedStyle(el);
                    if (style.display === 'none' || style.visibility === 'hidden') continue;
                    if (r.width === 0 && r.height === 0) continue;
                    // Build a short, stable selector.
                    let id = '';
                    if (el.id && /^[A-Za-z][\\w-]*$/.test(el.id)) id = '#' + el.id;
                    else {
                        const parts = [];
                        let node = el;
                        for (let i = 0; i < 3 && node && node.nodeType === 1; i++) {
                            let part = node.tagName.toLowerCase();
                            if (node.id && /^[A-Za-z][\\w-]*$/.test(node.id)) {
                                parts.unshift('#' + node.id);
                                break;
                            }
                            const cls = (node.className && typeof node.className === 'string')
                                ? node.className.trim().split(/\\s+/).filter(Boolean) : [];
                            if (cls.length) part += '.' + cls[0];
                            parts.unshift(part);
                            node = node.parentElement;
                        }
                        id = parts.join(' > ');
                    }
                    if (seen.has(id)) continue;
                    seen.add(id);
                    const name = (el.getAttribute('aria-label')
                                  || el.getAttribute('title')
                                  || el.getAttribute('placeholder')
                                  || el.getAttribute('name')
                                  || (el.innerText || el.value || '')).trim().slice(0, 120);
                    out.push({
                        selector: id,
                        tag: el.tagName.toLowerCase(),
                        role: el.getAttribute('role') || '',
                        type: el.getAttribute('type') || '',
                        name: name,
                        disabled: !!el.disabled || el.getAttribute('aria-disabled') === 'true',
                    });
                }
                return out;
            }""",
            cap,
        )

        elements = rows if isinstance(rows, list) else []

        # 2) Compact ARIA outline of the page for context/navigation.
        aria = ""
        try:
            aria = await _page.locator("body").aria_snapshot(timeout=5000)
            if not isinstance(aria, str):
                aria = str(aria)
        except Exception:
            aria = ""

        return {
            "success": True,
            "data": {
                "url": _page.url,
                "title": await _page.title(),
                "elements": elements,
                "element_count": len(elements),
                "truncated": len(elements) >= cap,
                "aria": aria[:20000] if (interactive_only is False) else aria[:4000],
            },
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


async def set_viewport_size(width: int, height: int, reset: bool = False) -> dict:
    """Set the browser viewport, or reset it to the default when ``reset``."""
    global _page
    try:
        if reset:
            if _page is not None:
                await _page.set_viewport_size({"width": 1280, "height": 720})
            return {"success": True, "data": {"reset": True, "width": 1280, "height": 720}}
        w = max(320, min(int(width), 3840))
        h = max(240, min(int(height), 2160))
        if _page is None:
            return {
                "success": False,
                "error": "No page open. Call browser_navigate first, then set the viewport.",
            }
        await _page.set_viewport_size({"width": w, "height": h})
        return {"success": True, "data": {"width": w, "height": h}}
    except Exception as e:
        return {"success": False, "error": str(e)}


async def browser_get_text(selector: str = "", max_chars: int = 20000) -> dict:
    """Return visible page text, optionally scoped to one element."""
    global _page
    try:
        if selector:
            locator = _page.locator(selector)
            if await locator.count() == 0:
                return {"success": False, "error": f"No element matches selector: {selector}"}
            text = await locator.first.inner_text()
        else:
            text = await _page.evaluate("document.body ? document.body.innerText : ''")

        cap = max(100, min(int(max_chars or 20000), 200000))
        total = len(text)
        clipped = text[:cap]
        return {
            "success": True,
            "data": {
                "text": clipped,
                "length": total,
                "truncated": total > cap,
                "url": _page.url,
                "title": await _page.title(),
            },
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


async def browser_wait_for(selector: str = "", state: str = "visible", timeout: int = 10000) -> dict:
    """Wait for a selector to reach a state (visible/hidden/attached/detached).

    Also accepts ``state="load"`` / ``"networkidle"`` to wait on the page itself.
    """
    global _page
    allowed = {"visible", "hidden", "attached", "detached", "load", "networkidle"}
    if state not in allowed:
        return {"success": False, "error": f"state must be one of {sorted(allowed)}"}
    try:
        if state in ("load", "networkidle"):
            await _page.wait_for_load_state(state, timeout=int(timeout))
        else:
            await _page.locator(selector).first.wait_for(
                state=state, timeout=int(timeout)
            )
        return {
            "success": True,
            "data": {"selector": selector, "state": state, "url": _page.url},
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


async def browser_scroll(direction: str = "down", amount: int = 800, selector: str = "") -> dict:
    """Scroll the page, or a specific element, by a pixel amount."""
    global _page
    if direction not in ("up", "down", "top", "bottom"):
        return {"success": False, "error": "direction must be up, down, top, or bottom"}
    try:
        before = await _page.evaluate("window.scrollY")
        if selector:
            target = _page.locator(selector)
            if await target.count() == 0:
                return {"success": False, "error": f"No element matches selector: {selector}"}
            await target.first.evaluate(
                "(el, y) => el.scrollBy(0, y)", int(amount)
            )
        else:
            dy = int(amount) if direction in ("up", "down") else 0
            js = {
                "down": f"window.scrollBy(0, {abs(dy)})",
                "up": f"window.scrollBy(0, -{abs(dy)})",
                "top": "window.scrollTo(0, 0)",
                "bottom": "window.scrollTo(0, document.body.scrollHeight)",
            }[direction]
            await _page.evaluate(js)
        # Give the scroll a moment to settle before reporting the new offset.
        await _page.wait_for_timeout(200)
        after = await _page.evaluate("window.scrollY")
        return {
            "success": True,
            "data": {
                "direction": direction,
                "amount": amount,
                "scrolled": after - before,
                "position": after,
            },
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


async def browser_screenshot(path: str = "") -> dict:
    global _page
    try:
        if not path:
            path = str(WORKSPACE / "screenshot.png")
        await _page.screenshot(path=path)
        return {"success": True, "data": {"path": path}}
    except Exception as e:
        return {"success": False, "error": str(e)}


async def ping() -> dict:
    """Liveness probe. The host backend polls this to detect readiness."""
    return {"pong": True, "pid": os.getpid()}


# --- Read-only file access ----------------------------------------------------
# Dedicated methods rather than "cat"/"ls" through exec_command, so the host can
# grant file reading without widening the shell allowlist.

MAX_READ_BYTES = 1024 * 1024  # 1MB, matches settings.tools.max_output_size


def _safe_path(raw: str) -> Path:
    """Resolve a workspace-relative path, refusing anything outside the workspace.

    Containers are not a security boundary against a determined attacker (the
    user owns the image), but this stops a model mistake from wandering into
    /etc or /root by accident.
    """
    candidate = (WORKSPACE / (raw or ".")).resolve()
    if candidate != WORKSPACE and WORKSPACE not in candidate.parents:
        raise ValueError(f"Path '{raw}' escapes the workspace")
    return candidate


async def read_file(path: str, max_bytes: int = MAX_READ_BYTES) -> dict:
    """Read a UTF-8 text file from the workspace (read-only)."""
    try:
        target = _safe_path(path)
        if not target.exists():
            return {"success": False, "error": f"File not found: {path}"}
        if not target.is_file():
            return {"success": False, "error": f"Not a file: {path}"}
        size = target.stat().st_size
        cap = max(1, min(int(max_bytes or MAX_READ_BYTES), MAX_READ_BYTES))
        data = target.read_bytes()[:cap]
        text = data.decode("utf-8", errors="replace")
        return {
            "success": True,
            "data": {
                "path": str(target.relative_to(WORKSPACE)),
                "content": text,
                "size": size,
                "truncated": size > len(data),
            },
        }
    except ValueError as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        return {"success": False, "error": str(e)}


async def list_files(path: str = ".", max_depth: int = 3) -> dict:
    """List workspace directory contents (read-only)."""
    try:
        target = _safe_path(path)
        if not target.exists():
            return {"success": False, "error": f"Path not found: {path}"}
        if not target.is_dir():
            return {"success": False, "error": f"Not a directory: {path}"}

        skip = {".git", "__pycache__", ".venv", "venv", "node_modules", ".tonyagent"}
        depth_cap = max(1, min(int(max_depth or 3), 12))
        entries: list[dict] = []

        def walk(directory: Path, depth: int) -> None:
            if depth > depth_cap:
                return
            try:
                children = sorted(directory.iterdir(), key=lambda p: p.name.lower())
            except Exception:
                return
            for child in children:
                if child.name in skip:
                    continue
                rel = str(child.relative_to(WORKSPACE))
                is_dir = child.is_dir()
                size = 0 if is_dir else child.stat().st_size
                entries.append({"path": rel, "type": "dir" if is_dir else "file", "size": size})
                if is_dir:
                    walk(child, depth + 1)

        walk(target, 1)
        return {"success": True, "data": {"path": str(target.relative_to(WORKSPACE)), "entries": entries}}
    except ValueError as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        return {"success": False, "error": str(e)}


# Method dispatch
METHODS = {
    "ping": ping,
    "close": close_browser,
    "exec_command": exec_command,
    "execute_js": execute_js,
    "browser_navigate": browser_navigate,
    "browser_click": browser_click,
    "browser_type": browser_type,
    "browser_eval": browser_eval,
    "browser_snapshot": browser_snapshot,
    "set_viewport_size": set_viewport_size,
    "browser_get_text": browser_get_text,
    "browser_wait_for": browser_wait_for,
    "browser_scroll": browser_scroll,
    "browser_screenshot": browser_screenshot,
    "read_file": read_file,
    "list_files": list_files,
}


async def handle_request(request: dict) -> dict:
    """Handle a JSON-RPC request."""
    method = request.get("method")
    params = request.get("params", {})
    request_id = request.get("id")

    if method not in METHODS:
        return {
            "jsonrpc": "2.0",
            "error": {"code": -32601, "message": f"Method not found: {method}"},
            "id": request_id,
        }

    try:
        result = await METHODS[method](**params)
        return {"jsonrpc": "2.0", "result": result, "id": request_id}
    except Exception as e:
        return {
            "jsonrpc": "2.0",
            "error": {"code": -32603, "message": str(e)},
            "id": request_id,
        }


async def main():
    """Main RPC server loop: one JSON-RPC object per line on stdout."""
    # Line buffering keeps responses from sitting in a buffer waiting to fill.
    sys.stdout.reconfigure(line_buffering=True)
    loop = asyncio.get_event_loop()

    while True:
        # Read on a worker thread so the event loop stays free while idle.
        raw = await loop.run_in_executor(None, sys.stdin.buffer.readline)
        if not raw:
            break

        line = raw.decode("utf-8", errors="replace").strip()
        if not line:
            continue

        try:
            request = json.loads(line)
            response = await handle_request(request)
        except json.JSONDecodeError:
            continue
        except Exception:
            traceback.print_exc()
            continue

        # Write straight to the buffer: the previous asyncio.StreamWriter with
        # transport=None raised AttributeError on every single response.
        sys.stdout.buffer.write((json.dumps(response) + "\n").encode("utf-8"))
        sys.stdout.buffer.flush()


if __name__ == "__main__":
    asyncio.run(main())