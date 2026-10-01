"""End-to-end tests for the real chat path (httpx transport mocked, not the SDK).

The transport is faked at the httpx level so the request building, the dialect
translation and the SSE parsing all run for real - mocking the client itself
would have hidden exactly the bugs we are guarding against.
"""

from __future__ import annotations

import json

import httpx
import pytest

from tonyagent.providers import ChatCompletion, ChatCompletionChunk  # noqa: F401
from tonyagent.providers.base import ChatMessage, MessageRole


def _sse(pieces):
    return "".join(
        "data: " + json.dumps({"choices": [{"delta": {"content": p}, "index": 0}],
                               "model": "fake"}) + "\n\n"
        for p in pieces
    ) + "data: [DONE]\n\n"


def _install_transport(monkeypatch, pieces=("Hello", " from", " mock"),
                       status=200, models=None, fail_body=None):
    """Swap httpx.AsyncClient for one backed by a MockTransport."""
    import tonyagent.api.client as client_mod

    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if status >= 400:
            return httpx.Response(status, text=fail_body or '{"error":{"message":"boom"}}')
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": m} for m in (models or ["m1", "m2"])]})
        return httpx.Response(200, text=_sse(list(pieces)),
                              headers={"content-type": "text/event-stream"})

    transport = httpx.MockTransport(handler)
    real_client = httpx.AsyncClient

    def factory(*a, **kw):
        kw.pop("transport", None)
        return real_client(*a, transport=transport, **kw)

    monkeypatch.setattr(client_mod.httpx, "AsyncClient", factory)

    def fake_key(name):
        import tonyagent.providers  # noqa: F401
        from tonyagent.providers.base import provider_registry

        cls = provider_registry.get(name)
        prefix = getattr(cls, "key_prefix", "") or ""
        # Build a key that satisfies the provider's own declared rules. Faking
        # it with a fixed 64-char body produced 70 characters for OpenRouter,
        # which is not a valid 73-character key - the mock then failed a check
        # that was doing its job.
        expected = getattr(cls, "key_length", None)
        if expected:
            return (prefix + "a" * expected)[:expected].ljust(expected, "a")
        # An empty key_prefix means "no prefix is enforced" (Mistral, Ollama),
        # NOT "no key exists". Ollama genuinely needs none, but Mistral and the
        # rest still require a bearer value, so return a placeholder and let
        # check_key decide.
        return prefix + "a" * 64

    monkeypatch.setattr("tonyagent.providers.base.load_api_key", fake_key)
    return seen


def _chat_window(monkeypatch, provider_name="openrouter", model="stealth/space-bunny-alpha"):
    """A MainWindow bound to a real AgentSession.

    The window no longer drives the turn; the session does and reports over the
    event bus. These tests therefore assert on the *events the UI receives*,
    which is exactly the surface a Tauri frontend will use.
    """
    from tonyagent.core.events import EventBus
    from tonyagent.core.session import AgentSession
    from tonyagent.providers import ProviderFactory
    from tonyagent.ui.views.main_window import MainWindow
    import tonyagent.ui.views.main_window as mw

    captured = []
    monkeypatch.setattr(
        mw, "schedule_on_ui",
        lambda fn, *a, **kw: captured.append((getattr(fn, "__name__", str(fn)), a)),
    )
    win = MainWindow.__new__(MainWindow)
    win._generating = False
    win._current_ai_message_frame = object()
    win._current_ai_label = None
    win._log = lambda *a, **k: None
    win._update_token_count = lambda n: None
    win._session = AgentSession(bus=EventBus())
    win._current_provider = ProviderFactory.create_provider(provider_name, model=model)
    win._session.provider = win._current_provider
    win._session.provider_name = provider_name
    win._session.model = model
    win._session.messages = [ChatMessage(role="user", content="Hi")]
    # Route core events through the UI handler, exactly as __init__ does.
    win._session.bus.subscribe(win._on_session_event)
    return win, captured


async def test_chat_path_streams_end_to_end(monkeypatch):
    """The provider must actually stream a reply."""
    seen = _install_transport(monkeypatch)
    win, captured = _chat_window(monkeypatch)

    await win._session.run_turn("Hi")

    names = [c[0] for c in captured]
    assert "_generation_error" not in names, [a[0] for n, a in captured if n == "_generation_error"]
    assert "".join(a[0] for n, a in captured if n == "_stream_chunk") == "Hello from mock"
    assert "_generation_finished" in names
    assert win._session.messages[-1].role.value == "assistant"
    assert win._session.messages[-1].content == "Hello from mock"
    # The request must have carried the key and the tools.
    post = [r for r in seen if r.method == "POST"][0]
    assert post.headers["Authorization"].startswith("Bearer sk-or-")
    body = json.loads(post.content)
    assert body["tools"], "tools were not sent"
    assert body["stream"] is True


async def test_chat_path_with_string_roles_streams(monkeypatch):
    """The UI builds messages with plain-string roles; that must work."""
    _install_transport(monkeypatch)
    win, captured = _chat_window(monkeypatch)
    win._session.messages = [ChatMessage(role="user", content="Hi")]
    await win._session.run_turn("Hi")
    assert "_generation_error" not in [c[0] for c in captured]
    assert "".join(a[0] for n, a in captured if n == "_stream_chunk") == "Hello from mock"


async def test_provider_failure_reaches_the_user(monkeypatch):
    """A rejected key must produce a visible error, never a silent empty bubble."""
    _install_transport(monkeypatch, status=401,
                       fail_body='{"error":{"message":"User not found.","code":401}}')
    win, captured = _chat_window(monkeypatch)
    await win._session.run_turn("Hi")
    errors = [a[0] for n, a in captured if n == "_generation_error"]
    assert errors, "a 401 produced no error at all"
    assert "User not found" in errors[0]


async def test_real_health_check_reports_success(monkeypatch):
    _install_transport(monkeypatch)
    win, _ = _chat_window(monkeypatch)
    health = await win._current_provider.check_connection()
    assert health.ok, health.message
    assert health.models == ["m1", "m2"]


async def test_real_health_check_catches_a_401(monkeypatch):
    _install_transport(monkeypatch, status=401,
                       fail_body='{"error":{"message":"User not found."}}')
    win, _ = _chat_window(monkeypatch)
    health = await win._current_provider.check_connection()
    assert not health.ok
    assert "User not found" in health.message


def test_truncated_key_is_caught_before_any_request():
    """The exact failure the user hit: a short key that looks fine locally."""
    from tonyagent.providers.openrouter import OpenRouterProvider

    truncated = OpenRouterProvider(api_key="sk-or-v1-abc", model="m")
    assert truncated.validate_credentials() is False, "a truncated key must not validate"
    with pytest.raises(Exception):
        truncated.http_client().check_key()

    full = OpenRouterProvider(api_key="sk-or-v1-" + "a" * 64, model="m")
    assert full.validate_credentials() is True


async def test_tool_calls_actually_execute(monkeypatch):
    """Regression: the tool path raised RuntimeError and no tool ever ran.

    The turn loop called the *synchronous* ``tool_orchestrator.execute_tool()``
    from inside a coroutine, and that function deliberately refuses to run in a
    live event loop. Every tool call therefore died before executing, and the
    blanket ``except Exception`` hid it. The session now awaits the async entry
    point; this asserts a real tool reaches the orchestrator.
    """
    from tonyagent.core.events import EventBus, EventType
    from tonyagent.core.session import AgentSession
    from tonyagent.providers import ChatCompletionChunk
    from tonyagent.tools import tool_orchestrator
    from tonyagent.tools.base import ToolResult, ToolResultStatus

    executed = []

    async def fake_async(self, tool_call):
        executed.append(tool_call.name)
        return ToolResult(status=ToolResultStatus.SUCCESS, output="done")

    monkeypatch.setattr(
        tool_orchestrator,
        "execute_tool_async",
        fake_async.__get__(tool_orchestrator, type(tool_orchestrator)),
    )

    class _Provider:
        def estimate_tokens(self, messages):
            return 42

        async def chat_completion(self, messages=None, tools=None, tool_choice=None,
                                  stream=False, **kw):
            async def gen():
                if not getattr(self, "_replied", False):
                    self._replied = True
                    yield ChatCompletionChunk(
                        tool_calls=[{"id": "c1", "function": {
                            "name": "list_files", "arguments": "{}"}}],
                        finish_reason="tool_calls",
                    )
                else:
                    yield ChatCompletionChunk(content="all set", finish_reason="stop")
            return gen()

    bus = EventBus()
    session = AgentSession(bus=bus)
    session.provider = _Provider()
    session.model = "stub"

    seen = []
    bus.subscribe(seen.append)

    await session.run_turn("list my files")

    failures = [e for e in seen if e.type == EventType.TURN_FAILED]
    assert not failures, f"turn failed: {[e.payload for e in failures]}"
    assert executed == ["list_files"], f"tool never ran; executed={executed}"
    # The tool result must also be appended so the model can see it.
    assert any(m.role.value == "tool" for m in session.messages)


async def test_a_turn_can_chain_several_tool_rounds():
    """Regression: the loop allowed exactly ONE round of tools, then errored.

    The first live turn hit it: "Hi." -> the model called list_dir -> got the
    result -> asked for another tool, and the session answered with
    "Model requested more tools after a tool result." One round is not the
    honest number for an agent; the turn now loops up to MAX_TOOL_ROUNDS.
    """
    import types

    from tonyagent.core.events import EventBus, EventType
    from tonyagent.core.session import AgentSession
    from tonyagent.providers import ChatCompletionChunk

    executed = []

    class _Provider:
        def __init__(self):
            self.rounds = 0

        def estimate_tokens(self, messages):
            return 42

        async def chat_completion(self, messages=None, tools=None, tool_choice=None,
                                  stream=False, **kw):
            self.rounds += 1
            n = self.rounds

            async def gen():
                if n <= 3:  # three tool rounds, then a plain answer
                    yield ChatCompletionChunk(
                        tool_calls=[{"id": f"c{n}", "function": {
                            "name": f"tool_{n}", "arguments": "{}"}}],
                        finish_reason="tool_calls",
                    )
                else:
                    yield ChatCompletionChunk(content="done", finish_reason="stop")
            return gen()

    async def run_tools(self, tool_calls, turn_id, round_no):
        """Mirror the real executor: one tool message per round."""
        for raw in tool_calls:
            executed.append(raw["function"]["name"])
            session.messages.append(ChatMessage(
                role="tool", content=f"{raw['function']['name']} ran",
                tool_call_id=raw["id"],
            ))
        self._round_orders.append(round_no)

    bus = EventBus()
    session = AgentSession(bus=bus)
    session.provider = _Provider()
    session.model = "stub"
    session._run_tool_calls = types.MethodType(run_tools, session)

    seen = []
    bus.subscribe(seen.append)
    await session.run_turn("do the thing")

    failures = [e for e in seen if e.type == EventType.TURN_FAILED]
    errors = [e for e in seen if e.type == EventType.ERROR]
    assert not failures, [e.payload for e in failures]
    assert not errors, [e.payload for e in errors]
    assert executed == ["tool_1", "tool_2", "tool_3"]
    assert session.messages[-1].role.value == "assistant"
    assert session.messages[-1].content == "done"


async def test_the_round_backstop_ends_a_turn_that_never_spends_a_call():
    """A gateway answering with nothing but nameless tool calls must not hang.

    A call with no ``function.name`` is skipped without being counted, so it
    never spends a call of the per-turn budget -- the budget cannot be what
    ends this turn, and something has to. It is the round backstop, and it
    says so rather than stopping the turn without a word.

    The per-turn budget itself is covered in ``test_tool_call_budget.py``,
    which drives the real executor; this test is only about the backstop,
    because that is the one bound that no normal turn should ever meet.
    """
    import types

    from tonyagent.core.events import EventBus, EventType
    from tonyagent.core.session import AgentSession
    from tonyagent.providers import ChatCompletionChunk

    class _Provider:
        def estimate_tokens(self, messages):
            return 42

        async def chat_completion(self, messages=None, tools=None, tool_choice=None,
                                  stream=False, **kw):
            async def gen():
                yield ChatCompletionChunk(
                    tool_calls=[{"id": "c1", "function": {"arguments": "{}"}}],
                    finish_reason="tool_calls",
                )
            return gen()

    async def run_tools(self, tool_calls, turn_id, round_no):
        """Mirror the real executor's shape, including its refusal flag.

        The flag is the contract: it is what tells the loop to stop. A stub
        that returns None here would run the loop to the backstop on a turn
        that should have ended, which is how this test passed for the wrong
        reason the first time it was written.
        """
        for raw in tool_calls:
            name = (raw.get("function") or {}).get("name", "")
            if not name:
                continue
            self.messages.append(ChatMessage(
                role="tool", content=f"{name} ran",
                tool_call_id=raw["id"],
            ))
        self._round_orders.append(round_no)
        return False

    bus = EventBus()
    session = AgentSession(bus=bus)
    session.provider = _Provider()
    session.model = "stub"
    session._run_tool_calls = types.MethodType(run_tools, session)

    seen = []
    bus.subscribe(seen.append)
    await session.run_turn("keep going")

    assert session._round_orders == list(range(1, AgentSession.MAX_TOOL_ROUNDS + 1))
    errors = [e for e in seen if e.type == EventType.ERROR]
    assert errors, "the backstop was hit and nothing said so"
    assert "tool call" in errors[-1].payload["message"]
    # The turn still ends cleanly rather than as a crash.
    assert any(e.type == EventType.TURN_FINISHED for e in seen)
    # No digest here, and there should not be one: the digest exists to close
    # a history left ending on an unanswered tool result, and this turn ran no
    # tool at all. Asserting it would be asserting the opposite rule.
    assert not [m for m in session.messages if m.role.value == "tool"]


async def test_a_plain_answer_appends_no_digest():
    """A turn that never touched a tool must not grow a synthetic message."""
    from tonyagent.core.events import EventBus
    from tonyagent.core.session import AgentSession
    from tonyagent.providers import ChatCompletionChunk

    class _Provider:
        def estimate_tokens(self, messages):
            return 42

        async def chat_completion(self, messages=None, tools=None, tool_choice=None,
                                  stream=False, **kw):
            async def gen():
                yield ChatCompletionChunk(content="just an answer", finish_reason="stop")
            return gen()

    bus = EventBus()
    session = AgentSession(bus=bus)
    session.provider = _Provider()
    session.model = "stub"
    await session.run_turn("hello")
    assert [m.role.value for m in session.messages] == ["user", "assistant"]
    assert session.messages[-1].content == "just an answer"


async def test_a_turn_ending_on_a_tool_result_still_closes_with_an_assistant_note():
    """The model answered with a tool call and nothing else; the next turn must
    not start from a history that ends on an unanswered tool result."""
    import types

    from tonyagent.core.events import EventBus
    from tonyagent.core.session import AgentSession
    from tonyagent.providers import ChatCompletionChunk

    class _Provider:
        def estimate_tokens(self, messages):
            return 42

        async def chat_completion(self, messages=None, tools=None, tool_choice=None,
                                  stream=False, **kw):
            async def gen():
                yield ChatCompletionChunk(
                    tool_calls=[{"id": "c1", "function": {
                        "name": "list_files", "arguments": "{}"}}],
                    finish_reason="tool_calls",
                )
            return gen()

    async def run_tools(self, tool_calls, turn_id, round_no):
        """Mirror the real executor: one tool message per round."""
        for raw in tool_calls:
            session.messages.append(ChatMessage(
                role="tool", content=f"{raw['function']['name']} ran",
                tool_call_id=raw["id"],
            ))
        self._round_orders.append(round_no)

    bus = EventBus()
    session = AgentSession(bus=bus)
    session.provider = _Provider()
    session.model = "stub"
    session._run_tool_calls = types.MethodType(run_tools, session)
    await session.run_turn("list")

    roles = [m.role.value for m in session.messages]
    assert roles[-2] == "tool"
    assert roles[-1] == "assistant"
    assert "[result 1]" in session.messages[-1].content


def test_provider_error_is_actionable():
    from tonyagent.ui.views.main_window import MainWindow

    win = MainWindow.__new__(MainWindow)
    for raw, needle in (("Error code: 401", "API key"), ("Error code: 429", "Rate limited")):
        assert needle.lower() in win._format_provider_error(raw).lower()
