"""The code viewer's reads: the tree, one file, and the gates between them.

The two properties that matter are the ones the viewer inherits rather
than chooses: the same project boundary every file tool works inside, and
the same skip rules the agent's grep uses -- so the tree the user sees and
the tree the model searches are one tree. A test for either is a test that
they cannot drift.
"""

from __future__ import annotations

import asyncio
import io
import os
from pathlib import Path

import pytest

from tonyagent.files import (
    MAX_REPORTED_FILES,
    MAX_SOURCE_BYTES,
    SourceError,
    format_edit_report,
    language_for,
    project_tree,
    read_for_viewer,
    read_source,
    write_source,
)
from tonyagent.folder import folder_manager


@pytest.fixture
def project(tmp_path, monkeypatch):
    """A small project, and the boundary pointed at it."""
    root = tmp_path / "proj"
    (root / "src").mkdir(parents=True)
    (root / "src" / "app.ts").write_text("const a = 1;\n", encoding="utf-8")
    (root / "README.md").write_text("# hi\n", encoding="utf-8")
    monkeypatch.setattr(folder_manager, "_current_folder", root)
    return root


# --- language ----------------------------------------------------------------


@pytest.mark.parametrize(
    "path, expected",
    [
        ("src/app.ts", "typescript"),
        ("src/app.tsx", "tsx"),
        ("src/app.js", "javascript"),
        ("src/app.jsx", "jsx"),
        ("main.py", "python"),
        ("data.json", "json"),
        ("style.css", "css"),
        ("index.html", "html"),
        ("README.md", "markdown"),
        ("run.sh", "shell"),
        ("ci.yml", "yaml"),
        ("Cargo.toml", "toml"),
        ("main.rs", "rust"),
        ("main.go", "go"),
        ("query.sql", "sql"),
        ("notes.txt", "plain"),
        ("weird.qqq", "plain"),
        ("Dockerfile", "shell"),
        ("Makefile", "shell"),
        (".gitignore", "ini"),
        (".env", "shell"),
        (".env.production", "shell"),
    ],
)
def test_a_file_gets_the_language_the_viewer_highlights(path, expected):
    assert language_for(path) == expected


def test_a_filename_beats_its_extension():
    """``Dockerfile`` has no suffix; ``dockerfile.txt`` is not one."""
    assert language_for("dockerfile") == "shell"
    assert language_for("Dockerfile") == "shell"
    assert language_for("something.dockerfile") == "plain"


# --- the tree ----------------------------------------------------------------


def test_the_tree_lists_files_and_directories(project):
    tree = project_tree()
    paths = {e.path: e.kind for e in tree.entries}
    assert paths == {"src": "dir", "README.md": "file", "src/app.ts": "file"}
    assert not tree.truncated


def test_the_tree_skips_what_the_agent_skips(project):
    (project / "node_modules").mkdir()
    (project / "node_modules" / "left-pad").mkdir()
    (project / "node_modules" / "left-pad" / "index.js").write_text("x")
    (project / ".git").mkdir()
    (project / ".git" / "config").write_text("x")
    (project / "__pycache__").mkdir()
    (project / "__pycache__" / "m.pyc").write_text("x")

    tree = project_tree()
    assert {e.path for e in tree.entries} == {"src", "README.md", "src/app.ts"}, (
        "the tree must apply the same skip rules grep does, or the two walks "
        "disagree about what is in the project"
    )


def test_the_tree_is_confined_to_the_project(project):
    (project.parent / "outside.txt").write_text("secret", encoding="utf-8")
    with pytest.raises(ValueError, match="escape"):
        project_tree("..")
    with pytest.raises(ValueError, match="escape"):
        project_tree(str(project.parent))


def test_the_tree_reports_its_own_bounds(project):
    for index in range(5):
        (project / f"f{index}.txt").write_text("x", encoding="utf-8")
    tree = project_tree(max_entries=2)
    assert tree.truncated
    assert len(tree.entries) == 2


def test_the_tree_stops_at_its_depth(project):
    deep = project / "a" / "b" / "c" / "d" / "e" / "f" / "g"
    deep.mkdir(parents=True)
    (deep / "buried.txt").write_text("x", encoding="utf-8")

    shallow = project_tree(max_depth=2)
    assert "a/b/c/d/e/f/g/buried.txt" not in {e.path for e in shallow.entries}

    deep_enough = project_tree(max_depth=9)
    assert "a/b/c/d/e/f/g/buried.txt" in {e.path for e in deep_enough.entries}


# --- reading one file ---------------------------------------------------------


def test_read_source_returns_text_lines_and_language(project):
    source = read_source("src/app.ts")
    assert source.path == "src/app.ts"
    # Compared with the newline normalised: the file's own bytes are what the
    # viewer shows, and this machine may have written CRLF.
    assert source.content.replace("\r\n", "\n") == "const a = 1;\n"
    assert source.total_lines == 2
    assert source.language == "typescript"


def test_read_source_refuses_an_escape(project):
    with pytest.raises(SourceError, match="escape"):
        read_source("../outside.txt")


def test_read_source_refuses_a_directory(project):
    with pytest.raises(SourceError, match="Not a file"):
        read_source("src")


def test_read_source_refuses_a_missing_file(project):
    with pytest.raises(SourceError, match="File not found"):
        read_source("nope.txt")


def test_read_source_refuses_a_binary_file(project):
    (project / "blob.bin").write_bytes(b"\x00\x01\x02")
    with pytest.raises(SourceError, match="binary"):
        read_source("blob.bin")


def test_read_source_refuses_non_utf8(project):
    (project / "latin.txt").write_bytes(b"caf\xe9\n")
    with pytest.raises(SourceError, match="not valid UTF-8"):
        read_source("latin.txt")


def test_read_source_refuses_a_file_over_the_cap(project):
    big = project / "big.txt"
    big.write_bytes(b"x" * (MAX_SOURCE_BYTES + 16))
    with pytest.raises(SourceError, match="over the"):
        read_source("big.txt")


def test_read_source_refuses_a_symlink_that_leaves(project):
    outside = project.parent / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    link = project / "sneaky.txt"
    try:
        link.symlink_to(outside)
    except OSError:  # pragma: no cover - Windows without developer mode
        pytest.skip("symlinks are not available here")
    with pytest.raises(SourceError, match="escape"):
        read_source("sneaky.txt")


# --- the RPC surface ----------------------------------------------------------


def _server():
    from tonyagent.headless.server import StdioServer
    from tonyagent.core.session import AgentSession

    return StdioServer(AgentSession(), io.StringIO(""), io.StringIO())


def test_files_tree_reaches_the_window(project):
    reply = asyncio.run(_server()._handlers["files.tree"]({"path": "."}))
    assert {e["path"] for e in reply["entries"]} == {"src", "README.md", "src/app.ts"}
    assert reply["truncated"] is False


def test_files_read_reaches_the_window(project):
    reply = asyncio.run(_server()._handlers["files.read"]({"path": "src/app.ts"}))
    assert reply["content"].strip() == "const a = 1;"
    assert reply["language"] == "typescript"


def test_files_read_refuses_with_a_sentence_not_a_stack(project):
    from tonyagent.headless.server import RpcError

    # A binary file is a *view* now (`kind: "binary"`), so the failures left
    # are the ones where there is nothing to look at at all.
    with pytest.raises(RpcError, match="File not found"):
        asyncio.run(_server()._handlers["files.read"]({"path": "nope.txt"}))
    with pytest.raises(RpcError, match="Not a file"):
        asyncio.run(_server()._handlers["files.read"]({"path": "src"}))
    with pytest.raises(RpcError, match="missing path"):
        asyncio.run(_server()._handlers["files.read"]({"path": ""}))


def test_the_two_file_methods_are_registered():
    assert {"files.tree", "files.read"} <= set(_server()._handlers)


def test_files_write_is_registered():
    assert "files.write" in _server()._handlers


# --- what the viewer is shown: text, image, or "no preview" -------------------


def test_a_text_file_reads_as_text_with_a_kind(project):
    reply = read_for_viewer("src/app.ts").to_dict()
    assert reply["kind"] == "text"
    assert reply["language"] == "typescript"
    assert "const a = 1;" in reply["content"]


def test_an_image_reads_as_an_image_the_window_can_draw(project):
    from PIL import Image

    picture = project / "shot.png"
    Image.new("RGB", (40, 20), (10, 20, 30)).save(picture)

    reply = read_for_viewer("shot.png").to_dict()

    assert reply["kind"] == "image"
    assert reply["mime"] == "image/png"
    assert (reply["width"], reply["height"]) == (40, 20)
    assert (reply["display_width"], reply["display_height"]) == (40, 20)
    assert reply["downscaled"] is False
    # A data URL's worth of bytes, decoded back to an image by the window.
    import base64

    assert base64.b64decode(reply["data"])[:8] == b"\x89PNG\r\n\x1a\n"


def test_a_big_image_is_downscaled_for_the_window(project):
    from PIL import Image

    from tonyagent.files import VIEWER_MAX_EDGE

    Image.new("RGB", (VIEWER_MAX_EDGE * 2, 100), (0, 0, 0)).save(project / "wide.png")

    reply = read_for_viewer("wide.png").to_dict()

    assert reply["downscaled"] is True
    assert reply["width"] == VIEWER_MAX_EDGE * 2, "the source size is still reported"
    assert reply["display_width"] == VIEWER_MAX_EDGE


def test_a_mislabelled_image_is_an_error_not_a_broken_picture(project):
    (project / "fake.png").write_bytes(b"not a png at all")
    with pytest.raises(SourceError, match="not an image"):
        read_for_viewer("fake.png")


def test_a_binary_file_is_a_view_rather_than_a_failure(project):
    (project / "blob.zip").write_bytes(b"PK\x03\x04\x00\x00")
    reply = read_for_viewer("blob.zip").to_dict()

    assert reply["kind"] == "binary"
    assert reply["size"] == 6
    assert "binary" in reply["reason"]


def test_a_file_over_the_cap_is_named_with_its_size(project):
    (project / "huge.txt").write_bytes(b"x" * (MAX_SOURCE_BYTES + 32))
    reply = read_for_viewer("huge.txt").to_dict()
    assert reply["kind"] == "binary"
    assert "over the" in reply["reason"]


def test_a_missing_file_is_still_a_failure(project):
    with pytest.raises(SourceError, match="File not found"):
        read_for_viewer("gone.txt")
    with pytest.raises(SourceError, match="Not a file"):
        read_for_viewer("src")


def test_csv_is_its_own_language_so_the_window_can_offer_a_grid(project):
    assert language_for("data.csv") == "csv"
    assert language_for("data.tsv") == "csv"


# --- saving ------------------------------------------------------------------


def test_a_save_writes_the_file_and_reports_the_delta(project):
    saved = write_source("src/app.ts", "const a = 2;\nconst b = 3;\n")

    assert saved.path == "src/app.ts"
    assert saved.added == 2
    assert saved.removed == 1
    assert saved.total_lines == 3
    assert (project / "src" / "app.ts").read_text(encoding="utf-8") == "const a = 2;\nconst b = 3;\n"


def test_a_save_leaves_no_scratch_file_behind(project):
    write_source("src/app.ts", "const a = 9;\n")
    leftovers = [p.name for p in project.rglob("*tonyagent-tmp*")]
    assert leftovers == [], f"a failed or finished save left scratch files: {leftovers}"


@pytest.mark.skipif(os.name != "posix", reason="Windows has no executable bit to preserve")
def test_a_save_keeps_the_files_mode(project):
    """A script that is saved must still be runnable.

    The temp file a save is written through is created with the process's
    default mode, so without copying the original's across, editing a
    `#!/bin/sh` file would silently strip its executable bit.
    """
    import os
    import stat as stat_module

    script = project / "run.sh"
    script.write_text("#!/bin/sh\necho hi\n", encoding="utf-8")
    os.chmod(script, 0o755)

    write_source("run.sh", "#!/bin/sh\necho hello\n")

    mode = stat_module.S_IMODE(script.stat().st_mode)
    assert mode == 0o755, f"the executable bit was lost: {oct(mode)}"


def test_a_save_refuses_an_escape_and_a_missing_file(project):
    with pytest.raises(SourceError, match="escape"):
        write_source("../outside.txt", "nope")
    with pytest.raises(SourceError, match="File not found"):
        write_source("brand-new.txt", "nope")
    with pytest.raises(SourceError, match="Not a file"):
        write_source("src", "nope")


def test_a_save_refuses_content_over_the_cap(project):
    with pytest.raises(SourceError, match="over the"):
        write_source("src/app.ts", "x" * (MAX_SOURCE_BYTES + 1))


def test_a_save_reaches_the_window_through_the_handler(project):
    reply = asyncio.run(
        _server()._handlers["files.write"]({"path": "src/app.ts", "content": "let z = 1;\n"})
    )
    assert reply["path"] == "src/app.ts"
    assert reply["added"] == 1
    assert reply["removed"] == 1


# --- telling the agent what the user changed ----------------------------------


def test_an_empty_report_is_nothing_at_all():
    assert format_edit_report([]) == ""
    assert format_edit_report([{"nope": 1}]) == ""


def test_the_report_names_files_and_lines():
    report = format_edit_report(
        [
            {"path": "app/src/App.tsx", "added": 6, "removed": 3, "lines": [{"start": 42, "end": 51}]},
            {"path": "README.md", "added": 1, "removed": 0, "lines": [{"start": 7, "end": 7}]},
        ]
    )
    assert "app/src/App.tsx" in report
    assert "lines 42-51" in report
    assert "+6 \u22123" in report
    assert "README.md" in report
    assert "lines 7" in report
    # The instruction that makes the report useful rather than decorative.
    assert "Read a file again" in report


def test_the_report_is_bounded_and_says_so():
    edits = [
        {"path": f"file{index}.ts", "added": 1, "removed": 1, "lines": [{"start": index}]}
        for index in range(MAX_REPORTED_FILES + 3)
    ]
    report = format_edit_report(edits)

    assert report.count(".ts:") == MAX_REPORTED_FILES, "only the cap should be listed"
    assert "and 3 more files" in report


def test_the_report_caps_line_ranges_per_file():
    from tonyagent.files import MAX_REPORTED_RANGES

    ranges = [{"start": index, "end": index} for index in range(MAX_REPORTED_RANGES + 5)]
    report = format_edit_report([{"path": "big.ts", "added": 5, "removed": 0, "lines": ranges}])

    assert "+5 more" in report


def test_the_report_survives_junk_entries():
    """Anything that can write to the pipe can send this, so nothing raises."""
    report = format_edit_report(
        [
            {"path": "ok.ts", "added": "not a number", "removed": None, "lines": "not a list"},
            {"path": "weird.ts", "lines": [{"start": None, "end": 3}, "nonsense", 12]},
            {"path": ""},
            "not a dict",
        ]
    )
    assert "ok.ts" in report
    assert "weird.ts" in report


def test_send_carries_the_report_with_the_message(project, monkeypatch):
    """The wiring, not just the formatter: `send` has to hand it over."""
    from tonyagent.headless.server import StdioServer
    from tonyagent.core.session import AgentSession

    server = StdioServer(AgentSession(), io.StringIO(""), io.StringIO())
    captured: dict = {}

    def fake_send(text, attachments=None):
        captured["text"] = text
        captured["attachments"] = attachments
        return "turn-1"

    monkeypatch.setattr(server.session, "send", fake_send)
    server._handlers["send"](
        {
            "text": "why is this failing?",
            "user_edits": [{"path": "a.py", "added": 2, "removed": 1, "lines": [{"start": 4}]}],
        }
    )

    assert captured["text"].startswith("why is this failing?")
    assert "a.py" in captured["text"]
    assert "lines 4" in captured["text"]


def test_send_without_edits_is_untouched(project, monkeypatch):
    from tonyagent.headless.server import StdioServer
    from tonyagent.core.session import AgentSession

    server = StdioServer(AgentSession(), io.StringIO(""), io.StringIO())
    captured: dict = {}

    def fake_send(text, attachments=None):
        captured["text"] = text
        return "t"

    monkeypatch.setattr(server.session, "send", fake_send)
    server._handlers["send"]({"text": "plain message"})

    assert captured["text"] == "plain message"
