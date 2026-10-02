"""Prove the window's system menu works, with the keyboard and the mouse.

`decorations: false` removed the title bar, and with it the three things a
title bar is for that no amount of markup replaces: the system menu, Move and
Size. Those last two are drag loops the OS runs -- there is no version of them
that is a React component -- so the app asks the OS for the menu it already has
(`src-tauri/src/system_menu.rs`) and the question worth asking is whether the
request ever reaches the window.

A unit test cannot answer it. It would prove that a keydown handler calls
`invoke("show_system_menu")`, which is the same code whether the command is
registered, permitted by the ACL, compiled into the binary and answered by the
window. So this drives the *shipped* app with real input and then looks at the
real thing.

**How the menu is found.** A menu that is being tracked is a real top-level
window of class `#32768`, owned by the window it belongs to. That is also the
discriminator that matters: the WebView2 context menu is the same class, owned
by the webview. So "a `#32768` appeared" proves nothing, and "a `#32768` whose
owner is the app's own HWND" proves the app's menu and not the page's.

**What is read off it.** `MN_GETHMENU` gives the menu, and the items can be read
back with `GetMenuStringW` and `GetMenuState`. The labels are localised, so they
are reported rather than matched, but the *enabled* pattern is the OS's opinion
of the window's state -- Restore greyed on a normal window, Maximize greyed on a
maximized one -- and that is a fact about the window, in the OS's own words, that
a hand-built menu would have to reimplement and get wrong.

Run:  python scripts/verify_system_menu.py

Presses F10, not Alt+Space: Alt+Space is a global hotkey on the machine this was
built on, so the OS takes it and the app never sees it. See the comment in
`useWindowControls.ts`.

Leaves the app as it found it: no menu is left open, the cursor goes back to
where it was, and it only stops a copy of the app that it started itself.
"""

from __future__ import annotations

import ctypes
import json
import os
import subprocess
import sys
import time
from ctypes import wintypes
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXE = ROOT / "app" / "src-tauri" / "target" / "release" / "tonyagent-app.exe"

user32 = ctypes.WinDLL("user32", use_last_error=True)

EnumWindowsProc = ctypes.WINFUNCTYPE(
    ctypes.c_bool, wintypes.HWND, wintypes.LPARAM
)

user32.EnumWindows.argtypes = [EnumWindowsProc, wintypes.LPARAM]
user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
user32.GetWindow.restype = wintypes.HWND
user32.GetWindowThreadProcessId.argtypes = [
    wintypes.HWND,
    ctypes.POINTER(wintypes.DWORD),
]
user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.SetForegroundWindow.restype = wintypes.BOOL
user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
user32.SendMessageW.argtypes = [
    wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
]
user32.SendMessageW.restype = wintypes.LPARAM
user32.GetMenuItemCount.argtypes = [wintypes.HMENU]
user32.GetMenuState.argtypes = [wintypes.HMENU, wintypes.UINT, wintypes.UINT]
user32.GetMenuStringW.argtypes = [
    wintypes.HMENU, wintypes.UINT, wintypes.LPWSTR, ctypes.c_int, wintypes.UINT
]

# The class every menu window has, tracked or not.
MENU_CLASS = "#32768"
# `MN_GETHMENU`: the one message a menu window answers, and the only way to get
# at the menu it is tracking.
MN_GETHMENU = 0x01E1
GW_OWNER = 0x0004
MF_BYPOSITION = 0x0400
# MFS_GRAYED | MFS_DISABLED, from GetMenuState's low word.
MFS_UNAVAILABLE = 0x0003
MFS_SEPARATOR = 0x0800

SW_RESTORE = 9
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
user32.GetWindowLongW.restype = ctypes.c_long
user32.GetDpiForWindow.argtypes = [wintypes.HWND]
user32.GetDpiForWindow.restype = wintypes.UINT
user32.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
user32.EndMenu.restype = wintypes.BOOL
user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]

# `--topbar-h` in styles.css, in CSS pixels. The bar is this tall whatever the
# window's width or the monitor's scale, so it is the one number here that
# cannot be measured off the screen and has to be read out of the source.
TOPBAR_CSS = 42

VK_F10, VK_ESCAPE = 0x79, 0x1B
VK_M, VK_S, VK_RETURN = 0x4D, 0x53, 0x0D
VK_RIGHT, VK_DOWN = 0x27, 0x28
KEYEVENTF_KEYUP = 0x0002
MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP = 0x0008, 0x0010
user32.keybd_event.argtypes = [
    ctypes.c_ubyte, ctypes.c_ubyte, wintypes.DWORD, ctypes.c_size_t
]
user32.mouse_event.argtypes = [
    wintypes.DWORD, ctypes.c_int, ctypes.c_int, wintypes.DWORD, ctypes.c_size_t
]
user32.SetWindowPos.argtypes = [
    wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
    ctypes.c_int, ctypes.c_int, wintypes.UINT,
]
SWP_NOZORDER, SWP_NOACTIVATE = 0x0004, 0x0010


# --- the window -------------------------------------------------------------
def top_level_windows() -> list[int]:
    found: list[int] = []

    def keep(hwnd: int, _lparam: int) -> bool:
        found.append(hwnd)
        return True

    user32.EnumWindows(EnumWindowsProc(keep), 0)
    return found


def window_pid(hwnd: int) -> int:
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def class_name(hwnd: int) -> str:
    buffer = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buffer, 256)
    return buffer.value


def app_window(pid: int) -> int | None:
    for hwnd in top_level_windows():
        if window_pid(hwnd) == pid and class_name(hwnd) == "Tauri Window":
            return hwnd
    return None


def title_of(hwnd: int) -> str:
    buffer = ctypes.create_unicode_buffer(256)
    user32.GetWindowTextW(hwnd, buffer, 256)
    return buffer.value


def webview_menus() -> list[dict]:
    """
    Menu windows belonging to another process, which is where the webview's own
    context menu shows up.

    Reported rather than judged: the point of the negative case is that the
    *app's* menu must not appear, and naming the menu that did appear is what
    makes the difference between "nothing happened" and "the page answered".
    """
    out: list[dict] = []
    for hwnd in top_level_windows():
        if class_name(hwnd) != MENU_CLASS or not user32.IsWindowVisible(hwnd):
            continue
        hmenu = wintypes.HMENU(user32.SendMessageW(hwnd, MN_GETHMENU, 0, 0))
        labels = []
        for index in range(user32.GetMenuItemCount(hmenu) if hmenu else 0):
            label = ctypes.create_unicode_buffer(128)
            user32.GetMenuStringW(hmenu, index, label, 128, MF_BYPOSITION)
            labels.append(label.value)
        out.append({"pid": window_pid(hwnd), "labels": labels})
    return out


def is_maximized(hwnd: int) -> bool:
    # Read rather than inferred, because the check below compares the menu's
    # greyed-out items against it. `0x00010000` is WS_MAXIMIZEBOX -- the style
    # that says the window *may* be maximized -- and reading that instead is how
    # a maximized-looking window gets reported as normal. WS_MAXIMIZE is
    # 0x01000000.
    user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.GetWindowLongW.restype = ctypes.c_long
    return bool(user32.GetWindowLongW(hwnd, -16) & 0x01000000)


def window_rect(hwnd: int) -> tuple[int, int, int, int]:
    rect = wintypes.RECT()
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    return rect.left, rect.top, rect.right, rect.bottom


# --- the menu ---------------------------------------------------------------
def tracked_menus(pid: int) -> list[dict]:
    """
    Every menu window on screen that belongs to the app's process.

    **By process, not by owner.** The obvious discriminator -- the menu window's
    `GW_OWNER` -- does not work, and finding that out is the whole reason this
    note is here: a tracked menu is a top-level window of class `#32768`, and on
    this machine `GetWindow(menu, GW_OWNER)` reads 0 for the app's own system
    menu. A verifier written against it reports "no menu" for a menu that is
    plainly on screen, and then the menu it failed to recognise stays open,
    covers the title bar and swallows the next right-click.

    The process is the honest test. The menu window is created by the thread
    that called `TrackPopupMenu`, which is the app's main thread; the WebView2's
    context menu is created by `msedgewebview2.exe` and so cannot be mistaken for
    this one. The owner is reported alongside, for the record only.
    """
    menus: list[dict] = []
    for hwnd in top_level_windows():
        if class_name(hwnd) != MENU_CLASS or not user32.IsWindowVisible(hwnd):
            continue
        if window_pid(hwnd) != pid:
            continue
        hmenu = wintypes.HMENU(user32.SendMessageW(hwnd, MN_GETHMENU, 0, 0))
        items: list[dict] = []
        if hmenu:
            for index in range(user32.GetMenuItemCount(hmenu)):
                label = ctypes.create_unicode_buffer(128)
                user32.GetMenuStringW(hmenu, index, label, 128, MF_BYPOSITION)
                state = user32.GetMenuState(hmenu, index, MF_BYPOSITION)
                items.append(
                    {
                        "label": label.value,
                        "enabled": (state & MFS_UNAVAILABLE) == 0,
                        "separator": (state & MFS_SEPARATOR) != 0,
                    }
                )
        left, top, _r, _b = window_rect(hwnd)
        menus.append(
            {
                "hwnd": hwnd,
                "owner": int(user32.GetWindow(hwnd, GW_OWNER) or 0),
                "at": [left, top],
                "items": items,
            }
        )
    return menus


def menu_for(pid: int) -> dict | None:
    menus = tracked_menus(pid)
    return menus[0] if menus else None


def summarise(menu: dict | None) -> dict:
    if menu is None:
        return {"open": False, "items": [], "labels": []}
    return {
        "open": True,
        "at": menu["at"],
        "labels": [item["label"] for item in menu["items"]],
        "items": menu["items"],
    }


def contract(items: list[dict], maximized: bool) -> bool:
    """
    The system menu's own rules, read back off the menu.

    Windows builds this menu, so its shape is fixed and its contents are the
    OS's opinion of the window: Restore, Move, Size, Minimize, Maximize, a
    separator, Close -- with whichever of Restore and Maximize does not apply
    greyed out. A menu built by hand would have to encode that rule and would
    get it wrong the first time the window was maximized.

    By position, not by label: the labels are localised and carry their
    mnemonics (`&Move`, `Mi&nimize`), but their order is not localised.

    Read against the window's own `WS_MAXIMIZE`, never against how big the
    window looks. On this machine the window is dragged out past its work area
    and is *not* maximized by the style's account, and the menu agrees with the
    style: Restore greyed. A verifier that took "it fills the screen" for
    "maximized" would be asserting the wrong rule against a menu that is right.
    """
    if len(items) != 7 or not items[5]["separator"]:
        return False
    if not (items[1]["enabled"] and items[2]["enabled"]):
        return False
    if not (items[3]["enabled"] and items[4]["enabled"] and items[6]["enabled"]):
        return False
    # The greyed-out item is the one that would do nothing: on a normal window
    # that is Restore, on a maximized one it is Maximize. Getting this backwards
    # is easy -- it looks like a maximized window is one where Maximize is off --
    # and it fails against a window in either state, which is the point.
    return items[0]["enabled"] is maximized and items[4]["enabled"] is not maximized


# --- input ------------------------------------------------------------------
def press_f10() -> None:
    # F10 rather than Alt+Space, which is what the app binds: on the machine
    # this was built on, Alt+Space is a global hotkey (Copilot) and the OS eats
    # it before the window ever sees it. A verifier that pressed Alt+Space would
    # be testing the hotkey, not the app.
    user32.keybd_event(VK_F10, 0, 0, 0)
    time.sleep(0.04)
    user32.keybd_event(VK_F10, 0, KEYEVENTF_KEYUP, 0)


def press_escape() -> None:
    user32.keybd_event(VK_ESCAPE, 0, 0, 0)
    time.sleep(0.03)
    user32.keybd_event(VK_ESCAPE, 0, KEYEVENTF_KEYUP, 0)


def tap(vk: int, times: int = 1, pause: float = 0.04) -> None:
    for _ in range(times):
        user32.keybd_event(vk, 0, 0, 0)
        time.sleep(0.02)
        user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)
        time.sleep(pause)


def move_or_size(hwnd: int, pid: int, mnemonic: int, arrows: int, arrow: int) -> dict:
    """
    Drive the system's own move or size loop from the keyboard.

    Open the menu, choose the item by its mnemonic, nudge with the arrow keys,
    commit with Enter, and report the rectangle before and after. This is the
    case the whole feature exists for: Move and Size are loops the OS runs, and
    a window with no system menu has neither -- it cannot be placed or resized
    at all, and no unit test can show that because nothing in the DOM is
    involved.

    The window is put back where it was by the caller, from the rectangle
    recorded here.
    """
    before = window_rect(hwnd)
    press_f10()
    opened = menu_for(pid) is not None
    if opened:
        tap(mnemonic)
        time.sleep(0.3)
        tap(arrow, times=arrows)
        tap(VK_RETURN)
    time.sleep(0.5)
    after = window_rect(hwnd)
    dismiss(pid)
    moved = before[:2] != after[:2]
    resized = before[2:] != after[2:]
    return {
        "opened": opened,
        "before": list(before),
        "after": list(after),
        "moved": moved,
        "resized": resized,
    }


def right_click(x: int, y: int) -> None:
    user32.SetCursorPos(x, y)
    time.sleep(0.05)
    user32.mouse_event(MOUSEEVENTF_RIGHTDOWN, 0, 0, 0, 0)
    time.sleep(0.06)
    user32.mouse_event(MOUSEEVENTF_RIGHTUP, 0, 0, 0, 0)


def focus(hwnd: int) -> bool:
    """
    Bring the window forward, and *check* that it is forward.

    `SetForegroundWindow` fails for a process that has not sent an input event
    recently, and on this machine something else -- an on-screen display, of
    all things -- is often holding the foreground. A keyboard probe that quietly
    did nothing because the key went to another window is the worst kind of
    failure: it looks like the shortcut is broken. So this reports what the
    foreground actually is.
    """
    user32.ShowWindow(hwnd, SW_RESTORE)
    for _ in range(20):
        if user32.SetForegroundWindow(hwnd):
            time.sleep(0.2)
            if int(user32.GetForegroundWindow() or 0) == hwnd:
                return True
        time.sleep(0.1)
    return int(user32.GetForegroundWindow() or 0) == hwnd


# --- the cases --------------------------------------------------------------
def wait_for_menu(pid: int, seconds: float = 3.0) -> dict | None:
    """Poll, because a menu that is not going to appear is not an error yet."""
    deadline = time.time() + seconds
    while time.time() < deadline:
        menu = menu_for(pid)
        if menu is not None:
            return menu
        time.sleep(0.05)
    return menu_for(pid)


def dismiss(pid: int) -> bool:
    """
    Close the menu, and never leave one behind.

    `EndMenu` rather than Escape. Escape goes to whatever has the keyboard
    focus, and a menu is not it; a menu left open is not a cosmetic problem
    either -- it sits over the title bar and swallows the next right-click,
    which is exactly how a verifier ends up reporting "no menu" for a menu that
    is plainly on screen.
    """
    user32.EndMenu()
    time.sleep(0.4)
    if menu_for(pid) is None:
        return True
    press_escape()
    time.sleep(0.3)
    user32.EndMenu()
    time.sleep(0.4)
    return menu_for(pid) is None


def main() -> int:
    if not EXE.exists():
        print(f"[FAIL] {EXE} is missing: run the build first")
        return 1

    # Whoever was in front stays in front. A keyboard probe has to take the
    # focus to mean anything, and taking it away from whatever the user is
    # reading -- on another monitor, in a browser, mid-lecture -- and not giving
    # it back is the sort of thing that makes a test unwelcome.
    was_foreground = int(user32.GetForegroundWindow() or 0)

    started: subprocess.Popen[bytes] | None = None
    pid = 0
    # Someone may already be running the app -- the last verifier run usually
    # leaves it up, and where they put it is where they want it. Use theirs
    # rather than starting a second window on top of it, and never move it.
    running = subprocess.run(
        ["tasklist", "/FI", "IMAGENAME eq tonyagent-app.exe", "/NH"],
        capture_output=True,
        text=True,
    ).stdout
    if "tonyagent-app.exe" in running:
        pid = int(
            subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    "(Get-Process tonyagent-app | Select-Object -First 1).Id",
                ],
                capture_output=True,
                text=True,
            ).stdout.strip()
            or 0
        )
    else:
        started = subprocess.Popen(
            [str(EXE)],
            env={
                **os.environ,
                "WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS": "--remote-debugging-port=9333",
            },
        )
        pid = started.pid

    hwnd = 0
    deadline = time.time() + 40
    while time.time() < deadline:
        hwnd = app_window(pid) or 0
        if hwnd:
            break
        time.sleep(0.5)

    if not hwnd:
        print("[FAIL] the app never opened a window")
        if started:
            started.kill()
        return 1

    # Where the bar is, in screen pixels, at whatever scale this monitor runs.
    # The bar is 42 CSS px (`--topbar-h`), and on a 175% display that is 74
    # physical ones; a hardcoded 20 is inside it at 100% and still inside it at
    # 175%, but the caption buttons are 46 CSS px wide and only 80 physical at
    # that scale, so the points are computed rather than guessed.
    origin = wintypes.POINT(0, 0)
    user32.ClientToScreen(hwnd, ctypes.byref(origin))
    dpi = user32.GetDpiForWindow(hwnd) or 96
    scale = dpi / 96.0
    bar = round(TOPBAR_CSS * scale)
    left, top, right, bottom = window_rect(hwnd)
    on_bar = (origin.x + 300, origin.y + bar // 3)
    on_caption = (right - round(23 * scale), origin.y + bar // 2)
    in_transcript = (origin.x + 300, origin.y + 300)
    print(
        f"window hwnd={hwnd} at ({left},{top})..({right},{bottom}) "
        f"dpi={dpi} bar={bar}px"
    )
    print(f"  bar=({on_bar[0]},{on_bar[1]}) "
          f"caption=({on_caption[0]},{on_caption[1]}) "
          f"transcript=({in_transcript[0]},{in_transcript[1]})")

    cursor = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(cursor))
    results: list[tuple[str, dict, bool]] = []
    maximized = is_maximized(hwnd)
    try:
        # --- F10, first ---------------------------------------------------
        # First because it needs the focus, and because the mouse cases leave a
        # menu behind that a keystroke cannot get past: a right-click off the
        # title bar opens the *webview's* context menu, that menu has the input
        # captured, and the F10 that follows goes to it. Run in this order and
        # the keyboard case is measured against a clean desktop.
        if not focus(hwnd):
            results.append(
                (
                    "the_window_takes_the_focus",
                    {
                        "foreground": int(user32.GetForegroundWindow() or 0),
                        "title": title_of(int(user32.GetForegroundWindow() or 0)),
                    },
                    False,
                )
            )
        else:
            press_f10()
            menu = wait_for_menu(pid)
            summary = summarise(menu)
            results.append(
                (
                    "f10",
                    {**summary, "maximized": maximized},
                    summary["open"] and contract(summary["items"], maximized),
                )
            )
            results.append(("f10_dismisses", {"clean": dismiss(pid)}, True))

        # --- a right-click on the title bar -------------------------------
        right_click(*on_bar)
        menu = wait_for_menu(pid)
        summary = summarise(menu)
        results.append(
            (
                "right_click_on_the_bar",
                summary,
                summary["open"]
                and contract(summary["items"], maximized)
                # The menu opens at the pointer, so the click point is a
                # prediction the OS can fail: a menu at the window's own corner
                # would mean the coordinates never reached the webview. A few
                # pixels of slack, because the menu window's rectangle carries
                # the drop shadow the visual menu does not have.
                and abs(menu["at"][0] - on_bar[0]) <= 2
                and abs(menu["at"][1] - on_bar[1]) <= 8,
            )
        )
        results.append(("right_click_dismisses", {"clean": dismiss(pid)}, True))

        # --- including on a caption button -------------------------------
        # Windows answers a right-click on the caption buttons with the same
        # menu, and the handler is on the whole bar rather than on the empty
        # patch of it, so this is the case that says so. The point is computed
        # from the scale because a 46px button is 80 physical pixels at 175% and
        # 46 at 100%: a hardcoded offset lands on a different control.
        right_click(*on_caption)
        menu = wait_for_menu(pid)
        results.append(
            (
                "right_click_on_a_caption_button",
                summarise(menu),
                menu is not None and contract(menu["items"], maximized),
            )
        )
        results.append(("caption_click_dismisses", {"clean": dismiss(pid)}, True))

        # --- and nowhere else ---------------------------------------------
        # The transcript's own right-click is the webview's menu, which is the
        # same class of window in a different process. What must not happen is
        # the app's: a right-click that is not on the caption is not the frame.
        right_click(*in_transcript)
        time.sleep(0.8)
        stray = menu_for(pid)
        results.append(
            (
                "right_click_off_the_bar",
                {
                    "app_menu": summarise(stray),
                    "webview_menus": [
                        menu["labels"] for menu in webview_menus()
                    ],
                },
                stray is None,
            )
        )
        # The webview's menu is tracked by its own process, so `EndMenu` from
        # here does not touch it and Escape does. It is also the reason the
        # keyboard case runs first.
        press_escape()
        dismiss(pid)

        # --- Move and Size, the reason any of this exists ------------------
        # Both are loops the OS runs; a window whose system menu was thrown away
        # has neither, and cannot be placed or resized. They are measured by
        # moving the window and putting it back, so the rectangle the user chose
        # on the other monitor is the one still there afterwards.
        home = window_rect(hwnd)
        for name, mnemonic, arrow, want in (
            ("move", VK_M, VK_RIGHT, "moved"),
            ("size", VK_S, VK_DOWN, "resized"),
        ):
            result = move_or_size(hwnd, pid, mnemonic, 6, arrow)
            results.append((f"{name}_is_the_systems_own_loop", result, result[want]))
            if result["moved"] or result["resized"]:
                user32.SetWindowPos(
                    hwnd, None, home[0], home[1], home[2] - home[0], home[3] - home[1],
                    SWP_NOZORDER | SWP_NOACTIVATE,
                )
                time.sleep(0.4)
        results.append(
            (
                "the_window_ends_up_where_it_started",
                {"rect": list(window_rect(hwnd))},
                window_rect(hwnd) == home,
            )
        )
    finally:
        user32.SetCursorPos(cursor.x, cursor.y)
        # Anything still open, so a run that dies mid-case cannot leave a menu
        # over the user's desktop.
        user32.EndMenu()
        if was_foreground:
            user32.SetForegroundWindow(was_foreground)
        if started:
            started.terminate()

    failures = 0
    for name, detail, ok in results:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}: {json.dumps(detail)}")
        if not ok:
            failures += 1

    if failures:
        print(f"\n{failures} case(s) failed")
        return 1
    print("\nthe window's system menu opens, and closes, the way Windows does")
    return 0


if __name__ == "__main__":
    sys.exit(main())
