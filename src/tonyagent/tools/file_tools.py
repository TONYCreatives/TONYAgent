"""File operation tools for TONYAgent."""

from __future__ import annotations

import difflib
import os
from pathlib import Path
from typing import Any

from tonyagent.tools.base import Tool, ToolResult, ToolResultStatus, ToolCategory, register_tool
from tonyagent.tools.workspace import confine
from tonyagent.tools.images import EDGE_NOTE, MAX_SOURCE_BYTES, encode


#: How many diff lines a `file_change` artifact may carry. The trajectory view
#: shows the real +/− change, but a whole-file rewrite is bounded: the artifact
#: is also the tool result the model reads back on the next round, so echoing
#: an unbounded file would double every large edit.
_DIFF_MAX_LINES = 120


def _line_delta(before: str, after: str) -> tuple[int, int]:
    """Count lines added and removed between two file contents.

    A real diff, not a length comparison. ``len(after) - len(before)`` says
    nothing useful: rewriting one line for another looks identical to appending
    a thousand. The frontend renders these as the +N/-N badges in the Files
    tree, so a wrong number there is worse than no number -- it looks checked.
    """
    before_lines = before.splitlines()
    after_lines = after.splitlines()
    added = removed = 0
    matcher = difflib.SequenceMatcher(None, before_lines, after_lines)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag in ("replace", "delete"):
            removed += i2 - i1
        if tag in ("replace", "insert"):
            added += j2 - j1
    return added, removed


def _bounded_diff(before: str, after: str) -> str:
    """A unified diff of the change, capped at ``_DIFF_MAX_LINES`` lines.

    The trajectory view wants the actual +/− lines rather than a count, and the
    edit tools already read both sides to compute the count, so this is free.
    The file headers (``---``/``+++``) are dropped -- the path is already in the
    artifact -- and a ``… N more lines`` tail says a large change was cut
    rather than pretending it was small.
    """
    raw = difflib.unified_diff(
        before.splitlines(),
        after.splitlines(),
        lineterm="",
        n=2,
    )
    lines = [ln for ln in raw if not ln.startswith(("---", "+++"))]
    if len(lines) > _DIFF_MAX_LINES:
        hidden = len(lines) - _DIFF_MAX_LINES
        lines = lines[:_DIFF_MAX_LINES] + [f"… {hidden} more lines"]
    return "\n".join(lines)


def _change_artifact(path: str, added: int, removed: int, diff: str = "") -> dict:
    """The machine-readable form the Files tree and the trajectory read.

    Kept separate from `output`, which stays a human sentence, because the
    transcript and the tree want the same fact in two different shapes. `diff`
    is the unified diff, for the trajectory view; it is empty for the tools that
    do not read both sides -- a delete removes the whole file, not a delta.
    """
    return {
        "type": "file_change",
        "data": {"path": path, "added": added, "removed": removed, "diff": diff},
    }


#: The workspace boundary, from its one home. Kept under this name because it
#: is a module-level helper of this module's tools, not a second implementation
#: -- see `tonyagent.tools.workspace` for why there is only one.
_resolve_path = confine


@register_tool
class ReadTool(Tool):
    """Read a text file from the project folder, optionally one line window.

    Paths are project-relative and confined to the project folder; a path that
    escapes it is refused rather than clamped, so the model learns that the
    folder is the boundary rather than discovering it by reading someone else's
    SSH key.

    ``offset`` and ``limit`` exist because reading a whole file is the most
    expensive single call a tool can make. A 4000-line file is tens of thousands
    of tokens, and a model that wanted line 12 pays for all of it -- once per
    turn, because the cost lives in the history rather than in the call.

    Lines are numbered, 1-based, because everything downstream refers to lines by
    number: the model quoting one back to the user, and the next ``edit`` whose
    ``old_string`` has to match exactly. Leaving the model to count is how an
    off-by-one becomes an edit in the wrong place. The window is reported against
    the file's total, so "that is the whole file" stays distinguishable from
    "there is more" -- the difference between answering and guessing.
    """

    name = "read"
    description = (
        "Read a file from the project folder, with line numbers. Use offset and "
        "limit to read part of a large file."
    )
    category = ToolCategory.FILE
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Relative path from project root"},
            "offset": {
                "type": "integer",
                "description": "First line to read, 1-based. Defaults to the start.",
            },
            "limit": {
                "type": "integer",
                "description": "How many lines to read. Defaults to the end.",
            },
            "encoding": {"type": "string", "enum": ["utf-8", "latin-1", "cp1252"], "default": "utf-8"},
        },
        "required": ["path"],
        "additionalProperties": False,
    }
    destructive = False
    requires_confirmation = False

    async def execute(self, path: str, offset: int | None = None,
                      limit: int | None = None, encoding: str = "utf-8") -> ToolResult:
        try:
            target = _resolve_path(path)
            if not target.exists():
                return ToolResult(status=ToolResultStatus.ERROR, error=f"File not found: {path}")
            if not target.is_file():
                return ToolResult(status=ToolResultStatus.ERROR, error=f"Not a file: {path}")

            content = target.read_text(encoding=encoding)
            lines = content.splitlines()
            total = len(lines)

            start = max(0, (offset or 1) - 1)
            if start > total:
                return ToolResult(
                    status=ToolResultStatus.ERROR,
                    error=(
                        f"offset {offset} is past the end of {path}, "
                        f"which has {total} line(s)"
                    ),
                )
            end = total if limit is None else min(total, start + max(0, limit))
            window = lines[start:end]

            if not window:
                body = "(no lines in that range)"
            else:
                body = "\n".join(
                    f"{start + index + 1}\t{line}"
                    for index, line in enumerate(window)
                )
            span = f"lines {start + 1}-{start + len(window)} of {total}"
            return ToolResult(
                status=ToolResultStatus.SUCCESS,
                output=f"{path} ({span})\n{body}",
            )
        except Exception as e:
            return ToolResult(status=ToolResultStatus.ERROR, error=str(e))


@register_tool
class ReadImageTool(Tool):
    """Read an image file from the project folder and look at it.

    The pixels go to the model rather than to a path: the picture is attached to
    the tool message and is gone when the turn ends (see ``ToolResult.images``),
    so nothing is written and there is nothing to clean up afterwards. That is
    the difference between this and ``browser_screenshot``, which writes because
    its output is something to keep -- this output is something to look at.

    Confined to the project folder like every other file tool, and refused for a
    file that is not an image rather than sending bytes the provider will reject
    with a complaint about a format nobody asked about.
    """

    name = "read_image"
    description = (
        "Read an image file from the project folder and look at it. Use it for a "
        "screenshot, diagram or photograph that the project contains."
    )
    category = ToolCategory.FILE
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Relative path from project root"},
        },
        "required": ["path"],
        "additionalProperties": False,
    }
    destructive = False
    requires_confirmation = False

    async def execute(self, path: str) -> ToolResult:
        try:
            target = _resolve_path(path)
            if not target.exists():
                return ToolResult(status=ToolResultStatus.ERROR, error=f"File not found: {path}")
            if not target.is_file():
                return ToolResult(status=ToolResultStatus.ERROR, error=f"Not a file: {path}")

            size = target.stat().st_size
            if size > MAX_SOURCE_BYTES:
                return ToolResult(
                    status=ToolResultStatus.ERROR,
                    error=(
                        f"{path} is {size / (1024 * 1024):.1f} MB, over the "
                        f"{MAX_SOURCE_BYTES // (1024 * 1024)} MB limit for an image "
                        "handed to the model."
                    ),
                )

            # Imported here so this module imports anywhere, matching
            # `screen_tools`. Pillow is a declared dependency, but a broken one
            # should fail this tool rather than the whole tool registry.
            from PIL import Image, UnidentifiedImageError

            try:
                image = Image.open(target)
                image.load()
            except UnidentifiedImageError:
                return ToolResult(
                    status=ToolResultStatus.ERROR,
                    error=(
                        f"{path} is not an image file that can be opened. PNG, JPEG, "
                        "GIF and WebP are what this is tested with."
                    ),
                )

            part, original_w, original_h, out_w, out_h = encode(image)
            said = (
                f"{path} is {original_w}x{original_h} and is attached to you as a "
                "picture."
            )
            if (out_w, out_h) != (original_w, original_h):
                said += " " + EDGE_NOTE.format(
                    ow=original_w, oh=original_h, w=out_w, h=out_h
                )
            return ToolResult(
                status=ToolResultStatus.SUCCESS,
                output=said,
                # The model needs to know what it was handed, because the size it
                # reads here is the size on disk and not the size it can see.
                artifacts=[
                    {
                        "type": "image",
                        "path": path,
                        "source": [original_w, original_h],
                        "sent_as": [out_w, out_h],
                    }
                ],
                images=[part],
            )
        except Exception as e:
            return ToolResult(status=ToolResultStatus.ERROR, error=str(e))


@register_tool
class WriteTool(Tool):
    """Create or overwrite a file in the project folder.

    Destructive and confirmation-gated: it replaces existing content, so the
    caller is asked before it happens unless the project is trusted. Reports a
    ``file_change`` artifact so the UI can show a diff.
    """

    name = "write"
    description = "Create or overwrite a file in the project folder."
    category = ToolCategory.FILE
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Relative path from project root"},
            "content": {"type": "string", "description": "File content to write"},
            "encoding": {"type": "string", "enum": ["utf-8", "latin-1"], "default": "utf-8"},
        },
        "required": ["path", "content"],
        "additionalProperties": False,
    }
    destructive = True
    requires_confirmation = True

    async def execute(self, path: str, content: str, encoding: str = "utf-8") -> ToolResult:
        try:
            target = _resolve_path(path)
            target.parent.mkdir(parents=True, exist_ok=True)
            # Read the old contents *before* writing. A file that does not
            # exist yet is all additions, which is the case a naive
            # "diff against empty" would get right by accident and an existing
            # one would get badly wrong.
            previous = ""
            existed = target.exists()
            if existed:
                try:
                    previous = target.read_text(encoding=encoding)
                except (OSError, UnicodeDecodeError):
                    # Unreadable as text (binary, or a different encoding).
                    # The write is still fine; we just cannot say what changed,
                    # and reporting a wrong count would be worse than none.
                    previous = ""
                    existed = False
            target.write_text(content, encoding=encoding)
            added, removed = _line_delta(previous if existed else "", content)
            return ToolResult(
                status=ToolResultStatus.SUCCESS,
                output=f"Written {len(content)} chars to {path}",
                artifacts=[
                    _change_artifact(
                        path,
                        added,
                        removed,
                        _bounded_diff(previous if existed else "", content),
                    )
                ],
            )
        except Exception as e:
            return ToolResult(status=ToolResultStatus.ERROR, error=str(e))


@register_tool
class EditTool(Tool):
    """Replace an exact string inside an existing file.

    **The match has to be unambiguous.** This refuses an ``old_string`` that
    appears more than once, because "replace the first one" is a guess about
    which one the model meant, and a wrong guess is a corruption the model will
    then reason about as if it were intentional. The previous version of this
    tool made exactly that guess, silently.

    The error says how many matches there were and names both ways out: include
    more surrounding context to pin the one that was meant, or pass
    ``replace_all`` to say that all of them are meant. Those are different
    intentions and the tool cannot tell them apart, so it asks rather than
    picking.

    ``old_string`` is matched against the raw file, not the numbered output of
    ``read``. The numbers are a reading aid; the tab and digits in front of a
    line are not part of it.
    """

    name = "edit"
    description = (
        "Replace an exact string in a file. The match must be unique unless "
        "replace_all is set."
    )
    category = ToolCategory.FILE
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Relative path from project root"},
            "old_string": {"type": "string", "description": "Exact text to replace"},
            "new_string": {"type": "string", "description": "Text to replace it with"},
            "replace_all": {
                "type": "boolean",
                "description": "Replace every occurrence instead of requiring a unique one.",
                "default": False,
            },
        },
        "required": ["path", "old_string", "new_string"],
        "additionalProperties": False,
    }
    destructive = True
    requires_confirmation = True

    async def execute(self, path: str, old_string: str, new_string: str,
                      replace_all: bool = False) -> ToolResult:
        try:
            target = _resolve_path(path)
            if not target.exists():
                return ToolResult(status=ToolResultStatus.ERROR, error=f"File not found: {path}")

            # An empty `old_string` matches at every position in the file, so
            # `replace_all` on it would rewrite the whole thing with
            # `new_string` interleaved -- a destructive no-op that reads like a
            # successful edit. Refused by name rather than left to arithmetic.
            if old_string == "":
                return ToolResult(
                    status=ToolResultStatus.ERROR,
                    error="old_string is empty, which matches everywhere in the file",
                )

            content = target.read_text(encoding="utf-8")
            occurrences = content.count(old_string)
            if occurrences == 0:
                return ToolResult(
                    status=ToolResultStatus.ERROR,
                    error=f"old_string not found in {path}",
                )
            if occurrences > 1 and not replace_all:
                return ToolResult(
                    status=ToolResultStatus.ERROR,
                    error=(
                        f"old_string appears {occurrences} times in {path}, so which "
                        "one to replace would be a guess. Include more surrounding "
                        "lines to make it unique, or pass replace_all to replace "
                        "every occurrence."
                    ),
                )

            new_content = (
                content.replace(old_string, new_string)
                if replace_all
                else content.replace(old_string, new_string, 1)
            )
            # Diff the whole file before and after, not just the replaced
            # block: a replacement can shift surrounding lines, and the tree
            # badge is about the file, not the span.
            added, removed = _line_delta(content, new_content)
            target.write_text(new_content, encoding="utf-8")
            replaced = occurrences if replace_all else 1
            return ToolResult(
                status=ToolResultStatus.SUCCESS,
                output=f"Replaced {replaced} occurrence(s) in {path}",
                artifacts=[
                    _change_artifact(
                        path, added, removed, _bounded_diff(content, new_content)
                    )
                ],
            )
        except Exception as e:
            return ToolResult(status=ToolResultStatus.ERROR, error=str(e))


@register_tool
class DeleteFileTool(Tool):
    """Delete a file from the project folder, via the recycle bin.

    Destructive and confirmation-gated. Goes to the recycle bin rather than
    unlinking, so a mistaken call is recoverable by the user but not by the
    agent pretending it can undo itself.
    """

    name = "delete_file"
    description = "Delete a file from the project folder (moves to recycle bin)."
    category = ToolCategory.FILE
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Relative path from project root"},
        },
        "required": ["path"],
        "additionalProperties": False,
    }
    destructive = True
    requires_confirmation = True

    async def execute(self, path: str) -> ToolResult:
        try:
            target = _resolve_path(path)
            if not target.exists():
                return ToolResult(status=ToolResultStatus.ERROR, error=f"File not found: {path}")

            # Count before deleting. A deletion is a pure removal, so the
            # badge is the whole file's line count -- the Files tree shows a
            # struck-through -N and a number nobody can reconcile otherwise.
            removed = 0
            try:
                removed = len(target.read_text(encoding="utf-8", errors="ignore").splitlines())
            except OSError:
                pass

            # No `unlink()` fallback on a missing `send2trash`: that fallback
            # turned the tool's contract -- "moves to the recycle bin" -- into
            # a permanent deletion the transcript still described as a
            # recoverable one. A missing dependency is an error the model (and
            # the user, reading the card) can see and act on.
            import send2trash
            send2trash.send2trash(str(target))

            return ToolResult(
                status=ToolResultStatus.SUCCESS,
                output=f"Deleted {path}",
                artifacts=[_change_artifact(path, 0, removed)],
            )
        except Exception as e:
            return ToolResult(status=ToolResultStatus.ERROR, error=str(e))


@register_tool
class ListDirTool(Tool):
    """List the contents of a directory in the project folder.

    The only file tool with no required arguments: listing the project root is
    a reasonable thing to want, and the default path makes that one call.
    """

    name = "list_dir"
    description = "List directory contents with optional recursion."
    category = ToolCategory.FILE
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Relative path from project root", "default": "."},
            "recursive": {"type": "boolean", "description": "List recursively", "default": False},
            "max_depth": {"type": "integer", "description": "Max recursion depth", "default": 3},
        },
        "additionalProperties": False,
    }
    destructive = False
    requires_confirmation = False

    async def execute(self, path: str = ".", recursive: bool = False, max_depth: int = 3) -> ToolResult:
        try:
            target = _resolve_path(path)
            if not target.exists():
                return ToolResult(status=ToolResultStatus.ERROR, error=f"Path not found: {path}")
            if not target.is_dir():
                return ToolResult(status=ToolResultStatus.ERROR, error=f"Not a directory: {path}")

            entries = []
            if recursive:
                for root, dirs, files in os.walk(target):
                    depth = len(Path(root).relative_to(target).parts)
                    if depth > max_depth:
                        dirs[:] = []
                        continue
                    rel_root = Path(root).relative_to(target)
                    for f in files:
                        entries.append(str(rel_root / f))
                    for d in dirs:
                        entries.append(str(rel_root / d) + "/")
            else:
                for entry in target.iterdir():
                    entries.append(entry.name + ("/" if entry.is_dir() else ""))

            entries.sort()
            output = "\n".join(entries) if entries else "(empty)"
            return ToolResult(status=ToolResultStatus.SUCCESS, output=output)
        except Exception as e:
            return ToolResult(status=ToolResultStatus.ERROR, error=str(e))
