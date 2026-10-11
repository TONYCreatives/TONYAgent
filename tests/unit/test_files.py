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
from pathlib import Path

import pytest

from tonyagent.files import (
    MAX_SOURCE_BYTES,
    SourceError,
    language_for,
    project_tree,
    read_source,
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

    (project / "blob.bin").write_bytes(b"\x00\x01")
    with pytest.raises(RpcError, match="binary"):
        asyncio.run(_server()._handlers["files.read"]({"path": "blob.bin"}))
    with pytest.raises(RpcError, match="File not found"):
        asyncio.run(_server()._handlers["files.read"]({"path": "nope.txt"}))
    with pytest.raises(RpcError, match="missing path"):
        asyncio.run(_server()._handlers["files.read"]({"path": ""}))


def test_the_two_file_methods_are_registered():
    assert {"files.tree", "files.read"} <= set(_server()._handlers)
