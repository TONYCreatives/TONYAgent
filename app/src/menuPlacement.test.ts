/**
 * Where a menu opens, without a layout engine.
 *
 * Every case here was reported from the running window first, and the reason
 * they are written against a pure function is that the failures were *not*
 * visible to any test the app had: a menu is positioned by CSS against its own
 * trigger, so a menu that hangs off the window edge looks exactly like a menu
 * that does not until somebody opens it there. jsdom has no layout at all -- it
 * reports every rectangle as zero -- so the only testable form of the rule is
 * arithmetic, which is what `placeMenu` is.
 *
 * The two numbers that matter are read off the measurement that found the bugs,
 * not invented: a 900px-wide window with a 320px picker anchored to a chip at
 * x=600 (the title bar's cluster), and a 640x480 window -- the app's minimum --
 * with a row menu opened from a click at y=417.
 */

import "./test-dom.js";
import assert from "node:assert/strict";
import { describe, test } from "node:test";

import {
  MENU_MIN_HEIGHT,
  placeFixedMenu,
  placeMenu,
  pointerBounds,
  viewportBounds,
} from "./menuPlacement.js";
import type { MenuBounds } from "./menuPlacement.js";

/** A rectangle, written the way a measurement reports one. */
const box = (
  left: number,
  top: number,
  right: number,
  bottom: number,
): MenuBounds => ({ top, bottom, left, right });

describe("a menu opens toward the room it has", () => {
  test("a trigger near the top of the window opens down, not up", () => {
    // The permission menu's own bug, kept: it was anchored above its trigger
    // while the trigger was the panel's *first* control, so it rendered off the
    // top of the window -- measured at y=-210 in an 800px window, with the
    // whole ladder outside the visible area.
    assert.deepEqual(
      placeMenu(box(40, 120, 200, 150), box(0, 24, 1024, 776)),
      { dir: "down", align: "start", maxHeight: 776 - 150 - 6 },
    );
  });

  test("a trigger near the bottom opens up", () => {
    // A control low in a scrolling panel has no room below it. This is the row
    // menu's bug: three items, 132px of menu, opened from a click at y=417 of a
    // 480-tall window, where Delete ended up 68px past the client rect.
    assert.equal(
      placeMenu(pointerBounds(243, 417), box(0, 0, 640, 480), { gap: 4 }).dir,
      "up",
    );
  });

  test("the cap is the room that was measured, less the gap", () => {
    // Not the height of the menu, which is not known until it is laid out, and
    // not a fixed number, which would be wrong in every window but one.
    assert.equal(
      placeMenu(box(40, 10, 200, 40), box(0, 0, 1024, 306)).maxHeight,
      260,
    );
  });

  test("and it is floored, because a zero-height menu cannot be used", () => {
    const cramped = placeMenu(box(4, 4, 200, 34), box(0, 0, 1024, 40));
    assert.equal(cramped.dir, "down");
    assert.equal(cramped.maxHeight, MENU_MIN_HEIGHT);
  });
});

describe("a menu hangs from whichever edge has room", () => {
  /** The model picker's own width, which is what the horizontal half is about. */
  const WIDTH = 320;

  test("a trigger with room to its right keeps the menu on its left edge", () => {
    // The ordinary case, and the one that must not change: a 360px chip in the
    // middle of a 900px window, with its 320px menu landing at 300..620 -- well
    // inside the client rect, and where every menu in the app opened before
    // there was a measurement. A rule that picked the *roomier* side instead of
    // the fitting one would move it left of the chip here, which is a change
    // nobody asked for.
    assert.equal(
      placeMenu(box(300, 40, 660, 64), box(0, 0, 900, 600), { width: WIDTH })
        .align,
      "start",
    );
  });

  test("a trigger against the right edge hangs the menu to its left", () => {
    // The report. The chip is in the title bar's right-hand cluster, at x=600 of
    // a 900px window -- so the menu ran from 600 to 920 and the last 20px of it
    // were outside the window. 300 + 320 > 900, so the left edge is not the one
    // to hang from; 700 - 320 >= 0, so the right edge is.
    const placed = placeMenu(box(600, 40, 700, 64), box(0, 0, 900, 600), {
      width: WIDTH,
    });
    assert.equal(placed.align, "end");
    assert.equal(placed.dir, "down");
  });

  test("a menu with no width of its own keeps the side it always had", () => {
    // The row menus: three labels and `min-width: 132px` is all the width there
    // is, and the component has no node to measure at the moment it needs the
    // answer. Taken as fitting, which keeps `start` -- and honest, because the
    // alternative is flipping a menu that was never in the way on a guess.
    assert.equal(
      placeMenu(box(600, 40, 700, 64), box(0, 0, 900, 600)).align,
      "start",
    );
  });

  test("neither side fitting still has to open somewhere", () => {
    // A menu wider than the room on *both* sides: 320px of menu into a 250px
    // window, where nothing can fit and the only question left is which way the
    // overflow is least bad. The roomier side wins, and it has to win on the
    // room either side of the anchor rather than on the anchor's own width --
    // 60..160 leaves 190 to the right of it and 160 to the left, which is
    // `start`; 180..240 leaves 70 and 240, which is `end`.
    assert.equal(
      placeMenu(box(60, 40, 160, 64), box(0, 0, 250, 600), { width: WIDTH })
        .align,
      "start",
    );
    assert.equal(
      placeMenu(box(180, 40, 240, 64), box(0, 0, 250, 600), { width: WIDTH })
        .align,
      "end",
    );
    // And a tie goes to the side every menu in this app opened on before there
    // was a choice: 250 - 75 = 175 and 175 - 0 = 175.
    assert.equal(
      placeMenu(box(75, 40, 175, 64), box(0, 0, 250, 600), { width: WIDTH })
        .align,
      "start",
    );
  });

  test("the window is what it is measured against when there is no panel", () => {
    // jsdom's window is 1024x768, and the helper reads it rather than being
    // handed it: the two row menus are positioned in the viewport, and this is
    // the only box they have.
    assert.deepEqual(viewportBounds(), {
      top: 0,
      left: 0,
      right: 1024,
      bottom: 768,
    });
  });
});

describe("a fixed menu is given the placement as offsets", () => {
  test("opening down and right is the position it had before there was a choice", () => {
    // The ported behaviour, and it has to be exactly this: the two row menus
    // were given `left: box.left, top: box.bottom + gap` by hand, so a menu
    // that opened down with room around it must land on the same pixel or this
    // is a regression dressed as a fix.
    const button = box(24, 200, 48, 224);
    const { offsets } = placeFixedMenu(button, 4);
    assert.deepEqual(offsets, { top: 228, left: 24 });
  });

  test("and opening up is the same position, written from the window's floor", () => {
    // A fixed box counts `bottom` up from the viewport's bottom edge, so the
    // menu's bottom lands at 417 - 4 = 413, one gap above the click.
    const { placement, offsets } = placeFixedMenu(pointerBounds(243, 417), 4);
    assert.equal(placement.dir, "up");
    assert.deepEqual(offsets, { bottom: 768 - 417 + 4, left: 243 });
  });

  test("and it stays on the anchor's left edge, however far right that is", () => {
    // The horizontal half is not a question for these two: a 132px menu hanging
    // off a click in a 255px sidebar, or off a tab in a strip capped at 60% of
    // the window, is inside the window for any width above 330 -- and this
    // window cannot be made narrower than 640. So the offsets are the anchor's
    // own left edge and nothing else, which is also the position the inline
    // `left: x` gave these menus before there was a placement.
    const { offsets } = placeFixedMenu(pointerBounds(980, 300), 4);
    assert.equal(offsets.left, 980);
  });
});
