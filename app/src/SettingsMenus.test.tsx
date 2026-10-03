/**
 * The permission and thinking menus, rendered in jsdom.
 *
 * Both controls' whole claim is that they change something real, so most of
 * these are about them not lying: that Permission draws the levels the core
 * sent rather than four hardcoded names, that it says which rung is in force,
 * that the one rung which acts without asking says so where it can be seen,
 * and that Thinking offers the provider's own efforts rather than a guess.
 *
 * **The two are tested through one file because they are one component.** They
 * share every part but the rows, so the tests that matter most -- that the
 * trigger names the value in force, that picking one asks the core, that
 * re-picking the current one does not, that Escape closes the menu without
 * closing the panel behind it -- are asserted once and would otherwise be
 * duplicated in a way that lets the two copies drift apart, which is exactly
 * what "one vocabulary" is supposed to prevent.
 */

import "./test-dom.js";
import assert from "node:assert/strict";
import { describe, test } from "node:test";
import { dom } from "./test-dom.js";

import {
  PermissionMenu,
  ThinkingMenu,
  measureMenu,
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
  test("picking one reports it and closes the menu", async () => {
    const { container, changed } = await renderPermission({ value: "medium" });
    await click(one(container, ".permchoice-trigger")!);
    assert.ok(one(container, ".permchoice-menu"), "the menu did not open");

    await click(all(container, ".permchoice-item")[3]);
    assert.deepEqual(changed, ["full"]);
    assert.equal(
      one(container, ".permchoice-menu"),
      null,
      "the menu stayed open",
    );
  });

  test("re-picking the level already in force does nothing", async () => {
    const { container, changed } = await renderPermission({ value: "medium" });
    await click(one(container, ".permchoice-trigger")!);
    await click(all(container, ".permchoice-item")[1]);
    assert.deepEqual(changed, [], "the core was asked to set what it already had");
  });

  test("it is refused while a turn is in flight", async () => {
    // Switching mid-turn would change the rules underneath a half-built answer,
    // and the reply is keyed to a model that was allowed something else.
    const { container } = await renderPermission({ busy: true });
    const trigger = one(container, ".permchoice-trigger") as HTMLButtonElement;
    assert.equal(trigger.disabled, true);
  });
});

// --- what a level actually permits ---------------------------------------
describe("the menu says what a level actually permits", () => {
  test("each rung states what the next one adds", async () => {
    // The labels are names. The difference between Medium and High -- whether
    // the agent may execute code -- is the entire decision, and it has to be on
    // screen where the decision is made.
    //
    // Read per item rather than across the menu, because Low and Full gain
    // nothing from a neighbour and so render no line at all: the ends of the
    // ladder have nothing above or below them to compare against.
    const { container } = await renderPermission();
    await click(one(container, ".permchoice-trigger")!);
    const items = all(container, ".permchoice-item");
    const gainOf = (i: number) =>
      texts(items[i], ".permchoice-gain").join("") || null;
    assert.deepEqual(
      items.map((_, i) => gainOf(i)),
      [
        null,
        "Can run shell commands",
        "Can run commands outside the allow-list",
        null,
      ],
    );
  });

  test("Full is marked with both of the powers it adds", async () => {
    // Spelled out rather than implied: a user who cannot see these has no way
    // to make an informed choice about handing an agent unasked access to
    // commands the project never allow-listed.
    //
    // Two markers, not one, because they are two decisions. Being willing to
    // have the agent run `ls` is not the same decision as being willing to have
    // it run anything, unasked.
    const { container } = await renderPermission();
    await click(one(container, ".permchoice-trigger")!);
    const warned = all(container, ".permchoice-item").filter((item) =>
      item.querySelector(".permchoice-warn"),
    );
    assert.equal(warned.length, 1);
    assert.match(warned[0].textContent ?? "", /Full/);
    const marks = texts(warned[0], ".permchoice-warn");
    assert.deepEqual(marks, ["any command", "no prompts"]);
  });

  test("the menu opens upward, out of the panel's bottom edge", async () => {
    // These rows sit near the bottom of a modal, so a menu opening downward
    // would render off the bottom of it.
    const { container } = await renderPermission();
    const menu = (await openMenu(container))!;
    assert.match(getComputedStyle(menu).bottom || "", /px|auto/);
    assert.equal(
      getComputedStyle(menu).top,
      "auto",
      "the menu is anchored to the top",
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

// --- one component, two controls -----------------------------------------
describe("both menus come from the same parts", () => {
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

  test("both announce themselves as menus", async () => {
    for (const container of [
      (await renderPermission()).container,
      (await renderThinking()).container,
    ]) {
      const trigger = one(container, ".permchoice-trigger")!;
      assert.equal(trigger.getAttribute("aria-haspopup"), "listbox");
      assert.equal(trigger.getAttribute("aria-expanded"), "false");
      await click(trigger);
      assert.equal(trigger.getAttribute("aria-expanded"), "true");
      assert.ok(
        one(container, ".permchoice-menu[role='listbox']"),
        "the list is not announced as a listbox",
      );
    }
  });

  test("escape closes the menu without reaching the panel behind it", async () => {
    // The window treats Escape as "close whatever is open", and the settings
    // panel is open behind this menu. One Escape should close the menu; a user
    // who meant to leave the panel has to press it twice, which is the price of
    // not closing both at once.
    const { container } = await renderPermission();
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
    const { container } = await renderPermission();
    const menu = await openMenu(container);
    assert.ok(menu, "the menu did not open");
    assert.ok(
      ["up", "down"].includes(menu.getAttribute("data-dir") ?? ""),
      `unexpected direction: ${menu.getAttribute("data-dir")}`,
    );
    assert.match(menu.getAttribute("style") ?? "", /max-height/);
  });
});