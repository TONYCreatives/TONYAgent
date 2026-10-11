"""The Docker-free runtime, and the line between it and real isolation.

The 22 tool schemas are hand-written dicts in ``schemas.py`` that duplicate
flags declared on the Tool classes. That duplication is a drift hazard: a tool
can be marked ``sandbox_required`` on its class and not in its schema, and
nothing complains until a tool silently runs somewhere it should not. These
tests pin the two together, and pin the behaviour that actually matters -- that
having no Docker daemon costs the agent two tools, not twenty.
"""

from __future__ import annotations

from pathlib import Path

from tonyagent.sandbox.base import SandboxConfig, SandboxManager, SandboxStatus
from tonyagent.tools.base import ToolCategory, tool_registry
from tonyagent.tools.schemas import ALL_SCHEMAS, SCHEMAS_BY_NAME


# --- the advertised schemas are the registry, and stay that way -------------
#
# These used to be *parity* tests. ``schemas.py`` was a second, hand-written copy
# of every tool's declaration, and the tests that lived here compared that copy
# against the classes to catch drift.
#
# That whole class of bug is gone: the schemas are now derived from the registry
# (``Tool.describe``), so a test comparing the two would be comparing a thing to
# itself and would pass no matter what either one said. What can still break is
# the *derivation*, and the tests below are the ways it can.


def _registered_tools() -> dict:
    # Importing the tool modules is what populates the registry.
    import tonyagent.tools  # noqa: F401
    import tonyagent.tools.browser_tools  # noqa: F401
    import tonyagent.tools.file_tools  # noqa: F401
    import tonyagent.tools.network_tools  # noqa: F401
    import tonyagent.tools.sandbox_file_tools  # noqa: F401
    import tonyagent.tools.search_tools  # noqa: F401
    import tonyagent.tools.shell_tools  # noqa: F401

    tools = tool_registry.get_all()
    return {t.name: t for t in tools}


#: Every field a descriptor has to carry. A tool missing one is a tool the window
#: cannot describe and the orchestrator cannot gate.
#:
#: This is a floor, not an equality: a descriptor may carry more. `folder_required`
#: was added when `web_fetch` made the orchestrator's `!= "http_request"` special
#: case untenable, and adding it here is what makes the next flag a deliberate
#: decision rather than an omission nobody notices.
_DESCRIPTOR_FIELDS = frozenset({
    "name",
    "description",
    "parameters",
    "category",
    "destructive",
    "requires_confirmation",
    "sandbox_required",
    "isolation_required",
    "folder_required",
})


def test_the_registry_is_populated_before_the_schemas_are_read():
    """The import-order hazard the derivation introduced.

    ``ALL_SCHEMAS`` is built from the registry on first access, so reading it
    before ``tonyagent.tools`` has imported the tool modules binds an empty list.
    An empty tool list raises nothing anywhere -- it is a model offered no tools
    at all, which presents as a model that simply refuses to act.
    """
    registered = set(_registered_tools())
    assert registered, "no tools registered at all"
    assert set(SCHEMAS_BY_NAME) == registered
    assert len(ALL_SCHEMAS) == len(registered)


def test_every_descriptor_carries_the_full_field_set():
    """A missing flag is a tool nothing can gate.

    ``describe`` emits all four flags even when they are False precisely so this
    holds. The hand-written schemas it replaced omitted the false ones, which
    made "absent" and "false" look identical to a reader and let a new tool leave
    one out without anything noticing.
    """
    incomplete = {
        name: sorted(_DESCRIPTOR_FIELDS - set(schema))
        for name, schema in SCHEMAS_BY_NAME.items()
        if not _DESCRIPTOR_FIELDS <= set(schema)
    }
    assert not incomplete, f"descriptors missing fields: {incomplete}"


def test_every_descriptor_advertises_a_complete_json_schema():
    """``parameters`` must be a whole JSON Schema, not a bare properties map.

    This is the shape that has to reach the provider: the model reads
    ``parameters["properties"]`` for its argument names. A bare properties map
    here would be re-wrapped correctly downstream, so the mistake would stay
    hidden until the model could not name a single argument.
    """
    bad = []
    for name, schema in SCHEMAS_BY_NAME.items():
        parameters = schema.get("parameters") or {}
        if parameters.get("type") != "object":
            bad.append(f"{name}: parameters.type is {parameters.get('type')!r}")
        if not isinstance(parameters.get("properties"), dict):
            bad.append(f"{name}: no properties map")
        for keyword in ("type", "properties", "required", "additionalProperties"):
            if keyword in (parameters.get("properties") or {}):
                bad.append(f"{name}: {keyword!r} nested as a parameter name")
    assert not bad, "\n".join(bad)


def test_every_descriptor_names_a_real_category():
    """``category`` is documented as driving UI filtering, so a string is not enough."""
    bad = [
        f"{name}: {schema.get('category')!r}"
        for name, schema in SCHEMAS_BY_NAME.items()
        if not isinstance(schema.get("category"), ToolCategory)
    ]
    assert not bad, f"descriptors without a ToolCategory: {bad}"


def test_describe_and_get_schema_agree_on_the_wrapping():
    """The two conversions must not disagree about where ``properties`` lives.

    ``describe`` is the flat declaration; ``get_schema`` is the OpenAI-wrapped
    one. ``get_schema`` used to wrap an already-complete schema a *second* time,
    advertising a single parameter named ``type``. Nothing called it, which is
    the only reason that never reached a model. Pinned so the next caller
    inherits working code.
    """
    for name, tool in _registered_tools().items():
        wrapped = tool.get_schema()["function"]["parameters"]
        assert set(wrapped.get("properties") or {}) == set(
            tool.parameters.get("properties") or {}
        ), f"{name}: get_schema and parameters disagree about the argument names"


def test_every_tool_documents_itself():
    """A tool class should say what it does.

    This is now the *only* place a description can come from, which is what makes
    it worth asserting: the description the model reads is ``Tool.description``,
    so a tool with no docstring and no description is a tool the model is shown
    with nothing explaining it. (This test predates the derivation and was the
    reason the hand-written schemas looked like the only description there was.)
    """
    undocumented = sorted(
        name for name, tool in _registered_tools().items()
        if not (tool.__doc__ or "").strip()
    )
    assert not undocumented, f"tools with no docstring: {undocumented}"


def test_only_code_execution_requires_isolation():
    """Exactly the two tools that run arbitrary code are gated.

    This is the assertion that keeps the Docker dependency from creeping back:
    a new tool should have to argue for itself to land on the isolated list.
    """
    gated = {s["name"] for s in ALL_SCHEMAS if s.get("isolation_required")}
    assert gated == {"execute_command", "execute_js"}


# --- the local runtime itself ------------------------------------------------


def test_detection_falls_back_to_local_when_docker_is_down(monkeypatch):
    """With no containing backend, detection must still return a usable answer.

    It used to return "docker" unconditionally here, which made a Docker-less
    machine look like a Docker problem instead of a supported configuration.
    """
    import asyncio

    import builtins

    real_import = builtins.__import__

    def no_docker(name, *args, **kwargs):
        if name == "docker":
            raise ImportError("no docker in this test")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_docker)
    monkeypatch.setattr("subprocess.run", lambda *a, **k: type(
        "R", (), {"stdout": "", "returncode": 740}
    )())

    assert asyncio.run(SandboxManager._detect_backend()) == "local"


def test_manager_start_reports_running_without_isolation(tmp_path: Path):
    """`start` succeeds on a machine with no daemon, and does not overclaim."""
    import asyncio

    manager = SandboxManager()
    ok = asyncio.run(manager.start(SandboxConfig(project_path=str(tmp_path), type="local")))
    try:
        assert ok is True
        assert manager.is_running() is True
        assert manager.is_isolated() is False
    finally:
        asyncio.run(manager.stop())


def test_local_backend_does_not_claim_isolation():
    from tonyagent.sandbox.local_backend import LocalBackend

    assert LocalBackend.provides_isolation is False


def test_docker_backend_claims_isolation():
    from tonyagent.sandbox.docker_backend import DockerSandboxBackend

    assert DockerSandboxBackend.provides_isolation is True


def test_manager_exposes_isolation_separately_from_running(tmp_path: Path):
    """A live runtime is not the same claim as a contained one."""
    manager = SandboxManager()
    manager._config = SandboxConfig(project_path=str(tmp_path))
    # Nothing started yet, so both claims are false.
    assert manager.get_runtime_backend() is None
    assert manager.is_running() is False
    assert manager.is_isolated() is False


def test_get_backend_does_not_fall_back_to_the_local_runtime():
    """The isolating accessor must stay isolating.

    If this ever returned the local backend, execute_command would run
    model-authored shell on the host while looking like it was sandboxed.
    """
    manager = SandboxManager()
    assert manager.get_backend() is None


def test_ensure_local_starts_a_usable_runtime(tmp_path: Path):
    """The whole point: a real runtime with no Docker daemon anywhere."""
    import asyncio

    import tonyagent.folder as folder_pkg

    manager = SandboxManager()
    cfg = SandboxConfig(project_path=str(tmp_path))
    ok = asyncio.run(manager.ensure_local(cfg))
    try:
        assert ok is True
        backend = manager.get_local_backend()
        assert backend is not None
        assert backend.status is SandboxStatus.RUNNING
        # It is reachable as a runtime, and refused as an isolation boundary.
        assert manager.get_runtime_backend() is backend
        assert manager.is_running() is True
        assert manager.is_isolated() is False
    finally:
        asyncio.run(manager.stop())
    assert manager.get_runtime_backend() is None


def test_local_runtime_serves_the_read_only_file_tools(tmp_path: Path):
    """End to end over the real in-process handler, with no container."""
    import asyncio

    from tonyagent.sandbox.local_backend import LocalBackend

    (tmp_path / "note.txt").write_text("local runtime works", encoding="utf-8")
    backend = LocalBackend(SandboxConfig(project_path=str(tmp_path)))

    async def go():
        assert await backend.start() is True
        assert await backend.health_check() is True
        read = await backend.read_file("note.txt")
        listed = await backend.list_files(".")
        await backend.stop()
        return read, listed

    read, listed = asyncio.run(go())
    assert "local runtime works" in str(read.data)
    assert "note.txt" in str(listed.data)


def test_local_runtime_refuses_paths_outside_the_workspace(tmp_path: Path):
    """The workspace boundary must survive being pointed at a real folder.

    Pointed at a genuine directory rather than a container path, this is the
    check that stops a model mistake from reading the user's SSH keys.
    """
    import asyncio

    from tonyagent.sandbox.local_backend import LocalBackend

    (tmp_path.parent / "escaped.txt").write_text("secret", encoding="utf-8")
    backend = LocalBackend(SandboxConfig(project_path=str(tmp_path)))

    async def go():
        assert await backend.start() is True
        try:
            return await backend.read_file("../escaped.txt")
        finally:
            await backend.stop()

    result = asyncio.run(go())
    assert result.success is False
    assert "escape" in (result.error or "").lower()


def test_local_runtime_needs_a_project_folder(monkeypatch):
    """No folder means no runtime, and the message says so.

    The folder is cleared explicitly rather than relying on there being none:
    folder_manager is process-global, so other tests having set it would
    otherwise make this one pass or fail depending on ordering.
    """
    import asyncio

    from tonyagent.folder import folder_manager
    from tonyagent.sandbox.local_backend import LocalBackend

    monkeypatch.setattr(folder_manager, "_current_folder", None)
    backend = LocalBackend(SandboxConfig(project_path=""))
    assert asyncio.run(backend.start()) is False
    assert backend.status is SandboxStatus.STOPPED


# --- the code-execution tools stay shut without a container ------------------


def test_execute_command_refuses_to_run_on_the_local_runtime(tmp_path: Path, monkeypatch):
    """The one guarantee that must never regress.

    With only the local runtime up, execute_command has to refuse -- not fall
    back to the host, and not report success.
    """
    import asyncio

    from tonyagent.sandbox import get_shared_sandbox_manager
    from tonyagent.sandbox.local_backend import LocalBackend
    from tonyagent.tools.shell_tools import ExecuteCommandTool

    manager = get_shared_sandbox_manager()
    local = LocalBackend(SandboxConfig(project_path=str(tmp_path)))
    assert asyncio.run(local.start()) is True
    monkeypatch.setattr(manager, "_local", local, raising=False)
    try:
        result = asyncio.run(ExecuteCommandTool().execute("python --version"))
        assert result.status.value == "error"
        assert "isolated sandbox" in (result.error or "").lower()
    finally:
        asyncio.run(manager.stop())


def test_no_tool_claims_confirmation_without_destructive():
    """A ``requires_confirmation`` flag that the gate will never fire on is inert.

    ``_needs_confirmation`` holds the prompt behind ``destructive and
    requires_confirmation``, so a tool declaring ``requires_confirmation = True``
    while ``destructive = False`` describes a question that is never asked. Six
    of them did exactly that, and the flags were dropped from those
    declarations rather than the gate widened -- see the comment on the
    ``browser_click``/``browser_type`` pair in ``browser_tools.py`` for why the
    gate is not the thing to change.

    This is the pin that keeps a seventh from joining them, and it is the
    registry-reading form NEXT_SESSION recorded precisely because counting
    them from memory missed one.
    """
    inert = {
        name for name, tool in _registered_tools().items()
        if tool.requires_confirmation and not tool.destructive
    }
    assert not inert, f"requires_confirmation that can never fire: {sorted(inert)}"


def test_execute_js_refuses_to_run_on_the_local_runtime(tmp_path: Path, monkeypatch):
    import asyncio

    from tonyagent.sandbox import get_shared_sandbox_manager
    from tonyagent.sandbox.local_backend import LocalBackend
    from tonyagent.tools.browser_tools import ExecuteJsTool

    manager = get_shared_sandbox_manager()
    local = LocalBackend(SandboxConfig(project_path=str(tmp_path)))
    assert asyncio.run(local.start()) is True
    monkeypatch.setattr(manager, "_local", local, raising=False)
    try:
        result = asyncio.run(ExecuteJsTool().execute("1+1"))
        assert result.status.value == "error"
        assert "isolated" in (result.error or "").lower()
    finally:
        asyncio.run(manager.stop())


async def test_execute_js_keeps_the_denylist_on_the_host(tmp_path: Path, monkeypatch):
    """At Full the host is the runtime -- so the one filter stays.

    Without this, the only model-authored-code tool that never prompts was
    also the only one with no filter at all: ``execute_command`` still faces
    the denylist at Full, and handing ``execute_js`` the same machine asked
    for the same answer. It is the cheap inner ring, not a parser -- ordinary
    JavaScript never matches it.
    """
    from tonyagent.core.modes import PERMISSIONS
    from tonyagent.sandbox import get_shared_sandbox_manager
    from tonyagent.sandbox.local_backend import LocalBackend
    from tonyagent.tools.browser_tools import ExecuteJsTool
    from tonyagent.tools.context import use_context

    manager = get_shared_sandbox_manager()
    local = LocalBackend(SandboxConfig(project_path=str(tmp_path)))
    assert await local.start() is True
    monkeypatch.setattr(manager, "_local", local, raising=False)
    try:
        with use_context(permission=PERMISSIONS["full"]):
            destructive = await ExecuteJsTool().execute(
                "require('child_process').execSync('rm -rf /')"
            )
            assert destructive.status.value == "error"
            assert "denylist" in (destructive.error or "").lower()

            # The control: the pattern must not fire on arithmetic. A string
            # that *spells* a destructive command is denied, deliberately --
            # the same trade the denylist makes on command strings
            # (``echo "rm -rf /"`` is refused too), because normalisation
            # removes quotes and there is no parser underneath.
            result = await ExecuteJsTool().execute("1+1")
            assert "denylist" not in (result.error or "").lower(), (
                "ordinary JavaScript was denied as destructive"
            )
    finally:
        await manager.stop()


async def test_execute_js_is_not_denylisted_inside_a_container(tmp_path: Path, monkeypatch):
    """The scoping decision, pinned: the denylist is the *host* ring.

    Inside an isolating backend the container is the wall -- the same trade
    ``execute_command`` makes, where the pattern list is a courtesy rather
    than the boundary -- and a pattern that blocked JavaScript containing an
    ``rm -rf`` string would push real work around the filter for no gain.
    """
    from tonyagent.core.modes import PERMISSIONS
    from tonyagent.sandbox import get_shared_sandbox_manager
    from tonyagent.sandbox.base import SandboxConfig, SandboxStatus
    from tonyagent.tools.browser_tools import ExecuteJsTool
    from tonyagent.tools.context import use_context

    class IsolatingBackend:
        provides_isolation = True
        status = SandboxStatus.RUNNING
        config = SandboxConfig()

        async def execute_js(self, script: str, timeout: int = 10):
            return type("R", (), {"success": True, "data": "ran", "error": None})()

    manager = get_shared_sandbox_manager()
    monkeypatch.setattr(manager, "_backend", IsolatingBackend())
    try:
        with use_context(permission=PERMISSIONS["full"]):
            result = await ExecuteJsTool().execute("require('fs').rmSync('/x', {recursive:true})")
        assert result.status.value == "success", result.error
    finally:
        monkeypatch.setattr(manager, "_backend", None)
