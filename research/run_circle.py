"""Pop a live circle on the desktop for a human to judge.

This is the prototype from `proto_layered_pet.py` with the wiring that makes it a
usable thing to test: it stays up until it is closed, it logs every drag and click it
sees, and it can be dragged by the OS itself (`WM_NCHITTEST` -> `HTCAPTION`).

It is a native layered window -- there is no WebView2 in it. Each frame is a 32-bit
ARGB bitmap blitted with `UpdateLayeredWindow(..., ULW_ALPHA)`, so the transparency is
per-pixel: the dark disc, a drop shadow that fades to nothing, and the antialiased rim
are all just alpha. The GDI region is kept for **input only**, so the corners are
click-through; it is never visible, because the alpha is already gone before its edge.

Logs to stdout and to `.tmp-circle.jsonl`, so a subjective "it looked smooth" can be
read next to what the window actually did.

**Right-click closes it.** Run: python research/run_circle.py
"""

import ctypes
import json
import pathlib
import threading
import time
from ctypes import wintypes

import clr  # noqa: F401

clr.AddReference("System.Drawing")
from System.Drawing import Bitmap, Color, Graphics, SolidBrush  # noqa: E402  # noqa: E501
from System.Drawing.Drawing2D import SmoothingMode  # noqa: E402
from System.Drawing.Imaging import PixelFormat  # noqa: E402

import grab_cursor  # noqa: E402 - beside this file, and loads PIL itself

SIZE = 180
AT = (900, 250)
LOG = pathlib.Path(".tmp-circle.jsonl")

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

HTCAPTION = 2
HTCLIENT = 1

#: Filled in by `main`: the `grab` and `grabbing` cursors, so the procedure can set
#: them. A draggable thing should say so before it is dragged.
cursors: dict = {}


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
    user32.LoadCursorW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR]
    user32.LoadCursorW.restype = wintypes.HANDLE
    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.ShowWindow.restype = wintypes.BOOL
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.GetWindowRect.restype = wintypes.BOOL
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
    user32.SetWindowRgn.argtypes = [wintypes.HWND, ctypes.c_void_p, wintypes.BOOL]
    user32.SetWindowRgn.restype = ctypes.c_int
    user32.GetMessageW.argtypes = [
        ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT
    ]
    user32.GetMessageW.restype = ctypes.c_int
    user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
    user32.TranslateMessage.restype = wintypes.BOOL
    user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
    user32.DispatchMessageW.restype = LRESULT
    user32.DestroyWindow.argtypes = [wintypes.HWND]
    user32.DestroyWindow.restype = wintypes.BOOL
    user32.PostQuitMessage.argtypes = [ctypes.c_int]
    user32.PostQuitMessage.restype = None
    user32.SetCursor.argtypes = [wintypes.HANDLE]
    user32.SetCursor.restype = wintypes.HANDLE
    user32.DestroyCursor.argtypes = [wintypes.HANDLE]
    user32.DestroyCursor.restype = wintypes.BOOL

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


def say(event: str, **fields: object) -> None:
    line = json.dumps({"event": event, **fields})
    LOG.open("a", encoding="utf-8").write(line + "\n")
    print(f"[circle] {line}", flush=True)


def rect(hwnd: int) -> tuple:
    box = wintypes.RECT()
    user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(box))
    return (box.left, box.top)


#: The gesture in progress, for the click-versus-drag answer.
drag: dict = {"started_at": None, "active": False}
_procs: list = []


def proc(hwnd, message, wparam, lparam):
    if message == WM_SETCURSOR:
        # A hand, not the arrow: the window has no frame to hint with, and no title
        # bar to say it can be moved, so the cursor is the only affordance there is.
        handle = cursors.get("grabbing") if drag["active"] else cursors.get("grab")
        if handle:
            user32.SetCursor(handle)
            return 1
        return user32.DefWindowProcW(hwnd, message, wparam, lparam)
    if message == WM_NCHITTEST:
        # **The whole drag.** Answering `HTCAPTION` asks Windows to run its own move
        # loop, so dragging, snapping and the final position are the OS's business
        # rather than ours -- which is what a layered window was said not to allow.
        return HTCAPTION
    if message == WM_ENTERSIZEMOVE:
        drag["active"] = True
        drag["started_at"] = rect(hwnd)
        return 0
    if message == WM_MOVING:
        # Keep the closed hand for the duration. Note the return: `WM_MOVING` must go
        # to `DefWindowProc`, because that is what is allowed to **change the rect** --
        # answering "handled" here would switch snapping off.
        handle = cursors.get("grabbing")
        if handle:
            user32.SetCursor(handle)
        return user32.DefWindowProcW(hwnd, message, wparam, lparam)
    if message == WM_EXITSIZEMOVE:
        drag["active"] = False
        ended = rect(hwnd)
        moved = ended != drag["started_at"]
        say(
            "click" if not moved else "drag",
            start=list(drag["started_at"]),
            end=list(ended),
            moved=moved,
        )
        return 0
    if message in (WM_RBUTTONUP, WM_NCRBUTTONUP):
        say("closed by right-click")
        user32.DestroyWindow(hwnd)
        return 0
    if message == WM_CLOSE:
        user32.DestroyWindow(hwnd)
        return 0
    if message == WM_DESTROY:
        user32.PostQuitMessage(0)
        return 0
    if message == WM_ERASEBKGND:
        return 1
    return user32.DefWindowProcW(hwnd, message, wparam, lparam)


def compose() -> int:
    """The disc, a soft shadow, and the mark -- all of it alpha.

    The shadow is the one thing the region could never have: with per-pixel alpha it
    is just pixels at low opacity, fading outward, and the desktop shows through.
    """
    bitmap = Bitmap(SIZE, SIZE, PixelFormat.Format32bppArgb)
    graphics = Graphics.FromImage(bitmap)
    graphics.SmoothingMode = SmoothingMode.AntiAlias
    graphics.Clear(Color.Transparent)

    centre = SIZE / 2
    # A shadow: overlapping discs at low alpha, brightest nearest the card.
    for step in range(14, 0, -1):
        inset = 4 - step * 0.6
        alpha = int(9 * (1 - step / 14) ** 1.6)
        if alpha <= 0:
            continue
        graphics.FillEllipse(
            SolidBrush(Color.FromArgb(alpha, 0, 0, 0)),
            int(inset), int(inset), int(SIZE - inset * 2), int(SIZE - inset * 2),
        )

    graphics.FillEllipse(
        SolidBrush(Color.FromArgb(255, 32, 32, 32)), 8, 8, SIZE - 16, SIZE - 16
    )
    ink = SolidBrush(Color.FromArgb(255, 232, 232, 232))
    graphics.FillRectangle(ink, 36, 58, 108, 27)   # crossbar of the mark
    graphics.FillRectangle(ink, 79, 85, 22, 56)    # stem
    hole = SolidBrush(Color.FromArgb(255, 32, 32, 32))
    for cx in (66, 114):
        graphics.FillEllipse(hole, cx - 8, 66, 16, 17)
    graphics.Dispose()
    return bitmap.GetHbitmap(Color.FromArgb(0)).ToInt64()


def blit(hwnd: int, hbitmap: int) -> None:
    screen = user32.GetDC(None)
    memory = gdi32.CreateCompatibleDC(screen)
    gdi32.SelectObject(memory, hbitmap)
    size = wintypes.SIZE(SIZE, SIZE)
    source = wintypes.POINT(0, 0)
    destination = wintypes.POINT(*AT)
    blend = BLENDFUNCTION(AC_SRC_OVER, 0, 255, AC_SRC_ALPHA)
    user32.UpdateLayeredWindow(
        wintypes.HWND(hwnd), screen, ctypes.byref(destination), ctypes.byref(size),
        memory, ctypes.byref(source), 0, ctypes.byref(blend), ULW_ALPHA,
    )
    gdi32.DeleteDC(memory)
    user32.ReleaseDC(None, screen)
    gdi32.DeleteObject(hbitmap)


def main() -> None:
    bind()
    LOG.write_text("", encoding="utf-8")

    grab, grabbing = grab_cursor.load(pathlib.Path(".tmp-cursors"))
    cursors["grab"] = grab
    cursors["grabbing"] = grabbing

    wc = WNDCLASSEX()
    callback = WNDPROC(proc)
    _procs.append(callback)
    wc.cbSize = ctypes.sizeof(WNDCLASSEX)
    wc.lpfnWndProc = callback
    wc.hInstance = kernel32.GetModuleHandleW(None)
    # The class cursor is the fallback for anywhere `WM_SETCURSOR` is not sent.
    wc.hCursor = grab
    wc.lpszClassName = "ProtoCircle"
    if not user32.RegisterClassExW(ctypes.byref(wc)):
        raise SystemExit(f"RegisterClassExW failed: {ctypes.GetLastError()}")

    hwnd = user32.CreateWindowExW(
        WS_EX_LAYERED | WS_EX_TOPMOST | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW,
        "ProtoCircle", "TONYAgent circle prototype", WS_POPUP | WS_VISIBLE,
        AT[0], AT[1], SIZE, SIZE, None, None, kernel32.GetModuleHandleW(None), None,
    )
    if not hwnd:
        raise SystemExit(f"CreateWindowExW failed: {ctypes.GetLastError()}")

    blit(int(hwnd), compose())
    # Input only. The alpha is already zero at the rim, so this is invisible; it is
    # what keeps the corners click-through.
    user32.SetWindowRgn(wintypes.HWND(hwnd), gdi32.CreateEllipticRgn(0, 0, SIZE, SIZE), True)
    user32.ShowWindow(wintypes.HWND(hwnd), SW_SHOWNOACTIVATE)
    say("shown", at=list(AT), size=SIZE, hwnd=int(hwnd))

    message = wintypes.MSG()
    while user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
        user32.TranslateMessage(ctypes.byref(message))
        user32.DispatchMessageW(ctypes.byref(message))
    for handle in (grab, grabbing):
        user32.DestroyCursor(handle)
    say("gone")


if __name__ == "__main__":
    main()
