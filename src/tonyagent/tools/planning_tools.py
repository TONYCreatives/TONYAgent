"""Tools for the agent's own plan: the task list and the goal.

These four change nothing outside the conversation. They write to
``core.task_state``, which the session renders into its system prompt, so what they
actually do is decide what the model reads on its next turn.

**None of them is confirmation-gated, and none is destructive.** The thing being
written is the agent's own note-to-self, not the user's project; there is nothing
here for a confirmation dialog to protect. What they *can* do is lose information --
`create_goal` refuses to overwrite a live objective, and `todo_write` replaces the
list outright -- so those two are careful in the refusal rather than in a prompt.
"""

from __future__ import annotations

from tonyagent.core.task_state import (
    GOAL_STATUSES,
    MAX_ITEM_CHARS,
    TODO_STATUSES,
    Todo,
    current_state,
)
from tonyagent.tools.base import (
    Tool,
    ToolCategory,
    ToolResult,
    ToolResultStatus,
    register_tool,
)


def _list_text(todos: list[Todo]) -> str:
    """The task list as the transcript shows it."""
    marks = {"pending": "[ ]", "in_progress": "[~]", "completed": "[x]"}
    rows = "\n".join(
        f"{index}. {marks.get(todo.status, '[ ]')} {todo.text}"
        for index, todo in enumerate(todos, start=1)
    )
    done = sum(1 for todo in todos if todo.status == "completed")
    return f"{done} of {len(todos)} done:\n{rows}"


@register_tool
class TodoWriteTool(Tool):
    """Replace the agent's task list for this conversation.

    **The whole list, every time.** Not a patch: the model sends the list it wants
    to exist, which is the only shape that makes *removing* an item possible without
    a second verb. A list that can only grow is one nobody prunes, and a task the
    model quietly abandoned is then read on every later turn as work still
    outstanding -- which is worse than no task at all, because it looks current.

    Changing a plan touches no file, so this is offered in every mode including
    Plan. A plan is what Plan mode is *for*, and a mode that refused to let the agent
    write down what it intends would make it carry the plan in prose instead.
    """

    name = "todo_write"
    description = (
        "Write the plan for this task as a list of steps, replacing any previous "
        "list. Send the complete list each time, with each step's status, and keep "
        "it current as you work: one step in_progress at a time, completed when it "
        "is done. Use it for work with more than a couple of steps, so the plan "
        "survives the turns it takes."
    )
    category = ToolCategory.UTILITY
    parameters = {
        "type": "object",
        "properties": {
            "todos": {
                "type": "array",
                "description": "The complete task list, in the order it should be done.",
                "items": {
                    "type": "object",
                    "properties": {
                        "text": {
                            "type": "string",
                            "description": "The step, as a short imperative phrase.",
                        },
                        "status": {
                            "type": "string",
                            "enum": list(TODO_STATUSES),
                            "description": "pending, in_progress or completed.",
                        },
                    },
                    "required": ["text"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["todos"],
        "additionalProperties": False,
    }
    destructive = False
    requires_confirmation = False
    folder_required = False

    async def execute(self, todos: list[dict] | None = None) -> ToolResult:
        state = current_state()

        if todos is None:
            # `validate_args` refuses this before it gets here -- `todos` is
            # required -- but the tool is also called directly by tests and by
            # anything that drives it without the orchestrator, so it answers
            # rather than raising.
            if not state.todos:
                return ToolResult(
                    status=ToolResultStatus.SUCCESS,
                    output="No task list yet.",
                    summary="no plan",
                )
            return ToolResult(
                status=ToolResultStatus.SUCCESS,
                output=_list_text(state.todos),
                summary=state.summary(),
            )

        if not isinstance(todos, list):
            return ToolResult(
                status=ToolResultStatus.ERROR,
                error="todos must be a list of {text, status} objects",
            )

        # Items are checked here rather than by `validate_args`, which validates the
        # top-level shape (a list) and not what is inside it. A bad item is the
        # model's typo, so it is answered with the item's number and what is wrong
        # with it rather than a generic refusal.
        parsed: list[Todo] = []
        for index, entry in enumerate(todos, start=1):
            if not isinstance(entry, dict):
                return ToolResult(
                    status=ToolResultStatus.ERROR,
                    error=f"Task {index} must be an object with a 'text' field.",
                )
            text = " ".join(str(entry.get("text") or "").split())
            if not text:
                return ToolResult(
                    status=ToolResultStatus.ERROR,
                    error=f"Task {index} has no text.",
                )
            if len(text) > MAX_ITEM_CHARS:
                return ToolResult(
                    status=ToolResultStatus.ERROR,
                    error=(
                        f"Task {index} is {len(text)} characters; keep each step "
                        f"under {MAX_ITEM_CHARS} so the list stays readable."
                    ),
                )
            status = str(entry.get("status") or "pending")
            if status not in TODO_STATUSES:
                return ToolResult(
                    status=ToolResultStatus.ERROR,
                    error=(
                        f"Task {index} has status {status!r}; it must be one of "
                        f"{', '.join(TODO_STATUSES)}."
                    ),
                )
            parsed.append(Todo(text=text, status=status))

        if not parsed:
            # An empty list is how the plan is cleared, and saying so is better
            # than a card reading "0 of 0 done".
            state.replace_todos([])
            return ToolResult(
                status=ToolResultStatus.SUCCESS,
                output="Task list cleared.",
                summary="no plan",
            )

        state.replace_todos(parsed)
        return ToolResult(
            status=ToolResultStatus.SUCCESS,
            output=_list_text(parsed),
            summary=f"{state.done_count}/{len(parsed)} tasks done",
        )


@register_tool
class CreateGoalTool(Tool):
    """Set the objective for this conversation.

    A goal is the thing the task list is a plan *for*, and it is deliberately
    separate: the list changes every few minutes and the objective does not, and a
    model that has to restate its objective to reorder its steps loses the thread.

    **It refuses to overwrite a live goal.** Silently replacing an active objective
    would drop work the user asked for with nothing anywhere recording that it had
    been abandoned -- and the new goal would then read as though it were the only
    one there had ever been. Finishing the old one is one call, so the refusal names
    it.
    """

    name = "create_goal"
    description = (
        "Set the objective for this conversation, for a task that will span several "
        "turns. One goal at a time: finish the current one with update_goal before "
        "setting another."
    )
    category = ToolCategory.UTILITY
    parameters = {
        "type": "object",
        "properties": {
            "objective": {
                "type": "string",
                "description": "What is to be achieved, in one sentence.",
            },
        },
        "required": ["objective"],
        "additionalProperties": False,
    }
    destructive = False
    requires_confirmation = False
    folder_required = False

    async def execute(self, objective: str = "") -> ToolResult:
        state = current_state()
        wanted = " ".join(str(objective or "").split())
        if not wanted:
            return ToolResult(
                status=ToolResultStatus.ERROR,
                error="A goal needs an objective.",
            )
        if state.has_goal and state.goal_status == "active":
            return ToolResult(
                status=ToolResultStatus.ERROR,
                error=(
                    f"There is already an active goal: '{state.goal}'. Finish it "
                    "with update_goal(status='complete') or record why it is "
                    "blocked before setting another, so the old objective is not "
                    "dropped without a trace."
                ),
            )
        state.set_goal(wanted)
        return ToolResult(
            status=ToolResultStatus.SUCCESS,
            output=f"Goal set: {state.goal}",
            summary="goal: active",
        )


@register_tool
class GetGoalTool(Tool):
    """Read the current goal back.

    Its own tool rather than a reply the model is trusted to remember, because the
    goal is in the system prompt and the *state* of it may have moved since -- and
    because a model that cannot ask "what am I doing" will restate the objective
    from memory, which is how a drifting goal goes unnoticed.
    """

    name = "get_goal"
    description = "Read the current goal and its state."
    category = ToolCategory.UTILITY
    parameters = {"type": "object", "properties": {}, "additionalProperties": False}
    destructive = False
    requires_confirmation = False
    folder_required = False

    async def execute(self) -> ToolResult:
        state = current_state()
        if not state.has_goal:
            return ToolResult(
                status=ToolResultStatus.SUCCESS,
                output="No goal set. Use create_goal to set one.",
                summary="no goal",
            )
        said = f"{state.goal}\nState: {state.goal_status or 'active'}"
        if state.goal_note:
            said += f"\nNote: {state.goal_note}"
        return ToolResult(
            status=ToolResultStatus.SUCCESS,
            output=said,
            summary=f"goal: {state.goal_status or 'active'}",
        )


@register_tool
class UpdateGoalTool(Tool):
    """Move the goal on: complete it, or say what it is blocked on.

    ``active`` is accepted so a goal can be reopened -- a blocked goal that turns
    out to be unblocked should not need a second objective to record that.

    **A blocked goal must say what it is blocked on.** "Blocked" with no reason is
    the report that helps nobody: the next turn reads it, learns nothing, and either
    retries the same wall or stops for no stated cause. The note is required, not
    encouraged.
    """

    name = "update_goal"
    description = (
        "Update the current goal's state. Use 'complete' when the objective is met "
        "and 'blocked' when it cannot proceed -- a blocked goal must carry a note "
        "saying what it is blocked on."
    )
    category = ToolCategory.UTILITY
    parameters = {
        "type": "object",
        "properties": {
            "status": {
                "type": "string",
                "enum": list(GOAL_STATUSES),
                "description": "active, complete or blocked.",
            },
            "note": {
                "type": "string",
                "description": "Why, for a blocked goal; optional otherwise.",
            },
            "objective": {
                "type": "string",
                "description": "Reworded objective, if it needs to be sharper.",
            },
        },
        "required": ["status"],
        "additionalProperties": False,
    }
    destructive = False
    requires_confirmation = False
    folder_required = False

    async def execute(self, status: str = "", note: str = "",
                      objective: str = "") -> ToolResult:
        state = current_state()
        if not state.has_goal:
            return ToolResult(
                status=ToolResultStatus.ERROR,
                error="There is no goal to update. Set one with create_goal first.",
            )
        if status not in GOAL_STATUSES:
            return ToolResult(
                status=ToolResultStatus.ERROR,
                error=(
                    f"{status!r} is not a goal state; it must be one of "
                    f"{', '.join(GOAL_STATUSES)}."
                ),
            )
        # The note is required of the *resulting* state, not of this call. A goal
        # that is already blocked and already says why does not have to repeat
        # itself in order to be reworded -- asking for it again would make a
        # one-word improvement to the objective cost a restatement of the reason,
        # and the model would either duplicate it or drop it.
        if status == "blocked" and not (" ".join(str(note or "").split()) or state.goal_note):
            return ToolResult(
                status=ToolResultStatus.ERROR,
                error=(
                    "A blocked goal needs a note saying what it is blocked on -- "
                    "otherwise the next turn reads 'blocked' and learns nothing it "
                    "can act on."
                ),
            )

        # A reworded objective keeps any existing note unless a new one is given, so
        # sharpening the wording does not silently erase why it was blocked.
        state.set_goal(
            objective or state.goal,
            status=status,
            note=note or state.goal_note,
        )
        said = f"Goal is now {state.goal_status}: {state.goal}"
        if state.goal_note:
            said += f"\nNote: {state.goal_note}"
        return ToolResult(
            status=ToolResultStatus.SUCCESS,
            output=said,
            summary=f"goal: {state.goal_status}",
        )
