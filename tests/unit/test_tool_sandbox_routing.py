"""Phase 3 tests: tools route through the shared sandbox manager."""

from __future__ import annotations

import asyncio

import pytest

from tonyagent.config.settings import settings
from tonyagent.folder.manager import folder_manager
from tonyagent.sandbox import get_shared_sandbox_manager
from tonyagent.providers import ChatCompletion, ChatCompletionChunk
from tonyagent.sandbox.base import BrowserResult, CommandResult, SandboxConfig, SandboxStatus
from tonyagent.tools.base import ToolResultStatus
from tonyagent.tools.browser_tools import _check_sandbox
from tonyagent.tools.shell_tools import ExecuteCommandTool, _resolve_sandbox_cwd


class FakeBackend:
    #: Stands in for the container, so it declares that it contains what runs
    #: inside it. The code-execution tools refuse anything that does not.
    provides_isolation = True

    def __init__(self, enable_network: bool = True):
        self.status = SandboxStatus.RUNNING
        self.last_cwd: str | None = None
        # browser_* tools refuse to run without egress, so the default fake
        # opts in. Use FakeBackend(enable_network=False) to test that path.
        self.config = SandboxConfig(enable_network=enable_network)

    @property
    def has_network(self) -> bool:
        return bool(self.config.enable_network)

    async def execute_command(self, command, cwd="/workspace", timeout=30):
        self.last_cwd = cwd
        assert cwd.startswith("/workspace"), cwd
        return CommandResult(stdout=f"ran:{command}", stderr="", returncode=0)

    async def ping(self, timeout=10):
        return {"pong": True, "pid": 1}

    async def health_check(self):
        return True

    async def browser_navigate(self, url):
        return BrowserResult(success=True, data={"url": url, "title": "T"})


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setattr(folder_manager, "_current_folder", tmp_path)
    (tmp_path / "sub").mkdir()
    return tmp_path


@pytest.fixture
def fake_backend():
    manager = get_shared_sandbox_manager()
    backend = FakeBackend()
    manager._backend = backend
    yield backend
    manager._backend = None


async def test_check_sandbox_none_when_running(fake_backend):
    assert _check_sandbox() is None


async def test_check_sandbox_error_when_stopped():
    get_shared_sandbox_manager()._backend = None
    err = _check_sandbox()
    assert err and "not running" in err.lower()


async def test_resolve_sandbox_cwd(project):
    assert _resolve_sandbox_cwd(".") == "/workspace"
    assert _resolve_sandbox_cwd("sub") == "/workspace/sub"
    with pytest.raises(ValueError):
        _resolve_sandbox_cwd("../escape")


async def test_execute_command_routes_to_sandbox(project, fake_backend):
    tool = ExecuteCommandTool()
    result = await tool.execute("python --version", cwd="sub", timeout=5)
    assert result.status is ToolResultStatus.SUCCESS
    assert fake_backend.last_cwd == "/workspace/sub"
    assert "ran:python --version" in result.output["stdout"]


async def test_execute_command_fails_closed_without_sandbox(project, monkeypatch):
    get_shared_sandbox_manager()._backend = None
    monkeypatch.setattr(settings.tools, "fallback_to_local", False)
    tool = ExecuteCommandTool()
    result = await tool.execute("python --version")
    assert result.status is ToolResultStatus.ERROR
    assert "sandbox" in result.error.lower()


async def test_execute_command_falls_back_when_enabled(project, monkeypatch):
    get_shared_sandbox_manager()._backend = None
    monkeypatch.setattr(settings.tools, "fallback_to_local", True)
    tool = ExecuteCommandTool()
    result = await tool.execute("python -c \"print('hello-fallback')\"")
    assert result.status is ToolResultStatus.SUCCESS
    assert "hello-fallback" in result.output["stdout"]


async def test_browser_tool_uses_shared_backend(project, fake_backend):
    from tonyagent.tools.browser_tools import BrowserNavigateTool

    tool = BrowserNavigateTool()
    result = await tool.execute("https://example.com")
    assert result.status is ToolResultStatus.SUCCESS


async def test_shared_manager_singleton():
    from tonyagent.sandbox import get_shared_sandbox_manager as get2
    from tonyagent.tools.browser_tools import get_sandbox_manager as tools_get

    assert get2() is get_shared_sandbox_manager()
    assert tools_get() is get_shared_sandbox_manager()


async def test_browser_tool_refuses_when_network_disabled(project, monkeypatch):
    """With egress off, navigate must explain itself instead of failing obscurely."""
    from tonyagent.tools.browser_tools import BrowserNavigateTool

    manager = get_shared_sandbox_manager()
    manager._backend = FakeBackend(enable_network=False)
    try:
        result = await BrowserNavigateTool().execute("https://example.com")
        assert result.status is ToolResultStatus.ERROR
        assert "network" in result.error.lower()
        assert "Settings" in result.error
    finally:
        manager._backend = None


async def test_shell_tool_still_works_with_network_disabled(project, monkeypatch):
    """Shell commands need no egress, so hardening must not break them."""
    manager = get_shared_sandbox_manager()
    manager._backend = FakeBackend(enable_network=False)
    try:
        result = await ExecuteCommandTool().execute("python --version", cwd=".")
        assert result.status is ToolResultStatus.SUCCESS
        assert "ran:python --version" in result.output["stdout"]
    finally:
        manager._backend = None


# --- Stage A: SSRF guard (http_request) ---------------------------------------

# Every one of these must be treated as internal. The old implementation
# missed link-local and IPv6 entirely, and was gated on the wrong setting.
INTERNAL_HOSTS = [
    "localhost",
    "app.localhost",
    "myhost.local",
    "127.0.0.1",
    "127.1",             # abbreviated loopback
    "2130706433",        # decimal encoding of 127.0.0.1
    "0.0.0.0",           # unspecified
    "10.0.0.5",
    "172.16.3.4",
    "192.168.1.1",
    "169.254.169.254",   # cloud instance metadata - the big one
    "169.254.1.1",
    "::1",               # IPv6 loopback
    "[::1]",
    "fe80::1",           # IPv6 link-local
    "fc00::1",           # IPv6 unique-local
    "224.0.0.1",         # multicast
    "",                  # empty -> fail closed
]

PUBLIC_HOSTS = [
    "example.com",
    "api.openai.com",
    "8.8.8.8",
    "1.1.1.1",
    "2606:4700::1111",
]


@pytest.mark.parametrize("host", INTERNAL_HOSTS)
def test_internal_hosts_are_detected(host):
    from tonyagent.tools.network_tools import _is_internal_host

    assert _is_internal_host(host) is True, f"{host!r} should be internal"


@pytest.mark.parametrize("host", PUBLIC_HOSTS)
def test_public_hosts_are_not_flagged(host):
    from tonyagent.tools.network_tools import _is_internal_host

    assert _is_internal_host(host) is False, f"{host!r} should be public"


def test_ssrf_guard_is_independent_of_sandbox_network(monkeypatch):
    """The regression that motivated Stage A: the old guard used the sandbox flag.

    With sandbox network OFF, internal hosts must still be BLOCKED. Previously
    the inverted check let them through.
    """
    from tonyagent.config.settings import settings
    from tonyagent.tools.base import ToolResultStatus
    from tonyagent.tools.network_tools import HttpRequestTool

    monkeypatch.setattr(settings.sandbox, "enable_network", False)
    monkeypatch.setattr(settings.tools, "allow_internal_http", False)
    async def _check():
        out = []
        for host in ("http://127.0.0.1:8080/", "http://169.254.169.254/latest/meta-data/"):
            out.append(await HttpRequestTool().execute(host))
        return out

    results = asyncio.run(_check())
    for r in results:
        assert r.status is ToolResultStatus.ERROR
        assert "internal address" in r.error


def test_internal_http_requires_explicit_opt_in(monkeypatch):
    """Enabling sandbox network must NOT unlock internal hosts."""
    from tonyagent.config.settings import settings
    from tonyagent.tools.base import ToolResultStatus
    from tonyagent.tools.network_tools import HttpRequestTool

    monkeypatch.setattr(settings.sandbox, "enable_network", True)   # unrelated
    monkeypatch.setattr(settings.tools, "allow_internal_http", False)

    async def _check():
        return await HttpRequestTool().execute("http://localhost:3000/")

    r = asyncio.run(_check())
    assert r.status is ToolResultStatus.ERROR
    assert "allow_internal_http" in r.error


def test_allow_internal_http_opt_in_passes_the_guard(monkeypatch):
    """With the opt-in set, the guard stops blocking (connection may still fail)."""
    from tonyagent.config.settings import settings
    from tonyagent.tools.network_tools import HttpRequestTool

    monkeypatch.setattr(settings.tools, "allow_internal_http", True)

    async def _check():
        # Port 1 on loopback refuses fast; we only care it is not *blocked*.
        return await HttpRequestTool().execute("http://127.0.0.1:1/", timeout=2)

    r = asyncio.run(_check())
    assert r is not None
    assert "internal address" not in (r.error or "")


def test_allow_internal_http_defaults_to_false():
    from tonyagent.config.settings import ToolsSettings

    assert ToolsSettings().allow_internal_http is False


# --- Stage B: read-only in-container file tools --------------------------------

class SandboxFileBackend(FakeBackend):
    """Backend that answers read_file / list_files like the real container."""

    def __init__(self, content="hello from the container", entries=None, fail=None):
        super().__init__(enable_network=True)
        self.content = content
        self.entries = entries if entries is not None else [
            {"path": "probe.txt", "type": "file", "size": 12},
            {"path": "sub", "type": "dir", "size": 0},
        ]
        self.fail = fail

    async def read_file(self, path, max_bytes=1048576):
        from tonyagent.sandbox.base import BrowserResult

        if self.fail:
            return BrowserResult(success=False, error=self.fail)
        if path == "big.txt":
            return BrowserResult(
                success=True,
                data={"path": path, "content": "x" * 10, "size": 999, "truncated": True},
            )
        return BrowserResult(
            success=True, data={"path": path, "content": self.content, "size": len(self.content), "truncated": False}
        )

    async def list_files(self, path=".", max_depth=3):
        from tonyagent.sandbox.base import BrowserResult

        if self.fail:
            return BrowserResult(success=False, error=self.fail)
        return BrowserResult(success=True, data={"path": path, "entries": self.entries})


@pytest.fixture
def sandbox_file_backend():
    manager = get_shared_sandbox_manager()
    backend = SandboxFileBackend()
    manager._backend = backend
    yield backend
    manager._backend = None


async def test_sandbox_read_file_returns_content(sandbox_file_backend):
    from tonyagent.tools.sandbox_file_tools import SandboxReadFileTool

    r = await SandboxReadFileTool().execute("probe.txt")
    assert r.status is ToolResultStatus.SUCCESS
    assert "hello from the container" in r.output


async def test_sandbox_read_file_flags_truncation(sandbox_file_backend):
    from tonyagent.tools.sandbox_file_tools import SandboxReadFileTool

    r = await SandboxReadFileTool().execute("big.txt")
    assert r.status is ToolResultStatus.SUCCESS
    assert "truncated" in r.output.lower()
    assert "999" in r.output


async def test_sandbox_list_files_marks_directories(sandbox_file_backend):
    from tonyagent.tools.sandbox_file_tools import SandboxListFilesTool

    r = await SandboxListFilesTool().execute(".")
    assert r.status is ToolResultStatus.SUCCESS
    assert "probe.txt" in r.output
    assert "sub/" in r.output  # trailing slash = directory
    assert "2 entries" in r.output


async def test_sandbox_list_files_empty(sandbox_file_backend):
    from tonyagent.tools.sandbox_file_tools import SandboxListFilesTool

    sandbox_file_backend.entries = []
    r = await SandboxListFilesTool().execute(".")
    assert r.status is ToolResultStatus.SUCCESS
    assert r.output == "(empty)"


async def test_sandbox_file_tools_fail_closed_without_backend():
    from tonyagent.tools.sandbox_file_tools import SandboxListFilesTool, SandboxReadFileTool

    get_shared_sandbox_manager()._backend = None
    for tool in (SandboxReadFileTool(), SandboxListFilesTool()):
        r = await tool.execute("probe.txt")
        assert r.status is ToolResultStatus.ERROR
        assert "sandbox" in r.error.lower()


async def test_sandbox_file_tools_surface_container_errors(sandbox_file_backend):
    from tonyagent.tools.sandbox_file_tools import SandboxReadFileTool

    sandbox_file_backend.fail = "File not found: nope.txt"
    r = await SandboxReadFileTool().execute("nope.txt")
    assert r.status is ToolResultStatus.ERROR
    assert "File not found" in r.error


def test_sandbox_file_tools_are_registered_and_advertised():
    """Registry and ALL_SCHEMAS are parallel sources of truth - keep them in sync."""
    import tonyagent.tools as T

    for name in ("sandbox_read_file", "sandbox_list_files"):
        assert name in T.tool_registry.list_names(), f"{name} not registered"
        assert name in T.SCHEMAS_BY_NAME, f"{name} missing from schemas"
        tool = T.tool_registry.get(name)
        assert tool.sandbox_required is True
        assert tool.destructive is False
        assert tool.requires_confirmation is False  # read-only, no prompt


def test_registry_and_schemas_never_diverge():
    """A tool registered but not advertised silently breaks every model call."""
    import tonyagent.tools as T

    registered = set(T.tool_registry.list_names())
    advertised = set(T.SCHEMAS_BY_NAME)
    assert registered == advertised, (
        f"only registered: {registered - advertised}; only advertised: {advertised - registered}"
    )


# --- Stage C: grep / glob robustness -------------------------------------------

async def test_grep_finds_matches(project, monkeypatch):
    from tonyagent.tools.search_tools import GrepTool

    (project / "a.py").write_text("alpha\nneedle here\nbeta\n", encoding="utf-8")
    r = await GrepTool().execute("needle")
    assert r.status is ToolResultStatus.SUCCESS
    assert "a.py:2" in r.output
    assert "needle here" in r.output


async def test_grep_context_lines(project, monkeypatch):
    from tonyagent.tools.search_tools import GrepTool

    (project / "ctx.py").write_text("l1\nl2\nNEEDLE\nl4\nl5\n", encoding="utf-8")
    r = await GrepTool().execute("NEEDLE", context_lines=1)
    assert r.status is ToolResultStatus.SUCCESS
    assert "> 3: NEEDLE" in r.output   # match marked
    assert "  2: l2" in r.output        # one line before
    assert "  4: l4" in r.output        # one line after


async def test_grep_respects_max_results(project, monkeypatch):
    from tonyagent.tools.search_tools import GrepTool

    (project / "many.txt").write_text("hit\n" * 500, encoding="utf-8")
    r = await GrepTool().execute("hit", max_results=10)
    assert r.status is ToolResultStatus.SUCCESS
    assert "Found 10 matches" in r.output
    assert "truncated" in r.output.lower()


async def test_grep_skips_oversized_files(project, monkeypatch):
    """A huge file must be skipped, not read into memory."""
    from tonyagent.tools.search_tools import GrepTool

    # 3MB of matches; default cap is 10MB so force it with max_filesize_mb=1.
    (project / "huge.log").write_text("needle\n" * 300_000, encoding="utf-8")
    r = await GrepTool().execute("needle", max_filesize_mb=1)
    assert r.status is ToolResultStatus.SUCCESS
    assert "Found 0 matches" in r.output
    assert "skipped over size limit" in r.output


async def test_grep_handles_invalid_regex(project, monkeypatch):
    from tonyagent.tools.search_tools import GrepTool

    r = await GrepTool().execute("[unclosed")
    assert r.status is ToolResultStatus.ERROR
    assert "Invalid regex" in r.error


async def test_grep_case_insensitive(project, monkeypatch):
    from tonyagent.tools.search_tools import GrepTool

    (project / "ci.txt").write_text("Needle\n", encoding="utf-8")
    assert "Found 0 matches" in (await GrepTool().execute("needle")).output
    r = await GrepTool().execute("needle", case_sensitive=False)
    assert "Found 1 matches" in r.output


async def test_glob_respects_max_results(project, monkeypatch):
    from tonyagent.tools.search_tools import GlobTool

    for i in range(60):
        (project / f"f{i}.py").write_text("x", encoding="utf-8")
    r = await GlobTool().execute("**/*.py", max_results=10)
    assert r.status is ToolResultStatus.SUCCESS
    assert "Found 10 files" in r.output
    assert "truncated" in r.output.lower()


async def test_glob_empty_message_is_correct(project, monkeypatch):
    """The old one-liner reported a bogus count on the empty path."""
    from tonyagent.tools.search_tools import GlobTool

    r = await GlobTool().execute("**/*.nothing")
    assert r.status is ToolResultStatus.SUCCESS
    assert r.output == "No matches found"
    assert "Found" not in r.output


async def test_glob_nonempty_message_has_no_bogus_count(project, monkeypatch):
    from tonyagent.tools.search_tools import GlobTool

    (project / "only.py").write_text("x", encoding="utf-8")
    r = await GlobTool().execute("**/*.py")
    assert r.output.startswith("Found 1 files")
    assert "only.py" in r.output


def test_search_schemas_match_tool_signatures():
    """grep/glob gained params - the advertised schema must not lag behind."""
    import tonyagent.tools as T

    grep_schema = T.SCHEMAS_BY_NAME["grep"]["parameters"]["properties"]
    assert "context_lines" in grep_schema
    assert "max_filesize_mb" in grep_schema
    glob_schema = T.SCHEMAS_BY_NAME["glob"]["parameters"]["properties"]
    assert "max_results" in glob_schema


# --- Stage D: new browser tools ------------------------------------------------

class BrowserToolBackend(FakeBackend):
    """Answers the three new browser RPCs like the real container would."""

    def __init__(self, text="Page body text", fail=None, scroll_delta=800):
        super().__init__(enable_network=True)
        self.text = text
        self.fail = fail
        self.scroll_delta = scroll_delta

    async def browser_get_text(self, selector="", max_chars=20000):
        from tonyagent.sandbox.base import BrowserResult

        if self.fail:
            return BrowserResult(success=False, error=self.fail)
        if selector == "#missing":
            return BrowserResult(success=False, error="No element matches selector: #missing")
        body = self.text if not selector else f"text of {selector}"
        cap = max(100, min(int(max_chars or 20000), 200000))
        return BrowserResult(
            success=True,
            data={
                "text": body[:cap],
                "length": len(body),
                "truncated": len(body) > cap,
                "url": "https://example.com/",
                "title": "Example Domain",
            },
        )

    async def browser_wait_for(self, selector="", state="visible", timeout=10000):
        from tonyagent.sandbox.base import BrowserResult

        if self.fail:
            return BrowserResult(success=False, error=self.fail)
        return BrowserResult(success=True, data={"selector": selector, "state": state})

    async def browser_scroll(self, direction="down", amount=800, selector=""):
        from tonyagent.sandbox.base import BrowserResult

        if self.fail:
            return BrowserResult(success=False, error=self.fail)
        delta = self.scroll_delta if direction == "down" else 0
        return BrowserResult(
            success=True,
            data={"direction": direction, "amount": amount, "scrolled": delta, "position": delta},
        )


@pytest.fixture
def browser_tools_backend():
    manager = get_shared_sandbox_manager()
    backend = BrowserToolBackend()
    manager._backend = backend
    yield backend
    manager._backend = None


async def test_browser_get_text_returns_page_text(browser_tools_backend):
    from tonyagent.tools.browser_tools import BrowserGetTextTool

    r = await BrowserGetTextTool().execute()
    assert r.status is ToolResultStatus.SUCCESS
    assert "Page body text" in r.output


async def test_browser_get_text_scopes_to_selector(browser_tools_backend):
    from tonyagent.tools.browser_tools import BrowserGetTextTool

    r = await BrowserGetTextTool().execute("#main")
    assert r.status is ToolResultStatus.SUCCESS
    assert "text of #main" in r.output


async def test_browser_get_text_flags_truncation(browser_tools_backend):
    from tonyagent.tools.browser_tools import BrowserGetTextTool

    browser_tools_backend.text = "A" * 5000
    r = await BrowserGetTextTool().execute(max_chars=200)
    assert r.status is ToolResultStatus.SUCCESS
    assert "truncated" in r.output.lower()


async def test_browser_get_text_surfaces_missing_selector(browser_tools_backend):
    from tonyagent.tools.browser_tools import BrowserGetTextTool

    r = await BrowserGetTextTool().execute("#missing")
    assert r.status is ToolResultStatus.ERROR
    assert "No element matches" in r.error


async def test_browser_wait_for_requires_selector_or_load_state(browser_tools_backend):
    from tonyagent.tools.browser_tools import BrowserWaitForTool

    r = await BrowserWaitForTool().execute(selector="", state="visible")
    assert r.status is ToolResultStatus.ERROR
    assert "CSS selector" in r.error


async def test_browser_wait_for_accepts_selector(browser_tools_backend):
    from tonyagent.tools.browser_tools import BrowserWaitForTool

    r = await BrowserWaitForTool().execute("#ready", state="visible", timeout=5000)
    assert r.status is ToolResultStatus.SUCCESS
    assert "visible" in r.output


async def test_browser_wait_for_accepts_load_state_without_selector(browser_tools_backend):
    from tonyagent.tools.browser_tools import BrowserWaitForTool

    r = await BrowserWaitForTool().execute(state="networkidle")
    assert r.status is ToolResultStatus.SUCCESS
    assert "the page" in r.output


async def test_browser_scroll_reports_movement(browser_tools_backend):
    from tonyagent.tools.browser_tools import BrowserScrollTool

    r = await BrowserScrollTool().execute(direction="down", amount=800)
    assert r.status is ToolResultStatus.SUCCESS
    assert "Scrolled down" in r.output
    assert "800px" in r.output


async def test_new_browser_tools_need_no_confirmation(browser_tools_backend):
    """Reading and waiting must not interrupt the user; they cannot mutate state."""
    import tonyagent.tools as T

    for name in ("browser_get_text", "browser_wait_for", "browser_scroll"):
        tool = T.tool_registry.get(name)
        assert tool is not None, f"{name} not registered"
        assert tool.destructive is False
        assert tool.requires_confirmation is False
        assert tool.sandbox_required is True


async def test_new_browser_tools_fail_closed_without_backend():
    from tonyagent.tools.browser_tools import (
        BrowserGetTextTool,
        BrowserScrollTool,
        BrowserWaitForTool,
    )

    get_shared_sandbox_manager()._backend = None
    for tool in (BrowserGetTextTool(), BrowserWaitForTool(), BrowserScrollTool()):
        r = await tool.execute()
        assert r.status is ToolResultStatus.ERROR
        assert "sandbox" in r.error.lower()


def test_browser_schemas_match_new_tools():
    import tonyagent.tools as T

    for name, prop in (
        ("browser_get_text", "max_chars"),
        ("browser_wait_for", "state"),
        ("browser_scroll", "direction"),
    ):
        props = T.SCHEMAS_BY_NAME[name]["parameters"]["properties"]
        assert prop in props, f"{name} schema missing {prop}"


def test_rpc_server_registers_new_methods():
    """The methods live in the IMAGE - a missing entry means Method not found."""
    import ast
    from pathlib import Path

    tree = ast.parse(Path("docker/sandbox/rpc_server.py").read_text(encoding="utf-8"))
    registered = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "METHODS":
            registered = {k.value for k in node.value.keys}
    for m in ("browser_get_text", "browser_wait_for", "browser_scroll"):
        assert m in registered, f"{m} not in METHODS dispatch table"


# --- browser_snapshot / set_viewport_size -------------------------------------

class SnapshotBackend(FakeBackend):
    def __init__(self, elements=None, aria="- heading \"Example Domain\"", fail=None):
        super().__init__(enable_network=True)
        self.elements = elements if elements is not None else [
            {"selector": "h1", "tag": "h1", "role": "", "type": "", "name": "Example Domain", "disabled": False},
            {"selector": "#more", "tag": "a", "role": "", "type": "", "name": "More information...", "disabled": False},
            {"selector": "#go", "tag": "button", "role": "", "type": "submit", "name": "Go", "disabled": True},
        ]
        self.aria = aria
        self.fail = fail
        self.last_args = None

    async def browser_snapshot(self, interactive_only=True, max_elements=100):
        from tonyagent.sandbox.base import BrowserResult

        self.last_args = (interactive_only, max_elements)
        if self.fail:
            return BrowserResult(success=False, error=self.fail)
        return BrowserResult(
            success=True,
            data={
                "url": "https://example.com/",
                "title": "Example Domain",
                "elements": self.elements,
                "element_count": len(self.elements),
                "truncated": len(self.elements) >= max_elements,
                "aria": self.aria,
            },
        )

    async def set_viewport_size(self, width=1280, height=720, reset=False):
        from tonyagent.sandbox.base import BrowserResult

        if self.fail:
            return BrowserResult(success=False, error=self.fail)
        if reset:
            return BrowserResult(success=True, data={"reset": True, "width": 1280, "height": 720})
        return BrowserResult(success=True, data={"width": width, "height": height})


@pytest.fixture
def snapshot_backend():
    manager = get_shared_sandbox_manager()
    backend = SnapshotBackend()
    manager._backend = backend
    yield backend
    manager._backend = None


async def test_snapshot_lists_selectors_and_names(snapshot_backend):
    """The whole point: a text model can see what is clickable and how to click it."""
    from tonyagent.tools.browser_tools import BrowserSnapshotTool

    r = await BrowserSnapshotTool().execute()
    assert r.status is ToolResultStatus.SUCCESS
    assert "Example Domain" in r.output          # title
    assert "#more" in r.output                   # ready-to-use selector
    assert "More information" in r.output        # accessible name
    assert "disabled" in r.output                # state is visible


async def test_snapshot_includes_aria_outline(snapshot_backend):
    from tonyagent.tools.browser_tools import BrowserSnapshotTool

    r = await BrowserSnapshotTool().execute()
    assert "ARIA outline" in r.output
    assert "heading" in r.output


async def test_snapshot_handles_empty_page(snapshot_backend):
    from tonyagent.tools.browser_tools import BrowserSnapshotTool

    snapshot_backend.elements = []
    snapshot_backend.aria = ""
    r = await BrowserSnapshotTool().execute()
    assert r.status is ToolResultStatus.SUCCESS
    assert "no interactive elements" in r.output.lower()


async def test_snapshot_reports_no_page(snapshot_backend):
    from tonyagent.tools.browser_tools import BrowserSnapshotTool

    snapshot_backend.fail = "No page open. Call browser_navigate first."
    r = await BrowserSnapshotTool().execute()
    assert r.status is ToolResultStatus.ERROR
    assert "navigate" in r.error


async def test_snapshot_passes_through_params(snapshot_backend):
    from tonyagent.tools.browser_tools import BrowserSnapshotTool

    await BrowserSnapshotTool().execute(interactive_only=False, max_elements=5)
    assert snapshot_backend.last_args == (False, 5)


async def test_set_viewport_size(snapshot_backend):
    from tonyagent.tools.browser_tools import SetViewportSizeTool

    r = await SetViewportSizeTool().execute(width=390, height=844)
    assert r.status is ToolResultStatus.SUCCESS
    assert "390x844" in r.output


async def test_set_viewport_size_reset(snapshot_backend):
    from tonyagent.tools.browser_tools import SetViewportSizeTool

    r = await SetViewportSizeTool().execute(reset=True)
    assert r.status is ToolResultStatus.SUCCESS
    assert "reset" in r.output.lower()


async def test_snapshot_tools_need_no_confirmation(snapshot_backend):
    import tonyagent.tools as T

    for name in ("browser_snapshot", "set_viewport_size"):
        tool = T.tool_registry.get(name)
        assert tool is not None, f"{name} not registered"
        assert tool.destructive is False
        assert tool.requires_confirmation is False
        assert tool.sandbox_required is True


async def test_snapshot_tools_fail_closed_without_backend():
    from tonyagent.tools.browser_tools import BrowserSnapshotTool, SetViewportSizeTool

    get_shared_sandbox_manager()._backend = None
    for tool in (BrowserSnapshotTool(), SetViewportSizeTool()):
        r = await tool.execute()
        assert r.status is ToolResultStatus.ERROR
        assert "sandbox" in r.error.lower()


def test_rpc_server_registers_snapshot_methods():
    """Image-bound: a missing entry means Method not found at runtime."""
    import ast
    from pathlib import Path

    tree = ast.parse(Path("docker/sandbox/rpc_server.py").read_text(encoding="utf-8"))
    registered = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "METHODS":
            registered = {k.value for k in node.value.keys}
    for m in ("browser_snapshot", "set_viewport_size", "browser_get_text",
              "browser_wait_for", "browser_scroll", "read_file", "list_files"):
        assert m in registered, f"{m} missing from METHODS"


def test_snapshot_schemas_advertised():
    import tonyagent.tools as T

    for name, prop in (("browser_snapshot", "max_elements"),
                       ("set_viewport_size", "width")):
        assert name in T.SCHEMAS_BY_NAME
        assert prop in T.SCHEMAS_BY_NAME[name]["parameters"]["properties"]


# --- Regression: streaming contract mismatch (no reply for OpenAI family) -----

class _AsyncGenProvider:
    """Shape 1: a true async generator (Anthropic / Gemini / Ollama)."""

    async def chat_completion(self, messages, tools=None, tool_choice=None, stream=False, **kw):
        for piece in ("Hel", "lo ", "world"):
            yield ChatCompletionChunk(content=piece)


class _CoroGenProvider:
    """Shape 2: a coroutine that returns an async generator (OpenAI family)."""

    async def chat_completion(self, messages, tools=None, tool_choice=None, stream=False, **kw):
        async def gen():
            for piece in ("Hel", "lo ", "world"):
                yield ChatCompletionChunk(content=piece)

        return gen()


class _CoroOnceProvider:
    """Shape 3: a coroutine that returns one non-streaming completion."""

    async def chat_completion(self, messages, tools=None, tool_choice=None, stream=False, **kw):
        return ChatCompletion(content="Hello world", finish_reason="stop", model="m")


def _make_window(provider):
    """A MainWindow stand-in exposing just the chunk normaliser."""
    from tonyagent.ui.views.main_window import MainWindow

    win = MainWindow.__new__(MainWindow)
    win._current_provider = provider
    win._message_history = []
    return win


@pytest.mark.parametrize(
    "provider_cls", [_AsyncGenProvider, _CoroGenProvider, _CoroOnceProvider]
)
async def test_iter_provider_chunks_handles_every_shape(provider_cls):
    """Regression: 'async for' got a coroutine -> no reply for openrouter/groq/...

    The UI iterated provider.chat_completion() directly. That works only when the
    method is a true async generator; the OpenAI-compatible family returns a
    coroutine, so every message silently produced
    "'async for' requires an object with __aiter__ method, got coroutine".
    """
    win = _make_window(provider_cls())
    text = "".join([c.content or "" async for c in win._iter_provider_chunks(None)])
    assert text == "Hello world"


async def test_old_direct_iteration_pattern_was_broken():
    """Documents exactly why the helper exists."""
    for provider_cls in (_CoroGenProvider, _CoroOnceProvider):
        with pytest.raises(TypeError, match="__aiter__"):
            async for _ in provider_cls().chat_completion(messages=[]):
                pass


async def test_iter_provider_chunks_yields_tool_calls():
    """A tool-call-only response must not be dropped as empty."""

    class ToolOnly:
        async def chat_completion(self, messages, tools=None, tool_choice=None, stream=False, **kw):
            return ChatCompletion(
                content=None,
                tool_calls=[{"id": "c1", "type": "function",
                             "function": {"name": "read_file", "arguments": "{}"}}],
                finish_reason="tool_calls", model="m",
            )

    win = _make_window(ToolOnly())
    chunks = [c async for c in win._iter_provider_chunks(None)]
    assert len(chunks) == 1
    assert chunks[0].tool_calls


async def test_iter_provider_chunks_handles_empty_response():
    class Empty:
        async def chat_completion(self, messages, tools=None, tool_choice=None, stream=False, **kw):
            return ChatCompletion(content=None, finish_reason="stop", model="m")

    win = _make_window(Empty())
    assert [c async for c in win._iter_provider_chunks(None)] == []


def test_ui_does_not_iterate_chat_completion_directly():
    """Guard both the UI and the core against the raw form coming back.

    The turn loop now lives in ``AgentSession``. The UI delegates to it, so
    neither file may call ``chat_completion`` in the broken raw form - that form
    raised "'async for' requires an object with __aiter__, got coroutine" for
    every OpenAI-compatible provider.
    """
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    ui = (root / "src/tonyagent/ui/views/main_window.py").read_text(encoding="utf-8")
    core = (root / "src/tonyagent/core/session.py").read_text(encoding="utf-8")

    assert "async for chunk in self._current_provider.chat_completion" not in ui
    # The UI must not call the provider directly at all; it goes through the
    # session, which owns the only implementation.
    assert ".chat_completion(" not in ui, "the UI must not drive the provider"
    # Exactly one implementation of the normalisation exists, in the core.
    assert core.count("_iter_chunks") >= 2
    assert "chat_completion(" in core
