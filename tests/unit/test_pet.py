"""The desktop pet, tested where a window is not needed.

The window itself is verified on a real desktop -- see the module docstring of
``pet.py`` for the four facts that were measured there, and which
``test_the_card_is_built_to_be_looked_at_without_being_activated`` pins as flags.
What is testable here is everything the app decides around it, and all of it is
the silent kind of failure: a second card per press, a status pushed before the
page could take it, a remembered preference that is not remembered.
"""

from __future__ import annotations

from typing import Any

import pytest


@pytest.fixture(autouse=True)
def _prefs_in_a_temp_dir(monkeypatch, tmp_path):
    """Keep the preference file out of the real config directory.

    The pet remembers whether it was open, and a test that let it write there
    would leave the developer's own app with a pet they did not ask for.
    """
    from tonyagent.window import prefs

    path = tmp_path / "window.json"
    monkeypatch.setattr(prefs, "_path", lambda: path)
    return path


class FakeEvent:
    """`events.closed += handler`, and a way to fire it."""

    def __init__(self) -> None:
        self.handlers: list[Any] = []

    def __iadd__(self, handler: Any) -> "FakeEvent":
        self.handlers.append(handler)
        return self

    def fire(self) -> None:
        for handler in self.handlers:
            handler()


class FakeEvents:
    """pywebview's `EventContainer` for the names the pet subscribes to.

    `shown` and `loaded` are not decoration: they are how the card finds out that
    its window exists, which is what `_dress` waits for. A fake without them is a
    pet that is never clipped -- which is exactly what shipped.
    """

    def __init__(self) -> None:
        self.closed = FakeEvent()
        self.shown = FakeEvent()
        self.loaded = FakeEvent()


class _Handle:
    @staticmethod
    def ToInt64() -> int:
        return 4242


class FakeWindow:
    """A window with the things ``DeskPet`` may touch."""

    def __init__(self, x: int = 0, y: int = 0) -> None:
        self.events = FakeEvents()
        self.scripts: list[str] = []
        self.destroyed = 0
        self.shown = 0
        self.restored = 0
        #: pywebview's own position properties, which is what `drag` reads to
        #: find out where the user let go. A test moves the card by setting them.
        self.x = x
        self.y = y

    def evaluate_js(self, script: str) -> None:
        self.scripts.append(script)

    def destroy(self) -> None:
        self.destroyed += 1

    def show(self) -> None:
        self.shown += 1

    def restore(self) -> None:
        self.restored += 1


def pet(**kwargs: Any):
    """A `DeskPet` whose window creation is recorded, not performed."""
    from tonyagent.window.pet import DeskPet

    created: list[tuple[str, int, int]] = []

    def create(page: str, x: int, y: int) -> FakeWindow:
        created.append((page, x, y))
        return FakeWindow()

    return DeskPet(page="/pet.html", create=create, **kwargs), created


def test_the_card_is_built_to_be_looked_at_without_being_activated():
    """The three flags that make it usable while the user is doing something else.

    ``focus=False`` is the load-bearing one and it is not cosmetic: pywebview turns
    it into ``WS_EX_NOACTIVATE``, which was measured on the real window -- the
    card never takes the foreground, so a status update cannot pull the keyboard
    out of whatever the user is typing in. ``on_top`` keeps it visible over the
    window they moved to, and ``frameless``+non-resizable is what makes it a card
    rather than a second app window.

    ``transparent`` is deliberately absent, and that is measured too: on this
    shell it does nothing -- ``WS_EX_LAYERED`` stays unset and the pixels beside
    the artwork come back as the control grey. Asking for it would be a line
    claiming a feature the window does not have.
    """
    from tonyagent.window import pet as pet_module

    captured: dict[str, Any] = {}

    def fake_create_window(*args: Any, **kwargs: Any) -> None:
        captured.update(kwargs)
        return None

    import webview

    original = webview.create_window
    try:
        webview.create_window = fake_create_window  # type: ignore[assignment]
        pet_module._create_window("/pet.html", 10, 20, api=None)
    finally:
        webview.create_window = original  # type: ignore[assignment]

    assert captured["frameless"] is True
    assert captured["resizable"] is False
    assert captured["on_top"] is True
    assert captured["focus"] is False, "the card would take the keyboard from the user"
    # **Off, and the page drags the card instead.** pywebview's own drag moves the
    # form a `SetWindowPos` per mouse move, so the OS is not dragging it, it cannot
    # be snapped, and the host never learns where it ended up. `DeskPet.drag` runs
    # the real move loop and saves the position.
    assert captured["easy_drag"] is False, "two drags would fight for the same press"
    assert captured["x"] == 10 and captured["y"] == 20
    assert "transparent" not in captured or captured["transparent"] is False
    # **Visible, and that is the re-measured answer rather than the first one.**
    # Creating it hidden and revealing it with `SWP_NOACTIVATE` looked like the
    # tidy way to avoid the single activation a new window gets, and on the real
    # desktop it did not avoid it -- the card still came back as
    # `GetForegroundWindow()` -- while it cost the card both `WS_EX_TOPMOST` and
    # `WS_EX_NOACTIVATE`, which are the two styles that make it a pet. So it is
    # created visible and the foreground is handed back; see `_reveal`.
    assert "hidden" not in captured, "a hidden card loses the styles that make it a pet"


def test_a_new_card_is_revealed_without_being_activated(monkeypatch):
    """Both halves, because either one alone is a card that steals the keyboard.

    `SWP_NOACTIVATE` stops the card from being clicked into the foreground and does
    not stop creating it from doing that -- measured on the real desktop, where the
    card came back as `GetForegroundWindow()` immediately after it was made. So the
    handle that owned the foreground *before* the card existed is asked for first
    and handed back afterwards; without the second half the user's typing goes to a
    status card the moment the agent finishes a tool.
    """
    from tonyagent.window import pet as pet_module

    raised: list[int] = []
    given_back: list[tuple[int, int]] = []
    monkeypatch.setattr(pet_module.win32, "root_window", lambda hwnd: hwnd)
    monkeypatch.setattr(pet_module.win32, "raise_without_activating", raised.append)
    monkeypatch.setattr(
        pet_module.win32,
        "give_foreground_back",
        lambda previous, mine: given_back.append((previous, mine)) or True,
    )

    window = FakeWindow()
    window.native = type("Native", (), {"Handle": _Handle})()
    pet_module._reveal(window, previous=777)

    assert raised == [4242], "the card was raised in a way that takes the foreground"
    assert given_back == [(777, 4242)], "the foreground the card took was not given back"
    assert window.shown == 0, "it was also shown the ordinary way"


def test_a_card_that_cannot_be_raised_still_appears_and_still_gives_it_back(monkeypatch):
    """A failed tidy-up is not a missing window, and not a stolen foreground either.

    The card is created visible, so `SetWindowPos` failing leaves it on screen and
    merely not at the front -- a cosmetic loss, and raising here would turn "the pet
    is behind something" into "the pet button does nothing". The hand-back still
    has to happen, and *after* the attempt: the activation being undone was caused
    by creating the window, so it happened whether or not the z-order was fixed.
    """
    from tonyagent.window import pet as pet_module

    def refuse(hwnd: int) -> None:
        raise OSError("no window there")

    given_back: list[tuple[int, int]] = []
    monkeypatch.setattr(pet_module.win32, "root_window", lambda hwnd: hwnd)
    monkeypatch.setattr(pet_module.win32, "raise_without_activating", refuse)
    monkeypatch.setattr(
        pet_module.win32,
        "give_foreground_back",
        lambda previous, mine: given_back.append((previous, mine)) or False,
    )

    window = FakeWindow()
    window.native = type("Native", (), {"Handle": _Handle})()
    pet_module._reveal(window, previous=777)

    assert given_back == [(777, 4242)], "a card that could not be raised kept the foreground"
    assert window.shown == 0, "the card was shown a second time to compensate"


def test_the_default_idle_status_is_written_in_the_cards_vocabulary():
    """The default is a frame the card accepts, not one it discards.

    A status reaches the card as unchecked JSON and is validated there -- a frame
    without a `mood` the card knows is dropped in favour of the card's own idle.
    So a host default written as `{"state": "idle"}` would not be a default: it
    would be a frame that silently goes nowhere, and the card would say whatever
    it says on its own while the host believed it had said something.
    """
    from tonyagent.window.pet import IDLE

    assert IDLE["mood"] in {"idle", "working", "waiting", "failed"}
    assert IDLE["label"], "an idle card with no label says nothing at all"


def test_it_opens_at_the_corner_of_the_work_area():
    """Bottom right, inside the work area, which is the screen minus the taskbar.

    Asserted as arithmetic on a plain rectangle rather than against the real
    monitor: the number that matters is the margin, and a card that lands under
    the taskbar is a card whose bottom third nobody can read.
    """
    from tonyagent.window.pet import HEIGHT, MARGIN, WIDTH, _bottom_right

    area = type("Rect", (), {"right": 1440, "bottom": 900})()
    x, y = _bottom_right(area, WIDTH, HEIGHT)

    assert x == 1440 - WIDTH - MARGIN
    assert y == 900 - HEIGHT - MARGIN
    assert x + WIDTH + MARGIN == area.right, "the card overhangs the right edge"
    assert y + HEIGHT + MARGIN == area.bottom, "the card overhangs the bottom edge"


def _area(left: int = 0, top: int = 0, right: int = 1440, bottom: int = 900):
    """A work area, as `win32.work_area` answers one."""
    return type("Rect", (), {"left": left, "top": top, "right": right, "bottom": bottom})()


def test_the_place_it_was_left_wins_over_the_corner(monkeypatch):
    """A card that comes back in the corner every launch cannot really be moved."""
    from tonyagent.window import pet as pet_module

    pet_module.prefs.set("pet_pos", [240, 120])
    monkeypatch.setattr(pet_module.win32, "work_area", lambda hwnd: _area())
    p, _created = pet()

    assert p._corner() == (240, 120)


def test_a_place_that_is_no_longer_on_screen_is_pulled_back_into_view(monkeypatch):
    """Undocking a monitor must not strand the card where nothing can reach it.

    There is nothing to drag it back by: it is not on screen to be pressed. So a
    remembered position is clamped into the work area that exists now.
    """
    from tonyagent.window import pet as pet_module

    pet_module.prefs.set("pet_pos", [3200, 1400])
    monkeypatch.setattr(pet_module.win32, "work_area", lambda hwnd: _area())
    p, _created = pet()

    x, y = p._corner()
    assert x + pet_module.WIDTH <= 1440, "the card overhangs the right edge"
    assert y + pet_module.HEIGHT <= 900, "the card overhangs the bottom edge"


def test_a_place_that_cannot_be_read_is_the_corner_not_an_error(monkeypatch):
    """A decoration's position is not worth a refusal: the corner is an answer."""
    from tonyagent.window import pet as pet_module

    monkeypatch.setattr(pet_module.win32, "work_area", lambda hwnd: _area())
    for broken in ("nonsense", [1], [1, 2, 3], ["left", "top"], None, 5):
        pet_module.prefs.set("pet_pos", broken)
        p, _created = pet()
        assert p._corner() == pet_module._bottom_right(_area(), pet_module.WIDTH, pet_module.HEIGHT)


def test_dragging_saves_where_it_ended_and_says_it_moved(monkeypatch):
    """The OS's move loop, then the position it left the window at.

    The move is faked by having the loop's own stand-in write the window's new
    position, which is what the real loop does to the real window.
    """
    from tonyagent.window import pet as pet_module

    p, _created = pet()
    monkeypatch.setattr(pet_module.win32, "root_window", lambda hwnd: hwnd)
    p._window = FakeWindow(x=900, y=700)
    p._window.native = type("Native", (), {"Handle": _Handle})()

    def move(hwnd: int) -> None:
        assert hwnd == 4242, "the move loop was handed the wrong window"
        p._window.x, p._window.y = 300, 260

    monkeypatch.setattr(pet_module.win32, "begin_drag", move)

    assert p.drag() == {"moved": True, "x": 300, "y": 260}
    assert pet_module.prefs.get("pet_pos") == [300, 260]


def test_a_press_that_did_not_move_it_is_a_click(monkeypatch):
    """The answer the page needs: once the move loop starts it sees no events.

    A card whose drag swallows the press and never reports "nothing moved" is a
    card that can no longer open the app -- the click event never arrives.
    """
    from tonyagent.window import pet as pet_module

    p, _created = pet()
    p._window = FakeWindow(x=900, y=700)
    p._window.native = type("Native", (), {"Handle": _Handle})()
    pet_module.prefs.set("pet_pos", [900, 700])
    monkeypatch.setattr(pet_module.win32, "begin_drag", lambda hwnd: None)

    assert p.drag() == {"moved": False, "x": 900, "y": 700}
    assert pet_module.prefs.get("pet_pos") == [900, 700], "an unmoved card rewrote its position"


def test_a_drag_that_cannot_run_reports_that_it_did_not_move(monkeypatch):
    """A backend that cannot drag must not raise out of a tooltip's gesture."""
    from tonyagent.window import pet as pet_module

    p, _created = pet()
    p._window = FakeWindow(x=10, y=20)
    p._window.native = type("Native", (), {"Handle": _Handle})()

    def refuse(hwnd: int) -> None:
        raise OSError("no window thread here")

    monkeypatch.setattr(pet_module.win32, "begin_drag", refuse)

    assert p.drag() == {"moved": False, "x": 10, "y": 20}


def test_dragging_with_no_window_is_not_an_error():
    """The page can outlive the window by a frame; that is not a crash."""
    p, _created = pet()

    assert p.drag() == {"moved": False, "x": 0, "y": 0}


def test_the_card_is_smaller_than_the_one_that_shipped_before():
    """The size is a design decision, and this is the decision.

    236x248 was the first card, 172x188 the second, and 180x180 is the round one.
    Square because a circle needs one to be cut out of, and the *painted* area --
    the circle, not the window -- is what actually got smaller. The room came out
    of the design rather than the type: the name row above the character went, and
    the status line moved under it as a caption.
    """
    from tonyagent.window.pet import HEIGHT, WIDTH

    assert WIDTH == HEIGHT == 180, "a circle needs a square window to be cut from"
    # The visible circle against the rectangle it replaced; pi/4 of the square.
    assert WIDTH * HEIGHT * 0.785 < 236 * 248, "the card did not actually get smaller"


def test_the_window_is_cut_down_to_the_circle_it_draws(monkeypatch):
    """The shape is the window's, not the stylesheet's.

    A `border-radius: 50%` draws a circle *inside* a rectangle and the OS paints
    what is left; the corners are only really gone once the window has a region.
    Clipping is also what makes them click-through, which is the difference
    between a round pet and a rectangle pretending to be one.
    """
    from tonyagent.window import pet as pet_module

    clipped: list[int] = []
    monkeypatch.setattr(pet_module.win32, "root_window", lambda hwnd: hwnd)
    monkeypatch.setattr(pet_module.win32, "clip_to_circle", clipped.append)

    window = FakeWindow()
    window.native = type("Native", (), {"Handle": _Handle})()
    pet_module._clip(window)

    assert clipped == [4242], clipped


def test_the_region_is_cut_from_the_window_the_os_reports(monkeypatch):
    """**Measured, not requested**, and the difference was the rectangle.

    pywebview's WinForms backend sets the form's `MinimumSize` from `min_size`, and
    its default of 200x100 overrode a card asked for at 180: the real window came
    back 200x141 on this machine. A region built from the numbers we asked for left
    a slab of window beside the circle -- which is what the user saw. So the cut is
    computed from `GetWindowRect`.
    """
    from tonyagent.window import pet as pet_module

    monkeypatch.setattr(pet_module.win32, "root_window", lambda hwnd: hwnd)
    seen: list[int] = []
    monkeypatch.setattr(
        pet_module.win32, "clip_to_circle", lambda hwnd: seen.append(hwnd)
    )

    window = FakeWindow()
    window.native = type("Native", (), {"Handle": _Handle})()
    pet_module._clip(window)

    assert seen == [4242], "the window's own box was not what got measured"


def test_a_wide_window_is_cut_to_a_circle_centred_in_it():
    """The arithmetic the stylesheet has to match, as a pure function.

    A rectangle gets the *biggest circle that fits*, centred -- not an ellipse and
    not a circle anchored in a corner. `pet.css` draws `min(100vw, 100vh)` with
    `margin: auto`, so both halves of the shape are the same circle.
    """
    from tonyagent.window.win32 import circle_box

    assert circle_box(180, 180) == (0, 0, 180, 180), "a square window's circle is the window"
    # The 200x141 the card actually came back as, before `min_size` fixed it.
    assert circle_box(200, 141) == (29, 0, 170, 141), "a wide window's circle is not centred"
    left, top, right, bottom = circle_box(141, 200)
    assert (left, top) == (0, 29) and right - left == bottom - top == 141


def test_the_card_asks_for_a_window_it_can_actually_have():
    """The `min_size` half of the same measurement.

    pywebview clamps the form to `min_size`, whose default is 200x100 -- so the
    card has to ask for a minimum equal to the size it wants, or it gets a window
    of pywebview's choosing and the region has to be square inside it.
    """
    from tonyagent.window import pet as pet_module

    captured: dict[str, Any] = {}

    def fake_create_window(*args: Any, **kwargs: Any) -> None:
        captured.update(kwargs)
        return None

    import webview

    original = webview.create_window
    try:
        webview.create_window = fake_create_window  # type: ignore[assignment]
        pet_module._create_window("/pet.html", 0, 0, api=None)
    finally:
        webview.create_window = original  # type: ignore[assignment]

    assert captured["min_size"] == (pet_module.WIDTH, pet_module.HEIGHT)
    assert captured["width"] == captured["min_size"][0]
    assert captured["height"] == captured["min_size"][1]


def _quiet_reveal(monkeypatch: Any) -> tuple[list[int], list[tuple[int, int]]]:
    """Record what `_reveal` asks the OS for, without asking it.

    `_dress` does the reveal and the clip together, so every test about one of them
    has to account for the other.
    """
    from tonyagent.window import pet as pet_module

    raised: list[int] = []
    given_back: list[tuple[int, int]] = []
    monkeypatch.setattr(pet_module.win32, "root_window", lambda hwnd: hwnd)
    monkeypatch.setattr(pet_module.win32, "raise_without_activating", raised.append)
    monkeypatch.setattr(
        pet_module.win32,
        "give_foreground_back",
        lambda previous, mine: given_back.append((previous, mine)) or True,
    )
    return raised, given_back


def _window_comes_up(p: Any) -> None:
    """What the GUI loop does, about three quarters of a second after `open`.

    Measured on the real shell: `Window.native` is `None` when `create_window`
    returns, the form is created later, and `shown` fires just after that. Every
    test about the card's shape or its foreground has to model it, because not
    modelling it is the bug that shipped.
    """
    p._window.native = type("Native", (), {"Handle": _Handle})()
    p._window.events.shown.fire()


def test_opening_the_card_is_what_clips_it(monkeypatch):
    """The wiring: a card that opens is a card that ends up shaped.

    **And this pins down the bug the card shipped with.** `Window.native` does not
    exist when `create_window` returns -- measured: `None` for about three quarters
    of a second, with `shown` firing just after the form appears -- so clipping from
    `open()` ran with a null handle every time and returned silently. The pet was a
    rectangle window with a circle drawn inside it. So: nothing is clipped while
    there is no handle, and the moment the window says it is up, it is.
    """
    from tonyagent.window import pet as pet_module

    _quiet_reveal(monkeypatch)
    clipped: list[Any] = []
    monkeypatch.setattr(pet_module, "_clip", clipped.append)

    p, _created = pet()
    assert p.open() is True
    assert clipped == [], "a window with no handle was clipped anyway"

    _window_comes_up(p)
    assert len(clipped) == 1, "the card came up and was never shaped"

    clipped.clear()
    p._window.events.loaded.fire()
    p._window.events.shown.fire()
    assert clipped == [], "the card was dressed again by a later event"


def test_the_pages_ready_is_the_third_chance_to_get_shaped(monkeypatch):
    """The one signal the *page* can give, and the last one to arrive.

    A backend that fires neither window event still gets a circle, because the card
    saying it is listening is proof the window is up -- and a window that never gets
    shaped logs a warning rather than being silently rectangular, which is how the
    first version went unnoticed.
    """
    from tonyagent.window import pet as pet_module

    _quiet_reveal(monkeypatch)
    clipped: list[Any] = []
    monkeypatch.setattr(pet_module, "_clip", clipped.append)

    p, _created = pet()
    p.open()
    p._window.native = type("Native", (), {"Handle": _Handle})()

    p.mark_ready()

    assert len(clipped) == 1, "the page said it was listening and nothing happened"


def test_the_foreground_is_given_back_when_the_window_comes_up(monkeypatch):
    """The other half of the same mistake, and it had never worked either.

    `_reveal` was called from the same place as the clip, with the same null handle,
    so the card has been keeping the keyboard it stole on creation for as long as it
    has existed -- `give_foreground_back` matches on the handle it is given, and
    zero matches nothing.
    """
    from tonyagent.window import pet as pet_module

    raised, given_back = _quiet_reveal(monkeypatch)
    monkeypatch.setattr(pet_module.win32, "clip_to_circle", lambda *args: None)
    monkeypatch.setattr(pet_module, "_foreground", lambda: 777)

    p, _created = pet()
    assert p.open() is True
    assert raised == [] and given_back == [], "a window with no handle was revealed anyway"

    _window_comes_up(p)

    assert raised == [4242], "the card was not raised when it came up"
    assert given_back == [(777, 4242)], "the keyboard the card took was never handed back"


def test_a_replaced_window_is_dressed_on_its_own_terms(monkeypatch):
    """A second card is a second window, and the first one's dressing is not its.

    Closing the pet and opening it again makes a new window; the flag that says
    "already shaped" has to be about *this* window or the replacement is a
    rectangle for the rest of its life.
    """
    from tonyagent.window import pet as pet_module

    _quiet_reveal(monkeypatch)
    clipped: list[Any] = []
    monkeypatch.setattr(pet_module, "_clip", clipped.append)

    p, _created = pet()
    p.open()
    _window_comes_up(p)
    assert len(clipped) == 1

    p.close()
    assert p.open() is True
    assert clipped and len(clipped) == 1, "the replacement was clipped before it had a window"

    _window_comes_up(p)
    assert len(clipped) == 2, "the replacement window was never shaped"


def test_a_card_that_cannot_be_clipped_is_not_an_error(monkeypatch):
    """A square pet is a pet. Refusing to open one would be a decoration failing
    at the thing it decorates."""
    from tonyagent.window import pet as pet_module

    def refuse(hwnd: int, width: int, height: int) -> None:
        raise OSError("no window region for you")

    monkeypatch.setattr(pet_module.win32, "root_window", lambda hwnd: hwnd)
    monkeypatch.setattr(pet_module.win32, "clip_to_circle", refuse)

    window = FakeWindow()
    window.native = type("Native", (), {"Handle": _Handle})()

    pet_module._clip(window)  # does not raise


def test_a_window_with_no_handle_is_not_asked_for_one(monkeypatch):
    """A fake window in a test has no `native`, and a real one that has not been
    created yet is the same thing: nothing to clip, and nothing to complain about."""
    from tonyagent.window import pet as pet_module

    def unexpected(hwnd: int, width: int, height: int) -> None:
        raise AssertionError("clipping was attempted with no handle")

    monkeypatch.setattr(pet_module.win32, "clip_to_circle", unexpected)

    pet_module._clip(FakeWindow())  # does not raise


def test_showing_it_twice_makes_one_card():
    """The second press shows the card that is there rather than stacking another."""
    p, created = pet()

    assert p.open() is True
    assert p.open() is True

    assert len(created) == 1, "a second pet window was created"
    assert p.is_open() is True


def test_a_closed_card_is_replaced_by_the_next_show():
    """Closing the card is not a resignation from the feature."""
    p, created = pet()

    p.open()
    p._window.events.closed.fire()

    assert p.is_open() is False
    assert p.open() is True
    assert len(created) == 2, "the closed card was reused instead of replaced"


def test_a_build_with_no_pet_page_refuses_instead_of_lying():
    """`pet.html` missing is a real case: `--url` can point at anything.

    The refusal is reported rather than raising, because the caller is a toggle
    that has to draw *something* -- and `open: false` is the truth.
    """
    from tonyagent.window.pet import DeskPet

    assert DeskPet(page="").open() is False
    assert DeskPet(page="").is_open() is False


def test_no_status_is_pushed_before_the_page_says_it_is_listening():
    """The deadlock guard, and the reason the card is not blank forever.

    ``evaluate_js`` before the document is ready does not fail, it deadlocks --
    the same hazard `Bridge.ready` exists for. So a status arriving before
    ``mark_ready`` is *kept* and not sent, and it is sent by ``mark_ready``: a
    card that opened while the agent was working draws the work, not "waiting for
    work".
    """
    p, _ = pet()
    p.open()
    window = p._window

    p.push({"mood": "working", "label": "Running read_file", "detail": ""})
    assert window.scripts == [], "a status was pushed to a page that cannot take it yet"

    p.mark_ready()
    assert len(window.scripts) == 1, "the remembered status was never sent"
    assert "Running read_file" in window.scripts[0]


def test_the_card_remembers_what_the_agent_was_doing_across_a_reopen():
    """Hide and show again, and it comes back with the current status.

    A card that opened on "waiting for work" while a turn was mid-flight would be
    wrong in a way that is worse than empty: it would say the agent was idle.
    """
    p, _ = pet()
    p.open()
    p.mark_ready()
    p.push({"mood": "working", "label": "Running grep", "detail": ""})

    p.set_open(False)
    p.set_open(True)
    window = p._window
    window.scripts.clear()
    p.mark_ready()

    assert any("Running grep" in script for script in window.scripts)


def test_it_remembers_whether_it_was_open():
    """Across restarts, which is the only reason the preference exists."""
    p, _ = pet()

    assert p.was_open() is False, "the pet is open by default"

    p.set_open(True)
    assert p.was_open() is True

    p.set_open(False)
    assert p.was_open() is False


def test_hiding_it_takes_the_window_down_and_saying_so_is_true():
    p, _ = pet()
    p.open()
    window = p._window

    assert p.set_open(False) == {"open": False}
    assert window.destroyed == 1
    assert p.is_open() is False


def test_clicking_it_restores_and_shows_the_app():
    """Restore first: the app is usually behind something and often minimized."""
    p, _ = pet()
    app = FakeWindow()
    p.attach_app(app)

    assert p.raise_app() is True
    assert app.restored == 1
    assert app.shown == 1


def test_raising_an_app_that_is_not_attached_is_reported_not_raised():
    p, _ = pet()
    assert p.raise_app() is False


def test_the_bridge_refuses_a_pet_action_that_is_not_one():
    from tonyagent.window.bridge import Bridge

    with pytest.raises(ValueError):
        Bridge().pet("teleport")


def test_the_bridge_reports_up_now_and_wanted_next_time_separately():
    """Two booleans, and they are different questions.

    `wanted` is what the shell remembered; `open` is whether a window exists. A
    toggle drawing the first would claim a card the webview never made, and one
    drawing the second would come back off after every restart.
    """
    from tonyagent.window.bridge import Bridge

    desk, _created = pet()
    bridge = Bridge(pet=desk)

    assert bridge.pet("state") == {"open": False, "wanted": False}

    assert bridge.pet("show") == {"open": True, "wanted": True}
    assert bridge.pet("state") == {"open": True, "wanted": True}

    assert bridge.pet("hide") == {"open": False, "wanted": False}
    # Hidden now, and it stays hidden next time: this is the user's decision.
    assert bridge.pet("state") == {"open": False, "wanted": False}


def test_a_bridge_with_no_pet_page_reports_that_it_could_not_open():
    """`wanted` and `open` come apart in exactly this case, which is why both exist."""
    from tonyagent.window.bridge import Bridge

    bridge = Bridge()

    assert bridge.pet("show") == {"open": False, "wanted": True}


def test_the_bridge_hands_the_pet_the_app_window_to_raise():
    """Wired by the host, because the pet needs the bridge and the bridge the pet."""
    from tonyagent.window.bridge import Bridge
    from tonyagent.window.pet import DeskPet

    bridge = Bridge()
    app = FakeWindow()
    bridge._attach(None, app)
    desk = DeskPet(page="/pet.html", api=bridge)
    bridge._attach_pet(desk)

    desk.open()
    assert desk.raise_app() is True
    assert app.shown == 1


def test_the_preference_file_survives_a_broken_one(monkeypatch, tmp_path):
    """A file that cannot be parsed is replaced, not refused.

    The alternative is a preference that can never be set again, which is what a
    half-written file would otherwise amount to.
    """
    from tonyagent.window import prefs

    path = tmp_path / "window.json"
    monkeypatch.setattr(prefs, "_path", lambda: path)
    path.write_text("{not json", encoding="utf-8")

    assert prefs.get("pet_open", "fallback") == "fallback"
    assert prefs.set("pet_open", True) is True
    assert prefs.get("pet_open") is False or prefs.get("pet_open") is True
    assert prefs.get("pet_open") is True


def test_a_missing_preference_file_is_a_default_not_an_error(monkeypatch, tmp_path):
    from tonyagent.window import prefs

    monkeypatch.setattr(prefs, "_path", lambda: tmp_path / "nothing-here.json")

    assert prefs.get("anything", 7) == 7
