"""Composer modes: what the agent may do, and what it is told it is doing.

A mode is two things that must agree:

* a **system prompt** that tells the model what kind of work this is, and
* a **tool allow-list** that decides which tools exist for this turn at all.

Both are needed and neither is sufficient. Omitting a tool from the schema is
*advisory* -- a model can still hallucinate a call for a tool it was never
shown. So the allow-list is also enforced in the orchestrator, which is the
layer that actually decides whether a tool runs. The schema filter is there to
stop the model wanting it in the first place; the orchestrator check is the
guarantee.

The distinction that matters: **Plan refuses writes, it does not merely
discourage them.** A mode that only changes the prompt produces a model that
says "I will not modify the file" right before it does. Prompt text is a
request; the allow-list is a fact.
"""

from __future__ import annotations

from dataclasses import dataclass, field


#: Tool categories, by the name the schema uses. Kept as strings so adding a
#: category to the tool base does not silently change what a mode permits.
READ_ONLY = "read_only"
MUTATING = "mutating"
COMMAND = "command"
BROWSER = "browser"
NETWORK = "network"


@dataclass(frozen=True)
class Mode:
    """One composer mode."""

    name: str
    label: str
    system_prompt: str
    #: Tool *names* this mode may call. A tool in no mode is unreachable.
    allowed_tools: frozenset[str]
    description: str
    #: Whether the model may change the workspace without asking first.
    writes: bool = True


# Everything that can only observe. Safe in every mode, including Plan.
_READ_ONLY_TOOLS = frozenset({
    "read_file",
    "list_dir",
    "glob",
    "grep",
    "sandbox_read_file",
    "sandbox_list_files",
    "browser_navigate",
    "browser_get_text",
    "browser_screenshot",
    "browser_snapshot",
    "browser_scroll",
    "browser_wait_for",
    "browser_eval",
    "execute_js",
    "set_viewport_size",
    "browser_click",
    "browser_type",
    # Network egress is off by default in the sandbox, and this tool is the
    # one thing that can turn it on. It stays out of Plan and Skills on
    # purpose: a mode that must not change anything should not be able to
    # fetch something new into the workspace either.
})

# Observes, and can change the workspace.
_MUTATING_TOOLS = _READ_ONLY_TOOLS | {
    "write_file",
    "edit_file",
    "delete_file",
    "execute_command",
    # `http_request` is the one network tool. It is a mutating-mode tool
    # because fetching a URL is a side effect the user did not necessarily
    # ask for, and because the sandbox denies egress by default -- so a model
    # reaching for it in Build mode is a real event, and in Plan mode it is
    # a category error.
    "http_request",
}

#: Permission levels, in order. The tuple is the order for the UI, which must
#: not have to hardcode the list -- see `MODE_ORDER` for why that mattered once.
PERMISSION_ORDER = ("low", "medium", "high", "full")

#: The level a session starts in.
#:
#: `medium`, deliberately and not `high`. A fresh window that can run shell
#: commands the moment it opens is a window whose first turn has already been
#: given more than the user asked for, and the difference between "medium" and
#: "high" is exactly one tool: the one that executes model-authored code. Build
#: mode already grants that per-turn, so nothing is lost by starting one step
#: down and saying so in the bar.
DEFAULT_PERMISSION = "medium"


@dataclass(frozen=True)
class Permission:
    """One rung on the permission ladder.

    **This is the allow-list, not the prompt.** The same rule the module
    docstring states about modes applies here, and it is the whole reason this
    is a separate axis rather than four more modes: `Mode.system_prompt` asks the
    model to behave, while `allowed_tools` decides what it *can* do, enforced in
    the orchestrator. A permission level that only rewrote the prompt would
    produce a model that says "I won't run that" and then runs it.

    `skips_confirmation` is deliberately separate from `allowed_tools`, because
    it is a different kind of permission: the tool still runs only if its own
    gates pass (the command allow-list, and the sandbox isolation check), but
    the user is no longer asked first. That is why it is confined to `full` and
    why it does not widen the allow-list by even one tool.
    """

    name: str
    label: str
    description: str
    allowed_tools: frozenset[str]
    #: Whether this level stops asking before a destructive tool runs.
    skips_confirmation: bool = False


#: Read-only: observe the project, change nothing. Same set as Plan and Skills.
_LOW = Permission(
    name="low",
    label="Low",
    description="Read, search and browse. Nothing in the project is changed.",
    allowed_tools=_READ_ONLY_TOOLS,
)

#: Edit without running anything.
#:
#: **The level that did not exist before.** Plan and Build were adjacent: one
#: could not write, the other could write *and* shell out. A window editing
#: source files but refusing to run the test suite had no way to say so, and the
#: only honest setting for "let it fix things, but do not let it execute code"
#: was to pick one of the two and give up the other half.
_MEDIUM = Permission(
    name="medium",
    label="Medium",
    description="Read, search, edit and write files. Shell commands are refused.",
    allowed_tools=_MUTATING_TOOLS - {"execute_command"},
)

#: Full tool access. Still gated twice: a command must be on the allow-list, and
#: `execute_command` refuses to run without an isolating sandbox behind it. So
#: "High" grants the *attempt*, and the two gates decide whether it happens.
_HIGH = Permission(
    name="high",
    label="High",
    description=(
        "Everything, including running commands. Commands must still be "
        "allow-listed and the sandbox must be running."
    ),
    allowed_tools=_MUTATING_TOOLS,
)

#: High, without the confirmation prompt.
#:
#: **What this really means, stated plainly because the UI has to say it too.**
#: It does not add a single tool, and it does not lift the command allow-list or
#: the sandbox requirement. It removes one thing: the question. With the project
#: marked trusted, `python -c "<anything>"` already runs, because the allow-list
#: is matched on the executable's name and cannot see what it is handed. This
#: level makes that visible instead of leaving it buried in a trust toggle --
#: the same power, chosen in the open.
_FULL = Permission(
    name="full",
    label="Full",
    description=(
        "Everything High allows, without asking first. Commands still run only "
        "if allow-listed and sandboxed. Choose this only for a project you "
        "trust: a trusted command runner can execute arbitrary code."
    ),
    allowed_tools=_MUTATING_TOOLS,
    skips_confirmation=True,
)

PERMISSIONS: dict[str, Permission] = {
    p.name: p for p in (_LOW, _MEDIUM, _HIGH, _FULL)
}


def get_permission(name: str) -> Permission:
    """Look up a permission level, falling back to the default.

    Falls back rather than raising for the same reason `get_mode` does: a
    frontend sending a stale or invented name should get a level that is safe,
    not a rejection the user has to diagnose.
    """
    return PERMISSIONS.get((name or "").strip().lower(), PERMISSIONS[DEFAULT_PERMISSION])


_BUILD = Mode(
    name="build",
    label="Build",
    description="Full access. Read, write and run commands.",
    system_prompt=(
        "You are a software engineering agent working in a real project "
        "folder. Make the change the user asked for: read what you need, edit "
        "the files, and run whatever verifies the result. Prefer editing an "
        "existing file over creating a new one. When you are done, say what "
        "you changed and how you know it works."
    ),
    allowed_tools=_MUTATING_TOOLS,
    writes=True,
)

_PLAN = Mode(
    name="plan",
    label="Plan",
    description="Read and search only. Writing is refused, not discouraged.",
    system_prompt=(
        "You are in PLAN mode. Investigate the project and propose a change, "
        "but do not make it. You cannot write files or run commands: those "
        "tools are not available to you and an attempt will be refused by the "
        "system, not by you. Read enough to be specific -- name the files you "
        "would touch and the order you would touch them. End with a plan the "
        "user can approve."
    ),
    allowed_tools=_READ_ONLY_TOOLS,
    writes=False,
)

_MISSION = Mode(
    name="mission",
    label="Mission",
    description="A long task, run to completion without stopping to ask.",
    system_prompt=(
        "You are in MISSION mode. You have been given an objective, not a "
        "question. Work towards it to completion: break it down, take the "
        "steps, verify each one, and keep going past the first thing that "
        "does not work. Do not stop to ask whether to continue. Report the "
        "outcome when the objective is met or genuinely blocked."
    ),
    allowed_tools=_MUTATING_TOOLS,
    writes=True,
)

_SKILLS = Mode(
    name="skills",
    label="Skills",
    description="Explain and plan. No side effects at all.",
    system_prompt=(
        "You are in SKILLS mode. The user wants to understand something, not "
        "to change anything. Explain clearly and concretely, using this "
        "project as the example where it helps. You cannot write files or run "
        "commands. Show the code you would write, do not write it."
    ),
    allowed_tools=_READ_ONLY_TOOLS,
    writes=False,
)


MODES: dict[str, Mode] = {m.name: m for m in (_BUILD, _PLAN, _MISSION, _SKILLS)}

#: The mode a session starts in.
DEFAULT_MODE = "build"

#: Order for the UI, which must not have to hardcode the list.
MODE_ORDER = ("build", "plan", "mission", "skills")


def get_mode(name: str) -> Mode:
    """Look up a mode, falling back to the default.

    An unknown name must not be an error the user has to diagnose: a frontend
    that sends a stale mode name should get Build, not a rejection.
    """
    return MODES.get((name or "").strip().lower(), MODES[DEFAULT_MODE])
