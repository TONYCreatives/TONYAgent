"""The page's whole view of the host: ``window.pywebview.api``.

This is the replacement for three Tauri surfaces at once -- the shell plugin's
child process, the dialog plugin's folder picker, and the window API's caption
buttons -- and it is deliberately one object rather than three. All of them are
"the page asking the program it is running inside for something", which is one
relationship, and splitting it would have meant three bridge objects registered
on one window for no gain.

The two directions are not symmetrical, and the asymmetry is the point:

* **page -> host** is a method call. pywebview runs it on a worker thread and
  answers the page with a promise, so every method here returns as soon as it
  has done its part and none of them waits for the core.
* **core -> page** is a push. ``evaluate_js`` from the pump thread lands in the
  page as a plain function call, which is what the Tauri build had too: the
  frontend's transport is a callback that receives lines, and nothing above it
  knows which shell produced them.

So ``send`` does not await a reply. The reply comes back as a pushed frame and
the frontend's own request-id routing -- which is tested, and which did not
change -- pairs them up.

**Everything on this class is private except the page's own API, and that is a
rule rather than a style.** pywebview builds the page's API by walking ``dir()``
of this object, skipping names that begin with an underscore, and -- for any
public name that is *not* a method -- recursing into it. Both halves of that
have bitten this file:

* a public ``self.window`` would hand the page pywebview's entire Window API,
  because the walk descends into it;
* a public ``maximized`` *property* was **evaluated** by that walk, and reading
  the maximized state touches the WinForms control's handle -- which the walk
  does off the GUI thread. That deadlocked the window before it finished
  loading, with no error anywhere.

So the public methods below are the page's API and nothing else is public. The
push handlers are private for the same reason in the other direction: the page
has no business calling ``_frames`` to invent core output.
"""

from __future__ import annotations

import json
import threading
from typing import Any

from loguru import logger

from tonyagent.window import win32
from tonyagent.window.account import DEFAULT_VIEW, AccountBrowser
from tonyagent.window.pet import DeskPet

#: Everything ``window_control`` accepts, as a closed set rather than a
#: passthrough: the page is not trusted with an arbitrary window command just
#: because it can reach one.
#:
#: ``drag`` and ``resize`` are gestures rather than caption buttons, and they are
#: here because the page is the only thing that knows where the title bar and the
#: window's edges are. Both hand the press straight to the OS's own loops -- see
#: ``win32`` -- which is what makes Aero Snap and the drag-to-the-top maximize
#: the real ones instead of an imitation of them.
ACTIONS = frozenset({"minimize", "toggleMaximize", "close", "drag", "resize"})

#: Everything the desktop pet can be asked, as a closed set for the same reason
#: as ``ACTIONS``.
#:
#: ``state`` and the two that change it are the app page's -- it draws the toggle
#: and has to be able to ask whether the card is up. ``ready``, ``status`` and
#: ``focus`` are the pet's own: the first two are how the card announces itself
#: and receives what to draw, and the last is what clicking it does. Both pages
#: share one bridge, so the closed set is what keeps one from pretending to be the
#: other.
PET_ACTIONS = frozenset({"state", "show", "hide", "ready", "status", "focus"})

#: The JavaScript object the host pushes into. One global, installed by the
#: frontend's own entry point, so a push cannot arrive before anything is
#: listening and silently do nothing.
TARGET = "window.__tonyAgent"


class Bridge:
    """The ``js_api`` object: everything the page may ask the host to do."""

    def __init__(
        self,
        account: AccountBrowser | None = None,
        pet: DeskPet | None = None,
    ) -> None:
        #: The provider's own pages, in a browser window the app owns. Injected
        #: so a test can watch what the page asked for without a GUI loop; the
        #: default constructs nothing until the first view is opened.
        self._account = account if account is not None else AccountBrowser()
        #: The desktop pet. Injected by the host, which is the only thing that
        #: knows the URL the card's page is served from -- see `_attach_pet`.
        self._pet = pet if pet is not None else DeskPet()
        # Both are assigned rather than injected, and that is a real cycle
        # rather than a preference. The bridge pushes frames the core produces,
        # so the core needs `bridge._frames` at construction; and
        # `webview.create_window` has to be called before the bridge can name a
        # window. Neither can be a constructor argument, so `_attach` does it,
        # immediately afterwards, and both are only ever read from callbacks
        # that cannot fire before then -- the page has to load first.
        self._core: Any = None
        self._window: Any = None
        self._ready = threading.Event()
        self._pending: list[str] = []
        self._lock = threading.Lock()

    def _attach(self, core: Any, window: Any) -> None:
        """Give the bridge its two collaborators.

        Private because of the introspection rule above, which means the host
        reaches it by name rather than through the page's API. That is the
        intended direction: only the host has a core and a window to offer.
        """
        self._core = core
        self._window = window

    # -- the page's own lifecycle -------------------------------------------

    def ready(self) -> dict[str, bool]:
        """The page has mounted and can receive frames.

        This is the gate that keeps the window from hanging. ``evaluate_js``
        called before the document is ready does not fail -- it *deadlocks*:
        the script is handed to the webview, the result callback never fires,
        and the semaphore ``evaluate_js`` waits on is never released, so the
        calling thread is stuck with no error and no timeout. The pump runs on
        its own thread, so a deadlock there is a window that renders and then
        never speaks again.

        Frames that arrive before this are buffered and flushed here rather than
        dropped, which is the other half: the core writes only in answer to a
        request, and a request cannot be sent before the page is running, so
        nothing should arrive this early -- but "the reply to the first request
        went nowhere" is a bug that presents as a hang with no error anywhere,
        and being sure is two lines.
        """
        self._ready.set()
        with self._lock:
            pending, self._pending = self._pending, []
        if pending:
            self._push_frames(pending)
        return {"ok": True}

    # -- the core, in both directions ---------------------------------------

    def send(self, line: str) -> dict[str, bool]:
        """One request frame, on its way to the core.

        Returns as soon as it is written. Awaiting the reply here would hold a
        pywebview worker thread for the length of a model call, and the reply
        has a path back already.
        """
        self._core.write(line)
        return {"ok": True}

    def _frames(self, batch: list[str]) -> None:
        """Hand a batch of core output to the page. Runs on the pump thread."""
        if not self._ready.is_set():
            with self._lock:
                self._pending.extend(batch)
            return
        self._push_frames(batch)

    def _push_frames(self, batch: list[str]) -> None:
        """One ``evaluate_js`` for the whole batch.

        ``json.dumps`` rather than string interpolation, and it is not
        decoration: a frame carries whatever the model wrote, and a delta with a
        quote or a newline in it would otherwise be injected into the page as
        code. The list goes over as one argument so a fast stream costs one call
        per tick instead of one per token.
        """
        script = f"{TARGET}.onFrames({json.dumps(batch, ensure_ascii=False)})"
        self._window.evaluate_js(script)

    def _log(self, line: str) -> None:
        """One line of the core's stderr, for the log strip."""
        if not self._ready.is_set():
            return
        self._window.evaluate_js(f"{TARGET}.onLog({json.dumps(line, ensure_ascii=False)})")

    def _core_exit(self) -> None:
        """The core's stdout closed. The page has to stop saying "connected"."""
        if self._ready.is_set():
            self._window.evaluate_js(f"{TARGET}.onCoreExit()")

    def core_alive(self) -> dict[str, bool]:
        """Whether the core is running, asked rather than assumed.

        The page reads this once on mount, because a core that died before the
        window finished loading never pushed its exit to anybody.
        """
        return {"alive": bool(self._core.alive)}

    # -- the window ----------------------------------------------------------

    def window_control(self, action: str, edge: str | None = None) -> dict[str, bool]:
        """Minimize, maximize/restore, close, drag, or resize from an edge.

        ``toggleMaximize`` is a toggle here rather than two actions, because the
        window is the one that knows which way it goes. A page that decided
        would have to track the state itself, and it would be wrong the first
        time the user maximized by dragging to the screen edge.

        ``drag`` and ``resize`` do not return until the gesture is over: the
        OS's loop is modal, and it is running on the window's thread while this
        call waits. The answer is the window's state *afterwards*, which is the
        one that matters for a drag -- dragging to the top of the screen is a
        maximize, and the caption has to say so.
        """
        if action not in ACTIONS:
            raise ValueError(f"unknown window action: {action!r}")
        if action == "drag":
            hwnd = self._hwnd()
            self._on_window_thread(lambda: win32.begin_drag(hwnd))
        elif action == "resize":
            # Validated before the handle is asked for: a bad edge is a bad edge
            # whether or not there is a window to put it on.
            if edge not in win32.RESIZE_EDGES:
                raise ValueError(f"unknown resize edge: {edge!r}")
            hwnd = self._hwnd()
            self._on_window_thread(lambda: win32.begin_resize(hwnd, edge))
        elif action == "minimize":
            self._window.minimize()
        elif action == "close":
            # `destroy` rather than hiding it: the host's teardown -- reaping
            # the core -- runs off this, and a hidden window would leave the
            # process alive with nothing to bring it back.
            self._window.destroy()
        elif self._maximized():
            self._window.restore()
        else:
            self._window.maximize()
        return {"maximized": self._maximized()}

    def _maximized(self) -> bool:
        """Read from the window rather than remembered. See ``win32``.

        Private, and that is load-bearing rather than tidy: as a public property
        this was evaluated by pywebview's API walk, off the GUI thread, and
        deadlocked the window. See the module docstring.
        """
        try:
            return win32.is_maximized(self._hwnd())
        except Exception as exc:  # noqa: BLE001 - cosmetic, never fatal
            logger.debug(f"Could not read the maximized state: {exc}")
            return False

    def window_state(self) -> dict[str, bool]:
        """What the caption needs in order to draw itself."""
        return {"maximized": self._maximized()}

    def system_menu(self) -> dict[str, bool]:
        """The window's own system menu, at the cursor.

        Blocking, which is what a menu is: it runs a modal loop on the calling
        thread. That thread is a pywebview worker, so the window keeps painting
        while it is up and the page's promise settles when it closes.
        """
        win32.show_system_menu(self._hwnd())
        return {"maximized": self._maximized()}

    # -- the provider's own pages --------------------------------------------

    def open_account_view(self, view: str = DEFAULT_VIEW) -> dict[str, Any]:
        """Open one of the provider's account pages in a real browser window.

        Nothing above this line can answer what the *account* has used. The
        ledger counts this app's own requests, and the provider's dashboard is
        the only place the rest of it exists -- the other keys, the other tools,
        the credit balance -- behind the user's own sign-in, which a window the
        app draws inside itself cannot carry.

        The first press creates the window and every later one shows it, which
        is what keeps the sign-in: it is one cookie jar on disk, not one per
        press. The view name is checked against a closed set in
        ``account.VIEWS`` before any URL is used.
        """
        return self._account.open(view)

    def read_account_view(self, view: str = DEFAULT_VIEW) -> dict[str, Any]:
        """Open one of the provider's pages and read the figures it is showing.

        The same window as ``open_account_view``, doing the other half of the job:
        that method puts the page in front of the user so they can sign in, and
        this one asks the page what it says. Neither replaces the other, because
        the dashboard has to be able to show the numbers *and* to say "sign in"
        when the numbers are not there to show.

        These pages are the provider's own application, so what comes back is a
        list of the labels and values it displayed rather than this app's opinion
        about them. See ``AccountBrowser.EXTRACT``.
        """
        return self._account.read(view)

    # -- the desktop pet ------------------------------------------------------

    def pet(self, action: str = "state", payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """The pet's whole interface, in one method.

        It is one method rather than four because both pages call into it and the
        closed set is what tells them apart: the app asks for the state and sets
        it, the card announces itself and pushes back what to draw. Four public
        methods would be four names on both pages' API for one relationship.

        ``state`` reports two different booleans, and both are needed: ``open`` is
        whether a window exists *now*, ``wanted`` is whether it should be up when
        the app next starts. A toggle that drew itself from the first would come
        back off after every restart, and one that drew itself from the second
        would claim a window that the webview refused to make.
        """
        if action not in PET_ACTIONS:
            raise ValueError(f"unknown pet action: {action!r}")

        if action == "state":
            return {"open": self._pet.is_open(), "wanted": self._pet.was_open()}
        if action == "show":
            return {"open": bool(self._pet.set_open(True).get("open")), "wanted": True}
        if action == "hide":
            self._pet.set_open(False)
            return {"open": False, "wanted": False}
        if action == "ready":
            self._pet.mark_ready()
            return {"open": self._pet.is_open(), "wanted": self._pet.was_open()}
        if action == "focus":
            self._pet.raise_app()
            return {"open": self._pet.is_open(), "wanted": self._pet.was_open()}

        self._pet.push(payload or {})
        return {"open": self._pet.is_open(), "wanted": self._pet.was_open()}

    def _attach_pet(self, pet: DeskPet) -> None:
        """Give the bridge the pet, and the pet the window it raises.

        Private and called by the host, for the same reason `_attach` is: the pet
        needs the bridge as its page's ``js_api`` and the bridge needs the pet, so
        neither can be a constructor argument for the other. The app's own window
        is handed over at the same time -- it is what the card raises when it is
        clicked, and it is the only side of this that knows its own handle.
        """
        self._pet = pet
        if self._window is not None:
            pet.attach_app(self._window)

    # -- files ---------------------------------------------------------------

    def pick_folder(self) -> dict[str, str | None]:
        """A directory, as an absolute path.

        A native picker rather than ``<input type="file">``, for the reason the
        module this replaces gave and which has not stopped being true: a web
        file input yields a `File`, not a directory path, and the core needs a
        real path it can hand to the sandbox.
        """
        import webview

        chosen = self._window.create_file_dialog(
            webview.FOLDER_DIALOG, directory="", allow_multiple=False
        )
        return {"path": _first(chosen)}

    def pick_files(self, multiple: bool = True) -> dict[str, list[str]]:
        """Files, as absolute paths. The attachment button's picker.

        Returns paths, not contents. The core takes attachments as base64 on the
        wire, and the page already has a path-to-bytes path for files it is
        handed -- a second one here would be a second place for a file limit to
        disagree with itself.
        """
        import webview

        chosen = self._window.create_file_dialog(
            webview.OPEN_DIALOG, directory="", allow_multiple=multiple
        )
        return {"paths": [str(one) for one in (chosen or ())]}

    # -- the native window ---------------------------------------------------

    def _on_window_thread(self, work: Any) -> None:
        """Run `work` on the thread that owns the window, then return.

        **Not a tidiness call, and the difference is the whole feature.** The
        page's request arrives on a pywebview worker thread, but a window
        gesture is not a message the host can send on the page's behalf from
        anywhere: `WM_NCLBUTTONDOWN` starts a modal loop that belongs to the
        window's own thread, and the `ReleaseCapture()` in front of it -- the
        half of the classic pair that is easy to leave out -- acts on whichever
        thread makes the call. Issued from a worker it released the worker's own
        (empty) capture, left the webview's in place, and the loop never took:
        measured, the window did not move by a pixel.

        The fallback is a direct call rather than an error, because a backend
        with no WinForms control behind it has no window thread to marshal to,
        and refusing to try would turn "this backend cannot drag" into "this
        backend raises".
        """
        native = getattr(self._window, "native", None)
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

    def _hwnd(self) -> int:
        """The top-level window's handle.

        ``GetAncestor(..., GA_ROOT)`` rather than the handle pywebview hands
        out, because that one belongs to the *webview control* nested inside the
        form. The system menu and the corner preference are properties of the
        top-level window, and asking a child control for them gets a handle the
        OS will not act on.
        """
        native = getattr(self._window, "native", None)
        if native is None:
            raise RuntimeError("the window has no native handle yet")
        return win32.root_window(int(native.Handle.ToInt64()))


def _first(chosen: Any) -> str | None:
    """The single path out of a picker result, or ``None`` if it was cancelled.

    A cancel is a normal outcome and must not surface as an error. The result's
    shape is not something to trust either: pywebview returns a sequence for one
    selection on some backends and a bare string on others, and a caller that
    assumed the sequence would hand the core the first *character* of a path.
    """
    if isinstance(chosen, str):
        return chosen
    if isinstance(chosen, (list, tuple)) and chosen:
        return str(chosen[0])
    return None
