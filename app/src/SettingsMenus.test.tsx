/**
 * The permission and thinking menus, rendered in jsdom.
 *
 * Both controls' whole claim is that they change something real, so most of
 * these are about them not lying: that Permission draws the levels the core
 * sent rather than four hardcoded names, that it says which rung is in force,
 * that the one rung which acts without asking says so where it can be seen,
 * and that Thinking offers the provider's own efforts rather than a guess.
 *
 * **The two are tested through one file because they are one control.** They
 * share every part but the framing -- Permission is four rows on screen and
 * Thinking is a popover -- so the tests that matter most (that the control names
 * the value in force, that picking one asks the core, that re-picking the
 * current one does not, that Escape closes a popover without closing the panel
 * behind it) are asserted once and would otherwise be duplicated in a way that
 * lets the two copies drift apart, which is exactly what "one vocabulary" is
 * supposed to prevent.
 *
 * **Where a test needs a press, it presses the control the user would.** The
 * permission ladder has no trigger any more, so a test that clicks one is
 * asserting a shape that was deliberately removed -- and `openMenu` below is
 * named for the framing it opens rather than for the control, so a reader can
 * see which of the two it is talking about.
 */

import "./test-dom.js";
import assert from "node:assert/strict";
import { describe, test } from "node:test";
import { dom } from "./test-dom.js";

import {
  PermissionMenu,
  ThinkingMenu,
  measureMenu,
  permissionGain,
  type MenuBounds,
  type PermissionInfo,
  type PermissionList,
  type ReasoningInfo,
} from "./SettingsMenus.js";
import { all, click, one, render, texts } from "./test-render.js";

const { window: domWindow } = dom;

/** The four levels the core sends, in order. */
const level = (over: Partial<PermissionInfo> = {}): PermissionInfo => ({
  name: "low",
  label: "Low",
  description: "Read, search and browse.",
  runs_commands: false,
  skips_confirmation: false,
  runs_any_command: false,
  // Mirrors the core ladder, where only Full runs on the host. Spelled out here
  // rather than defaulted, so a fixture that forgets the flag reads as the
  // sandboxed level -- the safe direction to be wrong in.
  runs_on_host: false,
  ...over,
});

const LADDER: PermissionList = {
  permission: "medium",
  permissions: [
    level(),
    level({
      name: "medium",
      label: "Medium",
      description: "Edit files. Shell commands are refused.",
    }),
    level({
      name: "high",
      label: "High",
      description: "Everything, including running commands.",
      runs_commands: true,
    }),
    level({
      name: "full",
      label: "Full",
      description: "Everything, without asking first.",
      runs_commands: true,
      skips_confirmation: true,
      runs_any_command: true,
      runs_on_host: true,
    }),
  ],
};

/** A model that can be asked to think at five different depths. */
function reasoning(over: Partial<ReasoningInfo> = {}): ReasoningInfo {
  return {
    supported: true,
    efforts: ["max", "xhigh", "high", "medium", "low"],
    default_effort: "max",
    mandatory: true,
    effort: "high",
    ...over,
  };
}

async function renderPermission(
  over: Partial<React.ComponentProps<typeof PermissionMenu>> = {},
) {
  const changed: string[] = [];
  const container = await render(
    <PermissionMenu
      list={LADDER}
      value="medium"
      busy={false}
      disabled={false}
      onChange={(name) => changed.push(name)}
      {...over}
    />,
  );
  return { container, changed };
}

async function renderThinking(
  over: Partial<React.ComponentProps<typeof ThinkingMenu>> = {},
) {
  const changed: string[] = [];
  const container = await render(
    <ThinkingMenu
      info={reasoning()}
      busy={false}
      disabled={false}
      onChange={(effort) => changed.push(effort)}
      {...over}
    />,
  );
  return { container, changed };
}

const steps = (c: HTMLElement) =>
  all(c, ".permchoice-step").map((e) => e.classList.contains("is-on"));

/** The rungs, as they are: on screen, with nothing to open first. */
const rungs = (c: HTMLElement) => all(c, ".permchoice-item");

/** The popover's own: the thinking dial is the only control here that has one. */
const openMenu = async (c: HTMLElement) => {
  await click(one(c, ".permchoice-trigger")!);
  return one(c, ".permchoice-menu");
};

// --- the permission menu draws the ladder the core sent -------------------
describe("the permission menu draws the ladder the core sent", () => {
  test("one segment per level, filled up to and including the current one", async () => {
    // A ladder, not four independent choices. "Filled up to here" is the claim
    // that Medium sits between Low and High; four separate buttons would say
    // "pick one", which is a different and wrong thing.
    const { container } = await renderPermission({ value: "medium" });
    assert.equal(all(container, ".permchoice-step").length, 4);
    assert.deepEqual(steps(container), [true, true, false, false]);
  });

  test("the current level is named, not just drawn", async () => {
    const { container } = await renderPermission({ value: "high" });
    assert.deepEqual(texts(container, ".permchoice-value"), ["High"]);
    assert.deepEqual(steps(container), [true, true, true, false]);
  });

  test("and it draws the levels it was given, not four it knows", async () => {
    // A core that adds a fifth level must not need a frontend change, and one
    // that renames Medium must not leave the menu claiming the old name.
    const custom: PermissionList = {
      permission: "cautious",
      permissions: [
        level({ name: "cautious", label: "Cautious" }),
        level({ name: "wide", label: "Wide", runs_commands: true }),
      ],
    };
    const { container } = await renderPermission({ list: custom, value: "cautious" });
    assert.deepEqual(texts(container, ".permchoice-value"), ["Cautious"]);
    assert.equal(all(container, ".permchoice-step").length, 2);
  });

  test("an unread ladder renders nothing at all", async () => {
    // Not a disabled row, and not four greyed segments: naming a choice nobody
    // has been told the terms of is worse than not offering it, because the
    // user cannot tell a real "Medium" from a placeholder one.
    const { container } = await renderPermission({ list: null });
    assert.equal(one(container, ".permchoice"), null);
  });
});

// --- choosing a level ----------------------------------------------------
describe("choosing a permission level", () => {
  test("picking one reports it, with nothing to open and nothing to close", async () => {
    // The absence is the claim as much as the press is: a press that then had to
    // be dismissed would mean the ladder was still a menu.
    const { container, changed } = await renderPermission({ value: "medium" });
    assert.equal(one(container, ".permchoice-trigger"), null, "the ladder is behind a press");
    assert.equal(one(container, ".permchoice-menu"), null, "the ladder is a popover");

    await click(rungs(container)[3]);
    assert.deepEqual(changed, ["full"]);
  });

  test("re-picking the level already in force does nothing", async () => {
    const { container, changed } = await renderPermission({ value: "medium" });
    await click(rungs(container)[1]);
    assert.deepEqual(changed, [], "the core was asked to set what it already had");
  });

  test("it is refused while a turn is in flight", async () => {
    // Switching mid-turn would change the rules underneath a half-built answer,
    // and the reply is keyed to a model that was allowed something else.
    //
    // Asserted on every rung rather than on a trigger, because there is no
    // trigger: without one the state is the rows' to carry, and a rung that
    // forgot it would be the one control in the panel still live mid-turn.
    const { container } = await renderPermission({ busy: true });
    const buttons = rungs(container) as HTMLButtonElement[];
    assert.equal(buttons.length, 4);
    assert.ok(
      buttons.every((rung) => rung.disabled),
      "a permission level could be changed while a turn was running",
    );
  });
});

// --- what a level actually permits ---------------------------------------
describe("the menu says what a level actually permits", () => {
  test("each rung states what stepping up to it adds", async () => {
    // The labels are names. The difference between Medium and High -- whether
    // the agent may execute code -- is the entire decision, and it has to be on
    // screen where the decision is made.
    //
    // **On the higher row, not the lower one.** The sentence is written by
    // `permissionGain(here, above)` -- what the step *up from here* buys -- and
    // it used to be rendered under `here`, which is what a one-option-at-a-time
    // menu allows. Read as a ladder it is a contradiction: measured on the real
    // panel, Medium said "Edit files. Shell commands are refused." with "Can run
    // shell commands" on the line directly beneath it. Moving the sentence to the
    // row above makes it true of that row and turns the list into a scale -- each
    // rung says what it adds over the one below, and the floor says nothing
    // because there is nothing below it.
    const { container } = await renderPermission();
    const items = rungs(container);
    const gainOf = (i: number) =>
      texts(items[i], ".permchoice-gain").join("") || null;
    assert.deepEqual(
      items.map((_, i) => gainOf(i)),
      [
        null,
        null,
        "Can run shell commands",
        "Runs on this computer, outside the sandbox",
      ],
    );

    // And each one is a true statement about the rung it is written on: High
    // runs commands, Medium does not.
    assert.equal(items[2].getAttribute("aria-checked"), "false");
    assert.match(texts(items[1], ".permchoice-desc").join(""), /refused/);
  });

  test("the rung below Full names the machine, not the allow-list", () => {
    // The single most consequential sentence in the panel, asserted on its own
    // so it cannot be bought by a change somewhere else in the row.
    //
    // It is checked as a pair because either one alone passes by accident: a
    // menu that dropped every gain line would satisfy "is the host sentence
    // there", and one that put it second would satisfy "is the host sentence
    // absent from the headline".
    const high = level({ name: "high", runs_commands: true });
    const full = level({
      name: "full",
      runs_commands: true,
      skips_confirmation: true,
      runs_any_command: true,
      runs_on_host: true,
    });
    assert.equal(
      permissionGain(high, full),
      "Runs on this computer, outside the sandbox",
    );
    assert.equal(high.runs_on_host, false, "the level below must stay sandboxed");
  });

  test("Full is marked with every power it adds, the machine first", async () => {
    // Spelled out rather than implied: a user who cannot see these has no way
    // to make an informed choice about handing an agent unasked access to
    // commands the project never allow-listed.
    //
    // Three markers, not one, because they are three decisions. Being willing to
    // have the agent run `ls` is not the same decision as being willing to have
    // it run anything, unasked -- and neither is the same decision as letting it
    // run outside the sandbox on the machine it was asked to help with. The
    // host marker leads, because that is the one that is about the user's
    // files rather than the project's.
    const { container } = await renderPermission();
    const warned = rungs(container).filter((item) =>
      item.querySelector(".permchoice-warn"),
    );
    assert.equal(warned.length, 1);
    assert.match(warned[0].textContent ?? "", /Full/);
    const marks = texts(warned[0], ".permchoice-warn");
    assert.deepEqual(marks, ["on this computer", "any command", "no prompts"]);
  });

  test("the ladder is a radio group, so the current rung is announced as one", async () => {
    // The framing that replaced the menu. A listbox says "pick one of four"; a
    // ladder with one rung in force is one of four *chosen*, and only the second
    // tells a screen reader which rung the agent is actually on.
    const { container } = await renderPermission({ value: "medium" });
    const group = one(container, ".permchoice-list")!;
    assert.equal(group.getAttribute("role"), "radiogroup");
    assert.equal(group.getAttribute("aria-label"), "Permission");

    const buttons = rungs(container);
    assert.deepEqual(
      buttons.map((rung) => rung.getAttribute("role")),
      ["radio", "radio", "radio", "radio"],
    );
    assert.deepEqual(
      buttons.map((rung) => rung.getAttribute("aria-checked")),
      ["false", "true", "false", "false"],
      "the rung in force is not the one marked selected",
    );
    // And nothing is announced as a listbox, because it is not one: the option
    // role belongs to the popover, and a `aria-selected` here would be an
    // attribute a radio ignores.
    assert.equal(one(container, "[role='listbox']"), null);
    assert.deepEqual(
      buttons.map((rung) => rung.getAttribute("aria-selected")),
      [null, null, null, null],
    );
  });
});

// --- the thinking menu ---------------------------------------------------
describe("the thinking menu", () => {
  test("a model that cannot reason gets no menu", async () => {
    const { container } = await renderThinking({
      info: reasoning({ supported: false, efforts: [], default_effort: "" }),
    });
    assert.equal(
      all(container, ".permchoice").length,
      0,
      "offered a dial that cannot change anything",
    );
  });

  test("a model that reasons with no choice to make gets no menu", async () => {
    // Supported, but the provider named no efforts. The support flag alone is
    // not enough to justify the control.
    const { container } = await renderThinking({
      info: reasoning({ efforts: [] }),
    });
    assert.equal(
      all(container, ".permchoice").length,
      0,
      "an empty menu leaked into the settings panel",
    );
  });

  test("it stays out of the way while the core has not answered", async () => {
    // Null means "not read", which is not the same as "not supported": the
    // first keeps the control where it is, the second removes it.
    const { container } = await renderThinking({ info: null });
    assert.equal(all(container, ".permchoice").length, 0);
  });

  test("it offers the model's own default first, then its efforts in order", async () => {
    const { container } = await renderThinking();
    await openMenu(container);
    assert.deepEqual(texts(container, ".permchoice-item .permchoice-name"), [
      "Default (max)",
      "max",
      "xhigh",
      "high",
      "medium",
      "low",
    ]);
  });

  test("a model with no named default says so rather than inventing one", async () => {
    const { container } = await renderThinking({
      info: reasoning({ default_effort: "" }),
    });
    await openMenu(container);
    assert.equal(texts(container, ".permchoice-item .permchoice-name")[0], "Default");
  });

  test("the efforts the provider reported are the efforts offered", async () => {
    // The order is the provider's, and the names are the provider's. Hardcoding
    // either would drift the moment a model changed.
    const { container } = await renderThinking({
      info: reasoning({ efforts: ["off", "on"], default_effort: "on" }),
    });
    await openMenu(container);
    assert.deepEqual(texts(container, ".permchoice-item .permchoice-name"), [
      "Default (on)",
      "off",
      "on",
    ]);
  });

  test("it shows the effort the core reported, not the one last clicked", async () => {
    // The menu describing a state that does not exist is the one failure mode
    // this whole file exists to prevent.
    const { container } = await renderThinking({
      info: reasoning({ effort: "medium" }),
    });
    assert.deepEqual(texts(container, ".permchoice-value"), ["medium"]);
  });

  test("choosing an effort asks the core for it", async () => {
    const { container, changed } = await renderThinking();
    await click(one(container, ".permchoice-trigger")!);
    await click(all(container, ".permchoice-item")[2]);
    assert.deepEqual(changed, ["xhigh"]);
  });

  test("choosing the default asks for the absence of a choice", async () => {
    // The default option's `value` is the empty string, and it has to stay
    // distinct from the efforts: sending "max" instead would pin the model to
    // its default forever, which is the opposite of offering the model a
    // choice. The core builds no `reasoning` field at all for an empty effort.
    const { container, changed } = await renderThinking({
      info: reasoning({ effort: "low" }),
    });
    await click(one(container, ".permchoice-trigger")!);
    await click(all(container, ".permchoice-item")[0]);
    assert.deepEqual(
      changed,
      [""],
      "the default must arrive as an empty effort, not as the effort in the label",
    );
  });

  test("no effort carries a description, because the core sends none", async () => {
    // The effort names are the provider's and they change with its models, so a
    // sentence written here about "medium" would be a guess about a dial this
    // window cannot see. Only the default can be explained, and it can.
    const { container } = await renderThinking();
    await click(one(container, ".permchoice-trigger")!);
    const items = all(container, ".permchoice-item");
    assert.equal(
      texts(items[0], ".permchoice-desc").length,
      1,
      "the default should say what it does",
    );
    for (const item of items.slice(1)) {
      assert.equal(
        texts(item, ".permchoice-desc").length,
        0,
        "an effort was described in words the core never sent",
      );
    }
  });

  test("it is refused while a turn is in flight, because effort applies to the next one", async () => {
    const { container } = await renderThinking({ busy: true });
    const trigger = one(container, ".permchoice-trigger") as HTMLButtonElement;
    assert.equal(trigger.disabled, true);
  });
});

// --- one control, two framings -------------------------------------------
describe("both controls come from the same parts", () => {
  test("neither is a native select, because a system dropdown does not match this window", async () => {
    // The Thinking control used to be a real `<select>`, which on Windows is a
    // light box with a system font and a system arrow on a black panel -- the
    // one control in this window that visibly came from somewhere else.
    for (const container of [
      (await renderPermission()).container,
      (await renderThinking()).container,
    ]) {
      assert.equal(
        all(container, "select").length,
        0,
        "a platform control is still in the settings panel",
      );
    }
  });

  test("both are labelled, and both name what is in force", async () => {
    const permissionView = await renderPermission({ value: "high" });
    assert.deepEqual(texts(permissionView.container, ".permchoice-label"), [
      "Permission",
    ]);
    assert.deepEqual(texts(permissionView.container, ".permchoice-value"), ["High"]);

    const thinkingView = await renderThinking();
    assert.deepEqual(texts(thinkingView.container, ".permchoice-label"), [
      "Thinking",
    ]);
    assert.deepEqual(texts(thinkingView.container, ".permchoice-value"), ["high"]);
  });

  test("only the popover announces itself as one", async () => {
    // **The difference the split turns on.** A trigger that opens a list is a
    // listbox, and a button that says `aria-haspopup` when nothing opens is a
    // control lying about itself. So the thinking dial announces the list it
    // has, and the ladder announces nothing -- it has no trigger at all.
    const thinking = (await renderThinking()).container;
    const trigger = one(thinking, ".permchoice-trigger")!;
    assert.equal(trigger.getAttribute("aria-haspopup"), "listbox");
    assert.equal(trigger.getAttribute("aria-expanded"), "false");
    await click(trigger);
    assert.equal(trigger.getAttribute("aria-expanded"), "true");
    assert.ok(
      one(thinking, ".permchoice-menu[role='listbox']"),
      "the list is not announced as a listbox",
    );

    const ladder = (await renderPermission()).container;
    assert.equal(one(ladder, ".permchoice-trigger"), null);
    assert.equal(one(ladder, "[aria-haspopup]"), null, "something promises a popover");
    assert.equal(one(ladder, "[role='listbox']"), null);
  });

  test("escape closes a popover without reaching the panel behind it", async () => {
    // The window treats Escape as "close whatever is open", and the settings
    // panel is open behind this menu. One Escape should close the menu; a user
    // who meant to leave the panel has to press it twice, which is the price of
    // not closing both at once.
    //
    // The ladder has no such duty -- there is nothing open to close -- and the
    // other half of that is in `App.test.tsx`: the one Escape there goes past
    // the panel's contents and puts the sidebar away.
    const { container } = await renderThinking();
    await click(one(container, ".permchoice-trigger")!);
    domWindow.document.dispatchEvent(
      new domWindow.KeyboardEvent("keydown", { key: "Escape", bubbles: true }),
    );
    await new Promise((resolve) => setTimeout(resolve, 0));
    assert.equal(one(container, ".permchoice-menu"), null);
  });
});

// --- where the menu opens -------------------------------------------------
describe("the menu opens toward the room it has", () => {
  /** A rectangle with only the two edges that matter for placement. */
  const rect = (top: number, bottom: number): MenuBounds => ({ top, bottom });

  test("a trigger near the top of the panel opens down, not up", () => {
    // The bug this replaced. The menu was anchored above its trigger while the
    // trigger was the panel's *first* control, so it rendered off the top of
    // the window: measured at y=-210 in an 800px window, with the whole
    // permission ladder outside the visible area.
    assert.deepEqual(
      measureMenu(rect(120, 150), rect(24, 776)),
      { dir: "down", maxHeight: 776 - 150 - 6 },
    );
  });

  test("a trigger near the bottom opens up", () => {
    // The half of the rule that keeps the composer's original behaviour: a
    // control low in a scrolling panel has no room below it.
    assert.equal(measureMenu(rect(700, 730), rect(24, 776)).dir, "up");
  });

  test("the cap is the room that was measured, less the gap", () => {
    // Not the height of the menu, which is not known until it is laid out, and
    // not a fixed number, which would be wrong in every window but one. What is
    // known at open time is the space available, and a menu taller than that is
    // a menu whose last option cannot be clicked.
    assert.equal(measureMenu(rect(10, 40), rect(0, 306)).maxHeight, 260);
  });

  test("and it is floored, because a zero-height menu cannot be used", () => {
    // A trigger hard against the top edge of its bounds still has to open
    // somewhere. The floor lets it exceed the measured room by a little and
    // scroll, which is recoverable; zero is not.
    const cramped = measureMenu(rect(4, 34), rect(0, 40));
    assert.equal(cramped.dir, "down");
    assert.equal(cramped.maxHeight, 120);
  });

  test("the open menu carries the direction it decided on", async () => {
    // `data-dir` is the whole contract with the stylesheet: the two anchors are
    // declared on it and the base rule declares neither, so a menu that never
    // got a direction would render unpositioned rather than silently opening
    // the wrong way. jsdom reports every rectangle as zero, so this exercises
    // the degenerate branch -- and it still has to name a direction.
    //
    // The thinking dial, because it is the only control here with a menu: the
    // permission ladder has no direction to decide, which is the whole point of
    // its being expanded.
    const { container } = await renderThinking();
    const menu = await openMenu(container);
    assert.ok(menu, "the menu did not open");
    assert.ok(
      ["up", "down"].includes(menu.getAttribute("data-dir") ?? ""),
      `unexpected direction: ${menu.getAttribute("data-dir")}`,
    );
    assert.match(menu.getAttribute("style") ?? "", /max-height/);
  });
});