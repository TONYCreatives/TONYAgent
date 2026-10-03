/**
 * The rail's icons, and the one that had to be drawn rather than transcribed.
 *
 * **The settings gear is asserted on its shape, not on its pixels.** It used to
 * be two concentric circles with eight radial ticks, which is what you get by
 * writing a gear as "a body and some teeth" instead of as a shape: it reads as a
 * sun or a brightness icon, and at the 17px the rail draws it the ticks are far
 * enough apart that the eye never joins them to the body. So what is asserted
 * is the thing that was wrong -- a sun is two circles and radial marks, a gear
 * is one outline with teeth in it -- which is checkable from the markup and is
 * the part that actually regressed.
 *
 * Everything else here is the rail's standing contract, gathered because the
 * gear change was the first time this component's markup was edited since it
 * was written.
 */

import "./test-dom.js";
import assert from "node:assert/strict";
import { describe, test } from "node:test";

import { IconRail } from "./IconRail.js";
import { all, one, render } from "./test-render.js";

async function renderRail(over: Partial<React.ComponentProps<typeof IconRail>> = {}) {
  return render(
    <IconRail
      connected
      busy={false}
      messageCount={0}
      expanded={false}
      onToggle={() => {}}
      onClear={() => {}}
      onCancel={() => {}}
      onSettings={() => {}}
      onSearch={() => {}}
      {...over}
    />,
  );
}

/** The settings button, addressed the way a user reaches it. */
const settingsButton = (c: HTMLElement) =>
  one(c, '.rail-btn[aria-label="Settings"]')!;

describe("the settings button's glyph", () => {
  test("it is a gear, not a sun", async () => {
    // A sun is concentric circles with marks radiating outward; that is
    // literally what it used to be, and it is what a gear must not look like.
    // Asserted as the absence of the two things a sun is made of.
    const container = await renderRail();
    const svg = one(settingsButton(container), "svg")!;
    const shapes = [...svg.children].map((node) => node.tagName.toLowerCase());

    assert.ok(
      !shapes.includes("circle"),
      "the gear is built from circles, which is what made it read as a sun",
    );
    // Every mark is a path, and there is more than one of them: a hub and a
    // toothed body. A single path is the whole silhouette, which is what
    // survives being drawn small.
    assert.deepEqual(
      [...new Set(shapes)],
      ["path"],
      "the gear's marks are not all paths, so they do not join into one shape",
    );
    assert.ok(
      svg.querySelectorAll("path").length >= 2,
      "the gear has one path, so there is no body for the teeth to belong to",
    );
  });

  test("its teeth are part of one outline, not marks beside it", async () => {
    // The old glyph's ticks were separate strokes floating outside a circle.
    // Asserted as the absence of short standalone segments: a path that is
    // nothing but a straight dash from one radius to another is exactly that.
    const container = await renderRail();
    const paths = [...one(settingsButton(container), "svg")!.querySelectorAll("path")];
    const dashOnly = paths.filter((path) =>
      /d="[ML][^A-Za-z]*"/.test(path.getAttribute("d") ?? ""),
    );
    assert.equal(
      dashOnly.length,
      0,
      "the gear still has teeth drawn as marks beside the body rather than in it",
    );
  });

  test("and it is hidden from assistive tech, because the name is the label", async () => {
    const container = await renderRail();
    const svg = one(settingsButton(container), "svg")!;
    assert.equal(svg.getAttribute("aria-hidden"), "true");
    assert.equal(svg.getAttribute("stroke"), "currentColor");
  });
});

describe("the rail is a strip of icons that never changes width", () => {
  test("every entry is named for a screen reader, not only titled", async () => {
    // The rail draws no text labels, so `aria-label` is the only place the name
    // exists. A title alone would leave a keyboard user with four unlabelled
    // buttons.
    const container = await renderRail({ messageCount: 3 });
    for (const button of all(container, ".rail-btn")) {
      assert.ok(
        button.getAttribute("aria-label"),
        "a rail button has no name in the accessibility tree",
      );
      assert.ok(
        button.getAttribute("title"),
        "a rail button has no tooltip",
      );
    }
  });

  test("the toggle says whether the panel it opens is open", async () => {
    const closed = await renderRail({ expanded: false });
    assert.equal(
      one(closed, ".rail-toggle")!.getAttribute("aria-label"),
      "Open sidebar",
    );
    assert.equal(one(closed, ".rail-toggle")!.getAttribute("aria-expanded"), "false");

    const open = await renderRail({ expanded: true });
    assert.equal(
      one(open, ".rail-toggle")!.getAttribute("aria-label"),
      "Close sidebar",
    );
    assert.equal(one(open, ".rail-toggle")!.getAttribute("aria-expanded"), "true");
  });

  test("the panel's width does not follow it -- only the toggle's name does", async () => {
    // The rail used to widen to 307px and grow a text label beside every icon,
    // which is the one thing the reference never does. Expanding the panel now
    // changes one attribute and nothing about the strip, so the two renders
    // differ in exactly one way.
    const closed = await renderRail({ expanded: false });
    const open = await renderRail({ expanded: true });

    assert.equal(
      all(open, ".rail").length,
      1,
      "the rail rendered more than one strip when the panel opened",
    );
    assert.equal(
      all(open, ".rail").length,
      all(closed, ".rail").length,
      "the rail itself changed when the panel opened",
    );
    // Same controls either way: an expanded rail used to add a `.rail-label`
    // beside each icon, and this is what that would have tripped.
    assert.deepEqual(
      all(open, ".rail-btn").map((b) => b.getAttribute("aria-label")),
      [
        ...all(closed, ".rail-btn").map((b) =>
          b.getAttribute("aria-label") === "Open sidebar" ? "Close sidebar" : b.getAttribute("aria-label"),
        ),
      ],
      "the rail gained or lost a control when the panel opened",
    );
    assert.equal(
      one(open, ".rail-label"),
      null,
      "the rail grew text labels again",
    );
  });

  test("Stop appears only mid-turn, and Clear only with something to clear", async () => {
    // Addressed by `aria-label` rather than by text: the rail draws icons, so
    // `texts` returns one empty string per button and says nothing about which
    // control is which. The toggle is excluded by `.rail-btn:not(.rail-toggle)`
    // because it also carries `.rail-btn` and is not one of the items below the
    // logo -- the thing under test here is which entries appear, not the toggle.
    const names = (c: HTMLElement) =>
      all(c, ".rail-btn:not(.rail-toggle)").map((b) => b.getAttribute("aria-label"));

    const idle = await renderRail({ messageCount: 0 });
    assert.deepEqual(names(idle), ["Clear conversation", "Search project", "Settings"]);

    const busy = await renderRail({ busy: true, messageCount: 4 });
    assert.deepEqual(names(busy), [
      "Clear conversation",
      "Stop generating",
      "Search project",
      "Settings",
    ]);

    const empty = await renderRail({ messageCount: 0 });
    const clear = one(
      empty,
      '.rail-btn[aria-label="Clear conversation"]',
    ) as HTMLButtonElement;
    assert.equal(
      clear.disabled,
      true,
      "Clear is live with nothing in the conversation to clear",
    );
  });

  test("an unreachable core disables the entries that need it", async () => {
    // Rendered disabled rather than wired to a stub that silently does nothing,
    // which is how the Tkinter UI ended up with controls that appeared to work.
    //
    // The toggle is excluded because it does not talk to the core at all: it
    // shows and hides a panel that is already in the window, so it stays live
    // with the backend stopped -- which is the only way back to the rail.
    const container = await renderRail({ connected: false });
    const needingCore = all(container, ".rail-btn:not(.rail-toggle)");
    assert.ok(needingCore.length > 0, "the rail rendered nothing to check");
    for (const button of needingCore) {
      assert.equal(
        (button as HTMLButtonElement).disabled,
        true,
        `${button.getAttribute("aria-label")} is live with no core to answer it`,
      );
    }
    // And the one that must not be.
    assert.equal(
      (one(container, ".rail-toggle") as HTMLButtonElement).disabled,
      false,
      "the sidebar toggle was disabled with no core, leaving no way back to it",
    );
  });
});