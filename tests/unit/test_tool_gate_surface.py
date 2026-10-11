"""The whole registered surface, swept through the orchestrator.

**Why a sweep, when each gate already has a test.** Every other gate test names
the tool it is about: ``test_confirmation_contract.py`` drives ``delete_file``,
``test_local_sandbox.py`` drives ``execute_command``, ``test_modes_and_diffs.py``
drives the pair a mode change is about. That is the right shape for a claim about
a *tool* and the wrong shape for a claim about the *surface*: a tool added
tomorrow that no mode refuses, a permission set that quietly disagrees with the
mode set, or a tool whose path parameter is never confined, is invisible to all
of them. This file asks every question of every tool, by iterating the registry,
so the answer cannot depend on somebody having remembered to write the test.

Three properties make the sweep honest rather than decorative:

* **It counts what it swept.** The refusal tables below are written out by hand
  rather than read off ``Mode.allowed_tools`` -- a sweep that asks the gate what
  the gate should say agrees with every change to the gate. The path sweep
  asserts which tools it reached, so a renamed parameter cannot silently shrink
  it, and the destructive/sandbox sets are asserted, so a tool joining one is a
  diff somebody reads.
* **"Refused" is measured as "the body never ran."** Each tool's ``execute`` is
  replaced by a recorder for the duration of a test, so a gate that refuses
  *after* the tool has already done its work fails here the same way the
  original confirmation hole did.
* **The dangerous cases are also measured for real effect** -- a file that
  survives a denied delete, a planted file that was never created, a command
  that never reached the host -- because a recorder only proves what the
  orchestrator did, not what the machine did.

The environment is forced where the machine's own state would decide the
outcome: a running Docker would answer the sandbox questions for us, so
``_no_runtime`` empties the shared manager first and every refusal below is the
gate's own.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import pytest

import tonyagent.tools  # noqa: F401  -- importing registers every tool
from tonyagent.core.modes import MODES, PERMISSIONS, get_mode, get_permission
from tonyagent.folder.manager import folder_manager
from tonyagent.sandbox import get_shared_sandbox_manager
from tonyagent.tools import tool_registry
from tonyagent.tools.base import ToolResult, ToolResultStatus
from tonyagent.tools.orchestrator import CONFIRMATION_TIMEOUT_S, ToolCall, ToolOrchestrator
from tonyagent.tools.shell_tools import NO_RUNTIME

#: What each mode must refuse, written out. Same spirit as the tool-count
#: tripwire in ``test_user_questions.py``: 41 tools, and the day one of them
#: stops being refused by Plan -- or a new write-shaped tool joins without
#: being added here -- this list is what makes that a decision rather than a
#: discovery.
REFUSED_BY_MODE: dict[str, set[str]] = {
    "build": set(),
    "mission": {"take_screenshot"},
    "plan": {
        "delete_file", "edit", "execute_command", "http_request", "job_kill",
        "send_message", "subagent", "subagent_fork", "take_screenshot",
        "web_fetch", "write",
    },
    "skills": {
        "delete_file", "edit", "execute_command", "http_request", "job_kill",
        "send_message", "subagent", "subagent_fork", "take_screenshot",
        "web_fetch", "write",
    },
}

#: The same, per permission level. ``medium`` is the level a window opens in, so
#: the one tool it adds over ``low`` and the one it withholds from ``high`` are
#: both load-bearing.
REFUSED_BY_PERMISSION: dict[str, set[str]] = {
    "low": {
        "delete_file", "edit", "execute_command", "http_request", "job_kill",
        "send_message", "subagent", "subagent_fork", "take_screenshot",
        "web_fetch", "write",
    },
    "medium": {"execute_command", "take_screenshot"},
    "high": {"take_screenshot"},
    "full": set(),
}

#: The tools that must ask before they run. Enumerated rather than discovered so
#: a tool that *becomes* destructive is a diff somebody reads -- the failure this
#: guards is the opposite direction: a destructive tool that stops being in this
#: set, because the set is what the confirmation sweep iterates.
DESTRUCTIVE_TOOLS = {"delete_file", "edit", "execute_command", "write"}

#: Parameters whose value is a filesystem path. ``pattern`` is deliberately not
#: here: it is a path to ``glob`` and a regular expression to ``grep``, so the
#: path-shaped promise is stated for it in its own test below.
PATH_KEYS = {"path", "file", "filepath", "directory", "dir", "cwd", "source", "target"}

#: Tools the path sweep must reach. A parameter renamed out of ``PATH_KEYS``
#: would otherwise drop a tool out of the sweep and leave the suite green.
PATH_TOOLS = {
    "browser_screenshot", "delete_file", "edit", "execute_command", "glob",
    "grep", "list_dir", "read", "read_image", "sandbox_list_files",
    "sandbox_read_file", "write",
}


def _sample_args(tool, override: dict | None = None) -> dict:
    """Minimal valid arguments, built from the tool's own schema.

    Enum-aware on purpose: a tool handed ``"probe"`` for an enum parameter is
    refused by *argument validation*, which would let a test that means to
    exercise the confirmation gate pass without ever reaching it -- measured on
    ``write``, whose ``encoding`` enum short-circuited before the prompt.
    """
    override = override or {}
    properties = (tool.parameters or {}).get("properties", {}) or {}
    args: dict = {}
    for key, schema in properties.items():
        if key in override:
            args[key] = override[key]
            continue
        if schema.get("enum"):
            args[key] = schema["enum"][0]
        else:
            kind = schema.get("type")
            args[key] = {
                "string": "sample",
                "integer": 1,
                "number": 1,
                "boolean": False,
                "array": [],
                "object": {},
            }.get(kind, "sample")
    return args


@pytest.fixture
def project(tmp_path: Path, monkeypatch):
    """A project folder, and an ``outside`` directory beside it to aim at."""
    project = tmp_path / "project"
    outside = tmp_path / "outside"
    project.mkdir()
    outside.mkdir()
    (project / "inside.txt").write_text("inside value\n", encoding="utf-8")
    (project / "doomed.txt").write_text("delete me\n", encoding="utf-8")
    (outside / "secret.txt").write_text(
        "OUTSIDE-SECRET-VALUE-9931\n", encoding="utf-8"
    )
    monkeypatch.setattr(folder_manager, "_current_folder", project)
    return project


@pytest.fixture
def body_ran(monkeypatch):
    """Replace every tool's body with a recorder, and collect what it recorded.

    The recorder stands in for the tool, so a test can use arguments that would
    otherwise be dangerous (a real ``delete_file``, a real screenshot) and still
    measure the only thing it is about: whether the gate let the call through.
    Returns the list of tool names whose bodies were reached.
    """
    reached: list[str] = []

    for name in tool_registry.list_names():
        tool = tool_registry.get(name)
        original = tool.execute

        async def spy(*args, _name=name, **kwargs):
            reached.append(_name)
            return ToolResult(status=ToolResultStatus.SUCCESS, output="spy", summary="spy")

        spy.__wrapped__ = original  # type: ignore[attr-defined]
        monkeypatch.setattr(tool, "execute", spy)
    return reached


@pytest.fixture
def no_runtime(monkeypatch):
    """Empty the shared sandbox manager, so "no runtime" is a fact here.

    Not a stubbed gate: ``_resolve_target`` and ``check_runtime`` run exactly as
    they do in the app and read the manager, which is the state a window starts
    in. Forcing it means a developer with Docker running gets the same answers
    as CI, and that the refusals below are about the gate rather than about this
    machine.
    """
    manager = get_shared_sandbox_manager()
    monkeypatch.setattr(manager, "get_runtime_backend", lambda: None)
    monkeypatch.setattr(manager, "get_backend", lambda: None)
    from tonyagent.config.settings import settings

    monkeypatch.setattr(settings.tools, "fallback_to_local", False)
    return manager


def _answering(orch: ToolOrchestrator, approve: bool) -> None:
    """Install a bridge that answers every prompt, a tick later, as the window does."""

    def answer(request):
        asyncio.get_running_loop().call_soon(
            orch.respond_to_confirmation, request.tool_call.id, approve
        )

    orch.set_confirmation_callback(answer)


# --- the two axes ---------------------------------------------------------------


@pytest.mark.parametrize("mode_name", sorted(MODES))
async def test_each_mode_refuses_exactly_its_table(mode_name, project, body_ran):
    """Every tool, every mode: the refusal is the mode's, and the body did not run.

    The wording is asserted too. "Not available" is what the model has to act
    on, and a refusal that came back as ``Unknown tool`` or ``Invalid
    arguments`` would mean the call was refused by something other than the mode
    -- which is the shape a gate takes when it is really a schema filter.
    """
    mode = get_mode(mode_name)
    refused = REFUSED_BY_MODE[mode_name]
    assert refused == {n for n in tool_registry.list_names() if n not in mode.allowed_tools}, (
        "the registry and the mode's allow-list disagree about what this mode refuses"
    )

    orch = ToolOrchestrator()
    orch.set_mode(mode)
    for name in sorted(tool_registry.list_names()):
        body_ran.clear()
        result = await orch.execute_tool_async(
            ToolCall(id=f"{mode_name}-{name}", name=name, arguments={})
        )
        if name in refused:
            assert result.status is ToolResultStatus.ERROR, (name, result.status)
            assert "not available in" in (result.error or ""), (name, result.error)
            assert mode.label in (result.error or ""), (
                f"{name} was refused without naming the mode: {result.error!r}"
            )
            assert body_ran == [], f"{name} ran in {mode_name} mode"
        else:
            assert "not available in" not in (result.error or ""), (
                f"{name} was refused in {mode_name} mode, which allows it"
            )


@pytest.mark.parametrize("level", sorted(PERMISSIONS))
async def test_each_permission_level_refuses_exactly_its_table(level, project, body_ran):
    """The other axis, swept the same way. Separate test, separate table.

    Kept apart from the mode sweep because the two are independent limits that
    happen to overlap today -- ``plan`` and ``low`` refuse the same eleven tools
    -- and a test that merged them would still pass if one axis stopped being
    enforced at all.
    """
    permission = get_permission(level)
    refused = REFUSED_BY_PERMISSION[level]
    assert refused == {
        n for n in tool_registry.list_names() if n not in permission.allowed_tools
    }, "the registry and the permission's allow-list disagree"

    orch = ToolOrchestrator()
    orch.set_permission(permission)
    for name in sorted(tool_registry.list_names()):
        body_ran.clear()
        result = await orch.execute_tool_async(
            ToolCall(id=f"{level}-{name}", name=name, arguments={})
        )
        if name in refused:
            assert result.status is ToolResultStatus.ERROR, (name, result.status)
            assert body_ran == [], f"{name} ran at {level} permission"
        else:
            assert "not available in" not in (result.error or ""), (
                f"{name} was refused at {level}, which allows it"
            )


async def test_the_two_axes_intersect_rather_than_override(project, body_ran):
    """A mode can only ever take tools away, and so can a level.

    The claim ``tool_permitted`` makes in prose, measured on all sixteen
    combinations: a tool runs only where *both* allow it. The cardinalities are
    asserted, because an intersection that accidentally became a union would
    otherwise still refuse everything the sweep above expects.
    """
    allowed_total = 0
    for mode_name, mode in MODES.items():
        for level, permission in PERMISSIONS.items():
            orch = ToolOrchestrator()
            orch.set_mode(mode)
            orch.set_permission(permission)
            for name in sorted(tool_registry.list_names()):
                expected = name in mode.allowed_tools and name in permission.allowed_tools
                assert orch.tool_permitted(name) is expected, (mode_name, level, name)
                allowed_total += expected
            body_ran.clear()
            result = await orch.execute_tool_async(
                ToolCall(id="x", name="write", arguments={})
            )
            refused_for_write = (
                "write" not in mode.allowed_tools or "write" not in permission.allowed_tools
            )
            if refused_for_write:
                assert result.status is ToolResultStatus.ERROR
                assert body_ran == [], f"write ran at {mode_name}/{level}"
    # The four modes and four levels are not one ladder each: the union of what
    # every combination allows is bigger than any single pair, and the
    # intersection is what none of them may exceed.
    assert allowed_total > len(tool_registry.list_names())


async def test_every_registered_tool_is_reachable_somewhere(project, body_ran):
    """No tool is in no mode -- and Build+Full reaches every one of them.

    ``modes.py`` says "a tool in no mode is unreachable", and an unreachable
    tool is invisible in a way no other test notices: it is never called, so
    nothing fails. Reached through the orchestrator with each tool's own
    schema-derived arguments, so this is the real path, and with a bridge, so a
    destructive tool is admitted rather than refused before its body.
    """
    orch = ToolOrchestrator()
    orch.set_mode(get_mode("build"))
    orch.set_permission(get_permission("full"))
    _answering(orch, approve=True)

    unreached = []
    for name in sorted(tool_registry.list_names()):
        body_ran.clear()
        await orch.execute_tool_async(
            ToolCall(id=f"reach-{name}", name=name,
                     arguments=_sample_args(tool_registry.get(name)))
        )
        if body_ran != [name]:
            unreached.append(name)
    assert unreached == [], (
        f"Build+Full did not reach {unreached}; either a tool is unreachable or "
        "its the sample arguments are no longer valid"
    )


# --- the confirmation gate, for every tool that has one --------------------------


async def test_every_destructive_tool_is_refused_when_nothing_can_ask(project, body_ran):
    """No bridge is not permission. Swept, because the hole was found in one tool.

    ``_request_confirmation`` returned ``None`` with no callback installed, and
    the caller reads ``None`` as "approved" -- measured on ``delete_file``: the
    file was gone. The fix is in one place, and this is the sweep that says the
    place covers every tool that needs it: the destructive set is asserted, and
    each member is called through the orchestrator with no bridge.
    """
    assert {n for n in tool_registry.list_names()
            if tool_registry.get(n).destructive} == DESTRUCTIVE_TOOLS, (
        "the destructive set changed; the confirmation sweep below must cover "
        "the new member"
    )

    orch = ToolOrchestrator()
    orch.set_mode(get_mode("build"))
    orch.set_permission(get_permission("high"))
    assert orch._confirmation_callback is None, "this test is about the no-bridge case"

    for name in sorted(DESTRUCTIVE_TOOLS):
        body_ran.clear()
        result = await orch.execute_tool_async(
            ToolCall(id=name, name=name,
                     arguments=_sample_args(tool_registry.get(name)))
        )
        assert result.status is ToolResultStatus.ERROR, (name, result.status)
        assert name in (result.error or ""), (name, result.error)
        assert "not run" in (result.error or ""), (name, result.error)
        assert body_ran == [], f"{name} ran with nobody to ask"
        assert orch._pending_confirmations == {}


async def test_every_destructive_tool_is_refused_when_the_user_says_no(project, body_ran):
    """A denied prompt is a refusal, for every tool, and it leaves nothing behind."""
    for name in sorted(DESTRUCTIVE_TOOLS):
        orch = ToolOrchestrator()
        _answering(orch, approve=False)
        body_ran.clear()
        result = await orch.execute_tool_async(
            ToolCall(id=name, name=name,
                     arguments=_sample_args(tool_registry.get(name)))
        )
        assert result.status is ToolResultStatus.CANCELLED, (name, result.status)
        assert body_ran == [], f"{name} ran after the user said no"
        assert orch._pending_confirmations == {}, (
            f"{name} left a prompt behind for a later responder to answer"
        )


async def test_a_denied_delete_really_leaves_the_file_alone(project):
    """The same claim, on the machine rather than through a recorder.

    The recorder proves the orchestrator never ran the body; this proves the
    file the user's ``No`` was about is still there, which is the outcome the
    person clicking the button cares about.
    """
    doomed = project / "doomed.txt"
    orch = ToolOrchestrator()
    _answering(orch, approve=False)

    result = await orch.execute_tool_async(
        ToolCall(id="deny", name="delete_file", arguments={"path": "doomed.txt"})
    )

    assert result.status is ToolResultStatus.CANCELLED
    assert doomed.exists(), "a denied prompt still deleted the file"


async def test_every_destructive_tool_is_refused_when_the_answer_never_comes(
    project, body_ran, monkeypatch
):
    """The likeliest real case -- the user walked away -- for every tool.

    The wait is shortened rather than sat out: the timeout is one module
    constant for exactly this reason.
    """
    import tonyagent.tools.orchestrator as orchestrator_module

    monkeypatch.setattr(orchestrator_module, "CONFIRMATION_TIMEOUT_S", 0.05)
    for name in sorted(DESTRUCTIVE_TOOLS):
        orch = ToolOrchestrator()
        orch.set_confirmation_callback(lambda request: None)  # nobody answers
        body_ran.clear()
        result = await orch.execute_tool_async(
            ToolCall(id=name, name=name,
                     arguments=_sample_args(tool_registry.get(name)))
        )
        assert result.status is ToolResultStatus.CANCELLED, (name, result.status)
        assert body_ran == [], f"{name} ran after its prompt timed out"
        assert orch._pending_confirmations == {}
        assert CONFIRMATION_TIMEOUT_S > 1, "the real timeout is no longer a wait"


# --- the sandbox gate ------------------------------------------------------------


async def test_a_command_that_is_approved_still_needs_the_sandbox(project, no_runtime):
    """An allow-listed command, approved by the user, at High: still refused.

    This is the pair the sandbox exists for. The command is on the allow-list
    (gate one), the user has answered the prompt (gate four), and the only thing
    left is *where it would run* -- so the call must come back with the one
    sentence for "nothing is attached", and the machine must be untouched. The
    contrast in the same test is the point: the rung above it is allowed to do
    exactly this, and it is the rung, not an accident.
    """
    command = f'"{sys.executable}" --version'
    orch = ToolOrchestrator()
    orch.set_mode(get_mode("build"))
    orch.set_permission(get_permission("high"))
    _answering(orch, approve=True)

    result = await orch.execute_tool_async(
        ToolCall(id="cmd", name="execute_command", arguments={"command": command})
    )

    assert result.status is ToolResultStatus.ERROR, result
    assert result.error == NO_RUNTIME, result.error
    assert result.output is None, "a refused command produced output"

    # The rung whose description says "commands run directly on this computer":
    # allowed, without a container, without a prompt.
    full = ToolOrchestrator()
    full.set_mode(get_mode("build"))
    full.set_permission(get_permission("full"))
    ran = await full.execute_tool_async(
        ToolCall(id="cmd2", name="execute_command", arguments={"command": command})
    )
    assert ran.status is ToolResultStatus.SUCCESS, ran.error
    assert "Python" in str(ran.output.get("stdout", "")), (
        f"the Full rung did not run the command on the host: {ran.output!r}"
    )


async def test_the_one_setting_that_also_reaches_the_host_is_a_setting(project, no_runtime):
    """``tools.fallback_to_local`` is the other way out, and it is opt-in.

    Documented as a *separate* decision from the permission rung, so it is
    pinned separately: High plus this setting runs on the host, and the setting
    being off is what the refusal above rests on.
    """
    from tonyagent.config.settings import settings

    settings.tools.fallback_to_local = True
    try:
        orch = ToolOrchestrator()
        orch.set_mode(get_mode("build"))
        orch.set_permission(get_permission("high"))
        # High still asks; the setting decides *where*, not whether to prompt.
        _answering(orch, approve=True)
        ran = await orch.execute_tool_async(
            ToolCall(
                id="cmd",
                name="execute_command",
                arguments={"command": f'"{sys.executable}" --version'},
            )
        )
        assert ran.status is ToolResultStatus.SUCCESS, ran.error
    finally:
        settings.tools.fallback_to_local = False


async def test_every_sandbox_required_tool_refuses_with_one_sentence(project, no_runtime):
    """The same cause gets the same words, for every tool that has the cause.

    ``runtime_access`` exists because two tools once described "no sandbox" two
    different ways. The sweep is what keeps a third from joining them: the set
    of sandbox-required tools is asserted, and each one is called with its own
    valid arguments and must answer with ``NO_RUNTIME`` exactly.
    """
    needed = {n for n in tool_registry.list_names()
              if tool_registry.get(n).sandbox_required}
    assert needed == {
        "browser_click", "browser_eval", "browser_get_text", "browser_navigate",
        "browser_screenshot", "browser_scroll", "browser_snapshot", "browser_type",
        "browser_wait_for", "execute_command", "execute_js", "sandbox_list_files",
        "sandbox_read_file", "set_viewport_size",
    }, "the sandbox-required set changed; the sweep below must cover the new member"

    orch = ToolOrchestrator()
    orch.set_mode(get_mode("build"))
    orch.set_permission(get_permission("high"))
    _answering(orch, approve=True)  # so execute_command reaches the sandbox gate

    for name in sorted(needed):
        # No spy here on purpose: this test is about the refusal the *real* body
        # produces, and the gate is the first thing each of them does.
        arguments = _sample_args(tool_registry.get(name))
        if name == "execute_command":
            # Otherwise the allow-list refuses first and the runtime is never
            # consulted; the command has to be one the allow-list knows.
            arguments["command"] = f'"{sys.executable}" --version'
        result = await orch.execute_tool_async(
            ToolCall(id=name, name=name, arguments=arguments)
        )
        assert result.status is ToolResultStatus.ERROR, (name, result.status)
        assert result.error == NO_RUNTIME, (name, result.error)


# --- the workspace boundary ------------------------------------------------------


def _path_pairs() -> list[tuple[str, str]]:
    pairs = []
    for name in sorted(tool_registry.list_names()):
        tool = tool_registry.get(name)
        properties = (tool.parameters or {}).get("properties", {}) or {}
        for key in sorted(properties):
            if key in PATH_KEYS:
                pairs.append((name, key))
    return pairs


async def test_every_path_taking_tool_refuses_an_escape(project):
    """``../outside/secret.txt``, through every path parameter, on four spellings.

    The invariant is deliberately blunt: an attempt to leave the project is an
    **error**, never a success. The sentinel outside the folder makes the read
    half of that measurable, and the file that must not appear makes the write
    half measurable -- a tool that quietly wrote outside would otherwise be
    indistinguishable from one that refused.
    """
    pairs = _path_pairs()
    assert {name for name, _ in pairs} >= PATH_TOOLS, (
        "the sweep no longer reaches these tools; a parameter was renamed out "
        f"of PATH_KEYS: {sorted(PATH_TOOLS - {n for n, _ in pairs})}"
    )
    assert len(pairs) == 12, (
        f"the sweep reaches {len(pairs)} path parameters; it was 12. A change "
        "here means a tool's path parameter moved -- update this count and "
        "`PATH_TOOLS` in the same diff, because silence is what a sweep failing "
        "to cover a tool looks like."
    )

    planted = project.parent / "outside" / "planted.txt"
    # No spy here, for the same reason the confirmation sweep has none: the
    # confinement check lives *inside* each tool's body, so a recorder standing
    # in for the body would answer the question this test is asking. The
    # arguments are safe to aim at the real tools because the gate is what is
    # being measured -- and the planted file is the proof.
    escapes = [
        "../outside/secret.txt",
        "sub/../../outside/secret.txt",
        "..\\outside\\secret.txt",
        str(project.parent / "outside" / "secret.txt"),
    ]

    orch = ToolOrchestrator()
    orch.set_mode(get_mode("build"))
    orch.set_permission(get_permission("high"))
    _answering(orch, approve=True)  # destructive tools must reach their path gate

    for name, key in pairs:
        tool = tool_registry.get(name)
        for escape in escapes:
            override = {key: escape}
            if name == "execute_command":
                # The allow-list is a gate *before* the path, and "sample" is
                # not on it -- so without this the escape would be refused for
                # the wrong reason. See the test below for the host path, where
                # the cwd is what refuses.
                override["command"] = f'"{sys.executable}" --version'
            result = await orch.execute_tool_async(
                ToolCall(
                    id=f"{name}-{key}",
                    name=name,
                    arguments=_sample_args(tool, override),
                )
            )
            error = (result.error or "").lower()
            assert result.status is ToolResultStatus.ERROR, (
                f"{name}.{key} accepted {escape!r}: {result.status} "
                f"{result.output!r}"
            )
            assert "was not run" not in error, (
                f"{name}.{key} was refused by the confirmation gate, so its path "
                "gate was never reached"
            )
            # One of two documented reasons, depending on whether the tool needs
            # a runtime before it can even look at a path: the boundary itself,
            # or nothing attached to serve it. A success is what is forbidden.
            assert (
                "escape" in error
                or "outside" in error
                or "sandbox" in error
                or "not found" in error
            ), f"{name}.{key} was refused without saying why: {result.error!r}"
            assert "OUTSIDE-SECRET" not in f"{result.output}{result.error}", (
                f"{name}.{key} read a file outside the project"
            )
            assert not planted.exists(), (
                f"{name}.{key} created a file outside the project"
            )


async def test_a_host_command_still_cannot_start_outside_the_project(project):
    """Full runs on the host; the *cwd* is still the workspace boundary.

    The rung that lifts the sandbox is the one where a path check still has to
    hold, because there is no container left to contain anything: a command run
    with ``cwd=".."`` executes in the user's home directory as the user. The
    boundary is the last thing between the Full rung and the whole filesystem,
    so it is measured here rather than assumed from the sandboxed cases.
    """
    orch = ToolOrchestrator()
    orch.set_mode(get_mode("build"))
    orch.set_permission(get_permission("full"))

    result = await orch.execute_tool_async(
        ToolCall(
            id="cwd-escape",
            name="execute_command",
            arguments={"command": f'"{sys.executable}" --version', "cwd": "../"},
        )
    )

    assert result.status is ToolResultStatus.ERROR, (
        f"a host command started outside the project: {result.output!r}"
    )
    assert "escape" in (result.error or ""), result.error


async def test_a_write_aimed_outside_creates_nothing(project):
    """The write side, on the machine: an approving bridge is not a way out.

    ``write`` is destructive, so a test that forgot the bridge would pass for
    the wrong reason. With the user answering *yes*, the only thing left between
    the call and the workspace boundary is the path -- which is the gate this
    pins.
    """
    orch = ToolOrchestrator()
    _answering(orch, approve=True)
    target = project.parent / "outside" / "planted.txt"

    result = await orch.execute_tool_async(
        ToolCall(
            id="plant",
            name="write",
            arguments={"path": "../outside/planted.txt", "content": "planted"},
        )
    )

    assert result.status is ToolResultStatus.ERROR, result
    assert "escape" in (result.error or ""), result.error
    assert not target.exists(), "a write escaped the project folder"


async def test_glob_refuses_a_pattern_that_climbs_out(project):
    """The historical hole, kept as its own named test.

    ``glob`` was the one tool that reached outside the project *through its
    pattern*, while every copy of the containment rule was intact -- the reason
    ``tools/workspace.py`` exists. Named here so the specific vector cannot be
    deleted as redundant with the sweep above.
    """
    tool = tool_registry.get("glob")
    for pattern in ("../outside/*.txt", "**/../../outside/*.txt", "*/../outside/*"):
        result = await tool.execute(pattern=pattern, path=".")
        assert result.status is ToolResultStatus.ERROR, (pattern, result.status)
        assert "escape" in (result.error or "").lower() or "outside" in (
            result.error or ""
        ).lower(), (pattern, result.error)


async def test_a_symlink_out_of_the_project_is_refused(project):
    """Resolved, not just spelled: the boundary follows the link.

    A purely lexical check accepts ``root/link/secret`` where ``link`` points
    outside. ``confine`` resolves first, so the call is refused. Skipped where
    the OS will not let an unprivileged process make a symlink (Windows without
    developer mode), with the reason recorded rather than silently passed.
    """
    outside = project.parent / "outside"
    link = project / "link"
    try:
        os.symlink(outside, link, target_is_directory=True)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"this machine cannot create a symlink without privilege: {exc}")

    orch = ToolOrchestrator()
    result = await orch.execute_tool_async(
        ToolCall(id="link", name="read", arguments={"path": "link/secret.txt"})
    )

    assert result.status is ToolResultStatus.ERROR, result
    assert "OUTSIDE-SECRET" not in f"{result.output}{result.error}"


# --- the surface's own memory ----------------------------------------------------


async def test_the_execution_history_is_a_ring_rather_than_a_leak(project):
    """The one thing every tool call writes to, bounded.

    ``_execution_history`` holds each call's **full arguments** — for ``write``
    that is the contents of the file — and it grew without a limit, with no
    reader anywhere in the tree (``get_history``/``clear_history`` have no
    callers). A long conversation, and especially a fan-out, could therefore
    hold megabytes of workspace contents in memory for a history nobody asks
    for. The bound is here rather than in a reader because the leak was the
    default state; what the newest end must keep is the *recent* calls, which is
    the assertion the last line makes.
    """
    from tonyagent.tools.orchestrator import EXECUTION_HISTORY_LIMIT

    orch = ToolOrchestrator()
    for index in range(EXECUTION_HISTORY_LIMIT + 5):
        result = await orch.execute_tool_async(
            ToolCall(id=f"call-{index}", name="read", arguments={"path": "inside.txt"})
        )
        assert result.status is ToolResultStatus.SUCCESS, result.error

    history = orch.get_history()
    assert len(history) == EXECUTION_HISTORY_LIMIT, (
        f"the history kept {len(history)} entries against a cap of "
        f"{EXECUTION_HISTORY_LIMIT}"
    )
    assert history[0]["call"]["id"] == "call-5", (
        "the ring dropped the wrong end: the newest calls are the ones worth "
        f"keeping, and the oldest kept is {history[0]['call']['id']!r}"
    )
    assert history[-1]["call"]["id"] == f"call-{EXECUTION_HISTORY_LIMIT + 4}"
    assert orch._pending_confirmations == {}
