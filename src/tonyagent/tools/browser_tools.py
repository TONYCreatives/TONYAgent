"""Browser automation tools for TONYAgent."""

from __future__ import annotations

from typing import Any

from tonyagent.tools.base import Tool, ToolResult, ToolResultStatus, ToolCategory, register_tool
from tonyagent.tools.runtime_access import (
    check_runtime,
    isolated_backend,
    running_backend,
)
from tonyagent.sandbox import get_shared_sandbox_manager
from tonyagent.sandbox.base import SandboxStatus
from tonyagent.tools.workspace import confine, project_root


def get_sandbox_manager():
    """Backwards-compat alias returning the shared manager."""
    return get_shared_sandbox_manager()


def _check_sandbox(needs_network: bool = False, needs_isolation: bool = False):
    """Return None if a usable runtime exists, else an error string.

    Thin alias for :func:`runtime_access.check_runtime`, kept so the existing
    call sites and their tests read the same. The implementation is shared with
    the sandbox file tools: two copies of this is how ``execute_command`` and
    ``execute_js`` came to describe one condition differently.
    """
    return check_runtime(needs_network=needs_network, needs_isolation=needs_isolation)


def _running_backend():
    """The runtime for the browser tools, or raise. See runtime_access."""
    return running_backend()


def _isolated_backend():
    """The runtime for a tool that must not run uncontained."""
    return isolated_backend()
# The confirm-prompt flag on this module.
#
# ``browser_navigate``, ``browser_click``, ``browser_type`` and ``execute_js``
# all declared ``requires_confirmation = True`` once, and all four were inert:
# the orchestrator's gate at ``orchestrator.py::_needs_confirmation`` is
# ``destructive and requires_confirmation``, and none of them is destructive,
# so the question was never asked and never could be. That is the same class of
# lie as a schema whose flag is a claim nothing enforces, so the flag is dropped
# rather than the gate widened.
#
# Why not make the gate fire on them instead -- the question NEXT_SESSION
# recorded as needing a decision first -- because the honest consequence,
# once worked through, is worse than the inconsistency:
#
# * ``execute_js`` is arbitrary model-authored code, which looks like the case
#   for a prompt. But it is in the read-only tool set -- reachable in Plan mode
#   and at Low -- and the whole design of those modes is that nothing stops the
#   turn: Plan's read-only sweep runs unattended. Sending every ``execute_js``
#   to the destructive prompt would make Plan stop mid-read, and ``skips_confirmation``
#   on Full would then be the only thing letting Plan finish, which has the
#   permission ladder contradicting itself to fix a prompt the ladder never
#   asked for.
#
# * ``browser_click`` before every click is worse still. A page interaction is
#   one click of several -- snapshot, click, type, scroll, click -- and a prompt
#   between each is a browser the user has to baby-sit. The old affordance for
#   easing that, session-middle "always allow tool till turn done", is not what
#   the confirmation-wait code implements either: it currently maps to
#   task-set *and prompt-step pause* (``_wait_till_get_reply``), so a browser
#   session under it is not even a promise the click runs.
#
# * The destructive prompt is for things that cannot be undone: a `write` over
#   a file, a `delete_file`, a command whose effects do not stay in the
#   container. None of these four is that. Their real gates are the ones they
#   already carry: ``sandbox_required`` and, for ``execute_js``,
#   ``isolation_required`` -- which is exactly the gate that keeps arbitrary
#   code off the host, and which the destructive prompt never was.
#
# ``test_no_tool_claims_confirmation_without_destructive`` in
# ``tests/unit/test_local_sandbox.py`` pins the invariant registry-wide, counted
# against the registry rather than from memory -- which is how the earlier count
# of five missed ``execute_js``. If a seventh tool ever wants a real prompt, the
# decision it needs is what makes it destructive, not a louder flag.

@register_tool
class BrowserNavigateTool(Tool):
    """Open a URL in the headless browser.

    Starts the browser on first use and reuses the page afterwards, so this is
    the call that establishes the session every other browser tool acts on.
    """

    name = "browser_navigate"
    description = "Navigate browser to a URL in the sandbox."
    category = ToolCategory.BROWSER
    parameters = {"type": "object", "properties": {"url": {"type": "string", "description": "URL to navigate to"}}, "required": ["url"], "additionalProperties": False}
    destructive = False
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
class BrowserClickTool(Tool):
    """Click an element matched by a CSS selector.

    A selector that matches nothing costs Playwright's full timeout, so prefer
    a selector you have seen in a snapshot.
    """

    name = "browser_click"
    description = "Click an element on the page by CSS selector."
    category = ToolCategory.BROWSER
    parameters = {"type": "object", "properties": {"selector": {"type": "string", "description": "CSS selector of element to click"}}, "required": ["selector"], "additionalProperties": False}
    destructive = False
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
class BrowserTypeTool(Tool):
    """Type text into an element matched by a CSS selector.

    Fills the field rather than sending per-key events, so it suits forms and
    search boxes; it is not a way to reproduce keystroke-by-keystroke
    behaviour.
    """

    name = "browser_type"
    description = "Type text into an element by CSS selector."
    category = ToolCategory.BROWSER
    parameters = {"type": "object", "properties": {"selector": {"type": "string", "description": "CSS selector of element"}, "text": {"type": "string", "description": "Text to type"}}, "required": ["selector", "text"], "additionalProperties": False}
    destructive = False
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
class BrowserEvalTool(Tool):
    """Evaluate JavaScript in the page and return the result.

    The escape hatch for anything the other tools cannot express. It runs in
    the page, not in Node -- for the latter see ``execute_js``.
    """

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
class BrowserSnapshotTool(Tool):
    """Describe the current page as text: an ARIA tree of interactive elements.

    This is how the model learns which selectors are real. Guessing selectors
    from a URL is what makes the other browser tools time out.
    """

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
class SetViewportSizeTool(Tool):
    """Resize the viewport, for checking responsive layout.

    The resize persists for later calls, so a test that cares about both phone
    and desktop widths has to set the size before each phase rather than once.
    """

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
class BrowserGetTextTool(Tool):
    """Read the visible text of the page, optionally scoped to one selector.

    Truncates at ``max_chars`` and says so. Note that the text is whatever the
    page served, which is not always English -- assert on substance rather than
    on a string you saw once.
    """

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
class BrowserWaitForTool(Tool):
    """Wait for a selector to reach a state: visible, hidden, attached, detached.

    The right answer to a page that has not finished loading. Polling here costs
    one round trip; guessing and re-navigating costs the whole flow.
    """

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
class BrowserScrollTool(Tool):
    """Scroll the page, or one element, up, down, to the top or to the bottom.

    Scrolling an element is how lazily-loaded content is usually revealed.
    """

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
class BrowserScreenshotTool(Tool):
    """Capture a screenshot into the project folder.

    Writes inside the workspace, so the path is confined like any other file
    tool. An empty path saves as ``screenshot.png`` at the workspace root.
    """

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
                # The boundary's check, not a fifth copy of it (see
                # `tonyagent.tools.workspace`): only the host -> container
                # mapping belongs here.
                try:
                    rel = confine(path).relative_to(project_root()).as_posix()
                except ValueError as exc:
                    return ToolResult(status=ToolResultStatus.ERROR, error=str(exc))
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
class ExecuteJsTool(Tool):
    """Run JavaScript under Node.js, outside any page.

    Lives in this module only because it shares the runtime; it is not a
    browser tool. It executes arbitrary code, so like ``execute_command`` it
    refuses to run on the local runtime and needs a containing backend --
    ``category`` says SHELL for that reason.
    """

    name = "execute_js"
    description = "Execute JavaScript in Node.js context in the sandbox."
    category = ToolCategory.SHELL
    parameters = {"type": "object", "properties": {"script": {"type": "string", "description": "JavaScript code to execute"}, "timeout": {"type": "integer", "description": "Timeout in seconds", "default": 10}}, "required": ["script"], "additionalProperties": False}
    destructive = False
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
