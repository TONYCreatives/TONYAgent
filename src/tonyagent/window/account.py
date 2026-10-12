"""The provider's own dashboard, in a browser window this app owns.

The usage view counts what **this app** sent: every request is noted in the
ledger on its way out, and that is the only thing it can honestly count. The
account's real usage is not that number -- it is every key, every other tool and
every other machine, plus the credit balance none of them can see from here. The
only place that number exists is the provider's own site, behind the user's own
sign-in.

**So the app opens a real browser at it.** Not a second view of the ledger, and
not an iframe: the page is reached with a session cookie, and a window the app
draws inside itself has no cookie jar of its own. What pywebview gives is the
rendering engine in a window this program creates, which is what every Electron
browser pane is -- and because the profile on disk is shared and persistent (see
``host.profile_dir``), the user signs in once and stays signed in across
restarts.

Two things about that session are worth naming, because they are the whole cost
of this design:

* the window is **framed**, unlike the app's own. It is a browser: it has a
  title bar, an address bar, a back button and the OS's own frame, and the user
  can move it, resize it and close it without the app's help.
* it is **not sandboxed and not the agent's browser**. The Docker image's
  Chromium has no cookies and never will; this one is the user's own session,
  and the agent has no tool that can reach it.
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable
from typing import Any

from loguru import logger

from tonyagent.window import win32

#: Where each view lives.
#:
#: A closed set rather than a URL the page hands over, for the reason
#: ``Bridge.ACTIONS`` is one: the page can reach this method, and a method that
#: opens whatever it is given is a way to put any site on the internet in front
#: of the user inside a window this program created.
VIEWS: dict[str, str] = {
    "activity": "https://openrouter.ai/activity",
    "credits": "https://openrouter.ai/settings/credits",
    "keys": "https://openrouter.ai/settings/keys",
}

#: What the button means when it does not say: the page that answers "how much
#: have I actually used", which is the question the ledger above cannot answer.
DEFAULT_VIEW = "activity"

TITLE = "OpenRouter"

#: The size the provider's own layout is designed against. A browser window, so
#: the minimum is a browser window's -- small enough to sit beside the app.
WIDTH, HEIGHT = 1180, 860
MIN_WIDTH, MIN_HEIGHT = 420, 320

#: What the webview paints before the page loads. White, unlike the app's own
#: field: this is somebody else's page, and it is overwhelmingly a light one.
BACKGROUND = "#ffffff"

#: How long a navigation is given before the read gives up and says so. The
#: number is a UX decision rather than a network one: past this the user has
#: stopped waiting, and a page that arrives afterwards is one they can read
#: themselves by pressing the page's own button.
LOAD_TIMEOUT = 25.0

#: Afterwards, this long, before the figures are read. The document arriving and
#: the figures arriving are two different events: the page is an application that
#: fetches its own numbers after it paints, so reading the instant it loads finds
#: the shape of a dashboard and none of its contents.
SETTLE = 2.5

#: A cap on what is brought back, so a page that matches the pattern everywhere
#: cannot return a wall of numbers. Twelve is more than any of these pages shows.
MAX_FIGURES = 12

#: How many entries are looked at before the scan stops, as a multiple of the cap.
#:
#: Two different bounds, and both are needed. The cap is what is *rendered*; this
#: is what is *inspected*, and it exists because the list is untrusted input that
#: arrives from a page over which this program has no control -- an array of a
#: million entries should not be walked. It is generous rather than tight so that
#: a page whose first few matches are junk (a table header, a hidden template)
#: still yields the figures further down, which is the reason the cap is not
#: applied to the input slice instead.
INSPECT_LIMIT = MAX_FIGURES * 4

#: The script that reads the page, as the page's own DOM sees it.
#:
#: **It reads what the page is displaying and does not interpret it.** Every
#: figure comes back as the label the page put next to it and the text it showed,
#: paired, and nothing is renamed, summed or converted -- because the alternative
#: is the app deciding that "$2.50" beside the word "credits" means the credit
#: balance, and being wrong in a way the user cannot see. What the page says is
#: what the dashboard says, attributed to the page.
#:
#: It cannot be validated against the signed-in page from here, and it is written
#: to be honest about that instead of clever: an element that matches nothing
#: yields no figure, a signed-out page is reported as signed out rather than as an
#: account with no usage, and the label that comes back is the page's own wording
#: so a wrong pairing is visible to the reader rather than hidden behind a nicer
#: name. Scripts, styles and SVG are skipped: their text is code and geometry, and
#: a number in a stylesheet is not a figure.
#:
#: A leaf element whose *whole* text is a money amount or a thousands-separated
#: integer is the shape these dashboards use for a metric, and the label is the
#: nearest ancestor whose remaining text is short enough to be a label rather
#: than a paragraph.
EXTRACT = r"""(() => {
  const norm = (s) => (s || '').replace(/\s+/g, ' ').trim();
  const MONEY = /^[$]?\s?\d{1,3}(,\d{3})*(\.\d{1,2})?$/;
  const THOUSANDS = /^\d{1,3}(,\d{3})+$/;
  const SKIP = new Set(['SCRIPT', 'STYLE', 'NOSCRIPT', 'TEMPLATE', 'SVG', 'PATH']);
  const labelFor = (el, shown) => {
    let node = el.parentElement;
    for (let depth = 0; depth < 4 && node; depth++) {
      const remainder = norm(node.textContent).split(shown).join(' ').trim();
      if (remainder.length >= 2 && remainder.length <= 60) return remainder;
      node = node.parentElement;
    }
    return '';
  };
  const figures = [];
  const seen = new Set();
  for (const el of document.querySelectorAll('body *')) {
    if (el.children.length) continue;
    if (SKIP.has(el.tagName)) continue;
    const shown = norm(el.textContent);
    if (!shown || (!MONEY.test(shown) && !THOUSANDS.test(shown))) continue;
    const label = labelFor(el, shown);
    if (!label) continue;
    const key = label + '|' + shown;
    if (seen.has(key)) continue;
    seen.add(key);
    figures.push({ label: label, value: shown });
    if (figures.length >= 12) break;
  }
  return {
    url: location.href,
    title: document.title,
    signedOut: /(^|\/)sign-in(\/|$)/.test(location.pathname),
    figures: figures,
  };
})()"""


class AccountBrowser:
    """One window, opened on demand, holding the provider's own pages.

    One, not one per view: the sign-in is a cookie in the profile, and a second
    window would be a second way to be signed out of the first. Changing view
    navigates the window that is already there.
    """

    def __init__(self, create: Callable[[str, str], Any] | None = None) -> None:
        #: Injected by the tests, which have no GUI loop to create a window on.
        self._create = create or _create_window
        self._window: Any = None
        self._view = ""
        self._lock = threading.Lock()

    def open(self, view: str = DEFAULT_VIEW) -> dict[str, Any]:
        """Show the window, or make the one that is already there show `view`.

        Returns what happened rather than nothing, because one outcome is not a
        success: a webview that refuses to create a second window answers
        ``opened: False``, and a caller that assumed otherwise would tell the
        user a window had opened that had not.
        """
        url = VIEWS.get(view)
        if url is None:
            raise ValueError(f"unknown account view: {view!r}")
        with self._lock:
            live = self._window
            if live is not None:
                if view != self._view:
                    live.load_url(url)
                    self._view = view
                _bring_to_front(live)
                return {"view": view, "url": url, "opened": True, "reused": True}

            window = self._create(TITLE, url)
            if window is None:
                logger.warning("The webview refused a second window for the account view.")
                return {"view": view, "url": url, "opened": False, "reused": False}
            self._window = window
            self._view = view
            window.events.closed += self._closed
            return {"view": view, "url": url, "opened": True, "reused": False}

    def read(self, view: str = DEFAULT_VIEW) -> dict[str, Any]:
        """Show `view` and report the figures the page is displaying.

        Four outcomes, named rather than collapsed into "failed": no window could
        be made, the page did not arrive in time, the page is the sign-in page, or
        here are the figures it is showing. The dashboard draws a different
        sentence for each, because they are different things for the user to do.

        The read happens *in the page*, on its own origin, with the cookies the
        user signed in with -- which is the whole reason this is a browser window
        and not an HTTP call. There is no API key in it and no endpoint to keep up
        with.
        """
        url = VIEWS.get(view)
        if url is None:
            raise ValueError(f"unknown account view: {view!r}")

        navigation = view != self._view
        # `.get("opened")` and not the dict's truthiness. The first version of this
        # read `if not self.open(view)`, and a refusal is `{"opened": False}` -- a
        # non-empty dict, which is true -- so the no-window path was unreachable and
        # the line below it crashed on a window that had never been made. Found by
        # `test_a_read_with_no_window_to_read_from_says_so`.
        if not self.open(view).get("opened"):
            return _failure(view, url, "no-window")
        window = self._window
        if window is None:  # pragma: no cover - `open` reported success without one
            return _failure(view, url, "no-window")

        if navigation:
            # Cleared before the load is asked for, not after: pywebview sets
            # `loaded` on every load, and the browser hands the *previous* page's
            # event back if the new document has not started. Waiting on a stale
            # signal would read the old page and call it the new one.
            window.events.loaded.clear()
            if not window.events.loaded.wait(LOAD_TIMEOUT):
                return _failure(view, url, "timeout")
            time.sleep(SETTLE)

        try:
            payload = self._extract(window)
        except Exception as exc:  # noqa: BLE001 - a page that will not answer
            logger.warning(f"The account page could not be read: {exc}")
            return _failure(view, url, "unreadable")

        return {
            "view": view,
            "url": str(payload.get("url") or url),
            "ok": True,
            "signed_out": bool(payload.get("signedOut")),
            "figures": _figures(payload.get("figures")),
            "read_at": time.time(),
        }

    @staticmethod
    def _extract(window: Any) -> dict[str, Any]:
        """Run the script and take its JSON, whichever way pywebview hands it over.

        ``evaluate_js`` parses a JSON-shaped result for the caller when it
        recognises one, so the same call can produce a dict or a string
        depending on what the page returned. Both are accepted because guessing
        which one arrives is how this becomes a bug on somebody else's machine.
        """
        raw = window.evaluate_js(f"JSON.stringify({EXTRACT})")
        if isinstance(raw, dict):
            return raw
        if isinstance(raw, str) and raw.strip():
            try:
                loaded = json.loads(raw)
            except ValueError:
                return {}
            return loaded if isinstance(loaded, dict) else {}
        return {}

    def _closed(self) -> None:
        """Forget the window, so the next press makes a new one.

        **Nothing waits here, and that is not tidiness.** This runs on the
        window's own thread, while ``open`` holds ``_lock`` across the call that
        asks that same thread to create a window. A close that queued up behind
        the lock would be the window thread waiting for a lock held by a thread
        waiting for the window thread -- a deadlock with a closed window behind
        it.
        """
        self._window = None
        self._view = ""


def _create_window(title: str, url: str) -> Any:
    """The second window itself.

    Called from a worker thread, which is the only way pywebview accepts a
    window after the loop is running: it hands the creation to the window's own
    thread and returns, so the page's request settles without waiting for the
    provider's site to load.
    """
    import webview

    return webview.create_window(
        title,
        url=url,
        width=WIDTH,
        height=HEIGHT,
        min_size=(MIN_WIDTH, MIN_HEIGHT),
        resizable=True,
        # Framed on purpose. See the module docstring: this window is a browser,
        # and the app's own frameless chrome would leave the user with a page
        # they cannot move, resize or close except by closing the app.
        frameless=False,
        # Off by default, and it is the one setting that makes this a browser
        # rather than a picture of one.
        text_select=True,
        background_color=BACKGROUND,
    )


def _bring_to_front(window: Any) -> None:
    """Show the window, un-minimizing it only if it is minimized.

    ``restore()`` sets the window state to ``Normal``, so calling it every time
    would shrink a window the user had maximized: a second press of the same
    button would be a window that jumped backwards. pywebview has no way to ask
    -- ``Window.state`` is the JavaScript state bridge and not the window's
    presentation state -- so the question goes to Win32, the same way the
    caption's own maximized state does.
    """
    if win32.is_minimized(_handle(window)):
        window.restore()
    window.show()


def _failure(view: str, url: str, reason: str) -> dict[str, Any]:
    """A read that did not happen, in the same shape as one that did.

    The same keys, including ``figures``, so the caller has one shape to draw and
    cannot accidentally render a failed read's missing list as "no usage".
    """
    return {
        "view": view,
        "url": url,
        "ok": False,
        "reason": reason,
        "signed_out": False,
        "figures": [],
        "read_at": time.time(),
    }


def _figures(raw: Any) -> list[dict[str, str]]:
    """The figures, checked and clipped.

    The page is not this program, so what comes back off it is treated as input
    rather than as data: a pairing is kept only if it is a label and a value that
    are both strings and both non-empty, the label is clipped to something a row
    can hold, and the list is capped. A malformed entry is dropped rather than
    rendered.
    """
    figures: list[dict[str, str]] = []
    if not isinstance(raw, list):
        return figures
    for item in raw[:INSPECT_LIMIT]:
        if len(figures) >= MAX_FIGURES:
            break
        if not isinstance(item, dict):
            continue
        label = item.get("label")
        value = item.get("value")
        if not isinstance(label, str) or not isinstance(value, str):
            continue
        label, value = label.strip()[:80], value.strip()[:40]
        if label and value:
            figures.append({"label": label, "value": value})
    return figures


def _handle(window: Any) -> int:
    """The window's top-level handle, or zero when there is none to ask.

    Zero is the answer rather than an error, and it is a true one: a backend
    with no WinForms control behind it has no window that can be minimized, and
    ``IsIconic(0)`` says so.
    """
    native = getattr(window, "native", None)
    if native is None:
        return 0
    try:
        return win32.root_window(int(native.Handle.ToInt64()))
    except Exception as exc:  # noqa: BLE001 - an unaskable window is not a fatal one
        logger.debug(f"Could not read the account window's handle: {exc}")
        return 0
