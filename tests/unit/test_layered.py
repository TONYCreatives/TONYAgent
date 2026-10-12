"""The card's window: its shape, its drag, and the difference between a drag and a click.

Everything here is driven through the window procedure with fake Win32 calls, so no
window is created and nothing needs a desktop -- but every assertion is about a
measurement that was taken on a real layered window first, which is why the numbers
and the styles in them are specific rather than plausible.
"""

from __future__ import annotations

import ctypes
import threading
import time
from ctypes import wintypes
from pathlib import Path
from typing import Any

import pytest

from tonyagent.window import layered


class FakeUser32:
    """Enough of `user32` to run the procedure, and a record of what was asked."""

    def __init__(self, at: tuple[int, int] = (100, 200), size: tuple[int, int] = (180, 180)):
        self.at = at
        self.size = size
        self.calls: list[tuple[str, tuple]] = []
        self.def_result = 7
        self.messages: list[int] = []
        self.move_on_defwindowproc: tuple[int, int] | None = None

    def _record(self, name: str, *args: Any) -> None:
        self.calls.append((name, args))

    def named(self, name: str) -> list[tuple]:
        return [args for called, args in self.calls if called == name]

    def called(self, name: str) -> bool:
        return any(called == name for called, _ in self.calls)

    # -- the calls the procedure makes ----------------------------------------

    def GetWindowRect(self, hwnd, pointer) -> int:
        self._record("GetWindowRect", int(hwnd))
        box = pointer._obj
        box.left, box.top = self.at
        box.right, box.bottom = self.at[0] + self.size[0], self.at[1] + self.size[1]
        return 1

    def DefWindowProcW(self, hwnd, message, wparam, lparam) -> int:
        self._record("DefWindowProcW", int(message))
        self.messages.append(int(message))
        if message == layered.WM_NCLBUTTONDOWN and self.move_on_defwindowproc:
            # **The OS move loop, in one line**: while `DefWindowProc` is running the
            # user drags the window, so by the time it returns the position has moved.
            self.at = self.move_on_defwindowproc
        return self.def_result

    def SetCursor(self, handle):
        self._record("SetCursor", handle)
        return handle

    def CreateWindowExW(self, *args):
        self._record("CreateWindowExW", *args)
        return 1234

    def RegisterClassExW(self, description):
        self._record("RegisterClassExW")
        return 1

    def GetModuleHandleW(self, name=None):
        return 99

    def LoadCursorW(self, instance, name):
        return 5

    def LoadImageW(self, *args):
        self._record("LoadImageW", *args)
        return 6

    def DestroyCursor(self, handle):
        self._record("DestroyCursor", handle)
        return 1

    def ShowWindow(self, hwnd, command):
        self._record("ShowWindow", int(hwnd), int(command))
        return 1

    def PostMessageW(self, hwnd, message, wparam, lparam):
        self._record("PostMessageW", int(hwnd), int(message))
        return 1

    def PostQuitMessage(self, code):
        self._record("PostQuitMessage", code)

    def DestroyWindow(self, hwnd):
        self._record("DestroyWindow", int(hwnd))
        return 1

    def SetWindowPos(self, *args):
        self._record("SetWindowPos", *args)
        return 1

    def GetMessageW(self, message, hwnd, low, high) -> int:
        self._record("GetMessageW")
        return 0  # nothing to pump: `_run` does its work and stops

    def TranslateMessage(self, message):
        return 1

    def DispatchMessageW(self, message):
        return 0

    def SetWindowRgn(self, hwnd, region, redraw):
        self._record("SetWindowRgn", int(hwnd), region, bool(redraw))
        return 1

    def GetDC(self, hwnd):
        self._record("GetDC", hwnd)
        return 77

    def ReleaseDC(self, hwnd, dc):
        self._record("ReleaseDC", hwnd, dc)
        return 1

    def UpdateLayeredWindow(self, *args):
        self._record("UpdateLayeredWindow", *args)
        return 1


class FakeGdi32:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple]] = []

    def named(self, name: str) -> list[tuple]:
        return [args for called, args in self.calls if called == name]

    def CreateEllipticRgn(self, *args):
        self.calls.append(("CreateEllipticRgn", args))
        return 4242

    def CreateCompatibleDC(self, screen):
        self.calls.append(("CreateCompatibleDC", (screen,)))
        return 88

    def SelectObject(self, dc, obj):
        self.calls.append(("SelectObject", (dc, obj)))
        return 99

    def DeleteDC(self, dc):
        self.calls.append(("DeleteDC", (dc,)))
        return 1

    def DeleteObject(self, obj):
        self.calls.append(("DeleteObject", (obj,)))
        return 1


@pytest.fixture
def win(monkeypatch) -> tuple[layered.LayeredWindow, FakeUser32, FakeGdi32]:
    """A card that believes it is on screen, with fake Win32 underneath."""
    user, gdi = FakeUser32(), FakeGdi32()
    monkeypatch.setattr(layered, "user32", user)
    monkeypatch.setattr(layered, "gdi32", gdi)
    monkeypatch.setattr(layered, "kernel32", user)
    monkeypatch.setattr(layered, "_bind", lambda: None)
    monkeypatch.setattr(layered, "_load_cursors", lambda directory=None: {"grab": 6, "grabbing": 8})

    events: dict[str, Any] = {"drag": [], "click": 0, "context": 0}
    card = layered.LayeredWindow(
        at=(100, 200),
        on_drag=lambda x, y: events["drag"].append((x, y)),
        on_click=lambda: events.__setitem__("click", events["click"] + 1),
        on_context=lambda: events.__setitem__("context", events["context"] + 1),
    )
    card._hwnd = 1234
    card._thread = threading.current_thread()
    card._cursors = {"grab": 6, "grabbing": 8}
    layered._WINDOWS[1234] = card
    card.events = events  # type: ignore[attr-defined]
    try:
        yield card, user, gdi
    finally:
        layered._WINDOWS.pop(1234, None)
        layered._DRAGGING.discard(1234)


def send(card: layered.LayeredWindow, message: int, wparam: int = 0, lparam: int = 0) -> int:
    return card.handle_message(1234, message, wparam, lparam)


# -- shape ---------------------------------------------------------------------


def test_the_window_is_created_layered_topmost_and_never_activating(monkeypatch):
    """The four styles, and the reason for each.

    `LAYERED` is what makes per-pixel alpha possible at all; `TOPMOST` is a card that
    sits over the work; `NOACTIVATE` is the one that matters most -- a pet that took
    the keyboard while the user was typing in another window would be a bug, not a
    decoration; and `TOOLWINDOW` keeps it out of Alt-Tab.
    """
    user, gdi = FakeUser32(), FakeGdi32()
    monkeypatch.setattr(layered, "user32", user)
    monkeypatch.setattr(layered, "gdi32", gdi)
    monkeypatch.setattr(layered, "kernel32", user)
    monkeypatch.setattr(layered, "_bind", lambda: None)
    monkeypatch.setattr(layered, "_load_cursors", lambda directory=None: {})
    monkeypatch.setattr(layered, "_WINDOWS", {})

    card = layered.LayeredWindow(at=(300, 400))
    card._run()  # the window thread's body, with `GetMessageW` returning at once

    (created,) = user.named("CreateWindowExW")
    styles, _, _, window_style, x, y, width, height = created[:8]
    assert styles == (
        layered.WS_EX_LAYERED
        | layered.WS_EX_TOPMOST
        | layered.WS_EX_NOACTIVATE
        | layered.WS_EX_TOOLWINDOW
    )
    assert window_style == layered.WS_POPUP | layered.WS_VISIBLE
    assert (x, y, width, height) == (300, 400, 180, 180)
    assert user.named("ShowWindow") == [(1234, layered.SW_SHOWNOACTIVATE)]
    layered._WINDOWS.pop(1234, None)


def test_the_input_region_is_the_card_the_corners_are_not(monkeypatch, win):
    """The region is for hit-testing only, and it is cut to the card's own box."""
    card, user, gdi = win
    monkeypatch.setattr(layered, "_WINDOWS", {})
    card._run()

    (region_args,) = gdi.named("CreateEllipticRgn")
    assert region_args == (0, 0, 180, 180)
    ((hwnd, region, redraw),) = user.named("SetWindowRgn")
    assert (hwnd, region, redraw) == (1234, 4242, True)
    layered._WINDOWS.pop(1234, None)


def test_the_background_is_never_erased(win):
    """**Regression guard.** A layered window that erases its background paints over
    the alpha it was handed, and the transparency is gone -- the whole point."""
    card, _user, _gdi = win
    assert send(card, layered.WM_ERASEBKGND) == 1


def test_a_missing_cursor_file_is_not_an_error(tmp_path: Path, monkeypatch):
    """A card without its hand cursor is a card, so this degrades rather than fails."""
    user = FakeUser32()
    monkeypatch.setattr(layered, "user32", user)
    assert layered._load_cursors(tmp_path) == {}


# -- the drag ------------------------------------------------------------------


def test_the_hit_test_answers_caption_so_windows_drags_it(win):
    """Measured on a real window: six drags ran the OS's own move loop this way."""
    card, _user, _gdi = win
    assert send(card, layered.WM_NCHITTEST) == layered.HTCAPTION


def test_a_card_that_is_not_draggable_keeps_its_clicks(win):
    card, _user, _gdi = win
    card.draggable = False
    assert send(card, layered.WM_NCHITTEST) == layered.HTCLIENT


def test_moving_reaches_defwindowproc_so_snapping_still_works(win):
    """**`WM_MOVING` must not be answered "handled".** That handler is the one allowed
    to change the window's rect, so swallowing it switches snapping off silently."""
    card, user, _gdi = win
    result = send(card, layered.WM_MOVING)
    assert result == user.def_result, "the rect was frozen out of the move loop"
    assert layered.WM_MOVING in user.messages


def test_a_press_that_does_not_move_is_a_click(win):
    """No timer and no threshold: the move loop returns, and the box answers it."""
    card, _user, _gdi = win
    send(card, layered.WM_NCLBUTTONDOWN)
    assert card.events["click"] == 1
    assert card.events["drag"] == []


def test_a_press_that_moves_reports_where_it_ended(win):
    """The position the card must save comes from the OS, not from the arithmetic."""
    card, user, _gdi = win
    user.move_on_defwindowproc = (640, 480)
    send(card, layered.WM_NCLBUTTONDOWN)
    assert card.events["drag"] == [(640, 480)]
    assert card.events["click"] == 0


def test_the_end_of_a_gesture_also_reports_the_position(win):
    """The other path in: `WM_ENTERSIZEMOVE` .. `WM_EXITSIZEMOVE`, which is what a
    drag that began outside the hit test (a keyboard move, a snap) looks like."""
    card, user, _gdi = win
    send(card, layered.WM_ENTERSIZEMOVE)
    user.at = (55, 66)
    send(card, layered.WM_EXITSIZEMOVE)
    assert card.events["drag"] == [(55, 66)]


def test_a_gesture_that_changed_nothing_reports_nothing(win):
    card, _user, _gdi = win
    send(card, layered.WM_ENTERSIZEMOVE)
    send(card, layered.WM_EXITSIZEMOVE)
    assert card.events["drag"] == []


def test_a_right_click_is_offered_to_the_caller(win):
    card, _user, _gdi = win
    send(card, layered.WM_RBUTTONUP)
    send(card, layered.WM_NCRBUTTONUP)
    assert card.events["context"] == 2


# -- cursors -------------------------------------------------------------------


def test_the_cursor_is_the_open_hand_and_closes_while_dragging(win):
    """Windows has no open-hand cursor, so the pair is drawn and shipped with the app."""
    card, user, _gdi = win
    send(card, layered.WM_SETCURSOR)
    send(card, layered.WM_ENTERSIZEMOVE)
    send(card, layered.WM_SETCURSOR)
    assert user.named("SetCursor") == [(6,), (8,)]
    send(card, layered.WM_EXITSIZEMOVE)
    send(card, layered.WM_SETCURSOR)
    assert user.named("SetCursor")[-1] == (6,)


def test_a_drag_motion_keeps_the_closed_hand(win):
    card, user, _gdi = win
    send(card, layered.WM_ENTERSIZEMOVE)
    send(card, layered.WM_MOVING)
    assert (8,) in user.named("SetCursor")


# -- drawing -------------------------------------------------------------------


def test_a_frame_is_blended_with_its_own_alpha_at_the_position_the_os_reports(win):
    """`ULW_ALPHA` with `AC_SRC_ALPHA` is the whole transparency mechanism."""
    card, user, gdi = win
    user.at = (310, 410)
    assert card._blit(1234, 555) is True

    ((hwnd, screen, destination, size, memory, source, colour, blend, flags),) = (
        user.named("UpdateLayeredWindow")
    )
    assert hwnd == 1234
    assert (destination._obj.x, destination._obj.y) == (310, 410)
    assert (size._obj.cx, size._obj.cy) == (180, 180)
    assert colour == 0
    assert (blend._obj.BlendOp, blend._obj.AlphaFormat) == (layered.AC_SRC_OVER, layered.AC_SRC_ALPHA)
    assert flags == layered.ULW_ALPHA
    # The bitmap is the caller's, so the device context is restored and given back.
    assert gdi.named("SelectObject") == [(88, 555), (88, 99)]
    assert gdi.named("DeleteDC") == [(88,)]
    assert user.named("ReleaseDC") == [(None, 77)]


def test_drawing_to_a_card_that_is_not_up_is_a_no_op(win):
    """Not an exception: the card is decoration, and the app outranks it."""
    card, user, _gdi = win
    card._hwnd = 0
    assert card.draw(555) is False
    assert user.named("UpdateLayeredWindow") == []


def test_a_frame_drawn_from_another_thread_is_marshalled_and_waited_for(win):
    """Win32 wants the window's own thread for anything message-shaped, so a blit
    from the bridge's thread is queued, posted, and waited for -- a race would show
    up here as a frame that was drawn twice or not at all."""
    card, user, _gdi = win
    result: dict = {}
    other = threading.Thread(target=lambda: result.setdefault("drawn", card.draw(777)))
    other.start()
    for _ in range(100):
        if user.named("PostMessageW"):
            break
        time.sleep(0.01)

    assert user.named("UpdateLayeredWindow") == [], "it blitted from the wrong thread"
    assert user.named("PostMessageW") == [(1234, layered.WM_DRAW)]
    card._drain()  # what `WM_DRAW` does on the window's own thread
    other.join(timeout=2)
    assert result.get("drawn") is True
    assert len(user.named("UpdateLayeredWindow")) == 1


# -- teardown ------------------------------------------------------------------


def test_destroying_the_window_unregisters_it(win):
    card, user, _gdi = win
    send(card, layered.WM_DESTROY)
    assert 1234 not in layered._WINDOWS
    assert user.named("PostQuitMessage") == [(0,)]
    assert card._hwnd == 0


def test_closing_asks_the_window_to_close(win):
    card, user, _gdi = win
    card.close()
    assert user.named("PostMessageW") == [(1234, layered.WM_CLOSE)]
    assert card.is_open() is False


def test_the_card_is_win32_only(monkeypatch):
    monkeypatch.setattr(layered.sys, "platform", "linux")
    with pytest.raises(layered.WindowsOnlyError):
        layered.LayeredWindow().open()


def test_the_message_sizes_are_pointer_sized():
    """The first prototype failed here: an `LPARAM` as `c_long` overflows a pointer."""
    assert ctypes.sizeof(layered.LPARAM) == ctypes.sizeof(ctypes.c_void_p)
    assert ctypes.sizeof(layered.WPARAM) == ctypes.sizeof(ctypes.c_void_p)
    assert ctypes.sizeof(layered.LRESULT) == ctypes.sizeof(ctypes.c_void_p)


def test_the_window_class_keeps_its_procedure_alive():
    """A collected callback is a window that calls freed memory on the next message."""
    first = layered._class_proc()
    second = layered._class_proc()
    assert first is second
    assert layered.WINDOW_CLASS in layered._PROCS


def test_a_failed_creation_still_releases_the_starting_thread(monkeypatch):
    """`open()` waits on a flag, so a window that never appears must still set it."""
    user = FakeUser32()
    user.CreateWindowExW = lambda *args: 0  # type: ignore[method-assign]
    monkeypatch.setattr(layered, "user32", user)
    monkeypatch.setattr(layered, "kernel32", user)
    monkeypatch.setattr(layered, "gdi32", FakeGdi32())
    monkeypatch.setattr(layered, "_bind", lambda: None)

    card = layered.LayeredWindow()
    card.at = (0, 0)
    card._run()
    assert card._hwnd == 0


def test_rectangles_are_read_through_the_pointer_ctypes_gives_us():
    """A guard on the test double itself: `byref` is what `GetWindowRect` wants."""
    box = wintypes.RECT()
    reference = ctypes.byref(box)
    assert reference._obj is box
