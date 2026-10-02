/**
 * The per-turn tool call budget control.
 *
 * This number appears twice in the window: here, and on every tool card as
 * "Tool call 3/10". They are the same number, and the rules below are all
 * about them not drifting apart -- the control showing the core's value rather
 * than the one last clicked, and offering only values the core will accept.
 *
 * Presets *and* a free field. A user who wants 7 or 80 is the one who already
 * knows something about what a call costs, and rounding them to the nearest
 * thing on offer is not a decision they made. What keeps "1000, which reads as
 * unlimited" from being a hazard is the field's ceiling and its refusal in
 * place, not the absence of the field.
 */

import "./test-dom.js";
import assert from "node:assert/strict";
import { describe, test } from "node:test";

import { useState } from "react";

import { MAX_BUDGET, ToolBudgetControl, parseBudget } from "./ToolBudgetControl.js";
import {
  all,
  click,
  one,
  pointerDown,
  press,
  render,
  setValue,
  texts,
  wait,
} from "./test-render.js";

interface Harness {
  container: HTMLElement;
  calls: number[];
  closed: number;
}

async function control(props: {
  value: number | null;
  disabled?: boolean;
  open?: boolean;
} = { value: 10 }): Promise<Harness> {
  const calls: number[] = [];
  let closed = 0;
  const container = await render(
    <ToolBudgetControl
      value={props.value}
      disabled={props.disabled ?? false}
      open={props.open ?? false}
      onOpen={() => {}}
      onClose={() => {
        closed += 1;
      }}
      onChange={(limit) => calls.push(limit)}
    />,
  );
  return {
    container,
    calls,
    get closed() {
      return closed;
    },
  };
}

/**
 * A control whose open state the test actually owns.
 *
 * The dismissal tests have to go through a caller that can really close it.
 * An earlier version passed `open={true}` as a fixed prop and counted calls to
 * `onClose`, which cannot work: the component asks its parent to close, and a
 * parent pinned open is not going to. Worse, the test then waited for a node
 * that was never going to leave.
 */
function Live() {
  const [open, setOpen] = useState(true);
  return (
    <ToolBudgetControl
      value={10}
      disabled={false}
      open={open}
      onOpen={() => setOpen(true)}
      onClose={() => setOpen(false)}
      onChange={() => {}}
    />
  );
}

const live = () => render(<Live />);

const button = (container: HTMLElement) =>
  one(container, ".tool-budget-btn") as HTMLButtonElement | null;

const popover = (container: HTMLElement) => one(container, ".budget-popover");

const field = (container: HTMLElement) =>
  one(container, ".budget-custom-input") as HTMLInputElement | null;

const problem = (container: HTMLElement) => one(container, ".budget-problem");

// --- the number ------------------------------------------------------------
describe("the tool budget control's number", () => {
  test("it shows the budget the core is holding", async () => {
    const { container } = await control({ value: 25 });
    assert.match(button(container)!.getAttribute("title") ?? "", /25 per turn/);
  });

  test("it says it is reading rather than drawing a number it does not have", async () => {
    // Null means the core has not answered yet. A control that showed "10"
    // from a default would be reporting a budget no turn is held to, and this
    // number is what a reader watches to see a turn approaching its cap.
    const { container } = await control({ value: null });
    const title = button(container)!.getAttribute("title") ?? "";
    assert.match(title, /reading/);
    assert.doesNotMatch(title, /\d+ per turn/);
  });

  test("it is named for a screen reader", async () => {
    const { container } = await control({ value: 10 });
    assert.equal(button(container)!.getAttribute("aria-label"), "Tool call budget");
  });

  test("it is disabled when the window is disabled", async () => {
    const { container } = await control({ value: 10, disabled: true });
    assert.equal(button(container)!.disabled, true);
  });
});

// --- the popover -----------------------------------------------------------
describe("the tool budget popover", () => {
  test("it is not in the DOM until it is opened", async () => {
    // A permanently mounted panel is a panel covering the transcript, and a
    // composer row control should cost nothing until it is used.
    const { container } = await control({ value: 10, open: false });
    assert.equal(popover(container), null);
  });

  test("it states the unit, because a number without one is a riddle", async () => {
    // "Tool calls per turn", and the hint says a call is a call: a model
    // asking for five tools in one message has spent five, not one.
    const { container } = await control({ value: 10, open: true });
    assert.deepEqual(texts(container, ".budget-popover-title"), [
      "Tool calls per turn",
    ]);
    const hint = one(container, ".budget-popover-hint")!.textContent ?? "";
    assert.match(hint, /one call at a time/);
    assert.match(hint, /five/);
  });

  test("the current budget is the chosen one", async () => {
    const { container } = await control({ value: 20, open: true });
    const active = all(container, ".budget-preset.is-active");
    assert.deepEqual(texts(container, ".budget-preset.is-active"), ["20"]);
    assert.equal(active.length, 1, "two presets claim to be the current budget");
  });

  test("choosing a budget asks the core for it", async () => {
    const { container, calls } = await control({ value: 10, open: true });
    await click(all(container, ".budget-preset")[3] as HTMLButtonElement);
    assert.deepEqual(calls, [20]);
  });

  test("every offered value is a whole number of calls", async () => {
    const { container, calls } = await control({ value: 10, open: true });
    for (const preset of all(container, ".budget-preset")) {
      await click(preset);
    }
    assert.ok(calls.length > 0, "no preset was offered at all");
    for (const limit of calls) {
      assert.equal(Number.isInteger(limit), true, `${limit} is not a whole number`);
      assert.ok(limit >= 1, `${limit} would refuse every tool`);
    }
  });

  test("a budget set elsewhere is shown, not snapped to a preset", async () => {
    // 7 from the environment. Snapping it to the nearest preset would make
    // the control report a budget the core is not holding -- the same lie as
    // showing a default before the core has answered.
    const { container } = await control({ value: 7, open: true });
    assert.equal(all(container, ".budget-preset.is-active").length, 0);
    assert.match(one(container, ".budget-custom")!.textContent ?? "", /7 per turn/);
  });

  test("a budget that is a preset says so with the preset, not a duplicate line", async () => {
    const { container } = await control({ value: 10, open: true });
    assert.equal(one(container, ".budget-custom"), null);
  });

  test("the popover closes when the pointer goes down elsewhere", async () => {
    // The row menu's dismissal, applied here: a popover that only closes on
    // its own button is a popover a user has to hunt for the exit to.
    //
    // Driven with real state rather than a fixed `open` prop, because the
    // dismissal is the component calling `onClose` and the caller is what
    // stops being open. A harness that pinned `open: true` would render a
    // popover that is not open and assert on a lie.
    const container = await live();
    assert.ok(popover(container), "the popover never opened");
    await pointerDown(document.body);
    await wait(300);
    assert.equal(popover(container), null, "clicking away did not dismiss it");
  });

  test("Escape closes it too", async () => {
    // Same contract as the confirmation dialog, which can now be denied with
    // Escape: a panel that traps the user until they find its button is a
    // panel some people never leave.
    const container = await live();
    await press("Escape");
    await wait(300);
    assert.equal(popover(container), null, "Escape did not dismiss it");
  });

  test("pressing a preset is not a press elsewhere", async () => {
    // The bug this file was written for. `window.addEventListener("pointerdown",
    // close, true)` fires on the way *down*, for every press including presses
    // that land inside the popover -- so choosing 20 closed the popover on the
    // way to choosing 20, and the value changed under a panel that was on its
    // way out.
    //
    // Asserted on `data-state` immediately after the press: the node is still
    // mounted (it has to be, or the exit has nothing to animate), so "closed"
    // here is a state and not an absence.
    const container = await live();
    assert.ok(popover(container), "the popover never opened");
    await pointerDown(all(container, ".budget-preset")[2]);
    assert.equal(
      popover(container)!.dataset.state,
      "open",
      "pressing a preset dismissed the popover it was in",
    );
  });

  test("pressing the number field is not a press elsewhere either", async () => {
    const container = await live();
    await pointerDown(field(container)!);
    assert.equal(
      popover(container)!.dataset.state,
      "open",
      "pressing the field dismissed the popover it was in",
    );
  });
});

// --- the free field --------------------------------------------------------
describe("typing a budget", () => {
  test("the field opens holding the budget the core is holding", async () => {
    // Not empty. A blank field beside a control that already knows the number
    // asks the user to re-enter what the window is displaying, and the first
    // keystroke then means "replace it" rather than "edit it".
    const { container } = await control({ value: 12, open: true });
    assert.equal(field(container)!.value, "12");
  });

  test("a number that is not a preset goes through", async () => {
    const { container, calls } = await control({ value: 10, open: true });
    await setValue(field(container)!, "7");
    await press("Enter", field(container)!);
    assert.deepEqual(calls, [7]);
  });

  test("the Set button applies it too", async () => {
    // Two ways in, because Enter is not the only thing a person does to a
    // number field and reaching for the mouse is not an error.
    const { container, calls } = await control({ value: 10, open: true });
    await setValue(field(container)!, "80");
    await click(one(container, ".budget-custom-apply") as HTMLButtonElement);
    assert.deepEqual(calls, [80]);
  });

  test("zero is refused in the popover, with the reason", async () => {
    // `_h_tools_set` refuses it too, and this mirrors that rather than
    // deferring to it: a round trip would take the focus off the field to
    // render a failure several hundred pixels away, and throw away what was
    // typed. Zero is not a small budget, it is a refusal of every tool.
    const { container, calls } = await control({ value: 10, open: true });
    await setValue(field(container)!, "0");
    await press("Enter", field(container)!);
    assert.deepEqual(calls, [], "a zero budget was sent to the core");
    assert.match(problem(container)!.textContent ?? "", /at least one/i);
    assert.ok(popover(container), "the popover closed on a refused value");
  });

  test("editing after a refusal clears it, so it cannot go stale", async () => {
    const { container } = await control({ value: 10, open: true });
    await setValue(field(container)!, "0");
    await press("Enter", field(container)!);
    assert.ok(problem(container));
    await setValue(field(container)!, "8");
    assert.equal(problem(container), null, "the refusal outlived the typo");
  });

  test("the field is not clamped while it is being typed into", async () => {
    // Typing "10" passes through "1" and then "10"; a field that rewrites what
    // is under the cursor turns every edit into a fight with the caret.
    const { container } = await control({ value: 10, open: true });
    await setValue(field(container)!, "1");
    assert.equal(field(container)!.value, "1");
    assert.equal(problem(container), null);
  });

  test("the field is disabled when the core is not reachable", async () => {
    const { container } = await control({ value: 10, open: true, disabled: true });
    assert.equal(field(container)!.disabled, true);
  });
});

// --- what the field will accept -------------------------------------------
describe("parseBudget", () => {
  /** The refusal message, or "" when the value was accepted. */
  const reason = (text: string): string => {
    const parsed = parseBudget(text);
    return "reason" in parsed ? parsed.reason : "";
  };

  test("a whole number in range is the limit", () => {
    assert.deepEqual(parseBudget("7"), { limit: 7 });
    assert.deepEqual(parseBudget("  7  "), { limit: 7 });
    assert.deepEqual(parseBudget(String(MAX_BUDGET)), { limit: MAX_BUDGET });
  });

  test("nothing typed is not a budget of zero", () => {
    assert.match(reason(""), /enter/i);
    assert.match(reason("   "), /enter/i);
  });

  test("zero and negatives are refused, not clamped", () => {
    assert.match(reason("0"), /at least one/i);
    assert.match(reason("-5"), /at least one/i);
  });

  test("a fraction is refused, because a call is a whole thing", () => {
    assert.match(reason("2.5"), /whole/i);
  });

  test("text that only starts with a number is refused", () => {
    // `parseInt("12abc")` is 12. Accepting that would apply a budget the user
    // did not type.
    assert.match(reason("12abc"), /not a number/i);
    assert.match(reason("abc"), /not a number/i);
  });

  test("past the ceiling is refused by name", () => {
    // The message quotes the limit rather than saying "too many", because the
    // number is the thing the user has to change.
    assert.match(reason(String(MAX_BUDGET + 1)), new RegExp(String(MAX_BUDGET)));
  });

  test("the ceiling is a bound and not a suggestion", () => {
    // A budget nobody can express gets rounded to the nearest thing on offer,
    // which is a decision the user did not make.
    assert.equal(reason(String(MAX_BUDGET)), "");
    assert.ok(reason(String(MAX_BUDGET + 1)).length > 0);
  });
});

// --- it outlives the dismissal --------------------------------------------
describe("the tool budget popover on the way out", () => {
  test("it stays mounted briefly so the exit can be seen", async () => {
    // Same reason the row menu does: unmounting on click deletes the node
    // before styles.css can play the exit, and the panel vanishes.
    const { container } = await control({ value: 10, open: false });
    // Rendered already closed: the node exists for the exit animation.
    const node = popover(container);
    if (node) {
      assert.equal(node.getAttribute("data-state"), "closed");
      await wait(300);
      assert.equal(
        popover(container),
        null,
        "the panel outlived its exit animation",
      );
    }
  });
});
