"""The app's log file, which used to be configured by nobody.

`utils/logging.setup_logging` was defined, exported in `__all__`, and called by
nothing at all. The gap was not obvious, because the *host* has its own
`window.log` for startup failures -- but the host is not the process that logs a
keyring warning, a provider error or a turn that died. That is the core, and the
core's stderr goes to the app's log strip: a strip in a window, which is not
something to read after the fact.

So a failure with no symptom in the window left nothing on disk, and diagnosing
the keyring bug this release fixes took a temporary probe and two rebuilds for
want of a file to read.
"""

from __future__ import annotations

from loguru import logger

from tonyagent.utils import logging as applog


def test_it_writes_a_file(monkeypatch, tmp_path):
    """The one thing the module is for, and the one thing it never did."""
    # On the class, not the instance: `Settings` is a pydantic model and
    # refuses an attribute it does not declare.
    monkeypatch.setattr(type(applog.settings), "get_logs_dir", lambda self: tmp_path)
    try:
        applog.setup_logging(colorize=False)
        logger.warning("a line that has to reach the file")
    finally:
        # Global state: a sink left behind would follow every later test, and
        # the next call to `setup_logging` would be adding to it rather than
        # starting from the default.
        logger.remove()

    written = list(tmp_path.glob("tonyagent_*.log"))
    assert written, "setup_logging added no file sink"
    assert "a line that has to reach the file" in written[0].read_text(encoding="utf-8")


def test_the_console_handler_can_be_left_uncoloured(capsys, monkeypatch, tmp_path):
    """The core's stderr is a pipe the app reads, not a terminal.

    Colour there arrives in the log strip as literal escapes, which is why the
    core used to spell its own handler out with `colorize=False` rather than
    calling this. It calls this now, so the switch has to exist -- and it has to
    still keep the stderr half, because the strip is where a user watches a turn.
    """
    # On the class, not the instance: `Settings` is a pydantic model and
    # refuses an attribute it does not declare.
    monkeypatch.setattr(type(applog.settings), "get_logs_dir", lambda self: tmp_path)
    try:
        applog.setup_logging(colorize=False)
        logger.warning("plain")
    finally:
        logger.remove()

    err = capsys.readouterr().err
    assert "plain" in err, "the core lost its stderr handler"
    assert "\x1b[" not in err, "the core's pipe got ANSI escapes"
