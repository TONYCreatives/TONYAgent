/**
 * Layout rules jsdom cannot measure.
 *
 * Everything below is a *cascade* decision rather than a rendering one: which
 * rule wins, and whether a rule exists at all in the state it was meant for.
 * jsdom has no layout engine, so `getBoundingClientRect` returns zeros and a
 * computed-style assertion here would pass against anything -- the same trap the
 * row-menu colour tests document, where a rule can sit in the file the whole
 * time and never once apply.
 *
 * So the stylesheet is read directly, the way `reducedMotion.test.ts` reads it.
 * What cannot be checked this way is pixels: that the collapsed rail's icons
 * really do line up is verified in the packaged app with a real layout, and
 * recorded in NEXT_SESSION.md. What *can* be checked here is the thing that
 * actually went wrong -- that the toggle carried a cross-axis rule of its own,
 * and that nothing pinned the shell's rows when the title bar became the first
 * child of the grid.
 */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { describe, test } from "node:test";

// `tsc` emits the tests to `.tmp/` and copies no other file, so the stylesheet
// is one directory up from the compiled module.
const STYLESHEET = readFileSync(new URL("../src/styles.css", import.meta.url), "utf8");

/**
 * `selector { body }` pairs, comments and the reduced-motion block stripped.
 *
 * Comments go first for the reason the other two stylesheet readers give: this
 * file documents rules in comments that name the very selector they document,
 * so a comment left in place is parsed as part of the selector it precedes.
 *
 * The reduced-motion block goes too, because it re-declares selectors with
 * `animation: none` and is declared last -- so `.sidebar`, `.chatrow` and a
 * dozen others would resolve to their *cancellations* here, and asking what
 * `top` a cancelled `.sidebar` has would come back empty.
 */
function rules(css: string): { selectors: string[]; body: string }[] {
  const clean = css.replace(/\/\*[\s\S]*?\*\//g, "");
  return [...withoutReducedMotion(clean).matchAll(/([^{}]+)\{([^{}]*)\}/g)].map((m) => ({
    selectors: m[1]
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean),
    body: m[2],
  }));
}

/** Remove the `@media (prefers-reduced-motion: reduce) { ... }` block. */
function withoutReducedMotion(css: string): string {
  const opener = /@media[^{]*prefers-reduced-motion:\s*reduce[^{]*\{/g;
  let out = "";
  let cursor = 0;
  for (const match of css.matchAll(opener)) {
    out += css.slice(cursor, match.index);
    let depth = 1;
    let index = match.index + match[0].length;
    while (depth && index < css.length) {
      if (css[index] === "{") depth += 1;
      else if (css[index] === "}") depth -= 1;
      index += 1;
    }
    cursor = index;
  }
  return out + css.slice(cursor);
}

const RULES = rules(STYLESHEET);

/** Every declaration block written for exactly `selector`, in source order. */
function bodies(selector: string): string[] {
  return RULES.filter((rule) => rule.selectors.includes(selector)).map((rule) => rule.body);
}

/** The last declaration block for `selector`, which is the one that wins. */
function body(selector: string): string {
  const found = bodies(selector);
  assert.ok(found.length > 0, `${selector} has no rule in the stylesheet at all`);
  return found[found.length - 1];
}

// --- the collapsed rail ----------------------------------------------------
describe("the sidebar's reopen button", () => {
  test("it carries no cross-axis placement of its own", () => {
    // The rail centres its buttons with `align-items: center`. `align-self:
    // flex-start` on the toggle overrode that in *both* states: invisible when
    // expanded, because `.rail-expanded .rail-btn` is `width: 100%` there, and
    // 16px off in the collapsed rail -- measured at x=0 while every other icon
    // sat at x=16, so the one control that brings the sidebar back was the one
    // hanging against the window edge.
    //
    // Asserted as the *absence* of a declaration rather than the presence of the
    // replacement, because any value here reintroduces the misalignment and only
    // the rail's own centring gets it right.
    const own = bodies(".rail-toggle").join("\n");
    assert.doesNotMatch(
      own,
      /align-self/,
      "the toggle is placed on the cross axis itself, so it will not line up with the icons beside it",
    );
  });

  test("the expanded rail still gives it the full width", () => {
    // Not redundant with the rule above. `stretch` only reproduces what
    // `align-items: stretch` already does in the expanded rail; dropping it is
    // harmless, and asserting its absence instead would pin a line that has no
    // job. What has to survive is that the toggle is a full-width row there,
    // like every other button.
    const expanded = bodies(".rail.rail-expanded .rail-toggle").join("\n");
    assert.match(expanded, /align-self:\s*stretch/, "the expanded toggle lost its row");
    assert.match(body(".rail.rail-expanded"), /align-items:\s*stretch/);
  });

  test("the icons themselves are still centred, which is what it now relies on", () => {
    assert.match(body(".rail"), /align-items:\s*center/);
  });
});

// --- the title bar's row ---------------------------------------------------
describe("the app shell's rows", () => {
  test("the shell has a row of its own for the title bar", () => {
    // One `100%` row means the title bar shares a track with everything else,
    // and the caption ends up wherever auto-placement puts it.
    const rows = /grid-template-rows:\s*([^;]+)/.exec(body(".app"));
    assert.ok(rows, "the shell declares no rows at all");
    assert.match(rows[1], /var\(--topbar-h\)/);
  });

  test("the title bar takes row 1 across every column", () => {
    // Across *every* column, because the caption buttons belong at the right
    // edge of the window and not at the right edge of the transcript column --
    // which the Files panel covers.
    const bar = body(".topbar");
    assert.match(bar, /grid-row:\s*1\b/);
    assert.match(bar, /grid-column:\s*1\s*\/\s*-1/);
  });

  test("every other in-flow child names its row explicitly", () => {
    // Auto-placement fills row 1 first. A build that renders no Files panel at
    // all would then push the rail into the title bar's row and move the whole
    // window down 42px, and nothing about that failure points at the grid.
    for (const selector of [".sidecol", ".main", ".sidebar-reopen"]) {
      assert.match(body(selector), /grid-row:\s*2\b/, `${selector} does not name row 2`);
    }
    // And each names its column, for the same reason: `.main` was once
    // auto-placed and landed in the collapsed rail's track.
    assert.match(body(".sidecol"), /grid-column:\s*1\b/);
    assert.match(body(".main"), /grid-column:\s*2\b/);
    assert.match(body(".sidebar-reopen"), /grid-column:\s*3\b/);
  });

  test("the Files overlay starts below the title bar", () => {
    // It is an overlay, so it would otherwise cover the caption -- putting its
    // own header where the window's close button is -- and take the drag region
    // with it, leaving a window with the panel open impossible to move.
    assert.match(body(".sidebar"), /top:\s*var\(--topbar-h\)/);
    assert.match(body(".sidebar-scrim"), /inset:\s*var\(--topbar-h\)/);
  });
});

// --- the custom budget field ----------------------------------------------
describe("the budget number field", () => {
  test("the native spinners are removed", () => {
    // `appearance: none`, not `::-webkit-inner-spin-button { display: none }`.
    // The webkit rule leaves a field that still decides for itself what it will
    // accept on some paths, and on Windows what is actually being removed here
    // is a white pair of arrows on a black popover.
    assert.match(body(".budget-custom-input"), /appearance:\s*none/);
  });

  test("it is styled as the control itself, not wrapped", () => {
    // The same trap as `.settings-select` and `.sidebar-filter`, documented in
    // this file: a styled wrapper leaves the platform's own chrome on top.
    assert.ok(
      !STYLESHEET.includes(".budget-custom-field"),
      "the field is wrapped in a styled div, so the native control shows through",
    );
  });

  test("a refused value is shown in the popover, next to the field", () => {
    assert.match(body(".budget-problem"), /color:\s*var\(--danger\)/);
  });
});