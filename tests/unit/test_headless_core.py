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
