"""Phase 4 tests: trust toggle + orchestrator entry points + UI wiring."""

from __future__ import annotations

import ast
from contextlib import contextmanager
import asyncio
from pathlib import Path

import pytest

from tonyagent.folder.manager import folder_manager
from tonyagent.tools import tool_orchestrator
from tonyagent.tools import orchestrator as orchestrator_mod
from tonyagent.tools.base import ToolResultStatus
from tonyagent.tools.orchestrator import ToolCall, ToolOrchestrator


@pytest.fixture(autouse=True)
def _inline_ui_callbacks(monkeypatch):
    """Run confirmation callbacks inline.

    ``schedule_on_ui`` only enqueues onto a queue that the Tk main loop drains;
    with no UI running the confirmation future would never resolve and the
    orchestrator would block for its full 60s timeout.
    """
    monkeypatch.setattr(
        orchestrator_mod, "schedule_on_ui", lambda func, *a, **kw: func(*a, **kw)
    )


async def test_execute_tool_rejects_async_context():
    orch = ToolOrchestrator()
    call = ToolCall(id="1", name="nope", arguments={})
    with pytest.raises(RuntimeError, match="execute_tool_async"):
        orch.execute_tool(call)


async def test_execute_tool_async_entry_point():
    orch = ToolOrchestrator()
    call = ToolCall(id="1", name="unknown-tool", arguments={})
    result = await orch.execute_tool_async(call)
    assert result.status is ToolResultStatus.ERROR
    assert "Unknown tool" in result.error


async def test_trusted_project_skips_confirmation(tmp_path, monkeypatch):
    from tonyagent.tools.file_tools import WriteFileTool

    orch = ToolOrchestrator()
    monkeypatch.setattr(folder_manager, "_current_folder", tmp_path)
    orch.set_trusted(str(tmp_path), True)
    assert orch.is_trusted(str(tmp_path)) is True

    # list_dir is non-destructive; use write_file (destructive+confirm) instead.
    orch.set_confirmation_callback(lambda req: (_ for _ in ()).throw(AssertionError("should not ask")))
    call = ToolCall(id="t1", name="write_file", arguments={"path": "note.txt", "content": "hi"})
    result = await orch.execute_tool_async(call)
    assert result.status is ToolResultStatus.SUCCESS
    assert (tmp_path / "note.txt").read_text() == "hi"


async def test_untrusted_project_still_asks(tmp_path, monkeypatch):
    from tonyagent.tools.file_tools import WriteFileTool

    orch = ToolOrchestrator()
    monkeypatch.setattr(folder_manager, "_current_folder", tmp_path)
    assert orch.is_trusted(str(tmp_path)) is False

    async def fake_confirm(tool_call, tool):
        # Simulate user approving via the future machinery.
        await asyncio.sleep(0)
        orch.respond_to_confirmation(tool_call.id, True)

    def on_confirm(request):
        asyncio.get_running_loop().create_task(fake_confirm(request.tool_call, request.tool))

    orch.set_confirmation_callback(on_confirm)
    call = ToolCall(id="t2", name="write_file", arguments={"path": "note2.txt", "content": "yo"})
    result = await orch.execute_tool_async(call)
    assert result.status is ToolResultStatus.SUCCESS
    assert (tmp_path / "note2.txt").read_text() == "yo"


async def test_shared_orchestrator_trust_roundtrip(tmp_path):
    tool_orchestrator.set_trusted(str(tmp_path), True)
    assert tool_orchestrator.is_trusted(str(tmp_path)) is True
    tool_orchestrator.set_trusted(str(tmp_path), False)
    assert tool_orchestrator.is_trusted(str(tmp_path)) is False


def test_ui_has_trust_toggle_and_stats_migration():
    src = (Path(__file__).resolve().parents[2] / "src/tonyagent/ui/views/main_window.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(src)
    assert tree is not None
    assert "_on_trust_toggle" in src
    assert "trust_check" in src
    assert "set_trusted" in src
    # Phase 4 migration: no direct docker SDK use in the UI anymore.
    assert "docker.from_env()" not in src
    assert "get_stats()" in src
    assert "fallback_to_local" not in src  # UI never needed it; tools own it


def test_stats_polling_happens_off_the_ui_thread():
    """`docker stats` must never run on the Tk thread (it blocks ~1s)."""
    from pathlib import Path as _P

    src = (_P(__file__).resolve().parents[2] / "src/tonyagent/ui/views/main_window.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(src)

    poll = next(
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == "_update_sandbox_resource_usage"
    )
    # The collector itself must not await docker directly...
    assert not any(isinstance(n, ast.Await) for n in ast.walk(poll))
    # ...it must hand off to a thread and render via the UI queue.
    assert any(isinstance(n, ast.Call) and getattr(n.func, "attr", "") == "start"
               for n in ast.walk(poll))
    assert any(
        isinstance(n, ast.Call) and getattr(n.func, "id", "") == "schedule_on_ui"
        for n in ast.walk(poll)
    )
    apply_fn = next(
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == "_apply_sandbox_stats"
    )
    assert any(
        isinstance(n, ast.Call) and getattr(n.func, "attr", "") == "configure"
        for n in ast.walk(apply_fn)
    )


def test_collapsible_never_binds_toggle_to_a_press():
    """Regression: a press-drag to select text collapsed the section for good.

    The toggle used to be bound to <Button-1> on the PANEL. A drag-select
    anywhere in the body fired it, grid_remove() then destroyed the widget under
    the cursor, which ended the drag - and no further <Button-1> ever arrived, so
    the section could never be reopened. The toggle must therefore:
      1. never be bound to the `panel` itself, and
      2. be bound to <ButtonRelease-1> (a click), not <Button-1> (a press).
    A <Button-1> bind is still allowed, but only to swallow the press so the
    title does not start a text selection - never to call `toggle`.
    """
    from pathlib import Path
    import ast

    src = (Path(__file__).resolve().parents[2] / "src/tonyagent/ui/views/main_window.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(src)
    fn = next(
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == "_make_collapsible"
    )

    toggle_binds, press_binds_with_toggle, panel_binds = [], [], []
    for call in (n for n in ast.walk(fn) if isinstance(n, ast.Call)):
        if not (isinstance(call.func, ast.Attribute) and call.func.attr == "bind"):
            continue
        target = getattr(call.func.value, "id", None)
        event = next(
            (a.value for a in call.args
             if isinstance(a, ast.Constant) and isinstance(a.value, str)),
            None,
        )
        # A bind that passes `toggle` as a callback is the dangerous one.
        passes_toggle = any(
            isinstance(a, ast.Name) and a.id == "toggle" for a in call.args
        )
        if passes_toggle:
            toggle_binds.append((target, event))
            if event == "<Button-1>":
                press_binds_with_toggle.append((target, event))
        if target == "panel":
            panel_binds.append(event)

    assert toggle_binds, "expected the toggle to be bound somewhere"
    assert not press_binds_with_toggle, (
        f"toggle must not fire on <Button-1> (press): {press_binds_with_toggle}"
    )
    assert any(e == "<ButtonRelease-1>" for _, e in toggle_binds), (
        f"toggle should bind on <ButtonRelease-1>, got {toggle_binds}"
    )
    assert not panel_binds, (
        f"the panel itself must never be bound (breaks text selection): {panel_binds}"
    )


def test_collapsible_callers_pass_a_title_label():
    from pathlib import Path

    src = (Path(__file__).resolve().parents[2] / "src/tonyagent/ui/views/main_window.py").read_text(
        encoding="utf-8"
    )
    # Without a title label there is nothing to bind to, so a section could
    # never be reopened - exactly the reported bug.
    assert src.count("title_label=self._") >= 2, "collapsible sections missing title labels"


# --- Regression: chat could never start (ToolSchema) ---------------------------

def test_all_schemas_convert_to_tool_schema():
    """Regression: ToolSchema(**schema) raised on 'category' and killed every turn.

    ALL_SCHEMAS entries carry UI-only keys the dataclass does not declare, so
    the UI must use the dedicated converter.
    """
    import tonyagent.tools as T
    from tonyagent.providers.base import ToolSchema

    tools = [ToolSchema.from_tool_schema_dict(s) for s in T.ALL_SCHEMAS]
    assert len(tools) == len(T.ALL_SCHEMAS)
    assert all(t.name for t in tools)
    # 'required' must be lifted out of the JSON-Schema 'parameters' block.
    read = next(t for t in tools if t.name == "read_file")
    assert read.required == ["path"]
    # And the result must be usable as a provider payload.
    payloads = [t.to_openai_format() for t in tools]
    assert all(p["type"] == "function" for p in payloads)
    assert all(p["function"]["name"] for p in payloads)


def test_tool_schema_converter_tolerates_missing_optional_keys():
    from tonyagent.providers.base import ToolSchema

    t = ToolSchema.from_tool_schema_dict({"name": "x", "description": "d"})
    assert t.name == "x" and t.parameters == {} and t.required == []
    t2 = ToolSchema.from_tool_schema_dict(
        {"name": "y", "description": "d", "parameters": {"type": "object", "required": ["a"]}}
    )
    assert t2.required == ["a"]


def test_ui_uses_the_schema_converter():
    """Guard the call site so the bare **schema form cannot come back.

    The conversion moved into the core session when the turn loop was
    extracted, so the guard follows it there. ``ALL_SCHEMAS`` entries carry
    extra UI-only keys, so ``ToolSchema(**schema)`` raised TypeError while
    ``from_tool_schema_dict`` is the supported path.
    """
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    core = (root / "src/tonyagent/core/session.py").read_text(encoding="utf-8")
    assert "ToolSchema(**schema)" not in core
    assert "ToolSchema.from_tool_schema_dict(" in core


# --- Regression: ghost/secondary buttons rendered white ------------------------

def test_transparent_token_is_literal_not_text_primary():
    """Unknown tokens fall back to text_primary, which made ghost buttons white.

    In dark mode text_primary is near-white, so a 'transparent' fg_color became a
    white block with white text - visible only on hover.
    """
    from tonyagent.ui.theme import theme_manager

    pair = theme_manager.get_color_pair("transparent")
    assert pair == ("transparent", "transparent")
    # Must not silently degrade to a theme colour.
    assert "transparent" not in theme_manager.get_color_pair("text_primary")


def test_transparent_token_literal_in_both_modes():
    from tonyagent.ui.theme import theme_manager

    previous = theme_manager.get_theme()
    try:
        for mode in ("light", "dark"):
            theme_manager.set_theme(mode)
            assert theme_manager.get_color_pair("transparent") == ("transparent", "transparent")
    finally:
        theme_manager.set_theme(previous)


def test_every_theme_token_resolves_to_something_sane():
    """No token should resolve to an accidental near-white/near-black fallback."""
    from tonyagent.ui.theme import LITERAL_COLORS, theme_manager

    previous = theme_manager.get_theme()
    known = {
        "primary", "primary_hover", "primary_active", "secondary", "secondary_hover",
        "surface", "surface_hover", "surface_active", "background", "background_secondary",
        "border", "border_focus", "text_primary", "text_secondary", "text_muted",
        "text_on_primary", "success", "success_bg", "warning", "warning_bg", "error",
        "error_bg", "info", "info_bg", "shadow", "overlay",
    } | set(LITERAL_COLORS)
    try:
        theme_manager.set_theme("dark")
        for token in known:
            value = theme_manager.get_color_pair(token)
            assert all(isinstance(c, str) and c for c in value), token
    finally:
        theme_manager.set_theme(previous)

# --- Live UI: build the real window and assert it is usable -------------------

@contextmanager
def real_window(monkeypatch, provider="openrouter", stored_key="sk-or-v1-" + "a" * 64):
    """Build an actual MainWindow so widget states can be asserted.

    This is the check that would have caught the 'Save to Keyring is disabled'
    and 'the entry cannot be clicked' bugs - both were invisible to source
    inspection and to the mock-based tests.

    The default ``stored_key`` is a structurally valid 73-character key because
    the app now verifies exact key length locally. A stand-in like
    "sk-or-EXISTING-KEY" is correctly rejected as malformed, which would fail
    these widget-state tests for a reason unrelated to what they check.
    """
    import customtkinter as ctk

    import tonyagent.config.keyring as kr
    from tonyagent.config.settings import settings
    from tonyagent.ui.theme import theme_manager
    from tonyagent.ui.views.main_window import MainWindow

    theme_manager.initialize()
    monkeypatch.setattr(kr, "load_api_key", lambda name: stored_key)
    monkeypatch.setattr(settings.provider, "name", provider)

    root = ctk.CTk()
    root.withdraw()
    try:
        win = MainWindow(root)
        root.update_idletasks()
        yield win, root
    finally:
        try:
            root.destroy()
        except Exception:
            pass


def test_api_key_entry_and_save_button_are_usable(monkeypatch):
    """Regression: both were disabled, so the user could not enter a key."""
    with real_window(monkeypatch) as (win, root):
        assert win.api_key_entry.cget("state") == "normal", "API key entry is not clickable"
        assert win.save_key_btn.cget("state") == "normal", "Save to Keyring is disabled"
        assert win.test_btn.cget("state") == "normal"

        # Typing must stick.
        win.api_key_entry.insert(0, "sk-or-NEW-KEY")
        root.update()
        assert win.api_key_entry.get() == "sk-or-NEW-KEY"
        assert win.api_key_entry.cget("state") == "normal"
        assert win.save_key_btn.cget("state") == "normal"


def test_key_entry_is_empty_not_prefilled(monkeypatch):
    """A mask baked into the field turns typing into garbage."""
    with real_window(monkeypatch) as (win, _root):
        assert win.api_key_entry.get() == "", "field should start empty"
        assert "replace" in win.api_key_entry.cget("placeholder_text").lower()
        assert "keyring" in win.api_key_saved_hint.cget("text").lower()


def test_no_saved_key_path_is_also_usable(monkeypatch):
    """A provider with no stored key must not be disabled either."""
    with real_window(monkeypatch, stored_key=None) as (win, _root):
        assert win.api_key_entry.cget("state") == "normal"
        assert win.save_key_btn.cget("state") == "normal"
        assert "no key saved" in win.api_key_saved_hint.cget("text").lower()


def test_ghost_buttons_are_transparent_not_white(monkeypatch):
    """Regression: unknown theme tokens fell back to text_primary (white)."""
    with real_window(monkeypatch) as (win, _root):
        for name in ("save_key_btn", "test_btn", "forget_key_btn"):
            btn = getattr(win, name)
            fg = btn.cget("fg_color")
            assert fg != ("transparent", "#F8FAFC"), (
                f"{name} background resolved to near-white: {fg}"
            )


def test_collapsible_sections_toggle_without_error(monkeypatch):
    with real_window(monkeypatch) as (win, root):
        was = win._provider_expanded()
        win._set_provider_expanded(not was)
        root.update()
        assert win._provider_expanded() is (not was)
        win._set_provider_expanded(was)
        root.update()


def test_key_hint_and_forget_button_do_not_overlap(monkeypatch):
    """Regression: both were gridded into row 3 / column 1, so the text drew
    underneath the button. Assert real geometry rather than reading the source.
    """
    with real_window(monkeypatch) as (win, root):
        root.update()

        def box(w):
            assert w.winfo_ismapped(), f"{type(w).__name__} is not visible"
            x, y = w.winfo_rootx(), w.winfo_rooty()
            return (x, y, x + w.winfo_width(), y + w.winfo_height())

        hint, btn = box(win.api_key_saved_hint), box(win.forget_key_btn)
        overlaps = not (hint[2] <= btn[0] or btn[2] <= hint[0]
                        or hint[3] <= btn[1] or btn[3] <= hint[1])
        assert not overlaps, f"key hint overlaps the Forget button: {hint} vs {btn}"
        # And they must be stacked, not on the same line.
        assert hint[3] <= btn[1], "the Forget button should sit below the hint"
        # The key entry must be above both.
        assert box(win.api_key_entry)[3] <= hint[1]


def test_provider_panel_rows_do_not_collide(monkeypatch):
    """Every labelled row in the provider panel must have a distinct row."""
    with real_window(monkeypatch) as (win, root):
        root.update()
        # The real invariant is that no two widgets occupy the same grid cell,
        # because that is what makes them overlap. Comparing rows alone is no
        # longer correct now that the two action buttons sit side by side on one
        # row (Test Connection left, Save to Keyring right).
        cells = {}
        for name in ("provider_combo", "api_key_entry", "api_key_saved_hint",
                     "forget_key_btn", "model_combo", "test_btn", "save_key_btn"):
            info = getattr(win, name).grid_info()
            cells[name] = (int(info["row"]), int(info["column"]))
        assert len(set(cells.values())) == len(cells), f"cells collide: {cells}"

        # The stacked fields must still be on separate rows.
        stacked = [cells[n] for n in ("provider_combo", "api_key_entry", "model_combo")]
        assert len({r for r, _ in stacked}) == 3, f"fields overlap: {cells}"

        # And the two action buttons must not share a cell.
        assert cells["test_btn"] != cells["save_key_btn"], (
            f"action buttons overlap: {cells}"
        )
