/**
 * The permission bar, rendered in jsdom.
 *
 * The bar's whole claim is that it is a control over something real, so the
 * tests here are mostly about it not lying: that it draws the levels the core
 * sent rather than four hardcoded names, that it says which rung is in force,
 * and that the one rung which acts without asking says so where it can be seen.
 */

import "./test-dom.js";
import assert from "node:assert/strict";
import { describe, test } from "node:test";
import { dom } from "./test-dom.js";

import {
  PermissionBar,
  type PermissionInfo,
  type PermissionList,
} from "./PermissionBar.js";
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

async function renderBar(over: Partial<React.ComponentProps<typeof PermissionBar>> = {}) {
  const changed: string[] = [];
  const container = await render(
    <PermissionBar
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

const steps = (c: HTMLElement) =>
  all(c, ".permbar-step").map((e) => e.classList.contains("is-on"));

describe("the permission bar draws the ladder the core sent", () => {
  test("one segment per level, filled up to and including the current one", async () => {
    // A ladder, not four independent choices. "Filled up to here" is the claim
    // that Medium sits between Low and High; four separate buttons would say
    // "pick one", which is a different and wrong thing.
    const { container } = await renderBar({ value: "medium" });
    assert.equal(all(container, ".permbar-step").length, 4);
    assert.deepEqual(steps(container), [true, true, false, false]);
  });

  test("the current level is named, not just drawn", async () => {
    const { container } = await renderBar({ value: "high" });
    assert.deepEqual(texts(container, ".permbar-value"), ["High"]);
    assert.deepEqual(steps(container), [true, true, true, false]);
  });

  test("and it draws the levels it was given, not four it knows", async () => {
    // A core that adds a fifth level must not need a frontend change, and one
    // that renames Medium must not leave the bar claiming the old name.
    const custom: PermissionList = {
      permission: "cautious",
      permissions: [
        level({ name: "cautious", label: "Cautious" }),
        level({ name: "wide", label: "Wide", runs_commands: true }),
      ],
    };
    const { container } = await renderBar({ list: custom, value: "cautious" });
    assert.deepEqual(texts(container, ".permbar-value"), ["Cautious"]);
    assert.equal(all(container, ".permbar-step").length, 2);
  });

  test("an unread ladder draws nothing at all", async () => {
    // Not a disabled bar, and not four greyed segments: naming a choice nobody
    // has been told the terms of is worse than not offering it, because the
    // user cannot tell a real "Medium" from a placeholder one.
    const { container } = await renderBar({ list: null });
    assert.equal(one(container, ".permbar"), null);
  });
});

describe("choosing a level", () => {
  test("picking one reports it and closes the menu", async () => {
    const { container, changed } = await renderBar({ value: "medium" });
    await click(one(container, ".permbar-trigger")!);
    assert.ok(one(container, ".permmenu"), "the menu did not open");

    await click(all(container, ".permmenu-item")[3]);
    assert.deepEqual(changed, ["full"]);
    assert.equal(one(container, ".permmenu"), null, "the menu stayed open");
  });

  test("re-picking the level already in force does nothing", async () => {
    const { container, changed } = await renderBar({ value: "medium" });
    await click(one(container, ".permbar-trigger")!);
    await click(all(container, ".permmenu-item")[1]);
    assert.deepEqual(changed, [], "the core was asked to set what it already had");
  });

  test("it is refused while a turn is in flight", async () => {
    // Switching mid-turn would change the rules underneath a half-built answer,
    // and the reply is keyed to a model that was allowed something else.
    const { container } = await renderBar({ busy: true });
    const trigger = one(container, ".permbar-trigger") as HTMLButtonElement;
    assert.equal(trigger.disabled, true);
  });
});

describe("the menu says what a level actually permits", () => {
  test("each rung states what the next one adds", async () => {
    // The labels are names. The difference between Medium and High -- whether
    // the agent may execute code -- is the entire decision, and it has to be on
    // screen where the decision is made.
    //
    // Read per item rather than across the menu, because Low and Full gain
    // nothing from a neighbour and so render no line at all: the ends of the
    // ladder have nothing above or below them to compare against.
    const { container } = await renderBar();
    await click(one(container, ".permbar-trigger")!);
    const items = all(container, ".permmenu-item");
    const gainOf = (i: number) =>
      texts(items[i], ".permmenu-gain").join("") || null;
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
    const { container } = await renderBar();
    await click(one(container, ".permbar-trigger")!);
    const warned = all(container, ".permmenu-item").filter((item) =>
      item.querySelector(".permmenu-warn"),
    );
    assert.equal(warned.length, 1);
    assert.match(warned[0].textContent ?? "", /Full/);
    const marks = texts(warned[0], ".permmenu-warn");
    assert.deepEqual(marks, ["any command", "no prompts"]);
  });

  test("the menu opens above the bar, not over the composer", async () => {
    // Downward would cover the composer's own controls -- the one surface the
    // user is reaching for -- and hide the transcript the level applies to.
    const { container } = await renderBar();
    await click(one(container, ".permbar-trigger")!);
    const menu = one(container, ".permmenu")!;
    assert.match(getComputedStyle(menu).bottom || "", /px|auto/);
    assert.equal(getComputedStyle(menu).top, "auto", "the menu is anchored to the top");
  });

  test("escape closes it without reaching the composer", async () => {
    // The composer treats Escape as "abandon what I am typing", so an Escape
    // that opened the menu must not also empty a half-written message.
    const { container } = await renderBar();
    await click(one(container, ".permbar-trigger")!);
    domWindow.document.dispatchEvent(
      new domWindow.KeyboardEvent("keydown", { key: "Escape", bubbles: true }),
    );
    await new Promise((resolve) => setTimeout(resolve, 0));
    assert.equal(one(container, ".permmenu"), null);
  });
});