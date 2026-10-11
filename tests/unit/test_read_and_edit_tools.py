"""What ``read`` and ``edit`` do that their predecessors did not.

Both tools were renamed from ``read_file`` / ``edit_file`` and both changed
behaviour in the same pass, so the old tests do not describe them any more:

* ``read`` takes ``offset``/``limit`` and numbers its lines. The window exists
  because a whole large file is the most expensive call a tool can make, and the
  numbering exists because an ``edit`` has to name exact text and the model
  should not have to count lines to do it.
* ``edit`` refuses an ambiguous match instead of silently replacing the first
  one. That refusal is the whole point of the tool: "replace the first of three"
  is a guess about which one was meant, and a wrong guess is a corruption the
  model then reasons about as if it were deliberate.

The assertions about *what was left on disk after a refusal* are the ones that
matter most. A tool that reports an error and edits anyway is worse than one that
guesses, because the error teaches the model to trust a refusal that is not one.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import tonyagent.tools  # noqa: F401  -- importing registers every tool
from tonyagent.folder import folder_manager
from tonyagent.tools import tool_registry
from tonyagent.tools.base import ToolResultStatus


@pytest.fixture
def project(tmp_path: Path, monkeypatch):
    """A project folder, without going through set_folder (which writes config)."""
    monkeypatch.setattr(folder_manager, "_current_folder", tmp_path)
    return tmp_path


def tool(name: str):
    found = tool_registry.get(name)
    assert found is not None, f"{name} is not registered"
    return found


# --- read: the line window --------------------------------------------------


async def test_a_whole_file_comes_back_numbered(project):
    (project / "f.py").write_text("alpha\nbeta\ngamma\n", encoding="utf-8")

    result = await tool("read").execute(path="f.py")

    assert result.status is ToolResultStatus.SUCCESS
    assert "1\talpha" in result.output
    assert "3\tgamma" in result.output
    assert "lines 1-3 of 3" in result.output, (
        "the reader cannot tell 'the whole file' from 'there is more'"
    )


async def test_offset_starts_where_it_says(project):
    """1-based, and line 2 is the second line -- not the third and not the first."""
    (project / "f.py").write_text("alpha\nbeta\ngamma\n", encoding="utf-8")

    result = await tool("read").execute(path="f.py", offset=2)

    assert "2\tbeta" in result.output
    assert "3\tgamma" in result.output
    assert "1\talpha" not in result.output
    assert "lines 2-3 of 3" in result.output


async def test_limit_stops_where_it_says(project):
    (project / "f.py").write_text("alpha\nbeta\ngamma\n", encoding="utf-8")

    result = await tool("read").execute(path="f.py", limit=1)

    assert "1\talpha" in result.output
    assert "beta" not in result.output
    assert "lines 1-1 of 3" in result.output


async def test_offset_and_limit_together_window_the_middle(project):
    (project / "f.py").write_text("a\nb\nc\nd\ne\n", encoding="utf-8")

    result = await tool("read").execute(path="f.py", offset=2, limit=2)

    assert "2\tb" in result.output
    assert "3\tc" in result.output
    assert "4\td" not in result.output
    assert "lines 2-3 of 5" in result.output


async def test_offset_past_the_end_says_how_long_the_file_is(project):
    """A negative result has to be actionable: the model needs the real length."""
    (project / "f.py").write_text("alpha\nbeta\n", encoding="utf-8")

    result = await tool("read").execute(path="f.py", offset=99)

    assert result.status is ToolResultStatus.ERROR
    assert "99" in result.error
    assert "2 line" in result.error


async def test_reading_a_missing_file_is_refused(project):
    result = await tool("read").execute(path="nope.py")
    assert result.status is ToolResultStatus.ERROR
    assert "File not found" in result.error


async def test_reading_outside_the_project_is_refused(project):
    result = await tool("read").execute(path="../escape.py")
    assert result.status is ToolResultStatus.ERROR
    assert "escape" in result.error


async def test_reading_reports_no_change(project):
    """A read is not a change, so it must not put a badge on the file tree."""
    (project / "f.py").write_text("alpha\n", encoding="utf-8")

    result = await tool("read").execute(path="f.py")

    assert result.artifacts == []


# --- edit: the match has to be unambiguous ----------------------------------


async def test_an_unambiguous_match_is_replaced(project):
    (project / "f.py").write_text("one\ntwo\nthree\n", encoding="utf-8")

    result = await tool("edit").execute(
        path="f.py", old_string="two", new_string="TWO"
    )

    assert result.status is ToolResultStatus.SUCCESS
    assert (project / "f.py").read_text(encoding="utf-8") == "one\nTWO\nthree\n"


async def test_an_ambiguous_match_is_refused(project):
    (project / "f.py").write_text("dup\nx\ndup\n", encoding="utf-8")

    result = await tool("edit").execute(
        path="f.py", old_string="dup", new_string="changed"
    )

    assert result.status is ToolResultStatus.ERROR
    assert "2 times" in result.error


async def test_the_refusal_names_both_ways_out(project):
    """The model has to be able to fix this without guessing at the fix."""
    (project / "f.py").write_text("dup\nx\ndup\n", encoding="utf-8")

    result = await tool("edit").execute(
        path="f.py", old_string="dup", new_string="changed"
    )

    assert "surrounding" in result.error, "no hint to add context"
    assert "replace_all" in result.error, "no hint that all of them is an option"


async def test_an_ambiguous_match_changes_nothing_on_disk(project):
    """The part that matters: a refusal has to actually refuse.

    Reporting an error *and* editing would teach the model that the error is
    advisory, which is worse than never having raised it.
    """
    (project / "f.py").write_text("dup\nx\ndup\n", encoding="utf-8")

    result = await tool("edit").execute(
        path="f.py", old_string="dup", new_string="changed"
    )

    assert result.status is ToolResultStatus.ERROR
    assert (project / "f.py").read_text(encoding="utf-8") == "dup\nx\ndup\n"


async def test_replace_all_replaces_every_occurrence(project):
    (project / "f.py").write_text("dup\nx\ndup\n", encoding="utf-8")

    result = await tool("edit").execute(
        path="f.py", old_string="dup", new_string="changed", replace_all=True
    )

    assert result.status is ToolResultStatus.SUCCESS
    assert (project / "f.py").read_text(encoding="utf-8") == "changed\nx\nchanged\n"
    assert "2" in result.output, "the count of what was replaced is not reported"


async def test_replace_all_defaults_to_off(project):
    """Off by default is what makes the ambiguity check meaningful."""
    declared = tool("edit").parameters["properties"]["replace_all"]
    assert declared["default"] is False
    assert declared["type"] == "boolean"


async def test_an_empty_old_string_is_refused(project):
    """An empty match is everywhere, so replace_all on it rewrites the file.

    That would read as a successful edit and be a destructive no-op, which is
    why it is refused by name rather than left to arithmetic.
    """
    (project / "f.py").write_text("keep me\n", encoding="utf-8")

    result = await tool("edit").execute(
        path="f.py", old_string="", new_string="X", replace_all=True
    )

    assert result.status is ToolResultStatus.ERROR
    assert "empty" in result.error
    assert (project / "f.py").read_text(encoding="utf-8") == "keep me\n"


async def test_a_missing_old_string_is_refused(project):
    (project / "f.py").write_text("alpha\n", encoding="utf-8")

    result = await tool("edit").execute(
        path="f.py", old_string="nowhere", new_string="x"
    )

    assert result.status is ToolResultStatus.ERROR
    assert "not found" in result.error
    assert (project / "f.py").read_text(encoding="utf-8") == "alpha\n"


async def test_editing_a_missing_file_is_refused(project):
    result = await tool("edit").execute(
        path="nope.py", old_string="a", new_string="b"
    )
    assert result.status is ToolResultStatus.ERROR
    assert "File not found" in result.error


async def test_editing_outside_the_project_is_refused(project):
    result = await tool("edit").execute(
        path="../escape.py", old_string="a", new_string="b"
    )
    assert result.status is ToolResultStatus.ERROR
    assert "escape" in result.error


async def test_a_successful_edit_reports_the_line_diff(project):
    """The Files tree badge is about the file, so the artifact must carry counts."""
    (project / "f.py").write_text("a\nb\nc\n", encoding="utf-8")

    result = await tool("edit").execute(
        path="f.py", old_string="b", new_string="b1\nb2"
    )

    change = next(a for a in result.artifacts if a["type"] == "file_change")["data"]
    assert change["path"] == "f.py"
    assert change["added"] == 2
    assert change["removed"] == 1


async def test_the_old_parameter_names_are_not_silently_accepted(project):
    """A model working from an older prompt must be told the names changed.

    Two different refusals, and the order between them is deliberate. With only
    the old names present, the *missing-required* check fires first -- and that
    is the better message of the two, because it names ``old_string``, which is
    exactly what the caller has to send instead. The unknown-parameter message
    only appears once the required names are satisfied, where it is describing a
    genuine extra rather than a rename.
    """
    (project / "f.py").write_text("alpha\n", encoding="utf-8")

    ok, error = tool("edit").validate_args(
        {"path": "f.py", "old_text": "alpha", "new_text": "beta"}
    )
    assert not ok
    assert "old_string" in error, f"the correct name was not offered: {error}"

    ok, error = tool("edit").validate_args(
        {
            "path": "f.py",
            "old_string": "alpha",
            "new_string": "beta",
            "old_text": "alpha",
        }
    )
    assert not ok
    assert "old_text" in error, f"the stale extra was not named: {error}"
