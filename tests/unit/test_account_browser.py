"""The account browser: one real window, at the provider's own pages.

None of these open a window. What a window *does* -- what it paints, whether a
sign-in lasts -- is not assertable in a unit test; what is assertable is
everything the app decides around it, and that is where the failures would be
silent: a second window per press would look right and quietly lose the session,
and a view name taken from the page would be a window that can be pointed
anywhere.

Every claim here is about an object with a fake window behind it, so the
assertions are about the app's choices rather than pywebview's behaviour.
"""

from __future__ import annotations

from typing import Any

import pytest


class FakeEvent:
    """One pywebview event: `events.closed += handler`, then it fires."""

    def __init__(self) -> None:
        self.handlers: list[Any] = []

    def __iadd__(self, handler: Any) -> "FakeEvent":
        self.handlers.append(handler)
        return self

    def fire(self) -> None:
        for handler in self.handlers:
            handler()


class FakeLoaded:
    """`loaded`, which a read clears and then waits on.

    Counts the clears because that is the thing that goes wrong: pywebview sets
    `loaded` on *every* load, so a read that waits without clearing first is
    handed the previous page's event and treats the old document as the new one.
    """

    def __init__(self, arrives: bool = True) -> None:
        self.arrives = arrives
        self.cleared = 0
        self.waited: list[float | None] = []

    def clear(self) -> None:
        self.cleared += 1

    def wait(self, timeout: float | None = None) -> bool:
        self.waited.append(timeout)
        return self.arrives


class FakeEvents:
    """pywebview's `EventContainer`, for the two names the browser subscribes to."""

    def __init__(self, loaded: FakeLoaded | None = None) -> None:
        self.closed = FakeEvent()
        self.loaded = loaded if loaded is not None else FakeLoaded()


class FakeWindow:
    """A window with everything `AccountBrowser` may touch."""

    def __init__(self, answer: Any = None, arrives: bool = True) -> None:
        self.events = FakeEvents(FakeLoaded(arrives))
        self.loaded: list[str] = []
        self.shown = 0
        self.restored = 0
        self.scripts: list[str] = []
        #: What `evaluate_js` hands back -- a dict, a JSON string, or junk.
        self.answer = answer if answer is not None else {"figures": []}
        # After construction, not in a class body: a name assigned inside a
        # `class` block resolves in the *class* namespace, so `Handle = Handle`
        # there is a NameError.
        self.native = type("Native", (), {"Handle": _Handle})()
        self._minimized = False

    def load_url(self, url: str) -> None:
        self.loaded.append(url)

    def show(self) -> None:
        self.shown += 1

    def restore(self) -> None:
        self.restored += 1

    def evaluate_js(self, script: str) -> Any:
        self.scripts.append(script)
        # Exactly what it was handed: pywebview parses a JSON-shaped result for
        # the caller when it recognises one, so the same call arrives as a dict
        # on one page and as a string on another, and both have to work.
        return self.answer


class _Handle:
    @staticmethod
    def ToInt64() -> int:
        return 4242


def browser(answer: Any = None, *, arrives: bool = True) -> tuple[Any, list[tuple[str, str]]]:
    """An `AccountBrowser` whose window creation is recorded, not performed."""
    from tonyagent.window.account import AccountBrowser

    created: list[tuple[str, str]] = []

    def create(title: str, url: str) -> FakeWindow:
        created.append((title, url))
        return FakeWindow(answer, arrives)

    return AccountBrowser(create=create), created


def test_every_view_is_https_at_the_provider():
    """The page can name a view, so the URLs are the app's and not the page's.

    Pinned as a whole map rather than checked for a prefix: a view added with a
    plain-http URL, or one that wandered off the provider's domain, is a window
    this program creates for somebody else's site.
    """
    from tonyagent.window.account import DEFAULT_VIEW, VIEWS

    assert VIEWS == {
        "activity": "https://openrouter.ai/activity",
        "credits": "https://openrouter.ai/settings/credits",
        "keys": "https://openrouter.ai/settings/keys",
    }
    assert all(url.startswith("https://openrouter.ai/") for url in VIEWS.values())
    assert DEFAULT_VIEW in VIEWS


def test_the_first_press_opens_the_window_at_the_view(monkeypatch):
    from tonyagent.window import account as account_module

    monkeypatch.setattr(account_module.win32, "is_minimized", lambda hwnd: False)
    ab, created = browser()

    result = ab.open("credits")

    assert created == [(account_module.TITLE, "https://openrouter.ai/settings/credits")]
    assert result == {
        "view": "credits",
        "url": "https://openrouter.ai/settings/credits",
        "opened": True,
        "reused": False,
    }


def test_the_window_is_a_browser_and_not_another_copy_of_the_app(monkeypatch):
    """Framed and selectable, and both are the point of the thing.

    A frameless window is one the user cannot move or resize without the app's
    own chrome behind it, and `text_select` off is a page that cannot be copied
    out of -- which is what the app's own window is for and what a browser pane
    must not be.
    """
    from tonyagent.window import account as account_module

    captured: dict[str, Any] = {}

    def fake_create_window(*args: Any, **kwargs: Any) -> None:
        captured.update(kwargs)
        return None

    monkeypatch.setattr("webview.create_window", fake_create_window)
    account_module._create_window("OpenRouter", "https://openrouter.ai/activity")

    assert captured["frameless"] is False, "the browser window has no frame"
    assert captured["text_select"] is True, "the page cannot be selected from"
    assert captured["resizable"] is True
    assert captured["url"] == "https://openrouter.ai/activity"


def test_a_second_press_shows_the_window_that_is_already_there(monkeypatch):
    """**The sign-in is one cookie jar, and this is what keeps it one.**

    A window per press would be correct-looking and wrong: two signed-out
    windows, two sign-ins, and a session that lasts until the second one is
    closed. The second press must create nothing, and must bring the window the
    user already signed into back to the front.
    """
    from tonyagent.window import account as account_module

    monkeypatch.setattr(account_module.win32, "is_minimized", lambda hwnd: False)
    ab, created = browser()

    ab.open("activity")
    second = ab.open("activity")

    assert len(created) == 1, "a second window was created for the same view"
    assert second["reused"] is True
    window = ab._window
    assert window.shown == 1, "the existing window was never brought back"
    assert window.loaded == [], "the page was reloaded rather than shown"


def test_changing_view_navigates_the_window_that_exists(monkeypatch):
    """One window, two pages. A second window would be a second session."""
    from tonyagent.window import account as account_module

    monkeypatch.setattr(account_module.win32, "is_minimized", lambda hwnd: False)
    ab, created = browser()

    ab.open("activity")
    moved = ab.open("keys")

    assert len(created) == 1
    assert moved["reused"] is True
    assert ab._window.loaded == ["https://openrouter.ai/settings/keys"]
    # And pressing the key that is already showing must not reload it: a reload
    # is what a page does when it thinks it was navigated to again.
    ab.open("keys")
    assert ab._window.loaded == ["https://openrouter.ai/settings/keys"]


def test_a_view_that_is_not_one_is_refused_before_anything_is_opened():
    """The page reaches this method, so the name is checked, not followed.

    Refused before a window is created rather than after: a URL that is about to
    be rejected is not a reason to have opened a window to reject it in.
    """
    ab, created = browser()

    with pytest.raises(ValueError):
        ab.open("https://example.com")

    assert created == []


def test_a_closed_window_is_replaced_by_the_next_press(monkeypatch):
    """Closing it is not a resignation from the feature.

    The reference is dropped on `closed` rather than kept and poked: `show()` on
    a destroyed window either raises or does nothing, and the user's next press
    would then be a button that does not work until the app is restarted.
    """
    from tonyagent.window import account as account_module

    monkeypatch.setattr(account_module.win32, "is_minimized", lambda hwnd: False)
    ab, created = browser()

    ab.open("activity")
    ab._window.events.closed.fire()

    assert ab.open("activity")["reused"] is False
    assert len(created) == 2, "the closed window was reused instead of replaced"


def test_a_window_that_could_not_be_created_is_reported_as_such():
    """One outcome is not a success, and it is the page that has to say so."""
    from tonyagent.window.account import AccountBrowser

    ab = AccountBrowser(create=lambda title, url: None)

    result = ab.open("activity")

    assert result["opened"] is False
    assert result["reused"] is False


def test_only_a_minimized_window_is_restored(monkeypatch):
    """`restore()` means Normal, so calling it every time shrinks a maximized one.

    A second press of the same button would be a window that jumped backwards --
    and pywebview has no way to ask, because `Window.state` is the JavaScript
    state bridge rather than the window's presentation state.
    """
    from tonyagent.window import account as account_module

    ab, _ = browser()
    ab.open("activity")
    window = ab._window

    # The creation itself needs no `show()` -- a window that has just been made
    # is already on screen and in front.
    assert window.shown == 0

    monkeypatch.setattr(account_module.win32, "is_minimized", lambda hwnd: False)
    ab.open("activity")
    assert window.restored == 0, "a window that was not minimized was restored"
    assert window.shown == 1

    monkeypatch.setattr(account_module.win32, "is_minimized", lambda hwnd: True)
    ab.open("activity")
    assert window.restored == 1, "a minimized window was left in the taskbar"
    assert window.shown == 2


def test_the_handle_is_read_from_the_window_and_zero_when_there_is_none(monkeypatch):
    """`IsIconic(0)` is the answer for a backend with no native control.

    Raising instead would turn \"this backend cannot tell\" into \"this backend
    raises\", on a press that has nothing to do with the backend.
    """
    from tonyagent.window import account as account_module

    class Handle:
        @staticmethod
        def ToInt64() -> int:
            return 4242

    from tonyagent.window import win32

    with_native = type("W", (), {"native": type("N", (), {"Handle": Handle})()})()
    assert account_module._handle(with_native) == win32.root_window(4242)

    assert account_module._handle(type("W", (), {})()) == 0
    assert account_module._handle(type("W", (), {"native": object()})()) == 0


def test_the_dashboard_offers_exactly_the_views_the_host_has():
    """The names on the buttons and the keys in `VIEWS` are one contract.

    A name the page offers and the host does not have is a button that raises
    instead of one that opens nothing, and the user sees it as the generic "could
    not be opened" -- which is the failure that would be diagnosed last, because
    it looks like a window that would not open. Read out of the view's source
    rather than duplicated here, so a fifth page added on one side cannot pass.
    """
    import re
    from pathlib import Path

    from tonyagent.window.account import VIEWS

    source = (
        Path(__file__).resolve().parents[2] / "app" / "src" / "Dashboard.tsx"
    ).read_text(encoding="utf-8")
    block = source.split("const ACCOUNT_VIEWS = [", 1)[1].split("] as const", 1)[0]
    offered = re.findall(r'id: "([a-z]+)"', block)

    assert sorted(offered) == sorted(VIEWS), (
        f"the dashboard offers {offered} and the host has {sorted(VIEWS)}"
    )


# --- reading the figures off the page ---------------------------------------


def test_a_read_reports_the_labels_and_values_the_page_showed():
    """**The point of the whole feature: the account's figures on the dashboard.

    The pairing is the page's own -- its label, its wording, its formatting -- and
    that is asserted rather than assumed, because the alternative is this app
    deciding that an amount beside the word "credits" is the credit balance. The
    value here is nonsense on purpose: nothing in the result was interpreted, so
    nonsense is what comes back.
    """
    from tonyagent.window import account as account_module

    ab, _created = browser(
        {
            "url": "https://openrouter.ai/settings/credits",
            "signedOut": False,
            "figures": [
                {"label": "Credits remaining", "value": "$74.25"},
                {"label": "Total usage", "value": "$25.75"},
                {"label": "Unlabelled", "value": "banana"},
            ],
        }
    )

    result = ab.read("credits")

    assert result["ok"] is True
    assert result["signed_out"] is False
    assert result["figures"] == [
        {"label": "Credits remaining", "value": "$74.25"},
        {"label": "Total usage", "value": "$25.75"},
        {"label": "Unlabelled", "value": "banana"},
    ]
    assert result["url"] == "https://openrouter.ai/settings/credits"
    assert result["read_at"] > 0
    assert account_module.EXTRACT in ab._window.scripts[0]


def test_the_read_waits_for_the_page_after_asking_it_to_navigate():
    """Cleared *before* the load, which is the mistake this pins.

    pywebview sets `loaded` on every load. A read that waits without clearing
    first is handed the previous page's event -- already set -- and reads the old
    document while calling it the new one. The wait is only there when something
    was actually navigated, too: re-reading a page that is already up would
    otherwise block for the whole timeout on an event that will not fire again.
    """
    ab, _created = browser()

    ab.read("credits")
    window = ab._window
    assert window.events.loaded.cleared == 1, "the stale load event was waited on"
    assert window.events.loaded.waited == [
        pytest.importorskip("tonyagent.window.account").LOAD_TIMEOUT
    ]

    ab.read("credits")  # same view: nothing was navigated
    assert window.events.loaded.cleared == 1, "a read waited for a load nobody asked for"


def test_a_page_that_does_not_arrive_in_time_is_named_as_such():
    """Its own outcome, because the user does something different about it."""
    ab, _created = browser(arrives=False)

    result = ab.read("activity")

    assert result == {
        "view": "activity",
        "url": "https://openrouter.ai/activity",
        "ok": False,
        "reason": "timeout",
        "signed_out": False,
        "figures": [],
        "read_at": result["read_at"],
    }
    assert result["read_at"] > 0
    assert ab._window.scripts == [], "the page was read after it failed to arrive"


def test_a_signed_out_page_is_not_an_account_with_no_usage():
    """The distinction the dashboard's sentence is built on.

    A signed-out read *succeeded* -- the app asked the page and the page answered
    -- and the answer is that it is the sign-in page. Reporting that as zero usage
    would be the app inventing a number the user can act on wrongly.
    """
    ab, _created = browser(
        {
            "url": "https://openrouter.ai/sign-in?redirect_url=x",
            "signedOut": True,
            "figures": [],
        }
    )

    result = ab.read("activity")

    assert result["ok"] is True
    assert result["signed_out"] is True
    assert result["figures"] == []


def test_a_page_that_answers_with_nothing_readable_is_a_failure_not_an_empty_account():
    ab, _created = browser("not json at all")

    result = ab.read("activity")

    assert result["ok"] is True, "an unreadable document is still a document"
    assert result["figures"] == [], "something was invented out of an unparseable page"


def test_a_page_that_answers_with_a_broken_json_document_is_a_failure():
    ab, _created = browser("{")

    result = ab.read("activity")

    assert result["ok"] is True
    assert result["figures"] == []


def test_a_read_that_raises_is_reported_rather_than_propagated():
    """A window that will not answer is a sentence on the dashboard, not a crash."""
    ab, _created = browser()

    def explode(script: str) -> Any:
        raise RuntimeError("the webview is gone")

    ab.open("activity")
    ab._window.evaluate_js = explode  # type: ignore[method-assign]

    result = ab.read("activity")

    assert result["ok"] is False
    assert result["reason"] == "unreadable"


def test_figures_are_checked_and_clipped_before_they_are_drawn():
    """The page is not this program, so what comes off it is input.

    Every entry is kept only if it is a label and a value, both strings and both
    non-empty; labels are clipped to something a row can hold and the list is
    capped. A malformed entry is dropped rather than rendered as "undefined".
    """
    from tonyagent.window.account import MAX_FIGURES

    ab, _created = browser(
        {
            "figures": [
                {"label": "  Real  ", "value": "  $1.00  "},
                {"label": "no value"},
                {"value": "no label"},
                {"label": 7, "value": "not a label"},
                {"label": "missing value", "value": None},
                {"label": "", "value": ""},
                {"label": "x" * 500, "value": "y" * 500},
            ]
            + [{"label": f"extra {i}", "value": "1"} for i in range(MAX_FIGURES)],
        }
    )

    figures = ab.read("activity")["figures"]

    assert figures[0] == {"label": "Real", "value": "$1.00"}, "whitespace was kept"
    assert len(figures) <= MAX_FIGURES, "the cap is not a cap"
    assert all(len(figure["label"]) <= 80 for figure in figures)
    assert all(len(figure["value"]) <= 40 for figure in figures)
    assert len(figures) == MAX_FIGURES, "valid entries were dropped with the malformed ones"


def test_a_page_that_is_not_a_dict_of_figures_yields_none():
    ab, _created = browser([1, 2, 3])

    assert ab.read("activity")["figures"] == []


def test_reading_a_view_that_is_not_one_is_refused_before_anything_opens():
    ab, created = browser()

    with pytest.raises(ValueError):
        ab.read("https://example.com")

    assert created == []


def test_a_read_with_no_window_to_read_from_says_so():
    from tonyagent.window.account import AccountBrowser

    result = AccountBrowser(create=lambda title, url: None).read("activity")

    assert result["ok"] is False
    assert result["reason"] == "no-window"
    assert result["figures"] == []


def test_the_bridge_hands_the_read_through_to_the_page():
    from tonyagent.window.bridge import Bridge

    read: list[str] = []

    class Recorder:
        def open(self, view: str) -> dict[str, Any]:
            return {"view": view, "url": "u", "opened": True, "reused": False}

        def read(self, view: str) -> dict[str, Any]:
            read.append(view)
            return {"view": view, "figures": [], "ok": True}

    bridge = Bridge(account=Recorder())  # type: ignore[arg-type]

    assert bridge.read_account_view("credits")["ok"] is True
    assert read == ["credits"]


def test_the_bridge_opens_the_view_the_page_asked_for():
    """The one line of the page's API, exercised end to end."""
    from tonyagent.window.bridge import Bridge

    asked: list[str] = []

    class Recorder:
        def open(self, view: str) -> dict[str, Any]:
            asked.append(view)
            return {"view": view, "url": "u", "opened": True, "reused": False}

    bridge = Bridge(account=Recorder())  # type: ignore[arg-type]

    assert bridge.open_account_view("keys")["opened"] is True
    assert asked == ["keys"]
    # And the default is the provider's usage page, which is the question the
    # dashboard's button is asking.
    bridge.open_account_view()
    assert asked[-1] == "activity"
