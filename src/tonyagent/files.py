"""Reading project files for the window's code viewer, and saving them back.

**Why this is a module and not two more tools.** The viewer is the *user*
looking at code, not the model; but the files it may look at are the same
files the tools may touch, under the same boundary -- so the confinement
comes from `tonyagent.tools.workspace`, the one home, and the skip rules
come from the same `_should_skip` the agent's grep uses. A second
implementation of either rule is a second thing to disagree with the first.

**The write path is the user's, and that is the whole reason it is
allowed.** The agent's `write` tool is confirmation-gated because the user
has to approve what the *agent* does to their files. A person typing in the
editor they are looking at is not that: the edit is the user's own act, the
same keystrokes they would make in VSCode. What this module owes them
instead is the rest of the discipline -- confined, size-capped, atomic
(a temp file and a rename, so a crash mid-write cannot truncate a source
file), mode-preserving, and *reported*: the save returns what changed, and
`format_edit_report` is how those changes reach the model on the next
message, so the agent is never reasoning about a file it last saw in a
different state.

The viewer is still read-only *while a turn is running*, and that is
enforced in the window rather than here: the core has no way to know that a
save was typed rather than pasted, and the lock is a statement about the
agent working, not about who is allowed to write.
"""

from __future__ import annotations

import os
import tempfile
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

#: Largest image the viewer will preview, in bytes.
#:
#: Larger than the text cap because an image is *displayed* rather than
#: parsed, and a photograph that is 4 MB says nothing about a decode budget
#: the way a 4 MB source file does. The bytes that cross the pipe are then
#: bounded again by the downscale below -- this is the bound on what is read
#: off disk and handed to Pillow.
MAX_IMAGE_BYTES = 32 * 1024 * 1024

#: Longest edge of an image sent to the window.
#:
#: `tools.images.encode` owns the *model's* limit (1568, OpenAI's own number
#: for the large edge) and takes a caller's own name for it, which is what
#: this is: a picture shown in a resizable pane on a large monitor is worth
#: more detail than one a model is reading, and less than the original --
#: 2048 fits a 4K pane at roughly a quarter of the pixels.
VIEWER_MAX_EDGE = 2048

#: Largest PDF the viewer will preview, in bytes.
#:
#: Half the image cap: a PDF's bytes cross the pipe whole (unlike an image,
#: which is downscaled first), and a PDF embeds fonts and images the frame
#: decodes itself. Over the cap the file is still nameable -- it answers as
#: `binary` with the reason, and the viewer offers it externally.
MAX_PDF_BYTES = 16 * 1024 * 1024

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

#: How many files one edit report will name, and how many line ranges per
#: file. Both are caps on what the *model* is handed: a user who touched two
#: hundred files in one sitting has not produced two hundred facts the next
#: message needs, and a message nobody can read is worse than a summary.
MAX_REPORTED_FILES = 20
MAX_REPORTED_RANGES = 40

#: Suffix -> MIME type, for the images the viewer can show.
#:
#: A table rather than `mimetypes.guess_type`, which answers from the
#: machine's registry on Windows and can disagree with itself between two
#: installs for the same file. This is the window's own list: what it will
#: preview is what is here, and everything else is "no preview" rather than
#: a guess that fails to decode.
IMAGE_MIMES: dict[str, str] = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "gif": "image/gif",
    "webp": "image/webp",
    "bmp": "image/bmp",
    "ico": "image/x-icon",
    "avif": "image/avif",
    # Decoded by Pillow and re-encoded as PNG by `read_image_file`, so the
    # window never needs to draw the source format itself -- which matters
    # because Chromium does not draw TIFF at all.
    "tif": "image/tiff",
    "tiff": "image/tiff",
}


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
    # Data tables, which the viewer offers as a grid as well as as text.
    "csv": "csv", "tsv": "csv",
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
            "kind": "text",
            "path": self.path,
            "content": self.content,
            "total_lines": self.total_lines,
            "language": self.language,
            "size": self.size,
            "truncated": self.truncated,
        }


class SourceError(Exception):
    """A file the viewer cannot show, with the reason it cannot."""


@dataclass
class PdfFile:
    """A PDF, as a data URL the window's native frame can draw.

    The bytes go *in the reply*, like `ImageFile`: the webview can load
    `data:` and nothing else off-disk, and a spike confirmed its Chromium
    frame draws a `data:application/pdf` URL with the native toolbar
    (paging, zoom) for free. No rasterising here: that would need a PDF
    engine the core does not have, to redo what the frame already does.
    """

    path: str
    mime: str
    data: str
    size: int

    def to_dict(self) -> dict:
        return {
            "kind": "pdf",
            "path": self.path,
            "mime": self.mime,
            "data": self.data,
            "size": self.size,
        }


@dataclass
class BinaryFile:
    """Something the window can name but not draw.

    A *successful* answer rather than an error, and that is a deliberate
    split: "this is a binary" and "this file is not there" are different
    things, and only the second is a failure. The pane shows the name, the
    size and the reason, which is a better outcome for a `.zip` than a
    banner apologising for one.
    """

    path: str
    size: int
    reason: str

    def to_dict(self) -> dict:
        return {
            "kind": "binary",
            "path": self.path,
            "size": self.size,
            "reason": self.reason,
        }


@dataclass
class ImageFile:
    """A picture, as a data URL the window can draw.

    The bytes go *in the reply* rather than over a side channel: the webview
    can load `data:` (its content policy allows exactly that, and nothing
    else off-disk), and the core already owns reading project files under
    the boundary. `display_width`/`display_height` are what the window is
    given, which is the source size unless the long edge hit the cap.
    """

    path: str
    mime: str
    data: str
    size: int
    width: int
    height: int
    display_width: int
    display_height: int

    @property
    def downscaled(self) -> bool:
        return (self.display_width, self.display_height) != (self.width, self.height)

    def to_dict(self) -> dict:
        return {
            "kind": "image",
            "path": self.path,
            "mime": self.mime,
            "data": self.data,
            "size": self.size,
            "width": self.width,
            "height": self.height,
            "display_width": self.display_width,
            "display_height": self.display_height,
            "downscaled": self.downscaled,
        }


def _mime_for(path: Path) -> str | None:
    """The viewer's MIME for an image, or None when it is not one it shows."""
    suffix = path.suffix.lower().lstrip(".")
    return IMAGE_MIMES.get(suffix)


def read_svg_file(path: str) -> ImageFile:
    """Read an SVG as an image the window draws natively.

    Not through Pillow, which cannot open SVG: the raw text *is* the image,
    so it is base64'd straight into the reply and the window's `<img>` draws
    it as `image/svg+xml`. Dimensions are unknown without parsing the tag,
    so they are zero and the footer says "vector" -- see the viewer.
    """
    import base64

    target = confine(path)
    if not target.is_file():
        raise SourceError(f"Not a file: {path}")

    try:
        size = target.stat().st_size
    except OSError as exc:
        raise SourceError(f"Could not read {path}: {exc}") from exc
    if size > MAX_IMAGE_BYTES:
        raise SourceError(
            f"{path} is {size / (1024 * 1024):.1f} MB, over the "
            f"{MAX_IMAGE_BYTES // (1024 * 1024)} MB limit for an image preview."
        )

    try:
        raw = target.read_bytes()
    except OSError as exc:
        raise SourceError(f"Could not read {path}: {exc}") from exc
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SourceError(f"{path} is not valid UTF-8 text ({exc.reason}).") from exc
    if "<svg" not in text[:4096].lower():
        raise SourceError(f"{path} is not an SVG image.")

    return ImageFile(
        path=str(target.relative_to(project_root()).as_posix()),
        mime="image/svg+xml",
        data=base64.b64encode(raw).decode("ascii"),
        size=size,
        width=0,
        height=0,
        display_width=0,
        display_height=0,
    )


def read_image_file(path: str) -> ImageFile:
    """Read an image for the viewer, downscaled to `VIEWER_MAX_EDGE`.

    Pillow is imported here rather than at module scope, matching
    `file_tools`: a machine with a broken Pillow should fail *this* read,
    not the whole server's import.
    """
    target = confine(path)
    if not target.is_file():
        raise SourceError(f"Not a file: {path}")

    try:
        size = target.stat().st_size
    except OSError as exc:
        raise SourceError(f"Could not read {path}: {exc}") from exc
    if size > MAX_IMAGE_BYTES:
        raise SourceError(
            f"{path} is {size / (1024 * 1024):.1f} MB, over the "
            f"{MAX_IMAGE_BYTES // (1024 * 1024)} MB limit for an image preview."
        )

    from PIL import Image, UnidentifiedImageError

    from tonyagent.tools.images import encode

    try:
        image = Image.open(target)
        image.load()
    except UnidentifiedImageError as exc:
        raise SourceError(f"{path} is not an image that can be opened.") from exc
    except OSError as exc:
        raise SourceError(f"Could not read {path}: {exc}") from exc

    part, width, height, display_width, display_height = encode(image, VIEWER_MAX_EDGE)
    return ImageFile(
        path=str(target.relative_to(project_root()).as_posix()),
        mime=part["mime"],
        data=part["data"],
        size=size,
        width=width,
        height=height,
        display_width=display_width,
        display_height=display_height,
    )


def read_pdf_file(path: str) -> PdfFile:
    """Read a PDF for the viewer's native frame, or raise `SourceError`.

    Validated by magic, not by suffix alone: a text file renamed to `.pdf`
    is a `SourceError` here, which `read_for_viewer` answers as `binary` --
    the honest report of a mislabelled file, rather than a frame choking on
    bytes it cannot draw.
    """
    import base64

    target = confine(path)
    if not target.is_file():
        raise SourceError(f"Not a file: {path}")

    try:
        size = target.stat().st_size
    except OSError as exc:
        raise SourceError(f"Could not read {path}: {exc}") from exc
    if size > MAX_PDF_BYTES:
        raise SourceError(
            f"{path} is {size / (1024 * 1024):.1f} MB, over the "
            f"{MAX_PDF_BYTES // (1024 * 1024)} MB limit for a PDF preview."
        )

    try:
        raw = target.read_bytes()
    except OSError as exc:
        raise SourceError(f"Could not read {path}: {exc}") from exc
    if not raw.startswith(b"%PDF"):
        raise SourceError(f"{path} is not a PDF file.")

    return PdfFile(
        path=str(target.relative_to(project_root()).as_posix()),
        mime="application/pdf",
        data=base64.b64encode(raw).decode("ascii"),
        size=size,
    )


def read_for_viewer(path: str) -> SourceFile | ImageFile | PdfFile | BinaryFile:
    """Whatever the viewer should show for `path`.

    One entry point, four answers, and the choice is made *here* rather
    than by the window: the core knows the file's own bytes (an image is an
    image because it decodes, not because of its name) and owns the caps.

    An image is dispatched on its suffix rather than by trying to decode
    every file, because decoding everything to find out would mean opening
    a 900 MB video to learn it is not a picture. A file whose suffix says
    image but whose bytes do not decode is then a `SourceError`, which is
    the honest report of a mislabelled file. A PDF is dispatched the same
    way, on its suffix, and validated by magic.
    """
    target = confine(path)
    if not target.exists():
        raise SourceError(f"File not found: {path}")
    if not target.is_file():
        raise SourceError(f"Not a file: {path}")

    if _mime_for(target) is not None:
        return read_image_file(path)

    # SVG is text, so without this it would read as `xml` source. It draws
    # natively as an image, which is the more useful view -- with the source
    # one toggle away, like markdown's preview.
    if target.suffix.lower() == ".svg":
        return read_svg_file(path)

    if target.suffix.lower() == ".pdf":
        try:
            return read_pdf_file(path)
        except SourceError as exc:
            try:
                size = target.stat().st_size
            except OSError:
                size = 0
            return BinaryFile(
                path=str(target.relative_to(project_root()).as_posix()),
                size=size,
                reason=str(exc),
            )

    try:
        source = read_source(path)
    except SourceError as exc:
        # Every remaining refusal from the text path -- binary, not UTF-8,
        # over the cap -- is a file the window can name but not draw, which
        # is a view rather than a failure. The ones above are failures.
        try:
            size = target.stat().st_size
        except OSError:
            size = 0
        return BinaryFile(
            path=str(target.relative_to(project_root()).as_posix()),
            size=size,
            reason=str(exc),
        )
    return source


def read_source(path: str) -> SourceFile:
    """Read one project file as text for the viewer, or raise `SourceError`.

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


@dataclass
class SavedFile:
    """What a save changed, as the window and the badge need it."""

    path: str
    size: int
    total_lines: int
    added: int
    removed: int
    language: str

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "size": self.size,
            "total_lines": self.total_lines,
            "added": self.added,
            "removed": self.removed,
            "language": self.language,
        }


def write_source(path: str, content: str) -> SavedFile:
    """Save the user's text back to a project file.

    **Atomic, and that is not a flourish.** The naive `write_text` truncates
    the file first: a crash, a full disk or a killed process between the
    truncate and the write leaves the user's source file empty, and this is
    the one operation in the window that can destroy work. A temp file in
    the same directory plus `os.replace` makes the switch a rename, so the
    file on disk is either the old bytes or the new ones and never a
    half-written third thing.

    **The mode is carried over.** A temp file is created with the process's
    default mode, so replacing a `#!/bin/sh` script with one would quietly
    strip its executable bit. The original's mode is copied onto the temp
    file before the swap.

    Only existing files, and only text. This is the viewer's save, not a way
    to create files where the core was never pointed; a new file is the
    agent's `write` tool's business, where the user has already been asked.
    """
    try:
        target = confine(path)
    except ValueError as exc:
        raise SourceError(str(exc)) from None
    if not target.exists():
        raise SourceError(f"File not found: {path}")
    if not target.is_file():
        raise SourceError(f"Not a file: {path}")
    if not isinstance(content, str):
        raise SourceError("The viewer only saves text.")

    encoded = content.encode("utf-8")
    if len(encoded) > MAX_SOURCE_BYTES:
        raise SourceError(
            f"That is {len(encoded) / (1024 * 1024):.1f} MB, over the "
            f"{MAX_SOURCE_BYTES // (1024 * 1024)} MB limit for a save."
        )

    try:
        before = target.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError):
        # Not text as it stood, so there is no honest diff to compute. The
        # save still goes ahead; the badge just reports no line change
        # rather than a wrong one.
        before = ""

    temp_path = _write_temp(target, content)
    from tonyagent.tools.file_tools import _line_delta

    added, removed = _line_delta(before, content)
    return SavedFile(
        path=str(target.relative_to(project_root()).as_posix()),
        size=len(encoded),
        total_lines=content.count("\n") + 1,
        added=added,
        removed=removed,
        language=language_for(path),
    )


def _write_temp(target: Path, content: str) -> Path:
    """Write `content` beside `target` and rename it over the top, or raise.

    The scratch file is named after the target and hidden (a leading dot),
    because it lives inside the project for the moment it exists -- a failed
    save must not leave a stray `.app.ts.xxxx.tonyagent-tmp` in the user's
    tree, and the `except` below is what makes sure it does not.
    """
    handle = tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        newline="",
        dir=str(target.parent),
        prefix=f".{target.name}.",
        suffix=".tonyagent-tmp",
        delete=False,
    )
    temp_path = Path(handle.name)
    try:
        with handle:
            handle.write(content)
        try:
            # The rename replaces the file, so its mode comes from the temp
            # file unless it is copied across first.
            os.chmod(temp_path, target.stat().st_mode)
        except OSError:
            pass
        os.replace(temp_path, target)
    except Exception:
        try:
            temp_path.unlink()
        except OSError:
            pass
        raise
    return temp_path


def format_edit_report(edits: list[dict]) -> str:
    """The block that tells the model what the user changed by hand.

    **Why the agent has to be told at all.** Its context is whatever the
    files said when it last read them. A user editing in the viewer between
    two messages invalidates that silently, and the next answer is then
    about a file that no longer exists in the form the agent remembers --
    which fails as confident nonsense about code the user has already
    fixed. So the edits ride with the next message, the one moment the agent
    is guaranteed to look.

    The block is prose rather than JSON because it lands in a conversation:
    it is read by a model that reasons in sentences, and a schema would
    spend tokens saying the same thing. The line numbers are the ones in the
    file *after* the edit, which is the state the agent will find if it
    looks -- reporting the old numbering would send it to the wrong line.

    Bounded on both axes, and the bound is admitted in the text rather than
    silently truncating: a report that claims to be complete when it is not
    is worse than one that says where it stopped.
    """
    if not edits:
        return ""

    lines: list[str] = []
    shown = [edit for edit in edits if isinstance(edit, dict) and edit.get("path")]
    if not shown:
        return ""
    lines.append(
        "[The user edited these files in the code viewer since your last "
        "message. Read a file again before changing it: what you remember "
        "may be stale.]"
    )
    for edit in shown[:MAX_REPORTED_FILES]:
        path = str(edit["path"])
        added = _int_or_zero(edit.get("added"))
        removed = _int_or_zero(edit.get("removed"))
        detail: list[str] = []
        if added or removed:
            detail.append(f"+{added} \u2212{removed}")
        ranges = edit.get("lines") or []
        if isinstance(ranges, list) and ranges:
            rendered = []
            for entry in ranges[:MAX_REPORTED_RANGES]:
                if isinstance(entry, dict):
                    start = _int_or_zero(entry.get("start"))
                    end = _int_or_zero(entry.get("end")) or start
                    rendered.append(f"{start}" if end <= start else f"{start}-{end}")
                elif isinstance(entry, (int, float)) and not isinstance(entry, bool):
                    rendered.append(str(int(entry)))
            if rendered:
                detail.append("lines " + ", ".join(rendered))
                if len(ranges) > MAX_REPORTED_RANGES:
                    detail.append(f"+{len(ranges) - MAX_REPORTED_RANGES} more")
        lines.append(f"- {path}: " + ("; ".join(detail) if detail else "changed"))
    if len(shown) > MAX_REPORTED_FILES:
        lines.append(f"  ...and {len(shown) - MAX_REPORTED_FILES} more files")
    return "\n".join(lines)


def _int_or_zero(value: object) -> int:
    """An integer, or 0 for anything that is not one.

    Deliberately forgiving: this report is built from a JSON list that
    *anything able to write to the pipe* can send, and a malformed entry
    must cost a missing line number rather than the whole message.
    """
    if isinstance(value, bool):
        return 0
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return 0
    return 0
