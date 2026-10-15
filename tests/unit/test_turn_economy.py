"""What a turn may spend, and what the model is told about it.

The mechanism these tests surround already worked: one assistant message may
declare several tool calls, they run at the same time, and every result comes
back in the same batch -- ``test_parallel_tool_calls.py`` measures the overlap
rather than assuming it. What did not exist was anyone *telling the model*.
Every mode's prompt described the job the mode does and stopped there, and a
model that does not know it may batch asks one call at a time.

That is not a style difference. The provider this app defaults to is metered by
request -- the free OpenRouter tier allows 20 a minute and 1000 a day -- and
every round trip is one of them. Three reads in three messages costs three
requests where one message costs one, so "batch the independent calls" is the
single instruction in the prompt that has a price on it. The clause also carries
the other half of the same idea: write the steps down with ``todo_write`` in the
*same* message as the first batch, rather than spending a whole round saying
what you are about to do.

The clause lives in ``modes.TOOL_CALL_ECONOMY`` and the session appends it,
rather than each mode's prompt ending with a copy. That is why these tests are
about two properties and not about wording: that **every** mode gets it, and that
no mode's prompt gets two of it.
"""

from __future__ import annotations

import pytest

import tonyagent.tools  # noqa: F401  -- importing registers every tool
from tonyagent.core.events import EventBus
from tonyagent.core.modes import MODE_ORDER, TOOL_CALL_ECONOMY, get_mode
from tonyagent.core.session import AgentSession
from tonyagent.core.task_state import Todo


@pytest.fixture(autouse=True)
def _unrestricted_orchestrator():
    """Keep one test's mode out of the next, for the tests in files after this one.

    ``AgentSession.set_mode`` pushes the mode into the process-wide
    ``tool_orchestrator`` -- right in the app, where one session owns the window,
    and order-dependent in a suite. This module walks *every* mode, so it ends on
    whichever one runs last, and that is exactly the failure `test_skills`
    documents: measured here, this file left the orchestrator in Skills and nine
    ``test_workflow`` tests (the next file alphabetically that runs a real turn)
    failed with subagents refused -- a failure that names neither the file nor
    the session that caused it. The same fixture, for the same reason, is in
    ``test_skills`` and ``test_modes_and_diffs``.
    """
    from tonyagent.tools.orchestrator import tool_orchestrator

    previous_mode, previous_permission = (
        tool_orchestrator._mode,
        tool_orchestrator._permission,
    )
    tool_orchestrator.set_mode(None)
    yield
    tool_orchestrator.set_mode(previous_mode)
    tool_orchestrator.set_permission(previous_permission)


def _prompt(mode: str = "build") -> str:
    session = AgentSession(bus=EventBus())
    session.set_mode(mode)
    # Unlimited: these tests pin the economy block, and a budget line would put
    # the number of a turn into a comparison about wording. The budget is tested
    # on its own below.
    session.max_tool_calls = 0
    return session._messages_with_system()[0].content


@pytest.mark.parametrize("mode", MODE_ORDER)
def test_every_mode_is_told_it_may_ask_for_several_tools_at_once(mode: str):
    prompt = _prompt(mode)

    assert TOOL_CALL_ECONOMY in prompt, f"{mode} is not told how a turn is spent"
    # The one thing a model cannot infer from the tool schemas. Nothing about
    # being *offered* twenty tools says that several of them may be asked for in
    # one message, and a model that does not know asks serially.
    assert "several tool calls in one message" in prompt
    # ...and that the results arrive together, which is what makes batching
    # worth doing rather than a way to lose track of which answer is which.
    assert "run at the same time" in prompt
    assert "back together" in prompt


@pytest.mark.parametrize("mode", MODE_ORDER)
def test_a_mode_still_speaks_first(mode: str):
    """The mode's job is the first thing read, and the rules follow it.

    Order is worth pinning because the reverse reads as a preamble with a job
    bolted to the end of it, and because a mode's prompt is the thing the user
    chose when they picked the mode.
    """
    prompt = _prompt(mode)
    assert prompt.startswith(get_mode(mode).system_prompt)
    assert prompt == f"{get_mode(mode).system_prompt}\n\n{TOOL_CALL_ECONOMY}"


def test_the_rules_are_one_block_every_mode_shares():
    """Five prompts, one text: a fix to it is a fix to all five."""
    tails = {
        _prompt(mode)[len(get_mode(mode).system_prompt):] for mode in MODE_ORDER
    }
    assert tails == {f"\n\n{TOOL_CALL_ECONOMY}"}, "a mode has its own copy of the rules"


def test_a_plan_does_not_displace_it_or_come_twice():
    """The blocks are appended, so the one appended second cannot eat the first.

    The plan is the case worth testing rather than a skill: it is appended
    *after* the rules by the same method, and in Mission mode -- the mode whose
    whole point is a long task -- there is always one.
    """
    session = AgentSession(bus=EventBus())
    session.set_state(session.state)
    session.state.set_goal("Ship the retry fix")
    session.state.replace_todos([Todo("write the test")])

    prompt = session._messages_with_system()[0].content

    assert prompt.count(TOOL_CALL_ECONOMY) == 1
    assert "Ship the retry fix" in prompt
    assert "write the test" in prompt
    assert prompt.index(TOOL_CALL_ECONOMY) < prompt.index("Ship the retry fix")


def test_the_clause_asks_for_the_plan_in_the_same_message_as_the_work():
    """The plan-first half, pinned as the instruction it is.

    A plan sent in its own message costs exactly what the batching rule is
    trying to save, and it is the way this instruction is most likely to be
    quietly rewritten into something that reads better and costs more.
    """
    assert "todo_write in the same message" in TOOL_CALL_ECONOMY
    assert "metered" in TOOL_CALL_ECONOMY


def test_a_limited_turn_is_told_its_budget_and_to_plan_against_it():
    """The number on the wire, not only enforced and shown in the window.

    `TOOL_CALL_ECONOMY` says how to spend a turn but cannot say how many calls
    there are -- it is one fixed string. This is the per-session half: a model
    told it has ten reads its way to the third differently from one that meets
    the limit on the eleventh call. Asserted as guidance *and* the arithmetic
    (limit, spent, left), because the sentence is the point and the numbers are
    what make it honest.
    """
    session = AgentSession(bus=EventBus())
    session.set_mode("build")
    session.max_tool_calls = 10
    session._tool_calls_used = 3
    prompt = session._messages_with_system()[0].content

    assert "10 tool calls" in prompt, "the limit never reached the model"
    assert "3 spent" in prompt and "7 left" in prompt, prompt  # arithmetic, or a lie
    # Guidance before the fact, not a tally after it: plan, then spend.
    assert prompt.index("Tool-call budget") < prompt.index("Plan the whole job")


def test_an_unlimited_turn_is_not_told_a_budget():
    """`0` means no limit; naming one invites a model to fill it.

    The same reason the economy rules are phrased as rules rather than as a
    cap: "unlimited" is a ceiling a model spends because it is there.
    """
    session = AgentSession(bus=EventBus())
    session.set_mode("build")
    session.max_tool_calls = 0
    prompt = session._messages_with_system()[0].content
    assert "Tool-call budget" not in prompt
    # And the economy rules are still there -- the budget line adds to them.
    assert TOOL_CALL_ECONOMY in prompt
