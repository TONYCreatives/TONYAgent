"""Skills: procedures a user keeps in the project, and the ``/name`` syntax.

A skill is one Markdown file. It is *read*, never executed by this module: what
a skill does is tell the model a procedure to follow with the tools it already
has, so a skill cannot grant itself a permission, cannot escape the mode gate,
and cannot run anything by being loaded. That is the whole design, and every
decision below follows from it.

**Why a file in the project.** The alternative shapes were a table in settings
(which the user cannot review or diff) and a prompt template inside the app
(which the model cannot read, and which nobody can add to without a rebuild).
A file under ``.tonyagent/skills/`` is versionable, greppable, and editable in
whatever editor the user already works in -- the same argument that put
conversations on disk.

**Why a flat ``<name>.md`` and not ``<name>/SKILL.md``.** A skill is one
document by definition, so a directory per skill buys nothing but a second
level, and ``ls .tonyagent/skills`` answers "what have I got" in one line.

**Two roots, project first.** ``<project>/.tonyagent/skills/`` then
``<app data>/skills/``. The project's file wins a name collision, because the
project is what the agent is working on and a shared machine-wide skill must
not silently shadow the one that belongs to this repository. A shadowed file is
reported rather than ignored -- a skill that exists and does not run is exactly
the kind of silence this project keeps having to unpick.

**Nothing is cached.** Discovery is a directory listing and a handful of small
reads, and the alternative is a cache with an invalidation bug in it: the user
edits a skill in their editor and the next turn uses the old one. The file
tools re-read the workspace on every call for the same reason.
"""

from __future__ import annotations

import re
import stat
from dataclasses import dataclass, field
from pathlib import Path

from tonyagent.utils.paths import get_app_data_dir

#: The directory a skill lives in, under the project's ``.tonyagent``.
SKILLS_DIRNAME = "skills"
#: The project directory skills are found in, matching the other project config.
PROJECT_CONFIG_DIRNAME = ".tonyagent"
#: Only Markdown files are skills. A stray ``.bak`` or ``.txt`` beside them is
#: left alone rather than parsed and reported as broken.
SKILL_SUFFIX = ".md"

#: Longest a skill body may be, in characters.
#:
#: A body is rendered into the system prompt on the turn it is invoked, so this
#: is a budget rather than a tidiness rule: an unbounded skill is a user who
#: pastes a book into the file and then cannot work out why every turn in that
#: conversation is slow. Refused with the number in the message, so the fix is
#: obvious from the refusal itself.
MAX_SKILL_CHARS = 24_000

#: The byte bound checked *before* the file is read, in the same units the OS
#: reports sizes in.
#:
#: ``MAX_SKILL_CHARS * 4`` because UTF-8 is at most four bytes per character, so
#: this can refuse a file that ``MAX_SKILL_CHARS`` would have accepted -- and
#: that is the right direction for a bound whose whole job is to not allocate the
#: memory. The character check afterwards is the exact one, and a file between
#: the two bounds is refused with the character count in the message.
MAX_SKILL_BYTES = MAX_SKILL_CHARS * 4

#: What a skill name may look like: a bare word.
#:
#: Deliberately narrow. The name is typed after a slash in the composer, so a
#: name with a space in it could not be invoked at all, and a name with a dot or
#: a slash would collide with the filename it is derived from.
SKILL_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")

#: The sentence that says out loud what a skill is not.
#:
#: Kept here, in one place, because both ways in -- the ``/name`` syntax and the
#: ``run_skill`` tool -- must say the same thing. A model that reads the
#: procedure and assumes it was granted something is the one failure this
#: feature could have that matters.
PERMISSION_NOTE = (
    "Loading a skill grants nothing: it is a procedure, and the steps in it run "
    "with the tools and permissions this turn already has."
)


class SkillError(ValueError):
    """A skill file that cannot be used, with a reason the user can act on."""


@dataclass(frozen=True)
class Skill:
    """One skill: its name, its purpose, and the procedure itself."""

    name: str
    description: str
    body: str
    path: Path
    #: ``project`` or ``user`` -- which root it came from.
    source: str

    def to_dict(self) -> dict:
        """The shape the wire and the tools both carry.

        ``body`` is not in it. The listing exists to answer *what have I got*,
        and a listing that carries every procedure is the same document read
        again on every call; the body travels only when one is actually run.
        """
        return {
            "name": self.name,
            "description": self.description,
            "source": self.source,
            "path": str(self.path),
        }


@dataclass(frozen=True)
class SkillProblem:
    """A file that was meant to be a skill and is not usable.

    Reported rather than skipped: a skill with a typo in its front matter is
    invisible otherwise, and "I wrote a skill and the agent never used it" has
    no other way of being diagnosable.
    """

    path: Path
    reason: str

    def to_dict(self) -> dict:
        return {"path": str(self.path), "reason": self.reason}


@dataclass
class SkillSet:
    """Everything found under the roots, and everything wrong with it."""

    skills: list[Skill] = field(default_factory=list)
    problems: list[SkillProblem] = field(default_factory=list)

    def get(self, name: str) -> Skill | None:
        """Find a skill by name: exactly first, then case-insensitively.

        The second pass exists because the name is typed by hand. ``/Review``
        missing an existing ``review`` skill while ``list_skills`` shows it
        would read as the syntax being broken rather than the capital being
        wrong. It stays a *lookup* fallback: nothing normalises a stored name.
        """
        wanted = (name or "").strip()
        if not wanted:
            return None
        for skill in self.skills:
            if skill.name == wanted:
                return skill
        lowered = wanted.lower()
        for skill in self.skills:
            if skill.name.lower() == lowered:
                return skill
        return None

    @property
    def names(self) -> list[str]:
        return [skill.name for skill in self.skills]

    def is_empty(self) -> bool:
        return not self.skills


@dataclass(frozen=True)
class SkillInvocation:
    """A turn that began with ``/name``: which skill, and what was passed to it."""

    skill: Skill
    arguments: str

    def prompt_block(self) -> str:
        """The block the session appends to the system prompt for this turn.

        Appended to the *prompt* rather than stored as a message, for the reason
        the plan is: this is not something either party said. The user typed
        ``/review`` and that is what the transcript keeps; the procedure is
        background for the turn, and a transcript that grew a pasted document
        per invocation would make the file on disk unreadable in a week.

        The first line states the mapping, because a model seeing a bare
        ``/review`` at the top of a user message would otherwise have to guess
        what it means -- and the guess could just as easily be "this is a path".
        """
        args = self.arguments.strip()
        lines = [
            f'The user began this message with "/{self.skill.name}", which asks for '
            f'the skill named "{self.skill.name}" ({self.skill.path}). Follow its '
            "procedure for this turn, using your normal tools.",
        ]
        if args:
            lines.append("")
            lines.append(f"Arguments the user gave it: {args}")
        lines += [
            "",
            PERMISSION_NOTE,
            "",
            f"--- skill: {self.skill.name} ---",
            self.skill.body,
            f"--- end of skill: {self.skill.name} ---",
        ]
        return "\n".join(lines)


# -- one file -----------------------------------------------------------------

def parse_skill(text: str, fallback_name: str) -> tuple[str, str, str]:
    """``(name, description, body)`` from one skill file's text.

    Front matter is the optional ``---``-fenced header, with ``name:`` and
    ``description:``. It is a two-key, line-per-key format and deliberately not
    YAML: the project has no YAML dependency, and a parser that accepts nested
    structures would advertise a shape nothing reads. Anything else in the
    header is an error rather than a silent skip -- the same rule the tool
    schemas follow with ``additionalProperties``.

    Raises:
        SkillError: with a reason naming what is wrong and where.
    """
    raw = text or ""
    name = fallback_name
    description = ""
    body = raw.strip()

    if raw.startswith("---"):
        lines = raw.splitlines()
        if lines and lines[0].strip() == "---":
            close = next(
                (i for i, line in enumerate(lines[1:], start=1) if line.strip() == "---"),
                None,
            )
            if close is None:
                # Named rather than shrugged at. A header whose `name:` line
                # was silently ignored loads the skill under its filename, and
                # the user's only clue is that the name they chose did nothing
                # -- which is the shape of silence this module exists to avoid.
                # The fix is one line: delete the stray fence, or close it.
                raise SkillError(
                    "front matter opens with '---' and never closes with one; "
                    "a skill with no header needs no '---' line at all"
                )
            for line in lines[1:close]:
                if not line.strip():
                    continue
                key, sep, value = line.partition(":")
                if not sep:
                    raise SkillError(
                        f"front matter line {line.strip()!r} is not 'key: value'; "
                        "only 'name' and 'description' are read"
                    )
                key = key.strip().lower()
                value = value.strip().strip('"').strip("'")
                if key == "name":
                    name = value
                elif key == "description":
                    description = " ".join(value.split())
                else:
                    raise SkillError(
                        f"front matter key {key!r} is not read; only 'name' and "
                        "'description' are"
                    )
            body = "\n".join(lines[close + 1:]).strip()

    if not SKILL_NAME_RE.match(name or ""):
        raise SkillError(
            f"name {name!r} is not usable: a skill name is letters, digits, '-' and "
            "'_', starting with a letter or digit (it has to be typeable after a "
            "slash)"
        )
    if not body:
        raise SkillError("no procedure: the file has nothing after its front matter")
    if len(body) > MAX_SKILL_CHARS:
        raise SkillError(
            f"the procedure is {len(body)} characters; keep it under "
            f"{MAX_SKILL_CHARS} so it fits one turn's prompt"
        )
    return name, description, body


def load_skill_file(path: Path, source: str) -> Skill:
    """One skill from one file, or ``SkillError`` saying why not.

    **Size and type are checked before the read, not after it.** The character
    cap inside `parse_skill` is a prompt budget, and on its own it bounds what is
    *used* rather than what is *allocated*: discovery runs on every turn whose
    message starts with a known `/name` and on every `list_skills`, so a
    ``.md`` file -- or a symlink named like one -- pointing at a gigabyte of log
    would be read into memory in full, once per call, and only then found to be
    too long. ``st_size`` is the OS's number and costs one syscall.

    A directory can be named ``skills/notes.md``, and a stat is how it is told
    apart from a file before anything tries to open it.
    """
    try:
        info = path.stat()
    except OSError as exc:
        raise SkillError(f"cannot be read: {exc}") from exc
    if not stat.S_ISREG(info.st_mode):
        raise SkillError("is not a regular file")
    if info.st_size > MAX_SKILL_BYTES:
        raise SkillError(
            f"is {info.st_size} bytes, which is too big to load (the limit is "
            f"{MAX_SKILL_CHARS} characters of procedure)"
        )
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise SkillError(f"cannot be read: {exc}") from exc
    name, description, body = parse_skill(text, path.stem)
    return Skill(name=name, description=description, body=body, path=path, source=source)


# -- discovery ----------------------------------------------------------------

def skill_roots(folder: Path | str | None) -> list[tuple[str, Path]]:
    """The directories a skill may live in, most specific first.

    The user root is always present: skills are the user's, and a machine-wide
    skill that only works while a project is open would be a strange rule. The
    project root is added only when there is a project.
    """
    roots: list[tuple[str, Path]] = []
    if folder:
        roots.append(("project", Path(folder) / PROJECT_CONFIG_DIRNAME / SKILLS_DIRNAME))
    roots.append(("user", get_app_data_dir() / SKILLS_DIRNAME))
    return roots


def discover_skills(folder: Path | str | None = None) -> SkillSet:
    """Every usable skill under ``folder``'s project and the user root.

    A missing directory is not a problem to report: most projects have no
    skills, and "no skills" is a fine answer to "what have I got". A file that
    *is* there and is broken is a problem.
    """
    found = SkillSet()
    seen: dict[str, Skill] = {}

    for source, root in skill_roots(folder):
        try:
            files = sorted(root.glob(f"*{SKILL_SUFFIX}"))
        except OSError:
            # An unreadable directory is the user's business, not the turn's.
            continue
        for path in files:
            try:
                skill = load_skill_file(path, source)
            except SkillError as exc:
                found.problems.append(SkillProblem(path=path, reason=str(exc)))
                continue
            winner = seen.get(skill.name)
            if winner is not None:
                found.problems.append(
                    SkillProblem(
                        path=path,
                        reason=(
                            f"a skill named {skill.name!r} is already loaded from "
                            f"{winner.path}, so this file is not used"
                        ),
                    )
                )
                continue
            seen[skill.name] = skill
            found.skills.append(skill)

    return found


def discover_current_skills() -> SkillSet:
    """The skills for the project the session is actually working in.

    ``folder_manager`` rather than a parameter, matching every other tool that
    touches the workspace: the ``ToolContext`` migration of the folder is a
    separate pass (see the handoff), and a skill store with its own private
    notion of "the project" would be a second answer to the same question.
    """
    from tonyagent.folder.manager import folder_manager

    return discover_skills(folder_manager.current_folder)


# -- the /name syntax ---------------------------------------------------------

def slash_command(text: str) -> tuple[str, str] | None:
    """``(name, arguments)`` when ``text`` opens with ``/name``, else ``None``.

    Only the first token of the first line is the name, and the rest of the
    message -- including its later lines -- is the arguments, so

        /review focus on the retry path
        it bit us twice last month

    passes both lines along.
    """
    first, _, rest = (text or "").partition("\n")
    head = first.strip()
    if not head.startswith("/"):
        return None
    parts = head[1:].split(None, 1)
    if not parts:
        # A bare "/" is not a command; it is the user typing.
        return None
    name = parts[0]
    if not SKILL_NAME_RE.match(name):
        return None
    arguments = parts[1] if len(parts) > 1 else ""
    tail = rest.strip()
    if tail:
        arguments = f"{arguments}\n{tail}".strip()
    return name, arguments


def invocation_for(text: str, folder: Path | str | None) -> SkillInvocation | None:
    """The skill a message asks for, if it asks for one that exists.

    ``folder`` is required rather than defaulting, and that is deliberate: a
    default of ``None`` reads as "the current project" and means "the user root
    only", so a caller that forgot it would silently stop finding the project's
    own skills -- a bug that looks exactly like a skill not existing. The one
    caller that wants the current project passes it explicitly
    (``AgentSession._skill_for_this_turn``).

    **An unknown name is not an error, and not a command.** ``/usr/local/bin``
    and a typo both fall through and the message is read as the ordinary prose
    it is: hijacking a message because it happens to start with a slash would
    break pasting a path, and refusing it would put a refusal in front of a user
    who was not asking for anything. What tells a user their skill name is wrong
    is the composer's own list of names while they type it.
    """
    parsed = slash_command(text)
    if parsed is None:
        return None
    name, arguments = parsed
    skill = discover_skills(folder).get(name)
    if skill is None:
        return None
    return SkillInvocation(skill=skill, arguments=arguments)
