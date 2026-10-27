/**
 * The icon system, asserted as a contract rather than a description.
 *
 * Three things are checked from the rendered DOM: every registry entry draws
 * its declared weight within ±0.1px at every ladder size, stroked entries
 * carry no colour of their own, and every svg is hidden from assistive tech
 * (the control beside it is what is named). Two things are checked from the
 * source tree: the svg tag appears in exactly four files, and no path data is
 * defined twice. A spec nobody can fail is a comment; this file is what makes
 * §5.6 of the plan a rule.
 */

import "./test-dom.js";
import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { describe, test } from "node:test";

import { DRAWN_WEIGHT, ICON_SIZES, Icon, STROKE_FOR_SIZE, type IconName } from "./icons.js";
import { one, render } from "./test-render.js";

// `../src/`, not `./`: the compiled test runs from `.tmp/`, which holds no
// sources. The same address `stylesheet.ts` uses, for the same reason.
const SRC = new URL("../src/", import.meta.url);

/** Every non-test component source in the tree. */
function sources(): { name: string; text: string }[] {
  return readdirSync(SRC)
    .filter((name) => name.endsWith(".tsx") && !name.endsWith(".test.tsx"))
    .map((name) => ({ name, text: readFileSync(new URL(name, SRC), "utf8") }));
}

const NAMES: IconName[] = [
  "search",
  "close",
  "plus",
  "back",
  "folder",
  "file",
  "eye",
  "eyeOff",
  "trash",
  "send",
  "agent",
  "code",
  "trajectory",
  "usage",
  "pet",
  "dockOpen",
  "dockClosed",
  "assistantOpen",
  "assistantClosed",
  "forward",
  "gear",
  "stop",
  "menu",
];

const SOLID: ReadonlySet<IconName> = new Set(["stop", "menu"]);

describe("the registry draws one weight, in one frame, in one colour", () => {
  test("the ladder is four sizes and the table covers exactly it", async () => {
    assert.deepEqual([...ICON_SIZES], [12, 14, 16, 20]);
    assert.deepEqual(
      Object.keys(STROKE_FOR_SIZE).map(Number).sort((a, b) => a - b),
      [12, 14, 16, 20],
    );
  });

  for (const name of NAMES) {
    for (const size of ICON_SIZES) {
      test(`${name} at ${size}px draws ${DRAWN_WEIGHT}px within a tenth`, async () => {
        const container = await render(<Icon name={name} size={size} />);
        const svg = one(container, "svg")!;
        assert.equal(svg.getAttribute("viewBox"), "0 0 24 24");
        assert.equal(svg.getAttribute("width"), String(size));
        assert.equal(svg.getAttribute("height"), String(size));
        assert.equal(svg.getAttribute("aria-hidden"), "true");
        if (SOLID.has(name)) {
          assert.equal(svg.getAttribute("fill"), "currentColor");
          assert.equal(svg.getAttribute("stroke"), "none");
          assert.equal(svg.getAttribute("stroke-width"), null);
          return;
        }
        // Stroked: no colour of its own, and the table's stroke for the size.
        assert.equal(svg.getAttribute("fill"), "none");
        assert.equal(svg.getAttribute("stroke"), "currentColor");
        const stroke = Number(svg.getAttribute("stroke-width"));
        assert.equal(stroke, STROKE_FOR_SIZE[size]);
        const drawn = (stroke * size) / 24;
        assert.ok(
          Math.abs(drawn - DRAWN_WEIGHT) <= 0.1,
          `${name} at ${size}px draws ${drawn.toFixed(3)}px, not ${DRAWN_WEIGHT}`,
        );
      });
    }
  }

  test("a className reaches the svg, for the tree rows that tint it", async () => {
    const container = await render(<Icon name="folder" size={12} className="tree-icon" />);
    assert.equal(one(container, "svg")!.getAttribute("class"), "tree-icon");
  });
});

describe("the registry is the only place that draws", () => {
  test("the svg tag appears in exactly four files", async () => {
    const open = "<" + "svg";
    const drawn = sources()
      .filter(({ text }) => text.includes(open))
      .map(({ name }) => name)
      .sort();
    assert.deepEqual(drawn, ["AppMark.tsx", "WindowControls.tsx", "icons.tsx", "petcard.tsx"]);
  });

  test("no path data is defined twice", async () => {
    // Static `d` and `points` literals. Marks and captions draw their own
    // geometry (the pet's eyes are template expressions, the mark is rects);
    // what this forbids is two copies of one literal, which is how close,
    // plus, folder, search and back chevron each came to exist three times.
    const seen = new Map<string, string>();
    for (const { name, text } of sources()) {
      for (const match of text.matchAll(/\sd="([^"]+)"|\spoints="([^"]+)"/g)) {
        const data = match[1] ?? match[2];
        const first = seen.get(data);
        assert.equal(
          first,
          undefined,
          `${data.slice(0, 48)}… is drawn in both ${first} and ${name}`,
        );
        seen.set(data, name);
      }
    }
    assert.ok(seen.size > 20, "the scan found almost nothing, so it scans nothing");
  });

  test("no size lives outside the ladder", async () => {
    // Width, height and frame stroke as numeric literals: the registry owns
    // the table, the marks own their own canvases (dynamic props), and the
    // captions are the OS's 10. Anything else is a glyph with its own numbers.
    const allowed = new Set(["10", "12", "14", "16", "20"]);
    for (const { name, text } of sources()) {
      if (name === "AppMark.tsx" || name === "petcard.tsx" || name === "WindowControls.tsx") {
        continue;
      }
      for (const match of text.matchAll(/(?:width|height)="(\d+)"/g)) {
        assert.ok(allowed.has(match[1]), `${name} draws a ${match[1]}px box`);
      }
      for (const match of text.matchAll(/strokeWidth="([^"]+)"/g)) {
        assert.fail(`${name} sets its own frame stroke: ${match[1]}`);
      }
    }
  });
});
