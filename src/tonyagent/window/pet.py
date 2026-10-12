"""The desktop pet: a small window that says what the agent is doing.

The point is not decoration, it is **leaving**. A long turn is thirty seconds to
ten minutes of the app being the most important window on the screen, and the
only way to watch it used to be to keep looking at it. The pet is a second,
smaller window that carries the same answer -- what it is doing right now, and
whether it needs you -- while the app itself goes behind whatever else you are
using.

**Four measured facts decide the shape of it**, and they were measured on this
machine through ``Window.get_window_long`` and a screen capture, not assumed:

* ``focus=False`` gives the window ``WS_EX_NOACTIVATE`` -- the OS does not
  activate it and it never takes the foreground. That is what makes the pet
  usable while you type somewhere else; without it, every status update would
  pull the keyboard away from you.
* ``on_top=True`` sets ``TopMost``, so it stays above whatever you moved to.
* ``frameless`` and non-resizable, because it is a card rather than a window.
* **``transparent=True` does nothing here.** pywebview leaves the form opaque:
  ``WS_EX_LAYERED`` is unset, ``AllowTransparency`` is ``False`` and the pixels
  beside the artwork came back as the control grey rather than the window behind
  it. Setting the form's ``TransparencyKey`` by hand through pythonnet hung the
  window. So the pet is an opaque rounded card and is drawn as one -- a cut-out
  character is not available in this shell, and pretending otherwise would ship a
  grey rectangle with a character floating in it.

**The status arrives from the page, not from the core.** The app window is
already the thing that reduces the core's event stream into "busy", "which tool",
"waiting for an answer", and a second reducer here would be a second opinion
about it. So the page pushes what to display and this window only draws it.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from typing import Any

from loguru import logger

from tonyagent.window import prefs, win32

#: The JS global a status is pushed into. Each window has its own, so this is the
#: same name the app's page installs -- see `bridge.TARGET`.
PUSH_TARGET = "window.__tonyAgent"

TITLE = "TONYAgent"

#: The card. Narrow enough to sit in a corner without covering anything, tall
#: enough for the character and two lines of text at the app's own type scale.
WIDTH, HEIGHT = 236, 248

#: How far from the corner of the work area it starts -- clear of the taskbar it
#: already excludes, and far enough in that it does not look clipped to the edge.
MARGIN = 24

#: What it says when nothing has happened yet, and what a fresh window draws
#: before any status has arrived.
#:
#: **The keys are the card's, not the host's.** This goes over the same wire as
#: every other status and is validated by the card's ``readStatus``, which drops
#: anything without a ``mood`` it recognises -- so a default written in some other
#: vocabulary is not a default at all, it is a frame the card silently discards in
#: favour of its own. The two spellings are therefore the same one, and this is a
#: copy of ``petcard.PET_IDLE`` rather than a second opinion about it.
IDLE: dict[str, str] = {"mood": "idle", "label": "Ready when you are", "detail": ""}

#: The preference that remembers whether it was up.
OPEN_PREF = "pet_open"


class DeskPet:
    """The pet window, created on demand and remembered across restarts."""

    def __init__(
        self,
        page: str = "",
        api: Any = None,
        create: Callable[..., Any] | None = None,
    ) -> None:
        #: The `pet.html` URL. Empty means the frontend the window is serving has
        #: no pet page, and `set_open(True)` then honestly reports it cannot open.
        self._page = page
        #: The same `Bridge` the app's window carries, so the pet's page can ask
        #: the host for things -- it calls `pet("ready")` and `pet("focus")`.
        self._api = api
        #: Injected by the tests, which have no GUI loop to create a window on.
        self._create = create or self._create_window
        self._window: Any = None
        self._app: Any = None
        self._ready = False
        self._status: dict[str, Any] = dict(IDLE)
        self._lock = threading.Lock()

    # -- what the page asks ---------------------------------------------------

    def set_open(self, open_: bool) -> dict[str, Any]:
        """Show or hide the pet, and remember the answer.

        Remembered here rather than in the page because it has to survive the
        page: the app reloads its frontend on a rebuild, and a pet that vanished
        every time would be a pet nobody keeps.
        """
        prefs.set(OPEN_PREF, bool(open_))
        if not open_:
            self.close()
            return {"open": False}
        return {"open": self.open()}

    def open(self) -> bool:
        """Create the window if it is not there. Returns whether one is up."""
        with self._lock:
            if self._window is not None:
                _bring_to_front(self._window)
                return True
            if not self._page:
                logger.warning("The pet was asked for, but this build has no pet page.")
                return False
            x, y = self._corner()
            # Whatever has the foreground now, so it can be given back. Read
            # before the window exists, because creating one takes it and nothing
            # here can refuse that. See `win32.give_foreground_back`.
            before = _foreground()
            window = self._create(self._page, x, y)
            if window is None:
                logger.warning("The webview refused the pet window.")
                return False
            self._window = window
            # Not ready until the page says so. `evaluate_js` before the document
            # is ready does not fail, it deadlocks -- see `Bridge.ready` -- so the
            # first status waits for `mark_ready` rather than being sent here.
            self._ready = False
            _reveal(window, before)
            window.events.closed += self._closed
            return True

    def close(self) -> None:
        """Take it down, if it is up."""
        window = self._window
        if window is None:
            return
        try:
            window.destroy()
        except Exception as exc:  # noqa: BLE001 - a dead window is the goal
            logger.debug(f"The pet window could not be closed: {exc}")
        self._forget()

    def mark_ready(self) -> dict[str, Any]:
        """The pet's page is listening; send it what it should be drawing.

        A push before this would deadlock, and a push after it has already been
        sent would be a window that renders empty until something happens. Both
        are avoided by keeping the last status rather than sending it hopefully.
        """
        with self._lock:
            self._ready = True
        self.push(self._status)
        return {"open": self._window is not None}

    def push(self, status: dict[str, Any]) -> dict[str, Any]:
        """Remember a status and, if the pet is drawing, draw it."""
        self._status = dict(status or IDLE)
        window = self._window
        if window is None or not self._ready:
            return {"open": window is not None}
        try:
            payload = json.dumps(self._status, ensure_ascii=False)
            window.evaluate_js(f"{PUSH_TARGET}.onStatus({payload})")
        except Exception as exc:  # noqa: BLE001 - a lost frame is not fatal
            logger.debug(f"The pet did not take a status: {exc}")
        return {"open": True}

    def was_open(self) -> bool:
        """Whether it was up last time the app ran. What the toggle starts from."""
        return bool(prefs.get(OPEN_PREF, False))

    # -- internals ------------------------------------------------------------

    def is_open(self) -> bool:
        """Whether a window is up. The toggle draws itself from this."""
        return self._window is not None

    def raise_app(self) -> bool:
        """Bring the app's own window forward. What clicking the card does.

        Restore first: the app is usually behind something else and often
        minimized, and ``show()`` alone on a minimized window leaves it in the
        taskbar. Activating is intended here for once -- the user just clicked
        the pet -- which is the one moment it is not rude to take the foreground.
        """
        window = self._app
        if window is None:
            return False
        window.restore()
        window.show()
        return True

    def attach_app(self, window: Any) -> None:
        """Remember which window is *the app*, so the pet can raise it."""
        self._app = window

    def _create_window(self, page: str, x: int, y: int) -> Any:
        return _create_window(page, x, y, self._api)

    def _corner(self) -> tuple[int, int]:
        """The bottom-right of the work area, in screen coordinates.

        The work area rather than the screen: it is the screen minus the taskbar
        and anything else docked to it, so the pet sits above the taskbar instead
        of behind it. Read from the monitor the *app* is on, so on two screens the
        pet appears where the user is looking.
        """
        try:
            return _bottom_right(win32.work_area(0), WIDTH, HEIGHT)
        except Exception as exc:  # noqa: BLE001 - a placement is not a reason to refuse
            logger.debug(f"Could not read the work area for the pet: {exc}")
            return 0, 0

    def _closed(self) -> None:
        """Forget the window so the next press makes a new one.

        Nothing waits here -- see ``AccountBrowser._closed``: this runs on the
        window's thread while `open` may hold the lock asking that same thread to
        create a window, so taking the lock would deadlock both.
        """
        self._window = None
        self._ready = False

    def _forget(self) -> None:
        with self._lock:
            self._window = None
            self._ready = False


def _bottom_right(area: Any, width: int, height: int) -> tuple[int, int]:
    """Where the card goes inside a work area. A pure function, so it is testable."""
    return int(area.right) - width - MARGIN, int(area.bottom) - height - MARGIN


def _handle(window: Any) -> int:
    """The card's top-level handle, or zero when there is none to ask.

    ``GetAncestor(..., GA_ROOT)`` rather than the handle pywebview hands out,
    which belongs to the webview control nested inside the form -- the same walk
    ``Bridge._hwnd`` makes, and for the same reason.
    """
    native = getattr(window, "native", None)
    if native is None:
        return 0
    try:
        return win32.root_window(int(native.Handle.ToInt64()))
    except Exception as exc:  # noqa: BLE001 - an unaskable window is not a fatal one
        logger.debug(f"Could not read the pet window's handle: {exc}")
        return 0


def _reveal(window: Any, previous: int = 0) -> None:
    """Put a freshly created card on screen, and undo the activation it caused.

    Two halves, and both are needed. The window is created hidden and revealed
    with ``SWP_NOACTIVATE``, which is the polite version; and then the foreground
    is *handed back* to whatever had it, because the polite version is not enough:
    pywebview's hidden path shows the form before hiding it, and that first show
    is an activation nothing on this side can refuse. Measured on the real
    desktop, both before and after the hidden flag was added -- the card came back
    as ``GetForegroundWindow()`` either way.

    Neither half is allowed to raise. The card is created *visible* -- creating it
    hidden and showing it here was measured costing it ``WS_EX_TOPMOST`` and
    ``WS_EX_NOACTIVATE`` without stopping the activation -- so a failed
    ``SetWindowPos`` leaves a card that is on screen and not at the front, which is
    a cosmetic loss. Raising on this path would turn "the pet is behind something"
    into "the pet button does nothing".
    """
    hwnd = _handle(window)
    try:
        win32.raise_without_activating(hwnd)
    except Exception as exc:  # noqa: BLE001 - see the docstring
        logger.debug(f"Could not raise the card without activating it: {exc}")
    # Unconditionally, and *after* the attempt above: the activation this is
    # undoing was caused by creating the window, so a card that could not be
    # raised still took the foreground and still has to give it back.
    try:
        win32.give_foreground_back(previous, hwnd)
    except Exception as exc:  # noqa: BLE001 - a foreground that stays stolen is not fatal
        logger.debug(f"Could not give the foreground back after the card opened: {exc}")


def _foreground() -> int:
    """The foreground handle, or 0 where there is no such idea."""
    try:
        return win32.foreground_window()
    except Exception as exc:  # noqa: BLE001 - see the docstring
        logger.debug(f"Could not read the foreground window: {exc}")
        return 0


def _bring_to_front(window: Any) -> None:
    """Show the card again after something hid it.

    No ``restore()``: the pet has no maximize box and cannot be minimized by the
    user, so calling it would be a state change nothing asked for.
    """
    window.show()


def _create_window(page: str, x: int, y: int, api: Any = None) -> Any:
    """The card itself. See the module docstring for each flag's measurement."""
    import webview

    return webview.create_window(
        TITLE,
        url=page,
        js_api=api,
        width=WIDTH,
        height=HEIGHT,
        x=x,
        y=y,
        frameless=True,
        resizable=False,
        # **Not `hidden=True`, and that is a measurement.** Creating the card hidden
        # and revealing it with `SWP_NOACTIVATE` looked like the tidy way to avoid
        # the one activation a new window gets, and on the real desktop it did not
        # stop it -- the card still came back as `GetForegroundWindow()` -- while
        # it *did* come back without `WS_EX_TOPMOST` or `WS_EX_NOACTIVATE`, which
        # are the two styles that make it a pet at all. So it is created visible
        # and the foreground is handed back afterwards instead; see `_reveal`.
        # The whole card is the handle. The app's own window renounces this --
        # there, a window where nothing can be selected or pressed is useless --
        # but a card you drag out of the way by its artwork is the point.
        easy_drag=True,
        on_top=True,
        # Not activated, ever: this is the flag that lets the user keep typing
        # while the agent works, and `WS_EX_NOACTIVATE` is how it is enforced.
        focus=False,
        text_select=False,
        background_color="#1a1a1a",
    )
