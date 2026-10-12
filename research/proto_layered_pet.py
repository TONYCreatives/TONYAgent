"""Prototype: a native layered pet window with a genuinely antialiased rim.

The mechanism this proves, because it is the whole bet of the raster path and it can
be checked in one run:

1. A plain Win32 popup with `WS_EX_LAYERED` + `WS_EX_TOPMOST` + `WS_EX_NOACTIVATE`
   draws per-pixel alpha through `UpdateLayeredWindow`, so the **rim is antialiased**
   (pixels strictly between the card's colour and the backdrop -- the acceptance test
   from the brief, which a GDI region cannot pass).
2. The **region does not conflict with that**: it is kept only for input, so the
   corners stay click-through (`WindowFromPoint` at a corner answers the window
   *behind*, not the pet). It is never visible, because the alpha has faded to nothing
   before the region's edge.
3. The card is composed with **GDI+ from primitives**, not from pre-rendered
   Playwright sprites: the character is two rects, circles and lines, so it can be
   drawn live and animated by parameter rather than by blitting frames.

Every function is declared with argtypes and restypes, because the first version of
this file did not and failed exactly the way that always fails on 64-bit: `GetDC`
truncated to an `int`, a .NET `IntPtr` reaching ctypes unconverted, and
`DefWindowProcW`'s `lparam` overflowing a 32-bit `LPARAM`.

Run: python research/proto_layered_pet.py
"""

import ctypes
import json
import os
import pathlib
import threading
import time
from ctypes import wintypes

import clr  # noqa: F401 - loads the CLR before System.Drawing can be referenced

clr.AddReference("System.Drawing")
from System.Drawing import Bitmap, Color, Graphics, SolidBrush  # noqa: E402
from System.Drawing.Drawing2D import SmoothingMode  # noqa: E402
from System.Drawing.Imaging import PixelFormat  # noqa: E402

SIZE = 180
PET_AT = (300, 300)
BACKDROP_AT = (60, 60)
BACKDROP_SIZE = 500
OUT = pathlib.Path(".tmp-layered-probe.json")

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32
kernel32 = ctypes.windll.kernel32

#: Handles are pointer-sized; `WPARAM`/`LPARAM` are pointer-sized too. Getting any of
#: these as `int`/`c_long` truncates on 64-bit, which is what the first run did.
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

WM_ERASEBKGND = 0x0014
WM_PAINT = 0x000F


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


class PAINTSTRUCT(ctypes.Structure):
    """`ctypes.wintypes` has no `PAINTSTRUCT`, so it is declared here."""

    _fields_ = [
        ("hdc", wintypes.HDC),
        ("fErase", wintypes.BOOL),
        ("rcPaint", wintypes.RECT),
        ("fRestore", wintypes.BOOL),
        ("fIncUpdate", wintypes.BOOL),
        ("rgbReserved", ctypes.c_byte * 32),
    ]


def bind() -> None:
    """Declare every function, because the defaults are wrong on 64-bit."""
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
    user32.WindowFromPoint.argtypes = [wintypes.POINT]
    user32.WindowFromPoint.restype = wintypes.HWND
    user32.GetDC.argtypes = [wintypes.HWND]
    user32.GetDC.restype = wintypes.HDC
    user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
    user32.ReleaseDC.restype = ctypes.c_int
    user32.SetWindowRgn.argtypes = [wintypes.HWND, ctypes.c_void_p, wintypes.BOOL]
    user32.SetWindowRgn.restype = ctypes.c_int
    user32.BeginPaint.argtypes = [wintypes.HWND, ctypes.POINTER(PAINTSTRUCT)]
    user32.BeginPaint.restype = wintypes.HDC
    user32.EndPaint.argtypes = [wintypes.HWND, ctypes.POINTER(PAINTSTRUCT)]
    user32.EndPaint.restype = wintypes.BOOL
    user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.GetClientRect.restype = wintypes.BOOL
    user32.FillRect.argtypes = [wintypes.HDC, ctypes.POINTER(wintypes.RECT), wintypes.HBRUSH]
    user32.FillRect.restype = ctypes.c_int
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
    gdi32.CreateSolidBrush.argtypes = [wintypes.COLORREF]
    gdi32.CreateSolidBrush.restype = wintypes.HBRUSH
    gdi32.CreateEllipticRgn.argtypes = [ctypes.c_int] * 4
    gdi32.CreateEllipticRgn.restype = ctypes.c_void_p


_procs: list = []  # the WNDPROC callbacks must outlive the windows


def register(name: str, proc) -> None:
    _procs.append(proc)
    wc = WNDCLASSEX()
    wc.cbSize = ctypes.sizeof(WNDCLASSEX)
    wc.lpfnWndProc = proc
    wc.hInstance = kernel32.GetModuleHandleW(None)
    wc.hCursor = user32.LoadCursorW(None, wintypes.LPCWSTR(IDC_ARROW))
    wc.lpszClassName = name
    if not user32.RegisterClassExW(ctypes.byref(wc)):
        raise OSError(f"RegisterClassExW failed for {name}: {ctypes.GetLastError()}")


def backdrop_proc(hwnd, message, wparam, lparam):
    if message == WM_ERASEBKGND:
        return 1
    if message == WM_PAINT:
        paint = PAINTSTRUCT()
        hdc = user32.BeginPaint(hwnd, ctypes.byref(paint))
        rect = wintypes.RECT()
        user32.GetClientRect(hwnd, ctypes.byref(rect))
        brush = gdi32.CreateSolidBrush(0x00FFFFFF)
        user32.FillRect(hdc, ctypes.byref(rect), brush)
        gdi32.DeleteObject(brush)
        user32.EndPaint(hwnd, ctypes.byref(paint))
        return 0
    return user32.DefWindowProcW(hwnd, message, wparam, lparam)


def pet_proc(hwnd, message, wparam, lparam):
    if message == WM_ERASEBKGND:  # a layered window must not paint itself
        return 1
    return user32.DefWindowProcW(hwnd, message, wparam, lparam)


def compose_frame(blink: float) -> int:
    """The card, drawn from primitives with antialiasing. Returns an HBITMAP.

    A dark disc, the app's mark in two rects, and eyes whose height is the blink --
    the shapes the page already draws, so this is a port rather than a second design.
    """
    bitmap = Bitmap(SIZE, SIZE, PixelFormat.Format32bppArgb)
    graphics = Graphics.FromImage(bitmap)
    graphics.SmoothingMode = SmoothingMode.AntiAlias
    graphics.Clear(Color.Transparent)

    graphics.FillEllipse(
        SolidBrush(Color.FromArgb(255, 32, 32, 32)), 1, 1, SIZE - 2, SIZE - 2
    )

    ink = SolidBrush(Color.FromArgb(255, 232, 232, 232))
    graphics.FillRectangle(ink, 30, 52, 120, 30)  # crossbar
    graphics.FillRectangle(ink, 78, 82, 24, 62)   # stem

    hole = SolidBrush(Color.FromArgb(255, 32, 32, 32))
    eye_h = max(2, int(20 * blink))
    for cx in (62, 118):
        graphics.FillEllipse(hole, cx - 9, 62 + (20 - eye_h) // 2, 18, eye_h)
    graphics.Dispose()
    return bitmap.GetHbitmap(Color.FromArgb(0)).ToInt64()


def blit(hwnd: int, hbitmap: int) -> None:
    screen = user32.GetDC(None)
    memory = gdi32.CreateCompatibleDC(screen)
    gdi32.SelectObject(memory, hbitmap)
    size = wintypes.SIZE(SIZE, SIZE)
    source = wintypes.POINT(0, 0)
    destination = wintypes.POINT(PET_AT[0], PET_AT[1])
    blend = BLENDFUNCTION(AC_SRC_OVER, 0, 255, AC_SRC_ALPHA)
    ok = user32.UpdateLayeredWindow(
        wintypes.HWND(hwnd), screen, ctypes.byref(destination), ctypes.byref(size),
        memory, ctypes.byref(source), 0, ctypes.byref(blend), ULW_ALPHA,
    )
    gdi32.DeleteDC(memory)
    user32.ReleaseDC(None, screen)
    gdi32.DeleteObject(hbitmap)
    if not ok:
        raise OSError(f"UpdateLayeredWindow refused the frame: {ctypes.GetLastError()}")


def probe() -> dict:
    from PIL import ImageGrab

    left, top = PET_AT
    image = ImageGrab.grab(
        bbox=(left, top, left + SIZE, top + SIZE), all_screens=True
    ).convert("RGB")
    row = [image.getpixel((x, SIZE // 2)) for x in range(SIZE)]
    blends = [x for x, (r, g, b) in enumerate(row) if 60 < (r + g + b) / 3 < 220]
    return {
        "corners": [
            list(image.getpixel(p))
            for p in ((2, 2), (SIZE - 3, 2), (2, SIZE - 3), (SIZE - 3, SIZE - 3))
        ],
        "centre": list(image.getpixel((SIZE // 2, SIZE // 2))),
        "blend_pixels_on_the_midline": len(blends),
        "blend_run": [blends[0], blends[-1]] if blends else None,
        "unique_colours": len(image.getcolors(maxcolors=1 << 24) or []),
        "row_start": [list(row[i]) for i in range(12)],
        "row_end": [list(row[i]) for i in range(SIZE - 12, SIZE)],
        "corner_owner_hwnd": int(
            user32.WindowFromPoint(wintypes.POINT(left + 2, top + 2)) or 0
        ),
    }


def main() -> None:
    bind()
    notes: dict[str, object] = {}
    register("ProtoBackdrop", WNDPROC(backdrop_proc))
    register("ProtoPet", WNDPROC(pet_proc))
    instance = kernel32.GetModuleHandleW(None)

    backdrop = user32.CreateWindowExW(
        WS_EX_TOPMOST, "ProtoBackdrop", "backdrop", WS_POPUP | WS_VISIBLE,
        BACKDROP_AT[0], BACKDROP_AT[1], BACKDROP_SIZE, BACKDROP_SIZE,
        None, None, instance, None,
    )
    pet = user32.CreateWindowExW(
        WS_EX_LAYERED | WS_EX_TOPMOST | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW,
        "ProtoPet", "pet", WS_POPUP | WS_VISIBLE,
        PET_AT[0], PET_AT[1], SIZE, SIZE, None, None, instance, None,
    )
    notes["backdrop_hwnd"] = int(backdrop or 0)
    notes["pet_hwnd"] = int(pet or 0)
    notes["pet_created"] = bool(pet)

    ex = user32.GetWindowLongW(pet, GWLP_EXSTYLE)
    notes["pet_ex_style"] = hex(ex & 0xFFFFFFFF)
    notes["pet_layered"] = bool(ex & WS_EX_LAYERED)
    notes["pet_noactivate"] = bool(ex & WS_EX_NOACTIVATE)
    notes["pet_topmost"] = bool(ex & WS_EX_TOPMOST)

    def pump() -> None:
        message = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(message))
            user32.DispatchMessageW(ctypes.byref(message))

    threading.Thread(target=pump, daemon=True).start()
    user32.ShowWindow(pet, SW_SHOWNOACTIVATE)
    time.sleep(0.4)

    blit(int(pet), compose_frame(blink=1.0))
    # Input only, and deliberately the size of the alpha disc: it is never visible,
    # because the coverage has faded to nothing before the region's edge.
    user32.SetWindowRgn(pet, gdi32.CreateEllipticRgn(0, 0, SIZE, SIZE), True)
    notes["region_set"] = True
    time.sleep(1.0)

    result = probe()
    result["corner_owner_is_pet"] = result["corner_owner_hwnd"] == int(pet)
    notes["probe"] = result

    # A second frame: animation is a re-compose and a re-blit, nothing else.
    blit(int(pet), compose_frame(blink=0.15))
    time.sleep(0.5)
    notes["blinked"] = probe()["blend_pixels_on_the_midline"]

    OUT.write_text(json.dumps(notes, indent=2, default=str), encoding="utf-8")
    os._exit(0)


if __name__ == "__main__":
    main()
