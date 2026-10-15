/**
 * One drawing, three places.
 *
 * `app/icons/icon.svg` is what the taskbar, the installer and the window
 * frame show, and `AppMark` is what the title bar and the first-run state draw.
 * They are the same glyph, and nothing but this test knows that -- an SVG file
 * and a React component share no type, no import and no build step, so the usual
 * "you can't have two sources of truth" arguments do not apply and the drift is
 * silent. The rail had the glyph inline, the first-run state wanted it again at
 * a hundred pixels, and the failure mode of both of those is a logo that is
 * subtly not itself in one place, which is the kind of thing nobody reports and
 * everybody notices.
 *
 * So the geometry is compared against the file itself rather than against a
 * copy of it in a third file, which would only relocate the problem. When the
 * artwork is redrawn, this is the test that says so, and it says so by failing.
 *
 * The mark changed construction as well as shape: it was two stroked paths, then
 * two stadium rects, and is now two flat rects, so the agreement is on
 * `x`/`y`/`width`/`height`/`rx` rather than on `d`. Comparing rect attributes
 * rather than rasterising both and diffing the pixels is deliberate -- a pixel
 * diff passes when the two differ by a hair, and this is the test whose job is
 * to notice that they are different drawings.
 */

import "./test-dom.js";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { describe, test } from "node:test";

import { AppMark, MARK_EYES, MARK_FACE_AT, MARK_RECTS, MARK_VIEWBOX } from "./AppMark.js";
import { FOCUSABLE, one, render } from "./test-render.js";

// `tsc` emits the tests to `.tmp/` and copies no other file, so the artwork is
// one directory up from the compiled module and beside `src/`.
const ARTWORK = readFileSync(
  new URL("../icons/icon.svg", import.meta.url),
  "utf8",
);

/** Every `<rect .../>` in the artwork, as attribute maps, in file order. */
function artworkRects(): Record<string, string>[] {
  return [...ARTWORK.matchAll(/<rect\b([^>]*)\/>/g)].map((m) => {
    const attrs: Record<string, string> = {};
    for (const a of m[1].matchAll(/([a-z-]+)="([^"]*)"/g)) {
      attrs[a[1]] = a[2];
    }
    return attrs;
  });
}

describe("the mark", () => {
  test("its two strokes are the strokes on the taskbar", () => {
    // Both rects, both orders, all five numbers each. One rect matching is not
    // evidence of anything, and a glyph drawn with the stem first would pass a
    // set comparison while the window showed a different drawing.
    const drawn = artworkRects();
    // The first rect is the ground, not a stroke of the glyph.
    const strokes = drawn.slice(1);
    assert.equal(strokes.length, MARK_RECTS.length, "the file draws a different number of strokes");

    for (const [i, mark] of MARK_RECTS.entries()) {
      const rect = strokes[i];
      assert.ok(rect, `icon.svg has no stroke ${i}, so the window would show a different glyph`);
      for (const key of ["x", "y", "width", "height", "rx"] as const) {
        assert.equal(
          rect[key],
          String(mark[key]),
          `stroke ${i} differs on ${key}: component ${mark[key]}, icon.svg ${rect[key]}`,
        );
      }
    }

    assert.equal(
      MARK_RECTS.length,
      drawn.length - 1,
      "icon.svg draws something the component does not",
    );
  });

  test("it is drawn at the artwork's own weight, not a lighter cousin", async () => {
    // 204 of 1024 is the number `icon.svg` documents at length: 3.19px at the 16px
    // the rail and the taskbar both show. The stadium mark before it was 163 --
    // 2.55px, which still rasterised as a solid two-pixel core, so this is not
    // a rescue from a broken stem; it is the weight that went with the flat
    // terminals. The chevron before that was 72 of 512 -- 14.06%, which came
    // through as 0.7px, below a device pixel, and did disintegrate. Read off
    // the rendered DOM rather than off the source, so what is checked is what
    // the browser is handed.
    const container = await render(<AppMark />);
    const rects = [...container.querySelectorAll("rect")];
    assert.equal(rects.length, MARK_RECTS.length);

    const stem = rects[1];
    for (const key of ["x", "y", "width", "height", "rx"] as const) {
      assert.equal(
        stem.getAttribute(key),
        String(MARK_RECTS[1][key]),
        `the rendered stem does not carry ${key}`,
      );
    }

    // The floor, stated as a ratio rather than as "204", so a future redraw that
    // thins the stem has to move this number on purpose. 19.92% is what this
    // redraw chose (204/1024); the stadium mark sat at 15.92% (163/1024) and
    // the chevron at 14.06% (72/512), which is the thinnest this app has ever
    // shipped and the one that came through as 0.7px.
    const stemPct = (MARK_RECTS[1].width / MARK_VIEWBOX) * 100;
    assert.ok(
      stemPct >= 19.92,
      `the stem is ${stemPct.toFixed(2)}% of the canvas, below the 19.92% this `
        + "redraw measured and chose, so the mark is being thinned rather than "
        + "redrawn",
    );

    assert.equal(
      one(container, "svg")!.getAttribute("viewBox"),
      `0 0 ${MARK_VIEWBOX} ${MARK_VIEWBOX}`,
    );
    assert.ok(ARTWORK.includes(`viewBox="0 0 ${MARK_VIEWBOX} ${MARK_VIEWBOX}"`));
  });

  test("both terminals are square, and the two strokes meet without a seam", () => {
    // Square, because that is what a T has: no mitre to blunt, no arm to round off.
// The stadium mark before it spent half the crossbar's length tapering into a
    // half-circle, so at 16px the bar's middle rows were white and its ends were
    // blue, and the whole mark read as a lozenge. A quarter-radius compromise
    // does not fix that, it only halves it, which is why the soft-corner
    // candidate was drawn and dropped rather than adopted.
    for (const [i, r] of MARK_RECTS.entries()) {
      assert.equal(
        Number(r.rx),
        0,
        `stroke ${i} has rx ${r.rx}: the terminals are square, and a radius here `
          + "is the taper that made the mark illegible at 16px",
      );
    }

    // Meeting without a seam is a geometry claim, not a taste one: the stem's
    // top edge is the crossbar's bottom edge, so nothing overlaps (which would
    // antialias the shared line twice, leaving a lighter seam down the middle of
    // the glyph) and nothing is left with a gap (which at 16px is a sub-pixel
    // break, and a T whose crossbar floats above its stem is not a T).
    const [bar, stem] = MARK_RECTS;
    assert.equal(
      stem.y,
      bar.y + bar.height,
      `the stem starts at y=${stem.y} but the crossbar ends at y=${bar.y + bar.height}, `
        + "so the two either overlap or leave a gap",
    );

    // And centred under it exactly -- an off-centre stem is the other way a T
    // stops reading as one, and `(1024 - 204) / 2 = 410` is what makes it exact.
    const barCentre = bar.x + bar.width / 2;
    const stemCentre = stem.x + stem.width / 2;
    assert.equal(
      stemCentre,
      barCentre,
      `the stem is centred at ${stemCentre} and the crossbar at ${barCentre}`,
    );
    assert.equal(stemCentre, MARK_VIEWBOX / 2, "the glyph is not centred on the canvas");
  });

  test("it cannot be reached by Tab or announced twice", async () => {
    const container = await render(<AppMark />);
    const svg = one(container, "svg")!;

    // `aria-hidden` because every surface that draws this already says the name
    // in text -- the tab beside it in the title bar, the wordmark on the
    // first-run panel.
    assert.equal(svg.getAttribute("aria-hidden"), "true");
    // SVG 1.1's spelling of the same thing. Without it this element is focusable
    // in some WebView builds, which would put a Tab stop on a decoration.
    assert.equal(svg.getAttribute("focusable"), "false");
    assert.equal(
      container.querySelectorAll(FOCUSABLE).length,
      0,
      "the mark is something a keyboard can land on",
    );
  });

  test("it is painted on currentColor, never on a literal", async () => {
    // The rail is achromatic by design and the first-run state wants the accent,
    // and `--accent` is read out of the rasterised artwork -- so a hex here
    // would be a colour that stops moving when the artwork does.
    const container = await render(<AppMark />);
    assert.equal(one(container, "svg")!.getAttribute("fill"), "currentColor");
    assert.equal(one(container, "svg")!.getAttribute("stroke"), null);
    // The eyes are the one carve that is not `currentColor`: they are the
    // surface tone, the poke through the glyph that makes it a face rather than a
    // mark with two holes. The stroke rule still holds -- an eye is a fill.
    const strokes = one(container, "svg")!.querySelectorAll("circle[stroke]");
    assert.equal(strokes.length, 0, "an eye is stroked, which is not an eye");
  });

  test("and the pet's eyes are the two circles the artwork draws", async () => {
    // The face is part of the one drawing too. `MARK_EYES` are the same two eyes
    // the desktop pet draws, and `icon.svg` carries them as circles so the rect
    // comparison above keeps seeing only the body's two strokes. Comparing both
    // keeps the window's eyes and the taskbar's from drifting apart -- the drift
    // this test was written to catch, now about the face as well as the frame.
    assert.equal(MARK_EYES.length, 2);
    const expected = MARK_EYES.map((e) => ({
      cx: String(e.cx),
      cy: String(e.cy),
      r: String(e.r),
    }));

    // At the face threshold and above, the mark is the pet -- eyes and all.
    const container = await render(<AppMark size={MARK_FACE_AT} />);
    const circles = [...one(container, "svg")!.querySelectorAll("circle")].map((c) => ({
      cx: c.getAttribute("cx"),
      cy: c.getAttribute("cy"),
      r: c.getAttribute("r"),
    }));
    assert.deepEqual(circles, expected, "the mark does not draw the pet's two eyes");

    const drawn = [...ARTWORK.matchAll(/<circle\b([^>]*)\/>/g)].map((m) => {
      const attrs: Record<string, string> = {};
      for (const a of m[1].matchAll(/([a-z-]+)="([^"]*)"/g)) attrs[a[1]] = a[2];
      return { cx: attrs.cx ?? null, cy: attrs.cy ?? null, r: attrs.r ?? null };
    });
    assert.deepEqual(
      drawn.map((d) => ({ cx: d.cx, cy: d.cy, r: d.r })),
      expected,
      "icon.svg draws different eyes from the mark",
    );
  });

  test("below the face threshold it is the clean T, with no eyes", async () => {
    // The title bar draws this at 22px. Two r=52 eyes there are a hair each and
    // read as specks on a bar rather than a look, so the small mark holds the
    // face back and stays the two strokes it always was. The taskbar icon is a
    // separate raster that keeps its eyes at every size; this is only the one
    // in-app component, drawn live.
    const small = await render(<AppMark size={22} />);
    const svg = one(small, "svg")!;
    assert.equal(
      svg.querySelectorAll("circle").length,
      0,
      "a mark too small for a face is drawing one",
    );
    // Gating the eyes gated nothing else: the strokes are still the whole mark.
    assert.equal(svg.querySelectorAll("rect").length, MARK_RECTS.length);
  });

  test("the size it is asked for is the size it draws", async () => {
    // Both attributes, not just one: an SVG with a width and no height lays out
    // at 150x100 in some engines, and the mark would stop being square on the
    // one surface where it is the largest thing on screen.
    const container = await render(<AppMark size={104} />);
    const svg = one(container, "svg")!;
    assert.equal(svg.getAttribute("width"), "104");
    assert.equal(svg.getAttribute("height"), "104");

    const small = await render(<AppMark />);
    assert.equal(one(small, "svg")!.getAttribute("width"), "32");
  });
});