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
