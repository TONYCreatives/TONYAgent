/**
 * The rail's icons, and the one that had to be drawn rather than transcribed.
 *
 * **The settings gear is asserted on its construction, not on its pixels.** It
 * has been wrong twice. It began as two concentric circles with eight radial
 * ticks -- which is what you get by writing a gear as "a body and some teeth"
 * instead of as a shape, and it reads as a sun. It was then redrawn as one
 * continuous *outline* around the teeth, which helped and was not enough: at the
 * 17px the rail draws it, a thin ring around a thin hub ring is still two rings,
 * and it still read as brightness rather than as settings.
 *
 * So it is filled now, which is what Windows itself does for this control, and
 * what is asserted is the thing that makes it a gear rather than a sun: one
 * path, filled rather than stroked, with the hub cut out of it rather than
 * drawn on top. All three are checkable from the markup and all three are what
 * regressed each time.
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
      onCancel={() => {}}
      onSettings={() => {}}
      onSearch={() => {}}
      dashboardOpen={false}
      onDashboard={() => {}}
      petOpen={false}
      onPet={() => {}}
      {...over}
    />,
  );
}

/** The settings button, addressed the way a user reaches it. */
const settingsButton = (c: HTMLElement) =>
  one(c, '.rail-btn[aria-label="Settings"]')!;

describe("the settings button's glyph", () => {
  test("it is one filled silhouette, not a ring with marks around it", async () => {
    // A sun is concentric circles with marks radiating outward; a ring is a
    // thin outline around thin teeth. This is neither: it is one closed shape
    // with the teeth as part of its edge.
    const container = await renderRail();
    const svg = one(settingsButton(container), "svg")!;
    const shapes = [...svg.children].map((node) => node.tagName.toLowerCase());

    assert.deepEqual(shapes, ["path"], "the gear is drawn as more than one mark");
    assert.ok(
      !shapes.includes("circle"),
      "the gear is built from circles, which is what made it read as a sun",
    );
    assert.equal(svg.getAttribute("fill"), "currentColor");
    assert.equal(svg.getAttribute("stroke"), "none");
  });

  test("the hub is a hole in it, not a circle drawn on top", async () => {
    // `evenodd` and a second subpath. Under the default rule a second subpath
    // wound the same way would *fill*, and the gear would come out as a solid
    // blob -- which reads as a flower rather than as a cog.
    const container = await renderRail();
    const svg = one(settingsButton(container), "svg")!;
    const d = one(settingsButton(container), "svg path")!.getAttribute("d") ?? "";

    assert.equal(svg.getAttribute("fill-rule"), "evenodd");
    assert.ok(
      (d.match(/[Mm]/g) ?? []).length >= 2,
      "the path has one subpath, so there is nothing for the hub to be cut out of",
    );
  });

  test("and it is hidden from assistive tech, because the name is the label", async () => {
    const container = await renderRail();
    const svg = one(settingsButton(container), "svg")!;
    assert.equal(svg.getAttribute("aria-hidden"), "true");
    assert.equal(svg.getAttribute("focusable"), "false");
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

  test("the rail shows which destination you are on, not just what is clickable", async () => {
    // `.rail-btn.is-active` is the rail's only lit state, and until this it was
    // reached by exactly one thing: the Stop button, while a turn runs. So the
    // rail could say "something is happening" and nothing else -- opening the
    // conversation panel, which is the most common thing anyone does here, lit
    // no lamp at all.
    //
    // The toggle is a destination like the others even though its control is
    // different, so it carries the same class. Asserted on the toggle rather
    // than counted, because the busy state legitimately lights a second item and
    // a count would call that a bug.
    const closed = await renderRail({ expanded: false });
    assert.ok(
      !one(closed, ".rail-toggle")!.className.includes("is-active"),
      "the closed panel's toggle is lit",
    );

    const open = await renderRail({ expanded: true });
    assert.ok(
      one(open, ".rail-toggle")!.className.includes("is-active"),
      "the open panel's toggle is not lit, so the rail does not say where you are",
    );
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

  test("Stop appears only mid-turn, and nothing else is conditional", async () => {
    // Addressed by `aria-label` rather than by text: the rail draws icons, so
    // `texts` returns one empty string per button and says nothing about which
    // control is which. The toggle is excluded by `.rail-btn:not(.rail-toggle)`
    // because it also carries `.rail-btn` and is not one of the items below it --
    // the thing under test here is which entries appear, not the toggle.
    //
    // Clear is gone from this list on purpose: it was a trash glyph between the
    // toggle and Search, and clearing belongs beside the conversation list rather
    // than in the window's own strip. The sidebar's foot carries it.
    const names = (c: HTMLElement) =>
      all(c, ".rail-btn:not(.rail-toggle)").map((b) => b.getAttribute("aria-label"));

    const idle = await renderRail({ messageCount: 0 });
    assert.deepEqual(names(idle), [
      "Search project",
      "Usage dashboard",
      "Show desktop pet",
      "Settings",
    ]);

    const busy = await renderRail({ busy: true, messageCount: 4 });
    assert.deepEqual(names(busy), [
      "Stop generating",
      "Search project",
      "Usage dashboard",
      "Show desktop pet",
      "Settings",
    ]);

    // The pet is a toggle, so it says which way it goes rather than naming the
    // thing twice: with the card up, the entry that put it there is the entry
    // that takes it away.
    const showing = await renderRail({ petOpen: true });
    assert.ok(
      names(showing).includes("Hide desktop pet"),
      `the pet entry does not say what pressing it does; got ${JSON.stringify(names(showing))}`,
    );
  });

  test("an unreachable core disables the entries that need it", async () => {
    // Rendered disabled rather than wired to a stub that silently does nothing,
    // which is how the Tkinter UI ended up with controls that appeared to work.
    //
    // The toggle is excluded because it does not talk to the core at all: it
    // shows and hides a panel that is already in the window, so it stays live
    // with the backend stopped -- which is the only way back to the rail.
    // The pet is the second exception, added later and deliberately. It opens a
    // *window*, which the shell does without a core and without asking it
    // anything; a card that says "done" beside a stopped sandbox is the truth,
    // and a disabled control that could do its job is the fault this whole test
    // exists to catch. So it is excluded here and asserted live below.
    const container = await renderRail({ connected: false });
    const needingCore = all(container, '.rail-btn:not(.rail-toggle):not([aria-label$="desktop pet"])');
    assert.ok(needingCore.length > 0, "the rail rendered nothing to check");
    for (const button of needingCore) {
      assert.equal(
        (button as HTMLButtonElement).disabled,
        true,
        `${button.getAttribute("aria-label")} is live with no core to answer it`,
      );
    }
    assert.equal(
      (one(container, '.rail-btn[aria-label="Show desktop pet"]') as HTMLButtonElement)
        .disabled,
      false,
      "the pet needs no core to open a window",
    );
    // And the one that must not be.
    assert.equal(
      (one(container, ".rail-toggle") as HTMLButtonElement).disabled,
      false,
      "the sidebar toggle was disabled with no core, leaving no way back to it",
    );
  });
});

describe("the rail draws no mark of its own", () => {
  test("the app's glyph is in the title bar and nowhere in the strip", async () => {
    // The rail's head carried the app's glyph in a `--raised` box -- the text
    // "TA" once, then the drawing `icon.svg` ships. The mark moved to the title
    // bar's corner and this copy did not leave with it, so the window drew the
    // same drawing twice: 22px in the corner and 32px here, 64px apart, which is
    // what made the rail's one read as a second logo rather than as the app's.
    //
    // Asserted as an *absence*, like the two in `MessageList.test.tsx` and
    // `AppMark.test.tsx`. A test that checked the rail drew the right glyph
    // would pass with the glyph in the wrong place, and the wrong place is the
    // whole failure here.
    const container = await renderRail();

    assert.equal(
      all(container, ".rail-logo").length,
      0,
      "the rail is drawing the app's mark again",
    );
    // And not in some other box either. Every glyph the rail does draw is a
    // `path` -- the toggle, search and stop are stroked outlines and the gear is
    // one filled silhouette -- so a `rect` inside the strip can only be the
    // mark's two strokes.
    assert.equal(
      all(container, ".rail svg rect").length,
      0,
      "the mark's rects are inside the rail, so the glyph came back in a new box",
    );
    // The head is the toggle: nothing above it but the strip's own padding.
    const strip = one(container, ".rail")!;
    assert.equal(
      strip.firstElementChild?.className.split(" ")[0],
      "rail-btn",
      "something is above the rail's first control again",
    );
  });
});