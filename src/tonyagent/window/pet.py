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
  window. So the card is **cut out instead of composited**: a window region takes
  the corners off (`win32.clip_to_circle`), and what is outside the circle is not
  part of the window at all -- nothing to be transparent, and a click there goes
  through to the desktop. The rim is hard because the OS clips rather than
  antialiases, and there can be no drop shadow because there is no window outside
  the circle to paint one in.

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

#: The card. Round, and **square because a circle needs a square to be cut out
#: of**: the window is a rectangle however hard the stylesheet tries, so the shape
#: comes from a window region (`win32.clip_to_circle`) and the region is the
#: ellipse inscribed in the window's box. Any other aspect would cut a circle
#: inside a rectangle and leave the bands beside it showing.
#:
#: 180x180 is a step down from the 236x248 it started at, and a step down again in
#: *painted* area -- a circle of 180 covers 25,400 square pixels against the
#: rectangle's 32,300. The room for the earlier reduction came out of the design
#: rather than the type: the "TONYAgent" row above the character went (the
#: character *is* the app's mark, so the row named something the artwork already
#: says), and the status line moved under the character where it reads as a caption.
WIDTH, HEIGHT = 180, 180

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

#: The preference that remembers **where** it was put, as ``[x, y]``.
#:
#: Remembered because dragging a card somewhere and having it come back in the
#: corner next launch is the same as not being able to move it. The corner is the
#: default, not the position.
POS_PREF = "pet_pos"


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
        #: What had the foreground before the card was created, so it can be given
        #: back once the card is up. See `_dress`.
        self._previous = 0
        #: Whether this window has been revealed and clipped yet. See `_dress`.
        self._dressed = False

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
            # **Nothing that needs the window's handle happens here**, because
            # there is no handle yet: see `_dress`.
            self._previous = before
            self._dressed = False
            self._dress_when_up(window)
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

        Dressing happens here too, as a third chance: the page saying it is
        listening is proof that the window is up, and it is the one signal the
        *page* can give. See `_dress`.
        """
        with self._lock:
            self._ready = True
        self._dress()
        if not self._dressed and self._window is not None:
            # The window exists and the page is talking to us, so a handle that
            # still cannot be read is not a matter of timing any more -- and this
            # is the warning that was missing when the card shipped as a rectangle.
            logger.warning("The pet window could not be clipped to a circle.")
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

    def drag(self) -> dict[str, Any]:
        """Hand the press to the OS's own move loop, and remember where it ended.

        **The OS's loop and not pywebview's `easy_drag`, and the difference is
        what dragging a window means.** `easy_drag` moves the form itself, one
        `SetWindowPos` per mouse move, and a window moved by hand is not a window
        the OS is dragging -- so it cannot be snapped anywhere. This is the same
        call the app's own title bar makes (`win32.begin_drag`), which is the code
        a decorated window runs: drag it to the top and it maximizes, drag it to a
        side and it takes that half.

        **The answer is the interesting half.** `SendMessage` does not return
        until the user lets go, so by then the card either moved or did not -- and
        a press that did not move it is a *click*, which is how the card raises the
        app. The page cannot tell the two apart on its own: once the modal loop
        starts, it receives no further pointer events, and a click that never
        arrives as a `click` event is exactly the bug that would make the card
        unable to open the app.

        Returning `{"moved": False}` for a refused gesture is deliberate rather
        than exceptional: on a backend with no window thread, or a handle that
        cannot be read, the honest thing is that the card did not move, which
        makes the press a click.
        """
        window = self._window
        if window is None:
            return {"moved": False, "x": 0, "y": 0}
        before = _position(window)
        hwnd = _handle(window)
        try:
            # Marshalled: see `win32.on_window_thread` for why a gesture issued
            # from the page's worker thread moves nothing at all.
            win32.on_window_thread(window, lambda: win32.begin_drag(hwnd))
        except Exception as exc:  # noqa: BLE001 - a tooltip cannot be worth a crash
            logger.debug(f"The pet could not be dragged: {exc}")
            return {"moved": False, "x": before[0], "y": before[1]}
        after = _position(window)
        if after != before:
            prefs.set(POS_PREF, list(after))
        return {"moved": after != before, "x": after[0], "y": after[1]}

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

    def _dress_when_up(self, window: Any) -> None:
        """Ask the window to say when it is really there, then dress it.

        Two events because one is not enough to be sure: `shown` fires when the
        form appears and `loaded` when the document is ready, and a backend that
        fires neither still gets dressed by `mark_ready`, which is the page
        telling us it is listening.
        """
        events = getattr(window, "events", None)
        for name in ("shown", "loaded"):
            event = getattr(events, name, None)
            if event is not None:
                event += self._dress

    def _dress(self, *_args: Any) -> None:
        """Put the card's shape on it, and give the foreground back.

        **Both of these need the window's handle, and the handle does not exist
        when the window is asked for.** Measured: `Window.native` is `None` when
        `create_window` returns, stays `None` for about three quarters of a second,
        and `shown` fires shortly after it appears. This used to run in `open()`,
        so it ran with a null handle every single time and returned silently --
        which is why the pet shipped as a rectangle with a circle drawn inside it,
        *and* why the foreground the card steals on creation had never once been
        given back: `_reveal` was called from the same place and did nothing.

        Idempotent, and it refuses to mark itself done while there is no handle, so
        the later event or the page's own `ready` gets another go.
        """
        window = self._window
        if window is None or self._dressed:
            return
        if _handle(window) == 0:
            return
        self._dressed = True
        _reveal(window, self._previous)
        _clip(window)

    def _create_window(self, page: str, x: int, y: int) -> Any:
        return _create_window(page, x, y, self._api)

    def _corner(self) -> tuple[int, int]:
        """Where the card goes when it opens: where it was left, or the corner.

        The work area rather than the screen: it is the screen minus the taskbar
        and anything else docked to it, so the pet sits above the taskbar instead
        of behind it. Read from the monitor the *app* is on, so on two screens the
        pet appears where the user is looking.

        A remembered position wins, **clamped into the work area**. The monitor
        that position was measured on may be gone -- undocked, unplugged, or
        rearranged -- and restoring a card at x=3400 on a machine that now has one
        screen puts it somewhere the user cannot see or reach it. There is nothing
        to drag it back by, because it is not on screen to be pressed.
        """
        try:
            area = win32.work_area(0)
        except Exception as exc:  # noqa: BLE001 - a placement is not a reason to refuse
            logger.debug(f"Could not read the work area for the pet: {exc}")
            return 0, 0
        saved = _saved_position()
        if saved is not None:
            return _clamp(area, saved[0], saved[1], WIDTH, HEIGHT)
        return _bottom_right(area, WIDTH, HEIGHT)

    def _closed(self) -> None:
        """Forget the window so the next press makes a new one.

        Nothing waits here -- see ``AccountBrowser._closed``: this runs on the
        window's thread while `open` may hold the lock asking that same thread to
        create a window, so taking the lock would deadlock both.
        """
        self._window = None
        self._ready = False
        self._dressed = False

    def _forget(self) -> None:
        with self._lock:
            self._window = None
            self._ready = False
            self._dressed = False


def _bottom_right(area: Any, width: int, height: int) -> tuple[int, int]:
    """Where the card goes inside a work area. A pure function, so it is testable."""
    return int(area.right) - width - MARGIN, int(area.bottom) - height - MARGIN


def _clamp(area: Any, x: int, y: int, width: int, height: int) -> tuple[int, int]:
    """The nearest position that keeps the whole card inside the work area.

    Whole card rather than a corner of it: a card showing 20px of itself along an
    edge is a card you cannot read and cannot grab.
    """
    left, top = int(area.left), int(area.top)
    right = max(int(area.right) - width, left)
    bottom = max(int(area.bottom) - height, top)
    return min(max(int(x), left), right), min(max(int(y), top), bottom)


def _saved_position() -> tuple[int, int] | None:
    """The remembered position, or None when there is not a readable one.

    Anything unreadable -- absent, the wrong shape, a float, a string -- is None
    rather than an error: this decides where a decoration appears, and the corner
    is a perfectly good answer.
    """
    saved = prefs.get(POS_PREF)
    if not isinstance(saved, (list, tuple)) or len(saved) != 2:
        return None
    try:
        return int(saved[0]), int(saved[1])
    except (TypeError, ValueError):
        return None


def _position(window: Any) -> tuple[int, int]:
    """The card's screen position, as the window itself reports it.

    pywebview's own ``x``/``y`` rather than ``GetWindowRect``: it is the same
    number without a second Win32 call, and it is what a fake window in a test can
    answer without a GUI.
    """
    try:
        return int(window.x), int(window.y)
    except Exception as exc:  # noqa: BLE001 - an unaskable window is not a fatal one
        logger.debug(f"Could not read the pet window's position: {exc}")
        return 0, 0


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
    """Put a freshly created card in front without letting it keep the keyboard.

    Two halves, and both are needed. The card is raised with ``SWP_NOACTIVATE``,
    which is the polite version; and then the foreground is *handed back* to
    whatever had it, because the polite version is not enough: pywebview's hidden
    path shows the form before hiding it, and that first show is an activation
    nothing on this side can refuse. Measured on the real desktop, both before and
    after the hidden flag was added -- the card came back as
    ``GetForegroundWindow()`` either way.

    **Called from `_dress`, which is later than it looks.** The hand-back needs the
    window's handle, and the handle does not exist until the GUI loop creates the
    form -- about three quarters of a second after `create_window` returns. This
    used to be called straight from `open()` with a null handle, so the hand-back
    had never actually happened and the card did keep the keyboard. It is safe
    later because `give_foreground_back` only gives it back if the card still has
    it: by the time it runs, anything the user has clicked since is the answer
    instead.

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


def _clip(window: Any) -> None:
    """Take the window's corners off, so the card is the circle it draws.

    The stylesheet can only *draw* a circle: the window underneath it stays a
    rectangle, and its corners are painted by the OS. A window region is what
    makes the shape real -- and it is also what makes the corners click-through,
    which is the difference between a round pet and a rectangle pretending.

    The region is computed from the window's real box, not from `WIDTH`/`HEIGHT`;
    see `win32.clip_to_circle`, where getting that wrong left a slab of window
    beside the circle.

    Failure is logged rather than raised. A card that could not be clipped is a
    square card, which is what the pet was until now; refusing to open one would be
    a decoration failing at the thing it decorates.
    """
    hwnd = _handle(window)
    if not hwnd:
        return
    try:
        win32.clip_to_circle(hwnd)
    except Exception as exc:  # noqa: BLE001 - see the docstring
        logger.warning(f"The pet window could not be clipped to a circle: {exc}")


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
        # **`min_size` is not optional here, and it is what made the card a
        # rectangle.** pywebview's WinForms backend sets the form's
        # ``MinimumSize`` from this argument, whose default is ``200x100`` -- so a
        # card asked for at 180 came back **200x141**, and the circle cut inside it
        # left a slab of window beside itself. Measured through ``GetWindowRect``
        # on a real window, which is also how the region came to be computed from
        # the window's own box rather than from these two numbers.
        min_size=(WIDTH, HEIGHT),
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
        #
        # **`easy_drag` is off, and the page drags it instead.** pywebview's own
        # drag moves the form one `SetWindowPos` per mouse move, which looks the
        # same and is not: the OS is not dragging it, so it cannot be snapped, and
        # the host never learns where it ended up. `DeskPet.drag` runs the real
        # move loop and saves the position -- see its docstring.
        easy_drag=False,
        on_top=True,
        # Not activated, ever: this is the flag that lets the user keep typing
        # while the agent works, and `WS_EX_NOACTIVATE` is how it is enforced.
        focus=False,
        text_select=False,
        background_color="#1a1a1a",
    )
