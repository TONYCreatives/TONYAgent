"""The three things about the window that markup cannot draw.

Ported from the Rust shell this replaces, with its reasoning intact, because the
reasoning was the expensive part:

**Rounded corners are a window attribute, not a CSS radius.** A radius on ``body``
needs a transparent window for the corner to be visible through -- the corner
outside the radius is painted by whatever is *behind* the window, and an opaque
window has nothing behind it but its own background. Turning the window
transparent to get there puts the whole window on the layered path, where the
drop shadow, the resize borders and the compositor's own corner masking all
change behaviour. Asking DWM keeps an ordinary opaque window and gets exactly
the corners every other Windows 11 window has, including the radius Windows
scales for the monitor's DPI. ``DWMWCP_ROUND`` rather than ``_ROUNDSMALL``: the
small radius is what dialogs get and this is an application window. A failure is
logged, not fatal -- the plausible reason is a Windows that predates the
attribute, and square corners are cosmetic.

**The system menu is the OS's own, not a rebuilt one.** An undecorated window
still carries ``WS_SYSMENU``, so the OS is still holding a real menu with
Restore, Move, Size, Minimize, Maximize and Close on it, each already carrying
the enabled state that belongs to it. Building that menu here would mean
reimplementing those rules and getting the two greyed-out items subtly wrong.
Move and Size then come back as the system's own loops -- arrow keys and all --
instead of a drag this app would have to reimplement.

**``IsZoomed`` rather than bookkeeping.** The maximized flag has one authority,
and it is the window. Tracking it from events means a state machine that is
wrong the first time the user maximizes by dragging to the screen edge, which is
a gesture the app never hears about as a button press.

**The gestures are the OS's, not this program's.** A window with no frame cannot
be resized, and -- the part that is easy to miss -- it cannot be *snapped*
either: Aero Snap, the drag-to-the-top maximize and the half-screen tiles are
all behaviour the OS attaches to ``WS_THICKFRAME``, and a frameless window does
not carry it. So the window is given the style and answers ``WM_NCCALCSIZE``
with "the client area is the whole window": resizable, and still drawing no
frame of its own.

What *starts* a gesture is still the page, because the page is the only thing
that knows where the title bar and the edges are. It asks, and this module hands
the request to the OS as ``WM_NCLBUTTONDOWN`` with a hit-test code. From there
the move and sizing loops are Windows' own -- the same ones a decorated window
runs -- which is what makes snapping, the top-edge maximize and the drag
previews work rather than being imitated. The loop is modal and belongs to the
window's thread, so ``SendMessage`` is where this call sits until the user lets
go of the mouse; the caller is a pywebview worker thread and the window goes on
painting throughout.

Every prototype is declared with its argument and return types. That is not
tidiness: ctypes defaults an undeclared return to ``c_int``, and ``GetSystemMenu``
returns a *handle* -- so on 64-bit Windows the menu would come back truncated to
its low 32 bits and every call after it would be against a pointer that does not
exist. It works on a 32-bit build and fails on the one that ships.
"""

from __future__ import annotations

import ctypes
import sys
import time
from collections.abc import Callable
from ctypes import wintypes
from typing import Any

from loguru import logger

#: ``DWMWA_WINDOW_CORNER_PREFERENCE`` and its value for an application window.
DWMWA_WINDOW_CORNER_PREFERENCE = 33
DWMWCP_ROUND = 2

#: ``DWMWA_NCRENDERING_POLICY`` and ``DWMNCRP_DISABLED``: "draw no system frame for
#: this window", which is what takes its drop shadow away. See `no_shadow`.
DWMWA_NCRENDERING_POLICY = 2
DWMNCRP_DISABLED = 1

TPM_LEFTALIGN = 0x0000
TPM_TOPALIGN = 0x0000
TPM_RIGHTBUTTON = 0x0002
#: Return the chosen item as a value instead of posting it. The command is then
#: posted by hand, which keeps the window's own message loop as the thing that
#: acts on it -- the same thing that happens when a user clicks the menu.
TPM_RETURNCMD = 0x0100
WM_SYSCOMMAND = 0x0112

#: ``GetAncestor``'s "the top-level window that owns this handle".
GA_ROOT = 2

#: ``GWL_STYLE`` is the window's style word; ``GWLP_WNDPROC`` is the address of
#: its window procedure. Both are slots on the window rather than messages.
GWL_STYLE = -16
GWLP_WNDPROC = -4

#: The style bits a window must carry to be resizable at all.
#:
#: ``WS_THICKFRAME`` is the one that matters, and for more than resizing: it is
#: what makes the window eligible for Aero Snap and for the drag-to-the-top
#: maximize, so without it the gestures the user asks for are not refused --
#: they never reach the window at all. A frameless window carries none of these
#: bits, which is exactly why dragging it to the top of the screen did nothing.
WS_MAXIMIZEBOX = 0x00010000
WS_MINIMIZEBOX = 0x00020000
WS_THICKFRAME = 0x00040000
WS_SYSMENU = 0x00080000

#: ``SetWindowPos`` flags. Only ``SWP_FRAMECHANGED`` is load-bearing: without it
#: a new style is recorded on the window but the frame it implies is not
#: recomputed, and the window goes on behaving as it did.
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
SWP_FRAMECHANGED = 0x0020
#: ``SetWindowPos``'s "put it above everything that is not topmost", for the
#: window that is a card rather than a window.
HWND_TOPMOST = -1

#: The messages this module answers or sends. ``WM_NCCALCSIZE`` is the OS asking
#: what the client area should be; ``WM_NCLBUTTONDOWN`` with a hit-test code is
#: how a press becomes the OS's own move or sizing loop.
WM_NCCALCSIZE = 0x0083
WM_NCLBUTTONDOWN = 0x00A1

#: The hit-test codes. ``HTCAPTION`` means "the title bar" whatever element the
#: press landed on, which is the whole trick: return it and Windows drags the
#: window -- with snapping -- exactly as it would a decorated one.
HTCLIENT = 1
HTCAPTION = 2
HTLEFT = 10
HTRIGHT = 11
HTTOP = 12
HTTOPLEFT = 13
HTTOPRIGHT = 14
HTBOTTOM = 15
HTBOTTOMLEFT = 16
HTBOTTOMRIGHT = 17

#: ``MonitorFromWindow``'s "the monitor this window is nearest", which is the one
#: a maximized window belongs to.
MONITOR_DEFAULTTONEAREST = 2

#: The eight edges the page may ask to resize from, and the code each one is. A
#: closed map rather than a passthrough, for the reason ``Bridge.ACTIONS`` is
#: one: the page is not handed an arbitrary window command for asking nicely.
RESIZE_EDGES = {
    "left": HTLEFT,
    "right": HTRIGHT,
    "top": HTTOP,
    "bottom": HTBOTTOM,
    "top-left": HTTOPLEFT,
    "top-right": HTTOPRIGHT,
    "bottom-left": HTBOTTOMLEFT,
    "bottom-right": HTBOTTOMRIGHT,
}


class RECT(ctypes.Structure):
    """A screen rectangle. ``wintypes.RECT`` is the same shape under another name."""

    _fields_ = [
        ("left", wintypes.LONG),
        ("top", wintypes.LONG),
        ("right", wintypes.LONG),
        ("bottom", wintypes.LONG),
    ]


class NCCALCSIZE_PARAMS(ctypes.Structure):
    """What ``WM_NCCALCSIZE`` carries in ``lParam`` when ``wParam`` is true.

    ``rgrc[0]`` is the proposed window rectangle coming in and the client
    rectangle going out; ``[1]`` and ``[2]`` are the previous window and client
    rectangles, which this module never reads.
    """

    _fields_ = [("rgrc", RECT * 3), ("lppos", ctypes.c_void_p)]


class MONITORINFO(ctypes.Structure):
    """A monitor's bounds and work area. ``rcWork`` is the screen minus the taskbar."""

    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", RECT),
        ("rcWork", RECT),
        ("dwFlags", wintypes.DWORD),
    ]


#: ``LRESULT`` and the shape of a window procedure, so the callback's return and
#: argument widths are declared rather than guessed at by ctypes.
LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(
    LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
)

#: Each window's original procedure, by handle, so messages this module does not
#: answer still reach WinForms.
_original_procs: dict[int, int] = {}

#: The callbacks themselves, by handle. Holding the reference is the point:
#: ctypes frees the thunk when the last Python reference goes, and the window
#: would then call a pointer into freed memory on its next message.
_procedures: dict[int, object] = {}

_bound = False


class WindowsOnlyError(RuntimeError):
    """A window call was made somewhere there is no Win32 to make it on."""


def _bind() -> None:
    """Declare the prototypes once. See the module docstring for why."""
    global _bound  # noqa: PLW0603 - one-time ctypes setup, by design
    if _bound or sys.platform != "win32":
        return

    user32 = ctypes.windll.user32  # type: ignore[attr-defined]
    dwmapi = ctypes.windll.dwmapi  # type: ignore[attr-defined]

    user32.GetSystemMenu.argtypes = [wintypes.HWND, wintypes.BOOL]
    user32.GetSystemMenu.restype = wintypes.HMENU
    user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
    user32.GetCursorPos.restype = wintypes.BOOL
    user32.TrackPopupMenu.argtypes = [
        wintypes.HMENU,
        wintypes.UINT,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.HWND,
        ctypes.c_void_p,
    ]
    # A command id under TPM_RETURNCMD, a BOOL without it -- so an unsigned int
    # covers both readings and zero stays "dismissed" either way.
    user32.TrackPopupMenu.restype = ctypes.c_uint
    user32.PostMessageW.argtypes = [
        wintypes.HWND,
        wintypes.UINT,
        wintypes.WPARAM,
        wintypes.LPARAM,
    ]
    user32.PostMessageW.restype = wintypes.BOOL
    user32.IsZoomed.argtypes = [wintypes.HWND]
    user32.IsZoomed.restype = wintypes.BOOL
    user32.IsIconic.argtypes = [wintypes.HWND]
    user32.IsIconic.restype = wintypes.BOOL
    user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
    user32.GetAncestor.restype = wintypes.HWND
    user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.GetWindowLongW.restype = ctypes.c_long
    user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
    user32.SetWindowLongW.restype = ctypes.c_long
    user32.SetWindowPos.argtypes = [
        wintypes.HWND,
        wintypes.HWND,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.UINT,
    ]
    user32.SetWindowPos.restype = wintypes.BOOL
    user32.ReleaseCapture.argtypes = []
    user32.ReleaseCapture.restype = wintypes.BOOL
    user32.GetCapture.argtypes = []
    user32.GetCapture.restype = wintypes.HWND
    user32.SendMessageW.argtypes = [
        wintypes.HWND,
        wintypes.UINT,
        wintypes.WPARAM,
        wintypes.LPARAM,
    ]
    user32.SendMessageW.restype = LRESULT
    user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
    user32.MonitorFromWindow.restype = ctypes.c_void_p
    user32.GetMonitorInfoW.argtypes = [ctypes.c_void_p, ctypes.POINTER(MONITORINFO)]
    user32.GetMonitorInfoW.restype = wintypes.BOOL
    user32.CallWindowProcW.argtypes = [
        ctypes.c_void_p,
        wintypes.HWND,
        wintypes.UINT,
        wintypes.WPARAM,
        wintypes.LPARAM,
    ]
    user32.CallWindowProcW.restype = LRESULT
    # The `Ptr` variants exist only on 64-bit Windows. The plain ones are right
    # for a style word at either width, and would truncate a *procedure address*
    # on the width that ships -- which is why the two are not interchangeable
    # here even though both are a `Long`.
    if ctypes.sizeof(ctypes.c_void_p) == 8:
        user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.GetWindowLongPtrW.restype = ctypes.c_void_p
        user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
        user32.SetWindowLongPtrW.restype = ctypes.c_void_p

    dwmapi.DwmSetWindowAttribute.argtypes = [
        wintypes.HWND,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
    ]
    dwmapi.DwmSetWindowAttribute.restype = ctypes.c_long

    # `CreateEllipticRgn` is GDI and `SetWindowRgn` is user32, which is why one
    # module fetches both: a window region is a GDI object handed to the window
    # manager, and the two halves are in different libraries.
    gdi32 = ctypes.windll.gdi32  # type: ignore[attr-defined]
    gdi32.CreateEllipticRgn.argtypes = [
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
    ]
    gdi32.CreateEllipticRgn.restype = ctypes.c_void_p
    gdi32.DeleteObject.argtypes = [ctypes.c_void_p]
    gdi32.DeleteObject.restype = wintypes.BOOL
    user32.SetWindowRgn.argtypes = [wintypes.HWND, ctypes.c_void_p, wintypes.BOOL]
    user32.SetWindowRgn.restype = ctypes.c_int
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(RECT)]
    user32.GetWindowRect.restype = wintypes.BOOL

    _bound = True


def no_shadow(hwnd: int) -> None:
    """Turn off the window's drop shadow.

    **Measured, and it is the reason a round pet still looked rectangular.** The
    region cuts the window's corners, but DWM draws the drop shadow to the window's
    *rectangle*, not to its region -- so the cut-away corners are filled by the
    shadow and the pet reads as a dark rounded square with a circle drawn inside it.

    The evidence, taken over a pure white backdrop with the pet 180x180 in the
    middle of it (pixel values, 6px and 14px outside the window's rect):

        spot            window hidden   window shown   shadow policy off
        corner (6px)    255             193-241        255
        edge midpoint   255             119-211        255

    A circle inscribed in a square touches that square's edges at their *midpoints*
    and misses the corners entirely, so a shadow that followed the region would be
    strong at the edge midpoints and absent at the corners. It was dark at both,
    which is what says the shadow is rectangular -- and disabling non-client
    rendering removes it everywhere, including the ring outside the rect.

    ``DWMWA_NCRENDERING_POLICY`` with ``DWMNCRP_DISABLED`` is the documented way to
    say "this window has no system-drawn frame": the shadow, the system border and
    the compositor's rounded corners all go. None of them is wanted here -- the shape
    is a region and the edge is the card's own border -- and the pet keeps every
    extended style that makes it a pet (``WS_EX_NOACTIVATE``, topmost, frameless).
    """
    if sys.platform != "win32":
        raise WindowsOnlyError("a window shadow is DWM behaviour")
    _bind()
    policy = ctypes.c_int(DWMNCRP_DISABLED)
    hr = ctypes.windll.dwmapi.DwmSetWindowAttribute(  # type: ignore[attr-defined]
        wintypes.HWND(hwnd),
        DWMWA_NCRENDERING_POLICY,
        ctypes.byref(policy),
        ctypes.sizeof(policy),
    )
    if hr < 0:
        # Signed, like `round_corners`: anything below zero is `FAILED()` in C.
        raise OSError(f"DwmSetWindowAttribute refused the shadow policy: hr={hr}")


def round_corners(hwnd: int) -> None:
    """Ask the compositor to round this window's corners."""
    if sys.platform != "win32":
        raise WindowsOnlyError("rounded corners are a Win32 window attribute")
    _bind()
    preference = ctypes.c_int(DWMWCP_ROUND)
    hr = ctypes.windll.dwmapi.DwmSetWindowAttribute(  # type: ignore[attr-defined]
        wintypes.HWND(hwnd),
        DWMWA_WINDOW_CORNER_PREFERENCE,
        ctypes.byref(preference),
        ctypes.sizeof(preference),
    )
    # An HRESULT is a signed status where anything below zero failed, which is
    # what `FAILED()` in C is.
    if hr < 0:
        raise OSError(
            f"DwmSetWindowAttribute refused the corner preference (0x{hr & 0xFFFFFFFF:08x})"
        )


def is_maximized(hwnd: int) -> bool:
    """Whether the window is maximized, according to the window."""
    if sys.platform != "win32":
        return False
    _bind()
    return bool(ctypes.windll.user32.IsZoomed(wintypes.HWND(hwnd)))  # type: ignore[attr-defined]


def is_minimized(hwnd: int) -> bool:
    """Whether the window is minimized, according to the window.

    Asked the same way and for the same reason as ``is_maximized``: pywebview's
    own ``Window.state`` is the JavaScript state bridge and says nothing about
    the window's presentation state, so a caller that needs to know whether the
    window is down in the taskbar has to ask the window. A zero handle is not a
    window and answers ``False``.
    """
    if sys.platform != "win32":
        return False
    _bind()
    return bool(ctypes.windll.user32.IsIconic(wintypes.HWND(hwnd)))  # type: ignore[attr-defined]


def foreground_window() -> int:
    """Whatever owns the foreground right now, as a handle; 0 when nothing does.

    Asked *before* a window is created, so the same value can be handed back to
    ``give_foreground_back`` afterwards. See that function for why the card needs
    this at all.
    """
    if sys.platform != "win32":
        return 0
    _bind()
    return int(ctypes.windll.user32.GetForegroundWindow())  # type: ignore[attr-defined]


def give_foreground_back(previous: int, mine: int) -> bool:
    """Hand the foreground back to `previous` if `mine` took it. Returns whether.

    **Measured, and the reason a card cannot be created politely.** Creating a
    window takes the foreground once, and nothing available here prevents it:
    ``focus=False`` sets ``WS_EX_NOACTIVATE`` (verified on the real window), which
    stops *clicks* from activating it, and creating it hidden and revealing it
    with ``SWP_NOACTIVATE`` still came back with
    ``GetForegroundWindow() == the card``. pywebview's own hidden path shows the
    form before hiding it, and that first show is an activation nothing on this
    side can refuse.

    So the foreground is simply taken back: the handle that owned it before the
    card was made is restored, which is the difference between a pet that pulls
    the keyboard out of whatever the user was typing in and one that never
    touches it. Windows only allows this from the process that owns the current
    foreground window -- which is why it works here and nowhere else, and why a
    failure is reported rather than raised.
    """
    if sys.platform != "win32":
        return False
    if not previous or previous == mine:
        return False
    _bind()
    user32 = ctypes.windll.user32  # type: ignore[attr-defined]
    if int(user32.GetForegroundWindow()) != mine:
        # Something else already has it, and pushing our own window back in front
        # of *that* would be a worse intrusion than the one being undone.
        return False
    return bool(user32.SetForegroundWindow(wintypes.HWND(previous)))


def raise_without_activating(hwnd: int) -> None:
    """Put the window at the top of the z-order without giving it the foreground.

    **Measured, and the reason this function exists.** pywebview's ``focus=False``
    does set ``WS_EX_NOACTIVATE`` -- verified on the real window -- but that style
    only stops *clicks* from activating it. The window is activated once, when it
    is first created, and the style arrives too late to prevent it: a card created
    with ``focus=False`` measured ``GetForegroundWindow() == its own handle``
    immediately afterwards, which on a desktop pet means the keyboard is pulled
    out of whatever the user was typing in at the moment the agent finished a
    tool.

    No ``SWP_SHOWWINDOW``: the window is already visible when this runs (creating
    it hidden and showing it here was tried, and it cost the card both
    ``WS_EX_TOPMOST`` and ``WS_EX_NOACTIVATE`` without stopping the activation).
    ``SWP_NOACTIVATE`` plus the ``SWP_NOZORDER``-free topmost placement is what
    keeps it above the other windows while leaving the foreground alone -- and
    ``give_foreground_back`` is what undoes the activation creating it caused.
    """
    if sys.platform != "win32":
        raise WindowsOnlyError("showing without activating is a Win32 window behaviour")
    _bind()
    ctypes.windll.user32.SetWindowPos(  # type: ignore[attr-defined]
        wintypes.HWND(hwnd),
        wintypes.HWND(HWND_TOPMOST),
        0,
        0,
        0,
        0,
        SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE,
    )


def frameless_resizable_style(style: int) -> int:
    """The style word for a window that resizes and snaps but draws no frame.

    A pure function of the style it is handed, so the bits can be asserted
    without a window to put them on. The frame is not in the style word:
    ``WS_THICKFRAME`` is what *permits* one, and ``WM_NCCALCSIZE`` below is what
    declines to draw it.
    """
    return style | WS_THICKFRAME | WS_MAXIMIZEBOX | WS_MINIMIZEBOX | WS_SYSMENU


def frameless_fixed_style(style: int) -> int:
    """The style word for a window that is *real* without being resizable.

    ``WS_THICKFRAME`` is what makes Windows treat a window as a window: DWM rounds its
    corners and gives it a drop shadow. That is exactly what a card that is
    deliberately rectangular wants, and it cannot be had any other way -- a window
    region does not clip the composited content the card is drawn with (measured; see
    ``research/why-the-square.md``), while DWM's rounding does, as this app's own main
    window has been proving all along.

    It is deliberately **not** ``frameless_resizable_style``: no maximize box, no
    minimize box, no system menu. A pet that can be maximized is not a pet. The size
    is pinned separately, so dragging an edge has nothing to give.
    """
    return style | WS_THICKFRAME


def make_framed(hwnd: int) -> None:
    """Add the frame bits DWM rounds, minus the ones that would resize."""
    _adopt_style(hwnd, frameless_fixed_style)


def make_resizable(hwnd: int) -> None:
    """Add the frame bits to a window that must not draw a frame.

    Cheap and idempotent when there is nothing to do, because the host applies
    it from two places -- and the first of those is the attempt that is allowed
    to find no window yet.
    """
    _adopt_style(hwnd, frameless_resizable_style)


def _adopt_style(hwnd: int, recipe: Callable[[int], int]) -> None:
    """Set a window's style word to what `recipe` asks for, and make it take effect."""
    if sys.platform != "win32":
        raise WindowsOnlyError("window styles are a Win32 behaviour")
    _bind()
    user32 = ctypes.windll.user32  # type: ignore[attr-defined]
    handle = wintypes.HWND(hwnd)
    style = user32.GetWindowLongW(handle, GWL_STYLE)
    wanted = recipe(style)
    if wanted == style:
        return
    user32.SetWindowLongW(handle, GWL_STYLE, wanted)
    # ``SWP_FRAMECHANGED`` is what makes the new style take effect *now* rather
    # than at whatever next moves or resizes the window.
    user32.SetWindowPos(
        handle,
        None,
        0,
        0,
        0,
        0,
        SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED,
    )


def work_area(hwnd: int) -> RECT:
    """The window's monitor minus the taskbar and anything else docked to it."""
    _bind()
    user32 = ctypes.windll.user32  # type: ignore[attr-defined]
    monitor = user32.MonitorFromWindow(wintypes.HWND(hwnd), MONITOR_DEFAULTTONEAREST)
    info = MONITORINFO()
    info.cbSize = ctypes.sizeof(MONITORINFO)
    if not user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
        raise OSError("this window's monitor has no work area to read")
    return info.rcWork


def _window_proc(hwnd: int, message: int, wparam: int, lparam: int) -> int:
    """The window's procedure, with exactly one message answered here.

    ``WM_NCCALCSIZE`` is the OS asking how much of this window is non-client.
    The answer is *none of it*, and that is what removes the frame
    ``WS_THICKFRAME`` implies while leaving the resizing and the snapping that
    come with the style.

    The exception is a maximized window. There the OS proposes a rectangle that
    overhangs the screen by the frame thickness -- correct for a window that
    paints its own frame, wrong for one that does not, and it shows up as the
    client area disappearing under the taskbar. So a maximized window is given
    the monitor's work area instead.

    Everything else goes to the procedure this one replaced, which is WinForms'
    own and knows a great deal more about this window than this module does.
    """
    try:
        if message == WM_NCCALCSIZE and wparam:
            if is_maximized(int(hwnd)):
                params = ctypes.cast(lparam, ctypes.POINTER(NCCALCSIZE_PARAMS)).contents
                params.rgrc[0] = work_area(int(hwnd))
            return 0
    except Exception as exc:  # noqa: BLE001 - see the comment below
        # This runs inside the OS's own message dispatch, where an exception has
        # nowhere to go and would take the window with it. The safe answer is to
        # fall through to the original procedure: the window keeps a frame it
        # was not supposed to draw, and it keeps working.
        logger.debug(f"WM_NCCALCSIZE fell through to WinForms: {exc}")
    previous = _original_procs.get(int(hwnd))
    if previous is None:
        return 0
    return ctypes.windll.user32.CallWindowProcW(  # type: ignore[attr-defined]
        previous, wintypes.HWND(hwnd), message, wparam, lparam
    )


def install_frame(hwnd: int) -> None:
    """Give the window the procedure above, once.

    Idempotent on purpose. The host applies this from two places -- immediately,
    and again on ``shown`` -- because the first may run before the form has a
    handle. Installing it twice would chain this module's procedure into itself,
    and every message would re-enter it forever.
    """
    if sys.platform != "win32":
        raise WindowsOnlyError("the frame is a Win32 window procedure")
    _bind()
    if hwnd in _original_procs:
        return
    user32 = ctypes.windll.user32  # type: ignore[attr-defined]
    handle = wintypes.HWND(hwnd)
    procedure = WNDPROC(_window_proc)
    address = ctypes.cast(procedure, ctypes.c_void_p)
    if ctypes.sizeof(ctypes.c_void_p) == 8:
        previous = user32.SetWindowLongPtrW(handle, GWLP_WNDPROC, address)
    else:
        previous = user32.SetWindowLongW(handle, GWLP_WNDPROC, address)
    if not previous:
        raise OSError("the window refused a new window procedure")
    _original_procs[hwnd] = int(previous)
    _procedures[hwnd] = procedure
    # Ask for the frame to be recomputed *now*, with this procedure in place.
    #
    # Not tidiness, and it was measured: ``SetWindowLongPtrW`` alone changes who
    # answers the next message, and ``WM_NCCALCSIZE`` is only sent when the frame
    # is recomputed. Adding the style bits first therefore computed the client
    # area under WinForms -- a normal frame, 12x13px smaller than the window --
    # and it stayed that way until something else resized the window. The window
    # looked right from the outside and its page was inset from its own edge.
    user32.SetWindowPos(
        handle,
        None,
        0,
        0,
        0,
        0,
        SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED,
    )


def begin_drag(hwnd: int) -> None:
    """Start the OS's own move loop, which is where Aero Snap lives.

    Drag to the top and it maximizes, drag to a side and it takes that half,
    drag against the top edge of the screen and it offers the snap layouts --
    all of it the same code a decorated window runs, because this is that code.
    """
    _begin_native_gesture(hwnd, HTCAPTION)


def begin_resize(hwnd: int, edge: str) -> None:
    """Start the OS's own sizing loop from one of ``RESIZE_EDGES``."""
    code = RESIZE_EDGES.get(edge)
    if code is None:
        raise ValueError(f"unknown resize edge: {edge!r}")
    _begin_native_gesture(hwnd, code)


def _begin_native_gesture(hwnd: int, code: int) -> None:
    """Hand a press to the OS as a non-client press, and block until it ends.

    ``SendMessage`` rather than ``PostMessage``: the loop it starts is modal and
    runs on the window's own thread, and this call is how the page says "the
    user is dragging now". It returns when they let go of the mouse.
    """
    if sys.platform != "win32":
        raise WindowsOnlyError("a native window gesture is Win32 behaviour")
    _bind()
    user32 = ctypes.windll.user32  # type: ignore[attr-defined]
    # The press that got here already gave something the mouse capture, and the
    # OS's loop refuses to run while anything holds it.
    held = user32.GetCapture()
    user32.ReleaseCapture()
    started = time.perf_counter()
    result = user32.SendMessageW(
        wintypes.HWND(hwnd), WM_NCLBUTTONDOWN, wintypes.WPARAM(code), _cursor_lparam()
    )
    # Timed, so "the drag did nothing" has an answer either way: a loop that ran
    # and moved nothing looks nothing like a loop that never started.
    logger.debug(
        f"window gesture {code}: capture {int(held) if held else 0} -> "
        f"{int(user32.GetCapture()) if user32.GetCapture() else 0}, "
        f"{time.perf_counter() - started:.3f}s, rc={result}"
    )


def _cursor_lparam() -> int:
    """The cursor's screen position, packed the way a mouse message packs it.

    Two signed 16-bit halves. Negative coordinates -- a second monitor to the
    left or above -- wrap, which is what ``MAKELPARAM`` does and what the OS
    expects to find.
    """
    user32 = ctypes.windll.user32  # type: ignore[attr-defined]
    at = wintypes.POINT()
    if not user32.GetCursorPos(ctypes.byref(at)):
        return 0
    return ((at.y & 0xFFFF) << 16) | (at.x & 0xFFFF)


def root_window(hwnd: int) -> int:
    """The top-level window that owns a handle.

    A webview is a control nested inside a form, and the handle pywebview offers
    belongs to the *control*. Everything this module asks the OS for -- the
    system menu, the corner preference, the maximized state -- belongs to the
    top-level window, so the handle is walked up before it is used. Asked on the
    child, ``GetSystemMenu`` returns the menu of a control that has none.
    """
    if sys.platform != "win32":
        return hwnd
    _bind()
    root = ctypes.windll.user32.GetAncestor(wintypes.HWND(hwnd), GA_ROOT)  # type: ignore[attr-defined]
    # `GetAncestor` answers NULL for a handle it cannot place, and a NULL passed
    # on to `GetSystemMenu` is a call on a null window. ctypes is not consistent
    # about the *shape* of that answer -- a `c_void_p` restype comes back as a
    # bare address here and as `None` when it is null -- so both are unwrapped
    # rather than one being assumed. Found by a test asserting the null case.
    address = getattr(root, "value", root)
    return int(address) if address else hwnd


def on_window_thread(window: Any, work: Callable[[], None]) -> None:
    """Run `work` on the thread that owns `window`, then return.

    **Not a tidiness call, and the difference is a whole feature.** A page's
    request arrives on a pywebview worker thread, but a window gesture is not a
    message the host can send on the page's behalf from anywhere:
    ``WM_NCLBUTTONDOWN`` starts a modal loop that belongs to the window's own
    thread, and the ``ReleaseCapture()`` in front of it -- the half of the classic
    pair that is easy to leave out -- acts on whichever thread makes the call.
    Issued from a worker it released the worker's own (empty) capture, left the
    webview's in place, and the loop never took: measured, the window did not move
    by a pixel.

    Two windows need this now -- the app's own draggable chrome and the pet's card
    -- which is why it lives here rather than as a method on one of them. The
    fallback is a direct call rather than an error, because a backend with no
    WinForms control behind it has no window thread to marshal to, and refusing to
    try would turn "this backend cannot drag" into "this backend raises".
    """
    native = getattr(window, "native", None)
    invoke = getattr(native, "Invoke", None)
    if invoke is None:
        work()
        return
    try:
        # pythonnet's delegate type. It is there whenever there is a WinForms
        # control to invoke on -- the import needs `clr`, which the Windows
        # backend has already imported by then.
        from System import Action  # noqa: PLC0415
    except Exception as exc:  # noqa: BLE001 - no delegate, no marshalling
        logger.debug(f"No delegate to marshal a window gesture with: {exc}")
        work()
        return
    invoke(Action(work))


def clip_to_circle(hwnd: int) -> None:
    """Cut the window down to the biggest circle that fits it, centred.

    **A region and not transparency, and that is the only way this shell offers a
    round window.** `transparent=True` leaves the form opaque here -- measured: no
    ``WS_EX_LAYERED``, ``AllowTransparency`` false, and the pixels beside the
    artwork coming back as control grey -- and setting the form's
    ``TransparencyKey`` by hand, which is the compositing route, hung the window.
    A window region predates all of it and composites nothing: the pixels outside
    the ellipse are simply not part of the window, so the desktop behind them
    shows through and a click there goes to whatever is behind rather than to the
    pet.

    Two consequences are visible and are chosen rather than suffered:

    * the rim is **hard**. The OS clips the window; it does not antialias it. A
      circle drawn in CSS on top of the region therefore has a slightly stepped
      edge, and nothing here can smooth it;
    * a **drop shadow cannot exist**, because there is no window outside the
      circle for one to be painted in. The card's `box-shadow` was removed rather
      than left in the stylesheet to be silently clipped.

    **The window's own box is what is measured, not the size it was asked for**,
    and that is a bug rather than a precaution. The first version cut a circle of
    the *requested* size, and pywebview's WinForms backend sets
    ``MinimumSize = min_size`` -- a default of ``200x100`` -- so a card asked for
    at 180 came back **200x141** and the region left a slab of window beside the
    circle. Asking Windows what the window is costs one call and cannot disagree
    with it.
    """
    if sys.platform != "win32":
        raise WindowsOnlyError("a window region is Win32 behaviour")
    _bind()
    gdi32 = ctypes.windll.gdi32  # type: ignore[attr-defined]
    user32 = ctypes.windll.user32  # type: ignore[attr-defined]
    box = RECT()
    if not user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(box)):
        raise OSError("GetWindowRect refused the window")
    left, top, right, bottom = circle_box(
        int(box.right - box.left), int(box.bottom - box.top)
    )
    region = gdi32.CreateEllipticRgn(left, top, right, bottom)
    if not region:
        raise OSError("CreateEllipticRgn returned no region")
    # `SetWindowRgn` *takes ownership* on success -- the system deletes the region,
    # so deleting it here too would be a double free. It does not on failure, and
    # that is the branch that has to clean up.
    if not user32.SetWindowRgn(wintypes.HWND(hwnd), region, True):
        gdi32.DeleteObject(region)
        raise OSError("SetWindowRgn refused the region")


def circle_box(width: int, height: int) -> tuple[int, int, int, int]:
    """The bounding box of the biggest centred circle inside a rectangle.

    A pure function so it can be tested without a window, and the one place the
    arithmetic lives: the stylesheet draws the same circle with
    `min(100vw, 100vh)`, and the two have to agree or the rim shows a sliver of
    whichever is larger.
    """
    side = min(int(width), int(height))
    left = (int(width) - side) // 2
    top = (int(height) - side) // 2
    return left, top, left + side, top + side


def show_system_menu(hwnd: int) -> None:
    """Put the window's own system menu on screen at the cursor.

    Blocks until the menu is dismissed, because that is what a menu is: it runs
    a modal loop and dispatches the window's messages while it is up. The caller
    runs on a pywebview worker thread, so the app keeps painting throughout.
    """
    if sys.platform != "win32":
        raise WindowsOnlyError("the system menu is a Win32 window menu")
    _bind()
    user32 = ctypes.windll.user32  # type: ignore[attr-defined]
    handle = wintypes.HWND(hwnd)

    # `False` asks for the live menu rather than a copy -- nothing to free.
    hmenu = user32.GetSystemMenu(handle, False)
    if not hmenu:
        raise OSError("this window has no system menu")

    at = wintypes.POINT()
    if not user32.GetCursorPos(ctypes.byref(at)):
        raise OSError("GetCursorPos failed")

    # At the cursor, not at the press: Windows puts the system menu at the
    # pointer, and F10 opens it there too, so both routes agree without either
    # being told where the bar is.
    chosen = user32.TrackPopupMenu(
        hmenu,
        TPM_LEFTALIGN | TPM_TOPALIGN | TPM_RIGHTBUTTON | TPM_RETURNCMD,
        at.x,
        at.y,
        0,
        handle,
        None,
    )
    # Zero is the menu being dismissed -- Escape, or a click elsewhere. There is
    # nothing to report and nothing to undo.
    if chosen and not user32.PostMessageW(handle, WM_SYSCOMMAND, chosen, 0):
        raise OSError("the window refused the menu command it had just been given")
