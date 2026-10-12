"""The agent's plan: the task list, the goal, and where they are kept.

Three things are worth testing separately, because they fail in different ways:

* **The state itself** has to tolerate whatever is in a conversation file. It is
  read while a chat is being opened, and a state that cannot be parsed must cost
  the plan rather than the transcript.
* **The tools** have to refuse bad input without half-applying it. A `todo_write`
  that rejected the fifth item after storing the first four would leave a plan
  nobody wrote.
* **The wiring** is where this feature can appear to work and do nothing: the
  session renders the plan into the prompt and the tools mutate it, so they must
  hold the *same* object, and it must survive a save and a reload.
"""

from __future__ import annotations

import asyncio
import io
import json
from pathlib import Path

import pytest

import tonyagent.tools  # noqa: F401  -- importing registers every tool
from tonyagent.core.conversations import ConversationStore
from tonyagent.core.events import EventBus
from tonyagent.core.modes import TOOL_CALL_ECONOMY
from tonyagent.core.session import AgentSession
from tonyagent.core.task_state import (
    TODO_STATUSES,
    SessionState,
    Todo,
    current_state,
    set_current_state,
)
from tonyagent.headless.server import StdioServer
from tonyagent.tools import tool_registry
from tonyagent.tools.base import ToolResultStatus


def tool(name: str):
    found = tool_registry.get(name)
    assert found is not None, f"{name} is not registered"
    return found


@pytest.fixture(autouse=True)
def fresh_state():
    """Every test starts with a plan of its own.

    The state is published process-wide (see `task_state`), so a test that wrote a
    goal would otherwise hand it to the next one -- which is exactly the leak the
    per-conversation design exists to prevent, arriving through the back door.
    """
    set_current_state(SessionState())
    yield
    set_current_state(SessionState())


# --- the state itself --------------------------------------------------------


def test_text_is_collapsed_to_one_line():
    assert Todo("  write\n the\ttest  ").text == "write the test"


def test_an_unknown_status_reads_as_pending():
    """A state written by a newer build costs a status, not the whole list."""
    assert Todo("x", status="nonsense").status == "pending"


@pytest.mark.parametrize(
    "raw",
    [
        None,
        "a string",
        [],
        42,
        {"todos": "not a list"},
        {"todos": [None, 7, {"text": ""}, {"text": "   "}]},
        {"goal": ["a", "list"]},
    ],
)
def test_junk_state_reads_as_no_state(raw):
    state = SessionState.from_dict(raw)
    assert isinstance(state, SessionState)
    assert state.todos == []


def test_a_bare_string_entry_still_opens():
    """A hand-written or older entry is a task, not a parse failure."""
    state = SessionState.from_dict({"todos": ["just text"]})
    assert [todo.text for todo in state.todos] == ["just text"]
    assert state.todos[0].status == "pending"


def test_the_state_round_trips_through_a_dict():
    original = SessionState(
        todos=[Todo("one"), Todo("two", "in_progress"), Todo("three", "completed")],
        goal="Ship it",
        goal_status="active",
        goal_note="waiting on review",
    )
    restored = SessionState.from_dict(original.to_dict())
    assert restored.to_dict() == original.to_dict()


def test_nothing_renders_as_nothing():
    assert SessionState().render() == ""
    assert SessionState().is_empty()


def test_the_rendered_plan_marks_each_status_and_counts_what_is_done():
    state = SessionState(
        todos=[Todo("first", "completed"), Todo("second", "in_progress"), Todo("third")],
        goal="Ship it",
    )
    rendered = state.render()

    assert "[x] first" in rendered
    assert "[~] second" in rendered
    assert "[ ] third" in rendered
    assert "1 of 3 done" in rendered
    assert "Ship it" in rendered


def test_replacing_the_list_replaces_it_rather_than_merging():
    """The reason `todo_write` sends the whole list: dropping a step has to work.

    A list that can only grow is one nobody prunes, and a step the model quietly
    abandoned is then read on every later turn as work still outstanding.
    """
    state = SessionState(todos=[Todo("a"), Todo("b"), Todo("c")])
    state.replace_todos([Todo("c")])
    assert [todo.text for todo in state.todos] == ["c"]


def test_current_state_is_never_none():
    """A tool must always have somewhere to write, even outside a session."""
    set_current_state(None)
    assert isinstance(current_state(), SessionState)


# --- the tools ---------------------------------------------------------------


async def test_todo_write_stores_the_list_and_reports_it():
    result = await tool("todo_write").execute(
        todos=[{"text": "read the file"}, {"text": "change it", "status": "in_progress"}]
    )

    assert result.status is ToolResultStatus.SUCCESS, result.error
    assert "1. [ ] read the file" in result.output
    assert "2. [~] change it" in result.output
    assert result.summary == "0/2 tasks done"
    assert [todo.text for todo in current_state().todos] == ["read the file", "change it"]


async def test_todo_write_can_shrink_the_list():
    await tool("todo_write").execute(todos=[{"text": "a"}, {"text": "b"}, {"text": "c"}])
    await tool("todo_write").execute(todos=[{"text": "a"}])

    assert [todo.text for todo in current_state().todos] == ["a"]


async def test_an_empty_list_clears_the_plan():
    await tool("todo_write").execute(todos=[{"text": "a"}])
    result = await tool("todo_write").execute(todos=[])

    assert result.status is ToolResultStatus.SUCCESS
    assert current_state().todos == []
    assert "cleared" in result.output


@pytest.mark.parametrize(
    ("entry", "needle"),
    [
        ("not an object", "must be an object"),
        ({"status": "pending"}, "no text"),
        ({"text": "   "}, "no text"),
        ({"text": "x", "status": "almost"}, "almost"),
    ],
)
async def test_a_bad_item_is_refused_and_the_item_is_named(entry, needle):
    result = await tool("todo_write").execute(todos=[{"text": "fine"}, entry])

    assert result.status is ToolResultStatus.ERROR
    assert "2" in result.error, "the refusal did not say which item was wrong"
    assert needle in result.error


async def test_a_refused_write_leaves_the_previous_list_alone():
    """The failure mode that matters: a half-applied plan nobody wrote.

    Validation happens before anything is stored, so a list with one bad item
    changes nothing at all rather than storing its first four entries.
    """
    await tool("todo_write").execute(todos=[{"text": "keep me"}])
    before = current_state().to_dict()

    result = await tool("todo_write").execute(
        todos=[{"text": "one"}, {"text": "two"}, {"text": "bad", "status": "nope"}]
    )

    assert result.status is ToolResultStatus.ERROR
    assert current_state().to_dict() == before


async def test_a_task_longer_than_the_limit_is_refused():
    result = await tool("todo_write").execute(todos=[{"text": "x" * 500}])
    assert result.status is ToolResultStatus.ERROR
    assert "500" in result.error


async def test_create_goal_sets_it():
    result = await tool("create_goal").execute(objective="Make the retry idempotent")

    assert result.status is ToolResultStatus.SUCCESS
    assert current_state().goal == "Make the retry idempotent"
    assert current_state().goal_status == "active"


async def test_create_goal_refuses_to_overwrite_a_live_goal():
    """Silently replacing an objective drops work with nothing recording it."""
    await tool("create_goal").execute(objective="the first one")

    result = await tool("create_goal").execute(objective="something else")

    assert result.status is ToolResultStatus.ERROR
    assert "already an active goal" in result.error
    assert "the first one" in result.error
    assert "update_goal" in result.error, "the refusal did not say how to proceed"
    assert current_state().goal == "the first one"


async def test_create_goal_is_allowed_once_the_old_one_is_finished():
    await tool("create_goal").execute(objective="the first one")
    await tool("update_goal").execute(status="complete")

    result = await tool("create_goal").execute(objective="the second one")

    assert result.status is ToolResultStatus.SUCCESS
    assert current_state().goal == "the second one"


async def test_create_goal_needs_an_objective():
    result = await tool("create_goal").execute(objective="   ")
    assert result.status is ToolResultStatus.ERROR
    assert current_state().has_goal is False


async def test_get_goal_says_when_there_is_none():
    result = await tool("get_goal").execute()
    assert result.status is ToolResultStatus.SUCCESS
    assert "No goal set" in result.output


async def test_get_goal_reads_it_back():
    await tool("create_goal").execute(objective="Ship it")
    result = await tool("get_goal").execute()
    assert "Ship it" in result.output
    assert "active" in result.output


async def test_update_goal_completes():
    await tool("create_goal").execute(objective="Ship it")
    result = await tool("update_goal").execute(status="complete", note="done and tested")

    assert result.status is ToolResultStatus.SUCCESS
    assert current_state().goal_status == "complete"
    assert current_state().goal_note == "done and tested"


async def test_a_blocked_goal_must_say_what_it_is_blocked_on():
    """'Blocked' with no reason is the report that helps nobody: the next turn
    reads it, learns nothing, and either retries the same wall or stops for no
    stated cause."""
    await tool("create_goal").execute(objective="Ship it")

    result = await tool("update_goal").execute(status="blocked")

    assert result.status is ToolResultStatus.ERROR
    assert "blocked on" in result.error
    assert current_state().goal_status == "active", "the refusal still changed the state"

    ok = await tool("update_goal").execute(status="blocked", note="needs the API key")
    assert ok.status is ToolResultStatus.SUCCESS
    assert current_state().goal_status == "blocked"
    assert current_state().goal_note == "needs the API key"


async def test_update_goal_needs_a_goal_to_update():
    result = await tool("update_goal").execute(status="complete")
    assert result.status is ToolResultStatus.ERROR
    assert "no goal" in result.error.lower()


async def test_update_goal_refuses_an_unknown_state():
    await tool("create_goal").execute(objective="Ship it")
    result = await tool("update_goal").execute(status="nearly")
    assert result.status is ToolResultStatus.ERROR
    assert "nearly" in result.error


async def test_rewording_a_goal_keeps_why_it_was_blocked():
    await tool("create_goal").execute(objective="Fix it")
    await tool("update_goal").execute(status="blocked", note="waiting on review")

    await tool("update_goal").execute(status="blocked", objective="Fix the retry path")

    assert current_state().goal == "Fix the retry path"
    assert current_state().goal_note == "waiting on review"


# --- the tools and the session hold one object -------------------------------


def test_the_plan_reaches_the_system_prompt():
    session = AgentSession(bus=EventBus())
    session.state.set_goal("Ship the retry fix")
    session.state.replace_todos([Todo("write the test")])

    system = session._messages_with_system()[0]

    assert system.role_value == "system"
    assert "Ship the retry fix" in system.content
    assert "write the test" in system.content


def test_the_prompt_carries_no_plan_when_there_is_no_plan():
    """Nothing is appended past the rules every mode is sent.

    Was `content == session._mode.system_prompt`, and that equality is no longer
    the right shape: every mode's prompt now ends with the turn-economy rules
    (`test_turn_economy.py`), so the old assertion would have to be deleted --
    and deleting it would leave the *absence* it existed for unchecked. Written
    out in full, it fails for either mistake: a plan block that appeared, or
    rules that went missing.
    """
    session = AgentSession(bus=EventBus())
    system = session._messages_with_system()[0]

    assert session.state.render() == "", "there is a plan to be rendered"
    assert system.content == f"{session._mode.system_prompt}\n\n{TOOL_CALL_ECONOMY}"


async def test_a_tool_write_is_what_the_session_then_prompts_with():
    """The integration that can silently fail: a copy would look like it saved.

    The tool writes through `current_state()`; the session renders `self.state`. If
    those were two objects the write would report success, the card would show the
    new list, and the model would be sent the old one on the next turn.

    The session adopts its state explicitly with `set_state`: construction no
    longer repoints the global (see `test_subagent_isolation.py` -- a subagent
    built mid-turn must not steal the parent's plan), so the act that publishes
    is adoption, which is exactly what this test exercises.
    """
    session = AgentSession(bus=EventBus())
    session.set_state(session.state)

    await tool("todo_write").execute(todos=[{"text": "from a tool"}])

    assert [todo.text for todo in session.state.todos] == ["from a tool"]
    assert "from a tool" in session._messages_with_system()[0].content


def test_clearing_the_history_clears_the_plan():
    """A task list outliving the transcript it was written against describes work
    whose context has been thrown away -- and it would still be prompted."""
    session = AgentSession(bus=EventBus())
    session.state.set_goal("Ship it")
    session.state.replace_todos([Todo("a")])

    session.clear()

    assert session.state.is_empty()
    assert "Ship it" not in session._messages_with_system()[0].content


# --- persistence -------------------------------------------------------------


def _drive(requests, session=None, store=None, conversation_id=""):
    session = session or AgentSession(bus=EventBus())
    stdin = io.StringIO("\n".join(json.dumps(r) for r in requests) + "\n")
    stdout = io.StringIO()
    server = StdioServer(
        session, stdin, stdout, store=store, conversation_id=conversation_id
    )
    asyncio.run(server.serve())
    frames = [json.loads(line) for line in stdout.getvalue().splitlines() if line.strip()]
    return server, frames


def test_a_conversation_file_without_a_plan_still_opens(tmp_path):
    """Files written before the plan existed have no `state` key at all.

    All that has to survive is "does this old chat still open" -- the same rule the
    store already applies to message fields.
    """
    store = ConversationStore(tmp_path)
    conversation = store.create(title="old")
    path = tmp_path / f"{conversation.id}.json"

    data = json.loads(path.read_text(encoding="utf-8"))
    del data["state"]
    path.write_text(json.dumps(data), encoding="utf-8")

    loaded = store.load(conversation.id)
    assert loaded is not None
    assert loaded.state == {}

    # And a `state` that is not an object at all is the same as none.
    data["state"] = "not a dict"
    path.write_text(json.dumps(data), encoding="utf-8")
    loaded = store.load(conversation.id)
    assert loaded is not None
    assert loaded.state == {}


def test_the_plan_is_saved_into_the_conversation_file(tmp_path):
    store = ConversationStore(tmp_path)
    conversation = store.create(title="with a plan")
    conversation.state = SessionState(todos=[Todo("a")], goal="Ship it").to_dict()
    store.save(conversation)

    loaded = store.load(conversation.id)
    assert loaded is not None
    assert loaded.state["goal"] == "Ship it"


def test_duplicating_a_conversation_copies_its_plan(tmp_path):
    store = ConversationStore(tmp_path)
    original = store.create(title="original")
    original.state = SessionState(goal="Ship it").to_dict()
    store.save(original)

    clone = store.duplicate(original.id)

    assert clone is not None
    assert clone.state["goal"] == "Ship it"


def test_the_plan_survives_switching_away_and_back(tmp_path):
    """The end-to-end version: the two wiring points in the server.

    `_persist` has to bank the plan with the conversation being left, and
    `_load_into_session` has to adopt it on the way back. Either one missing gives a
    plan that saves and then reads as empty.
    """
    store = ConversationStore(tmp_path)
    first = store.create(title="first")
    second = store.create(title="second")

    server, _ = _drive([], store=store, conversation_id=first.id)
    server.session.state.set_goal("Ship the retry fix")
    server.session.state.replace_todos([Todo("write the test")])

    server._h_conversations_switch({"id": second.id})
    assert server.session.state.is_empty(), "the other chat inherited a plan"

    server._h_conversations_switch({"id": first.id})
    assert server.session.state.goal == "Ship the retry fix"
    assert [todo.text for todo in server.session.state.todos] == ["write the test"]


def test_plan_get_reports_the_plan_over_the_protocol():
    """So a panel can read it without scraping a tool result out of the transcript."""
    session = AgentSession(bus=EventBus())
    session.state.set_goal("Ship it")
    session.state.replace_todos([Todo("a", "completed"), Todo("b")])

    _, frames = _drive(
        [{"id": 1, "method": "plan.get"}], session=session
    )

    result = frames[0]["result"]
    assert result["plan"]["goal"] == "Ship it"
    assert len(result["plan"]["todos"]) == 2
    assert result["summary"] == "goal: active \u00b7 1/2 tasks done"
    assert "Ship it" in result["rendered"]


def test_plan_get_is_an_empty_plan_rather_than_an_error_when_there_is_none():
    _, frames = _drive([{"id": 1, "method": "plan.get"}])
    result = frames[0]["result"]
    assert result["plan"]["todos"] == []
    assert result["rendered"] == ""


# --- the tools as the model sees them ----------------------------------------


def test_the_planning_tools_are_offered_in_every_mode():
    """Writing down a plan changes no file, and Plan mode is where a plan belongs."""
    from tonyagent.core.modes import MODES

    for name in ("todo_write", "create_goal", "get_goal", "update_goal"):
        for mode in MODES.values():
            assert name in mode.allowed_tools, f"{name} missing from {mode.name}"


def test_the_status_enums_are_advertised():
    from tonyagent.tools.schemas import SCHEMAS_BY_NAME

    todos = SCHEMAS_BY_NAME["todo_write"]["parameters"]["properties"]["todos"]
    assert todos["items"]["properties"]["status"]["enum"] == list(TODO_STATUSES)
    statuses = SCHEMAS_BY_NAME["update_goal"]["parameters"]["properties"]["status"]
    assert set(statuses["enum"]) == {"active", "complete", "blocked"}


def test_the_planning_tools_need_no_project_folder():
    for name in ("todo_write", "create_goal", "get_goal", "update_goal"):
        assert tool(name).folder_required is False, name
        assert tool(name).destructive is False, name
        assert tool(name).requires_confirmation is False, name
