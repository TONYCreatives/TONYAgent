"""Search tools for TONYAgent."""

from __future__ import annotations

import re
import fnmatch
from pathlib import Path
from typing import Any

from tonyagent.tools.base import Tool, ToolResult, ToolResultStatus, ToolCategory, register_tool
from tonyagent.tools.workspace import relative
from tonyagent.tools.workspace import confine as _resolve_path


def _escapes_the_project(pattern: str) -> bool:
    """Whether a glob *pattern* walks out of the project folder.

    A pattern is not a path, but it is composed of path segments and it is
    handed to a filesystem walk, so it can climb: ``../*/*.txt`` leaves the
    project in its first two characters. Two things are refused -- a pattern
    that is absolute (``Path.rglob`` rejects one with ``NotImplementedError``
    anyway, which used to surface as "Tool execution failed"), and any ``..``
    segment, split on both separators so the Windows spelling is caught too.

    Deliberately not a general pattern validator: ``**/*.py``, ``a..b/*.txt``
    and a leading ``./`` are all fine, and the only property that matters here
    is whether the walk can leave the folder.
    """
    # A leading separator counts as absolute here as well as
    # `Path.is_absolute()`: on Windows the latter is False for `/abs/*` (no
    # drive letter), and the walk's own rejection of it is a
    # `NotImplementedError` paraphrased as "Tool execution failed" -- no use to
    # a model that has to change the pattern.
    if pattern.startswith(("/", "\\")) or Path(pattern).is_absolute():
        return True
    return ".." in re.split(r"[\\/]", pattern)


def _should_skip(path: Path) -> bool:
    """Skip VCS/build/venv dirs and binary-ish files during a scan."""
    skip_dirs = {".git", "__pycache__", ".venv", "venv", "node_modules", ".pytest_cache", ".mypy_cache", "dist", "build", ".tonyagent"}
    skip_files = {".pyc", ".pyo", ".pyd", ".so", ".dll", ".exe", ".bin", ".dat", ".db", ".sqlite", ".sqlite3"}

    for part in path.parts:
        if part in skip_dirs:
            return True
    if path.suffix in skip_files:
        return True
    return False


def _iter_matches(file_path: Path, regex, max_results: int):
    """Yield (line_no, text) matches, streaming the file line by line.

    Reading whole files with read_text() is what made grep unusable on large
    repos: one 200MB log exhausted memory. This reads incrementally and stops
    as soon as max_results is reached.
    """
    matches = []
    try:
        with file_path.open("r", encoding="utf-8", errors="ignore") as handle:
            for line_no, line in enumerate(handle, 1):
                if regex.search(line):
                    matches.append((line_no, line.rstrip("\n")[:200]))
                    if len(matches) >= max_results:
                        return matches
    except Exception:
        return matches
    return matches


def _extract_context(file_path: Path, line_no: int, before: int, after: int) -> str:
    """Return the matched line plus N lines either side, > marking the match."""
    try:
        lines = file_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except Exception:
        return ""
    start = max(0, line_no - 1 - before)
    end = min(len(lines), line_no + after)
    block = []
    for idx in range(start, end):
        marker = ">" if idx == line_no - 1 else " "
        block.append(f"{marker} {idx + 1}: {lines[idx][:200]}")
    return "\n".join(block)


@register_tool
class GrepTool(Tool):
    """Search file contents with a regex, confined to the project folder.

    Reports ``file:line`` matches with surrounding context so the model can act
    on a hit without re-reading the file. Unparseable output is truncated at
    ``max_output_size`` and says so, rather than silently losing the tail.
    """

    name = "grep"
    description = "Search for a regex pattern in file contents within the project."
    category = ToolCategory.SEARCH
    parameters = {
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "Regex pattern to search for"},
            "path": {"type": "string", "description": "Relative path to search in", "default": "."},
            "include": {"type": "string", "description": "File pattern to include (e.g., *.py)"},
            "case_sensitive": {"type": "boolean", "default": True},
            "max_results": {"type": "integer", "default": 100},
            "context_lines": {
                "type": "integer",
                "description": "Lines of context to show around each match", "default": 0,
            },
            "max_filesize_mb": {
                "type": "integer",
                "description": "Skip files larger than this many MB", "default": 10,
            },
        },
        "required": ["pattern"],
        "additionalProperties": False,
    }
    destructive = False
    requires_confirmation = False

    async def execute(
        self,
        pattern: str,
        path: str = ".",
        include: str = "",
        case_sensitive: bool = True,
        max_results: int = 100,
        context_lines: int = 0,
        max_filesize_mb: int = 10,
    ) -> ToolResult:
        try:
            target = _resolve_path(path)
            if not target.exists():
                return ToolResult(status=ToolResultStatus.ERROR, error=f"Path not found: {path}")

            flags = 0 if case_sensitive else re.IGNORECASE
            try:
                regex = re.compile(pattern, flags)
            except re.error as e:
                return ToolResult(status=ToolResultStatus.ERROR, error=f"Invalid regex: {e}")

            def match_file(p: Path) -> bool:
                return fnmatch.fnmatch(p.name, include) if include else True

            max_bytes = max(0, int(max_filesize_mb)) * 1024 * 1024
            before = after = max(0, int(context_lines))
            limit = max(1, int(max_results))

            results = []
            files_searched = 0
            files_skipped = 0
            truncated = False

            for candidate in target.rglob("*"):
                # Confined before it is read, not merely before it is reported:
                # a walk that reaches out of the project through a symlink has
                # no business having its contents searched either.
                if _should_skip(candidate) or relative(candidate) is None:
                    continue
                if not candidate.is_file() or not match_file(candidate):
                    continue
                file_path = candidate
                if max_bytes:
                    try:
                        if file_path.stat().st_size > max_bytes:
                            files_skipped += 1
                            continue
                    except OSError:
                        continue

                files_searched += 1
                for line_no, text in _iter_matches(file_path, regex, limit - len(results)):
                    entry = {
                        "file": relative(file_path),
                        "line": line_no,
                        "content": text.strip(),
                    }
                    if before or after:
                        entry["context"] = _extract_context(file_path, line_no, before, after)
                    results.append(entry)
                    if len(results) >= limit:
                        truncated = True
                        break
                if len(results) >= limit:
                    break

            lines_out = []
            for r in results:
                if r.get("context"):
                    lines_out.append(f"{r['file']}:{r['line']}:\n{r['context']}")
                else:
                    lines_out.append(f"{r['file']}:{r['line']}: {r['content']}")

            note = " [truncated at max_results]" if truncated else ""
            skip_note = f", {files_skipped} file(s) skipped over size limit" if files_skipped else ""
            output = f"Found {len(results)} matches in {files_searched} files{skip_note}{note}:\n"
            output += "\n".join(lines_out)

            return ToolResult(
                status=ToolResultStatus.SUCCESS,
                output=output,
                artifacts=[{"type": "grep_result", "data": results}],
            )
        except Exception as e:
            return ToolResult(status=ToolResultStatus.ERROR, error=str(e))


@register_tool
class GlobTool(Tool):
    """Find files by name using a glob pattern.

    The companion to ``grep``: one finds what to read, the other finds what is
    inside it.
    """

    name = "glob"
    description = "Find files matching a glob pattern within the project."
    # The *pattern* is confined as well as the path, and that is not belt and
    # braces -- it is a hole this pass found live. `path` was confined while
    # `pattern` was handed straight to `rglob`, so `../*/*.txt` listed files
    # from the parent directory and reported them as siblings of the project
    # (the display path came from a *lexical* `relative_to`, which happily
    # returns `..\elsewhere\secret.txt`). See `_escapes_the_project`.
    category = ToolCategory.SEARCH
    parameters = {
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "Glob pattern (e.g., **/*.py)"},
            "path": {"type": "string", "description": "Relative path to search in", "default": "."},
            "max_results": {
                "type": "integer",
                "description": "Maximum paths to return", "default": 200,
            },
        },
        "required": ["pattern"],
        "additionalProperties": False,
    }
    destructive = False
    requires_confirmation = False

    async def execute(self, pattern: str, path: str = ".", max_results: int = 200) -> ToolResult:
        try:
            target = _resolve_path(path)
            if not target.exists():
                return ToolResult(status=ToolResultStatus.ERROR, error=f"Path not found: {path}")
            if _escapes_the_project(pattern):
                return ToolResult(
                    status=ToolResultStatus.ERROR,
                    error=(
                        f"Pattern '{pattern}' reaches outside the project folder, "
                        "which is the boundary every file tool works inside. "
                        "Search for something in the project, or ask the user for "
                        "the file you need."
                    ),
                )

            limit = max(1, int(max_results))
            matches = []
            truncated = False
            for file_path in target.rglob(pattern):
                if _should_skip(file_path):
                    continue
                # Resolved, not merely relativised: `rglob` can reach a file
                # through a symlink that leaves the project, and a lexical
                # `relative_to` would report that path instead of refusing it.
                shown = relative(file_path)
                if shown is None:
                    continue
                matches.append(shown)
                if len(matches) >= limit:
                    truncated = True
                    break

            matches.sort()
            # The old one-liner was `"Found..." + join if matches else "No matches"`,
            # which parses as (concat) if matches else "No matches" - it only looked
            # right by accident and reported a bogus count on the empty path.
            if matches:
                note = " [truncated at max_results]" if truncated else ""
                output = f"Found {len(matches)} files{note}:\n" + "\n".join(matches)
            else:
                output = "No matches found"

            return ToolResult(
                status=ToolResultStatus.SUCCESS,
                output=output,
                artifacts=[{"type": "glob_result", "data": matches}],
            )
        except Exception as e:
            return ToolResult(status=ToolResultStatus.ERROR, error=str(e))

