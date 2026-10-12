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


#: Appended to **every** mode's prompt, by `AgentSession._messages_with_system`.
#:
#: One assistant message may declare several tool calls: they run at the same
#: time and every result comes back in one batch, so a turn that reads three
#: files can do it in one request instead of three. The mechanism is in the
#: session and has been since parallel tool calls landed -- what was missing was
#: anyone telling the model, because a model that does not know it *may* batch
#: asks one call at a time. That is not a style difference on a metered
#: provider: the free OpenRouter tier allows 20 requests a minute and 1000 a
#: day, and every round trip is one of them, so an unbatched turn spends the
#: user's quota on conversations the app could have had in a single message.
#:
#: Written as rules rather than as a suggestion, and kept short, because it is
#: sent on every request in every mode and is paid for in tokens each time.
#: `tests/unit/test_turn_economy.py` asserts it reaches every mode's prompt
#: intact, including the one thing a model cannot guess: that it may ask for
#: several tools in one message at all.
TOOL_CALL_ECONOMY = (
    "How to spend a turn. You may put several tool calls in one message: they "
    "run at the same time, and you get every result back together in the next "
    "one. Use that. Batch the calls that do not depend on each other -- the "
    "files you already know you need to read, the searches that have nothing to "
    "do with each other -- and put only the calls that need an earlier result "
    "in a later message. Never ask again for something you already have. "
    "Requests are metered, so a round spent narrating what you are about to do "
    "is a round not spent doing it: for work of more than one step, write the "
    "steps with todo_write in the same message as your first batch of calls, "
    "and then work the list. One command that reports everything you need "
    "beats three that each report part of it."
)


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
    "read",
    "read_image",
    "list_dir",
    # Managing jobs observes rather than changes: `job_list` and `job_output`
    # read what a job has already produced, and a job outlives the mode that
    # started it -- so refusing to *look* at one in Plan mode would hide state
    # the user can see, for no gain. `job_kill` is in the mutating set below,
    # because stopping a process is a change.
    "job_list",
    "job_output",
    # The planning tools. They change the agent's own note-to-self rather than the
    # workspace or the machine, so every rung may use them -- and Plan mode most of
    # all, because a plan is what that mode is for. Refusing to let the agent write
    # down what it intends would make it carry the plan in prose instead.
    "todo_write",
    "create_goal",
    "get_goal",
    "update_goal",
    # The two tools that reach the user. Safe in every mode, and Plan most of
    # all: a plan is exactly what Plan mode exists to hand over for approval,
    # and a mode that could not show its plan to the user would have no way to
    # end. Neither writes, reads or runs anything -- they put words in front of
    # a person and wait.
    #
    # Mission is the mode whose prompt says "do not stop to ask whether to
    # continue", and it keeps them anyway: that is a preference for the model,
    # not a wall built out of a missing tool name, and `ask_user_question` for
    # a missing credential is the one interruption a long unattended run must
    # not be prevented from making. The 60s ask timeout bounds the wait either
    # way, so Mission cannot be stalled by a dialog nobody is reading.
    "ask_user_question",
    "present",
    # The subagent registry's read and control verbs. Looking at who exists
    # observes agent-internal state — the same class as job_list/job_output;
    # interrupting one stops the agent's own work rather than anything in the
    # workspace, and a model that spawned a doomed child must be able to stop
    # paying for it in every mode, for the same reason job_kill sits here at
    # Plan rather than above it. `subagent` itself is NOT here: it runs
    # model-authored work under the child's own budget, and the mutating set
    # below is where that belongs.
    "list_agents",
    "interrupt_agent",
    # The skill tools. Loading a saved procedure is a read, so both belong here
    # and are reachable from every rung -- Plan and Skills most of all, since
    # reading what a procedure says is exactly what those two modes are for. A
    # skill cannot widen anything by being loaded: its steps are performed
    # afterwards with the tools the turn already has, so a procedure that says
    # "write the file" is still refused in Plan mode at the write.
    "list_skills",
    "run_skill",
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
    "write",
    "edit",
    "delete_file",
    "execute_command",
    # Spawning a child session is a change to the machine's doing — its tool
    # calls really run, under a budget — so it sits with the other verbs that
    # cause work rather than with the ones that merely look. The child cannot
    # widen its parent's permission (subagent_tools.spawn inherits exactly
    # the parent's), so this grants no escalation.
    "subagent",
    # The workflow verbs, beside it and for the same reason: `send_message`
    # continues an existing child and `subagent_fork` starts a copy of one, and
    # each runs a child's turn for real -- under the child's own budget, and
    # under this session's mode and permission, which neither can widen.
    "send_message",
    "subagent_fork",
    # The network tools. Mutating-mode rather than read-only because fetching a
    # URL is a side effect the user did not necessarily ask for, and because
    # egress is off in the sandbox by default -- so a model reaching for one in
    # Build mode is a real event, and in Plan mode it is a category error.
    # `web_fetch` is a reader, but it reads somewhere else.
    "http_request",
    "web_fetch",
    # Stopping a background job is a change to the machine, so it sits with the
    # other mutating tools rather than with the two readers above.
    "job_kill",
}

#: Tools that observe the user's own machine rather than the workspace.
#:
#: Kept out of every other rung on purpose. Everything above reads files or
#: drives a browser the agent itself opened; this reads the desktop, which is
#: where the user's other windows, their messages and their documents are. Full
#: is the rung whose own wording says commands run on this computer outside the
#: project folder, so it is the only place where that is an agreement rather
#: than an overreach.
#:
#: Two axes have to agree before the model is even shown a tool
#: (`ToolOrchestrator.tool_permitted` intersects them), so this set appears
#: twice: once in the permission ladder, and once in Build -- the mode where
#: "look at the screen and fix what is wrong with it" is the work. It is in
#: Build and not Mission because a long unattended run should not be able to
#: keep photographing the desktop, and adding it there is one line whenever
#: that is wanted on purpose.
_HOST_SCREEN_TOOLS = frozenset({
    "take_screenshot",
})

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
    #: Whether this level runs commands that are *not* on the allow-list.
    #:
    #: Kept separate from `allowed_tools` because it widens a different axis.
    #: The allow-list answers "may this run at all"; this answers "is this one
    #: of the ones we know about". Folding the two together would make Full's
    #: extra power indistinguishable from High, and there would be nothing left
    #: above it.
    bypasses_command_allowlist: bool = False
    #: Whether this level runs commands on the host, with no sandbox at all.
    #:
    #: **This is the one flag in this module that removes a boundary rather than
    #: a restriction.** Every other rung narrows what may run; this one changes
    #: *where* it runs. A model-authored command inside the Docker sandbox cannot
    #: reach the user's files outside the mounted workspace, cannot see the
    #: host's environment, and cannot outlive the container. With this set, none
    #: of that is true: it runs as the user, in their session, on their machine.
    #:
    #: Kept as its own field rather than folded into `allowed_tools` for the
    #: same reason `bypasses_command_allowlist` is: the window has to be able to
    #: say what a level does *before* the user picks it, and a level that can be
    #: distinguished only by reading prose is a level nobody reads.
    runs_on_host: bool = False


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
#: "High" grants the *attempt*, and the two gates decide whether it happens. Only
#: Full lifts the second one -- see `runs_on_host`.
_HIGH = Permission(
    name="high",
    label="High",
    description=(
        "Everything, including running commands. Commands must still be "
        "allow-listed and the sandbox must be running."
    ),
    allowed_tools=_MUTATING_TOOLS,
)

#: High, without the prompt, and **on your machine rather than in a container**.
#:
#: **What this really means, stated plainly because the UI has to say it too.**
#: It adds no tools, and it lifts the command allow-list. Those two were the
#: whole of Full until this pass. What it now also does is remove the sandbox.
#:
#: The three rungs below it run a model-authored command inside Docker, mounted
#: on one folder, with the network off. Full runs it through your own shell, as
#: you, with your environment, your credentials and your filesystem. A command
#: the sandbox would have refused -- one that reaches `..`, one that reads
#: `~/.ssh`, one that installs something -- succeeds here.
#:
#: That is not a refinement of the level above, it is a different thing, and it
#: is why `runs_on_host` is a separate field rather than something folded into
#: the allow-list: the window can say *this* is the rung that leaves the
#: sandbox, in words, before the user selects it.
_FULL = Permission(
    name="full",
    label="Full",
    description=(
        "Everything, without asking, any command, and no sandbox: commands "
        "run directly on this computer as you, outside the project folder, "
        "with your files and environment reachable. Choose this only when you "
        "accept responsibility for what the agent does."
    ),
    allowed_tools=_MUTATING_TOOLS | _HOST_SCREEN_TOOLS,
    skips_confirmation=True,
    bypasses_command_allowlist=True,
    runs_on_host=True,
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
    allowed_tools=_MUTATING_TOOLS | _HOST_SCREEN_TOOLS,
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
    description="Explain and plan, with this project's skills loadable. No side effects at all.",
    system_prompt=(
        "You are in SKILLS mode. The user wants to understand something, not "
        "to change anything. Explain clearly and concretely, using this "
        "project as the example where it helps. You cannot write files or run "
        "commands. Show the code you would write, do not write it. This is "
        "also the mode for saved skills: `list_skills` shows the ones this "
        "project and this user have, `run_skill` loads one, and a user message "
        "that begins with `/name` is the user asking for that skill. Loading "
        "one changes nothing and grants nothing -- follow its procedure with "
        "the tools you do have, and when a step needs a tool this mode refuses, "
        "say which step and what it would need rather than working around it."
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
