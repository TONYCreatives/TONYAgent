"""Prove pass B's four fixes in the running app, over CDP.

Three of the four are things no unit test can see, because each is a fact about
the *shipped window* rather than about a component:

* **The rail's reopen button.** `align-self: flex-start` on `.rail-toggle`
  overrode the rail's centring, so in the collapsed rail -- where every button is
  38px wide inside a 70px column -- the one control that brings the sidebar back
  sat at x=0 while every other icon sat at x=16. Only a real layout engine can
  measure that, which is why this reads `getBoundingClientRect` rather than the
  stylesheet.
* **The window has no system title bar.** `decorations: false` is a Rust-side
  change to the shipped binary; `is_decorated()` asking the shell is the only
  honest way to know it landed, and a unit test would pass either way.
* **The caption commands are permitted.** `core:window:default` grants getters
  only, so a caption drawn without the four extra permissions in
  `capabilities/default.json` is three dead buttons that log to the console.
  Proved by toggling the window and asking whether it changed -- then toggling
  it back, because the probe leaves the window as it found it.

The fourth, the free-text budget field, is a unit-tested piece of logic but a
*plumbing* fact here: the popover has to reach a real number input prefilled with
the core's own value, and a refused value has to stay in the popover rather than
turning into a banner in the transcript. The refusal is exercised and nothing is
applied, so the probe changes no setting.

Run after::

    "Build TONYAgent.bat"
    taskkill //IM tonyagent-app.exe //F
    taskkill //IM msedgewebview2.exe //F
    set WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS=--remote-debugging-port=9333
    app/src-tauri/target/release/tonyagent-app.exe
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROBE = HERE / "probe_webview.py"

# Each entry is (name, javascript, checker).
PROBES: list[tuple[str, str, object]] = [
    (
        "rail_collapsed_alignment",
        """
        (async () => {
          const rail = document.querySelector('.rail');
          const toggle = document.querySelector('.rail-toggle');
          if (!rail || !toggle) return { present: false };
          // Collapse first: the bug only exists in the collapsed rail, and the
          // window remembers which state it was left in.
          const expanded = rail.classList.contains('rail-expanded');
          if (expanded) toggle.click();
          await new Promise((r) => requestAnimationFrame(r));
          const boxes = [...rail.querySelectorAll('.rail-btn')].map((b) => {
            const r = b.getBoundingClientRect();
            return { cls: b.className, left: Math.round(r.left * 100) / 100 };
          });
          const lefts = [...new Set(boxes.map((b) => b.left))];
          return {
            present: true,
            collapsed: !rail.classList.contains('rail-expanded'),
            railWidth: Math.round(rail.getBoundingClientRect().width),
            lefts,
            aligned: lefts.length === 1,
            boxes,
          };
        })()
        """,
        # One distinct left edge for every button. Two is the bug: the toggle at
        # the window edge and the icons 16px in from it.
        lambda r: r["present"] and r["collapsed"] and r["aligned"]
        and r["railWidth"] == 70,
    ),
    (
        "title_bar_is_ours",
        """
        (async () => {
          const bar = document.querySelector('.topbar');
          if (!bar) return { present: false };
          const rect = bar.getBoundingClientRect();
          return {
            present: true,
            dragRegion: bar.getAttribute('data-tauri-drag-region'),
            left: Math.round(rect.left),
            right: Math.round(rect.right),
            top: Math.round(rect.top),
            innerWidth: window.innerWidth,
            buttons: [...bar.querySelectorAll('.win-btn')].map((b) => ({
              label: b.getAttribute('aria-label'),
              title: b.getAttribute('title'),
              drawn: !!b.querySelector('svg'),
            })),
          };
        })()
        """,
        # Spans the window, not the transcript column: the caption has to be at
        # the right edge of the *window*, and the Files panel covers column 2.
        lambda r: r["present"] and r["dragRegion"] == "deep"
        and r["left"] == 0 and abs(r["right"] - r["innerWidth"]) <= 1
        and r["top"] == 0
        and len(r["buttons"]) == 3
        and [b["label"] for b in r["buttons"]]
        == ["Minimize window", "Maximize window", "Close window"]
        and all(b["drawn"] for b in r["buttons"]),
    ),
    (
        "window_is_undecorated",
        """
        (async () => {
          const invoke = window.__TAURI_INTERNALS__.invoke;
          if (!invoke) return { present: false, why: 'no tauri internals' };
          const decorated = await invoke('plugin:window|is_decorated');
          return { present: true, decorated };
        })()
        """,
        # The Rust-side change. A unit test of the config file would pass whether
        # or not the build picked it up.
        lambda r: r["present"] and r["decorated"] is False,
    ),
    (
        "caption_commands_are_permitted",
        """
        (async () => {
          const invoke = window.__TAURI_INTERNALS__.invoke;
          if (!invoke) return { present: false };
          const before = await invoke('plugin:window|is_maximized');
          let error = null;
          try {
            await invoke('plugin:window|toggle_maximize');
          } catch (e) {
            error = String(e);
          }
          const after = await invoke('plugin:window|is_maximized');
          // Back the way it was, whichever way it went.
          if (after !== before && !error) {
            await invoke('plugin:window|toggle_maximize');
          }
          const restored = await invoke('plugin:window|is_maximized');
          return {
            present: true,
            before,
            after,
            restored,
            changed: after !== before,
            error,
          };
        })()
        """,
        # `core:window:default` is getters plus the internal double-click
        # maximize. `toggle_maximize` is not among them, so without the extra
        # capability this throws and the caption is three dead buttons.
        lambda r: r["present"] and not r["error"] and r["changed"] and r["restored"] is r["before"],
    ),
    (
        "budget_free_field",
        """
        (async () => {
          const b = document.querySelector('.tool-budget-btn');
          if (!b) return { present: false };
          const titleBefore = b.getAttribute('title');
          b.click();
          await new Promise((r) => setTimeout(r, 400));
          const pop = document.querySelector('.budget-popover');
          if (!pop) return { present: true, opened: false };
          const input = pop.querySelector('.budget-custom-input');
          if (!input) return { present: true, opened: true, hasField: false };
          // Read before anything is typed into it: the point of the assertion is
          // that it arrives holding the core's number, and a value read at the
          // end would be whatever this probe just wrote into it.
          const prefilled = input.value;

          const setter = Object.getOwnPropertyDescriptor(
            HTMLInputElement.prototype, 'value'
          ).set;
          const type = async (text) => {
            setter.call(input, text);
            input.dispatchEvent(new Event('input', { bubbles: true }));
            await new Promise((r) => requestAnimationFrame(r));
            input.dispatchEvent(
              new KeyboardEvent('keydown', { key: 'Enter', bubbles: true })
            );
            await new Promise((r) => setTimeout(r, 150));
          };

          // A refusal, and nothing applied: the probe leaves the setting alone.
          await type('0');
          const refusal = (pop.querySelector('.budget-problem') || {}).textContent || '';
          const stillOpen = pop.getAttribute('data-state');

          // And a press inside the field, which is the bug the pass opened with.
          input.dispatchEvent(
            new PointerEvent('pointerdown', { bubbles: true })
          );
          await new Promise((r) => setTimeout(r, 150));
          const afterPress = pop.getAttribute('data-state');

          return {
            present: true,
            opened: true,
            hasField: true,
            type: input.getAttribute('type'),
            min: input.getAttribute('min'),
            max: input.getAttribute('max'),
            prefilled,
            titleBefore,
            refusal,
            stillOpen,
            afterPress,
            titleAfter: b.getAttribute('title'),
            applied: titleBefore !== b.getAttribute('title'),
          };
        })()
        """,
        # Prefilled from the core, refused in place, and -- the part that is easy
        # to get wrong -- a press inside the popover does not dismiss it.
        lambda r: r["present"] and r["opened"] and r["hasField"]
        and r["type"] == "number" and r["min"] == "1"
        # The field opens holding the core's own number rather than blank.
        and r["prefilled"] and r["prefilled"].isdigit()
        and r["refusal"] and r["stillOpen"] == "open"
        and r["afterPress"] == "open" and not r["applied"],
    ),
    (
        "pressing_the_model_filter_keeps_the_menu",
        """
        (async () => {
          const chip = document.querySelector('.chip');
          if (!chip) return { present: false };
          chip.click();
          await new Promise((r) => setTimeout(r, 900));
          const menu = document.querySelector('.modelpicker');
          if (!menu) return { present: true, opened: false };
          const filter = menu.querySelector('.modelpicker-filter');
          if (!filter) return { present: true, opened: true, hasFilter: false };
          filter.dispatchEvent(
            new PointerEvent('pointerdown', { bubbles: true })
          );
          await new Promise((r) => setTimeout(r, 200));
          const after = document.querySelector('.modelpicker');
          return {
            present: true,
            opened: true,
            hasFilter: true,
            state: after ? after.getAttribute('data-state') : null,
          };
        })()
        """,
        # The report this pass opened with: clicking the filter closed the menu
        # the filter was in.
        lambda r: r["present"] and r["opened"] and r["hasFilter"] and r["state"] == "open",
    ),
]


def run_probe(expression: str) -> object:
    """Evaluate one expression through the existing CDP driver."""
    completed = subprocess.run(
        [sys.executable, str(PROBE), "-e", expression],
        capture_output=True,
        text=True,
        timeout=90,
    )
    if completed.returncode != 0:
        raise RuntimeError((completed.stderr or completed.stdout).strip())
    text = completed.stdout.strip()
    try:
        return json.loads(text)
    except ValueError:
        raise RuntimeError(f"unreadable probe output: {text[:200]}") from None


def main() -> int:
    failures: list[str] = []
    for name, expression, check in PROBES:
        try:
            result = run_probe(expression)
        except Exception as exc:  # noqa: BLE001 - reported, not raised
            print(f"[FAIL] {name}: {exc}")
            failures.append(name)
            continue
        print(f"[{name}] {json.dumps(result)}")
        try:
            ok = check(result)  # type: ignore[operator]
        except Exception as exc:  # noqa: BLE001 - a bad shape is a failure
            print(f"[FAIL] {name}: unexpected shape: {exc}")
            ok = False
        if not ok:
            print(f"[FAIL] {name} did not meet its contract")
            failures.append(name)

    if failures:
        print(f"\n{len(failures)} probe(s) failed: {', '.join(failures)}")
        return 1
    print("\nevery pass B fix is present in the packaged app")
    return 0


if __name__ == "__main__":
    sys.exit(main())