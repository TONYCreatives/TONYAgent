"""The window host, tested where a window is not needed.

The GUI itself is verified by ``scripts/verify_window.py``, which opens a real
window and probes it from the host side -- that cannot be a unit test, because it
needs a display, a WebView2 runtime and about fifteen seconds. What *can* be a
unit test is everything around it.

**One of these exists because of a bug the launcher found in a second.**
``python -m tonyagent.window`` did not work at all: ``-m package`` runs
``package.__main__``, and the package only exported ``main`` from ``__init__``,
so the one entry point the launcher and every instruction in this repository name
was the one path nothing exercised. Every harness in ``scripts/`` calls
``host.main()`` directly, and the whole suite was green while the app could not
be started the way it is started. Hence the first test here.

The rest pin the parts of the shell that fail *silently* -- an API surface
pywebview evaluates, a font served under the wrong MIME type, a handle truncated
to 32 bits. Each of those is a working-looking window with something subtly
wrong, which is exactly the class of bug a unit test is for.
"""

from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "src"

#: The page's whole API, and nothing else. See `Bridge`'s docstring: pywebview
#: walks `dir(js_api)`, *evaluates* every public attribute and recurses into
#: non-callables, so anything public here is either an API method or a hazard.
PAGE_API = [
    "core_alive",
    "pick_files",
    "pick_folder",
    "ready",
    "send",
    "system_menu",
    "window_control",
    "window_state",
]


def test_the_module_entry_point_exists():
    """``python -m tonyagent.window``, which is how the app is actually started."""
    done = subprocess.run(
        [sys.executable, "-m", "tonyagent.window", "--help"],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=120,
        env={**os.environ, "PYTHONPATH": str(SRC)},
    )
    assert done.returncode == 0, done.stderr
    assert "Open the TONYAgent window" in done.stdout


def test_the_bridge_exposes_the_page_api_and_nothing_else():
    from tonyagent.window.bridge import Bridge

    bridge = Bridge()
    public = sorted(name for name in dir(bridge) if not name.startswith("_"))

    assert public == PAGE_API, (
        "Bridge's public surface changed. pywebview exposes every public member "
        "of the js_api to the page, and evaluates the ones that are not methods."
    )


def test_the_bridge_does_not_hand_the_page_a_window_or_a_core():
    """The recursion half of the same rule.

    A public ``self.window`` would put pywebview's entire Window API in front of
    the page -- every method on it, discovered by walking into the attribute.
    """
    from tonyagent.window.bridge import Bridge

    bridge = Bridge()
    assert not hasattr(bridge, "window")
    assert not hasattr(bridge, "core")


def test_the_bridge_buffers_frames_until_the_page_is_listening():
    """The deadlock guard. See ``Bridge.ready``.

    ``evaluate_js`` before the document is ready does not fail, it deadlocks, so
    the pump must not call it until the page says it is listening.
    """
    from tonyagent.window.bridge import Bridge

    pushed: list[str] = []

    class FakeWindow:
        def evaluate_js(self, script: str) -> None:
            pushed.append(script)

    bridge = Bridge()
    bridge._attach(None, FakeWindow())

    bridge._frames(["one", "two"])
    assert pushed == [], "a frame was pushed before the page said it was listening"

    bridge.ready()
    assert len(pushed) == 1, "the buffered batch was not flushed by ready()"
    assert "one" in pushed[0] and "two" in pushed[0]


def test_the_bridge_frames_are_escaped_rather_than_interpolated():
    """A model's own output reaches the page through `evaluate_js`."""
    from tonyagent.window.bridge import Bridge

    pushed: list[str] = []

    class FakeWindow:
        def evaluate_js(self, script: str) -> None:
            pushed.append(script)

    bridge = Bridge()
    bridge._attach(None, FakeWindow())
    bridge.ready()
    bridge._frames(['{"text": "a \\" quote and a\nnewline"}'])

    # The frame arrives as a JSON *string literal* inside the script, so the
    # quote is escaped and the newline is not a line break in the script.
    assert '\\"' in pushed[0]
    assert "\n" not in pushed[0]


def test_a_picker_result_is_one_path_or_nothing():
    from tonyagent.window.bridge import _first

    assert _first("C:\\one") == "C:\\one"
    assert _first(["C:\\one", "C:\\two"]) == "C:\\one"
    # A cancel, and the shape pywebview uses for one selection on some backends.
    assert _first(None) is None
    assert _first([]) is None


def test_the_asset_server_refuses_a_directory_with_no_bundle(tmp_path):
    """The one failure a user can fix, said out loud instead of a blank window."""
    from tonyagent.window.assets import AssetServer, MissingFrontendError

    with pytest.raises(MissingFrontendError) as raised:
        AssetServer(tmp_path).start()

    assert "npm run build" in str(raised.value)


def test_the_asset_server_maps_fonts_and_forbids_caching(tmp_path):
    """Both halves are silent failures in a real window.

    A `.woff2` served as `application/octet-stream` is a font the page refuses to
    use, and Windows' `mimetypes` does not know the extension -- so the entire
    typography of this app falls back with nothing in any log. And a cached
    bundle is a rebuild that does not appear.
    """
    from tonyagent.window.assets import AssetServer

    (tmp_path / "index.html").write_text("<html></html>", encoding="utf-8")
    (tmp_path / "font.woff2").write_bytes(b"\x00\x01")

    server = AssetServer(tmp_path)
    origin = server.start()
    try:
        with urllib.request.urlopen(f"{origin}/index.html", timeout=30) as page:
            assert page.status == 200
            assert page.headers["Cache-Control"] == "no-store"
        with urllib.request.urlopen(f"{origin}/font.woff2", timeout=30) as font:
            assert font.headers["Content-Type"] == "font/woff2"
    finally:
        server.stop()


def test_the_core_refuses_to_write_before_it_starts():
    """A write to a process that is not there is an error, not a no-op."""
    from tonyagent.window.core import CoreProcess

    core = CoreProcess([sys.executable, "-c", "pass"], lambda batch: None)

    with pytest.raises(RuntimeError):
        core.write("{}\n")
    assert core.alive is False


def test_the_core_adds_a_missing_frame_terminator():
    """A frame without its newline is a frame the core reads forever."""
    from tonyagent.window.core import CoreProcess

    written: list[str] = []

    class FakeStdin:
        def write(self, text: str) -> None:
            written.append(text)

        def flush(self) -> None:
            pass

    core = CoreProcess([sys.executable, "-c", "pass"], lambda batch: None)
    core._proc = type("Fake", (), {"stdin": FakeStdin()})()  # type: ignore[assignment]

    core.write('{"id": 1}')
    assert written == ['{"id": 1}\n']

    core.write('{"id": 2}\n')
    assert written[-1] == '{"id": 2}\n', "a terminator was added twice"


def test_the_host_finds_its_bundle_and_its_icon():
    """Both are walked up from the module, not taken from the working directory.

    The launcher is a double-clicked `.bat`, whose cwd is whatever the shell had,
    so a relative path would make the app work from one shortcut and not another.
    The icon is the artwork that used to live in `src-tauri/icons/`.
    """
    from tonyagent.window.host import app_icon, default_dist

    assert default_dist() == REPO / "app" / "dist"

    icon = app_icon()
    assert icon is not None, "the window has lost its icon"
    assert Path(icon).name == "icon.ico"
    assert Path(icon).is_file()


def test_the_window_is_created_with_a_dwm_frame(monkeypatch):
    """``shadow=True`` is what makes the corners roundable at all.

    pywebview's ``shadow`` is what calls ``DwmExtendFrameIntoClientArea``, and
    with no frame there is nothing for DWM to round: the corner preference is
    accepted and then ignored. Measured on the real window -- with
    ``shadow=False`` the style has no ``WS_CAPTION``, no ``WS_THICKFRAME`` and no
    ``WS_POPUP``, and ``DwmGetWindowAttribute`` reads the preference back as 0.

    Asserted here rather than in a window, because a window is what
    ``scripts/verify_corners.py`` is for. This is the flag that regression would
    flip, and nothing else in the tree reads it.
    """
    from tonyagent.window import host
    from tonyagent.window.bridge import Bridge

    captured: dict[str, object] = {}

    def fake_create_window(*args: object, **kwargs: object) -> None:
        captured.update(kwargs)
        return None

    monkeypatch.setattr(host.webview, "create_window", fake_create_window)
    host.build_window("http://127.0.0.1:1/index.html", Bridge())

    assert captured["shadow"] is True, "the window has no DWM frame to round"
    assert captured["frameless"] is True, "the OS drew a title bar"
    assert captured["easy_drag"] is False, "the whole window became a drag handle"


def test_the_styling_is_applied_when_the_window_is_shown(monkeypatch):
    """The late apply, which is the one that survives.

    Setting the attribute before the form is on screen is *accepted and then
    discarded*: DWM reports it back as 0 a moment later and the corners stay
    square. So ``_startup`` applies it immediately and again on ``shown``, and
    this asserts both happen -- the first is the one that used to be the only one.

    The frame rides along on the same hook, and for the same reason: the style
    and the window procedure are properties of a window handle, and there is no
    handle until the form exists. Both calls are idempotent, which is what makes
    the repeat harmless rather than a second, different application.
    """
    from tonyagent.window import host, win32

    applied: list[int] = []
    resized: list[int] = []
    installed: list[int] = []
    subscribed: list[str] = []
    monkeypatch.setattr(win32, "round_corners", applied.append)
    monkeypatch.setattr(win32, "make_resizable", resized.append)
    monkeypatch.setattr(win32, "install_frame", installed.append)

    class Events:
        def __init__(self) -> None:
            # pywebview's `EventContainer` hands out an `Event` per name; this
            # stands in for `shown` itself, so `events.shown += handler` lands on
            # `__iadd__` and the result is written back to the same attribute.
            self.shown = self

        def __iadd__(self, handler: object) -> "Events":
            subscribed.append("shown")
            handler()  # type: ignore[operator]
            return self

    class Handle:
        @staticmethod
        def ToInt64() -> int:
            return 4242

    # Built with `type` rather than declared as a class body, for both of these:
    # a name assigned inside a `class` block resolves in the *class* namespace,
    # not the enclosing function's, so `Handle = Handle` and `native = native`
    # are both NameErrors. The obvious spelling of each is wrong.
    native = type("Native", (), {"Handle": Handle})()
    window = type("FakeWindow", (), {"events": Events(), "native": native})()

    host._startup(window)  # type: ignore[arg-type]

    assert subscribed == ["shown"], "nothing is re-applied on `shown`"
    assert applied == [4242, 4242], (
        "the corners were not applied both immediately and on `shown`"
    )
    assert resized == [4242, 4242], "the window never got its frame bits"
    assert installed == [4242, 4242], "the window never got its own procedure"


def test_the_frame_bits_are_added_without_clearing_anything():
    """A pure function of the style word, so the bits are checked without a window.

    The style is the whole of "resizable": ``WS_THICKFRAME`` is what Windows
    grants resizing *and* snapping for, and a frameless window carries none of
    it. Asserted against the exact set the page's gestures need, because one bit
    short is a window that resizes and will not snap, or the reverse.
    """
    from tonyagent.window import win32

    wanted = (
        win32.WS_THICKFRAME | win32.WS_MAXIMIZEBOX | win32.WS_MINIMIZEBOX | win32.WS_SYSMENU
    )
    assert win32.frameless_resizable_style(0) == wanted
    # Idempotent, and it keeps whatever else the window already carries: this is
    # applied to a live window, not to a blank style word.
    assert win32.frameless_resizable_style(wanted) == wanted
    assert win32.frameless_resizable_style(0x00000001) == wanted | 0x00000001


def test_the_resize_edges_are_the_eight_a_page_can_name():
    """The map is the contract between `useWindowControls` and this module.

    The page sends one of these names and nothing else, so a name on one side
    and not the other is a resize that raises. Eight distinct codes, because a
    corner is its own hit test in Win32 and not two sides in sequence.
    """
    from tonyagent.window import win32

    assert sorted(win32.RESIZE_EDGES) == [
        "bottom",
        "bottom-left",
        "bottom-right",
        "left",
        "right",
        "top",
        "top-left",
        "top-right",
    ]
    assert len(set(win32.RESIZE_EDGES.values())) == 8


def test_a_resize_edge_is_refused_before_a_window_is_needed():
    """A bad edge is a bad edge whether or not there is a window to put it on.

    The bridge here has no window attached, so reaching for the handle would
    raise ``RuntimeError`` -- which is exactly why the edge is validated first.
    The order *is* the assertion.
    """
    from tonyagent.window.bridge import Bridge

    with pytest.raises(ValueError):
        Bridge().window_control("resize", "middle")


def test_window_control_refuses_an_action_that_is_not_one():
    from tonyagent.window.bridge import Bridge

    with pytest.raises(ValueError):
        Bridge().window_control("teleport")

def test_a_gesture_is_marshalled_onto_the_window_thread(monkeypatch):
    """The modal loop belongs to the window's thread, so the call is `Invoke`d.

    **Measured, and the reason the first version of this did nothing.** Issued
    from a pywebview worker thread, the `ReleaseCapture` in front of the call
    released the *worker's* own (empty) capture, the webview kept the mouse, and
    the loop never took -- the window did not move by a pixel under a real
    mouse. Marshalled onto the UI thread the same call moves it, snaps it to a
    half and maximizes it on a drag to the top.
    """
    pytest.importorskip("clr")

    from tonyagent.window import bridge as bridge_module
    from tonyagent.window.bridge import Bridge

    dragged: list[int] = []
    monkeypatch.setattr(bridge_module.win32, "begin_drag", dragged.append)

    class Handle:
        @staticmethod
        def ToInt64() -> int:
            return 4242

    class Native:
        def __init__(self) -> None:
            self.invoked = 0

        def Invoke(self, action: object) -> None:
            self.invoked += 1
            action()  # type: ignore[operator]

    native = Native()
    # After construction, not in the class body: a name assigned inside a `class`
    # block resolves in the *class* namespace, so `Handle = Handle` there is a
    # NameError -- the same trap the window test further down documents.
    native.Handle = Handle  # type: ignore[attr-defined]
    window = type("FakeWindow", (), {"native": native})()

    bridge = Bridge()
    bridge._attach(None, window)
    bridge.window_control("drag")

    assert dragged == [4242], "the gesture never reached Win32"
    assert native.invoked == 1, "the gesture was not marshalled onto the window thread"


def test_a_gesture_still_reaches_win32_with_no_window_thread_to_use(monkeypatch):
    """A backend with no WinForms control has no window thread to marshal to.

    The direct call is the fallback rather than an error: refusing would turn
    "this backend cannot drag" into "this backend raises".
    """
    from tonyagent.window import bridge as bridge_module
    from tonyagent.window.bridge import Bridge

    dragged: list[int] = []
    monkeypatch.setattr(bridge_module.win32, "begin_drag", dragged.append)

    class Handle:
        @staticmethod
        def ToInt64() -> int:
            return 4242

    native = type("Native", (), {"Handle": Handle})()
    bridge = Bridge()
    bridge._attach(None, type("FakeWindow", (), {"native": native})())
    bridge.window_control("drag")

    assert dragged == [4242]


def test_the_minimum_size_leaves_room_for_a_half_snap():
    """Windows honours the minimum, so a minimum wider than half the screen is a
    window that cannot be snapped to half the screen.

    Measured on a 1440x900 display through the real move loop: with the old
    900x600 minimum, a drag to the left edge came back 900 wide instead of 720 --
    the left half plus 180px of the right one. No amount of getting the gesture
    right was going to change that, which is why the number is pinned here.
    """
    from tonyagent.window.host import MIN_HEIGHT, MIN_WIDTH

    assert MIN_WIDTH <= 640, "wider than half of a 1280px display"
    assert MIN_HEIGHT <= 480, "taller than half of a 960px display"

@pytest.mark.skipif(sys.platform != "win32", reason="Win32 only")
def test_a_gesture_can_be_handed_to_a_window_that_is_not_there():
    """The ctypes signature, exercised without a window to drag.

    A null window returns from ``SendMessage`` at once, and that is all this
    needs: the failure it guards is a prototype that does not match the call, and
    that raises before Windows ever looks at the handle. Found the hard way -- the
    first version of this passed the hit-test code as a bare int to a prototype
    declared with ``WPARAM``, which is a type error at the call and a title bar
    that silently does nothing at runtime.
    """
    from tonyagent.window import win32

    win32.begin_drag(0)
    win32.begin_resize(0, "bottom-right")
    with pytest.raises(ValueError):
        win32.begin_resize(0, "middle")

@pytest.mark.skipif(sys.platform != "win32", reason="Win32 only")
def test_the_win32_prototypes_are_declared_with_their_types():
    """ctypes defaults an undeclared return to ``c_int``.

    ``GetSystemMenu`` returns a *handle*, so an undeclared ``restype`` truncates
    it to its low 32 bits on 64-bit Windows and every call after that is against
    a pointer that does not exist. It works on a 32-bit build and fails on the
    one that ships.
    """
    from tonyagent.window import win32

    win32._bind()
    user32 = ctypes.windll.user32  # type: ignore[attr-defined]

    assert user32.GetSystemMenu.restype is win32.wintypes.HMENU
    assert user32.TrackPopupMenu.restype is ctypes.c_uint
    assert user32.GetAncestor.restype is win32.wintypes.HWND
    assert user32.IsZoomed.restype is win32.wintypes.BOOL
    # The frame's own two, where the same mistake is worse than a truncated
    # handle: `SetWindowLongPtrW` *returns the previous procedure*, and a
    # ctypes-defaulted `c_int` truncates it to its low 32 bits -- so every
    # message after the first would be dispatched through a pointer that does not
    # exist.
    assert user32.CallWindowProcW.restype is win32.LRESULT
    assert user32.SendMessageW.restype is win32.LRESULT
    assert user32.SetWindowPos.restype is win32.wintypes.BOOL


@pytest.mark.skipif(sys.platform != "win32", reason="Win32 only")
def test_the_root_window_walk_survives_a_handle_it_cannot_place():
    """`GetAncestor` answers zero for a handle it does not know.

    Returning zero would then be passed to `GetSystemMenu`, which is a call on a
    null window -- so the walk falls back to the handle it was given and the
    failure stays where it belongs.
    """
    from tonyagent.window import win32

    assert win32.root_window(0) == 0
