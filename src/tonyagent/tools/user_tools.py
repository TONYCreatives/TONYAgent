"""The two tools that reach the user: asking a question, and showing something.

Everything else in this package touches the project, the machine or the
network. These two touch the person, and they are the only ones that do --
which is why the plumbing they share lives in
:mod:`tonyagent.core.user_io` rather than in either tool, and why each of them
is a thin shell over one call into it.

**Neither touches the workspace, so neither needs a project folder.** The same
exception the network tools made before them: a question about what the user
wants does not read a file, and requiring a folder for it would refuse the one
call that works perfectly well on a bare session.

**A question is the last resort, not a progress report.** Both descriptions say
so to the model, because a model that asks "shall I continue?" every three
steps is worse than one that works: the turn's tool budget bounds how often it
can happen, and the timeout bounds how long it can stall, but neither of those
is a reason to encourage it. Ask when the answer is something only the user has
-- a preference, a credential, a decision their project turns on.

**The asymmetry between the two tools is deliberate, and it is the point.** A
question nobody answers is a call that did not get what it needed, so it fails
and the model is told to proceed on a stated assumption. A presentation nobody
answers was still delivered -- the content is on their screen -- so it succeeds
and says nobody has responded yet. Reporting a failed question as a success
would teach the model that asking is free; reporting an undelivered
presentation as a failure would teach it that showing its work is an error.
"""

from __future__ import annotations

from tonyagent.core import user_io
from tonyagent.core.user_io import (
    KIND_PRESENTATION,
    KIND_QUESTION,
    UserSilent,
    UserUnavailable,
)
from tonyagent.tools.base import (
    Tool,
    ToolCategory,
    ToolResult,
    ToolResultStatus,
    output_excerpt,
    register_tool,
)

#: Bounds on what a model may put in front of the user.
#:
#: A dialog is not a scroll-back buffer. A question longer than a paragraph is
#: one nobody reads, and six options is more than anyone can hold in their head
#: -- past that a question with options is a question that wants to be free
#: text. Each bound is refused by name rather than truncated, because a
#: silently shortened question asks the wrong thing.
MAX_QUESTION_CHARS = 1000
MAX_CONTENT_CHARS = 20000
MAX_OPTIONS = 6
MAX_OPTION_CHARS = 200


def _refuse(message: str) -> ToolResult:
    """A refusal in the model's own words, with the offending value elided."""
    return ToolResult(status=ToolResultStatus.ERROR, error=message)


def _clean(value: object) -> str:
    """Collapse whitespace, so a question is not a wall of blank lines.

    Collapsing rather than trimming only: a model that indents its question as
    a block quote has still asked the question.
    """
    return " ".join(str(value or "").split())


@register_tool
class AskUserQuestionTool(Tool):
    """Ask the user one question, and wait for their answer.

    **Why this exists as a tool.** A model working alone has to guess at
    everything only the user knows: which of two libraries they want, which of
    their accounts to use, whether a name is a real thing or a typo. Guessing
    wrong on those produces work that looks finished and is not, and the guess
    is invisible -- nobody can tell an assumption from a decision afterwards.
    Asking makes it visible and costs one round trip.

    **Not for asking permission.** The destructive-tool confirmation already
    covers "may I do this", and a question that asks it as well would be the
    same dialog twice with different words. Ask for information the user has
    and the model cannot obtain.

    **Options are a convenience for the user, not a constraint.** With options,
    they click one instead of typing; without, they type. An empty answer is
    still an answer -- it means "no comment", and the result says so rather
    than re-asking.
    """

    name = "ask_user_question"
    description = (
        "Ask the user a single question and wait for their answer. Use it when "
        "you need something only they can provide -- a preference, a choice "
        "between real alternatives, or a decision their project turns on. Offer "
        "options when there is a short list of known answers, so they can click "
        "one; leave them out when the answer has to be written. Do not use this "
        "to check on work you could verify yourself, or to ask permission for "
        "something destructive -- that has its own dialog."
    )
    category = ToolCategory.UTILITY
    destructive = False
    requires_confirmation = False
    folder_required = False
    asks_user = True
    parameters = {
        "type": "object",
        "properties": {
            "question": {
                "type": "string",
                "description": (
                    "The question, as you would ask it out loud. One question, "
                    "not a list."
                ),
            },
            "options": {
                "type": "array",
                "description": (
                    "Up to six possible answers to offer as buttons. Omit when "
                    "the answer must be written out."
                ),
                "items": {
                    "type": "string",
                    "description": "One possible answer, shown as one button.",
                },
            },
        },
        "required": ["question"],
        "additionalProperties": False,
    }

    async def execute(
        self, question: str = "", options: list[str] | None = None
    ) -> ToolResult:
        asked = _clean(question)
        if not asked:
            return _refuse(
                "ask_user_question needs a question. Ask something the user can "
                "answer, or do without the answer."
            )
        if len(asked) > MAX_QUESTION_CHARS:
            return _refuse(
                f"That question is {len(asked)} characters; a question over "
                f"{MAX_QUESTION_CHARS} is one nobody reads. Ask the short form."
            )

        choices: list[str] = []
        for raw in options or []:
            choice = _clean(raw)
            if not choice:
                return _refuse(
                    "One of the options is empty. An option with no words in it "
                    "is a button the user cannot choose between."
                )
            if choice in choices:
                return _refuse(
                    f"The option {choice!r} is listed twice. Two buttons saying "
                    "the same thing make the answer ambiguous."
                )
            if len(choice) > MAX_OPTION_CHARS:
                return _refuse(
                    f"The option {choice[:40]!r}... is over {MAX_OPTION_CHARS} "
                    "characters. Options are buttons, not paragraphs."
                )
            choices.append(choice)
        if len(choices) > MAX_OPTIONS:
            return _refuse(
                f"{len(choices)} options is more than anyone can choose between "
                f"-- the limit is {MAX_OPTIONS}. Either narrow the list or leave "
                "options out and let them answer in their own words."
            )

        try:
            answer = await user_io.ask(
                kind=KIND_QUESTION,
                prompt=asked,
                options=choices,
                tool_name=self.name,
            )
        except (UserUnavailable, UserSilent) as exc:
            # Both are the call failing to get an answer, which is what the
            # model has to know: it asked, it did not get an answer, and the
            # turn continues with whatever it does next.
            return _refuse(str(exc))

        if not answer:
            # An answer of nothing is still an answer -- Escape, or a button
            # that declines. It is not a failure, and re-asking would be the
            # way to make it one.
            return ToolResult(
                status=ToolResultStatus.SUCCESS,
                output=(
                    "The user chose not to answer. Do not ask again in this "
                    "turn: carry on with your best judgement, say plainly which "
                    "assumption you are making, or stop and say what you needed."
                ),
                summary=f"asked, not answered: {output_excerpt(asked, 60)}",
            )

        return ToolResult(
            status=ToolResultStatus.SUCCESS,
            output=f'The user answered: "{answer}"',
            summary=f"asked: {output_excerpt(asked, 60)}",
        )


@register_tool
class PresentTool(Tool):
    """Show the user something in their window, and wait for them to read it.

    **The difference from ``ask_user_question`` is the outcome, not the
    rendering.** A question wants an answer to continue; a presentation wants
    the user to *have seen* something before the turn carries on -- a plan, a
    diff summary, the findings of an investigation. That is why the two are
    separate tools rather than one with a flag: they fail differently. A
    presentation nobody answered still reached them, so it succeeds and says
    nobody responded; a question nobody answered got nothing, so it fails.

    **Anything longer than a few lines belongs in a file, not here.** This puts
    content in a dialog box in the middle of the window, which is the wrong
    shape for a report. Write the file, then present the two lines that say
    where it is and what it says.

    **Not a notification channel.** A model that presents after every step is
    narrating itself, and the dialog is modal -- it takes the window over. Let
    the answer in the transcript do the talking, and use this when being seen
    before continuing is the point.
    """

    name = "present"
    description = (
        "Show the user something in their window and wait for them to read it, "
        "returning any note they add. Use it to put a plan, a summary of "
        "findings, or a result in front of them before you continue -- something "
        "they should see rather than read later in the transcript. Keep it "
        "short: a few lines, not a report. Do not use it to report progress or "
        "to ask a question; the transcript carries your answer, and "
        "ask_user_question is for questions."
    )
    category = ToolCategory.UTILITY
    destructive = False
    requires_confirmation = False
    folder_required = False
    asks_user = True
    parameters = {
        "type": "object",
        "properties": {
            "content": {
                "type": "string",
                "description": (
                    "What to show them, in plain text. A few lines; it appears "
                    "in a dialog in the middle of their window."
                ),
            },
            "title": {
                "type": "string",
                "description": (
                    "A short heading for what this is. Omit and a plain one is "
                    "used."
                ),
            },
        },
        "required": ["content"],
        "additionalProperties": False,
    }

    async def execute(self, content: str = "", title: str = "") -> ToolResult:
        body = str(content or "").strip()
        if not body:
            return _refuse(
                "present needs content. There is nothing to show the user."
            )
        if len(body) > MAX_CONTENT_CHARS:
            return _refuse(
                f"That is {len(body)} characters; over {MAX_CONTENT_CHARS} is a "
                "report, and a dialog box is not where a report goes. Write it "
                "to a file and present the two lines that say where it is."
            )
        heading = _clean(title) or "The agent has something to show you."

        try:
            note = await user_io.ask(
                kind=KIND_PRESENTATION,
                prompt=heading,
                content=body,
                tool_name=self.name,
            )
        except UserUnavailable as exc:
            # Nothing is listening, so nothing was shown. Reporting that as a
            # success would tell the model its work had been seen.
            return _refuse(str(exc))
        except UserSilent:
            # Delivered and unanswered, which is a delivery: the content is on
            # their screen and they have not come back to it yet.
            return ToolResult(
                status=ToolResultStatus.SUCCESS,
                output=(
                    "This was presented in the user's window and they have not "
                    "responded. Do not present it again in this turn; carry on, "
                    "or stop and wait for them."
                ),
                summary=f"presented, no reply: {output_excerpt(heading, 60)}",
            )

        if not note:
            return ToolResult(
                status=ToolResultStatus.SUCCESS,
                output=(
                    "The user read this and had nothing to add. Continue with "
                    "the work."
                ),
                summary=f"presented: {output_excerpt(heading, 60)}",
            )

        return ToolResult(
            status=ToolResultStatus.SUCCESS,
            output=f'The user responded: "{note}"',
            summary=f"presented: {output_excerpt(heading, 60)}",
        )


