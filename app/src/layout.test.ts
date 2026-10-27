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
import { readFileSync, readdirSync } from "node:fs";
import { describe, test } from "node:test";

import { MENU_GAP } from "./menuPlacement.js";
import { readStylesheet, readStylesheetSource, stylesheetModules } from "./stylesheet.js";

// `tsc` emits the tests to `.tmp/` and copies no other file, so the stylesheet
// is one directory up from the compiled module.
const STYLESHEET = readStylesheet();

/** The entry itself: the `@import` list, with no rules behind it. */
const readEntry = () => readFileSync(new URL("../src/styles.css", import.meta.url), "utf8");

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

// --- colour maths -----------------------------------------------------------
// At module scope because three describes need it: the palette's ladders, the
// focus ring's legibility, and the composer's depth check. Each has a copy of
// this and they drift.

/** The declared hex of a token, e.g. `tokens("bg") === "#1a1a1a"`. */
const tokens = (name: string) =>
  new RegExp(`--${name}: *(#[0-9a-f]{6})`, "i").exec(STYLESHEET)?.[1];

/** Any declared value, for the steps that are lengths rather than colours. */
const tokenRaw = (name: string) =>
  new RegExp(`--${name}: *([^;]+);`, "i").exec(STYLESHEET)?.[1]?.trim();

const rgb = (hex: string) =>
  [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16));

/** WCAG relative luminance. Linearised, not the 0.2126r+... approximation. */
const luminance = (hex: string) =>
  rgb(hex)
    .map((v) => v / 255)
    .map((v) => (v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4))
    .reduce((sum, v, i) => sum + v * [0.2126, 0.7152, 0.0722][i], 0);

/** WCAG contrast ratio between two hex colours. */
const contrast = (a: string, b: string) => {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
};

/**
 * A flat masked colour token -- `rgb(r g b / a)` -- as `{ hex, alpha }`, or null.
 *
 * `--wash` is one colour at low alpha rather than a gradient's stops, and the
 * alpha is the interesting half: it is what keeps the ink on a washed row
 * legible. A gradient's ends would each need their own check; a flat tint needs
 * one, which is the whole reason this is simpler than the helper it replaced.
 */
const flatMasked = (name: string) => {
  const m = /rgba?\(\s*(\d+)\s+(\d+)\s+(\d+)\s*(?:\/\s*([\d.]+)\s*)?\)/i.exec(
    tokenRaw(name) ?? "",
  );
  if (!m) return null;
  return {
    hex:
      "#" +
      [m[1], m[2], m[3]].map((v) => Number(v).toString(16).padStart(2, "0")).join(""),
    alpha: m[4] === undefined ? 1 : parseFloat(m[4]),
  };
};


/**
 * Composite one hex over another, as the compositor does.
 *
 * Alpha compositing is not linear in the colours, so a wash cannot be reasoned
 * about by looking at its stops: `rgb(99 147 240 / 0.18)` is a *very* different
 * pixel over `--bg` than the same blue at full strength, and it is the
 * composited pixel that the text has to be readable against.
 */
function over(hex: string, alpha: number, onto: string): string {
  const top = rgb(hex);
  const back = rgb(onto);
  return (
    "#" +
    top
      .map((v, i) => Math.round(v * alpha + back[i] * (1 - alpha)))
      .map((v) => v.toString(16).padStart(2, "0"))
      .join("")
  );
}

/**
 * How much colour a pixel carries: its largest channel minus its smallest.
 *
 * Separating "selected" from "hovered" is not a lightness question. The wash
 * composited over `--bg` is *darker* than `--hover` at its bright end, so the
 * two are within about 1.1:1 of each other by luminance and could not be told
 * apart by contrast at all. What tells them apart is that one is achromatic and
 * the other is not, which is the property worth asserting.
 */
const chroma = (hex: string) => {
  const [r, g, b] = rgb(hex);
  return Math.max(r, g, b) - Math.min(r, g, b);
};

/**
 * Resolve a token to its hex, following `var()` references.
 *
 * Needed because `--focus-ring` is declared as `var(--accent-bright)`. An
 * earlier version of the test that checked it read `--accent-bright` directly,
 * which meant it passed whatever `--focus-ring` was set to -- it was asserting
 * a fact about a different token than the one in the rule. The depth cap turns
 * a cycle into a clear failure instead of a stack overflow.
 */
function resolveHex(name: string, depth = 0): string | undefined {
  const raw = tokenRaw(name);
  if (!raw) return undefined;
  const ref = /^var\(\s*(--[\w-]+)/.exec(raw);
  if (ref) {
    return depth >= 4 ? undefined : resolveHex(ref[1].slice(2), depth + 1);
  }
  return /^#[0-9a-f]{6}$/i.test(raw) ? raw : undefined;
}

/**
 * The stylesheet with its comments removed, for asserting that a selector or
 * token is *absent*.
 *
 * Separate from `STYLESHEET` because the two answer different questions. "Does
 * a rule for this selector exist?" wants the whole file -- the rules are found
 * through `RULES`, which strips comments for exactly the reason `rules`
 * documents. "Does this string appear anywhere?" does not: the prose in this
 * file explains what was removed and why, and it names the removed selectors
 * while doing so. A comment saying "`.app.rail-open` is gone entirely" is the
 * most useful comment in the file, and it would fail an absence test run
 * against the text.
 *
 * `withoutReducedMotion` is deliberately not applied here. The block being
 * asked about is not motion the user can turn off -- a reduced-motion
 * cancellation of a selector that no longer exists is harmless, and a
 * cancellation of one that does is a *feature*.
 */
const SOURCE = readStylesheetSource();

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

/** The first declaration block, before component-specific responsive overrides. */
function baseBody(selector: string): string {
  const found = bodies(selector);
  assert.ok(found.length > 0, `${selector} has no rule in the stylesheet at all`);
  return found[0];
}

/**
 * Every block declared at one width, in cascade order.
 *
 * `mediaBody` below returns the first one, which is right when the test is
 * asking about one surface's rule. It stopped being enough the moment the ladder
 * became shared: `(max-width: 560px)` appears in the title bar and in the status
 * bar now, so "the first block at 560" would answer a question about the footer
 * with the title bar's rules -- and pass, because the assertion it feeds is about
 * a selector that happens to be in both.
 */
function mediaBodies(query: string): string {
  const marker = `@media (${query})`;
  const out: string[] = [];
  let from = 0;
  for (;;) {
    const start = STYLESHEET.indexOf(marker, from);
    if (start === -1) break;
    const open = STYLESHEET.indexOf("{", start);
    let depth = 1;
    let index = open + 1;
    for (; index < STYLESHEET.length; index += 1) {
      if (STYLESHEET[index] === "{") depth += 1;
      if (STYLESHEET[index] === "}" && --depth === 0) break;
    }
    out.push(STYLESHEET.slice(open + 1, index));
    from = index;
  }
  assert.ok(out.length > 0, `${marker} is missing`);
  return out.join("\n");
}

/** A media query body with nested rules, kept intact for responsive assertions. */
function mediaBody(query: string): string {
  const marker = `@media (${query})`;
  const start = STYLESHEET.indexOf(marker);
  assert.notEqual(start, -1, `${marker} is missing`);
  const open = STYLESHEET.indexOf("{", start);
  let depth = 1;
  for (let index = open + 1; index < STYLESHEET.length; index += 1) {
    if (STYLESHEET[index] === "{") depth += 1;
    if (STYLESHEET[index] === "}" && --depth === 0) {
      return STYLESHEET.slice(open + 1, index);
    }
  }
  assert.fail(`${marker} is not closed`);
}

/**
 * One side of a `margin`/`padding` shorthand, in CSS px.
 *
 * Longhand first, then the shorthand expanded the way CSS expands it: one value
 * is all four sides, two is vertical/horizontal, three adds the bottom, four is
 * all of them. `side` is 0 for top/left and 2 for bottom/right.
 *
 * This is here rather than inlined because the first version of it was wrong
 * in exactly the way it exists to prevent: `padding: 18px` is a single value
 * meaning all four sides, and reading index 1 out of it returned `undefined`,
 * which the `?? 0` turned into a confident zero. A stylesheet assertion that
 * measures nothing passes, so a helper that silently returns 0 is worse than
 * no helper.
 */
function boxSide(text: string, prop: "margin" | "padding", side: 0 | 2): number {
  const longhand = new RegExp(`${prop}-${side === 0 ? "top|left" : "bottom|right"}:\\s*([\\d.]+)px`)
    .exec(text);
  if (longhand) return parseFloat(longhand[1]);
  const values = new RegExp(`(?:^|;)\\s*${prop}:\\s*([^;]+)`).exec(text)?.[1].trim().split(/\s+/) ?? [];
  if (values.length === 0) return 0;
  if (values.length === 1) return parseFloat(values[0]);
  // 2 -> vertical/horizontal, 3 -> top/horizontal/bottom, 4 -> all four.
  const index = values.length === 2 ? 1 : side;
  return parseFloat(values[index]);
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
    // There is no expanded rail any more. It used to widen to
    // --rail-w-expanded and stretch its rows, which needed a
    // `.rail.rail-expanded .rail-toggle` rule to keep the toggle a full-width
    // row; the rail is now a fixed 52px strip and the labels are gone, so both
    // rules went with it. Asserting the absence is the assertion -- a rule that
    // widened the rail again is exactly what would break the match with the
    // reference, and it would be easy to reintroduce by copying the old block
    // back.
    assert.doesNotMatch(SOURCE, /\.rail\.rail-expanded/);
    assert.match(body(".rail"), /align-items:\s*center/);
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
    const bar = baseBody(".topbar");
    assert.match(bar, /grid-row:\s*1\b/);
    assert.match(bar, /grid-column:\s*1\s*\/\s*-1/);
  });

  test("every other in-flow child names its row explicitly", () => {
    // Auto-placement fills row 1 first, so a rail or a main that did not name
    // its row would be pushed into the title bar's and move the whole window
    // down `--topbar-h`, and nothing about that failure points at the grid.
    for (const selector of [".rail", ".main"]) {
      assert.match(body(selector), /grid-row:\s*2\b/, `${selector} does not name row 2`);
    }
    // And each names its column, for the same reason: `.main` was once
    // auto-placed and landed in the collapsed rail's track.
    assert.match(body(".rail"), /grid-column:\s*1\b/);
    assert.match(body(".main"), /grid-column:\s*2\b/);
  });

  test("the shell is three columns, and the outer two are the workspace's", () => {
    // Direction B's structural fact: the nav, the reading column, the context
    // pane. The outer widths are tokens, so a dock can widen its own track from
    // one number rather than from a rule that restates 288.
    //
    // `.app.rail-open` still does not exist: the nav's state is `data-nav`, read
    // only to size column 1. Opening a dock *does* change a grid track now, and
    // the change is instant -- see the transition rule below and the note on
    // `.app` -- but it is still not a class that moves the text on every frame.
    assert.doesNotMatch(SOURCE, /\.app\.rail-open/);
    assert.doesNotMatch(SOURCE, /\.sidecol/);
    assert.doesNotMatch(body(".app"), /rail-w-expanded/);
    assert.match(
      body(".app"),
      /grid-template-columns:\s*var\(--nav-w\) minmax\(0, 1fr\) var\(--context-w\)/,
      "the shell must name a nav track, a centre and a context track",
    );
  });

  test("the nav docks at 1101 and the context at 1400, and nowhere else", () => {
    // The two numbers the arithmetic decides. At 1101 the centre is
    // 1101 - 288 - 48 = 765, still above the 760px column; at 1100 it would be
    // 764, so that is the step the nav stops being docked. At 1400 the whole
    // sum is exact: 288 + 824 + 288.
    assert.match(
      mediaBody("min-width: 1101px"),
      /\.app\[data-nav="open"\]\s*\{[^}]*--nav-w:\s*var\(--dock-w\)/,
    );
    assert.match(
      mediaBody("min-width: 1400px"),
      /\.app\[data-context="open"\]\s*\{[^}]*--context-w:\s*var\(--dock-w\)/,
    );
    // 288 is written once, and both docks read it.
    assert.match(STYLESHEET, /--dock-w:\s*var\(--list-w\)/);
    assert.doesNotMatch(body(".app"), /288px/);
  });

  test("the status strip is a row of the window, not of the main column", () => {
    // It used to be `.main`'s last child, so in Code mode it stopped at the
    // assistant's edge and the panel ran under it. A shell row is the honest
    // arrangement: the bar is the window's, and all three panes sit above it.
    assert.match(baseBody(".statusbar"), /grid-column:\s*1\s*\/\s*-1/);
    assert.match(baseBody(".statusbar"), /grid-row:\s*3\b/);
    assert.match(
      body(".app"),
      /grid-template-rows:\s*var\(--topbar-h\)[^;]*var\(--statusbar-h\)/,
    );
  });

  test("below 900 the compact forms float instead of taking a column", () => {
    // 900 is where 64 + 48 would start squeezing the reading column rather than
    // sitting in its air. Both leave the grid there, so the centre is the full
    // window and the 64/48px land in the 70px of air either side of 760.
    const narrow = mediaBody("max-width: 900px");
    assert.match(narrow, /\.app\[data-mode="agent"\]\s*\{[^}]*grid-template-columns:\s*minmax\(0, 1fr\)/);
    assert.match(narrow, /\.app\[data-mode="agent"\] \.rail\s*\{[^}]*position:\s*absolute/);
    assert.match(narrow, /\.app\[data-mode="agent"\] \.contextdock\s*\{[^}]*position:\s*absolute/);
    // The centre keeps clear of the two floating strips, but only by the part
    // the reading column was not already holding: the rail is 64 and the
    // composer's own edge is 32, so 32 more is reserved on the left. Without
    // this the 64px rail painted over the first 32px of the composer at 720.
    assert.match(
      narrow,
      /padding-left:\s*calc\(var\(--rail-w\)\s*-\s*var\(--column-edge\)\)/,
    );
    assert.match(
      narrow,
      /padding-right:\s*calc\(var\(--context-w-collapsed\)\s*-\s*var\(--column-edge\)\)/,
    );
    // Scoped to Agent, explicitly: the Agent forms float over a full-width
    // centre. Code is in this block too, and for the same reason at the same
    // step -- its explorer floats from 900 down, after its assistant already
    // has (see the 1247 rule) -- but its three rules are its own, because the
    // explorer is a panel with a 48px strip here while Agent's nav is a rail.
    assert.match(narrow, /\.app\[data-mode="code"\]\s*\{[^}]*grid-template-columns:\s*var\(--context-w-collapsed\)/);
    assert.match(
      narrow,
      /\.app\[data-mode="code"\] \.code-explorer\s*\{[^}]*position:\s*absolute[^}]*width:\s*var\(--dock-w\)/,
    );
    assert.match(narrow, /\.app\[data-mode="code"\] \.code-strip\s*\{[^}]*display:\s*flex/);
  });

  test("the Files pane is a pane of the sidebar, not a surface of its own", () => {
    // It used to be a right-hand overlay: its own absolute surface, its own
    // scrim and a reopen handle for when it was closed. It is a pane now -- the
    // sidebar's segmented control chooses it, it fills the sidebar's remaining
    // height, and there is nothing left to pin to a window edge or to reopen.
    assert.doesNotMatch(SOURCE, /\.sidebar-reopen/);
    assert.doesNotMatch(SOURCE, /\.sidebar-scrim/);
    assert.match(body(".files-pane"), /flex:\s*1/);
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
// --- the palette -------------------------------------------------------------
describe("the palette is ours", () => {
  // This block used to pin the twelve neutral values to the hexes counted out
  // of a screenshot of another application, one `assert.equal` per colour, and
  // justify each one by saying it was the reference's.
  //
  // That is a test that cannot survive being disagreed with. Every assertion
  // was a value, so the only way to change the palette was to delete the
  // evidence, and the only way for the palette to stay put was to keep copying
  // someone else's window. It also had nothing to say about whether the ramp
  // worked, which is the part that was actually wrong: --fg-mute sat at 4.21:1
  // on the field, under what 11px text needs, and no assertion here could see
  // that because every assertion was about a hex.
  //
  // What follows asserts the *properties* the two ladders have to have --
  // achromatic, ordered, legible -- and computes them from the token values in
  // the file. A step can be nudged and these still hold; a step that breaks the
  // ordering or the contrast floor fails, and says which.
  /** Every neutral, in the order the depth ladder climbs. */
  const SURFACES = ["bg", "surface", "chrome", "input", "raised", "chip"];
  const BORDERS = ["border-soft", "border", "border-strong"];
  const TEXT = ["fg", "fg-dim", "fg-mute"];

  test("no neutral carries a tint", () => {
    // The decision this palette is built on: the accent is the only chroma in
    // the window. The ladder it replaced was a warm green-grey, and a chroma
    // of three or four is enough to make two different windows read as the
    // same one -- which is exactly what was happening.
    //
    // Asserted across *every* neutral rather than a sample, because "mostly
    // achromatic" is not a thing a palette can be.
    const tinted: string[] = [];
    for (const name of [...SURFACES, ...BORDERS, ...TEXT]) {
      const [r, g, b] = rgb(tokens(name)!);
      if (r !== g || g !== b) tinted.push(`--${name} ${tokens(name)}`);
    }
    assert.deepEqual(tinted, [], "neutrals that are not r === g === b");
  });

  test("the surfaces climb, so depth has one direction", () => {
    const ladder: [string, number][] = SURFACES.map((n) => [n, luminance(tokens(n)!)]);
    for (let i = 1; i < ladder.length; i += 1) {
      const [prevName, prev] = ladder[i - 1];
      const [name, now] = ladder[i];
      assert.ok(
        prev < now,
        `--${name} (${tokens(name)}) is not above --${prevName} (${tokens(prevName)})`,
      );
    }
  });

  test("the borders climb too, and stay above the surfaces they edge", () => {
    const ladder: [string, number][] = BORDERS.map((n) => [n, luminance(tokens(n)!)]);
    for (let i = 1; i < ladder.length; i += 1) {
      assert.ok(ladder[i - 1][1] < ladder[i][1], `border ladder breaks at --${ladder[i][0]}`);
    }
    // A hairline darker than the thing it outlines is not a hairline; it is a
    // second, weaker border the eye reads as dirt.
    assert.ok(luminance(tokens("border-soft")!) > luminance(tokens("input")!));
    assert.ok(luminance(tokens("border")!) > luminance(tokens("raised")!));
  });

  test("the text ladder clears the legibility floor it is used at", () => {
    // The floors are the ones the tokens are actually used at: --fg is body
    // text, --fg-dim is secondary, and --fg-mute is metadata at 11px and below,
    // which is the small-text case. Before this ramp --fg-mute was 4.21:1 and
    // failed the last of these, which no hex-pinning assertion could have
    // caught.
    const floors: Record<string, number> = { fg: 12, "fg-dim": 7, "fg-mute": 4.5 };
    for (const name of TEXT) {
      const ratio = contrast(tokens(name)!, tokens("bg")!);
      assert.ok(
        ratio >= floors[name],
        `--${name} ${tokens(name)} is ${ratio.toFixed(2)}:1 on --bg, below `
          + `the ${floors[name]}:1 it is used at`,
      );
    }
  });

  test("the type, radius and elevation scales climb", () => {
    // Three ladders now, and the same rule as the surfaces: a step that does
    // not climb is not a step, it is a second name for the one below it. The
    // type ladder is read in px and the radii likewise, so this is the only
    // place that has to know they are lengths at all.
    const px = (name: string) => parseFloat(tokenRaw(name)!);
    for (const [label, names] of [
      ["type", ["text-2xs", "text-xs", "text-sm", "text-base", "text-md", "text-lg", "text-xl", "text-2xl", "text-display"]],
      ["radius", ["radius-xs", "radius-sm", "radius-md", "radius-lg"]],
    ] as const) {
      const values = names.map((n) => px(n));
      for (let i = 1; i < values.length; i += 1) {
        assert.ok(
          values[i] > values[i - 1],
          `--${names[i]} (${values[i]}px) is not above --${names[i - 1]} (${values[i - 1]}px)`,
        );
      }
      assert.ok(values.length > 1, `the ${label} ladder is a single step`);
    }
    // The pill is the one radius that is not a length, so it is excluded from
    // the climb above rather than special-cased inside it.
    assert.ok(parseFloat(tokenRaw("radius-pill")!) > px("radius-lg"));
  });

  test("every scale step is used by at least one rule", () => {
    // `--motion-slow` was declared for as long as this file existed and used
    // zero times, which is exactly what a scale grows when nothing checks. So
    // it is checked: parse the step names out of `:root`, then require each one
    // to be consumed by a rule outside it.
    //
    // Adding a step nobody uses is not free even when it looks free -- it is a
    // name that a later rule will reach for and a value that nothing keeps
    // honest.
    const declared = new Set(
      [...body(":root").matchAll(/(--(?:text|radius|shadow|motion|accent)[\w-]*)\s*:/g)].map(
        (m) => m[1],
      ),
    );
    const used = new Set<string>();
    for (const rule of RULES) {
      if (rule.selectors.includes(":root")) continue;
      for (const m of rule.body.matchAll(/var\((--(?:text|radius|shadow|motion|accent)[\w-]*)/g)) {
        used.add(m[1]);
      }
    }
    assert.deepEqual(
      [...declared].filter((t) => !used.has(t)).sort(),
      [],
      "declared in :root and never used by a rule",
    );
  });

  test("no rule writes a length the scales already own", () => {
    // The same failure as the raw-colour test, one dimension over. Fourteen
    // font sizes, three radii and eleven durations were literals a moment ago;
    // every one of them was a value a palette or scale change could not reach.
    //
    // Two families are exempt and both are exempt because they are not on a
    // scale: `border-radius: 50%` and `1px`, which make a dot or a 3px-tall
    // indicator rather than expressing a step.
    const offenders: string[] = [];
    for (const rule of RULES) {
      if (rule.selectors.includes(":root")) continue;
      const selector = rule.selectors.join(", ");
      for (const decl of rule.body.split(";")) {
        const d = decl.trim();
        if (/^font-size:\s*[\d.]+px/.test(d)) offenders.push(`${selector} -> ${d}`);
        if (/^border-radius:\s*[\d.]+px/.test(d) && !/^border-radius:\s*1px/.test(d)) {
          offenders.push(`${selector} -> ${d}`);
        }
        if (/^transition:/.test(d) && /\b[\d.]+m?s\b/.test(d)) offenders.push(`${selector} -> ${d}`);
      }
    }
    assert.deepEqual(offenders, [], "raw lengths outside the scale tokens");
  });

  test("the accent is white, and the window has no brand colour", () => {
    // This used to pin the accent to #6393f0 and say why: the value was read
    // out of the app icon's own antialias ramp, so it was derived rather than
    // chosen, and a redrawn icon invalidated it. That derivation is gone on
    // purpose -- the window is black, white and grey now -- so the assertion
    // changed with it. What is still worth pinning is the *pair*, because a
    // fill and the ink that sits on it are one decision rather than two.
    assert.equal(tokens("accent"), "#ffffff");
    assert.equal(tokens("accent-fg"), "#000000");
    // The app icon keeps its blue-to-violet tile, because a taskbar slot is a
    // square competing with other squares. So the window and the taskbar no
    // longer share a colour; that is the cost of this palette, and `tokens.css`
    // states it rather than leaving it to be discovered.
    assert.equal(chroma(tokens("accent")!), 0, "the accent is meant to be achromatic");
    assert.equal(chroma(tokens("accent-bright")!), 0);
  });

  test("the accent is legible as text, and its ink is legible on it", () => {
    // The reason the token is the ramp step and not the ground is contrast, so
    // the reason is asserted rather than described: if someone swaps the accent
    // for a prettier blue, this is what tells them it went too dark.
    assert.ok(
      contrast(tokens("accent")!, tokens("bg")!) >= 4.5,
      `--accent ${tokens("accent")} is not readable as text on --bg`,
    );
    assert.ok(
      contrast(tokens("accent-fg")!, tokens("accent")!) >= 4.5,
      `--accent-fg ${tokens("accent-fg")} is not readable on the accent fill`,
    );
  });

  test("signal carries the live state, legibly, on every surface it lands on", () => {
    // §5.1's table, asserted rather than quoted: `--signal` is small text on
    // the pane (8px spine nodes) and on chips, so it holds the 4.5 floor
    // everywhere it can land. Pin the values, not just the floor -- a drift
    // of 0.1 is a different hue, and the table is the contract.
    const signal = tokens("signal")!;
    assert.equal(contrast(signal, tokens("bg")!).toFixed(2), "11.79");
    assert.equal(contrast(signal, tokens("raised")!).toFixed(2), "8.56");
    assert.equal(contrast(signal, tokens("chip")!).toFixed(2), "7.36");
    // `--signal-dim` is secondary live text and graphics, on the two darker
    // surfaces only. On a chip it is 3.97:1, under the small-text floor -- so
    // the token's contract forbids small text there, and this test holds the
    // pairing nobody may add: the only rules that set it as a colour are the
    // pill's detail (on `--chrome`) and the run card's numbers (on
    // `--surface`), each past 4.5:1 in its own ground.
    const dim = tokens("signal-dim")!;
    assert.equal(contrast(dim, tokens("bg")!).toFixed(2), "6.36");
    assert.equal(contrast(dim, tokens("raised")!).toFixed(2), "4.62");
    assert.equal(contrast(dim, tokens("chrome")!).toFixed(2), "5.53");
    assert.equal(contrast(dim, tokens("surface")!).toFixed(2), "5.95");
    assert.ok(contrast(dim, tokens("chip")!) < 4.5, "--signal-dim reads as text on a chip now");
    const dimText = RULES.filter((rule) =>
      rule.body.split(";").some((decl) => /^\s*color\s*:\s*var\(--signal-dim\)/.test(decl)),
    ).map((rule) => rule.selectors.join(", "));
    assert.deepEqual(
      dimText.sort(),
      ['.run-card[data-run="working"] .run-tokens-value', '.statuspill[data-run="working"] .statuspill-detail'],
    );
  });

  test("the only chroma left in the window is meaning", () => {
    // This used to assert that the accent and --ok were far apart on the wheel:
    // a blue accent and a green status dot were both "a colour", and a success
    // dot beside a filled button had to be a distinction of kind. There is no
    // accent hue any more, so the question moved rather than went away. What
    // matters now is that everything carrying chroma is carrying *meaning*, and
    // that nothing carrying the brand is.
    //
    // The floor of 24 is a channel spread, not a hue angle: below about that,
    // a colour reads as grey with a cast rather than as a signal, which is the
    // failure mode this palette would have if the status colours were faded
    // toward the neutrals later.
    for (const name of ["ok", "danger", "warn", "signal", "signal-dim", "traj-add", "traj-del"]) {
      const carried = chroma(tokens(name)!);
      assert.ok(
        carried >= 24,
        `--${name} carries chroma ${carried}, too little to read as a signal`,
      );
    }
    for (const name of ["accent", "accent-bright"]) {
      assert.equal(chroma(tokens(name)!), 0, `--${name} is still carrying brand chroma`);
    }
    for (const name of ["wash", "accent-glow"]) {
      assert.equal(
        chroma(flatMasked(name)!.hex),
        0,
        `--${name} is still carrying brand chroma`,
      );
    }
  });

  test("no rule paints a raw colour the tokens already own", () => {
    // The failures this replaced were all one bug: a literal no token reached,
    // so no palette change could reach it either -- the old accent written out
    // by hand as rgba(186,205,169,0.1), a #d0d0d0 pill, a #333 scrollbar, a
    // #1a0a08 ink. A token swap reaches `var(--accent)` and nothing else, so
    // each of those would have survived it looking deliberate.
    //
    // `:root` is where the tokens are declared, so it is the one place a raw
    // hex belongs. Two families of declaration are exempt, and both are exempt
    // because their colour is not a palette value: `box-shadow`, which is the
    // absence of light, and the near-black scrim/backdrop tints, which are
    // "the window, dimmed" rather than any one colour. Checked against the
    // parsed rules rather than the raw lines so prose in a comment cannot fail
    // this.
    const offenders: string[] = [];
    for (const rule of RULES) {
      if (rule.selectors.includes(":root")) continue;
      const selector = rule.selectors.join(", ");
      if (/-(scrim|backdrop)\b/.test(selector)) continue;
      for (const decl of rule.body.split(";")) {
        if (/^\s*(box-shadow|-webkit-box-shadow)\s*:/.test(decl)) continue;
        for (const bad of decl.matchAll(/#[0-9a-fA-F]{3,8}\b|rgba?\(\s*\d/g)) {
          offenders.push(`${selector} -> ${bad[0]}`);
        }
      }
    }
    assert.deepEqual(offenders, [], "raw colours outside :root");
  });

  test("the browser is told this window is dark", () => {
    // Without it, scrollbars, the scrollbar corner and form-control defaults
    // paint themselves light inside a near-black window.
    assert.match(body(":root"), /color-scheme:\s*dark/);
  });
});

// --- chips, and what "selected" looks like -----------------------------------
//
// This block used to assert the opposite of what it asserts now: "chips are
// rounded rectangles, not stadiums", on the reasoning that one radius for cards
// and the stadium reserved for badges keeps a chip from reading as a different
// control. That reasoning was not wrong, it was just answering a question this
// window has since answered differently -- a shape language where *every*
// control you can see the edge of is a stadium and every container is a rounded
// rectangle. The old assertions are inverted here rather than deleted, because
// the thing worth holding is the *rule*, and the rule changed.
describe("a selected thing is a wash, and the tab is a tab", () => {
  test("the conversation tab is a browser tab, not a chip", () => {
    // It was the reference's chip -- a stadium floating in the middle of the
    // bar, which is the shape of a *control*. It is the shape a browser gives
    // the page it is showing: the height of the strip it is cut into, rounded at
    // the top and **square at the bottom**, so it reads as attached to the top
    // of the window rather than as a pill that happens to be up there.
    //
    // The strip is the bar's height and the tabs take that height, which is what
    // puts their bottom edge on the bar's own rather than in the middle of the
    // chrome. It is the *strip* that stretches them: a tab stretching itself is
    // a tab that only fills the bar when it is the only thing in it.
    assert.match(baseBody(".tabs"), /align-items:\s*stretch/);
    assert.match(baseBody(".tabs"), /height:\s*100%/);
    // Asserted as the four corners rather than as one radius, because the square
    // pair is the whole of the shape: a radius on the lower corners lifts the tab
    // off the edge it is attached to, and it is a chip again.
    assert.match(
      body(".tab"),
      /border-radius:\s*var\(--radius-xs\) var\(--radius-xs\) 0 0/,
    );
    assert.doesNotMatch(body(".tab"), /border-radius:\s*var\(--radius-pill\)/);
  });

  test("and the first tab starts on the rail's right edge", () => {
    // The other half of "the tab is a tab": where the strip *is*. It used to be
    // offset by `--list-w` minus the rail minus the gap so that it began on the
    // conversation panel's right edge. That is only the right answer while the
    // panel is open, and the panel is an overlay that starts closed -- so the
    // common window led with a logo, 224px of empty bar, and a lone tab.
    //
    // The strip is pulled back by exactly the bar's own gap, which is what puts
    // the first tab's left edge on the rail's right edge instead of 8px into the
    // bar. Asserted as the *relationship* rather than as `-8px`, because two
    // copies of eight are two things to keep in step; the day the bar's gap
    // moves, the strip has to move with it.
    //
    // The offset is also asserted absent: a `0` left in front of a stale
    // `--list-w` expression is the half-written failure this replaces, and it
    // would read as aligned without being aligned.
    const gap = parseFloat(/gap:\s*([0-9.]+)px/.exec(baseBody(".topbar"))![1]);
    const pull = parseFloat(/margin-left:\s*-([0-9.]+)px/.exec(baseBody(".tabs"))![1]);
    assert.equal(pull, gap, "the strip is not pulled back by the bar's own gap");
    assert.doesNotMatch(body(".tabs"), /--list-w|--rail-w/);
  });


  test("everything you can be *on* takes the wash, and none of it is a fill", () => {
    // The first two were both `--chip`, the flat step the depth ladder reserves
    // for "raised". A raised step is the right answer for a badge, which is a
    // thing other things sit on, and the wrong one for a selected row, which is
    // a state -- `--chip` is one step off `--hover`, so "the one you are in" and
    // "the one under the pointer" were a shade apart. The wash is a colour the
    // hover cannot be.
    assert.match(body(".tab.is-active"), /background:\s*var\(--wash\)/);
    assert.match(body(".chatrow.is-active"), /background:\s*var\(--wash\)/);

    // And the last two joined them. Both were solid accent fills, which is the
    // one treatment this window keeps for *press me* -- a disc of it in the rail
    // read as a control bolted onto the strip, and a preset painted with it read
    // as a button rather than as the value in force.
    assert.match(
      body(".rail-btn.is-active"),
      /background:\s*var\(--wash\)/,
      "the rail's chosen item is not the wash",
    );
    assert.match(
      body(".budget-preset.is-active"),
      /background:\s*var\(--wash\)/
      ,
      "the chosen budget preset is not the wash",
    );
  });

  test("neither of them draws a hairline any more", () => {
    // The edge of a chip is a shape, not a line. A 1px frame around a stadium is
    // what made the tab read as a card that happened to be short, and a frame on
    // a selected row is a box drawn inside a panel that already has edges.
    for (const selector of [".tab", ".chatrow.is-active"]) {
      assert.doesNotMatch(
        body(selector),
        /border(-top|-right|-bottom|-left)?:\s*1px/,
        `${selector} draws a hairline around a shape whose edge is its own fill`,
      );
    }
  });
});

// --- the shape language ------------------------------------------------------
//
// The tokens state the rule -- "a control you can see the edge of is a stadium,
// and a corner that stops short of one is a container" -- and until this pass it
// was true of the window's chips and of about half its controls. The per-turn
// budget popover is where it showed: a grid of six pill presets with a
// 6px-cornered `Set` button and a 6px-cornered number field under them, in a row
// that is one control.
//
// The sweep that followed is written out here because a list is the only form
// this assertion *can* take: "which classes are controls" is not something the
// stylesheet knows about itself, and a test that guessed from a selector's shape
// would be testing its own guess. What it buys is that the next rule added to a
// list has to be an argument rather than a copy-paste of whatever was nearby --
// and the third list is what that is worth: the sweep pill-ed the rows as well,
// and one look at the running window took them back.
describe("every control is a stadium and every container is a box", () => {
  /** Things the user presses or types in -- a shape that stands alone. */
  const CONTROLS = [
    // The composer, and the popover and menus it opens.
    ".icon-btn",
    ".budget-custom-input",
    ".budget-custom-apply",
    ".attach-item",
    ".attach-thumb",
    ".attach-doc",
    ".attach-remove",
    ".modelpicker-filter",
    ".permchoice-warn",
    ".permchoice-trigger",
    // The sidebar's controls.
    ".chatlist-toggle",
    ".chatlist-back",
    // (`.chatlist-act` lives with the rail above: the foot is the rail's twin,
    // so it wears the rail's corner rather than the pill.)
    // The title bar and the rail.
    ".tab-input",
    ".tab-close",
    // `.rail-btn` and `.chatlist-act` are not here on purpose: they are rounded
    // squares (`--radius-sm`) rather than stadiums, because a full disc of wash
    // on a 44px button read as a separate control bolted onto the strip rather
    // than as the state of the button. A test that required the pill here would
    // be requiring the circle back.
    ".helper-toggle",
    ".code-close",
    // The settings panel.
    ".settings-select",
    ".settings-input",
    ".settings-reveal",
    ".settings-unkey",
  ];

  /**
   * Rows, and why they are not controls.
   *
   * The sweep pill-ed these too and they came back on the owner's eye: a row is
   * as tall as one or two lines and *stacks with its neighbours*, so a stadium
   * turns a list into a column of buttons -- the conversation row is 271x56 and
   * the `/` menu's row is 712x31, which is a capsule the width of the composer.
   * The line the window actually draws is not "does it paint an edge" (a row
   * does, on hover) but "is it one thing you press, or one of a column of them".
   */
  const ROWS = [
    ".chatrow",
    ".chatrow-open",
    ".chatrow-input", // the row's own shape, one step in
    ".tree-row",
    ".skills-item",
    ".modelpicker-item",
    ".rowmenu button",
    ".permchoice-item",
    ".permchoice-list .permchoice-item",
    // The settings page's sections, one of a column rather than a segmented row.
    ".settings-tab",
  ];

  /**
   * Surfaces, and the two shapes that are attached rather than floating.
   *
   * `.composer-inner` and `.permchoice-open` are the two that *hold a stack of
   * controls* -- a control row, and the permission rows -- which is the one
   * reason a control-shaped box keeps a corner: a stadium on a box that tall
   * puts an arc through whatever is at its top and bottom.
   */
  const BOXES = [
    ".composer-inner",
    ".permchoice-open",
    ".modal",
    ".rowmenu",
    ".modelpicker",
    ".skills-menu",
    ".budget-popover",
    ".permchoice-menu",
    ".tab", // cut into the bar's own bottom edge, square where it meets it
    ".md-pre",
    ".usage-tile",
    ".banner",
  ];

  test("no control has a corner", () => {
    // Every block a selector owns, rather than `body`'s last one: several of
    // these classes are declared more than once -- `.chatrow` has an entry
    // animation in `arriving.css` that says nothing about its shape -- and a
    // block with no `border-radius` is not an override, it is an omission.
    for (const selector of CONTROLS) {
      const blocks = bodies(selector);
      assert.ok(
        blocks.some((block) => /border-radius:\s*var\(--radius-pill\)/.test(block)),
        `${selector} is a control with a corner`,
      );
      for (const block of blocks) {
        const declared = /border-radius:\s*([^;]+)/.exec(block)?.[1];
        assert.ok(
          declared === undefined || /var\(--radius-pill\)/.test(declared),
          `${selector} declares a corner: ${declared}`,
        );
      }
    }
  });

  test("no row is a stadium either", () => {
    for (const selector of ROWS) {
      for (const block of bodies(selector)) {
        assert.doesNotMatch(
          block,
          /border-radius:\s*var\(--radius-pill\)/,
          `${selector} is a row in a column wearing a button's shape`,
        );
      }
    }
  });

  test("and no container wears a control's shape", () => {
    for (const selector of BOXES) {
      for (const block of bodies(selector)) {
        assert.doesNotMatch(
          block,
          /border-radius:\s*var\(--radius-pill\)/,
          `${selector} is a container wearing a control's shape`,
        );
      }
    }
  });
});

// --- the strip's own robustness ---------------------------------------------
describe("the tab strip gives way instead of overflowing the window", () => {
  test("the strip can shrink, so a long one cannot push the caption out", () => {
    // `flex: none` held the strip at its content width however tight the bar got,
    // and Close is the last control on the bar, so it was the first thing to end
    // up outside the window.
    assert.match(baseBody(".tabs"), /flex:\s*0 1 auto/);
    assert.match(baseBody(".tabs"), /min-width:\s*0/);
    // Still capped and still not growing: yielding is not the strip taking the
    // bar's slack for itself.
    assert.match(baseBody(".tabs"), /max-width:\s*min\(60%,\s*360px\)/);
    // Past the ceiling it scrolls, rather than crushing the tabs flat.
    assert.match(baseBody(".tabs"), /overflow-x:\s*auto/);
  });

  test("a tab keeps a width it can be read at, and the strip scrolls instead", () => {
    // A tab is the thing the user is aiming at, and its lead slot and its close
    // glyph do not shrink. Without a floor, a ten-tab strip in a narrow window
    // squeezed the glyph out of the tab it belonged to.
    assert.match(body(".tab"), /flex:\s*0 1 auto/);
    assert.match(body(".tab"), /min-width:\s*72px/);
  });

  test("the model id is ellipsised, not wrapped onto a second line", () => {
    // A model id has no spaces in it, so a long one broke at whatever character
    // fit and grew the chip two rows tall inside a 52px bar.
    assert.match(baseBody(".chip"), /white-space:\s*nowrap/);
    assert.match(baseBody(".chip"), /max-width:\s*240px/);
    assert.match(
      baseBody(".chip > span:first-child"),
      /text-overflow:\s*ellipsis/,
      "the unbroken id has nothing to stop it crowding the caption",
    );
  });

  test("the busy ring sits in a slot that every tab already has", () => {
    // Asserted in the stylesheet rather than only in the DOM: the slot is what
    // keeps the title still, and a slot with no width does not.
    assert.match(body(".tab-lead"), /width:\s*12px/);
    assert.match(body(".tab-lead"), /flex:\s*none/);

    // **And the slot is not the tab's leading inset.** It used to be -- 12px of
    // empty box that read as padding while the tab was idle -- and that held for
    // exactly as long as nothing was drawn in it. The busy ring fills the slot
    // it is centred in, so a slot standing in for padding leaves the ring with
    // no air on that side: measured, the slot's left edge and the tab's were
    // both at x=64, and the ring sat flush against the tab's own edge. The
    // arithmetic is `air + ring + gap = inset`, so a 0 here is the ring touching
    // the edge again.
    assert.match(
      body(".tab"),
      /padding:\s*0\s+8px\s+0\s+4px/,
      "the tab lost the air in front of the busy ring",
    );
  });

  test("no separator is drawn beside the tab you are in, or the one you are on", () => {
    // Asserted as the selector group, because a rule naming only the active tab
    // leaves the hairline on its right -- the one that touches the wash.
    for (const selector of [
      ".tab.is-active::before",
      ".tab:hover::before",
      ".tab.is-active + .tab::before",
      ".tab:hover + .tab::before",
    ]) {
      assert.match(body(selector), /opacity:\s*0/, `${selector} still draws its hairline`);
    }
    // The base hairline keeps a fade, so a pointer crossing the strip does not
    // make the dividers blink in and out.
    assert.match(body(".tab + .tab::before"), /transition:\s*opacity/);
  });
});

// --- Code mode's chrome ------------------------------------------------------
describe("the file header gives way instead of dropping the file name", () => {
  test("the path has a floor, because everything beside it is fixed", () => {
    // Measured in the running window, not reasoned about: at a 620px window the
    // code pane is 352px wide and this row overflowed by 55px. The path was the
    // only child that could shrink -- every chip, button and the theme control
    // is `flex: none` -- so it shrank to nothing, and the header drew
    // `css`, `read-only`, Edit, theme and Close with no file named anywhere.
    assert.match(body(".code-path"), /min-width:\s*64px/);
    assert.match(body(".code-path"), /text-overflow:\s*ellipsis/);
  });

  test("what it gives up is dropped in a container query, not a media query", () => {
    // A media query cannot answer this: the pane is the window minus the
    // explorer, so the same window is a different pane width in each mode. The
    // header has to be measured by the box it is drawn in.
    assert.match(body(".code-viewer"), /container-type:\s*inline-size/);

    // Every container query in the cascade, because the first one is not
    // necessarily this one: the settings page stacks its own split section
    // in a query of its own, and a first-match here would answer a question
    // about the viewer with the settings' rules.
    const queries = [
      ...SOURCE.matchAll(/@container \(max-width:\s*\d+px\)\s*\{([\s\S]*?)\n\}/g),
    ].map((m) => m[1]);
    const query = queries.find((block) => block.includes(".code-chip-lang"));
    assert.ok(query, "nothing in the stylesheet responds to the pane's own width");
    // The language first -- the extension already says it, and the footer
    // repeats it -- then the lock's *word*. Never the padlock itself, which is
    // what says the file is read-only when the word has gone.
    assert.match(query, /\.code-chip-lang\s*\{\s*display:\s*none/);
    assert.match(query, /\.code-lock-word\s*\{\s*display:\s*none/);
    assert.doesNotMatch(
      query,
      /\.code-lock-icon\s*\{\s*display:\s*none/,
      "the padlock is the half of that chip that has to survive",
    );
  });

  test("the explorer's head is rows, not a baseline in a fixed band", () => {
    // The complaint this answers: `align-items: baseline` inside a fixed 34px
    // band positions a line by its baseline, so a line in a taller box sits
    // high -- the section title and the path both drew against the band's top
    // edge, and the header read as text that had slipped upward.
    assert.match(body(".code-explorer-head"), /flex-direction:\s*column/);
    assert.doesNotMatch(body(".code-explorer-head"), /align-items:\s*baseline/);
  });
});

// --- the accent --------------------------------------------------------------
describe("the accent is the icon's blue; the brand carries it as one gradient", () => {
  test("the brand gradient is declared once, as a token, and nothing else gradients", () => {
    // The accent used to be a two-stop gradient, the "one flat blue" pass deleted
    // it, and it is back -- scoped to the *brand* (the first-run wordmark and the
    // mark's glow) rather than folded into `--accent`. Selection stays flat, so a
    // gradient selection wash (`--grad-wash`) is still absent rather than being a
    // second stop this reintroduces; `--wash` remains one pixel value.
    assert.match(SOURCE, /--grad-accent\s*:/, "the brand gradient token is gone");
    assert.doesNotMatch(SOURCE, /grad-wash/, "the selection wash is a gradient again");
  });

  test("the rules that wear it paint the token, so there is one blue", () => {
    // A hex written into a rule is the failure this guards: it looks identical
    // on the day it is written and it is the copy that keeps the old colour the
    // next time the accent moves. Every accent fill names `--accent` instead.
    // The rail's active indicator used to be in this list. It is the wash now,
    // along with the chosen budget preset: a solid accent belongs to a control
    // that does something when you press it, not to one that is already chosen,
    // and both of these were the latter wearing the former's ink.
    // `.empty h1` was here until the wordmark became the brand *gradient* -- a
    // `color` cannot be a gradient, so it paints `--grad-accent` through a
    // background clipped to the letters. It is asserted, with its per-stop
    // contrast, below; what is left here is the set of *solid* accent fills,
    // which is every control that acts.
    const wearers = [
      [".icon-btn.send-btn", body(".icon-btn.send-btn")],
      [".icon-btn.stop-btn", body(".icon-btn.stop-btn")],
      [".btn-accent", body(".btn-accent")],
    ];
    for (const [selector, rule] of wearers) {
      assert.match(
        rule,
        /(background|color):\s*var\(--accent\)/,
        `${selector} does not paint the accent token`,
      );
      assert.doesNotMatch(
        rule,
        /linear-gradient\(\s*(#|rgb)/,
        `${selector} writes its own fill instead of using the token`,
      );
    }
  });

  test("the accent clears the text floor on the field, because the wordmark is it", () => {
    // `.empty h1` is the wordmark in accent-coloured *text*, so the accent has
    // to be legible as text and not merely as a fill. 4.5:1 is that bar, and it
    // is the reason `--accent` is one ramp step up from the icon's own ground.
    const ratio = contrast(tokens("accent")!, tokens("bg")!);
    assert.ok(
      ratio >= 4.5,
      `--accent ${tokens("accent")} is ${ratio.toFixed(2)}:1 on --bg, under the text floor`,
    );
  });

  test("the wordmark is that blue read through the letters, and every stop clears the text floor", () => {
    // The one place the accent is a gradient: the wordmark is *text*, and `color`
    // cannot be a gradient, so the ramp goes in the background and is clipped to
    // the glyph (`background-clip: text`, transparent fill). It is the pattern
    // this file used to forbid, scoped to one brand line -- and it still has to be
    // legible, which is a property of *each* stop, not of the pair.
    const wordmark = body(".empty h1");
    assert.match(wordmark, /background:\s*var\(--grad-accent\)/);
    assert.match(wordmark, /(-webkit-)?background-clip:\s*text/);
    assert.match(
      wordmark,
      /(-webkit-)?text-fill-color:\s*transparent|color:\s*transparent/,
    );

    // Two stops, both held to the *text* floor rather than the graphic one,
    // because a gradient that is legible at one end and not the other is a
    // gradient nobody can read.
    const grad = tokenRaw("grad-accent")!;
    assert.match(grad, /^linear-gradient\(/);
    const stops = [...grad.matchAll(/#[0-9a-f]{6}/gi)].map((m) => m[0]);
    assert.equal(stops.length, 2, "the brand gradient is not a two-stop ramp");
    const bg = tokens("bg")!;
    for (const stop of stops) {
      const ratio = contrast(stop, bg);
      assert.ok(
        ratio >= 4.5,
        `${stop} is ${ratio.toFixed(2)}:1 on --bg, under the text floor`,
      );
    }
  });

  test("the mark's glow is the accent, through a token and not a literal", () => {
    // The glyph stays flat `--accent` (asserted in the first-run suite below); the
    // glow around it is that blue in a drop-shadow, referenced through
    // `--accent-glow` so the copy cannot drift from the fill -- the same "no
    // second writing of the colour" rule the fills follow.
    assert.match(body(".empty-mark"), /filter:\s*drop-shadow\([^;]*var\(--accent-glow\)/);
    const glow = flatMasked("accent-glow");
    assert.ok(glow, "--accent-glow is not a masked rgb() colour");
    assert.ok(glow.alpha > 0 && glow.alpha <= 0.5, `the glow is at alpha ${glow.alpha}`);
  });

  test("the selection wash is the accent at low alpha", () => {
    // The wash carries the accent without *being* the accent -- the selected
    // conversation, the open tab. Flat, so a selected row is one pixel value
    // rather than a gradient's two; the alpha stays bounded because the row's
    // ink sits on top of it, and the ceiling it is really held to is the
    // timestamp's contrast rather than this number.
    const wash = flatMasked("wash");
    assert.ok(wash, "--wash is not a flat rgb() colour");
    assert.ok(
      wash.alpha > 0 && wash.alpha <= 0.35,
      `the wash is at alpha ${wash.alpha}, which stops being a wash`,
    );
    assert.equal(
      wash.hex.toLowerCase(),
      tokens("accent")!.toLowerCase(),
      "the wash is not the accent's own value",
    );
  });

  test("the ink on a washed row clears the floor on the pixel it is painted on", () => {
    // `--fg` on the title and `--fg-dim` on the timestamp, measured against the
    // *composited* wash rather than against `--bg`, because that is the surface
    // they are drawn on. Alpha compositing is not linear in the colours, so the
    // composite is computed rather than reasoned about.
    const wash = flatMasked("wash")!;
    const surface = over(wash.hex, wash.alpha, tokens("bg")!);
    for (const ink of ["fg", "fg-dim"]) {
      const ratio = contrast(tokens(ink)!, surface);
      assert.ok(
        ratio >= 4.5,
        `--${ink} is ${ratio.toFixed(2)}:1 on the composited wash (${surface}), `
          + "under the floor for the text that wears it",
      );
    }
  });

  test("a washed row is told from a hovered one by lightness, not by hue", () => {
    // The test the white accent forced to change its mind. It used to assert
    // the opposite: that the wash carried chroma and `--hover` did not, which
    // is what separated a selected row from a hovered one -- because composited
    // over `--bg` the two are about 1.1:1 apart and no contrast check could
    // tell them apart.
    //
    // An achromatic wash cannot do that, so the separation is the lightness the
    // old comment explicitly dismissed. It is small on purpose and cannot be
    // larger: `--fg-dim` has to clear 4.5:1 on the composited pixel, which caps
    // the wash at #3c3c3c against `--hover`'s #383838 -- 1.06:1. This asserts
    // the direction; the floor that sets the size is asserted immediately below,
    // so raising the alpha to widen this gap fails there rather than here.
    assert.equal(chroma(tokens("hover")!), 0, "--hover is supposed to be achromatic");
    const wash = flatMasked("wash")!;
    assert.equal(chroma(wash.hex), 0, "the wash is supposed to be achromatic now");
    const painted = over(wash.hex, wash.alpha, tokens("bg")!);
    assert.ok(
      luminance(painted) > luminance(tokens("hover")!),
      `the composited wash (${painted}) does not sit above --hover (${tokens("hover")})`,
    );
  });
});

// --- the bar's left corner ---------------------------------------------------
describe("the title bar is indented past the left column", () => {
  test("the mark takes the rail's column, so the tab still starts past it", () => {
    // The indent used to be the bar's own padding, and it is the mark's width
    // now. The two are equivalent: `--rail-w` of mark plus the bar's own 8px gap
    // puts the conversation tab exactly where the padding used to -- 8px past
    // the boundary the content below the bar is split by, which is where the
    // reference puts its tab. The caption stays hard against the right edge, so
    // the bar's two ends are deliberately not symmetrical.
    //
    // Asserted as the three parts rather than as one computed offset, because
    // the arrangement is what matters: a `padding` that came back alongside the
    // mark would double the indent, and that reads as "almost aligned" rather
    // than as a bug.
    assert.match(baseBody(".topbar"), /padding:\s*0;/);
    assert.match(baseBody(".topbar"), /gap:\s*8px/);
    assert.match(baseBody(".topbar-mark"), /width:\s*var\(--rail-w\)/);
  });

  test("and the indent does NOT follow the conversation panel", () => {
    // This used to be the other way round: `.app.rail-open .topbar` indented by
    // `--rail-w-expanded` so the tab moved right with the widened column.
    //
    // Now it must not, and the reason is the panel's position rather than a
    // preference. The panel is anchored *below* the bar (`top:
    // var(--topbar-h)`), the same as the Files panel and for the same reason --
    // a panel that started at y=0 would cover the caption buttons and take the
    // drag region with them. So the bar's left region is always exactly the
    // rail, open panel or not, and an indent that tracked the panel would put
    // the tab 255px right of the panel's own left edge with nothing under it.
    assert.doesNotMatch(SOURCE, /\.app\.rail-open \.topbar/);
    assert.match(body(".chatlist"), /top:\s*var\(--topbar-h\)/);
  });
});

// --- the conversation panel is an overlay -----------------------------------
describe("the conversation list floats over the transcript", () => {
  test("it is absolutely positioned, not a grid item", () => {
    // The change that makes it animatable. A column's width is a grid track,
    // and a grid track cannot be transitioned -- it snaps, and everything
    // inside it re-wraps on the way. Taking the panel out of flow means the
    // only thing that moves is a `transform`.
    assert.match(body(".chatlist"), /position:\s*absolute/);
    // x=0, over the rail: the rail is the collapsed state of one sidebar and
    // this panel is the expanded state, so the panel covers the strip rather
    // than sitting to its right. See the panel's own comment.
    assert.match(body(".chatlist"), /left:\s*0\b/);
    // And it stops on the status bar rather than at the window's edge. It was
    // `bottom: 0`, which painted this panel's footer across the bar's left
    // 224px and hid the connection state underneath it. Read through the token
    // so the panel and the bar cannot disagree about how tall the bar is.
    assert.match(body(".chatlist"), /bottom:\s*var\(--statusbar-h\)/);
    // `absolute` with no `grid-column`/`grid-row`: those would be inert, and
    // inert declarations are how a rule ends up documenting an arrangement that
    // stopped existing.
    assert.doesNotMatch(body(".chatlist"), /grid-/);
  });

  test("the panel and its scrim stop above the status bar", () => {
    // The bug this closes, and it was measured in the running window rather
    // than reasoned about: the panel ran to `bottom: 0`, so with the sidebar
    // open its own footer sat on the bar's row. `elementsFromPoint` at the
    // bar's left corner returned `chatlist-foot` first with `statusbar-state`
    // underneath it, so the bar's left 224px -- the connection state -- was
    // simply not visible.
    //
    // Both overlays read the token the bar's own height is declared with, so a
    // future change to that height moves all three together rather than leaving
    // one of them behind. The scrim's exact inset is pinned in its own suite
    // below, which is the place that knows why it stops at the rail.
    assert.match(body(".chatlist"), /bottom:\s*var\(--statusbar-h\)/);
    // And the bar's height is that token, not a second copy of the number.
    // `baseBody` and not `body`: the narrow-window block for `.statusbar` comes
    // later in the cascade and has no height in it, which is what `body` would
    // have read.
    assert.match(baseBody(".statusbar"), /height:\s*var\(--statusbar-h\)/);
    assert.match(STYLESHEET, /--statusbar-h:\s*26px/);
  });

  test("and it is the reference's width, pinned to the rail's right edge", () => {
    // Widened from the reference's 260px in the restructure. A roomier sidebar
    // -- a 40px "New chat" button and 12px row insets -- needs the extra width
    // to keep a title off its ellipsis, and the list is the one surface where
    // the text is the content. Pinned by value so a future tweak moves it
    // deliberately rather than by drift.
    assert.match(STYLESHEET, /--list-w:\s*288px/);
    assert.match(body(".chatlist"), /width:\s*var\(--list-w\)/);
  });

  test("it slides, from the edge it is anchored to", () => {
    // A translation, not a width, and in from the *left* because that is the
    // edge it hangs off: a panel appearing 20px to the left of where it belongs
    // would look like it were escaping from under the rail.
    assert.match(body('.chatlist[data-state="open"]'), /animation:\s*slide-in-left/);
    assert.match(
      body('.chatlist[data-state="closed"]'),
      /animation:\s*slide-out-left/,
    );
    // 16px, the same distance and for the same reason the files panel uses it.
    const keyframes = /@keyframes slide-in-left\s*\{([^}]*)\}/.exec(STYLESHEET);
    assert.ok(keyframes, "the panel has no enter animation");
    assert.match(keyframes[1], /translateX\(-16px\)/);
  });

  test("a closing panel is inert, so the next click is not eaten", () => {
    // It is still on screen for the length of the exit. 110ms of a 255px column
    // of live click targets is a region where the next click goes nowhere.
    assert.match(body('.chatlist[data-state="closed"]'), /pointer-events:\s*none/);
  });

  test("it has a shadow, because depth is what says 'over' rather than 'beside'", () => {
    // On a near-black UI a panel with no shadow and no hairline reads as a
    // column with a misplaced edge. The Files panel solves the same problem
    // with a scrim; a shadow is the right answer for a panel the user keeps
    // open, since a scrim would dim the transcript behind it continuously.
    assert.match(body(".chatlist"), /box-shadow:/);
  });
});

// --- the rail strip ---------------------------------------------------------
describe("the rail is a full-height strip down the left edge", () => {
  test("the rail itself paints --chrome, over its own full height", () => {
    // Measured in a full-DPI capture of the reference: 52px of #292b2a running
    // from the title bar to the bottom of the window, with 255px of #1c1d1c
    // beside it. That strip is the single clearest thing separating the two
    // apps at a glance, and it is 7% of the reference's pixels.
    //
    // Painted on `.rail` now rather than on a parent `.sidecol` column that the
    // list then painted --bg back over. The rail *is* column 1 -- the list has
    // been moved out to an overlay -- so there is nothing left to paint over it,
    // and the old arrangement had a way to go wrong: a strip whose background
    // belonged to a container sized by its contents stops at the last icon.
    // The rail is the window's edge and it is frosted now, like the title bar
    // and the status bar -- the three are one material (`--glass-chrome`). See
    // the glass block in tokens.css; the fill is still a token this line can
    // name, rather than a literal it cannot see.
    assert.match(body(".rail"), /background:\s*var\(--glass-chrome\)/);
    // The conversation panel is frosted now rather than painted --bg, so the
    // transcript behind it reaches the eye through the blur. Asserted against
    // the glass token, so the frosted fill is still the application's own value
    // and not a literal this line cannot see.
    assert.match(body(".chatlist"), /background:\s*var\(--glass-panel\)/);
    assert.match(body(".rail"), /height:\s*100%/);
  });

  test("it is a column of its own, at a width nothing else can change", () => {
    // `grid-column: 1` on the rail itself rather than on a wrapper, so the grid
    // track and the element that fills it cannot drift apart -- which is what
    // happened when the rail overflowed a track pinned to the closed width.
    assert.match(body(".rail"), /grid-column:\s*1\b/);
    assert.match(body(".rail"), /width:\s*var\(--rail-w\)/);
    // The list must still be allowed to shrink: a flex item's automatic minimum
    // size is its content, so one long conversation title would otherwise widen
    // the panel past its fixed width.
    assert.match(body(".chatlist"), /min-width:\s*0\b/);
  });

  test("the rail keeps its width at every sidebar state", () => {
    // The rail used to widen to --rail-w-expanded and grow text labels beside
    // its icons. The reference never does that -- its rail is a strip of icons
    // and the titles live in the panel next to it -- so there is no expanded
    // rail rule left to override, and asserting its absence is the point: a
    // rule that would widen it again is exactly what would break the match.
    assert.doesNotMatch(SOURCE, /\.rail\.rail-expanded|\.rail-label/);
    assert.match(body(".rail"), /width:\s*var\(--rail-w\)/);
  });

  test("and there is no width transition on it, because it never changes", () => {
    // Asserted because the absence is the point and a transition here would be
    // motion with no state change behind it: the rail is 52px whether or not the
    // panel is open, so there is nothing to animate and `transition: width`
    // would be a promise the layout cannot keep.
    assert.doesNotMatch(body(".rail"), /transition/);
  });

  test("the update mark hangs from the top, clear of where the sidebar stops", () => {
    // The rail runs to the window's bottom edge and its gear sits 14px above
    // that, while the sidebar -- which covers the rail while it is open -- stops
    // 26px above it. So the rail button's bottom 12px is on screen even with the
    // panel over the rail, and a mark anchored to the *bottom* corner leaked out
    // below the panel: measured in the running app, the dot's box ended 6px past
    // the sidebar's edge and its ring 8px, which is a stray white half-disc
    // sitting on the status bar with no gear around it.
    //
    // Asserted as the *anchor* rather than as a pixel offset: what has to stay
    // true is that the mark hangs from the top of its target, which is the half
    // the sidebar cannot uncover. A `bottom` here is the leak coming back,
    // whatever number is beside it.
    const dot = body(".rail-dot");
    assert.match(dot, /top:\s*\d+px/);
    assert.doesNotMatch(dot, /bottom:/);
  });
});

// --- the measure ------------------------------------------------------------
describe("the composer and the transcript share one measure", () => {
  test("and they share it by construction, not by agreement", () => {
    // This is the invariant, and it is the reason the number is a token.
    //
    // It did not hold. The transcript column was 860px and the composer 720px,
    // so the field sat inboard of the messages it was replying to, and nothing
    // in either file said whether that was the design or an accident. A test
    // comparing two numbers would only have frozen the accident; one token
    // cannot drift, because there is no second number to drift from.
    //
    // Asserted on the *token*, so changing the measure is one edit and does not
    // invalidate a test that only ever claimed the two are the same.


    for (const selector of [".composer-inner", ".transcript-inner", ".hint", ".banner"]) {
      assert.match(
        body(selector),
        /max-width:\s*var\(--measure\)/,
        `${selector} does not take the shared measure`,
      );
    }
    const measure = new RegExp("--measure: *([\\d.]+)px", "i").exec(STYLESHEET)?.[1];
    assert.ok(measure, "--measure is not declared");
  });

  test("and the text inside it starts on one edge, the composer's included", () => {
    // The half of the invariant the box could not carry.
    //
    // Sharing `--measure` was not enough, and that is the whole reason this test
    // exists. The transcript spent 28px of its 680 on padding while the composer
    // spent 19, so the messages were 624px wide inside the field that replied to
    // them: same centre, different edges, and both numbers looked deliberate.
    //
    // So the inset is a token too, and the composer is written *from* it: its
    // field and its control row subtract their own 1px border from the token,
    // which is the only reason the composer's text and the far side of that
    // border agree. That subtraction hard-codes the border, so the border is
    // pinned here -- a 2px border would put the composer's text one pixel right
    // of every other line and nothing else would notice.
    const border = parseFloat(/border:\s*([\d.]+)px\s+solid/.exec(body(".composer-inner"))![1]);
    assert.equal(border, 1, "the composer's border is not the 1px the inset subtracts");
    const measure = parseFloat(
      new RegExp("--measure: *([\\d.]+)px", "i").exec(STYLESHEET)![1],
    );
    const inset = parseFloat(
      new RegExp("--column-inset: *([\\d.]+)px", "i").exec(STYLESHEET)![1],
    );
    // A band, for the same reason the measure has one: under half a control's
    // own inset a line touches the column's edge, and over 40px the column has
    // paid its whole width for air on both sides. It also catches the one
    // failure a token cannot: a typo in the token itself, which every rule would
    // then follow faithfully.
    assert.ok(inset >= 8, `--column-inset ${inset}px puts text against the column's edge`);
    assert.ok(inset <= 40, `--column-inset ${inset}px is air rather than an inset`);
    assert.ok(inset * 2 < measure, `--column-inset ${inset}px leaves no column to inset from`);
    // And every rule that puts a line of text in the column has to take it: the
    // messages, the field itself and its control row, the hint under it, the
    // banner above it, and the log strip. The two inside the composer subtract
    // the border they sit behind; the rest take the whole inset.
    for (const selector of [
      ".transcript-inner",
      ".hint",
      ".banner",
      ".logstrip",
    ]) {
      assert.match(
        body(selector),
        /var\(--column-inset\)/,
        `${selector} does not take the column's inset`,
      );
    }
    for (const selector of [".composer textarea", ".composer-row"]) {
      assert.match(
        body(selector),
        /calc\(var\(--column-inset\) - 1px\)/,
        `${selector} does not hold the column's line behind the composer's border`,
      );
    }
  });

  test("and the transcript is centred on the composer's axis, scrollbar or not", () => {
    // The column's centre is a fact about the window, not about whether this
    // conversation happens to overflow. `.transcript` is the only scroller in
    // the lower half, and its scrollbar took 10px out of its own box: the
    // messages sat 5px left of the field below them, and -- worse than the
    // offset -- they *moved* there the moment a conversation grew past the
    // window. `both-edges` reserves the gutter on both sides, so the two boxes
    // share one centre at every scroll position.
    assert.match(body(".transcript"), /scrollbar-gutter:\s*stable\s+both-edges/);
  });

  test("and the two boxes are one box, at every width rather than at the widest", () => {
    // The half of this that only shows up in a narrow window.
    //
    // Measured before this: at 1280 the transcript's inner box and the
    // composer's inner box were both 760px at x=292. At 760 the window they were
    // 676 at x=74 against 632 at x=96 -- 22px apart on the left edge and 44px on
    // the width. Above 888px both boxes hit the `--measure` cap and the
    // difference vanished; below it, every width had its own. The cause was one
    // column derived two ways: `.transcript` holds a `--scrollbar` gutter on
    // each edge and takes no padding, while `.composer` takes 32px of padding
    // and has no scroller.
    //
    // So the air is a token and the composer holds the air *plus* the gutter the
    // transcript reserves. 22 + 10 is the 32 this surface already had, which is
    // why the fix moves nothing above 888 and fixes everything below it.
    assert.match(
      STYLESHEET,
      /--column-edge:\s*calc\(var\(--column-air\) \+ var\(--scrollbar\)\)/,
    );
    assert.match(body(".transcript"), /padding:\s*12px var\(--column-air\) 4px/);
    assert.match(body(".composer"), /padding:\s*0 var\(--column-edge\) 16px/);
    // The banner and the log strip are the other two occupants of that column,
    // and they are children of `.main` with no padding of their own -- which is
    // what let them span the full width of a narrow window while the field below
    // them did not. They subtract the same edge from the width instead.
    for (const selector of [".banner", ".logstrip"]) {
      assert.match(
        body(selector),
        /width:\s*calc\(100% - 2 \* var\(--column-edge\)\)/,
        `${selector} is not the width of the column it sits in`,
      );
    }
  });

  test("and a message is as wide as the field it replies to", () => {
    // Where the shared measure was still defeated by a literal.
    //
    // `.bubble` capped at `min(680px, 84%)`. 680 is the value `--measure` had
    // *before* it moved to 760 -- a stale copy of a token -- and `84%` resolved
    // against the transcript's content box, which is a second definition of the
    // reading column in a unit no token can reach. Measured at 1280: the prose
    // ran 224..830.5, 606.5px wide, inside a 722px column under a 760px field
    // whose own text starts on the same pixel. The window's stated invariant --
    // the composer is as wide as the messages it replies to -- held for neither.
    assert.doesNotMatch(body(".bubble"), /min\(\s*[\d.]+px\s*,\s*[\d.]+%\s*\)/);
    assert.match(body(".bubble"), /max-width:\s*100%/);
    // One cap is left, on the user's bubble, because that one is a chip rather
    // than a column -- and it is written so it can never exceed the column it
    // sits in, whatever the window does.
    assert.match(body(".bubble-user"), /max-width:\s*min\([\d.]+px, 100%\)/);
  });

  test("and it is narrow enough to be read, wide enough to be a field", () => {
    // A measure has two failure modes and this sits between them: under about
    // 560px the transcript stops holding a code block, over about 760px a line
    // of 13px prose runs past 90 characters and the eye loses the start of the
    // next one. Asserted as a band, because either edge of it is a real defect
    // and neither edge is a constant.
    const measure = parseFloat(new RegExp("--measure: *([\\d.]+)px", "i").exec(STYLESHEET)![1]);
    assert.ok(measure >= 560, `--measure ${measure}px cannot hold a code block`);
    assert.ok(measure <= 760, `--measure ${measure}px is too wide to read across`);
  });

  test("and its field is one step above the field it sits on", () => {
    // A recessed panel has to be readable *as* a panel, which is a claim about
    // depth rather than about a colour. Asserted against the depth ladder: the
    // composer's field must be above `--bg` and below the controls that sit on
    // it. Pinning #222423 here would have meant asserting a colour nobody can
    // argue with and everybody can edit.
    const lift = (name: string) => {
      const hex = new RegExp(`--${name}: *(#[0-9a-f]{6})`, "i").exec(STYLESHEET)![1];
      const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16));
      return 0.2126 * r + 0.7152 * g + 0.0722 * b;
    };
    assert.ok(lift("surface") > lift("bg"), "--surface is not above --bg");
    assert.ok(lift("surface") < lift("input"), "--surface is not below --input");
    assert.match(body(".composer-inner"), /background:\s*var\(--glass-field\)/);
  });

  test("and the field is one field in every mode", () => {
    // Chat, Plan and Skills used to tint the *textarea* to say "this mode does
    // not write": `color-mix(in srgb, var(--input) 70%, var(--bg))`, an opaque
    // grey one step *down* from the glass around it. The fill was the
    // textarea's rather than the field's, so it stopped at the control row --
    // and those three modes drew a grey typing area stacked on a glass control
    // row, which made the three quietest modes the loudest composer in the
    // window. Measured in a browser in Plan, before this: the textarea computed
    // to `color(srgb 0.148627 0.148627 0.148627)` where Build's computed to
    // `rgba(0, 0, 0, 0)`.
    //
    // The comment in composer.css records why the fill is gone; this asserts the
    // *absence*, which is the half a stray rule could undo quietly. It reads
    // SOURCE rather than STYLESHEET because the comment explaining the removal
    // names the selector it removed.
    assert.match(body(".composer textarea"), /background:\s*transparent/);
    assert.doesNotMatch(
      SOURCE,
      /textarea\.is-readonly/,
      "a read-only mode repaints the field again",
    );
    // Which is also why the field must go on *not* clipping its children: the
    // `/` menu hangs out of this box (see `.skills-menu`), so an
    // `overflow: hidden` here would cut the menu off at the field's own top edge.
    assert.doesNotMatch(body(".composer-inner"), /overflow:\s*(hidden|clip)/);
  });
});

// --- keyboard focus ---------------------------------------------------------
// --- motion coverage ---------------------------------------------------------
/**
 * Every state change that can animate has something to animate it.
 *
 * This began as an audit of the whole stylesheet, and it found 38 state rules
 * changing a visible property with nothing to interpolate it: the conversation
 * list, the model picker's rows, the file tree, the permission menu and every
 * form field snapped where the rest of the window faded over 110ms.
 *
 * The defect is invisible to a rule-by-rule read, which is why it survived: the
 * missing transition is not in the rule that is wrong -- it is absent from the
 * rule that should have carried it. So it is asserted over the cascade at once,
 * the way the colour-and-scale tests above are.
 *
 * A transition counts for a state when two things hold: its *subject* (the last
 * compound of its selector, states removed) is the same element or a subset of
 * the one changing, and the properties it lists cover everything that changes.
 * So a transition on `.icon-btn` covers `.icon-btn.send-btn`, and one on
 * `.composer-inner` deliberately does *not* cover the textarea inside it -- an
 * inherited transition does not animate a descendant.
 */
describe("every state change has a transition to animate it", () => {
  /** What is worth interpolating. `font-weight` and `text-decoration` are
   *  absent on purpose: neither animates reliably, so requiring a transition
   *  for them would be requiring a lie. */
  const ANIMATABLE = ["background", "background-color", "color", "border-color", "transform", "opacity", "filter", "height"];
  /** What each shorthand covers, so `background` counts for `background-color`. */
  const COVERS: Record<string, string[]> = { background: ["background-color"], border: ["border-color"] };

  const STATES = /:(hover|active|focus|focus-visible)\b|\.is-active|\[data-/;

  /**
   * The element a selector's last compound names: its tag and its classes, with
   * states and attributes removed.
   *
   * The tag is in here because `.rowmenu button` and `.rowmenu button:hover` are
   * the same element and carry no class at all -- a classes-only reading gives
   * both an empty set and matches nothing.
   */
  function subject(selector: string): Set<string> {
    const last = selector.split(/[\s>+~]+/).filter(Boolean).pop() ?? "";
    const out = new Set<string>();
    const tag = last.match(/^([a-z][\w-]*)/);
    if (tag) out.add(tag[1]);
    for (const m of last.matchAll(/\.([A-Za-z][\w-]*)/g)) out.add(m[1]);
    return out;
  }

  /** The properties every `transition` in a body lists, shorthands expanded. */
  function transitioned(body: string): Set<string> {
    const out = new Set<string>();
    for (const match of body.matchAll(/transition\s*:\s*([^;]+);/g)) {
      for (const part of match[1].split(",")) {
        const first = part.trim().split(/\s+/)[0];
        if (!first) continue;
        out.add(first);
        for (const also of COVERS[first] ?? []) out.add(also);
      }
    }
    return out;
  }

  function changed(body: string): Set<string> {
    const out = new Set<string>();
    for (const prop of ANIMATABLE) {
      if (new RegExp(`(^|[\\s;])${prop}\\s*:`).test(body)) out.add(prop);
    }
    return out;
  }

  const isSubset = (a: Set<string>, b: Set<string>) =>
    a.size > 0 && [...a].every((x) => b.has(x));

  test("no interactive state repaints itself in a single frame", () => {
    // A state listed here is deliberately instant, and adding one is a claim
    // that has to be argued beside it.
    const INSTANT_ON_PURPOSE = [
      // The stylesheet cannot see this one: the element is rendered as
      // `class="btn btn-accent"`, so the transition that animates it is on
      // `.btn` -- which lists both `background` and `filter` now. A CSS-only
      // reading sees `.btn-accent` and no transition anywhere.
      ".btn-accent:hover:not(:disabled)",
      // A native scrollbar part. Chromium paints it, and it takes no
      // transition from a stylesheet, so requiring one would be requiring a
      // rule that does nothing.
      "::-webkit-scrollbar-thumb:hover",
      // A dock becoming an overlay is a structural state, not a property fade:
      // the panel stops being a grid track and starts being a sheet, and a
      // transition on `height`/`background` would animate a reflow. The rule
      // is written for the state, and the plan's rule is that a dock toggle
      // reflows once, instantly.
      '.app > .chatlist[data-docked="true"]',
      // The rail leaving the grid at 900 is a breakpoint, not a hover. Height
      // 100% -> auto is how it stops stretching a column that is no longer
      // there; there is no in-between layout to interpolate. Trajectory is the
      // same rule for the same reason now that it carries the same dock.
      '.app[data-mode="agent"] .rail',
      '.app[data-mode="trajectory"] .rail',
      // The overlay form is displayed, not restyled: `display: none` to `flex`
      // has no frame in between, so the background arrives with the panel.
      // Phase 6 owns the reveal itself.
      '.contextdock[data-docked="false"][data-state="open"] .context-panel',
      // The spine's line, which is *drawn or not drawn* rather than restyled:
      // `data-spine` is a property of the run the walker produced, set once when
      // the message is rendered. A run of one call is not a state the line
      // transitions out of -- it is a run the line was never drawn for.
      '.tools[data-spine="true"]::before',
      // The same shape of thing in the expanded row: `data-tone="bad"` marks the
      // block as an error at the moment it is rendered. There is no frame in
      // which it is not an error, so there is nothing to ease.
      '.tool-block[data-tone="bad"] .tool-pre',
    ];

    const gaps: string[] = [];
    for (const rule of RULES) {
      for (const selector of rule.selectors) {
        if (!STATES.test(selector)) continue;
        // A disabled control has no state to ease into; it is inert.
        // A control that is switched off has no state to ease into: both a
        // plain `:disabled` rule and a `:disabled:hover` one say "do not
        // respond", and both are inert by design.
        if (selector.includes(":disabled")) continue;
        const wanted = changed(rule.body);
        if (wanted.size === 0) continue;
        if (INSTANT_ON_PURPOSE.includes(selector)) continue;
        const mine = subject(selector);
        const covered = RULES.some(
          (other) =>
            other.selectors.some((s) => isSubset(subject(s), mine)) &&
            [...wanted].every((prop) => transitioned(other.body).has(prop)),
        );
        if (!covered) gaps.push(`${selector} -> ${[...wanted].sort().join(", ")}`);
      }
    }
    assert.deepEqual(
      [...new Set(gaps)].sort(),
      [],
      "a state changes a visible property with nothing to animate it",
    );
  });
});

describe("a keyboard user can see where they are", () => {
  test("the ring is drawn on every focusable thing, once", () => {
    // Until this there was no rule anywhere in the file that set an `outline`,
    // and five that set it to `none`, so focus fell through to the UA default:
    // 1px #101010 on a #1a1a1a field, measured at 1.13:1. On nine controls in
    // ten, focusing changed nothing a person could see.
    //
    // One rule, not one per control: a ring that has to be re-declared for
    // every new button is a ring that the next button will not have.
    const rules = RULES.filter((r) => r.selectors.includes(":focus-visible"));
    assert.equal(rules.length, 1, `there are ${rules.length} :focus-visible rules, not 1`);
    assert.match(rules[0].body, /outline:\s*2px solid var\(--focus-ring\)/);
    // Positive and load bearing: at a negative offset the ring would sit on the
    // control's own fill and vanish on exactly the buttons that need marking.
    assert.match(rules[0].body, /outline-offset:\s*2px/);
  });

  test("nothing suppresses it but the one field that says it its own way", () => {
    // The five `outline: none` that are gone existed only because there was no
    // ring to show, and any one of them back would out-specify a bare
    // `:focus-visible` and kill the ring on that control while every other
    // control in the app still showed it.
    //
    // One exception, and it is not a control: the composer's text field. **A text
    // input matches `:focus-visible` on a *mouse* click** -- the browser's
    // heuristic, not this app's -- so the field drew the ring on every click, and
    // clicking a chat in the sidebar focuses it. The card already says it is
    // focused by taking its own border to `--accent`, so the two were two blue
    // boxes saying one thing: measured at 758x63, `outline-offset: 2px`.
    //
    // Asserted as the exact set rather than as a count, so a second suppression
    // cannot ride in behind this one.
    const suppressions = RULES.filter((r) => /outline:\s*none/.test(r.body));
    assert.deepEqual(
      suppressions.map((r) => r.selectors.join(", ")),
      [".composer textarea:focus-visible"],
      "something other than the composer's field suppresses the focus ring",
    );
    // And that field has something else to say, so the suppression is not the
    // whole treatment -- a field that suppressed the ring and said nothing would
    // be the original bug with the colours swapped.
    assert.match(
      body(".composer-inner:focus-within"),
      /border-color:\s*var\(--accent\)/,
    );
  });

  test("and it is legible on every surface it can land on", () => {
    // The four surfaces a focused control can sit against: the field, the
    // chrome the rail and title bar are painted, a raised card, and the
    // selected chip. 3:1 is the non-text bar, and the ring is non-text.
    //
    // `--focus-ring` is resolved through whatever it points at, so this holds
    // for the token the rule actually reads and not for a token it happens to
    // share a name with.
    const ring = resolveHex("focus-ring");
    assert.ok(ring, "--focus-ring does not resolve to a colour");
    for (const surface of ["bg", "chrome", "raised", "chip"]) {
      const r = contrast(ring, tokens(surface)!);
      assert.ok(
        r >= 3,
        `--focus-ring ${ring} is ${r.toFixed(2)}:1 on --${surface}, under 3:1`,
      );
    }
    // And it must not be the colour of the control it rings: `--accent` is the
    // fill of the send button, the accent button and the mode pills, so a ring
    // in it disappears into the thing it is marking.
    assert.notEqual(
      ring,
      tokens("accent"),
      "the focus ring is the accent, which is the fill of the buttons it marks",
    );
  });
});

// --- narrow-window layout ---------------------------------------------------
describe("compact windows keep the dashboard and status chrome in bounds", () => {
  test("the usage header wraps and its period picker can scroll locally", () => {
    // Previously the picker, title and exit button shared one unwrapped row:
    // at 520px the Usage view's content measured 503px inside a 456px column,
    // so the Back button was clipped at the right edge. The header now wraps,
    // and the period group is the only locally scrollable control.
    assert.match(baseBody(".usage-head"), /flex-wrap:\s*wrap/);
    assert.match(mediaBodies("max-width: 420px"), /\.usage-periods\s*\{[^}]*overflow-x:\s*auto/);
    assert.match(mediaBodies("max-width: 420px"), /\.usage-periods\s*\{[^}]*min-width:\s*0/);
    assert.match(mediaBodies("max-width: 420px"), /\.usage-periods\s*\{[^}]*flex:\s*1\s+1\s+0/);
    assert.match(STYLESHEET, /@media\s*\(max-width:\s*420px\)/);
    // The panel's own inset is the app's panel inset and not a clamp. A
    // `clamp(16px, 2.5vw, 32px)` made this the only surface in the window whose
    // content edge moved as the window was resized -- measured at 27.6px in a
    // 1106px window, 16px in a 760px one, against chat list and Files panes that
    // stayed put at both.
    assert.match(baseBody(".usage"), /padding:\s*18px var\(--pad-panel\) 24px/);
    assert.match(baseBody(".usage-account-figure dt"), /-webkit-line-clamp:\s*2/);
  });

  test("the footer gives up secondary status before logs", () => {
    // Provider/model and sandbox details can be recovered from Settings; the
    // Logs action must remain visible rather than widening or clipping the bar.
    assert.match(baseBody(".statusbar"), /min-width:\s*0/);
    assert.match(baseBody(".statusbar-logs"), /flex:\s*none/);
    assert.match(STYLESHEET, /@media\s*\(max-width:\s*560px\)/);
    const narrow = mediaBodies("max-width: 560px");
    /*
     * Named, not counted. The rule this replaces hid `span:nth-of-type(2)` and
     * `span:nth-of-type(5)`, and those two indices are not stable: when no
     * provider is bound the row swaps its provider span for a `linkish` button,
     * the spans renumber, and the same selectors then hide a different pair of
     * things -- in exactly the state where the bar is telling the user what to
     * do about it. What goes is the word beside the dot (the dot says it) and
     * the sandbox (one dialog away); the provider, the model and Logs stay.
     */
    assert.match(narrow, /\.statusbar > \.statusbar-state[\s\S]*display:\s*none/);
    assert.match(narrow, /\.statusbar > \.statusbar-sandbox[\s\S]*display:\s*none/);
    assert.match(narrow, /\.statusbar > \.sep[\s\S]*display:\s*none/);
    assert.doesNotMatch(narrow, /nth-of-type/, "the footer is hidden by position again");
  });

  test("the title-bar tab strip yields width to its actual controls", () => {
    // The strip may scroll inside itself, but the mode switch, model control and
    // native window caption must not be pushed outside the viewport.
    assert.match(baseBody(".tabs"), /min-width:\s*0/);
    const narrow = mediaBody("max-width: 560px");
    assert.match(narrow, /\.win-btn\s*\{[^}]*width:\s*32px/);
    assert.match(narrow, /\.topbar-mark\s*\{[^}]*width:\s*40px/);
    assert.match(narrow, /\.tabs\s*\{[^}]*max-width:\s*12%/);
    assert.match(STYLESHEET, /@media\s*\(max-width:\s*420px\)/);
    assert.match(baseBody(".tabs"), /max-width:\s*min\(60%,\s*360px\)/);
  });
});

// --- one ladder, one inset ------------------------------------------------
/*
 * The consistency the app was missing, asserted as properties rather than as
 * values.
 *
 * Both of these were "each surface decided for itself" failures: six media
 * query widths, three of them invented in a single pass for one surface, so one
 * window changed state at six different sizes; and five panel content edges (10,
 * 12, 14, 18 and a clamp), none of them derivable from the others. The tests
 * below are what makes the next number an argument instead of an accident.
 */
describe("one ladder, and one inset, for the whole window", () => {
  test("every media query in the cascade is a step on the ladder", () => {
    // A fourth width has to be added to the ladder in `tokens.css`, where it is
    // written down with the reason it exists -- not dropped into one surface and
    // left for the other two to disagree with.
    const widths = new Set(
      [...STYLESHEET.matchAll(/@media\s*\(\s*max-width:\s*(\d+)px\s*\)/g)].map((m) =>
        Number(m[1]),
      ),
    );
    assert.ok(widths.size > 0, "there are no media queries at all");
    // Four compact steps, because 1100 and 1400 are dock *thresholds* and are
    // written as the first width that can hold the dock rather than the last
    // one that cannot. 1100 is therefore the default (the rail), and its
    // boundary is the 1101 minimum below.
    // 1247 is the capacity threshold for Code's assistant, and it is a
    // *container* query on `#root` rather than a compaction step: it is
    // `--dock-w` + `--code-helper-w` + 560 - 1, the last width at which Code's
    // editor still has its reading width with the explorer and the assistant
    // both docked. It is written as a *maximum* container because what it
    // decides is when the assistant stops docking. See `shell.css`.
    assert.deepEqual(
      [...widths].sort((a, b) => a - b),
      [420, 560, 720, 900],
      "a surface reflows at a width the ladder does not have",
    );
    const floors = new Set(
      [...STYLESHEET.matchAll(/@media\s*\(\s*min-width:\s*(\d+)px\s*\)/g)].map((m) =>
        Number(m[1]),
      ),
    );
    assert.deepEqual(
      [...floors].sort((a, b) => a - b),
      [1101, 1400],
      "a dock threshold is not on the ladder",
    );
  });

  test("and a pane's own width is asked as a container query, not as one", () => {
    // The code viewer's header gives things up when *the pane* is narrow, which
    // is a different question from the window's width and cannot be answered
    // with a media query at all -- it used to be answered with 440, a fourth
    // number that looked like a breakpoint and was not one.
    assert.match(STYLESHEET, /@container\s*\(max-width:\s*440px\)/);
    assert.doesNotMatch(STYLESHEET, /@media[^{]*max-width:\s*440px/);
    // Code's assistant collapses the same way: 1247 is `--dock-w` (288) plus
    // `--code-helper-w` (400) plus the editor's 560 floor minus one, asked of
    // the `#root` container so the shell's own grid can answer it. A window
    // breakpoint here would grow the ladder for one mode.
    assert.match(STYLESHEET, /@container\s*\(max-width:\s*1247px\)/);
    assert.doesNotMatch(STYLESHEET, /@media[^{]*max-width:\s*1247px/);
  });

  test("every panel puts its content on the same edge", () => {
    // Asserted over *every* block for the selector rather than the last one:
    // `.code-header` has a second rule inside a container query, and "the last
    // rule" would then be answering this question with a rule about gaps.
    for (const selector of [
      ".chatlist-head",
      ".chatlist-foot",
      ".chatlist-empty",
      ".sidebar-empty",
      ".code-header",
      ".code-explorer-head",
      ".usage",
    ]) {
      assert.ok(
        bodies(selector).some((text) => /var\(--pad-panel\)/.test(text)),
        `${selector} does not hold the panel inset every other panel holds`,
      );
    }
    assert.match(body(".modal"), /padding:\s*var\(--pad-panel\)/);
  });

  test("and a card inside one lands on that edge too", () => {
    // A row is inset `--pad-row` from the panel and pads by `--pad-row`, so the
    // two together are `--pad-panel`: a conversation title, a group label,
    // a file's name and the Files filter's text all start on one line. The regions
    // token, which is what makes the arithmetic true rather than lucky.
    for (const selector of [".chatlist-rows", ".sidebar-tree"]) {
      assert.match(body(selector), /padding:\s*0 var\(--pad-row\)/);
    }
    for (const selector of [
      ".chatrow-open",
      ".chatlist-label",
      ".tree-row",
      ".sidebar-filter",
    ]) {
      assert.ok(
        bodies(selector).some((text) => /var\(--pad-row\)/.test(text)),
        `${selector} is a card in a panel and does not take the row inset`,
      );
    }
  });
});

// --- the density the controls have to hit -----------------------------------
describe("the rail's targets are big enough to hit", () => {
  test("the rail is as wide as its buttons and its air", () => {
    // Pinned by value, like `--topbar-h` and `--list-w`, because the derived
    // check below cannot see this one on its own. Widened to 64px in the
    // restructure: a 44px button inside it leaves 10px a side, which is the air
    // the other assertion asks for.
    assert.match(STYLESHEET, /--rail-w:\s*64px/);
  });

  test("a rail button is at least the 40px minimum click target", () => {
    // It was 38x34. 34px is under the 40px minimum, and the rail is the one
    // place in this app where every control is reached by a pointer alone --
    // the settings and stop buttons are the only way back to a usable window
    // once a turn is running.
    const railW = parseFloat(/--rail-w: *([\d.]+)px/.exec(STYLESHEET)![1]);
    const w = parseFloat(/width: *([\d.]+)px/.exec(body(".rail-btn"))![1]);
    const h = parseFloat(/height: *([\d.]+)px/.exec(body(".rail-btn"))![1]);
    assert.ok(w >= 40, `rail buttons are ${w}px wide`);
    assert.ok(h >= 40, `rail buttons are ${h}px tall`);
    // And the rail has to hold one with room either side, or it stops reading
    // as a strip and becomes a column of squares.
    assert.ok(
      railW - w >= 8,
      `a ${w}px button in a ${railW}px rail leaves ${(railW - w) / 2}px a side`,
    );
  });
});

// --- re-measured at full DPI ------------------------------------------------
describe("the bar and the tab pill, re-measured at full DPI", () => {
  test("the title bar is 52px, which is one text line plus its margins", () => {
    // It was 44px after the last re-derivation. The restructure gives the bar
    // more air around its one row of 13px text, and 52px is that text over 19px
    // of margin -- still a bar sized to its contents rather than to someone
    // else's caption buttons.
    assert.match(STYLESHEET, /--topbar-h:\s*52px/);
    // And the caption buttons have to survive inside it, because they fill the
    // bar's height and a bar too short for them clips their own labels.
    const bar = parseFloat(/--topbar-h: *([\d.]+)px/.exec(STYLESHEET)![1]);
    assert.ok(bar >= 40, `a ${bar}px bar cannot hold a 40px caption button`);
  });

  test("the tab sits flush on the chrome, with no hairline at all", () => {
    // This used to pin the tab's hairline to `--border` rather than the lighter
    // `--border-strong`, which was the right question while it had one. It has
    // none now: the wash separates the tab you are in from the chrome behind it.
    //
    // Asserted on the tab's own two controls rather than on the tab: a `<button>`
    // arrives with a border, and both of them have to be told not to draw one.
    // The tab itself is a box, and its edge is its fill.
    for (const selector of [".tab-open", ".tab-close"]) {
      assert.match(body(selector), /border:\s*0/);
      assert.doesNotMatch(body(selector), /border:\s*1px solid/);
      assert.doesNotMatch(body(selector), /var\(--border-strong\)/);
    }
  });
});

// --- the conversation panel's folder ----------------------------------------
describe("the panel names the folder it is showing", () => {
  test("the folder is a control, so it can be changed from the list", () => {
    // The list is scoped to one folder, so the folder is the thing a user needs
    // to be able to move -- and the picker used to hang off the project group's
    // header, which is gone. A heading that could not be pressed would leave the
    // chats pane with no way to change folders at all.
    assert.match(body(".chatlist-folder"), /cursor:\s*pointer/);
    // Undone rather than restyled: a `<button>` arrives with a border, a grey
    // background and a centred label, and all three have to go for it to read as
    // the heading it still is.
    assert.match(body(".chatlist-folder"), /border:\s*0/);
    assert.match(body(".chatlist-folder"), /background:\s*transparent/);
    assert.match(body(".chatlist-folder"), /text-align:\s*left/);
  });

  test("the folder can shrink rather than widening the panel", () => {
    // The panel is 255px and a folder is a full path. Without `min-width: 0` the
    // flex item's automatic minimum size is its content, so one long folder name
    // would push the panel past its fixed width -- the same trap `.chatlist`
    // itself is documented against.
    assert.match(body(".chatlist-folder-name"), /min-width:\s*0\b/);
    assert.match(body(".chatlist-folder-name"), /text-overflow:\s*ellipsis/);
  });

  test("and the scroll region still holds the groups", () => {
    // The groups went *inside* `.chatlist-rows` rather than beside it, so the
    // folder label above stays put while a long project's conversations
    // scroll. A structure that put the label outside this box would scroll the
    // heading away with its rows.
    assert.match(body(".chatlist-rows"), /flex:\s*1/);
    assert.match(body(".chatlist-rows"), /overflow-y:\s*auto/);
  });

  test("and the empty list grows, so the foot is at the bottom either way", () => {
    // `.chatlist-rows` is not *rendered* when there are no conversations -- the
    // component swaps it for `.chatlist-empty` -- so with the empty list at
    // `flex: none` the foot had nothing above it taking the free height and sat
    // wherever the content ended. Measured in a real window, not read off the
    // stylesheet: the foot landed 218px into a 712px panel, which is what "the
    // settings button is not at the bottom of the sidebar" looks like.
    //
    // Both, and not one or the other: exactly one of the two is on screen at a
    // time, so the foot is pinned in both states only if both declare it.
    assert.match(body(".chatlist-empty"), /flex:\s*1/);
  });
});

// --- the settings menus -----------------------------------------------------
describe("permission and thinking read as one control in the settings panel", () => {
  test("the rungs are a filled run, not four equal blocks", () => {
    // `.is-on` is applied to every step up to the current one, which is what
    // makes the control say "you are here" rather than "you picked one of
    // four". A rule that made all four identical would make the level
    // unreadable from the row alone.
    assert.match(STYLESHEET, /\.permchoice-step\.is-on/);
    // And the two states must be distinguishable at all.
    assert.match(body(".permchoice-step"), /background:\s*var\(--border\)/);
    assert.match(body(".permchoice-step.is-on"), /background:\s*var\(--fg-dim\)/);
  });

  test("the menu opens toward the side with room, not a fixed one", () => {
    // It opened upward unconditionally, which was correct while this was a bar
    // pinned to the bottom of the composer and wrong once it moved into the
    // panel: these rows are the panel's *first* group, so a menu anchored above
    // its trigger renders off the top of the window -- and, being inside a
    // scrolling modal, is clipped by the panel as well. Measured live at
    // y=-210 in an 800px window, with the whole ladder unreachable.
    //
    // Both anchors are declared, keyed on the direction the component measured.
    // The base rule declares neither, so a missing `data-dir` cannot silently
    // leave the menu unpositioned.
    assert.doesNotMatch(body(".permchoice-menu"), /\b(?:top|bottom):/);
    assert.match(body('.permchoice-menu[data-dir="up"]'), /bottom:\s*calc\(100%/);
    assert.match(body('.permchoice-menu[data-dir="down"]'), /top:\s*calc\(100%/);
    assert.doesNotMatch(body('.permchoice-menu[data-dir="down"]'), /\bbottom:/);
    assert.doesNotMatch(body('.permchoice-menu[data-dir="up"]'), /\btop:/);
  });

  test("the menu is capped and scrolls, so its last row is always reachable", () => {
    // Direction alone does not bound the menu: a model with nine efforts still
    // renders nine rows, and the room the component measured is the only thing
    // standing between the user and the bottom of the list. The cap is written
    // inline from the measurement, so `overflow-y: auto` is what makes a cap
    // that is still too tall usable rather than cut off.
    assert.match(body(".permchoice-menu"), /overflow-y:\s*auto/);
  });

  test("the panel itself is bounded, so its last group can be reached", () => {
    // The same `.modal` is the confirmation, the settings panel and the search
    // panel, and it had no height limit at all. In an 800px window the settings
    // panel measured 866px tall and started at y=-33: the Model group and the
    // Close button were rendered off the bottom of the screen with nothing to
    // scroll them into view.
    //
    // `max-height: 100%` rather than a viewport value because the backdrop
    // already pads by 24px, so the percentage resolves against exactly the
    // space inside that padding -- and `.search-modal` overrides it with the
    // lower cap it wants, rather than fighting a second rule.
    assert.match(body(".modal"), /max-height:\s*100%/);
    assert.match(body(".modal"), /overflow-y:\s*auto/);
  });

  test("and settings is a page of the window, not a dialog and not a pane", () => {
    // It has been both: a centred 500px `.modal`, and a 288px pane of the
    // sidebar. The pane is what made the arrangement awkward -- four sections
    // sharing a 252px tab row, where a fifth does not fit, and rows that had to
    // stack because a provider, a model and Apply want 420px between them.
    const page = body(".settings-page");
    assert.match(
      page,
      /grid-template-columns:\s*var\(--settings-nav-w\) minmax\(0, 1fr\)/,
    );

    // The nav holds its width and the body takes the rest: `minmax(0, 1fr)` and
    // `min-width: 0` rather than `1fr` alone, because a grid item's automatic
    // minimum size is its content -- one long model id would otherwise widen the
    // body and push the nav off the left edge of the window.
    assert.match(body(".settings-nav"), /overflow-y:\s*auto/);
    assert.match(body(".settings-body"), /min-width:\s*0/);

    // And the shell hands it the whole window: one track, because the rail is
    // not rendered in this mode. `.main` has to leave the column it is pinned
    // to -- against a single track, `grid-column: 2` places it in an *implicit*
    // second column and the page goes off the right edge of the window.
    assert.match(
      body('.app[data-mode="settings"]'),
      /grid-template-columns:\s*minmax\(0, 1fr\)/,
    );
    assert.match(body('.app[data-mode="settings"] .main'), /grid-column:\s*1\b/);
  });

  test("the way out of settings is at the top of the nav, not on the floor", () => {
    // **This used to be a sticky footer, and sticky was the bug.**
    // `.modal-actions` is `position: sticky; bottom: -18px`, which pins a bar to
    // the bottom of a *scrolling* panel -- right for a dialog whose content
    // overflows, and wrong for a pane whose section may be shorter than the
    // pane: with nothing to scroll there is no scrollport to be pinned to, so
    // the bar simply sat after the content. Measured on a 700px pane: Close was
    // 181px above the foot on Permission, 34px above it on Project, and flush on
    // Keys -- three answers to "where is the exit", and none of them the
    // sidebar's edge.
    //
    // A control at the top of the nav does not have to be held anywhere, so the
    // page has no fixed band at all: the nav is a column of its own and the body
    // is the only thing that scrolls.
    assert.match(body(".settings-nav-head"), /display:\s*flex/);
    assert.match(body(".settings-nav-head"), /flex:\s*none/);
    assert.match(body(".settings-back"), /place-items:\s*center/);

    const scroller = body(".settings-body");
    assert.match(scroller, /overflow-y:\s*auto/);
    // Reserved on the scroller, and for the original reason: moving between
    // sections used to shift the content box by the width of a scrollbar that
    // came and went.
    assert.match(scroller, /scrollbar-gutter:\s*stable/);

    // And there is no settings footer left to pin. The centred dialogs still
    // have theirs -- that is the half of the rule this is not about.
    assert.doesNotMatch(SOURCE, /\.settings-modal/);
    assert.match(
      body(".modal-actions"),
      /bottom:\s*calc\(-1 \* var\(--pad-panel\)\)/,
      "the dialog's sticky footer still cancels a hard-coded padding",
    );
  });

  test("and the rows no longer stack, because the page is the window", () => {
    // The model row is a grid of provider, model and Apply side by side, and
    // that needs about 420px: stacked at the sidebar's 252px the model id came
    // out three characters and a scrollbar. At the page's width it is a row
    // again, which is the whole reason for the move -- so the two overrides that
    // stacked it are gone, and asserting their absence is the point.
    assert.doesNotMatch(SOURCE, /\.chatlist \.settings-row/);

    // What replaces the stacking is a measure, and it is the window's own
    // reading column rather than a second number for this page: the body is the
    // window less the nav, and prose here is read the way prose in the
    // transcript is.
    assert.match(body(".settings-body > *"), /max-width:\s*var\(--measure\)/);

    // The search panel's own width and height cap still give way to the
    // sidebar's. It is the one pane left, so `.chatlist .modal` is now its rule.
    assert.match(body(".chatlist .modal"), /width:\s*100%/);
    assert.match(body(".chatlist .search-modal"), /width:\s*100%/);
    assert.match(body(".chatlist .search-modal"), /max-height:\s*none/);
  });

  test("the sub-panes take the tabs' place, at the tabs' height", () => {
    // Search swaps the segmented control for a back row rather than sitting
    // under it, so entering it does not shift the pane below it up by a row's
    // worth -- and the control that leaves a pane is where the control that
    // reached it was. Settings used to be the other half of this pair and is a
    // page of the window now.
    assert.match(body(".chatlist-subhead"), /height:\s*32px/);
    assert.match(body(".chatlist-back"), /place-items:\s*center/);
    // And the chats content is hidden for every pane that is not Chats, so a
    // pane added later cannot quietly keep the conversation list behind it.
    assert.match(
      body('.chatlist:not([data-pane="chats"]) .chatlist-rows'),
      /display:\s*none/,
    );
  });

  test("the menu is as wide as the row that opened it", () => {
    // `left: 0; right: 0` with no width, so the panel grows with the label
    // instead of the menu leaving the row it belongs to. A fixed 320px -- what
    // this had as a bar over the transcript -- overflows a 500px modal the
    // moment a label beside it grows.
    assert.match(body(".permchoice-menu"), /left:\s*0\b/);
    assert.match(body(".permchoice-menu"), /right:\s*0\b/);
    assert.doesNotMatch(body(".permchoice-menu"), /width:\s*\d/);
  });

  test("the rung that acts unasked is marked in the accent, not in danger", () => {
    // Nothing here is broken or refused -- the level works as designed -- so an
    // error colour would be a lie. And `--fg-dim` would be too quiet for the
    // one thing in the menu a user must not have to read the description to
    // notice.
    //
    // It is `--accent-bright` rather than `--accent` because this badge is the
    // one place accent-coloured text sits on a *raised* chip rather than on the
    // field, and `--accent` is 3.6:1 there -- under the small-text floor, and
    // worse than the sage it replaced. `--accent-bright` is the next step up
    // the same icon ramp and clears it at 5.4:1.
    assert.match(body(".permchoice-warn"), /color:\s*var\(--accent-bright\)/);
    assert.doesNotMatch(body(".permchoice-warn"), /var\(--danger\)/);
    assert.match(body(".permchoice-warn"), /background:\s*var\(--chip\)/);
  });

  test("the trigger is a field, like the settings rows beside it", () => {
    // It used to be a transparent outlined button, which was right over the
    // transcript and wrong in a panel of fields: it was the one row there that
    // did not read as a field, which is the opposite of what it is.
    assert.match(body(".permchoice-trigger"), /background:\s*var\(--input\)/);
    assert.match(body(".permchoice-trigger"), /height:\s*30px/);
    assert.match(body(".permchoice-trigger"), /width:\s*100%/);
  });

  test("the composer's own measure is gone with the control", () => {
    // It was 720px to line up with `.composer-inner`. In a 500px modal that
    // number is meaningless, and a rule left behind would be a hard limit on a
    // panel that is already the width of its container.
    assert.doesNotMatch(SOURCE, /\.permchoice\s*\{[^}]*--composer/);
    assert.doesNotMatch(body(".permchoice"), /max-width:\s*var\(--measure\)/);
    assert.match(body(".permchoice"), /width:\s*100%/);
  });

  test("the selected mode row is a state, and takes the wash", () => {
    // The mode is one chip with a menu now, so what can be "selected" is a row
    // in that menu rather than a pill on screen beside its rivals. A row is a
    // state -- the same thing the conversation row and the tab pill are -- so it
    // takes `--wash` and not the segmented control's `--chip`. The value is a
    // token rather than a literal for the reason the pills' was: a hex here is a
    // colour nothing in the palette can retint.
    assert.match(body(".modechip-option.is-active"), /background:\s*var\(--wash\)/);
    assert.match(body(".modechip-option.is-active"), /color:\s*var\(--fg\)/);
    assert.doesNotMatch(body(".modechip-option.is-active"), /#[0-9a-fA-F]{3,8}/);
  });

  test("the value is pushed to the far edge, so the eye finishes on the answer", () => {
    // Without the auto margin the label, the ladder and the value sit in a
    // cluster at the left and the caret has nowhere to go.
    assert.match(body(".permchoice-value"), /margin-left:\s*auto/);
  });

  test("the provider row's two fields are one width, which only a grid can say", () => {
    // Measured on the running app: as a flex row with `flex: 1` on both fields
    // the select came out 172.8px against the model input's 198.8px, in a 452px
    // panel -- both items computing `flex: 1 1 0%` with `min-width: 0`, which
    // should have split the free space evenly and did not. Rather than chase the
    // engine, the row states the relationship: two equal fields and a button.
    //
    // Pinned because it is the kind of rule a later pass simplifies back to
    // `display: flex` for consistency with the rows around it, and that
    // simplification is invisible in the markup and 26px wide on screen.
    assert.match(body(".settings-row-model"), /display:\s*grid/);
    assert.match(body(".settings-row-model"), /grid-template-columns:\s*1fr\s+1fr\s+auto/);
    // The rows around it are still flex, so the exception is one row and not the
    // beginning of two layout systems in one panel.
    assert.match(body(".settings-row"), /display:\s*flex/);
  });

  test("two fields stacked are two fields, not one with a line across it", () => {
    // Measured on the running build: `.settings-row` declared an 8px `gap` and
    // no vertical rhythm at all, so the base-URL field sat 0px under the
    // provider row -- two 30px fields with their borders one pixel apart,
    // 452px wide. It is the kind of thing no screenshot in a bug report
    // describes precisely ("a bit tight") and no amount of reading the markup
    // reveals, because the markup is two innocent sibling divs.
    //
    // Pinned as a relationship rather than as the number, because the number is
    // the part worth changing later: the gap has to be at least the row's own
    // 8px, or two unrelated controls stack up looking like one grid.
    const stacked = parseFloat(/margin-top:\s*([\d.]+)px/.exec(body(".settings-row ~ .settings-row"))?.[1] ?? "0");
    assert.ok(stacked > 0, "a second row is laid out flush against the first");

    const inner = parseFloat(/gap:\s*([\d.]+)px/.exec(body(".settings-row"))?.[1] ?? "0");
    assert.ok(
      stacked >= inner,
      `a ${stacked}px gap between rows is narrower than the ${inner}px inside one, so the pair reads as one field`,
    );

    // And it is the gap the panel already puts between prose and a field, so
    // "the second field" and "the first field" are introduced the same way.
    const afterNote = boxSide(body(".settings-note"), "margin", 2);
    assert.equal(stacked, afterNote, "the two fields are not spaced like the field and its note");

    // A general sibling, not `+`: an element rendered between the two rows must
    // not silently take the gap back to zero.
    assert.match(body(".settings-row ~ .settings-row"), /margin-top:\s*[\d.]+px/);
    assert.equal(RULES.filter((r) => r.selectors.includes(".settings-row + .settings-row")).length, 0);
  });
});

// --- the key group's button ------------------------------------------------
describe("the key group's actions row", () => {
  test("the control is its own width, not the whole page", () => {
    // It was a two-column grid with a lone button spanning both, which at the
    // pane's 252px is what made Save key a button rather than a stub. There is
    // only ever one control in this row, and at the page's measure spanning it
    // draws a submit bar across the settings page.
    assert.match(body(".settings-key-actions"), /display:\s*flex/);
    assert.equal(
      RULES.filter((r) =>
        r.selectors.includes(".settings-key-actions > .btn:only-child"),
      ).length,
      0,
      "the spanning rule is back",
    );
  });
});

// --- the settings panel's scrollbar -----------------------------------------
describe("the dialog's scrollbar stays inside the dialog's corners", () => {
  test("its travel is inset at both ends, and only on the rounded dialog", () => {
    // The defect: `.modal` is a 24px-radius box that scrolls, and a scrollbar is
    // a square-cornered box. Chromium paints the scrollbar over the border box
    // without clipping it to the radius, so at either end of its travel the last
    // few pixels of the thumb were drawn on the scrim rather than on the panel.
    // Measured on the settings panel at 1200x800, before: **7.0px of thumb past
    // the silhouette at the top and 7.0px at the bottom** -- y 28.5..35.5 and
    // y 764.0..771.0. The line appeared to continue past the dialog's corner and
    // stop in mid-air.
    //
    // The travel is inset rather than the thumb, so the thumb's denominator
    // shrinks along with it; measured after, at both ends of the scroll:
    // zero rows outside.
    for (const end of ["decrement", "increment"]) {
      const sel = `.modal::-webkit-scrollbar-button:vertical:${end}`;
      const found = RULES.find((r) => r.selectors.includes(sel));
      assert.ok(found, `${sel} is not in the stylesheet at all`);
      assert.match(found.body, /display:\s*block/);
      assert.match(found.body, /height:\s*\d+px/);
      // The buttons exist only to take space. Anything opaque in here would
      // paint a control the panel never asked for, which is how the browser's
      // own arrow glyphs would get in.
      assert.match(found.body, /background:\s*transparent/);
    }

    // And it is scoped to `.modal` on purpose: the transcript is a full-bleed
    // scroller with no corners to be outside of, and inset travel there would
    // cost accuracy for nothing. The global rule must stay bare.
    assert.doesNotMatch(body("::-webkit-scrollbar"), /button/);
  });
});

// --- the conversation panel's scrim -----------------------------------------
describe("the conversation panel dims what is behind it", () => {
  test("there is a scrim, because a shadow alone does not say 'over'", () => {
    // On a near-black UI a panel with a shadow and a hairline reads as a column
    // with a misplaced edge. The Files panel solved this with a scrim from the
    // start and the conversation panel now uses the same treatment.
    assert.match(body(".chatlist-scrim"), /position:\s*absolute/);
    assert.match(body(".chatlist-scrim"), /backdrop-filter:\s*blur/);
  });

  test("it stops at the rail, so Stop and Settings stay reachable", () => {
    // The distinguishing fact against `.sidebar-scrim`, which spans the full
    // width. Covering the rail would put the two buttons a user reaches for
    // mid-turn behind a backdrop they have to dismiss first, and the panel is
    // anchored to the rail precisely so the rail stays operable.
    //
    // The bottom edge is the status bar's height for the mirror-image reason.
    // The rail is worth covering and the bar is not: the bar is the one surface
    // that says whether the app is connected. Asserted as the whole inset, so
    // moving either edge has to be a decision rather than a drift.
    assert.match(
      body(".chatlist-scrim"),
      /inset:\s*var\(--topbar-h\) 0 var\(--statusbar-h\) var\(--rail-w\)/,
    );
  });

  test("and it starts below the title bar, like the panel it dims", () => {
    // Otherwise it covers the caption buttons and takes the drag region with
    // them, leaving a window that cannot be moved with the panel open.
    assert.match(body(".chatlist-scrim"), /var\(--topbar-h\)/);
  });

  test("it animates on data-state, so a dismissed scrim stops eating clicks", () => {
    // It is still on screen for the length of its exit, and a full-window
    // backdrop left clickable after the user closed the panel is a region where
    // the next click goes nowhere.
    assert.match(
      body('.chatlist-scrim[data-state="open"]'),
      /animation:\s*scrim-in/,
    );
    assert.match(
      body('.chatlist-scrim[data-state="closed"]'),
      /animation:\s*scrim-out/,
    );
    // The `pointer-events: none` is not in the scrim's own rule: it shares the
    // file-wide list every dismissing surface is named in, so asserting against
    // `body(...)` -- the *last* block written for the selector, which is the
    // animation -- would read the wrong rule. The question is which selectors
    // that one shared block names, so that is what is asserted.
    const inert = RULES.filter((rule) =>
      /pointer-events:\s*none/.test(rule.body),
    );
    assert.ok(
      inert.some((rule) =>
        rule.selectors.includes('.chatlist-scrim[data-state="closed"]'),
      ),
      "a dismissed scrim is not in the list of surfaces that stop eating clicks",
    );
  });

  test("the panel keeps its shadow, which the scrim does not replace", () => {
    // Two different statements: the scrim says "this is over the transcript",
    // the shadow says "this has an edge of its own". Dropping the shadow when
    // the scrim arrived would lose the second without gaining anything.
    assert.match(body(".chatlist"), /box-shadow:/);
  });
});

// --- the first-run panel ----------------------------------------------------
/*
 * Rules jsdom cannot measure, about a panel with nothing in it to interact
 * with.
 *
 * The composition is asserted here and the behaviour is asserted in
 * `MessageList.test.tsx`: that it holds no tab stop is a DOM question, but
 * *how it is drawn* -- scaled to the window, coloured off the accent ramp, and
 * set at steps off the type scale rather than at sizes somebody typed -- is a
 * cascade question, and a cascade question is what this file is for.
 *
 * Three of these would pass unchanged against a worse design, which is why each
 * names the failure it replaces.
 */
describe("the stylesheet is split into modules, and nothing is left out", () => {
  // The split's only real failure mode is silent: a module written but never
  // imported still parses, still lints, still shows up in the editor, and the
  // rule simply never reaches the browser. Every other assertion in this file
  // reads the concatenation, so it would pass on a stylesheet with a hole in
  // it -- it would just be asserting about less than it looks.
  const modules = stylesheetModules();

  test("the entry imports every module, once each, and holds no rules itself", () => {
    assert.ok(modules.length > 1, "the entry is not an index of modules any more");
    assert.deepEqual(
      [...new Set(modules)],
      modules,
      `the same module is imported twice, which doubles every rule in it: ${modules.join(", ")}`,
    );

    // An `entry` that also carries rules is a file whose split has begun but
    // not finished, and the rules in it are the ones the ordering does not
    // describe. The entry is an index or it is a stylesheet; it cannot be both.
    assert.doesNotMatch(
      readEntry(),
      /\{/,
      "the entry declares rules as well as importing modules, so its cascade order is unstated",
    );
  });

  test("every module on disk is imported, and every import resolves", () => {
    const onDisk = readdirSync(new URL("styles/", new URL("../src/", import.meta.url)))
      .filter((n) => n.endsWith(".css"))
      .sort();
    const imported = [...modules].sort();
    assert.deepEqual(
      imported,
      onDisk,
      "a module in styles/ is not in styles.css, so its rules never load",
    );
  });

  test("no rule is empty", () => {
    // Deleting the last declaration out of a rule leaves an empty one, and an
    // empty rule is invisible from here: the browser drops it, so the file reads
    // as though the rule had never been written. `.sidebar-filter input:focus`
    // sat that way for the whole of this sweep after `outline: none` came out of
    // it, and its selector was the only one in the stylesheet the document did
    // not resolve.
    const empty = [...STYLESHEET.matchAll(/([^{}]+)\{\s*\}/g)].map((m) =>
      m[1].split(/\s+/).join(" "),
    );
    assert.deepEqual(empty, [], `rules with nothing in them: ${empty.join(" | ")}`);
  });

  test("no module imports another, because the reader resolves one level only", () => {
    // Vite would follow a nested `@import`; `readStylesheet` would not, because it
    // reads the entry's list and nothing else. So a module that reaches sideways
    // would reach the browser and not the tests, and every assertion in this file
    // would quietly be about a smaller stylesheet than the one shipping.
    assert.doesNotMatch(
      STYLESHEET,
      /@import/,
      "a module imports another module; the tests read the entry's list and cannot follow it",
    );
  });
});

describe("the first-run panel", () => {
  test("the mark scales with the window instead of being pinned", () => {
    // A fixed width would be right for the rail, which has one size forever,
    // and wrong here: this is the only vertically centred thing in the window,
    // and on a short one a 104px mark plus three lines of text is the first
    // thing to collide with the composer.
    //
    // `clamp` and not `min()`: the ceiling is the size the component was handed
    // and the floor is the smallest size at which the glyph is still a glyph,
    // and both ends of the range have to be stated for the rule to be right on
    // a window nobody tested.
    const mark = body(".empty-mark");
    assert.match(mark, /width:\s*clamp\(/);
    assert.match(mark, /clamp\(\s*\d+px,\s*[\d.]+vh,\s*\d+px\s*\)/);
    // Off the viewBox's own 1:1, or the mark goes oval on the surface where it
    // is the largest thing on screen.
    assert.match(mark, /height:\s*auto/);

    // And it is not pinned the other way either: a `flex-shrink` of 0 would
    // make the clamp above unreachable inside a short flex column.
    assert.ok(
      !/flex-shrink:\s*0/.test(mark),
      "the mark refuses to shrink, which is the case the clamp exists for",
    );
  });

  test("the mark is the accent, painted through `color`", () => {
    // Two different jobs on the same icon ramp: the mark is a picture on the
    // field and the focus ring has to be legible against four surfaces, which
    // is why the ring has a token of its own. Reuse is right here -- both are
    // the icon's own blue -- and a literal hex is not, because `--accent` is
    // read out of the rasterised artwork.
    const mark = body(".empty-mark");
    assert.match(mark, /color:\s*var\(--accent\)/);
    // `color`, not `stroke` or `fill`. The glyph is drawn on `currentColor` so
    // the surface chooses; a rule that set `stroke` here would win over the
    // component's own attribute and quietly diverge from the rail's copy.
    assert.doesNotMatch(mark, /(stroke|fill):/);

    // The mark is legible as a graphic, which is 3:1 rather than 4.5:1 -- the
    // lower bar is for the non-text case, and asserting it here is what stops
    // somebody re-deriving `--accent` against `--chip` and losing the mark with
    // the badges.
    assert.ok(
      contrast(tokens("accent")!, tokens("bg")!) >= 3,
      "the mark does not clear 3:1 on the field it sits on",
    );
  });

  test("the hints are set from the type scale, not from sizes", () => {
    // Two steps, adjacent, and the smaller one on the key. The failure being
    // guarded against is `font-size: 11px` written into the rule, which reads
    // as a harmless local decision right up until the type scale is retuned and
    // these two are left behind at the old values.
    const row = body(".empty-hints");
    assert.match(row, /font-size:\s*var\(--text-sm\)/);

    const key = body(".empty-hints kbd");
    assert.match(key, /font-size:\s*var\(--text-xs\)/);
    assert.match(key, /font-family:\s*inherit/);

    // And the ladder really is a ladder here rather than two names for one
    // value: the key sits a step below the sentence that explains it.
    assert.ok(
      parseFloat(tokenRaw("text-xs")!) < parseFloat(tokenRaw("text-sm")!),
      "--text-xs and --text-sm are the same size",
    );

    // The wordmark and the line keep their steps: the mark takes the display
    // clamp (28 floor, 34 ceiling, viewport between), the line stays base.
    assert.match(
      body(".empty h1"),
      /font-size:\s*clamp\(var\(--text-2xl\),\s*4vw,\s*var\(--text-display\)\)/,
    );
    assert.match(body(".empty h1"), /letter-spacing:\s*-0\.015em/);
    assert.match(body(".empty p"), /font-size:\s*var\(--text-base\)/);
  });

  test("the hint row is a row, and it wraps rather than overflowing", () => {
    // `flex` because a two-item row is a row, not a paragraph with a slash in
    // it; `wrap` because the composer under it is 680px wide at its widest and
    // the panel above it is not.
    const row = body(".empty-hints");
    assert.match(row, /display:\s*flex/);
    assert.match(row, /flex-wrap:\s*wrap/);
    assert.match(row, /justify-content:\s*center/);
    // `list-style: none` rather than relying on nothing: it is a `<ul>`, so the
    // bullets are the UA's to remove and they have to be removed on purpose.
    assert.match(row, /list-style:\s*none/);
  });

  test("the mark arrives, and the arrival is cancelled under reduced motion", () => {
    // It reuses `rise-in` and `--motion-base`, the pair every other arriving
    // surface in this app uses. A first-run panel with its own entrance would
    // be the one piece of motion in the window that looks pasted in.
    assert.match(body(".empty-mark"), /animation:\s*rise-in var\(--motion-base\)/);

    // And the cancellation is asserted rather than assumed. `reducedMotion.test
    // .ts` already fails the run if a rule sets `animation` without a matching
    // entry; this is the other direction -- the entry has to name the selector
    // that is actually written, since `.empty-mark` and `.empty-mark[data-state]`
    // do not match the same thing and only one of them wins on specificity.
    const block = /@media[^{]*prefers-reduced-motion:\s*reduce[^{]*\{([\s\S]*)\}\s*$/.exec(
      STYLESHEET,
    );
    assert.ok(block, "the reduced-motion block is gone from the stylesheet");
    assert.match(block[1], /\.empty-mark\s*\{\s*animation:\s*none/);
  });
});

// --- the anchored menus -----------------------------------------------------
describe("every anchored menu is placed by measurement", () => {
  test("the picker's two axes are declared on the attributes, not the base rule", () => {
    // The report, in the stylesheet's terms. `.modelpicker` is `left: 0` and
    // `top: calc(100% + 6px)` on its base rule, and its chip is in the title
    // bar's *right-hand* cluster: measured in the running window at a 900px
    // width with the chip at x=600, the panel ran from 600 to 920 and the last
    // 20px of it were outside the window.
    //
    // The measurement now decides both axes -- see `menuPlacement.ts` -- and the
    // contract is the one `.permchoice-menu` above already states: neither
    // anchor on the base rule, both declared per attribute. That is what makes a
    // menu which never got a placement render *unpositioned* rather than
    // silently opening the wrong way; the components fall back to `down` and
    // `start` in their markup precisely because this rule declares neither.
    assert.doesNotMatch(body(".modelpicker"), /\b(?:top|bottom|left|right):/);
    assert.match(body('.modelpicker[data-dir="down"]'), /top:\s*calc\(100%/);
    assert.match(body('.modelpicker[data-dir="up"]'), /bottom:\s*calc\(100%/);
    assert.doesNotMatch(body('.modelpicker[data-dir="down"]'), /\bbottom:/);
    assert.doesNotMatch(body('.modelpicker[data-dir="up"]'), /\btop:/);
    assert.match(body('.modelpicker[data-align="start"]'), /left:\s*0/);
    assert.match(body('.modelpicker[data-align="end"]'), /right:\s*0/);
  });

  test("and the gap the cap is measured against is the one the stylesheet places with", () => {
    // The one number in this arrangement that exists twice. `placeMenu`
    // subtracts `MENU_GAP` from the room it measured to get the height the menu
    // may be, while these rules are what actually put the menu that far from its
    // trigger -- so a disagreement between the two puts the last row of a capped
    // menu past the floor it was capped to, and it is invisible until a window
    // is short enough for the cap to bind at all.
    //
    // A stylesheet cannot read a module constant, so the two are pinned to each
    // other here instead of by construction: the token in `tokens.css` is read
    // out of the cascade and compared with the module's own default.
    const gap = /--menu-gap:\s*([\d.]+)px/.exec(STYLESHEET)?.[1];
    assert.ok(gap, "`--menu-gap` is not declared");
    assert.equal(
      Number(gap),
      MENU_GAP,
      "the stylesheet's menu gap is not the one the placement subtracts",
    );
    for (const selector of [
      '.modelpicker[data-dir="down"]',
      '.modelpicker[data-dir="up"]',
      '.permchoice-menu[data-dir="up"]',
      '.permchoice-menu[data-dir="down"]',
      ".budget-popover",
      ".skills-menu",
    ]) {
      assert.match(
        body(selector),
        /calc\(100% \+ var\(--menu-gap\)\)/,
        `${selector} spells its gap out instead of taking the token`,
      );
    }
  });

  test("the cap gives way from the inside, so it can never cut the menu off", () => {
    // A cap the panel cannot honour is a cap that hides the bottom of the list.
    // The list is the one child allowed to shrink, so `max-height` written
    // inline from the measured room shortens it instead -- and `min-height: 0`
    // is what lets it shrink at all, since a flex item refuses by default.
    const list = body(".modelpicker-list");
    assert.match(list, /flex:\s*0 1 auto/);
    assert.match(list, /min-height:\s*0/);
    assert.match(list, /overflow-y:\s*auto/);
    // The field above it keeps its height: it is the one thing in there that
    // would look broken at 22px instead of 28.
    assert.match(body(".modelpicker-filter"), /flex:\s*none/);
  });

  test("the code viewer's local patch is folded in, and only its width is left", () => {
    // The theme chip had the same problem as the title bar's -- it sits at the
    // window's right edge -- and it was patched by hand with `left: auto; right:
    // 0`. The side is measured for both chips now, so the only thing that is
    // still this chip's own is that a theme name is short.
    const theme = body(".code-theme .modelpicker");
    assert.match(theme, /width:\s*232px/);
    assert.doesNotMatch(theme, /(?:^|[\s;])(?:left|right):/);
  });

  test("the row menu opens toward the room, and scrolls when there is none", () => {
    // The second report, and the one that hides an action rather than a label:
    // three items opened below a click at y=417 of a 480-tall window -- the
    // app's minimum -- where Delete landed 68px outside the client rect and
    // there was no way to reach it. The menu is placed by `placeFixedMenu` now,
    // which opens it upward there, and `overflow-y: auto` is the backstop for a
    // window too short for either side: an inline cap is only usable if
    // something scrolls.
    //
    // Read across every block rather than off the last one: `.rowmenu` is
    // declared twice -- the surface in `conversation-list.css`, and the
    // `transform-origin` its arrival needs in `surfaces.css` -- and `body()`
    // would answer with whichever came later in the cascade.
    assert.ok(
      bodies(".rowmenu").some((rule) => /overflow-y:\s*auto/.test(rule)),
      "the row menu's cap has nothing to scroll inside it",
    );
  });
});
