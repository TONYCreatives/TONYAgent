"""Prove the four new controls in the running app, over CDP.

Every feature in this pass is a control that used to be a placeholder, and a
placeholder is exactly the kind of thing that passes a unit test and is dead in
the window. So this reads the live DOM of the packaged app:

* the send button is an icon with a name, not the word "Continue";
* the attach button is enabled and reaches a real, hidden file input;
* the model chip opens a menu with a filter in it;
* the tool budget popover opens, states the unit, and offers whole numbers.

What it cannot prove, and why that is not a gap: no message is sent. A send
costs money and needs a key, and the parts that matter -- the tool-call
counter, the content parts, the validation -- are covered by unit tests in
``test_tool_call_budget.py`` and ``test_attachments.py``. This is here to
confirm the wiring is *reached*, which no unit test can.

It shells out to ``probe_webview.py`` rather than importing it, so the socket
and frame handling stay in one place.

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

# Each entry is (name, javascript, checker). The javascript returns a small
# value so a failure names the control instead of dumping a document, and the
# checker says what "working" means for that one control.
PROBES: list[tuple[str, str, object]] = [
    (
        "send_is_icon",
        """
        (() => {
          const b = document.querySelector('.send-btn');
          if (!b) return { present: false };
          return {
            present: true,
            label: b.getAttribute('aria-label'),
            hasIcon: !!b.querySelector('svg'),
            rowText: b.closest('.composer-row').textContent,
          };
        })()
        """,
        lambda r: r["present"] and r["label"] == "Send" and r["hasIcon"]
        and "Continue" not in (r["rowText"] or ""),
    ),
    (
        "attach_enabled",
        """
        (() => {
          const b = document.querySelector('[aria-label="Attach a file"]');
          const input = document.querySelector('.file-input');
          if (!b) return { present: false };
          return {
            present: true,
            disabled: b.disabled,
            inputPresent: !!input,
            inputHidden: input ? getComputedStyle(input).display === 'none' : null,
            accepts: input ? (input.getAttribute('accept') || '').slice(0, 30) : null,
          };
        })()
        """,
        lambda r: r["present"] and not r["disabled"] and r["inputPresent"]
        and r["inputHidden"],
    ),
    (
        "model_menu",
        """
        (async () => {
          const chip = document.querySelector('.chip');
          if (!chip) return { present: false };
          chip.click();
          await new Promise((r) => setTimeout(r, 500));
          const menu = document.querySelector('.modelpicker');
          if (!menu) return { present: true, opened: false };
          return {
            present: true,
            opened: true,
            hasFilter: !!menu.querySelector('.modelpicker-filter'),
            items: menu.querySelectorAll('.modelpicker-item').length,
            note: (menu.querySelector('.modelpicker-note') || {}).textContent || '',
            expanded: chip.getAttribute('aria-expanded'),
          };
        })()
        """,
        # Whether it *has* items depends on a key being configured, which is not
        # this probe's business -- an empty list reports its own reason. What is
        # the contract is that it opens and is filterable.
        lambda r: r["present"] and r["opened"] and r["hasFilter"],
    ),
    (
        "budget_popover",
        """
        (async () => {
          const b = document.querySelector('.tool-budget-btn');
          if (!b) return { present: false };
          b.click();
          await new Promise((r) => setTimeout(r, 500));
          const pop = document.querySelector('.budget-popover');
          if (!pop) return { present: true, opened: false };
          return {
            present: true,
            opened: true,
            title: (pop.querySelector('.budget-popover-title') || {}).textContent,
            presets: [...pop.querySelectorAll('.budget-preset')].map(
              (p) => p.textContent
            ),
            buttonTitle: b.getAttribute('title'),
          };
        })()
        """,
        lambda r: r["present"] and r["opened"]
        and (r["title"] or "").lower().startswith("tool calls")
        and bool(r["presets"]),
    ),
]


def run_probe(expression: str) -> object:
    """Evaluate one expression through the existing CDP driver."""
    completed = subprocess.run(
        [sys.executable, str(PROBE), "-e", expression],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if completed.returncode != 0:
        raise RuntimeError((completed.stderr or completed.stdout).strip())
    text = completed.stdout.strip()
    try:
        return json.loads(text)
    except ValueError:
        # The driver prints a JSON value; anything else is a driver problem and
        # is better reported verbatim than coerced into a passing shape.
        raise RuntimeError(f"unreadable probe output: {text[:200]}")


def main() -> int:
    failures: list[str] = []
    for name, expression, check in PROBES:
        try:
            result = run_probe(expression)
        except Exception as exc:  # noqa: BLE001 - reported, not raised
            print(f"[FAIL] {name}: {exc}")
            failures.append(name)
            continue
        print(f"[{name}] {result}")
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
    print("\nevery control is wired and reachable in the packaged app")
    return 0


if __name__ == "__main__":
    sys.exit(main())
