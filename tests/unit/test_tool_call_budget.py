"""The per-turn tool call budget: what it counts, and what it says.

The cap used to be ``MAX_TOOL_ROUNDS``, which counted assistant passes. That
number looked like a bound and was not one: a model asking for five tools in a
single message spent one round, so it could run thirty tools for the price of
six. The budget now counts individual calls, and every tool result carries
``Tool call N/M`` so the model and the reader can both see where the turn
stands.

Two properties are load-bearing and neither is obvious from the code:

* A call the budget refuses is still *answered*. The assistant message above it
  already declared the call in its ``tool_calls`` array, and an
  OpenAI-compatible endpoint rejects a declared call with no matching result.
  Dropping the refused ones would turn a finished turn into a 400 on the next
  message.
* A failing tool still spends a call. The model asked for it and the request
  went out; counting only successes would make a loop of failures free.

These tests drive the real ``_run_tool_calls`` and stub only the executor below
it. An earlier draft stubbed the loop too, and the stubs silently omitted its
refusal flag -- so the turn ran to the round backstop and the tests were
asserting on a loop that no longer existed. There is one loop; the tests use
it.
"""

import asyncio
import json

import pytest

from tonyagent.core.events import EventBus, EventType
from tonyagent.core.session import AgentSession
from tonyagent.providers import ChatCompletionChunk
from tonyagent.tools import tool_orchestrator
from tonyagent.tools.base import ToolResult, ToolResultStatus


@pytest.fixture
def executor(monkeypatch):
    """Record what the session asked to run, and answer every call.

    The tool itself is the only thing stubbed. Yields the list of tool names
    the session decided to run, which is the honest record of "what did this
    turn actually spend its budget on".
    """
    ran: list[str] = []

    async def fake_execute(call):
        ran.append(call.name)
        return ToolResult(status=ToolResultStatus.SUCCESS, output="ok")

    monkeypatch.setattr(tool_orchestrator, "execute_tool_async", fake_execute)
    return ran


@pytest.fixture
def failing_executor(monkeypatch):
    """Every call fails, which is the case the budget must still charge for."""
    async def fake_execute(call):
        return ToolResult(status=ToolResultStatus.ERROR, error="nope")

    monkeypatch.setattr(tool_orchestrator, "execute_tool_async", fake_execute)


def _provider_returning(batches):
    """A provider that walks `batches`, one list of tool calls per pass.

    The last batch repeats, so a turn that keeps asking runs out of budget
    rather than out of material.
    """

    class _Provider:
        def __init__(self):
            self.passes = 0

        def estimate_tokens(self, messages):
            return 42

        async def chat_completion(self, messages=None, tools=None, tool_choice=None,
                                  stream=False, **kw):
            index = min(self.passes, len(batches) - 1)
            self.passes += 1
            calls = batches[index]

            async def gen():
                if not calls:
                    yield ChatCompletionChunk(content="all done",
                                              finish_reason="stop")
                    return
                yield ChatCompletionChunk(tool_calls=calls, finish_reason="tool_calls")

            return gen()

    return _Provider()


def _call(name, call_id):
    return {"id": call_id, "function": {"name": name, "arguments": "{}"}}


def _session(batches, max_tool_calls=10):
    session = AgentSession(bus=EventBus())
    session.provider = _provider_returning(batches)
    session.model = "stub"
    session.max_tool_calls = max_tool_calls
    return session


async def _run(session, text="go"):
    seen = []
    session.bus.subscribe(seen.append)
    await session.run_turn(text)
    return seen


def _tool_results(session):
    """The tool messages, oldest first."""
    return [m for m in session.messages if m.role.value == "tool"]


def _declared_calls(session):
    """How many tool calls the assistant messages asked for in total."""
    return sum(
        len(m.tool_calls)
        for m in session.messages
        if m.role_value == "assistant" and m.tool_calls
    )


# --- what the number counts ------------------------------------------------
class TestWhatIsCounted:
    async def test_parallel_calls_in_one_message_each_cost_one(self, executor):
        """The bug the old cap had: three tools in one message cost one round."""
        session = _session([[_call("a", "c1"), _call("b", "c2"), _call("c", "c3")], []])

        await _run(session)

        assert executor == ["a", "b", "c"], (
            "a batch of three tools must spend three calls, not one round"
        )
        assert session._tool_calls_used == 3

    async def test_a_second_batch_spends_more_of_the_budget(self, executor):
        session = _session([
            [_call("a", "c1"), _call("b", "c2")],
            [_call("c", "c3")],
            [],
        ])

        await _run(session)

        assert executor == ["a", "b", "c"]
        assert session._tool_calls_used == 3

    async def test_the_counter_starts_from_zero_on_every_turn(self, executor):
        """A second turn gets the whole budget, not what the first left."""
        session = _session([[_call("a", "c1")], []])

        await _run(session, "first")
        assert session._tool_calls_used == 1

        await _run(session, "second")
        # The second turn asked for nothing, but the counter was reset first.
        # Without the reset a long session would start refusing tools for no
        # reason at all.
        assert session._tool_calls_used == 0

    async def test_a_failing_tool_still_spends_a_call(self, failing_executor):
        """Otherwise a loop of failing tools costs nothing and never stops."""
        session = _session([[_call("boom", "c1")]], max_tool_calls=2)

        await _run(session)

        assert session._tool_calls_used == 2, (
            "a tool that failed still cost a call, so a loop of failures "
            "cannot spend the budget for free"
        )


# --- what the result says --------------------------------------------------
class TestTheLabel:
    def test_the_label_is_tool_call_n_of_m(self):
        session = _session([[]])
        session._tool_calls_used = 3
        assert session._tool_budget_label() == "Tool call 3/10"

    def test_the_payload_carries_the_number_the_model_reads(self):
        session = _session([[]])
        session._tool_calls_used = 7
        payload = session._budget_payload()
        assert payload["index"] == 7
        assert payload["limit"] == 10
        assert payload["label"] == "Tool call 7/10"

    async def test_the_budget_travels_on_the_tool_completed_event(self, executor):
        """The UI reads the same field the model does, so they cannot disagree."""
        session = _session([[_call("read_file", "c1")], []])

        seen = await _run(session)

        completed = [e for e in seen if e.type == EventType.TOOL_COMPLETED]
        assert completed, "no tool result reached the frontend"
        assert completed[0].payload["tool_call_budget"]["label"] == "Tool call 1/10"

    async def test_the_budget_is_in_the_result_the_model_reads(self, executor):
        session = _session([[_call("a", "c1")], []])

        await _run(session)

        result = json.loads(_tool_results(session)[0].content)
        assert result["tool_call_budget"]["label"] == "Tool call 1/10"

    async def test_each_result_carries_its_own_number(self, executor):
        session = _session([
            [_call("a", "c1"), _call("b", "c2")],
            [_call("c", "c3")],
            [],
        ])

        await _run(session)

        labels = [
            json.loads(m.content)["tool_call_budget"]["label"]
            for m in _tool_results(session)
        ]
        assert labels == ["Tool call 1/10", "Tool call 2/10", "Tool call 3/10"]


# --- running out -----------------------------------------------------------
class TestRunningOut:
    async def test_the_call_after_the_last_one_is_refused(self, executor):
        session = _session(
            [[_call("a", "c1"), _call("b", "c2"), _call("c", "c3")], []],
            max_tool_calls=2,
        )

        await _run(session)

        assert executor == ["a", "b"], "the third call ran past the budget"
        assert session._tool_calls_used == 2

    async def test_every_declared_call_is_answered(self, executor):
        """The wire stays valid: no declared call is left without a result.

        An assistant message carrying three `tool_calls` needs three tool
        messages after it, or the next request is a 400. The refused third
        call is therefore answered with a refusal, not dropped.
        """
        session = _session(
            [[_call("a", "c1"), _call("b", "c2"), _call("c", "c3")], []],
            max_tool_calls=2,
        )

        await _run(session)

        results = _tool_results(session)
        assert _declared_calls(session) == 3
        assert len(results) == 3, (
            "a declared tool call went unanswered, which the next request "
            "would reject"
        )
        # The ids line up one-for-one, which is the part that must not drift.
        assert [m.tool_call_id for m in results] == ["c1", "c2", "c3"]

    async def test_the_refusal_is_a_result_the_model_can_read(self, executor):
        session = _session([[_call("a", "c1"), _call("b", "c2")], []],
                           max_tool_calls=1)

        await _run(session)

        refused = json.loads(_tool_results(session)[-1].content)
        assert refused["status"] == "error"
        # The model is reading this. A bare "error" leaves it to guess whether
        # retrying is worthwhile, which is how a loop starts.
        assert "Tool call 1/1" in refused["error"]
        assert "budget" in refused["error"].lower()

    async def test_the_refusal_reaches_the_frontend_too(self, executor):
        """So the card can be drawn failed, rather than left spinning."""
        session = _session([[_call("a", "c1"), _call("b", "c2")], []],
                           max_tool_calls=1)

        seen = await _run(session)

        completed = [e for e in seen if e.type == EventType.TOOL_COMPLETED]
        assert len(completed) == 2
        assert completed[-1].payload["result"]["status"] == "error"

    async def test_running_out_says_so_in_words_a_user_can_act_on(self, executor):
        session = _session([[_call("a", "c1")]], max_tool_calls=1)

        seen = await _run(session)

        errors = [e for e in seen if e.type == EventType.ERROR]
        assert errors, "the budget ran out and nothing said so"
        message = errors[-1].payload["message"]
        assert "1 tool call" in message
        assert "Tool call 1/1" in message
        # It ends as a finished turn, not a crash.
        assert any(e.type == EventType.TURN_FINISHED for e in seen)

    async def test_a_turn_inside_its_budget_reports_no_error(self, executor):
        session = _session([[_call("a", "c1")], []], max_tool_calls=10)

        seen = await _run(session)

        assert not [e for e in seen if e.type == EventType.ERROR], (
            "a turn that stayed inside its budget complained anyway"
        )

    async def test_the_model_gets_one_last_pass_to_answer(self, executor):
        """A spent budget stops tools, not the answer.

        The whole point of the budget is to stop the model *spending*, and a
        model that cannot answer at all is not a saving. So the turn still
        gives it a pass to summarise from the result it has; only a further
        tool call is refused, and that refusal is what ends the turn.
        """
        session = _session([[_call("a", "c1")]], max_tool_calls=1)

        await _run(session)

        assert session.provider.passes == 2, (
            "the model never got to answer from the one call it was allowed"
        )
        # The second pass asked again and was refused, so it ran nothing.
        assert executor == ["a"], "a tool ran after the budget was spent"

    async def test_the_turn_ends_once_a_call_is_refused(self, executor):
        session = _session([[_call("a", "c1")]], max_tool_calls=1)

        await _run(session)

        assert session.provider.passes == 2, (
            "the turn kept asking after the budget had already refused a call"
        )

    async def test_the_history_ends_on_an_assistant_turn(self, executor):
        """The digest still closes a turn that ended on tool results."""
        session = _session([[_call("a", "c1")], []], max_tool_calls=10)

        await _run(session)

        assert session.messages[-1].role.value == "assistant"


# --- the loop cannot hang --------------------------------------------------
class TestTheBackstop:
    async def test_a_gateway_that_only_asks_for_nameless_calls_terminates(self):
        """A hang, not a slow turn, and reachable from a malformed response.

        A call with no name is skipped without being counted, so it would
        never spend a call of the budget. The round backstop is what ends it.
        """
        session = _session([[{"id": "c1", "function": {"arguments": "{}"}}]])

        seen = await _run(session)

        assert any(e.type == EventType.TURN_FINISHED for e in seen), (
            "the turn never ended; a nameless tool call spun the loop"
        )
        # And it said why, rather than stopping without a word.
        errors = [e for e in seen if e.type == EventType.ERROR]
        assert errors, "the backstop ended the turn silently"

    def test_the_backstop_is_wider_than_the_default_budget(self):
        """A turn that spends its whole budget must never reach the backstop.

        If these two numbers ever crossed, a legitimate turn would be cut off
        by the wrong limit and the error would name a budget it never hit.
        """
        assert AgentSession.MAX_TOOL_ROUNDS > 10, (
            "the round backstop must be wider than the default tool budget"
        )


# --- where the number comes from -------------------------------------------
class TestTheSetting:
    def test_the_default_comes_from_settings(self):
        assert AgentSession(bus=EventBus()).max_tool_calls == 10

    def test_the_floor_is_one_call(self, monkeypatch):
        """Zero would refuse every tool, which is a different product.

        A turn with no tools is expressed by the model list, not by a budget
        of zero, so a zero in the config is a mistake to correct rather than
        an instruction to obey.
        """
        from tonyagent.config.settings import settings

        monkeypatch.setattr(settings.tools, "max_tool_calls", 0)
        assert AgentSession(bus=EventBus()).max_tool_calls == 1

    def test_the_environment_can_raise_it(self, monkeypatch):
        from tonyagent.config.settings import settings

        monkeypatch.setattr(settings.tools, "max_tool_calls", 42)
        assert AgentSession(bus=EventBus()).max_tool_calls == 42


# --- the RPC the settings icon writes to ------------------------------------
class TestTheRpc:
    """`tools.get` / `tools.set`, which the composer's budget icon calls.

    The icon lives in the composer rather than the settings panel because the
    budget is a per-turn decision, which means it is changed *often* and during
    a conversation. So the write path matters as much as the read path: a value
    the control painted and the core refused would leave the window and the
    tool cards disagreeing about the same number.
    """

    def _drive(self, requests, session=None):
        import io
        import json

        from tonyagent.core.events import EventBus
        from tonyagent.headless.server import StdioServer

        session = session or _session([[]])
        stdin = io.StringIO("\n".join(json.dumps(r) for r in requests) + "\n")
        stdout = io.StringIO()
        asyncio.run(StdioServer(session, stdin, stdout).serve())
        return [json.loads(l) for l in stdout.getvalue().splitlines() if l.strip()]

    def test_the_budget_is_readable(self):
        frames = self._drive([{"id": 1, "method": "tools.get"}])
        assert frames[0]["result"]["max_tool_calls"] == 10

    def test_it_reports_the_session_not_the_setting_file(self):
        # The session is what a turn consults. A control that read the config
        # would show a number the next turn is not held to, which is the one
        # number in the window that must not lie.
        session = _session([[]])
        session.max_tool_calls = 7
        frames = self._drive([{"id": 1, "method": "tools.get"}], session=session)
        assert frames[0]["result"]["max_tool_calls"] == 7

    def test_a_new_budget_takes_effect(self):
        session = _session([[]])
        frames = self._drive(
            [{"id": 1, "method": "tools.set", "params": {"max_tool_calls": 25}}],
            session=session,
        )
        assert frames[0]["result"]["max_tool_calls"] == 25
        assert session.max_tool_calls == 25

    def test_zero_is_refused_rather_than_silently_corrected(self):
        # A limit of zero refuses every tool, which is not a small budget. A
        # control that turned a typed 0 into a 1 would report a value the user
        # did not ask for, so the refusal has to be an error the UI can show.
        session = _session([[]])
        frames = self._drive(
            [{"id": 1, "method": "tools.set", "params": {"max_tool_calls": 0}}],
            session=session,
        )
        assert "error" in frames[0], "zero was accepted"
        assert session.max_tool_calls == 10, "the budget changed anyway"

    def test_a_negative_budget_is_refused(self):
        session = _session([[]])
        frames = self._drive(
            [{"id": 1, "method": "tools.set", "params": {"max_tool_calls": -3}}],
            session=session,
        )
        assert "error" in frames[0]
        assert session.max_tool_calls == 10

    def test_a_non_number_is_refused(self):
        for bad in ("ten", None, True, [5]):
            session = _session([[]])
            frames = self._drive(
                [{"id": 1, "method": "tools.set", "params": {"max_tool_calls": bad}}],
                session=session,
            )
            assert "error" in frames[0], f"accepted {bad!r}"
            assert session.max_tool_calls == 10

    def test_a_string_number_is_accepted(self):
        # The wire is JSON and a number field is a number, but a control that
        # sends "5" because it read a text input should not be told off for it.
        session = _session([[]])
        frames = self._drive(
            [{"id": 1, "method": "tools.set", "params": {"max_tool_calls": "5"}}],
            session=session,
        )
        assert frames[0]["result"]["max_tool_calls"] == 5

    def test_a_failure_to_persist_still_applies(self):
        # The same contract `reasoning.set` has: the choice governs this
        # session whether or not the disk write worked, so a failed write is
        # reported rather than raised and the window is not left showing a
        # budget the turn is not using.
        import tonyagent.config as config_module

        original = config_module.save_max_tool_calls

        def boom(limit):
            raise OSError("disk is full")

        config_module.save_max_tool_calls = boom
        try:
            session = _session([[]])
            frames = self._drive(
                [{"id": 1, "method": "tools.set", "params": {"max_tool_calls": 30}}],
                session=session,
            )
        finally:
            config_module.save_max_tool_calls = original

        assert frames[0]["result"]["max_tool_calls"] == 30
        assert frames[0]["result"]["persisted"] is False
        assert session.max_tool_calls == 30


class TestPersistence:
    def test_the_budget_is_saved_without_losing_the_allowlist(self, tmp_path, monkeypatch):
        # Read-modify-write, like its siblings. `save_config` takes a whole
        # config dict, and a sidecar that assembles one from `settings` would
        # write defaults over the user's real command allowlist.
        from tonyagent.config import migration, save_max_tool_calls

        path = tmp_path / "config.toml"
        path.write_text(
            '[tools]\nmax_tool_calls = 4\ncommand_allowlist = ["python", "git"]\n',
            encoding="utf-8",
        )
        monkeypatch.setattr(migration, "get_config_path", lambda: path)

        save_max_tool_calls(12)

        written = path.read_text(encoding="utf-8")
        assert "max_tool_calls = 12" in written
        assert "python" in written, "the allowlist was written over"
        assert "git" in written

    def test_it_creates_the_section_when_there_is_none(self, tmp_path, monkeypatch):
        from tonyagent.config import migration, save_max_tool_calls

        path = tmp_path / "config.toml"
        monkeypatch.setattr(migration, "get_config_path", lambda: path)

        save_max_tool_calls(8)

        assert "max_tool_calls = 8" in path.read_text(encoding="utf-8")
