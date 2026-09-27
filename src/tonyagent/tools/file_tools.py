"""File operation tools for TONYAgent."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from tonyagent.tools.base import Tool, ToolResult, ToolResultStatus, ToolCategory, register_tool
from tonyagent.folder.manager import folder_manager


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
            target.write_text(content, encoding=encoding)
            return ToolResult(status=ToolResultStatus.SUCCESS, output=f"Written {len(content)} chars to {path}")
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
            target.write_text(new_content, encoding="utf-8")
            return ToolResult(status=ToolResultStatus.SUCCESS, output=f"Replaced 1 occurrence in {path}")
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
            
            try:
                import send2trash
                send2trash.send2trash(str(target))
            except ImportError:
                target.unlink()
            
            return ToolResult(status=ToolResultStatus.SUCCESS, output=f"Deleted {path}")
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