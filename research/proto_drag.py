"""Can a layered window still be dragged by the OS -- and can a click still be told
from a drag?

This is the one piece that could change the design. The research says a
`WS_EX_LAYERED` window cannot use the OS move loop and would need a **custom** drag,
losing Aero Snap. If that is true the raster path costs more than it looked; if it is
false we keep the OS dragging and the claim was wrong. It is measurable, so it is
measured rather than believed.

Three things are checked on a real layered window (the prototype from
`proto_layered_pet.py`), driven by synthetic mouse input:

1. **`WM_NCHITTEST` -> `HTCAPTION`.** This is the cleaner mechanism than
   `SendMessage(WM_NCLBUTTONDOWN, HTCAPTION)`: it makes *Windows* start its own move
   loop, which is the only way the OS's dragging behaviour (and any snapping that
   applies to a fixed-size popup) comes for free.
2. **`WM_ENTERSIZEMOVE` / `WM_EXITSIZEMOVE` arrive**, which is how the app learns a
   drag happened and where it ended -- without which the position could not be saved.
3. **A press with no movement is still detectable as a click**, because the move loop
   runs and exits without the rect changing. That is what keeps "click the pet to
   bring the app back" working.

Real input is synthesised, so the cursor is saved and restored, the left button is
always released, and a watchdog gives up rather than leaving it stuck down.

Run: python research/proto_drag.py
"""

import ctypes
import json
import os
import pathlib
import threading
import time
from ctypes import wintypes

import clr  # noqa: F401

clr.AddReference("System.Drawing")
from System.Drawing import Bitmap, Color, Graphics, SolidBrush  # noqa: E402
from System.Drawing.Drawing2D import SmoothingMode  # noqa: E402
from System.Drawing.Imaging import PixelFormat  # noqa: E402

SIZE = 180
START = (700, 500)
OUT = pathlib.Path(".tmp-drag-probe.json")

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32
kernel32 = ctypes.windll.kernel32

LRESULT = ctypes.c_ssize_t
WPARAM = ctypes.c_size_t
LPARAM = ctypes.c_ssize_t
HGDIOBJ = ctypes.c_void_p
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, WPARAM, LPARAM)

WS_EX_LAYERED = 0x00080000
WS_EX_TOPMOST = 0x00000008
WS_EX_NOACTIVATE = 0x08000000
WS_EX_TOOLWINDOW = 0x00000080
WS_POPUP = 0x80000000
WS_VISIBLE = 0x10000000
SW_SHOWNOACTIVATE = 4
ULW_ALPHA = 0x00000002
AC_SRC_OVER = 0x00
AC_SRC_ALPHA = 0x01
GWLP_EXSTYLE = -20
IDC_ARROW = 32512

WM_DESTROY = 0x0002
WM_ERASEBKGND = 0x0014
WM_NCHITTEST = 0x0084
WM_ENTERSIZEMOVE = 0x0231
WM_EXITSIZEMOVE = 0x0232
WM_MOVING = 0x0216

HTCAPTION = 2
HTCLIENT = 1

MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004


class WNDCLASSEX(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.UINT),
        ("style", wintypes.UINT),
        ("lpfnWndProc", WNDPROC),
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


def bind() -> None:
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
    user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.GetWindowLongW.restype = ctypes.c_long
    user32.LoadCursorW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR]
    user32.LoadCursorW.restype = wintypes.HANDLE
    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.ShowWindow.restype = wintypes.BOOL
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.GetWindowRect.restype = wintypes.BOOL
    user32.SetWindowPos.argtypes = [
        wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
        ctypes.c_int, ctypes.c_int, wintypes.UINT,
    ]
    user32.SetWindowPos.restype = wintypes.BOOL
    user32.GetDC.argtypes = [wintypes.HWND]
    user32.GetDC.restype = wintypes.HDC
    user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
    user32.ReleaseDC.restype = ctypes.c_int
    user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
    user32.GetCursorPos.restype = wintypes.BOOL
    user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
    user32.SetCursorPos.restype = wintypes.BOOL
    user32.mouse_event.argtypes = [
        wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p
    ]
    user32.mouse_event.restype = None
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


#: What the window procedure sees, and the one switch the two tests flip.
observed: dict = {"messages": [], "hit_test": False, "proc_error": None}


def pet_proc(hwnd, message, wparam, lparam):
    try:
        if message == WM_NCHITTEST:
            # The mechanism under test: answering `HTCAPTION` is what asks Windows to
            # run its own move loop for a press anywhere on the pet.
            return HTCAPTION if observed["hit_test"] else HTCLIENT
        if message in (WM_ENTERSIZEMOVE, WM_EXITSIZEMOVE, WM_MOVING):
            name = {
                WM_ENTERSIZEMOVE: "WM_ENTERSIZEMOVE",
                WM_EXITSIZEMOVE: "WM_EXITSIZEMOVE",
                WM_MOVING: "WM_MOVING",
            }[message]
            if name != "WM_MOVING" or observed["messages"][-1:] != ["WM_MOVING"]:
                observed["messages"].append(name)
            return 0
        if message == WM_ERASEBKGND:
            return 1
    except Exception as exc:  # noqa: BLE001 - a probe reports, it does not raise
        observed["proc_error"] = repr(exc)
    return user32.DefWindowProcW(hwnd, message, wparam, lparam)


_procs: list = []


def create_window(name: str) -> int:
    proc = WNDPROC(pet_proc)
    _procs.append(proc)
    wc = WNDCLASSEX()
    wc.cbSize = ctypes.sizeof(WNDCLASSEX)
    wc.lpfnWndProc = proc
    wc.hInstance = kernel32.GetModuleHandleW(None)
    wc.hCursor = user32.LoadCursorW(None, wintypes.LPCWSTR(IDC_ARROW))
    wc.lpszClassName = name
    if not user32.RegisterClassExW(ctypes.byref(wc)):
        raise OSError(f"RegisterClassExW failed: {ctypes.GetLastError()}")
    return int(
        user32.CreateWindowExW(
            WS_EX_LAYERED | WS_EX_TOPMOST | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW,
            name, "drag probe", WS_POPUP | WS_VISIBLE,
            START[0], START[1], SIZE, SIZE, None, None,
            kernel32.GetModuleHandleW(None), None,
        )
    )


def frame(hwnd: int, hue: tuple) -> None:
    bitmap = Bitmap(SIZE, SIZE, PixelFormat.Format32bppArgb)
    graphics = Graphics.FromImage(bitmap)
    graphics.SmoothingMode = SmoothingMode.AntiAlias
    graphics.Clear(Color.Transparent)
    graphics.FillEllipse(SolidBrush(Color.FromArgb(255, *hue)), 1, 1, SIZE - 2, SIZE - 2)
    graphics.Dispose()
    hbitmap = bitmap.GetHbitmap(Color.FromArgb(0)).ToInt64()
    screen = user32.GetDC(None)
    memory = gdi32.CreateCompatibleDC(screen)
    gdi32.SelectObject(memory, hbitmap)
    size = wintypes.SIZE(SIZE, SIZE)
    source = wintypes.POINT(0, 0)
    destination = wintypes.POINT(START[0], START[1])
    blend = BLENDFUNCTION(AC_SRC_OVER, 0, 255, AC_SRC_ALPHA)
    user32.UpdateLayeredWindow(
        wintypes.HWND(hwnd), screen, ctypes.byref(destination), ctypes.byref(size),
        memory, ctypes.byref(source), 0, ctypes.byref(blend), ULW_ALPHA,
    )
    gdi32.DeleteDC(memory)
    user32.ReleaseDC(None, screen)
    gdi32.DeleteObject(hbitmap)


def rect(hwnd: int) -> tuple:
    box = wintypes.RECT()
    user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(box))
    return (box.left, box.top)


def press_and_drag(hwnd: int, from_xy: tuple, to_xy: tuple, steps: int = 6) -> dict:
    """A real press, a real drag, a real release -- the whole gesture, by hand."""
    trail = []
    user32.SetCursorPos(*from_xy)
    time.sleep(0.12)
    user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, None)
    time.sleep(0.15)
    for step in range(1, steps + 1):
        x = from_xy[0] + (to_xy[0] - from_xy[0]) * step // steps
        y = from_xy[1] + (to_xy[1] - from_xy[1]) * step // steps
        user32.SetCursorPos(x, y)
        time.sleep(0.06)
        trail.append(rect(hwnd))
    user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, None)
    time.sleep(0.35)
    return {"trail": trail, "cursor": user32.GetCursorPos(wintypes.POINT())}


def main() -> None:
    bind()
    notes: dict[str, object] = {}
    cursor_before = wintypes.POINT()

    def watchdog() -> None:
        time.sleep(40)
        user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, None)
        notes["watchdog"] = True
        OUT.write_text(json.dumps(notes, indent=2, default=str), encoding="utf-8")
        os._exit(1)

    threading.Thread(target=watchdog, daemon=True).start()

    # **The window is created on the thread that pumps.** Win32 delivers a window's
    # messages to the thread that created it, so a window made here and pumped on
    # another thread receives nothing at all -- which is exactly what the first run of
    # this probe measured: not one `WM_NCHITTEST`. The first prototype got away with
    # it because `UpdateLayeredWindow` needs no message loop, but every message-driven
    # behaviour in it was silently untested.
    created: dict = {}

    def ui_thread() -> None:
        hwnd = create_window("ProtoDragPet")
        frame(hwnd, (32, 32, 32))
        user32.ShowWindow(wintypes.HWND(hwnd), SW_SHOWNOACTIVATE)
        created["hwnd"] = hwnd
        message = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(message))
            user32.DispatchMessageW(ctypes.byref(message))

    threading.Thread(target=ui_thread, daemon=True).start()
    for _ in range(60):
        time.sleep(0.1)
        if created.get("hwnd"):
            break
    hwnd = created.get("hwnd")
    if not hwnd:
        raise SystemExit("the probe window never came up")
    time.sleep(0.6)
    user32.GetCursorPos(ctypes.byref(cursor_before))
    notes["hwnd"] = hwnd
    notes["start"] = list(START)
    notes["styles"] = hex(user32.GetWindowLongW(wintypes.HWND(hwnd), GWLP_EXSTYLE) & 0xFFFFFFFF)

    try:
        # --- 1. the hit-test switch off: a press is a client press, no drag --------
        observed["hit_test"] = False
        observed["messages"].clear()
        before = rect(hwnd)
        moved = press_and_drag(hwnd, (START[0] + 90, START[1] + 90), (START[0] + 190, START[1] + 190), steps=3)
        notes["client_press"] = {
            "before": list(before),
            "trail": [list(p) for p in moved["trail"]],
            "messages": list(observed["messages"]),
        }

        # --- 2. press with no movement: is it still a click? ----------------------
        user32.SetWindowPos(wintypes.HWND(hwnd), None, START[0], START[1], 0, 0, 0x0001 | 0x0004)
        time.sleep(0.4)
        observed["hit_test"] = True
        observed["messages"].clear()
        before_click = rect(hwnd)
        user32.SetCursorPos(START[0] + 90, START[1] + 90)
        time.sleep(0.12)
        user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, None)
        time.sleep(0.25)
        user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, None)
        time.sleep(0.4)
        notes["stationary_press"] = {
            "before": list(before_click),
            "after": list(rect(hwnd)),
            "messages": list(observed["messages"]),
        }

        # --- 3. the hit-test switch on: the OS should drag it itself --------------
        user32.SetWindowPos(wintypes.HWND(hwnd), None, START[0], START[1], 0, 0, 0x0001 | 0x0004)
        time.sleep(0.4)
        observed["messages"].clear()
        before_drag = rect(hwnd)
        dragged = press_and_drag(
            hwnd, (START[0] + 90, START[1] + 90), (START[0] + 250, START[1] + 160), steps=6
        )
        notes["hit_test_drag"] = {
            "before": list(before_drag),
            "trail": [list(p) for p in dragged["trail"]],
            "after": list(rect(hwnd)),
            "messages": list(observed["messages"]),
            "moved": rect(hwnd) != before_drag,
        }
    finally:
        user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, None)
        user32.SetCursorPos(cursor_before.x, cursor_before.y)
        notes["proc_error"] = observed["proc_error"]
        OUT.write_text(json.dumps(notes, indent=2, default=str), encoding="utf-8")
        os._exit(0)


if __name__ == "__main__":
    main()
