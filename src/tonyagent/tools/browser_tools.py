"""Browser automation tools for TONYAgent."""

from __future__ import annotations

from typing import Any

from tonyagent.tools.base import Tool, ToolResult, ToolResultStatus, ToolCategory, register_tool
from tonyagent.sandbox import get_shared_sandbox_manager
from tonyagent.sandbox.base import SandboxStatus
from tonyagent.folder.manager import folder_manager


def get_sandbox_manager():
    """Backwards-compat alias returning the shared manager."""
    return get_shared_sandbox_manager()


def _check_sandbox(needs_network: bool = False, needs_isolation: bool = False):
    """Return None if a usable RUNNING backend exists, else an error string.

    A headless browser is not a shell escape, so these tools accept the local
    runtime and work with no Docker daemon. ``needs_isolation`` is for the one
    browser tool that runs arbitrary code (``execute_js``), which still refuses
    to run anywhere that does not contain it.

    ``needs_network`` is for the tools that genuinely load pages. Network egress
    is off by default in the container, so without this they would fail deep
    inside Playwright with a confusing DNS error instead of saying what to
    change. The local runtime has no such switch: the host's own network is what
    it uses, so the gate does not apply there.
    """
    manager = get_shared_sandbox_manager()
    backend = manager.get_runtime_backend()
    if backend is None:
        return (
            "The sandbox runtime is not running. Choose a project folder in "
            "Settings first."
        )
    if needs_isolation and not getattr(backend, "provides_isolation", False):
        return (
            "This tool runs arbitrary code, so it needs an isolated sandbox and "
            "only the local runtime is available. Start Docker, then pick the "
            "project folder again."
        )
    # getattr rather than a direct attribute: a third-party backend predating
    # either flag must not blow up here. Both default to the refusing answer.
    if needs_network and not getattr(backend, "has_network", False):
        return (
            "Browser tools need network access, but the sandbox is running with "
            "--network none. Enable it in Settings > Sandbox > 'Allow network "
            "access', restart the sandbox, then try again."
        )
    return None


def _running_backend():
    backend = get_shared_sandbox_manager().get_runtime_backend()
    if backend is None:
        raise RuntimeError(
            "The sandbox runtime is not running. Choose a project folder in "
            "Settings first."
        )
    return backend


def _isolated_backend():
    """The runtime for a tool that must not run uncontained."""
    manager = get_shared_sandbox_manager()
    backend = manager.get_backend()
    if backend is None or backend.status is not SandboxStatus.RUNNING:
        raise RuntimeError(
            "This tool runs arbitrary code, so it needs an isolated sandbox. "
            "Start Docker and pick the project folder again."
        )
    if not getattr(backend, "provides_isolation", False):
        raise RuntimeError(
            "This tool runs arbitrary code, so it needs an isolated sandbox."
        )
    return backend
@register_tool
class BrowserNavigateTool:
    name = "browser_navigate"
    description = "Navigate browser to a URL in the sandbox."
    category = ToolCategory.BROWSER
    parameters = {"type": "object", "properties": {"url": {"type": "string", "description": "URL to navigate to"}}, "required": ["url"], "additionalProperties": False}
    destructive = False
    requires_confirmation = True
    sandbox_required = True

    async def execute(self, url: str):
        error = _check_sandbox(needs_network=True)
        if error: return ToolResult(status=ToolResultStatus.ERROR, error=error)
        try:
            backend = _running_backend()
            result = await backend.browser_navigate(url)
            if result.success:
                return ToolResult(status=ToolResultStatus.SUCCESS, output=f"Navigated to {url}", artifacts=[{"type": "browser_navigate", "url": url}])
            else:
                return ToolResult(status=ToolResultStatus.ERROR, error=result.error)
        except Exception as e:
            return ToolResult(status=ToolResultStatus.ERROR, error=str(e))

@register_tool
class BrowserClickTool:
    name = "browser_click"
    description = "Click an element on the page by CSS selector."
    category = ToolCategory.BROWSER
    parameters = {"type": "object", "properties": {"selector": {"type": "string", "description": "CSS selector of element to click"}}, "required": ["selector"], "additionalProperties": False}
    destructive = False
    requires_confirmation = True
    sandbox_required = True

    async def execute(self, selector: str):
        error = _check_sandbox(needs_network=True)
        if error: return ToolResult(status=ToolResultStatus.ERROR, error=error)
        try:
            backend = _running_backend()
            result = await backend.browser_click(selector)
            if result.success:
                return ToolResult(status=ToolResultStatus.SUCCESS, output=f"Clicked {selector}")
            else:
                return ToolResult(status=ToolResultStatus.ERROR, error=result.error)
        except Exception as e:
            return ToolResult(status=ToolResultStatus.ERROR, error=str(e))

@register_tool
class BrowserTypeTool:
    name = "browser_type"
    description = "Type text into an element by CSS selector."
    category = ToolCategory.BROWSER
    parameters = {"type": "object", "properties": {"selector": {"type": "string", "description": "CSS selector of element"}, "text": {"type": "string", "description": "Text to type"}}, "required": ["selector", "text"], "additionalProperties": False}
    destructive = False
    requires_confirmation = True
    sandbox_required = True

    async def execute(self, selector: str, text: str):
        error = _check_sandbox()
        if error: return ToolResult(status=ToolResultStatus.ERROR, error=error)
        try:
            backend = _running_backend()
            result = await backend.browser_type(selector, text)
            if result.success:
                return ToolResult(status=ToolResultStatus.SUCCESS, output=f"Typed into {selector}")
            else:
                return ToolResult(status=ToolResultStatus.ERROR, error=result.error)
        except Exception as e:
            return ToolResult(status=ToolResultStatus.ERROR, error=str(e))

@register_tool
class BrowserEvalTool:
    name = "browser_eval"
    description = "Evaluate JavaScript in the browser page context."
    category = ToolCategory.BROWSER
    parameters = {"type": "object", "properties": {"script": {"type": "string", "description": "JavaScript code to evaluate"}}, "required": ["script"], "additionalProperties": False}
    destructive = False
    requires_confirmation = False
    sandbox_required = True

    async def execute(self, script: str):
        error = _check_sandbox()
        if error: return ToolResult(status=ToolResultStatus.ERROR, error=error)
        try:
            backend = _running_backend()
            result = await backend.browser_eval(script)
            if result.success:
                return ToolResult(status=ToolResultStatus.SUCCESS, output=str(result.data), artifacts=[{"type": "browser_eval", "result": result.data}])
            else:
                return ToolResult(status=ToolResultStatus.ERROR, error=result.error)
        except Exception as e:
            return ToolResult(status=ToolResultStatus.ERROR, error=str(e))

@register_tool
class BrowserSnapshotTool:
    name = "browser_snapshot"
    description = (
        "Get a text snapshot of the current page: the interactive elements (with "
        "CSS selectors you can pass to browser_click / browser_type) plus an ARIA "
        "outline. Call this FIRST after navigating, and again after any action that "
        "changes the page, so you know what is clickable. No vision model needed."
    )
    category = ToolCategory.BROWSER
    parameters = {
        "type": "object",
        "properties": {
            "interactive_only": {
                "type": "boolean",
                "description": "True (default) lists only actionable elements and trims the ARIA outline; False includes a longer outline",
                "default": True,
            },
            "max_elements": {
                "type": "integer",
                "description": "Maximum elements to list",
                "default": 100,
            },
        },
        "additionalProperties": False,
    }
    destructive = False
    requires_confirmation = False
    sandbox_required = True

    async def execute(self, interactive_only: bool = True, max_elements: int = 100):
        error = _check_sandbox()
        if error:
            return ToolResult(status=ToolResultStatus.ERROR, error=error)
        try:
            backend = _running_backend()
            result = await backend.browser_snapshot(interactive_only, max_elements)
            if not result.success:
                return ToolResult(status=ToolResultStatus.ERROR, error=result.error)
            data = result.data if isinstance(result.data, dict) else {}
            elements = data.get("elements", [])
            if not isinstance(elements, list):
                elements = []

            lines = [
                f"URL: {data.get('url', '')}",
                f"Title: {data.get('title', '')}",
                f"Interactive elements: {len(elements)}"
                + (" (truncated)" if data.get("truncated") else ""),
                "",
            ]
            for el in elements:
                if not isinstance(el, dict):
                    continue
                name = (el.get("name") or "").strip()
                tag = el.get("tag", "")
                bits = [f"[{tag}]"]
                if el.get("type"):
                    bits.append(f"type={el['type']}")
                if el.get("role"):
                    bits.append(f"role={el['role']}")
                if el.get("disabled"):
                    bits.append("disabled")
                label = f' "{name}"' if name else ""
                lines.append(f"  {el.get('selector', '')}{label}  {' '.join(bits[1:])}")

            if not elements:
                lines.append("  (no interactive elements found)")

            aria = (data.get("aria") or "").strip()
            if aria:
                lines += ["", "--- ARIA outline ---", aria]

            return ToolResult(
                status=ToolResultStatus.SUCCESS,
                output="\n".join(lines),
                artifacts=[
                    {
                        "type": "page_snapshot",
                        "url": data.get("url", ""),
                        "title": data.get("title", ""),
                        "element_count": len(elements),
                    }
                ],
            )
        except Exception as e:
            return ToolResult(status=ToolResultStatus.ERROR, error=str(e))


@register_tool
class SetViewportSizeTool:
    name = "set_viewport_size"
    description = (
        "Set the browser viewport size for responsive testing (for example "
        "390x844 for a phone). Use reset=true to restore the default."
    )
    category = ToolCategory.BROWSER
    parameters = {
        "type": "object",
        "properties": {
            "width": {"type": "integer", "description": "Viewport width in pixels"},
            "height": {"type": "integer", "description": "Viewport height in pixels"},
            "reset": {
                "type": "boolean",
                "description": "Restore the default 1280x720 viewport",
                "default": False,
            },
        },
        "required": ["width", "height"],
        "additionalProperties": False,
    }
    destructive = False
    requires_confirmation = False
    sandbox_required = True

    async def execute(self, width: int = 1280, height: int = 720, reset: bool = False):
        error = _check_sandbox()
        if error:
            return ToolResult(status=ToolResultStatus.ERROR, error=error)
        try:
            backend = _running_backend()
            result = await backend.set_viewport_size(width, height, reset)
            if not result.success:
                return ToolResult(status=ToolResultStatus.ERROR, error=result.error)
            data = result.data if isinstance(result.data, dict) else {}
            if data.get("reset"):
                return ToolResult(
                    status=ToolResultStatus.SUCCESS, output="Viewport reset to 1280x720."
                )
            return ToolResult(
                status=ToolResultStatus.SUCCESS,
                output=f"Viewport set to {data.get('width')}x{data.get('height')}.",
                artifacts=[{"type": "viewport", **data}],
            )
        except Exception as e:
            return ToolResult(status=ToolResultStatus.ERROR, error=str(e))


@register_tool
class BrowserGetTextTool:
    name = "browser_get_text"
    description = (
        "Read the visible text of the current page, optionally scoped to one CSS "
        "selector. Prefer this over browser_eval('document.body.innerText')."
    )
    category = ToolCategory.BROWSER
    parameters = {
        "type": "object",
        "properties": {
            "selector": {
                "type": "string",
                "description": "Optional CSS selector to scope to (e.g. 'main' or 'h1')",
                "default": "",
            },
            "max_chars": {
                "type": "integer",
                "description": "Maximum characters to return",
                "default": 20000,
            },
        },
        "additionalProperties": False,
    }
    destructive = False
    requires_confirmation = False
    sandbox_required = True

    async def execute(self, selector: str = "", max_chars: int = 20000):
        error = _check_sandbox()
        if error:
            return ToolResult(status=ToolResultStatus.ERROR, error=error)
        try:
            backend = _running_backend()
            result = await backend.browser_get_text(selector, max_chars)
            if not result.success:
                return ToolResult(status=ToolResultStatus.ERROR, error=result.error)
            data = result.data if isinstance(result.data, dict) else {}
            text = data.get("text", "")
            note = ""
            if data.get("truncated"):
                note = f"\n\n[truncated: {len(text)} of {data.get('length', '?')} chars]"
            return ToolResult(
                status=ToolResultStatus.SUCCESS,
                output=text + note,
                artifacts=[
                    {
                        "type": "page_text",
                        "url": data.get("url", ""),
                        "title": data.get("title", ""),
                        "length": data.get("length", len(text)),
                    }
                ],
            )
        except Exception as e:
            return ToolResult(status=ToolResultStatus.ERROR, error=str(e))


@register_tool
class BrowserWaitForTool:
    name = "browser_wait_for"
    description = (
        "Wait for a CSS selector to reach a state (visible, hidden, attached, "
        "detached), or wait for the page load state. Use before clicking or "
        "reading content that loads asynchronously."
    )
    category = ToolCategory.BROWSER
    parameters = {
        "type": "object",
        "properties": {
            "selector": {
                "type": "string",
                "description": "CSS selector to wait for (empty when state is load/networkidle)",
                "default": "",
            },
            "state": {
                "type": "string",
                "enum": ["visible", "hidden", "attached", "detached", "load", "networkidle"],
                "default": "visible",
            },
            "timeout": {
                "type": "integer",
                "description": "Timeout in milliseconds",
                "default": 10000,
            },
        },
        "additionalProperties": False,
    }
    destructive = False
    requires_confirmation = False
    sandbox_required = True

    async def execute(self, selector: str = "", state: str = "visible", timeout: int = 10000):
        error = _check_sandbox()
        if error:
            return ToolResult(status=ToolResultStatus.ERROR, error=error)
        if state not in ("load", "networkidle") and not selector:
            return ToolResult(
                status=ToolResultStatus.ERROR,
                error="Provide a CSS selector, or set state to 'load'/'networkidle'.",
            )
        try:
            backend = _running_backend()
            result = await backend.browser_wait_for(selector, state, timeout)
            if not result.success:
                return ToolResult(status=ToolResultStatus.ERROR, error=result.error)
            data = result.data if isinstance(result.data, dict) else {}
            return ToolResult(
                status=ToolResultStatus.SUCCESS,
                output=f"Reached '{state}' for {selector or 'the page'}.",
                artifacts=[{"type": "wait", **data}],
            )
        except Exception as e:
            return ToolResult(status=ToolResultStatus.ERROR, error=str(e))


@register_tool
class BrowserScrollTool:
    name = "browser_scroll"
    description = (
        "Scroll the page (or a specific element) up, down, to the top, or to the "
        "bottom. Use to reach content below the fold or to trigger lazy loading."
    )
    category = ToolCategory.BROWSER
    parameters = {
        "type": "object",
        "properties": {
            "direction": {
                "type": "string",
                "enum": ["up", "down", "top", "bottom"],
                "default": "down",
            },
            "amount": {
                "type": "integer",
                "description": "Pixels to scroll (ignored for top/bottom)",
                "default": 800,
            },
            "selector": {
                "type": "string",
                "description": "Optional CSS selector to scroll a specific element",
                "default": "",
            },
        },
        "additionalProperties": False,
    }
    destructive = False
    requires_confirmation = False
    sandbox_required = True

    async def execute(self, direction: str = "down", amount: int = 800, selector: str = ""):
        error = _check_sandbox()
        if error:
            return ToolResult(status=ToolResultStatus.ERROR, error=error)
        try:
            backend = _running_backend()
            result = await backend.browser_scroll(direction, amount, selector)
            if not result.success:
                return ToolResult(status=ToolResultStatus.ERROR, error=result.error)
            data = result.data if isinstance(result.data, dict) else {}
            scrolled = data.get("scrolled", 0)
            return ToolResult(
                status=ToolResultStatus.SUCCESS,
                output=(
                    f"Scrolled {direction} (moved {scrolled}px, now at "
                    f"{data.get('position', 0)}px)."
                ),
                artifacts=[{"type": "scroll", **data}],
            )
        except Exception as e:
            return ToolResult(status=ToolResultStatus.ERROR, error=str(e))


@register_tool
class BrowserScreenshotTool:
    name = "browser_screenshot"
    description = "Capture a screenshot of the current browser page."
    category = ToolCategory.BROWSER
    parameters = {"type": "object", "properties": {"path": {"type": "string", "description": "Path to save screenshot (relative to project root)", "default": ""}}, "additionalProperties": False}
    destructive = False
    requires_confirmation = False
    sandbox_required = True

    async def execute(self, path: str = ""):
        error = _check_sandbox()
        if error:
            return ToolResult(status=ToolResultStatus.ERROR, error=error)
        try:
            backend = _running_backend()
            # Map host-relative path to /workspace; empty -> server default.
            sandbox_path = ""
            if path:
                project_root = folder_manager.current_folder
                if project_root is None:
                    return ToolResult(
                        status=ToolResultStatus.ERROR, error="No project folder selected"
                    )
                target = (project_root / path).resolve()
                try:
                    rel = target.relative_to(project_root.resolve()).as_posix()
                except ValueError:
                    return ToolResult(
                        status=ToolResultStatus.ERROR,
                        error=f"Path '{path}' attempts to escape project folder",
                    )
                sandbox_path = f"/workspace/{rel}" if rel != "." else "/workspace"
            result = await backend.browser_screenshot(sandbox_path)
            if result.success:
                data = result.data if isinstance(result.data, dict) else {}
                saved = data.get("path", path)
                return ToolResult(
                    status=ToolResultStatus.SUCCESS,
                    output=f"Screenshot saved to {saved}",
                    artifacts=[{"type": "screenshot", "path": saved}],
                )
            else:
                return ToolResult(status=ToolResultStatus.ERROR, error=result.error)
        except Exception as e:
            return ToolResult(status=ToolResultStatus.ERROR, error=str(e))

@register_tool
class ExecuteJsTool:
    name = "execute_js"
    description = "Execute JavaScript in Node.js context in the sandbox."
    category = ToolCategory.BROWSER
    parameters = {"type": "object", "properties": {"script": {"type": "string", "description": "JavaScript code to execute"}, "timeout": {"type": "integer", "description": "Timeout in seconds", "default": 10}}, "required": ["script"], "additionalProperties": False}
    destructive = False
    requires_confirmation = True
    sandbox_required = True
    # Arbitrary code, so the local runtime is not enough: this one keeps
    # needing a backend that contains it.
    isolation_required = True

    async def execute(self, script: str, timeout: int = 10):
        error = _check_sandbox(needs_isolation=True)
        if error: return ToolResult(status=ToolResultStatus.ERROR, error=error)
        try:
            backend = _isolated_backend()
            result = await backend.execute_js(script, timeout)
            if result.success:
                return ToolResult(status=ToolResultStatus.SUCCESS, output=str(result.data), artifacts=[{"type": "execute_js", "result": result.data}])
            else:
                return ToolResult(status=ToolResultStatus.ERROR, error=result.error)
        except Exception as e:
            return ToolResult(status=ToolResultStatus.ERROR, error=str(e))
