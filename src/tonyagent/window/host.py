"""The desktop window: a native window around the built frontend.

This is the whole shell now. It replaces a Rust crate, a cargo build, a Windows
SDK requirement and a frozen sidecar with one Python module, because the shell
was only ever doing four things:

1. serve the built HTML to a webview,
2. start the Python core as a child process,
3. carry messages between the page and the core,
4. ask Windows for the two window features markup cannot draw.

Everything else -- conversation state, tools, sandboxing, and every pixel of the
interface -- is the same code it was. The frontend is unchanged apart from the
one module that talks to the shell, and the core does not know it has moved.

**Why a webview and not a browser.** "Open the HTML in a window" has two
readings and only one of them is this app. A browser tab is a page with someone
else's chrome around it: no custom title bar, no caption buttons the app draws,
no drag region, no bridge to a local process, and a back button the user did not
ask for. A webview is the rendering engine *without* the browser around it --
the same engine, in a window this program owns -- which is exactly what the
Tauri build was, and what every Electron app is.

**Why the frontend is still a separate build step.** It is Vite, and it stays
Vite: type-checking, JSX, CSS modules and the test suite all live there, and
rewriting that in Python would be a much larger change than this one. What went
away is the *Rust* half of the build, which is the half that needed cargo, an
`rc.exe` from a Windows SDK, and a target triple in a filename.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

import webview
from loguru import logger

from tonyagent.window import win32
from tonyagent.window.assets import AssetServer, MissingFrontendError
from tonyagent.window.bridge import Bridge
from tonyagent.window.core import CoreProcess, default_argv, source_env
from tonyagent.window.pet import DeskPet

#: The size the interface was designed against.
WIDTH, HEIGHT = 1200, 800

#: The smallest the window may be made -- and, less obviously, **the number that
#: decides whether a half-screen snap can happen at all**.
#:
#: It was 900x600, carried over from `tauri.conf.json` unchanged, and that is
#: wider than half of a 1440-wide screen. Dragging the window to the left edge
#: therefore snapped it to *900* wide instead of 720: it took the left half and
#: 180px of the right one. Measured through the real move loop on this machine's
#: 1440x900 display. Windows honours the minimum, so a window that cannot be half
#: the screen cannot be snapped to half the screen, and no amount of getting the
#: gesture right was going to change that.
#:
#: 640 is half of a 1280-wide display, the narrowest worth supporting, and 480 is
#: half of a 960-tall one. The interface is cramped at that size -- the composer
#: and what is left of the transcript -- but "too small to be pretty" is a better
#: failure than "the snap the user asked for did not happen".
MIN_WIDTH, MIN_HEIGHT = 640, 480

#: The app field. This is what the webview paints *before* the page loads, and
#: a dark app that flashes white on every launch is the one thing it cannot
#: hide. It matches `--app-field` in tokens.css.
BACKGROUND = "#1a1a1a"

#: What the drag region is, as a class. The *behaviour* is the app's own now --
#: see `main` -- so this name is the frontend's, and pywebview's selector does
#: not match it. The two must agree with `DRAG_REGION_CLASS` in the frontend's
#: `useWindowControls.ts`, which is the other half of the arrangement.
DRAG_CLASS = "app-drag-region"


def build_window(page: str, bridge: Bridge) -> webview.Window | None:
    """The window itself, undecorated and square until Windows is asked."""
    return webview.create_window(
        "TONYAgent",
        url=page,
        js_api=bridge,
        width=WIDTH,
        height=HEIGHT,
        min_size=(MIN_WIDTH, MIN_HEIGHT),
        resizable=True,
        # The app draws its own title bar, so the OS must not draw one too.
        frameless=True,
        # Off deliberately. `easy_drag` makes the *whole* window a drag handle,
        # which is a window where no text can be selected and no button can be
        # pressed -- the opposite of what a chat app needs. The drag regions
        # carry `DRAG_CLASS` and the host runs the OS's move loop for them, so
        # dragging works exactly where a title bar is and nowhere else.
        easy_drag=False,
        # The DWM frame, and this is what makes the corners roundable at all.
        #
        # It was `False`, on the reasoning that an OS shadow is drawn around a
        # decorated window's frame and there is no frame here. That was backwards.
        # pywebview's `shadow` is what calls `DwmExtendFrameIntoClientArea` -- a
        # 1px DWM frame -- and with no frame there is nothing for DWM to round, so
        # `DWMWA_WINDOW_CORNER_PREFERENCE` is accepted and then ignored.
        #
        # Measured, not reasoned: with `shadow=False` the window's style is
        # `WS_CAPTION` off, `WS_THICKFRAME` off, `WS_POPUP` off -- no frame at all
        # -- and the corner preference reads back as 0 (default). With it on, the
        # preference reads back as 2 and the corner pixels are the desktop's.
        # `scripts/verify_window.py` is what measured it, and it still does.
        shadow=True,
        background_color=BACKGROUND,
    )


def _startup(window: webview.Window) -> None:
    """Runs once the window exists and the GUI loop is up.

    Rounded corners are a DWM attribute of the top-level window, so they need a
    real handle and cannot happen at `create_window` time.

    **Applied twice, and the second time is the one that counts.** Setting the
    attribute from here -- after `start()` has called this, but before the form is
    on screen -- is *accepted and then discarded*: DWM reports it as 0 (default)
    a moment later, and the corners are square. Measured, not guessed. So it is
    set here as well as on `shown`, and the repeat costs nothing: it is one
    attribute on a window that already exists.

    A failure is logged and swallowed. Rounded corners are cosmetic, and
    refusing to open the window over them would turn a small loss into no app at
    all. This is the same judgement the Rust shell made, and it was right.
    """
    def apply(first_attempt: bool = False) -> None:
        """Apply the corners, tolerating the attempt that is deliberately early.

        The handle does not exist until the form does, and `_startup` runs before
        that -- so the *first* attempt finding no handle is the expected case and
        not a warning. It was one, and the log read

            WARNING | host:apply - The window has no native handle, so it cannot
                      be styled: 'NoneType' object has no attribute 'Handle'

        for a launch whose corners were round. The second attempt, on `shown`, is
        the one that counts, and there a missing handle is worth saying out loud.
        """
        try:
            native = window.native
            hwnd = win32.root_window(int(native.Handle.ToInt64()))
        except Exception as exc:  # noqa: BLE001 - a missing handle is not fatal
            say = logger.debug if first_attempt else logger.warning
            say(f"The window has no native handle, so it cannot be styled: {exc}")
            return
        try:
            win32.round_corners(hwnd)
        except Exception as exc:  # noqa: BLE001 - cosmetic
            logger.info(f"Rounded corners unavailable: {exc}")
        # The frame, which is what makes the window resizable and -- the part
        # that is easy to lose -- snappable. Both calls are idempotent, which is
        # what makes the repeat on `shown` the same call twice rather than a
        # second, different one.
        # The procedure first, then the style. The order is load-bearing:
        # installing the procedure is what makes the *next* frame computation
        # answer "no non-client area", and adding `WS_THICKFRAME` is what asks
        # for one. The other way round computes the frame under WinForms and the
        # page is left inset from the window's own edge.
        try:
            win32.install_frame(hwnd)
            win32.make_resizable(hwnd)
        except Exception as exc:  # noqa: BLE001 - a window that cannot resize
            logger.warning(f"The window could not be made resizable: {exc}")

    apply(first_attempt=True)

    # `shown` is the one that survives. pywebview fires it when the form is
    # actually on screen -- and it is the only moment at which `window.native` is
    # reliably there. A lambda rather than `apply` itself, because pywebview's
    # `Event.set` decides how to call a handler by counting its parameters, and a
    # zero-argument handler is the one case it calls with no arguments at all.
    try:
        window.events.shown += lambda: apply()
    except Exception as exc:  # noqa: BLE001 - not worth refusing to open over
        logger.debug(f"Could not follow the window's shown event: {exc}")


def has_console() -> bool:
    """Whether this process has a console for its log to go to.

    **Not `sys.stderr is not None`.** Under `pythonw` on Python 3.13 that is
    false: the interpreter hands out a `TextIOWrapper` for stderr anyway, and
    writes to it go nowhere. Measured -- the repr of `(sys.stdout, sys.stderr)`
    under `pythonw` is two wrappers, not `None, None`. So the question is asked
    of the OS, which is the thing that actually knows.

    A platform without `GetConsoleWindow` falls back to the standard streams,
    and a failure to ask assumes there *is* a console: moving the log to a file
    nobody expects is worse than leaving it where it already was.
    """
    if sys.platform != "win32":
        return sys.stderr is not None
    try:
        import ctypes

        return bool(ctypes.windll.kernel32.GetConsoleWindow())  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001 - see the docstring
        return True


def _log_without_a_console() -> None:
    """Keep the host's own log when there is no console to write it to.

    The launcher starts this with ``pythonw``, which is the GUI-subsystem
    interpreter: no console window appears beside the app. That is the right
    trade for something opened from a shortcut -- two windows for one app is not
    what "open it" should look like -- but it would also mean a startup failure
    said nothing anywhere, and a window that never appears with no message is the
    worst version of that.

    Only the host's own lines. The core's stderr is a separate channel and still
    reaches the app's log strip, which is the one a user can actually read.

    Written beside ``config.toml``, so there is one directory to look in. A log
    file that cannot be opened is not a reason to refuse to start -- but the
    reason is printed, because "the log is not where you think it is" is exactly
    the kind of thing this function exists to prevent.
    """
    if has_console():
        return
    try:
        from tonyagent.config.settings import settings

        path = settings.get_config_dir() / "window.log"
        logger.remove()
        logger.add(path, level="INFO", encoding="utf-8", rotation="1 MB")
        logger.info(f"No console, so the host's log is going to {path}")
    except Exception as exc:  # noqa: BLE001 - see the docstring
        logger.warning(f"Could not move the host's log to a file: {exc}")


def profile_dir() -> str:
    """The webview's own profile on disk, which is what keeps a sign-in.

    **This is the whole of "you sign in once".** pywebview defaults to
    ``private_mode``, which gives every run a fresh temporary cache directory:
    a window that is signed in and a window that has never been anywhere look
    identical, so the provider's page would ask for the sign-in again on every
    launch -- the one thing that makes a browser pane not worth having.

    Its own subdirectory of the config directory, beside ``config.toml`` and
    ``window.log``, so there is one directory to look in, and named for what it
    is rather than for the window that writes it: the account browser is not the
    only thing that could use it.

    A directory that cannot be made is not a reason to refuse to start --
    pywebview falls back to its own default -- but it is a reason to say so.
    """
    try:
        from tonyagent.config.settings import settings

        path = settings.get_config_dir() / "webview"
        path.mkdir(parents=True, exist_ok=True)
        return str(path)
    except Exception as exc:  # noqa: BLE001 - see the docstring
        logger.warning(f"Could not prepare the webview profile directory: {exc}")
        return ""


def main(argv: Sequence[str] | None = None) -> int:
    """Open the window. Returns the process's exit code."""
    _log_without_a_console()
    parser = argparse.ArgumentParser(
        prog="python -m tonyagent.window",
        description="Open the TONYAgent window.",
    )
    parser.add_argument(
        "--dist",
        help="the built frontend to serve (default: app/dist beside this repo)",
    )
    parser.add_argument(
        "--url",
        help=(
            "load the page from this URL instead of serving a build, which is "
            "how a Vite dev server is used -- it gets hot reload, at the cost "
            "of the window being a second thing to keep running"
        ),
    )
    parser.add_argument(
        "--no-core",
        action="store_true",
        help="open the window without starting a core, to work on the interface alone",
    )
    args = parser.parse_args(argv)

    server: AssetServer | None = None
    if args.url:
        page = args.url
    else:
        server = AssetServer(Path(args.dist) if args.dist else default_dist())
        try:
            page = f"{server.start()}/index.html"
        except MissingFrontendError as exc:
            logger.error(str(exc))
            return 2

    # Built in this order because of the cycle: the core needs the bridge's push
    # handlers to construct, and the bridge needs the core to answer `send`.
    # Neither can be a constructor argument -- see `Bridge.__init__`.
    #
    # `_frames` and friends are private because pywebview exposes every public
    # member of the js_api to the page, and these three are the host's own side
    # of the conversation. Reaching them by name from here is the intended
    # direction; the page has `send` and nothing else.
    bridge = Bridge()
    core = CoreProcess(
        default_argv(),
        bridge._frames,
        on_stderr=bridge._log,
        on_exit=bridge._core_exit,
        env=source_env(),
    )
    if not args.no_core:
        core.start()

    window = build_window(page, bridge)
    if window is None:
        logger.error("The webview refused to create a window.")
        return 3
    bridge._attach(core, window)

    # The desktop pet, built from the same bundle as the app. It is wired here
    # rather than inside `Bridge` because the URL it is served from is the host's
    # to know -- and because it needs the bridge as its page's `js_api`, which is
    # the same cycle `_attach` above describes.
    bridge._attach_pet(DeskPet(sibling_page(page, "pet.html"), api=bridge))

    # Dragging is the app's own now, and pywebview's is left to find nothing.
    #
    # `pywebview-drag-region` used to be the whole mechanism: pywebview watches
    # for a press on that class and *moves the window itself*, from JavaScript,
    # with a `SetWindowPos` per mouse move. That works, and it is also why the
    # window could never be snapped -- a window moved by hand is not a window the
    # OS is dragging, so the drag-to-the-top maximize, the half-screen tiles and
    # the snap previews simply never happen. The frontend's regions carry
    # `app-drag-region` instead and ask the host to start the OS's own move loop.
    #
    # No setting is changed to switch it off. `customize.js` looks for
    # `.pywebview-drag-region`, nothing in the page carries that class any more,
    # and its walk over the pressed element's ancestors finds nothing to do.

    try:
        # `private_mode=False` and a profile on disk, rather than pywebview's
        # default of a fresh temporary cache per run. The account browser is a
        # real browser at the provider's own site, and a browser that has signed
        # in and a browser that has never been anywhere are the same window
        # unless the cookies outlive the process. See `profile_dir`.
        webview.start(
            _startup,
            (window,),
            icon=app_icon(),
            private_mode=False,
            storage_path=profile_dir(),
        )
    finally:
        # In a `finally` and not in a close callback: the core has to be reaped
        # whether the window was closed, the page died, or this process was
        # asked to stop. An orphaned core still holds the sandbox and the API
        # key, with nobody left to show its errors to.
        core.stop()
        if server is not None:
            server.stop()
    return 0


def sibling_page(page: str, name: str) -> str:
    """Another page beside the one the app was pointed at.

    The pet and the account reader are built from the same bundle as the app, so
    their URLs differ from the app's only in the filename -- which works for a
    served build and for ``--url`` pointing at a Vite dev server without either
    case knowing about the other. A page that is not there is not an error here:
    the reader reports it cannot open, and the pet reports it cannot open.
    """
    head, _, _tail = page.rpartition("/")
    return f"{head}/{name}" if head else name


def default_dist() -> Path:
    """The built frontend, found relative to this file rather than to the cwd.

    Walked up rather than taken from the working directory: the host is started
    by a double-clicked launcher, whose working directory is whatever the shell
    that spawned it had, so a relative path would make the app work from one
    shortcut and not from another.
    """
    return Path(__file__).resolve().parents[3] / "app" / "dist"


def app_icon() -> str | None:
    """The window's icon, or ``None`` when the art is not there.

    The `.ico` rather than the `.png`: Windows wants a multi-resolution icon for
    the taskbar, the Alt+Tab switcher and the caption, and pywebview hands this
    straight to the form. The icons came with the shell and outlived it -- they
    moved from `src-tauri/icons/` to `app/icons/` when the Rust crate went away.

    Missing is not fatal, which is why this returns ``None`` instead of raising:
    a window with the default icon is a cosmetic difference, and refusing to open
    over one would turn that into no app at all. Same judgement as the corners.
    """
    icon = Path(__file__).resolve().parents[3] / "app" / "icons" / "icon.ico"
    return str(icon) if icon.is_file() else None


if __name__ == "__main__":
    raise SystemExit(main())

