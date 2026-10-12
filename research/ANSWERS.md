# Answers to the researcher's three questions

Relay these as-is. Each ends with the constraint the research should be designed
against.

## 1. Rasterisation fallback: idle CPU first — and neither should be a fixed clock

**Idle CPU, decisively.** This is a desktop pet: it sits on top of everything for
hours while the user works in another window, and the only thing it has to do in
that time is *nothing*. A decoration that costs 2% of a core forever gets turned off.
Judder in a slow breathing loop, by contrast, is close to invisible.

But the question's framing — 8–12 fps versus idle cost — is the wrong trade to
accept, because there is a third answer that removes it: **do not run a clock at
all.** Schedule work from state changes, not from a frame rate.

- **Asleep and idle-awake: zero scheduled work.** One static frame, no timer, no
  `UpdateLayeredWindow` call. Falling asleep is the design's own "nothing is
  happening" state, so it must cost nothing.
- **Awake-but-idle: only the blink is time-driven** (~120 ms, every 2–3 s). That is
  one timer that fires rarely, not a 12 fps loop.
- **Working: the typing loop is the only sustained animation**, and it only exists
  while the agent is running a turn.
- **Transitions (a hop, a shake, a fall-asleep) are discrete short sequences.**

So the requirement is: **a frame write happens only when the composed frame actually
changes** — assert it by measuring that the frame index is unchanged across an idle
minute. If the implementation can't promise that, it loses to the hard-edged circle
we already have.

Pacing then applies narrowly, and the honest form of the requirement is:

- a **discrete, fast** sequence (a blink) must not stutter — that is where a late
  frame is actually perceptible, because it is short and has a beginning and an end;
- a **sustained loop** (breathing, typing) may drop a frame without anyone noticing,
  but must not visibly *drift* over a second;
- a missed frame at a *pose boundary* (idle → working) is the one that reads as a
  glitch, so boundary transitions should be latched to the state change rather than
  to the next tick.

Acceptance numbers to design against: **no frame writes and no timer activity while
asleep**; under ~10 fps sustained while working; frame-write cost measured in
microseconds so the budget is knowable; and **all rasterisation done at build time,
not at startup** (Playwright at launch would add a browser to the startup path of a
status card).

## 2. WPF/WinUI host: the primitive is negotiable, the behaviours are not

**`WM_NCLBUTTONDOWN` + `ReleaseCapture` is not a hard requirement. Its behaviours
are.** In order of how strongly they should be defended:

1. **Never activates** (`WS_EX_NOACTIVATE`). Hard requirement, non-negotiable: the
   user must be able to keep typing elsewhere while the pet is on screen.
2. **Click versus drag is distinguishable.** A press that moves nothing must still
   raise the app window. We get this today from the move loop's return: it is modal,
   so when it comes back the host answers "did it move", and a non-move is treated as
   a click. Any replacement needs an equally reliable answer — a page-side threshold
   is not enough, because the modal loop swallows every event after the press.
3. **The final position is reported back to the host and persisted**, in a stated
   coordinate space. This bit us already: a window asked for at 180×180 came back
   **200×141** because pywebview's `min_size` default (200×100, logical units) clamps
   the form. WPF's `Left`/`Top` are device-independent pixels while `GetWindowRect` is
   physical, so at 150% scaling they disagree — say which space you mean, and prefer
   the physical one for anything passed to Win32.
4. **Native snap behaviour** (Aero Snap, Snap Layouts). This is the reason we
   *removed* pywebview's own custom drag: `easy_drag` moves the form one
   `SetWindowPos` per mouse move, and a window moved by hand is not a window the OS is
   dragging, so it cannot be snapped. It is the one behaviour I would accept losing
   only with it written down and agreed.

So: if a WPF window still exposes its HWND (`WindowInteropHelper`) and the OS move
loop still works there — verify that WPF's own input handling does not eat the
press — **keep the OS loop.** A custom drag is acceptable if and only if it delivers
1–3 above and either keeps 4 or explicitly trades it away. Note also that whatever the
host, the gesture has to be issued on the window's own thread; we have that
marshalling already and it is not optional (issued from a worker thread the loop never
takes and the window does not move a pixel).

## 3. Verification: automated, in two tiers, plus a short manual list

**Both — split by what can run without a user watching.** The acceptance test for
this whole investigation is automated, and it is one assertion:

> Across the rim, sample a horizontal run of pixels. There must exist pixels
> **strictly between** the card's colour and the backdrop's, and the transition must
> span **at least two** pixels.

That is what "antialiased" means, it is objective, and **it fails today** — a GDI
region gives a binary edge. Design the solution against it.

**Tier 1 — CI-safe, no window** (this is the house style here: every CSS animation is
audited by a test that reads the stylesheet). Unit-level assertions that the shape is
requested, that the shadow policy is requested, that a failed shape is retried, that
the page's drawn circle is the same size the region cuts (`min(100vw, 100vh)`), and
that any raster assets exist at the right dimensions. Cheap, fast, no GUI.

**Tier 2 — opt-in, needs a real window**, gated behind an environment variable the way
this repo's live WSL tests are (`TONYAGENT_TEST_WSL=1`): open the real window over a
known backdrop and assert
(a) `GetWindowRgn` reports a complex region with the corner outside it;
(b) the ring of pixels just outside the window's rect equals the backdrop — the
rectangular-shadow regression, which is exactly the bug that took a screenshot to
find;
(c) `WindowFromPoint` at a rect corner returns a window that is *not* the pet
(click-through);
(d) the rim-interpolation assertion above, at 100%, 150% and 200% scaling.

**Tier 3 — manual, and kept to about six items**, because these are judgements no
assertion makes: does the rim look smooth at each DPI; is there a flicker when the pet
opens; does it look right over light, dark and photographic wallpapers; does the drag
(and snap) feel like a window; does typing elsewhere stay uninterrupted; and is the
idle CPU in the measurement you asked for in answer 1.

One note on coverage: this repository's `check_all.py` runs compile, a launch check and
the test suite, and its Docker integration test is already excluded when no daemon is
present — so an environment-dependent tier-2 probe is normal here, but it has to *skip*
cleanly rather than fail when it cannot run.
