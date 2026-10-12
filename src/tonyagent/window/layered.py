"""A window whose shape is its own pixels, instead of a region cut out of a rectangle.

The pet used to be a rectangle with a circular *region* taken out of it, which was
four attempts and a screenshot to get right. It worked, and then the screenshot still
showed a rectangle, because DWM paints a window's drop shadow to the window's
*rectangle* -- so the corners the region cut away were filled back in by the shadow.
That is fixed (`win32.no_shadow`), but it left the real problem: **a region clips, it
does not antialias.** The rim is a hard step, and there is nowhere to paint a shadow.

This is the alternative, and every claim in it was measured on this machine before it
was written down:

**Per-pixel alpha, with no transparency tricks.** `WS_EX_LAYERED` plus
`UpdateLayeredWindow(..., ULW_ALPHA)` and a 32-bit ARGB bitmap: every pixel of the
window carries its own coverage, so the rim blends and a shadow is just pixels at low
opacity. Measured over a backdrop: the row across the rim runs `21, 25, 32` -- a
partial-coverage pixel where a region would have cut.

**The region is kept, for input only.** It makes the corners click-through
(`WindowFromPoint` at a corner answers the window *behind*, measured) and it is never
visible: the alpha has already faded to nothing before its edge. Shape and hit-testing
are two different jobs and this is what each one is for.

**The drag is still the OS's.** `WM_NCHITTEST` answering `HTCAPTION` makes Windows run
its own move loop, so dragging is the OS's own behaviour -- measured over six real
drags, each bracketed by `WM_ENTERSIZEMOVE`/`WM_EXITSIZEMOVE`. A layered window was
said not to allow this and to need a custom drag loop; it does not.

**`WM_MOVING` goes to `DefWindowProc`.** That is the handler allowed to *change the
rect*, so answering "handled" there would silently switch snapping off.

**Click versus drag is the move loop's own return value.** `DefWindowProc` given the
`WM_NCLBUTTONDOWN` blocks for the whole gesture, so when it returns, comparing the
window's box answers "did it move" -- no timer, no threshold, and the same signal the
page-driven drag used to give us.

**The window is created on the thread that pumps it.** Win32 delivers a window's
messages to the thread that created it, so a window made on one thread and pumped on
another receives nothing at all -- which is exactly what the first prototype measured:
not one `WM_NCHITTEST`.

This module is deliberately pure ctypes: it draws nothing and knows nothing about the
pet. It takes a bitmap handle to blit, so the artwork can live somewhere else and be
tested without a window, and this can be tested without artwork.
"""

from __future__ import annotations

import ctypes
import sys
import threading
import time
from collections.abc import Callable
from ctypes import wintypes
from pathlib import Path
from typing import Any

from loguru import logger

from tonyagent.window.win32 import WindowsOnlyError

#: The window class is one per process: one procedure, and a lookup from the window
#: handle to the object that owns it (`_WINDOWS`).
WINDOW_CLASS = "TONYAgentCard"

#: Default card size. The pet is a badge, not a window.
SIZE = 180

WS_EX_LAYERED = 0x00080000
WS_EX_TOPMOST = 0x00000008
WS_EX_NOACTIVATE = 0x08000000
WS_EX_TOOLWINDOW = 0x00000080
WS_POPUP = 0x80000000
WS_VISIBLE = 0x10000000
SW_SHOWNOACTIVATE = 4
SWP_NOSIZE = 0x0001
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
ULW_ALPHA = 0x00000002
AC_SRC_OVER = 0x00
AC_SRC_ALPHA = 0x01
IDC_ARROW = 32512

WM_DESTROY = 0x0002
WM_CLOSE = 0x0010
WM_ERASEBKGND = 0x0014
WM_SETCURSOR = 0x0020
WM_NCHITTEST = 0x0084
WM_RBUTTONUP = 0x0205
WM_NCRBUTTONUP = 0x00A5
WM_MOVING = 0x0216
WM_ENTERSIZEMOVE = 0x0231
WM_EXITSIZEMOVE = 0x0232
WM_NCLBUTTONDOWN = 0x00A1

#: Our own message: "a frame is waiting in the queue". `WM_APP` is the first value
#: Windows leaves to the application.
WM_APP = 0x8000
WM_DRAW = WM_APP + 1

HTCAPTION = 2
HTCLIENT = 1

GWL_EXSTYLE = -20

#: Registry of live windows, so the one window procedure can find its object.
_WINDOWS: dict[int, LayeredWindow] = {}

#: The class procedures have to outlive their windows, and there is one per class.
_PROCS: dict[str, Any] = {}
_CLASSES: set[str] = set()
_CLASS_LOCK = threading.Lock()

#: True while the window is being dragged, so the cursor can be the closed hand.
_DRAGGING: set[int] = set()

if sys.platform == "win32":  # pragma: no cover - the branch is the platform check
    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32
    kernel32 = ctypes.windll.kernel32
else:  # pragma: no cover
    user32 = gdi32 = kernel32 = None  # type: ignore[assignment]

#: `WNDPROC`'s signature in the sizes Windows actually uses. `wintypes.WPARAM` and
#: `wintypes.LPARAM` are 32-bit here, and `lparam` is a pointer in some messages, so
#: using them overflows -- which is how the first prototype failed.
LRESULT = ctypes.c_ssize_t
WPARAM = ctypes.c_size_t
LPARAM = ctypes.c_ssize_t
HGDIOBJ = ctypes.c_void_p


class WNDCLASSEX(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.UINT),
        ("style", wintypes.UINT),
        ("lpfnWndProc", ctypes.c_void_p),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON),
        ("hCursor", wintypes.HANDLE),
        ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
        ("hIconSm", wintypes.HICON),
    ]


class BLENDFUNCTION(ctypes.Structure):
    _fields_ = [
        ("BlendOp", ctypes.c_byte),
        ("BlendFlags", ctypes.c_byte),
        ("SourceConstantAlpha", ctypes.c_byte),
        ("AlphaFormat", ctypes.c_byte),
    ]


def _bind() -> None:
    """Declare every prototype, because the defaults are wrong on 64-bit.

    An undeclared return is `c_int`, so `GetDC` would come back truncated to its low
    32 bits and every drawing call after it would be against a handle that does not
    exist. It works on a 32-bit build and fails on the one that ships.
    """
    kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
    kernel32.GetModuleHandleW.restype = wintypes.HMODULE

    user32.RegisterClassExW.argtypes = [ctypes.POINTER(WNDCLASSEX)]
    user32.RegisterClassExW.restype = wintypes.ATOM
    user32.CreateWindowExW.argtypes = [
        wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
        ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID,
    ]
    user32.CreateWindowExW.restype = wintypes.HWND
    user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, WPARAM, LPARAM]
    user32.DefWindowProcW.restype = LRESULT
    user32.LoadCursorW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR]
    user32.LoadCursorW.restype = wintypes.HANDLE
    user32.LoadImageW.argtypes = [
        wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT,
        ctypes.c_int, ctypes.c_int, wintypes.UINT,
    ]
    user32.LoadImageW.restype = wintypes.HANDLE
    user32.DestroyCursor.argtypes = [wintypes.HANDLE]
    user32.DestroyCursor.restype = wintypes.BOOL
    user32.SetCursor.argtypes = [wintypes.HANDLE]
    user32.SetCursor.restype = wintypes.HANDLE
    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.ShowWindow.restype = wintypes.BOOL
    user32.DestroyWindow.argtypes = [wintypes.HWND]
    user32.DestroyWindow.restype = wintypes.BOOL
    user32.PostQuitMessage.argtypes = [ctypes.c_int]
    user32.PostQuitMessage.restype = None
    user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, WPARAM, LPARAM]
    user32.PostMessageW.restype = wintypes.BOOL
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.GetWindowRect.restype = wintypes.BOOL
    user32.SetWindowRgn.argtypes = [wintypes.HWND, ctypes.c_void_p, wintypes.BOOL]
    user32.SetWindowRgn.restype = ctypes.c_int
    user32.SetWindowPos.argtypes = [
        wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
        ctypes.c_int, ctypes.c_int, wintypes.UINT,
    ]
    user32.SetWindowPos.restype = wintypes.BOOL
    user32.GetDC.argtypes = [wintypes.HWND]
    user32.GetDC.restype = wintypes.HDC
    user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
    user32.ReleaseDC.restype = ctypes.c_int
    user32.UpdateLayeredWindow.argtypes = [
        wintypes.HWND, wintypes.HDC, ctypes.POINTER(wintypes.POINT),
        ctypes.POINTER(wintypes.SIZE), wintypes.HDC, ctypes.POINTER(wintypes.POINT),
        wintypes.DWORD, ctypes.POINTER(BLENDFUNCTION), wintypes.DWORD,
    ]
    user32.UpdateLayeredWindow.restype = wintypes.BOOL
    user32.GetMessageW.argtypes = [
        ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT
    ]
    user32.GetMessageW.restype = ctypes.c_int
    user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
    user32.TranslateMessage.restype = wintypes.BOOL
    user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
    user32.DispatchMessageW.restype = LRESULT

    gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
    gdi32.CreateCompatibleDC.restype = wintypes.HDC
    gdi32.SelectObject.argtypes = [wintypes.HDC, HGDIOBJ]
    gdi32.SelectObject.restype = HGDIOBJ
    gdi32.DeleteDC.argtypes = [wintypes.HDC]
    gdi32.DeleteDC.restype = wintypes.BOOL
    gdi32.DeleteObject.argtypes = [HGDIOBJ]
    gdi32.DeleteObject.restype = wintypes.BOOL
    gdi32.CreateEllipticRgn.argtypes = [ctypes.c_int] * 4
    gdi32.CreateEllipticRgn.restype = ctypes.c_void_p


def _window_proc(hwnd: int, message: int, wparam: int, lparam: int) -> int:
    """The one window procedure, dispatching to the object that owns `hwnd`."""
    window = _WINDOWS.get(hwnd)
    if window is None:
        return user32.DefWindowProcW(hwnd, message, wparam, lparam)
    try:
        return window.handle_message(hwnd, message, wparam, lparam)
    except Exception as exc:  # noqa: BLE001 - a pet must not take the app down
        logger.warning(f"The card's window procedure failed on {message:#x}: {exc}")
        return user32.DefWindowProcW(hwnd, message, wparam, lparam)


class LayeredWindow:
    """A frameless, topmost, never-activating window drawn from an ARGB bitmap.

    Blits are asynchronous but *ordered*: `draw` returns once the frame is on screen,
    so a caller can draw once and know the card is showing it. Nothing is scheduled
    between calls -- no timer, no animation loop -- which is what keeps an idle card
    at zero cost.
    """

    def __init__(
        self,
        *,
        size: tuple[int, int] = (SIZE, SIZE),
        at: tuple[int, int] = (0, 0),
        title: str = "TONYAgent",
        draggable: bool = True,
        on_drag: Callable[[int, int], None] | None = None,
        on_click: Callable[[], None] | None = None,
        on_context: Callable[[], None] | None = None,
    ) -> None:
        self.size = size
        self.at = at
        self.title = title
        self.draggable = draggable
        self.on_drag = on_drag
        self.on_click = on_click
        self.on_context = on_context

        self._hwnd = 0
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._queue: list[tuple[int, threading.Event | None]] = []
        self._queue_lock = threading.Lock()
        self._cursors: dict[str, int] = {}
        self._gesture_start: tuple[int, int] | None = None
        # True while a press is inside the OS move loop, so the two places that can
        # report a finished gesture do not both report the same one.
        self._press_active = False

    # -- lifecycle -------------------------------------------------------------

    def open(self, timeout: float = 5.0) -> bool:
        """Create the window on its own thread. True once it exists."""
        if sys.platform != "win32":
            raise WindowsOnlyError("a layered window is Win32")
        if self.is_open():
            return True
        self._ready.clear()
        self._thread = threading.Thread(
            target=self._run, name="tonyagent-card", daemon=True
        )
        self._thread.start()
        return self._ready.wait(timeout) and self.is_open()

    def close(self) -> None:
        """Ask the window to go away and wait for its thread to finish."""
        hwnd = self._hwnd
        if hwnd:
            user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
        # A callback on the window's own thread may close the card, and a thread
        # cannot join itself -- so only wait for a thread that is not this one.
        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join(timeout=3.0)
        self._thread = None
        self._hwnd = 0
        self._ready.clear()

    def is_open(self) -> bool:
        return bool(self._hwnd) and self._thread is not None and self._thread.is_alive()

    # -- drawing ---------------------------------------------------------------

    def draw(self, hbitmap: int) -> bool:
        """Put `hbitmap` on screen, centred in the window's box.

        The bitmap is the caller's: this does not keep it, because
        `UpdateLayeredWindow` copies it into the window's own surface. Returns False
        if the window is not up.
        """
        if not self.is_open():
            return False
        if threading.current_thread() is self._thread:
            return self._blit(self._hwnd, hbitmap)
        done = threading.Event()
        with self._queue_lock:
            self._queue.append((hbitmap, done))
        user32.PostMessageW(self._hwnd, WM_DRAW, 0, 0)
        return done.wait(2.0)

    def position(self) -> tuple[int, int]:
        """Where the window is now, per the OS -- the only authority on it."""
        hwnd = self._hwnd
        if not hwnd:
            return self.at
        box = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(box))
        return (box.left, box.top)

    def set_position(self, x: int, y: int) -> None:
        if self._hwnd:
            user32.SetWindowPos(
                self._hwnd, None, x, y, 0, 0,
                SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE,
            )

    # -- messages --------------------------------------------------------------

    def handle_message(self, hwnd: int, message: int, wparam: int, lparam: int) -> int:
        """Answer one message. Public so it can be tested without a window."""
        if message == WM_NCHITTEST:
            # **The whole drag.** This asks Windows to run its own move loop, so
            # dragging and snapping are the OS's behaviour rather than an imitation.
            return HTCAPTION if self.draggable else HTCLIENT
        if message == WM_SETCURSOR:
            self._set_cursor(hwnd)
            return 1
        if message == WM_ENTERSIZEMOVE:
            _DRAGGING.add(hwnd)
            self._gesture_start = self._box(hwnd)
            return 0
        if message == WM_MOVING:
            # Keep the closed hand for the duration. Note the return: `WM_MOVING`
            # must reach `DefWindowProc`, because that is what may **change the
            # rect** -- answering "handled" here would switch snapping off.
            handle = self._cursors.get("grabbing")
            if handle:
                user32.SetCursor(handle)
            return user32.DefWindowProcW(hwnd, message, wparam, lparam)
        if message == WM_EXITSIZEMOVE:
            _DRAGGING.discard(hwnd)
            # A gesture that began as a press is reported by the press path, and it
            # reports *after* this message has arrived -- the loop sends this one
            # before returning. So this is only for a move the OS began without us.
            if not self._press_active:
                self._finish_gesture(hwnd)
            return 0
        if message == WM_NCLBUTTONDOWN and self.draggable:
            # **Blocking: this call *is* the gesture**, and its return is the answer
            # to "did the window move" -- the same signal the page-driven drag gave
            # us. So the click *and* the drag are both reported from here, because
            # this is the one place that knows the loop has finished and where it
            # left the window.
            start = self._box(hwnd)
            self._press_active = True
            try:
                result = user32.DefWindowProcW(hwnd, message, wparam, lparam)
            finally:
                self._press_active = False
            ended = self._box(hwnd)
            self._gesture_start = None
            if ended == start:
                self._click()
            else:
                self._report_drag(ended)
            return result
        if message in (WM_RBUTTONUP, WM_NCRBUTTONUP):
            self._context()
            return 0
        if message == WM_DRAW:
            self._drain()
            return 0
        if message == WM_CLOSE:
            user32.DestroyWindow(hwnd)
            return 0
        if message == WM_DESTROY:
            _WINDOWS.pop(hwnd, None)
            _DRAGGING.discard(hwnd)
            self._hwnd = 0
            user32.PostQuitMessage(0)
            return 0
        if message == WM_ERASEBKGND:
            # A layered window that erases its own background paints over the alpha
            # it was given, and the transparency is gone.
            return 1
        return user32.DefWindowProcW(hwnd, message, wparam, lparam)

    def _set_cursor(self, hwnd: int) -> None:
        """The hand, because a window with no frame has no other affordance."""
        name = "grabbing" if hwnd in _DRAGGING else "grab"
        handle = self._cursors.get(name) or self._cursors.get("grab")
        if handle:
            user32.SetCursor(handle)

    def _finish_gesture(self, hwnd: int) -> None:
        """Report where a finished gesture left the card, if it moved it."""
        ended = self._box(hwnd)
        if self._gesture_start is not None and ended != self._gesture_start:
            self._report_drag(ended)
        self._gesture_start = None

    def _report_drag(self, at: tuple[int, int]) -> None:
        if self.on_drag:
            self.on_drag(*at)

    def _click(self) -> None:
        if self.on_click:
            self.on_click()

    def _context(self) -> None:
        if self.on_context:
            self.on_context()

    # -- internals -------------------------------------------------------------

    def _run(self) -> None:
        """The window's thread: create it here, and pump it here."""
        _bind()
        proc = _class_proc()
        hwnd = user32.CreateWindowExW(
            WS_EX_LAYERED | WS_EX_TOPMOST | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW,
            WINDOW_CLASS,
            self.title,
            WS_POPUP | WS_VISIBLE,
            self.at[0], self.at[1], self.size[0], self.size[1],
            None, None, kernel32.GetModuleHandleW(None), None,
        )
        if not hwnd:
            logger.warning(f"The card's window could not be created: {ctypes.GetLastError()}")
            self._ready.set()
            return
        self._hwnd = int(hwnd)
        _WINDOWS[self._hwnd] = self
        self._cursors = _load_cursors()
        # Input only: the alpha has already faded to nothing before this edge, so it
        # is invisible, and it is what makes the corners click-through.
        _mask_to_card(self._hwnd, self.size)
        user32.ShowWindow(self._hwnd, SW_SHOWNOACTIVATE)
        self._ready.set()
        assert proc is not None

        message = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(message))
            user32.DispatchMessageW(ctypes.byref(message))
        self._forget_cursors()

    def _drain(self) -> None:
        """Run the queued blits, on the thread that owns the window."""
        while True:
            with self._queue_lock:
                if not self._queue:
                    return
                hbitmap, done = self._queue.pop(0)
            try:
                self._blit(self._hwnd, hbitmap)
            finally:
                if done is not None:
                    done.set()

    def _blit(self, hwnd: int, hbitmap: int) -> bool:
        """`UpdateLayeredWindow`: the frame *is* the window's shape and position."""
        screen = user32.GetDC(None)
        memory = gdi32.CreateCompatibleDC(screen)
        previous = gdi32.SelectObject(memory, hbitmap)
        size = wintypes.SIZE(*self.size)
        source = wintypes.POINT(0, 0)
        destination = wintypes.POINT(*self.position())
        blend = BLENDFUNCTION(AC_SRC_OVER, 0, 255, AC_SRC_ALPHA)
        ok = user32.UpdateLayeredWindow(
            hwnd, screen, ctypes.byref(destination), ctypes.byref(size),
            memory, ctypes.byref(source), 0, ctypes.byref(blend), ULW_ALPHA,
        )
        gdi32.SelectObject(memory, previous)
        gdi32.DeleteDC(memory)
        user32.ReleaseDC(None, screen)
        if not ok:
            logger.warning(
                f"The card's frame was refused: {ctypes.GetLastError()}"
            )
        return bool(ok)

    def _box(self, hwnd: int) -> tuple[int, int]:
        return _box(hwnd)

    def _forget_cursors(self) -> None:
        for handle in self._cursors.values():
            if handle:
                user32.DestroyCursor(handle)
        self._cursors = {}


def _box(hwnd: int) -> tuple[int, int]:
    box = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(box))
    return (box.left, box.top)


def _class_proc() -> Any:
    """Register the class once, keeping the procedure alive for the process."""
    with _CLASS_LOCK:
        if WINDOW_CLASS not in _CLASSES:
            proc = ctypes.WINFUNCTYPE(
                LRESULT, wintypes.HWND, wintypes.UINT, WPARAM, LPARAM
            )(_window_proc)
            _PROCS[WINDOW_CLASS] = proc
            description = WNDCLASSEX()
            description.cbSize = ctypes.sizeof(WNDCLASSEX)
            description.lpfnWndProc = ctypes.cast(proc, ctypes.c_void_p)
            description.hInstance = kernel32.GetModuleHandleW(None)
            description.hCursor = user32.LoadCursorW(None, wintypes.LPCWSTR(IDC_ARROW))
            description.lpszClassName = WINDOW_CLASS
            if not user32.RegisterClassExW(ctypes.byref(description)):
                logger.warning(
                    f"The card's window class was refused: {ctypes.GetLastError()}"
                )
            _CLASSES.add(WINDOW_CLASS)
        return _PROCS.get(WINDOW_CLASS)


def _mask_to_card(hwnd: int, size: tuple[int, int]) -> None:
    """Elliptic input region the size of the card, so the corners fall through."""
    region = gdi32.CreateEllipticRgn(0, 0, size[0], size[1])
    if region:
        user32.SetWindowRgn(hwnd, region, True)


def _load_cursors(directory: Path | None = None) -> dict[str, int]:
    """The `grab`/`grabbing` pair, as 32-bit alpha cursors.

    They are files rather than `CreateCursor` calls for one reason: `CreateCursor`
    takes bitmasks, so its cursors are 1-bit and jagged, while a `.cur` read with
    `LoadImageW` may carry an alpha channel -- the same trick as the window itself.
    A missing file is not an error: the card simply keeps the arrow.
    """
    here = directory or Path(__file__).with_name("cursors")
    wanted = {"grab": "grab.cur", "grabbing": "grabbing.cur"}
    found: dict[str, int] = {}
    for name, filename in wanted.items():
        path = here / filename
        if not path.is_file():
            logger.debug(f"No {filename}; the card keeps the default cursor.")
            continue
        handle = user32.LoadImageW(None, str(path), 2, 0, 0, 0x00000010)
        if handle:
            found[name] = handle
    return found
