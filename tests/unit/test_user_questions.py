"""The two tools that reach the user: asking a question, and showing something.

The plumbing and the products are tested separately, because they fail
differently. A plumbing bug looks like a turn that hangs or a dialog that never
comes down; a product bug looks like a model that asks nothing, or asks about
everything. And the failure this feature has that no other tool has is
*stranding* a turn, so the timeout and the cancelled-turn paths are asserted as
carefully as the happy one.
"""

from __future__ import annotations

import asyncio
import json

import pytest

import tonyagent.tools  # noqa: F401 -- importing registers every tool
from tonyagent.core import user_io
from tonyagent.core.modes import MODES
from tonyagent.tools import tool_orchestrator, tool_registry
from tonyagent.tools.base import ToolResultStatus


@pytest.fixture(autouse=True)
def nobody_listening():
    """No user is attached unless a test attaches one.

    Both hooks are process-wide, like the session's confirmation callback: a
    test that left one installed would have the next test's "nothing is
    listening" case find a listener and pass for the wrong reason.
    """
    user_io.reset()
    yield
    user_io.reset()


@pytest.fixture
def listener():
    """Attach a user, and record what they were asked and what answered."""
    asked: list[user_io.QuestionRequest] = []
    resolved: list[tuple[str, str | None]] = []

    user_io.set_callbacks(asked.append, lambda i, a: resolved.append((i, a)))
    return asked, resolved


@pytest.fixture
def short_timeout(monkeypatch):
    """A 50ms ask timeout, so a silence test costs 50ms rather than 60s."""
    monkeypatch.setattr(user_io, "ASK_TIMEOUT_S", 0.05)


async def _until(predicate, timeout: float = 5.0) -> None:
    """Wait for something an event-loop task has to do to happen.

    Bounded in seconds, not in yields. Counting ``asyncio.sleep(0)`` calls
    instead made this fail at 200 of them on a busy machine -- a failure about
    the test machine that reads exactly like a turn that never asked its
    question, which is the one failure this file most needs to detect honestly.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not predicate():
        if loop.time() >= deadline:
            raise AssertionError("the expected thing did not happen")
        await asyncio.sleep(0)


def _tool(name: str):
    found = tool_registry.get(name)
    assert found is not None, f"{name} is not registered"
    return found


# --- the round trip ---------------------------------------------------------


async def test_a_question_round_trips_through_the_user(listener):
    asked, resolved = listener
    task = asyncio.create_task(
        user_io.ask(
            kind="question",
            prompt="Postgres or SQLite?",
            options=["Postgres", "SQLite"],
            tool_name="ask_user_question",
        )
    )
    await _until(lambda: asked)

    assert len(asked) == 1
    assert asked[0].kind == "question"
    assert asked[0].prompt == "Postgres or SQLite?"
    assert asked[0].options == ["Postgres", "SQLite"]
    assert asked[0].tool_name == "ask_user_question"
    assert user_io.pending_count() == 1

    assert user_io.respond(asked[0].id, "Postgres") is True
    assert await task == "Postgres"

    # Settled, out of the table, and announced. All three, or a window is left
    # holding a dialog for a question that was already answered -- and the
    # pending table grows for the life of the process.
    assert resolved == [(asked[0].id, "Postgres")]
    assert user_io.pending_count() == 0


async def test_an_answer_of_nothing_is_still_an_answer(listener):
    asked, resolved = listener
    task = asyncio.create_task(
        user_io.ask(kind="question", prompt="Which one?", tool_name="ask_user_question")
    )
    await _until(lambda: asked)
    assert user_io.respond(asked[0].id, "") is True
    assert await task == ""
    assert resolved == [(asked[0].id, "")]


async def test_a_late_answer_finds_nothing_to_answer(listener):
    """A reply for a question nobody holds is a no-op, not an error.

    The window clears its dialog on the way out, so the reply can arrive after
    the ask has already timed out. That is the normal end of a race.
    """
    asked, _ = listener
    assert user_io.respond("not-a-question", "yes") is False
    task = asyncio.create_task(user_io.ask(kind="question", prompt="Ready?"))
    await _until(lambda: asked)
    assert user_io.respond(asked[0].id, "one") is True
    await task
    # Twice: the second finds the future already resolved.
    assert user_io.respond(asked[0].id, "two") is False


async def test_nobody_listening_refuses_without_waiting():
    """A bare session has no user, and must not pay the timeout to find out.

    Waiting 60 seconds to report "there is nobody to ask" would make every
    headless run cost a minute per question -- for a condition that was knowable
    before the ask was made.
    """
    with pytest.raises(user_io.UserUnavailable):
        await asyncio.wait_for(
            user_io.ask(kind="question", prompt="Anyone there?"), timeout=1.0
        )
    assert user_io.pending_count() == 0
    assert user_io.is_listening() is False


async def test_a_question_nobody_answers_times_out_and_takes_itself_down(
    listener, short_timeout
):
    asked, resolved = listener
    with pytest.raises(user_io.UserSilent) as raised:
        await user_io.ask(kind="question", prompt="Still there?")
    # The dialog comes down on the timeout, or the window holds a modal over a
    # turn that has already moved on.
    assert resolved == [(asked[0].id, None)]
    assert user_io.pending_count() == 0
    # The message tells the model what to do about it, which is the only thing
    # it can act on: state an assumption and carry on, or stop.
    assert "assumption" in str(raised.value)


async def test_a_cancelled_turn_settles_the_ask_and_leaves_nothing_behind(listener):
    asked, resolved = listener
    task = asyncio.create_task(user_io.ask(kind="question", prompt="Interrupted?"))
    await _until(lambda: asked)

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert resolved == [(asked[0].id, None)]
    assert user_io.pending_count() == 0


# --- the tools themselves ---------------------------------------------------


async def test_the_question_tool_reports_the_answer_it_was_given(listener):
    asked, _ = listener
    task = asyncio.create_task(
        _tool("ask_user_question").execute(
            question="  Which database?  ", options=["Postgres", "SQLite"]
        )
    )
    await _until(lambda: asked)
    assert user_io.respond(asked[0].id, "Postgres") is True
    result = await task

    assert result.status is ToolResultStatus.SUCCESS
    assert result.output == 'The user answered: "Postgres"'
    # A card needs one line, and "asked" is the verb that says what happened.
    assert result.summary == "asked: Which database?"
    # Whitespace collapsed in what the user is shown, so the question is a
    # sentence rather than an indented block.
    assert asked[0].prompt == "Which database?"


async def test_a_declined_question_succeeds_and_says_what_to_do(listener):
    asked, _ = listener
    task = asyncio.create_task(
        _tool("ask_user_question").execute(question="May I delete the old build?")
    )
    await _until(lambda: asked)
    assert user_io.respond(asked[0].id, "") is True
    result = await task

    # Success, not a failure: the user answered, and "no comment" is an answer
    # the model can act on. Reporting it as an error would teach it that asking
    # is a way to fail a turn.
    assert result.status is ToolResultStatus.SUCCESS
    assert "chose not to answer" in result.output
    assert "Do not ask again" in result.output


async def test_a_question_nobody_answers_fails_the_call(listener, short_timeout):
    asked, _ = listener
    result = await _tool("ask_user_question").execute(question="Still there?")
    assert result.status is ToolResultStatus.ERROR
    assert "No answer arrived" in result.error


async def test_a_question_with_nobody_listening_is_refused_at_once():
    """The refusal names the condition, so the model knows to carry on alone."""
    result = await _tool("ask_user_question").execute(question="Anyone there?")
    assert result.status is ToolResultStatus.ERROR
    assert "no user to ask" in result.error


@pytest.mark.parametrize(
    "kwargs, expected",
    [
        ({"question": ""}, "needs a question"),
        ({"question": "   "}, "needs a question"),
        ({"question": "x" * 1001}, "nobody reads"),
        ({"question": "Which?", "options": ["a", ""]}, "is empty"),
        ({"question": "Which?", "options": ["a", "a"]}, "listed twice"),
        ({"question": "Which?", "options": ["a" * 201]}, "buttons, not paragraphs"),
        ({"question": "Which?", "options": [str(i) for i in range(7)]}, "more than anyone"),
    ],
)
async def test_a_question_the_dialog_could_not_show_is_refused(kwargs, expected):
    """Refused in the model's own words, before anything is shown.

    The duplicate option is the one worth naming: two buttons saying the same
    thing make the answer ambiguous, and the ambiguity only shows up when the
    user picks one.
    """
    result = await _tool("ask_user_question").execute(**kwargs)
    assert result.status is ToolResultStatus.ERROR
    assert expected in result.error


async def test_the_presentation_tool_reports_a_note(listener):
    asked, _ = listener
    task = asyncio.create_task(
        _tool("present").execute(content="Line one\nLine two", title="The plan")
    )
    await _until(lambda: asked)
    assert asked[0].kind == "presentation"
    assert asked[0].prompt == "The plan"
    assert asked[0].content == "Line one\nLine two"
    assert asked[0].options == []

    assert user_io.respond(asked[0].id, "Use the second option") is True
    result = await task
    assert result.status is ToolResultStatus.SUCCESS
    assert result.output == 'The user responded: "Use the second option"'


async def test_a_presentation_nobody_answered_still_succeeds(listener, short_timeout):
    """The one asymmetry in this feature, and the reason for it.

    A question got nothing, so the call failed. A presentation *delivered* --
    the content is on their screen whether or not they have come back to it --
    so reporting failure would teach the model that showing its work is an
    error.
    """
    asked, _ = listener
    result = await _tool("present").execute(content="Here is what I found.")
    assert result.status is ToolResultStatus.SUCCESS
    assert "have not responded" in result.output
    assert result.summary.startswith("presented, no reply:")
    assert asked


async def test_a_presentation_with_nobody_listening_fails():
    """Nothing was shown, so nothing was delivered. Reporting the opposite
    would tell the model its work had been seen."""
    result = await _tool("present").execute(content="Nobody is here.")
    assert result.status is ToolResultStatus.ERROR
    assert "no user to ask" in result.error


async def test_a_presentation_with_no_content_is_refused():
    result = await _tool("present").execute(content="   ")
    assert result.status is ToolResultStatus.ERROR
    assert "needs content" in result.error


async def test_a_presentation_over_the_limit_points_at_a_file():
    result = await _tool("present").execute(content="x" * 20001)
    assert result.status is ToolResultStatus.ERROR
    assert "Write it to a file" in result.error


# --- where they sit in the rest of the system --------------------------------


def test_both_tools_are_offered_in_every_mode():
    """Plan most of all: a plan is what Plan mode exists to hand over.

    A tool in no mode's allow-list is a tool the model is never shown and the
    orchestrator would refuse -- which for these two would read as the app
    being unable to ask the user anything, with no error anywhere.
    """
    for mode in MODES.values():
        assert "ask_user_question" in mode.allowed_tools, mode.name
        assert "present" in mode.allowed_tools, mode.name


def test_a_question_keeps_a_tool_batch_serial():
    """`will_prompt` is the one answer to "will this ask the user?".

    The session reads it to decide whether a batch may run concurrently, so a
    question answered `False` here would put a dialog on screen beside a tool
    still streaming -- two things fighting for the window the user is reading.
    """
    for name in ("ask_user_question", "present"):
        assert tool_orchestrator.will_prompt(name, {}) is True


async def test_a_question_is_not_routed_through_the_destructive_confirmation(
    listener,
):
    """The bug `will_prompt` alone would have shipped.

    `will_prompt` answers True for a question, and the executor used to read that
    same method to decide whether to raise the destructive-tool confirmation. A
    question therefore arrived as "Confirm tool execution / Allow / Deny" and
    only after Allow as the question itself -- two modals for one blocked turn,
    the first about nothing. It passed every test run alone, because a test with
    no confirmation callback installed takes the "nothing to ask" branch and the
    question goes straight through.

    So: a confirmation callback installed, and the question must still not
    produce one. Fails fast rather than waiting out the 60s timeout the bug
    would have cost.
    """
    from tonyagent.tools import ToolCall

    asked, _ = listener
    confirmations: list = []

    tool_orchestrator.set_confirmation_callback(confirmations.append)
    try:
        task = asyncio.create_task(
            tool_orchestrator.execute_tool_async(
                ToolCall(
                    id="c1",
                    name="ask_user_question",
                    arguments={"question": "Postgres or SQLite?"},
                )
            )
        )
        await _until(lambda: asked or confirmations)
        assert confirmations == [], (
            "the question went through the destructive-tool confirmation dialog"
        )
        assert asked, "the question never reached the user"
        assert user_io.respond(asked[0].id, "Postgres") is True
        result = await task
        assert result.status is ToolResultStatus.SUCCESS
        assert result.output == 'The user answered: "Postgres"'
    finally:
        tool_orchestrator.set_confirmation_callback(None)


def test_trust_and_full_do_not_silence_a_question():
    """`skips_confirmation` is about approvals of destructive work.

    A user who said "stop interrupting me" about file writes has not said "never
    ask me anything" -- so a question must not inherit that decision.
    """
    from tonyagent.core.modes import PERMISSIONS, get_mode

    previous_mode = tool_orchestrator._mode
    previous_permission = tool_orchestrator._permission
    try:
        tool_orchestrator.set_mode(get_mode("build"))
        tool_orchestrator.set_permission(PERMISSIONS["full"])
        tool_orchestrator.set_trusted("some/project", True)
        assert tool_orchestrator.will_prompt("ask_user_question", {}) is True
        assert tool_orchestrator.will_prompt("present", {}) is True
    finally:
        tool_orchestrator.set_permission(previous_permission)
        tool_orchestrator.set_mode(previous_mode)


def test_neither_tool_needs_a_project_folder():
    """A question about what the user wants does not read a file.

    The same exception the network tools made: the orchestrator refuses
    `folder_required` tools with no folder chosen, which for these two would
    refuse the one call that works perfectly well on a bare session.
    """
    for name in ("ask_user_question", "present"):
        tool = _tool(name)
        assert tool.folder_required is False, name
        assert tool.destructive is False, name
        assert tool.requires_confirmation is False, name
        assert tool.asks_user is True, name


def test_the_new_flag_is_not_advertised_to_the_model():
    """`describe()` is the contract the model and `tools.get` are shown.

    `asks_user` is the orchestrator's scheduling information and stays out of
    it -- so the descriptor keeps the fixed shape the wire format test asserts,
    and a frontend reading `tools.get` is not told something it must explain.
    """
    for name in ("ask_user_question", "present"):
        assert "asks_user" not in _tool(name).describe()


def test_the_ask_timeout_is_the_one_the_confirmation_uses():
    """One bound a user can learn, so the two waiting dialogs agree.

    The orchestrator's destructive-tool confirmation waits the same 60 seconds;
    if these drifted apart, "the app is waiting for me" would mean two
    different lengths of time depending on which dialog was up.
    """
    assert user_io.ASK_TIMEOUT_S == 60.0


def test_both_tools_are_registered_and_wired():
    """Declared once, derived twice: the registry and the advertised list."""
    from tonyagent.tools import ALL_SCHEMAS

    names = tool_registry.list_names()
    assert "ask_user_question" in names
    assert "present" in names
    advertised = {schema["name"] for schema in ALL_SCHEMAS}
    assert {"ask_user_question", "present"} <= advertised


def test_the_tool_count_is_a_tripwire():
    """The registry's size, so adding a tool is a diff you read.

    The same shape as the tripwire in `test_tool_wire_format.py`: the set
    assertions prove the wiring, and this makes the count something that is
    noticed rather than discovered. 34 -> 37 for the Phase 5 subagent tools,
    37 -> 39 for the Phase 6 workflow verbs `send_message` and
    `subagent_fork`, and 39 -> 41 for the Phase 7 pair `list_skills` and
    `run_skill` (read-only, so they are in every mode's set).
    """
    assert len(tool_registry.list_names()) == 41


async def test_the_session_publishes_an_ask_and_settles_it_on_the_answer():
    """The bridge, end to end: a tool asks, the window is told, the tool is
    answered by the same method the frontend's request lands in."""
    from tonyagent.core.events import EventBus, EventType
    from tonyagent.core.session import AgentSession

    session = AgentSession(bus=EventBus())
    seen: list = []
    session.bus.subscribe(seen.append)
    session.install_question_bridge()
    assert user_io.is_listening() is True

    task = asyncio.create_task(
        _tool("ask_user_question").execute(
            question="Which branch?", options=["main", "dev"]
        )
    )
    await _until(lambda: any(e.type == EventType.USER_ASKED for e in seen))
    asked = [e for e in seen if e.type == EventType.USER_ASKED][0]
    # The payload is the wire contract; see `QuestionRequest.to_payload`.
    assert asked.payload["kind"] == "question"
    assert asked.payload["name"] == "ask_user_question"
    assert asked.payload["prompt"] == "Which branch?"
    assert asked.payload["options"] == ["main", "dev"]

    question_id = asked.payload["id"]
    assert session.respond_to_question(question_id, "dev") is True
    result = await task
    assert result.output == 'The user answered: "dev"'

    settled = [e for e in seen if e.type == EventType.USER_RESOLVED]
    assert settled, "the ask was never taken down in the window"
    assert settled[-1].payload["id"] == question_id
    assert settled[-1].payload["answered"] is True

    # A late reply finds nothing, and says so rather than raising.
    assert session.respond_to_question(question_id, "again") is False


async def test_a_question_inside_a_real_turn_is_answered_and_carries_on():
    """The whole turn, not just the tool.

    The tool only blocks when something is awaiting it inside the turn's task, so
    this is the test that can see the one failure no tool-level test can: a turn
    that never finishes because nothing answered the question it asked. It runs
    with both bridges installed, because that is what a real run has, and pins
    three things: the question is asked *once* (not behind an approval dialog
    first), the answer lands in the transcript as JSON the model reads, and the
    turn carries on to a real answer instead of stopping at the tool.
    """
    from tonyagent.core.events import EventBus, EventType
    from tonyagent.core.session import AgentSession
    from tonyagent.providers import ChatCompletionChunk
    from tonyagent.tools import tool_orchestrator

    class _Provider:
        """One pass that asks a question, then one that answers."""

        def __init__(self):
            self.passes = 0

        def estimate_tokens(self, messages):
            return 11

        async def chat_completion(self, messages=None, tools=None, tool_choice=None,
                                  stream=False, **kw):
            self.passes += 1

            async def gen():
                if self.passes == 1:
                    yield ChatCompletionChunk(
                        tool_calls=[{
                            "id": "c1",
                            "function": {
                                "name": "ask_user_question",
                                "arguments": json.dumps(
                                    {
                                        "question": "Postgres or SQLite?",
                                        "options": ["Postgres", "SQLite"],
                                    }
                                ),
                            },
                        }],
                        finish_reason="tool_calls",
                    )
                    return
                yield ChatCompletionChunk(content="Using Postgres.", finish_reason="stop")

            return gen()

    session = AgentSession(bus=EventBus())
    session.provider = _Provider()
    session.model = "stub"
    # The wiring a real run has: the question bridge puts the ask on the bus,
    # and the confirmation bridge is what every other tool's approval already
    # goes through. Both installed, because the thing being watched for here is
    # the question being asked *once* -- routed through the question dialog and
    # not first through an approval dialog about nothing.
    session.install_question_bridge()
    session.install_confirmation_bridge()

    # The orchestrator is a module global with no teardown of its own, so
    # whatever the test before this one left on it is what this turn runs with.
    # Unrestricted is the default and the only state this test can assume, so it
    # is set explicitly -- otherwise this test passes alone and fails in a full
    # run, which is the worst way for a test to fail. All three are put back, so
    # this test does not become the one that pollutes the next.
    held = (
        tool_orchestrator._mode,
        tool_orchestrator._permission,
        tool_orchestrator._confirmation_callback,
    )
    tool_orchestrator.set_mode(None)
    tool_orchestrator.set_permission(None)

    seen: list = []
    session.bus.subscribe(seen.append)

    # The question is asked from inside the turn, so the answer has to come from
    # a task of its own: awaiting the turn would be awaiting the very thing that
    # has to answer it. The ask is waited for on the event bus, which is the
    # bridge the session installed over the top of any test listener.
    turn = asyncio.create_task(session.run_turn("set up the database"))
    try:
        await _until(lambda: any(e.type == EventType.USER_ASKED for e in seen))
    except AssertionError:
        # The turn is the thing being diagnosed. Take it down with the assertion
        # rather than leaving it blocked on a question nothing will answer.
        turn.cancel()
        raise
    finally:
        tool_orchestrator.set_mode(held[0])
        tool_orchestrator.set_permission(held[1])
        tool_orchestrator.set_confirmation_callback(held[2])

    asked = [e for e in seen if e.type == EventType.USER_ASKED][0]
    assert asked.payload["kind"] == "question"
    assert asked.payload["prompt"] == "Postgres or SQLite?"
    assert asked.payload["options"] == ["Postgres", "SQLite"]
    # The one gate a question must not be behind: the approval dialog. With the
    # confirmation bridge installed, the alternative to this assertion is a turn
    # that waits 60s for an Allow nobody is going to give it.
    assert not [e for e in seen if e.type == EventType.CONFIRMATION_REQUESTED], (
        "the question was routed through the destructive-tool confirmation dialog"
    )

    assert session.respond_to_question(asked.payload["id"], "Postgres") is True
    await turn

    tools = [m for m in session.messages if m.role.value == "tool"]
    assert len(tools) == 1
    # The stored tool message is JSON, so read it rather than substring it.
    assert json.loads(tools[0].content)["output"] == 'The user answered: "Postgres"'

    answers = [
        m.content for m in session.messages if m.role.value == "assistant" and m.content
    ]
    assert any("Using Postgres." in text for text in answers), (
        "the turn stopped at the question instead of carrying on"
    )
