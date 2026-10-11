"""The workspace boundary: where the project is, and what counts as inside it.

**One home for the rule, because four copies of it is how a boundary diverges.**
This rule used to exist as four private copies -- ``file_tools._resolve_path``,
``search_tools._resolve_path``, ``shell_tools._resolve_path`` and the inline
version inside ``browser_screenshot`` -- each a few lines long, each with the
same message, and each one edit away from disagreeing with the others about
what "inside the project" means. That is not a hypothetical: an adversarial pass
found ``glob`` walking out of the folder through its *pattern* while every copy
of the rule was intact, which is the class of failure a shared implementation is
for. The copies that were correct are now this file; the site that was wrong
uses it too.

**The check is on the resolved path.** ``(root / path).resolve()`` then
``relative_to(root)``, so a symlink inside the project that points outside it is
refused rather than followed, and an absolute path -- which ``/`` hands back
unchanged, ignoring the root -- is refused by the same two lines. A purely
lexical check would accept ``root/../elsewhere``; this one does not.

The folder comes from ``folder_manager`` rather than a parameter for the reason
every other workspace tool gives: the ``ToolContext`` migration of the folder is
its own pass, and a boundary that took the project as an argument would let a
caller pass one it does not own.
"""

from __future__ import annotations

from pathlib import Path

from tonyagent.folder.manager import folder_manager


def project_root() -> Path:
    """The project folder, resolved, or ``ValueError`` when none is chosen."""
    folder = folder_manager.current_folder
    if not folder:
        raise ValueError("No project folder selected")
    return Path(folder).resolve()


def confine(path: str | Path) -> Path:
    """``path`` resolved against the project folder, refusing any escape.

    Raises:
        ValueError: when no folder is chosen, or when the path resolves outside
            it. The message names the path the caller passed, because that is
            what the model has to change -- ``Path('x').resolve()`` is not.
    """
    base = project_root()
    target = (base / path).resolve()
    try:
        target.relative_to(base)
    except ValueError:
        raise ValueError(f"Path '{path}' attempts to escape project folder")
    return target


def within(path: str | Path) -> bool:
    """Whether ``path`` *resolves* inside the project folder.

    The predicate form of `confine`, for the callers that are filtering
    candidates rather than resolving one -- a directory walk or a glob finds
    files that already exist, and one reached through a symlink that leaves the
    project is not inside it. Never raises: a caller that asked a question is
    owed an answer, and "no project folder" means "not inside".
    """
    try:
        base = project_root()
    except ValueError:
        return False
    try:
        Path(path).resolve().relative_to(base)
    except (ValueError, OSError):
        return False
    return True


def relative(path: str | Path) -> str | None:
    """How a path is shown to the model: project-relative, or ``None`` outside.

    The display half of the same rule, and it exists for the same reason: a walk
    that reports ``str(file_path.relative_to(folder_manager.current_folder))``
    reports ``..\\elsewhere\\secret.txt`` for a path that climbed out, because
    that call is *lexical* -- it compares the unnormalised strings and returns a
    relative path with ``..`` in it rather than refusing. Resolving first is
    what makes the reported path and the confinement check agree.

    A ``None`` here is a candidate the caller should skip, not an error: it
    means the walk reached something that is not in the project, and the file is
    simply not reportable.
    """
    try:
        base = project_root()
        resolved = Path(path).resolve()
        return resolved.relative_to(base).as_posix()
    except (ValueError, OSError):
        return None
