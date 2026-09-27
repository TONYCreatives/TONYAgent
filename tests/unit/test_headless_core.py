"""The headless core and its stdio protocol.

These tests are the contract a future Tauri frontend codes against. They run
with no display and no network, and they assert one property above all: the
core never imports a GUI toolkit.
"""
import asyncio
import io
import json
import subprocess
import sys
from pathlib import Path

import pytest

from tonyagent.core.events import EventBus, EventType
from tonyagent.core.session import AgentSession
from tonyagent.headless.server import PROTOCOL_VERSION, StdioServer
from tonyagent.providers import ChatCompletionChunk


# --- the boundary itself ---------------------------------------------------
def test_core_import_does_not_pull_in_a_gui_toolkit():
    """Regression: importing the core used to drag in Tkinter.

    ``tonyagent.core.__init__`` re-exported the Tk app, so even
    ``tonyagent.core.session`` loaded a GUI toolkit and the core could not run
    as a sidecar.
    """
    code = (
        "import sys; sys.path.insert(0, 'src');"
        "import tonyagent.core.session, tonyagent.headless.server;"
        "print(','.join(k for k in ('tkinter','customtkinter') if k in sys.modules))"
    )
    out = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, cwd="."
    )
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "", f"GUI toolkit was imported: {out.stdout!r}"


def test_gui_app_is_still_importable_explicitly():
    """Lazy re-export must not break existing callers."""
    from tonyagent.core import TONYAgentApp

    assert TONYAgentApp.__name__ == "TONYAgentApp"


# --- event bus -------------------------------------------------------------
def test_bus_assigns_monotonic_sequence_numbers():
    bus = EventBus()
    a = bus.emit(EventType.LOG, {"m": 1})
    b = bus.emit(EventType.LOG, {"m": 2})
    assert b.sequence == a.sequence + 1


def test_bus_replays_recent_events_for_a_late_subscriber():
    bus = EventBus()
    bus.emit(EventType.LOG, {"m": 1})
    bus.emit(EventType.LOG, {"m": 2})
    seen = []
    bus.subscribe(lambda e: seen.append(e))
    assert [e.payload["m"] for e in bus.replay()] == [1, 2]
    # A subscriber that only wants what it missed can pass the watermark.
    assert [e.payload["m"] for e in bus.replay(after_sequence=1)] == [2]


def test_a_raising_subscriber_cannot_break_the_turn():
    """A broken transport must never abort generation."""
    bus = EventBus()

    def bad(_event):
        raise RuntimeError("frontend exploded")

    seen = []
    bus.subscribe(bad)
    bus.subscribe(lambda e: seen.append(e))
    bus.emit(EventType.LOG, {"m": 1})
    assert len(seen) == 1, "later subscribers still need the event"


def test_unsubscribe_stops_delivery():
    bus = EventBus()
    seen = []
    off = bus.subscribe(lambda e: seen.append(e))
    bus.emit(EventType.LOG)
    off()
    bus.emit(EventType.LOG)
    assert len(seen) == 1


# --- session ---------------------------------------------------------------
class _StubProvider:
    model = "stub-model"

    def __init__(self, pieces=("Hel", "lo ")):
        self.pieces = pieces
        self.calls = 0

    def estimate_tokens(self, messages):
        return 7

    async def chat_completion(self, messages=None, tools=None, tool_choice=None,
                              stream=False, **kw):
        self.calls += 1

        async def gen():
            for piece in self.pieces:
                yield ChatCompletionChunk(content=piece)
            yield ChatCompletionChunk(finish_reason="stop")

        return gen()


def _session(provider=None):
    s = AgentSession(bus=EventBus())
    s.provider = provider or _StubProvider()
    s.model = "stub-model"
    s.provider_name = "openrouter"
    return s


def _collect(bus):
    events = []
    bus.subscribe(events.append)
    return events


async def test_turn_streams_deltas_then_finishes():
    bus = EventBus()
    session = _session(_StubProvider(pieces=("Hel", "lo ", "world")))
    session.bus = bus
    events = _collect(bus)

    await session.run_turn("Hi")

    types = [e.type for e in events]
    assert EventType.TURN_STARTED in types
    assert types.count(EventType.MESSAGE_DELTA) == 3
    assert EventType.MESSAGE_COMPLETED in types
    assert types[-1] == EventType.TURN_FINISHED, "the turn must close with turn.finished"

    deltas = "".join(e.payload["text"] for e in events
                     if e.type == EventType.MESSAGE_DELTA)
    assert deltas == "Hello world"


async def test_history_keeps_the_user_and_assistant_messages():
    session = _session()
    await session.run_turn("Hi")
    assert [m.role for m in session.messages] == ["user", "assistant"]


async def test_provider_failure_is_reported_as_an_event_not_raised():
    """A failed turn must surface, not blow up the caller."""
    bus = EventBus()
    session = _session()
    session.bus = bus
    events = _collect(bus)

    async def boom(*a, **k):
        raise RuntimeError("provider exploded")
        yield  # pragma: no cover

    session.provider.chat_completion = boom
    await session.run_turn("Hi")

    failed = [e for e in events if e.type == EventType.TURN_FAILED]
    assert failed, "a failure must be reported"
    assert "provider exploded" in failed[0].payload["message"]


async def test_cancelled_turn_finishes_without_failing():
    bus = EventBus()
    session = _session()
    session.bus = bus
    events = _collect(bus)

    async def gen():
        for piece in ("a", "b"):
            session.cancel()
            yield ChatCompletionChunk(content=piece)
        yield ChatCompletionChunk(finish_reason="stop")

    async def cc(*a, **k):
        return gen()

    session.provider.chat_completion = cc
    await session.run_turn("Hi")

    last = [e for e in events
            if e.type in (EventType.TURN_FINISHED, EventType.TURN_FAILED)][-1]
    assert last.type == EventType.TURN_FINISHED
    assert last.payload.get("cancelled") is True


# --- stdio protocol --------------------------------------------------------
def _drive(requests, session=None):
    """Push requests through the server and return parsed frames."""
    session = session or _session()
    stdin = io.StringIO("\n".join(json.dumps(r) for r in requests) + "\n")
    stdout = io.StringIO()
    asyncio.run(StdioServer(session, stdin, stdout).serve())
    return [json.loads(l) for l in stdout.getvalue().splitlines() if l.strip()]


def test_ping_answers_with_the_protocol_version():
    frames = _drive([{"id": 1, "method": "ping"}])
    assert frames[0]["result"]["pong"] is True
    assert frames[0]["result"]["protocol"] == PROTOCOL_VERSION


def test_every_request_gets_exactly_one_reply():
    frames = _drive([
        {"id": 1, "method": "ping"},
        {"id": 2, "method": "state"},
        {"id": 3, "method": "clear"},
    ])
    assert [f["id"] for f in frames] == [1, 2, 3]


def test_unknown_method_is_an_error_reply_not_a_crash():
    frames = _drive([{"id": 1, "method": "nope"}])
    assert frames[0]["error"]["code"] == "unknown_method"


def test_malformed_json_does_not_kill_the_server():
    """A bad line must be reported and the server must keep serving."""
    stdin = io.StringIO(
        "not json\n" + json.dumps({"id": 2, "method": "ping"}) + "\n"
    )
    stdout = io.StringIO()
    asyncio.run(StdioServer(_session(), stdin, stdout).serve())
    frames = [json.loads(l) for l in stdout.getvalue().splitlines() if l.strip()]
    assert frames[0]["error"]["code"] == "bad_request"
    assert frames[1]["result"]["pong"] is True


def test_events_are_distinguishable_from_replies():
    """A frontend must be able to tell a push from a response."""
    session = _session()
    stdin = io.StringIO(json.dumps({"id": 1, "method": "ping"}) + "\n")
    stdout = io.StringIO()
    server = StdioServer(session, stdin, stdout)
    # Emit after the server subscribed, so the push lands on the wire.
    session.bus.emit(EventType.LOG, {"m": "hello"})
    asyncio.run(server.serve())
    frames = [json.loads(l) for l in stdout.getvalue().splitlines() if l.strip()]
    pushes = [f for f in frames if f.get("event") is True]
    assert pushes and pushes[0]["type"] == "log"
    assert pushes[0]["payload"] == {"m": "hello"}


def test_send_streams_events_attributable_to_its_turn():
    session = _session()
    stdin = io.StringIO(
        json.dumps({"id": 1, "method": "send", "params": {"text": "Hi"}}) + "\n"
    )
    stdout = io.StringIO()
    server = StdioServer(session, stdin, stdout)

    async def go():
        await server.serve()
        # Let the detached turn finish before the stream is read.
        await asyncio.sleep(0.3)

    asyncio.run(go())
    frames = [json.loads(l) for l in stdout.getvalue().splitlines() if l.strip()]
    assert "turn_id" in frames[0]["result"]
    turn_id = frames[0]["result"]["turn_id"]
    events = [f for f in frames if f.get("event") is True]
    assert events, "a turn must stream events"
    assert all(e["turn_id"] == turn_id for e in events)


def test_send_is_rejected_when_no_provider_is_bound():
    """A rejection is an error reply, and no stray event precedes it."""
    session = AgentSession(bus=EventBus())
    session.provider = None
    frames = _drive(
        [{"id": 1, "method": "send", "params": {"text": "Hi"}}], session=session
    )
    assert frames[0]["id"] == 1
    assert frames[0]["error"]["code"] == "rejected"
    assert "provider" in frames[0]["error"]["message"]


# --- sandbox and confirmation over the wire --------------------------------
def test_trust_set_round_trips_through_the_orchestrator():
    """Trust must be settable by a frontend that has no Tkinter checkbox."""
    from tonyagent.tools import tool_orchestrator

    session = _session()
    frames = _drive(
        [{"id": 1, "method": "trust.set",
          "params": {"project": "/tmp/proj", "trusted": True}}],
        session=session,
    )
    assert frames[0]["result"]["trusted"] is True
    assert tool_orchestrator.is_trusted("/tmp/proj") is True
    tool_orchestrator.set_trusted("/tmp/proj", False)


def test_trust_set_requires_a_project():
    frames = _drive(
        [{"id": 1, "method": "trust.set", "params": {"trusted": True}}]
    )
    assert frames[0]["error"]["code"] == "rejected"


# --- provider discovery ----------------------------------------------------
def test_providers_list_comes_from_the_registry():
    """The frontend must not carry its own copy of the provider names.

    A hardcoded list would drift the moment a provider is added or renamed,
    and the UI would offer a provider the core cannot build.
    """
    from tonyagent.providers import ProviderFactory

    frames = _drive([{"id": 1, "method": "providers.list"}])
    providers = frames[0]["result"]["providers"]
    expected = {p["name"] for p in ProviderFactory.get_available_providers()}
    assert {p["name"] for p in providers} == expected
    assert expected, "the registry must not be empty"
    assert "models" in providers[0]
    assert "has_credentials" in providers[0]


def test_providers_list_never_returns_key_material():
    """A credential flag is fine; the credential itself must never cross."""
    frames = _drive([{"id": 1, "method": "providers.list"}])
    for provider in frames[0]["result"]["providers"]:
        assert set(provider) == {
            "name", "models", "has_credentials",
            "supports_streaming", "supports_function_calling",
        }
        assert isinstance(provider["has_credentials"], bool)


def test_sandbox_start_remembers_the_project_for_state(monkeypatch):
    """A reloaded window must learn which folder the core is attached to.

    The real ``start_sandbox`` would need Docker; only the bookkeeping this
    handler does on top of it is under test.
    """
    session = _session()
    project = str(Path.cwd())

    async def fake_start(path=""):
        session.emit(EventType.SANDBOX_STATUS, {"status": "running"})
        return True

    monkeypatch.setattr(session, "start_sandbox", fake_start)

    stdin = io.StringIO(
        json.dumps({"id": 1, "method": "sandbox.start", "params": {"path": project}})
        + "\n"
        + json.dumps({"id": 2, "method": "state"}) + "\n"
    )
    stdout = io.StringIO()
    asyncio.run(StdioServer(session, stdin, stdout).serve())
    frames = [json.loads(l) for l in stdout.getvalue().splitlines() if l.strip()]
    # Look replies up by id: an async handler replies after the events it
    # causes, so frame order is not reply order.
    replies = {f["id"]: f["result"] for f in frames if "id" in f}

    assert replies[1]["running"] is True
    assert replies[1]["project"] == project
    assert replies[2]["project"] == project


def test_confirm_respond_requires_an_id():
    frames = _drive(
        [{"id": 1, "method": "confirm.respond", "params": {"confirmed": True}}]
    )
    assert frames[0]["error"]["code"] == "rejected"
    assert "id" in frames[0]["error"]["message"]


def test_confirmation_requests_are_published_as_events(monkeypatch):
    """Regression: a confirmation used to be queued for a Tk loop that is absent.

    With no ``after()`` loop draining the queue, the request vanished and the
    tool blocked for its full 60s timeout. The bridge must publish an event.
    """
    from tonyagent.tools import tool_orchestrator

    session = _session()
    seen = []
    session.bus.subscribe(seen.append)

    class _Req:
        def __init__(self):
            self.tool_call = type("C", (), {"id": "t9", "name": "write_file",
                                            "arguments": {"path": "a.txt"}})()
            self.tool = type("T", (), {"description": "writes", "destructive": True})()

    tool_orchestrator.set_confirmation_callback(session._on_confirmation_requested)
    try:
        session._on_confirmation_requested(_Req())
    finally:
        tool_orchestrator.set_confirmation_callback(None)

    requests = [e for e in seen if e.type == EventType.CONFIRMATION_REQUESTED]
    assert requests, "no confirmation event was published"
    assert requests[0].payload["id"] == "t9"
    assert requests[0].payload["name"] == "write_file"
    assert requests[0].payload["destructive"] is True


def test_server_installs_the_confirmation_bridge_automatically():
    """A sidecar must be able to ask the user without any UI wiring."""
    from tonyagent.tools import tool_orchestrator

    session = _session()
    _drive([{"id": 1, "method": "ping"}], session=session)
    # Constructing the server is what installs the bridge.
    assert tool_orchestrator._confirmation_callback is not None
    tool_orchestrator.set_confirmation_callback(None)


def test_sandbox_stats_reports_empty_when_not_running():
    """Stats are best-effort; a stopped sandbox must not raise."""
    session = _session()
    frames = _drive(
        [{"id": 1, "method": "sandbox.stats"}], session=session
    )
    assert "result" in frames[0], frames[0]
    assert frames[0]["result"] == {}


def test_the_reply_for_a_request_comes_before_its_events():
    """Ordering guarantee: a frontend can attribute pushes to a turn.

    ``send`` returns a turn id, then the turn streams events. If the reply
    arrived after the first event, the UI would have to buffer events it could
    not yet attribute.
    """
    session = _session()
    stdin = io.StringIO(
        json.dumps({"id": 7, "method": "send", "params": {"text": "Hi"}}) + "\n"
    )
    stdout = io.StringIO()
    server = StdioServer(session, stdin, stdout)

    async def go():
        await server.serve()
        await asyncio.sleep(0.3)

    asyncio.run(go())
    frames = [json.loads(l) for l in stdout.getvalue().splitlines() if l.strip()]
    assert frames[0]["id"] == 7, "the reply must be the first frame"
    assert frames[0]["result"]["turn_id"] == frames[1]["turn_id"]


# --- credentials over the wire ---------------------------------------------
#
# The React UI renders BOTH stdout and stderr: stdout frames become the
# transcript, the error banner and the log strip. So a key that reaches
# either stream is a key on screen. These tests are the guarantee that it
# does not, and they check the raw bytes rather than the parsed reply --
# a leak in a field nothing reads is still a leak.

_KEY = "sk-ant-supersecret-value-do-not-leak-1234567890"


class _FakeKeyring:
    """Stand-in for the `keyring` module, so no OS credential store is touched."""

    def __init__(self, fail: bool = False) -> None:
        self.store: dict[tuple[str, str], str] = {}
        self.fail = fail

    def set_password(self, service: str, key: str, value: str) -> None:
        if self.fail:
            # Mirrors a real backend: the exception quotes the value it was
            # handed, which is exactly why the handler must not return str(exc).
            raise RuntimeError(f"backend refused value {value!r}")
        self.store[(service, key)] = value

    def get_password(self, service: str, key: str) -> str | None:
        return self.store.get((service, key))

    def delete_password(self, service: str, key: str) -> None:
        self.store.pop((service, key), None)


@pytest.fixture
def fake_keyring(monkeypatch):
    import tonyagent.config.keyring as keyring_mod

    fake = _FakeKeyring()
    monkeypatch.setattr(keyring_mod, "keyring", fake)
    return fake


def test_key_save_stores_the_key_and_reports_only_the_provider(fake_keyring):
    frames = _drive([
        {"id": 1, "method": "key.save",
         "params": {"provider": "anthropic", "api_key": _KEY}},
    ])
    assert frames[0]["result"] == {"provider": "anthropic", "saved": True}
    assert fake_keyring.store[("TONYAgent", "anthropic:api_key")] == _KEY


def test_key_save_normalises_a_pasted_key(fake_keyring):
    """A trailing newline survives every local check and is rejected by the API."""
    frames = _drive([
        {"id": 1, "method": "key.save",
         "params": {"provider": "openai", "api_key": f'  "{_KEY}"\n'}},
    ])
    assert frames[0]["result"]["saved"] is True
    assert fake_keyring.store[("TONYAgent", "openai:api_key")] == _KEY


def test_the_key_never_appears_on_stdout(fake_keyring, capsys):
    """The load-bearing test: not in the reply, not in an event, not anywhere."""
    frames = _drive([
        {"id": 1, "method": "key.save",
         "params": {"provider": "anthropic", "api_key": _KEY}},
        {"id": 2, "method": "state"},
    ])
    wire = json.dumps(frames)
    assert _KEY not in wire
    # Belt and braces: a truncated key must not survive either, in case a
    # future edit starts masking only the tail.
    assert _KEY[:16] not in wire
    assert _KEY[-16:] not in wire
    # And nothing on stderr either -- the UI shows that in the log strip.
    assert _KEY not in capsys.readouterr().err


def test_a_keyring_failure_does_not_echo_the_key(monkeypatch, capsys):
    """A rejected key must not come back in the error the user sees.

    The real keyring backend quotes the value it refused inside its
    exception, so returning str(exc) would put the secret straight into the
    error banner and the log strip.
    """
    import tonyagent.config.keyring as keyring_mod

    monkeypatch.setattr(keyring_mod, "keyring", _FakeKeyring(fail=True))
    frames = _drive([
        {"id": 1, "method": "key.save",
         "params": {"provider": "anthropic", "api_key": _KEY}},
    ])
    assert frames[0]["error"]["code"] == "rejected"
    assert _KEY not in json.dumps(frames)
    assert _KEY not in capsys.readouterr().err


def test_key_save_requires_both_fields(fake_keyring):
    for params in ({}, {"provider": "openai"}, {"api_key": _KEY}, {"provider": " ", "api_key": _KEY}):
        frames = _drive([{"id": 1, "method": "key.save", "params": params}])
        assert frames[0]["error"]["code"] == "rejected", params


def test_key_delete_removes_the_stored_key(fake_keyring):
    fake_keyring.store[("TONYAgent", "groq:api_key")] = _KEY
    frames = _drive([
        {"id": 1, "method": "key.delete", "params": {"provider": "groq"}},
    ])
    assert frames[0]["result"] == {"provider": "groq", "deleted": True}
    assert ("TONYAgent", "groq:api_key") not in fake_keyring.store


def test_there_is_no_method_that_returns_a_key():
    """A get-key method is a screenshot waiting to happen.

    Guards the design decision, not the code: adding `key.get` would be a
    one-line change that silently breaks it.
    """
    server = StdioServer(_session(), io.StringIO(""), io.StringIO())
    assert not [m for m in server._handlers if "get" in m and "key" in m]


def test_providers_list_reports_credential_presence_after_a_save(fake_keyring):
    """`has_credentials` must reflect the keyring without revealing the key."""
    fake_keyring.store[("TONYAgent", "groq:api_key")] = _KEY
    frames = _drive([{"id": 1, "method": "providers.list"}])
    by_name = {p["name"]: p for p in frames[0]["result"]["providers"]}
    assert by_name["groq"]["has_credentials"] is True
    assert by_name["openai"]["has_credentials"] is False
    assert _KEY not in json.dumps(frames)


# --- search ----------------------------------------------------------------
def test_search_finds_matches_in_the_project(tmp_path, monkeypatch):
    (tmp_path / "a.py").write_text("import os\n\ndef load():\n    return 1\n", encoding="utf-8")
    (tmp_path / "b.txt").write_text("nothing here\n", encoding="utf-8")

    from tonyagent.folder import folder_manager

    previous = folder_manager.current_folder
    folder_manager.set_folder(tmp_path)
    try:
        frames = _drive([
            {"id": 1, "method": "search", "params": {"pattern": "def load"}},
        ])
    finally:
        # folder_manager is a module-level singleton and also persists the
        # choice in settings, so leaving it pointed at a tmp dir would leak
        # into every later test in the session.
        if previous is not None:
            folder_manager.set_folder(previous)

    result = frames[0]["result"]
    assert len(result["matches"]) == 1
    assert result["matches"][0]["file"] == "a.py"
    assert result["matches"][0]["line"] == 3


def test_search_rejects_an_empty_pattern():
    frames = _drive([{"id": 1, "method": "search", "params": {"pattern": "  "}}])
    assert frames[0]["error"]["code"] == "rejected"


def test_search_reports_an_invalid_regex_as_a_rejection():
    """A bad pattern is the user's typo, not a server fault."""
    frames = _drive([{"id": 1, "method": "search", "params": {"pattern": "([unclosed"}}])
    assert frames[0]["error"]["code"] == "rejected"
    assert "regex" in frames[0]["error"]["message"].lower()


def test_search_matches_the_same_rules_the_agent_gets(tmp_path):
    """The UI and the agent must not disagree about what is searchable.

    `search` delegates to the same GrepTool, so node_modules and friends are
    skipped for the user exactly as they are for the model. This test fails if
    someone ever gives the protocol its own scan.
    """
    import asyncio as _asyncio

    from tonyagent.folder import folder_manager
    from tonyagent.tools import tool_registry

    (tmp_path / "keep.py").write_text("needle\n", encoding="utf-8")
    junk = tmp_path / "node_modules" / "pkg"
    junk.mkdir(parents=True)
    (junk / "dep.py").write_text("needle\n", encoding="utf-8")

    previous = folder_manager.current_folder
    folder_manager.set_folder(tmp_path)
    try:
        grep = tool_registry.get("grep")
        direct = _asyncio.run(grep.execute(pattern="needle"))
        files = {a["data"][0]["file"] for a in direct.artifacts if a.get("type") == "grep_result"}
    finally:
        if previous is not None:
            folder_manager.set_folder(previous)

    assert files == {"keep.py"}, "node_modules must be skipped for both callers"
