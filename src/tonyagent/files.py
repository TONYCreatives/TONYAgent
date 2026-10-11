"""Reading project files for the window's code viewer.

**Why this is a module and not two more tools.** The viewer is the *user*
looking at code, not the model; but the files it may look at are the same
files the tools may touch, under the same boundary -- so the confinement
comes from `tonyagent.tools.workspace`, the one home, and the skip rules
come from the same `_should_skip` the agent's grep uses. A second
implementation of either rule is a second thing to disagree with the first.

**Reads, never writes.** There is deliberately no write path here. The
agent's `write` tool is confirmation-gated for a reason, and a UI write
that skipped the same gate would be a second, quieter door into the project
-- the class of hole the last audit pass spent itself closing. Editing is a
surface of its own, with that gate designed for it.

The viewer is read-only *by nature*, and read-only *by policy* while a turn
is running: the window enforces the second as a lock on the first, which is
what keeps a long generation from being raced by a half-scrolled read.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from tonyagent.tools.search_tools import _should_skip
from tonyagent.tools.workspace import confine, project_root

#: Largest file the viewer will hand to the window, in bytes.
#:
#: The read is one RPC reply rendered into one tab; a 40 MB minified bundle
#: would be a window that stops responding while it tokenises. The cap is
#: returned with the refusal so the viewer can say what it did not show.
MAX_SOURCE_BYTES = 1_048_576

#: Entries one tree walk will report.
#:
#: Bounded because a monorepo has no interesting upper limit, and an
#: unbounded walk is a reply that never ends. Truncation is reported, not
#: silently dropped -- a tree that claims to be complete when it is not is
#: worse than one that says where it stopped.
MAX_TREE_ENTRIES = 4000

#: How deep the walk goes by default.
#:
#: Six levels covers every layout this project has been used on (`src/
#: tonyagent/tools/` is three) while keeping `node_modules`-shaped trees
#: from eating the budget on paths nobody opens.
MAX_TREE_DEPTH = 6


#: Extension -> language id.
#:
#: The ids are the ones the frontend's tokeniser knows (`app/src/highlight.ts`),
#: and the mapping lives here so the *core* decides what a file is and the
#: window never has to guess from a name. A file with no entry reads as
#: `plain`, which is a rendering decision the viewer makes honestly rather
#: than highlighting a `.conf` as if it were shell.
LANGUAGES: dict[str, str] = {
    # TypeScript and JavaScript, kept separate from JSX because the token
    # boundaries differ in ways that matter (a `<div>` is a type assertion
    # or a tag, depending).
    "ts": "typescript", "mts": "typescript", "cts": "typescript",
    "tsx": "tsx",
    "js": "javascript", "mjs": "javascript", "cjs": "javascript",
    "jsx": "jsx",
    "py": "python", "pyi": "python",
    "json": "json", "jsonc": "json",
    "css": "css", "scss": "css", "sass": "css", "less": "css",
    "html": "html", "htm": "html", "xhtml": "html",
    "md": "markdown", "markdown": "markdown",
    "sh": "shell", "bash": "shell", "zsh": "shell", "fish": "shell",
    "ps1": "shell", "psm1": "shell",
    "yml": "yaml", "yaml": "yaml",
    "toml": "toml", "ini": "ini", "cfg": "ini", "conf": "ini",
    "rs": "rust",
    "go": "go",
    "sql": "sql",
    "java": "java", "kt": "java", "kts": "java",
    "c": "c", "h": "c",
    "cpp": "cpp", "cc": "cpp", "cxx": "cpp", "hpp": "cpp", "hh": "cpp",
    "cs": "cs",
    "rb": "ruby", "rake": "ruby",
    "php": "php",
    "xml": "xml", "svg": "xml", "xaml": "xml", "csproj": "xml",
    "txt": "plain", "log": "plain",
}

#: Whole *file names* that are not about their extension.
FILENAME_LANGUAGES: dict[str, str] = {
    "dockerfile": "shell",
    "makefile": "shell",
    ".gitignore": "ini",
    ".gitattributes": "ini",
    ".env": "shell",
}


def language_for(path: str | Path) -> str:
    """The language id the viewer highlights this file with.

    Filenames win over extensions on purpose: a `Dockerfile` is shell-shaped
    regardless of what its (absent) suffix claims, and highlighting it as
    plain would lose every comment in it.
    """
    name = Path(path).name
    lowered = name.lower()
    if lowered in FILENAME_LANGUAGES:
        return FILENAME_LANGUAGES[lowered]
    if lowered.startswith(".env"):
        return "shell"
    return LANGUAGES.get(lowered.rsplit(".", 1)[-1] if "." in lowered else "", "plain")


@dataclass
class TreeEntry:
    """One row of the project tree, as the window receives it."""

    path: str  # project-relative, POSIX separators
    kind: str  # "dir" | "file"
    size: int = 0
    children_count: int = 0

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "kind": self.kind,
            "size": self.size,
            "children_count": self.children_count,
        }


@dataclass
class TreeResult:
    entries: list[TreeEntry] = field(default_factory=list)
    truncated: bool = False

    def to_dict(self) -> dict:
        return {
            "entries": [entry.to_dict() for entry in self.entries],
            "truncated": self.truncated,
        }


def project_tree(
    path: str = ".",
    max_entries: int = MAX_TREE_ENTRIES,
    max_depth: int = MAX_TREE_DEPTH,
) -> TreeResult:
    """The project tree under `path`, confined to the project folder.

    Skipped directories are skipped *whole* -- the same `_should_skip` the
    agent's grep uses, applied per segment so a `node_modules` three levels
    down costs one `os.scandir` rather than a walk of everything under it.
    Depth and count both bound, and both are reported.
    """
    root = confine(path)
    entries: list[TreeEntry] = []
    truncated = False

    def on_error(_exc: OSError) -> None:
        # A folder the process may not read is not an error the viewer can
        # act on; the row simply does not appear. The alternative -- an
        # exception out of the RPC -- would take the whole tree with it.
        return

    for current, dirs, files in root.walk(top_down=True, on_error=on_error):
        rel_dir = current.relative_to(root)
        depth = len(rel_dir.parts)
        if depth >= max_depth:
            dirs[:] = []
        # Pruned before descent: `dirs[:]` is what os.walk reads.
        dirs[:] = sorted(d for d in dirs if not _should_skip(current / d))
        for name in sorted(dirs):
            if len(entries) >= max_entries:
                truncated = True
                dirs[:] = []
                break
            child = current / name
            entries.append(
                TreeEntry(
                    path=(rel_dir / name).as_posix() if rel_dir.parts else name,
                    kind="dir",
                )
            )
        for name in sorted(files):
            if len(entries) >= max_entries:
                truncated = True
                break
            child = current / name
            if _should_skip(child):
                continue
            try:
                size = child.stat().st_size
            except OSError:
                size = 0
            entries.append(
                TreeEntry(
                    path=(rel_dir / name).as_posix() if rel_dir.parts else name,
                    kind="file",
                    size=size,
                )
            )
    return TreeResult(entries=entries, truncated=truncated)


@dataclass
class SourceFile:
    """One file's text, ready for the viewer."""

    path: str
    content: str
    total_lines: int
    language: str
    size: int
    truncated: bool = False

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "content": self.content,
            "total_lines": self.total_lines,
            "language": self.language,
            "size": self.size,
            "truncated": self.truncated,
        }


class SourceError(Exception):
    """A file the viewer cannot show, with the reason it cannot."""


def read_source(path: str) -> SourceFile:
    """Read one project file for the viewer, or raise `SourceError`.

    Three refusals, each with a sentence the window can show rather than a
    stack: outside the project (the boundary), not a file (a directory), and
    either binary or over the size cap (the first by decoding strictly, the
    second by measuring first).

    `confine`'s refusal is a `ValueError` and is re-raised as a
    `SourceError`, so one `except` at the call site covers every way a read
    can be refused -- a caller that had to catch two exception types would
    eventually catch one.
    """
    try:
        target = confine(path)
    except ValueError as exc:
        raise SourceError(str(exc)) from None
    if not target.exists():
        raise SourceError(f"File not found: {path}")
    if not target.is_file():
        raise SourceError(f"Not a file: {path}")

    try:
        size = target.stat().st_size
    except OSError as exc:
        raise SourceError(f"Could not read {path}: {exc}") from exc

    if size > MAX_SOURCE_BYTES:
        raise SourceError(
            f"{path} is {size / (1024 * 1024):.1f} MB, over the "
            f"{MAX_SOURCE_BYTES // (1024 * 1024)} MB limit for the viewer."
        )

    try:
        raw = target.read_bytes()
    except OSError as exc:
        raise SourceError(f"Could not read {path}: {exc}") from exc

    if b"\x00" in raw[:8192]:
        raise SourceError(f"{path} is a binary file, which the viewer does not show.")

    try:
        content = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SourceError(f"{path} is not valid UTF-8 text ({exc.reason}).") from exc

    truncated = False
    if len(content) > MAX_SOURCE_BYTES:
        content = content[:MAX_SOURCE_BYTES]
        truncated = True

    rel = str(target.relative_to(project_root()).as_posix())
    return SourceFile(
        path=rel,
        content=content,
        total_lines=content.count("\n") + 1,
        language=language_for(rel),
        size=size,
        truncated=truncated,
    )
