"""File operation tools for TONYAgent."""

from __future__ import annotations

import difflib
import os
from pathlib import Path
from typing import Any

from tonyagent.tools.base import Tool, ToolResult, ToolResultStatus, ToolCategory, register_tool
from tonyagent.folder.manager import folder_manager


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


def _change_artifact(path: str, added: int, removed: int) -> dict:
    """The machine-readable form the Files tree reads.

    Kept separate from `output`, which stays a human sentence, because the
    transcript and the tree want the same fact in two different shapes.
    """
    return {
        "type": "file_change",
        "data": {"path": path, "added": added, "removed": removed},
    }


def _resolve_path(path: str) -> Path:
    """Resolve path relative to project folder with safety checks."""
    project_root = folder_manager.current_folder
    if not project_root:
        raise ValueError("No project folder selected")
    
    target = (project_root / path).resolve()
    
    try:
        target.relative_to(project_root.resolve())
    except ValueError:
        raise ValueError(f"Path '{path}' attempts to escape project folder")
    
    return target
@register_tool
class ReadFileTool(Tool):
    name = "read_file"
    description = "Read the contents of a file from the project folder."
    category = ToolCategory.FILE
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Relative path from project root"},
            "encoding": {"type": "string", "enum": ["utf-8", "latin-1", "cp1252"], "default": "utf-8"},
        },
        "required": ["path"],
        "additionalProperties": False,
    }
    destructive = False
    requires_confirmation = False

    async def execute(self, path: str, encoding: str = "utf-8") -> ToolResult:
        try:
            target = _resolve_path(path)
            if not target.exists():
                return ToolResult(status=ToolResultStatus.ERROR, error=f"File not found: {path}")
            if not target.is_file():
                return ToolResult(status=ToolResultStatus.ERROR, error=f"Not a file: {path}")
            
            content = target.read_text(encoding=encoding)
            return ToolResult(status=ToolResultStatus.SUCCESS, output=content)
        except Exception as e:
            return ToolResult(status=ToolResultStatus.ERROR, error=str(e))


@register_tool
class WriteFileTool(Tool):
    name = "write_file"
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
                artifacts=[_change_artifact(path, added, removed)],
            )
        except Exception as e:
            return ToolResult(status=ToolResultStatus.ERROR, error=str(e))


@register_tool
class EditFileTool(Tool):
    name = "edit_file"
    description = "Edit a file by replacing old_text with new_text (exact match required)."
    category = ToolCategory.FILE
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Relative path from project root"},
            "old_text": {"type": "string", "description": "Exact text to replace"},
            "new_text": {"type": "string", "description": "New text to insert"},
        },
        "required": ["path", "old_text", "new_text"],
        "additionalProperties": False,
    }
    destructive = True
    requires_confirmation = True

    async def execute(self, path: str, old_text: str, new_text: str) -> ToolResult:
        try:
            target = _resolve_path(path)
            if not target.exists():
                return ToolResult(status=ToolResultStatus.ERROR, error=f"File not found: {path}")
            
            content = target.read_text(encoding="utf-8")
            if old_text not in content:
                return ToolResult(status=ToolResultStatus.ERROR, error="old_text not found in file")
            
            new_content = content.replace(old_text, new_text, 1)
            # Diff the whole file before and after, not just the replaced
            # block: a replacement can shift surrounding lines, and the tree
            # badge is about the file, not the span.
            added, removed = _line_delta(content, new_content)
            target.write_text(new_content, encoding="utf-8")
            return ToolResult(
                status=ToolResultStatus.SUCCESS,
                output=f"Replaced 1 occurrence in {path}",
                artifacts=[_change_artifact(path, added, removed)],
            )
        except Exception as e:
            return ToolResult(status=ToolResultStatus.ERROR, error=str(e))


@register_tool
class DeleteFileTool(Tool):
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

            try:
                import send2trash
                send2trash.send2trash(str(target))
            except ImportError:
                target.unlink()

            return ToolResult(
                status=ToolResultStatus.SUCCESS,
                output=f"Deleted {path}",
                artifacts=[_change_artifact(path, 0, removed)],
            )
        except Exception as e:
            return ToolResult(status=ToolResultStatus.ERROR, error=str(e))

@register_tool
class ListDirTool(Tool):
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