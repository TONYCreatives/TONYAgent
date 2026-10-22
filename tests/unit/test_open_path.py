"""Open externally: one project file in the OS default app.

The viewer can draw text, images, and (next) PDFs and media. Everything
else -- a zip, an Office doc, an executable -- is a file the window can
name but not draw, and naming it without offering anything is a dead end.
So the host opens it where it does draw: the OS default app.

Two properties are pinned here:

* **The path is confined, not trusted.** It is project-relative and
  resolved through the same `confine` the viewer reads through, so the
  page cannot point this at anything outside the project.
* **A refusal is reported, not raised.** A missing file or a path outside
  the project answers `opened: False`, because a viewer button is not the
  place that could do anything with an exception.
"""

from __future__ import annotations

import subprocess
import sys

import pytest

from tonyagent.folder import folder_manager
from tonyagent.window.bridge import Bridge


@pytest.fixture
def project(tmp_path, monkeypatch):
    root = tmp_path / "proj"
    root.mkdir()
    (root / "doc.pdf").write_bytes(b"%PDF-1.4 fake\n")
    monkeypatch.setattr(folder_manager, "_current_folder", root)
    return root


def _stub_launcher(monkeypatch):
    """Capture what the host would open, on any platform."""
    launched: list[str] = []
    if sys.platform == "win32":
        import os

        monkeypatch.setattr(os, "startfile", lambda target: launched.append(target))
    else:
        monkeypatch.setattr(
            subprocess,
            "run",
            lambda args, **kwargs: launched.append(args[-1]),
        )
    return launched


def test_open_path_opens_a_project_file(project, monkeypatch):
    launched = _stub_launcher(monkeypatch)

    reply = Bridge().open_path("doc.pdf")

    assert reply == {"path": "doc.pdf", "opened": True}
    assert launched == [str(project / "doc.pdf")]


def test_open_path_refuses_a_path_outside_the_project(project, monkeypatch):
    launched = _stub_launcher(monkeypatch)

    reply = Bridge().open_path("../outside.txt")

    assert reply["opened"] is False
    assert launched == []


def test_open_path_reports_a_missing_file(project, monkeypatch):
    launched = _stub_launcher(monkeypatch)

    reply = Bridge().open_path("gone.pdf")

    assert reply == {"path": "gone.pdf", "opened": False}
    assert launched == []
