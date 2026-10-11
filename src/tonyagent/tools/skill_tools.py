"""The two skill tools: what the agent has, and how it loads one.

These are the *agent's* way in. The user has another one -- typing ``/name`` in
the composer, which the session resolves itself so a skill the user asked for
does not depend on the model deciding to look it up -- and both read the same
store in :mod:`tonyagent.core.skills`, so the two can never disagree about what
exists.

**Both are read-only, and that is the point of the design rather than a detail
of it.** A skill is a document; loading one changes nothing outside the
conversation, so it sits in the read-only allow-list and works in every mode
including Plan. What it *describes* is performed afterwards with the tools the
turn already has, which is why a skill cannot be a way around the mode gate: in
Plan mode a skill whose procedure says "write the file" is refused at the write,
exactly as it would be without the skill. That is asserted in
``tests/unit/test_skills.py`` against the orchestrator, not assumed.
"""

from __future__ import annotations

from tonyagent.core.skills import (
    PERMISSION_NOTE,
    Skill,
    SkillSet,
    discover_current_skills,
)
from tonyagent.tools.base import (
    Tool,
    ToolCategory,
    ToolResult,
    ToolResultStatus,
    register_tool,
)


def _catalogue(found: SkillSet) -> str:
    """The skill list as the transcript shows it.

    Problems come last and are named, because a file the user wrote and that
    did not load is the one thing this listing must not be quiet about.
    """
    lines: list[str] = []
    if not found.skills:
        lines.append(
            "No skills yet. A skill is a Markdown file in "
            ".tonyagent/skills/ (or the skills folder in this app's data "
            "directory); its first line can be a '---' header with 'name' and "
            "'description', and the rest is the procedure."
        )
    for skill in found.skills:
        purpose = f"-- {skill.description}" if skill.description else ""
        lines.append(f"{skill.name} [{skill.source}] {purpose}".rstrip())
        lines.append(f"    {skill.path}")
    if found.problems:
        lines.append("")
        lines.append("Files that could not be loaded:")
        for problem in found.problems:
            lines.append(f"    {problem.path}: {problem.reason}")
    return "\n".join(lines)


def _summary(found: SkillSet, prefix: str = "") -> str:
    """One line for the tool card, which is where "it worked" is actually read."""
    if not found.skills:
        return f"{prefix}no skills".strip()
    said = f"{prefix}{len(found.skills)} skill" + ("s" if len(found.skills) != 1 else "")
    if found.problems:
        said += f", {len(found.problems)} broken"
    return said


@register_tool
class ListSkillsTool(Tool):
    """The skills available to this conversation.

    Its own tool rather than a line in the system prompt, for the reason
    ``get_goal`` is: the catalogue is state that moves -- the user adds a file
    while the conversation is open -- and a model that cannot ask will work from
    whatever it was shown at the beginning of the turn. It is cheap enough to
    call twice in one turn (a directory listing and a few small reads).

    ``folder_required`` is False on purpose. With no project chosen the user
    root still holds skills, and refusing to list them because a folder is not
    open would hide the half of the store that has nothing to do with a project.
    """

    name = "list_skills"
    description = (
        "List the skills available for this project and this user: reusable "
        "procedures saved as Markdown files. Call it before run_skill when you "
        "are not sure a skill exists, or when the user refers to one by name."
    )
    category = ToolCategory.UTILITY
    parameters = {"type": "object", "properties": {}, "additionalProperties": False}
    destructive = False
    requires_confirmation = False
    folder_required = False

    async def execute(self) -> ToolResult:
        found = discover_current_skills()
        return ToolResult(
            status=ToolResultStatus.SUCCESS,
            output=_catalogue(found),
            summary=_summary(found),
        )


@register_tool
class RunSkillTool(Tool):
    """Load one skill's procedure.

    The procedure comes back as this tool's *result* rather than being injected
    into the prompt, because that is the shape that lets the model use it in the
    middle of a turn -- after reading a file that mentions a skill, or when the
    user refers to one part way through a conversation. The ``/name`` syntax
    covers the other case, the user asking for one up front.

    It answers a bad name with the list of good ones. "No such skill" on its own
    would make the model try again with another guess; ``list_skills`` output in
    the refusal ends the guessing in one call.
    """

    name = "run_skill"
    description = (
        "Load a skill: a saved procedure to follow. Pass its name and, if the "
        "user gave any, the arguments. The procedure is guidance for how to do "
        "the work -- it grants no extra permission, and its steps are carried "
        "out with your normal tools."
    )
    category = ToolCategory.UTILITY
    parameters = {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "The skill's name, as list_skills reports it.",
            },
            "arguments": {
                "type": "string",
                "description": (
                    "What the user wants the skill to focus on, if anything."
                ),
            },
        },
        "required": ["name"],
        "additionalProperties": False,
    }
    destructive = False
    requires_confirmation = False
    folder_required = False

    async def execute(self, name: str = "", arguments: str = "") -> ToolResult:
        wanted = " ".join(str(name or "").split())
        if not wanted:
            return ToolResult(
                status=ToolResultStatus.ERROR,
                error="A skill name is required. Use list_skills to see what exists.",
            )

        found = discover_current_skills()
        skill: Skill | None = found.get(wanted)
        if skill is None:
            known = ", ".join(found.names) or "none"
            return ToolResult(
                status=ToolResultStatus.ERROR,
                error=(
                    f"There is no skill named {wanted!r}. Available: {known}. "
                    "Call list_skills for their descriptions, or ask the user "
                    "which one they meant."
                ),
                summary=f"no skill {wanted}",
            )

        args = " ".join(str(arguments or "").split())
        lines = [
            f"Skill: {skill.name}",
            f"From: {skill.path}",
        ]
        if skill.description:
            lines.append(f"Purpose: {skill.description}")
        if args:
            lines.append(f"Arguments from the user: {args}")
        lines += [
            "",
            PERMISSION_NOTE,
            "",
            "Procedure:",
            skill.body,
        ]
        return ToolResult(
            status=ToolResultStatus.SUCCESS,
            output="\n".join(lines),
            summary=f"skill: {skill.name}",
        )
