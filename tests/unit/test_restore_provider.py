"""Restoring the saved provider when the sidecar starts.

The write side is covered in ``test_provider_persistence``; this covers the read
side, which is what makes that write mean anything. Without it every launch came
back on ``AgentSession``'s default provider *name* with no provider object
behind it, so ``state`` looked configured while the first message failed with
"no provider configured".

The dominant requirement here is that startup never raises. A sidecar that
refuses to start is a dead app; a sidecar that starts unbound is a working app
telling the truth about what it still needs. So each broken-config case asserts
the session is *usable and unbound*, not that an error surfaced.
"""

from __future__ import annotations

import pytest
import tomli
import tomli_w

from tonyagent.config import migration
from tonyagent.headless.server import build_session

# Spelled out so the literal newline never has to survive an escape layer.
NEWLINE = chr(10)


@pytest.fixture
def isolated_config(tmp_path, monkeypatch):
    """Redirect the config path itself, so the real one is never touched.

    Patched where the path is computed rather than by setting APPDATA: the
    provider factory reads the real user profile for the keyring in the same
    call, so a fixture that only moved the environment would still let a write
    land in the user's real config.toml.
    """
    path = tmp_path / "TONYAgent" / "config.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(migration, "get_config_path", lambda: path)
    return path


def _write(path, data: dict) -> None:
    with open(path, "wb") as handle:
        tomli_w.dump(data, handle)


def _saved(name="openrouter", model="stealth/space-bunny-alpha", base_url=""):
    return {
        "meta": {"version": migration.CURRENT_CONFIG_VERSION},
        "provider": {"name": name, "model": model, "base_url": base_url},
    }


def test_a_saved_provider_is_bound_at_startup(isolated_config):
    """The whole point: the first message after launch works."""
    _write(isolated_config, _saved())
    session = build_session()
    assert session.provider is not None
    assert session.provider_name == "openrouter"


def test_the_typed_model_id_is_restored_not_the_default(isolated_config):
    """A provider default would silently undo the user's choice.

    ``openrouter/auto`` is what ``OpenRouterProvider`` falls back to. Restoring
    the default instead of the saved id looks like a working app while routing
    every request to a different model than the one that was chosen.
    """
    _write(isolated_config, _saved(model="stealth/space-bunny-alpha"))
    session = build_session()
    assert session.model == "stealth/space-bunny-alpha"
    assert getattr(session.provider, "model", "") == "stealth/space-bunny-alpha"


def test_a_saved_base_url_is_restored(isolated_config):
    _write(isolated_config, _saved(base_url="https://gateway.internal/v1"))
    session = build_session()
    assert session.base_url == "https://gateway.internal/v1"


def test_an_empty_saved_base_url_stays_empty(isolated_config):
    """Empty means "the provider's own default", not "whatever settings says".

    ``settings.provider.base_url`` is an unrelated store -- ``Settings`` has no
    ``toml_file``, so config.toml never reaches it -- and it can carry a value
    from the environment. Substituting it here would send every request to an
    endpoint the user never picked.
    """
    _write(isolated_config, _saved(base_url=""))
    session = build_session()
    assert session.base_url == ""


def test_no_saved_provider_leaves_the_session_unbound(isolated_config):
    """First run ever: no file at all."""
    assert not isolated_config.exists()
    session = build_session()
    assert session.provider is None


def test_a_config_with_no_provider_section_leaves_the_session_unbound(isolated_config):
    """The file exists -- the user has other settings -- but never chose one."""
    _write(isolated_config, {"meta": {"version": 1}, "ui": {"theme": "dark"}})
    session = build_session()
    assert session.provider is None


def test_an_unknown_provider_name_leaves_the_session_unbound(isolated_config):
    """A provider removed in an upgrade must not stop the app from starting."""
    _write(isolated_config, _saved(name="some-provider-that-was-deleted"))
    session = build_session()
    assert session.provider is None


def test_a_corrupt_config_file_leaves_the_session_unbound(isolated_config):
    """``load_config`` backs up the unreadable file; startup continues."""
    isolated_config.write_text("this is not toml [[[", encoding="utf-8")
    session = build_session()
    assert session.provider is None


def test_a_config_path_that_cannot_be_read_leaves_the_session_unbound(monkeypatch):
    """``load_config`` itself blowing up must not take startup with it.

    This is the case the try/except in ``build_session`` exists for: every other
    failure is a value that ``load_config`` handles, and only an unexpected
    error here proves the guard is load-bearing.
    """
    def boom():
        raise OSError("config directory is not readable")

    monkeypatch.setattr(migration, "get_config_path", boom)
    session = build_session()
    assert session.provider is None


def test_a_missing_config_directory_is_not_an_error(tmp_path, monkeypatch):
    """First run on a clean profile: the directory does not exist yet."""
    path = tmp_path / "not-created-yet" / "TONYAgent" / "config.toml"
    monkeypatch.setattr(migration, "get_config_path", lambda: path)
    session = build_session()
    assert session.provider is None


def test_restoring_does_not_rewrite_the_config(isolated_config):
    """Startup must not migrate a current-version file into a new shape.

    ``load_config`` saves when the version is behind. Restoring runs on *every*
    launch, so a version bump plus a restore would rewrite the user's file
    before they had opened the app once.
    """
    _write(isolated_config, _saved())
    before = isolated_config.read_bytes()
    build_session()
    assert isolated_config.read_bytes() == before


def test_the_restored_session_can_be_driven_over_the_wire(isolated_config):
    """End to end: save through the handler, then start a server on it.

    The two halves were previously verified apart, and the gap between them is
    exactly where this bug lived -- a value written in one shape and read back
    expecting another.
    """
    import asyncio
    import io
    import json

    from tonyagent.core.events import EventBus
    from tonyagent.core.session import AgentSession
    from tonyagent.headless.server import StdioServer

    newline = chr(10)
    bind = {"id": 1, "method": "bind_provider",
            "params": {"name": "openrouter", "model": "stealth/space-bunny-alpha"}}
    asyncio.run(
        StdioServer(AgentSession(bus=EventBus()), io.StringIO(json.dumps(bind) + newline),
                    io.StringIO()).serve()
    )

    session = build_session()
    state_request = {"id": 1, "method": "state", "params": {}}
    stdout = io.StringIO()
    asyncio.run(
        StdioServer(session, io.StringIO(json.dumps(state_request) + newline),
                    stdout).serve()
    )
    frames = [json.loads(line) for line in stdout.getvalue().splitlines() if line.strip()]
    state = next(f for f in frames if f.get("id") == 1)["result"]

    assert state["provider"] == "openrouter"
    assert state["model"] == "stealth/space-bunny-alpha"
    assert state["base_url"] == ""

def test_startup_logs_which_config_file_it_read(isolated_config):
    """The path is the whole diagnosis when a restore silently finds nothing.

    ``get_config_dir`` resolves ``APPDATA``, and on Windows that is not one
    answer for all processes: a Microsoft Store Python is redirected under
    ``AppData/Local/Packages/.../LocalCache/Roaming`` while the packaged
    sidecar is not. That divergence produced a launch reporting "no saved
    provider" with a perfectly good config one directory away, and nothing on
    screen said which file was asked for. The log line is the fix; this keeps it
    from being removed later as noise.
    """
    from loguru import logger

    seen = []

    def capture(message):
        seen.append(str(message))

    logger.add(capture, level="INFO")
    try:
        build_session()
    finally:
        logger.remove()

    joined = NEWLINE.join(seen)
    assert str(isolated_config) in joined, (
        "startup never named the config file it read: " + joined
    )
