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
const SOURCE = STYLESHEET.replace(/\/\*[\s\S]*?\*\//g, "");

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
    const bar = body(".topbar");
    assert.match(bar, /grid-row:\s*1\b/);
    assert.match(bar, /grid-column:\s*1\s*\/\s*-1/);
  });

  test("every other in-flow child names its row explicitly", () => {
    // Auto-placement fills row 1 first. A build that renders no Files panel at
    // all would then push the rail into the title bar's row and move the whole
    // window down 42px, and nothing about that failure points at the grid.
    for (const selector of [".rail", ".main", ".sidebar-reopen"]) {
      assert.match(body(selector), /grid-row:\s*2\b/, `${selector} does not name row 2`);
    }
    // And each names its column, for the same reason: `.main` was once
    // auto-placed and landed in the collapsed rail's track.
    assert.match(body(".rail"), /grid-column:\s*1\b/);
    assert.match(body(".main"), /grid-column:\s*2\b/);
    assert.match(body(".sidebar-reopen"), /grid-column:\s*3\b/);
  });

  test("the shell has one column layout, because the rail never changes width", () => {
    // The decisive structural fact, and the reason the conversation panel can
    // animate at all. `.app.rail-open` used to widen column 1 to 307px, which
    // made opening the sidebar a *layout* change: the transcript re-wrapped,
    // and a grid track cannot be transitioned, so the track snapped while the
    // content inside it tried to follow.
    //
    // Asserted as the absence of the rule *and* of the class. A rule here
    // reading `--rail-w-expanded` would silently undo the overlay, because
    // opening the panel would start pushing the transcript again underneath a
    // panel that is supposed to float over it.
    assert.doesNotMatch(SOURCE, /\.app\.rail-open/);
    assert.doesNotMatch(SOURCE, /\.sidecol/);
    assert.doesNotMatch(body(".app"), /rail-w-expanded/);
    assert.match(
      body(".app"),
      /grid-template-columns:\s*var\(--rail-w\) minmax\(0, 1fr\) auto/,
      "column 1 must be the rail and only the rail",
    );
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
// --- the palette, measured off the reference --------------------------------
describe("the palette is the reference's", () => {
  // Every value here was counted out of a screenshot of the Freebuff window
  // running on this machine, not chosen. That makes them worth pinning: a
  // palette drifts one plausible-looking edit at a time, and the drift is
  // invisible in a diff and in review -- the window still looks deliberate, it
  // just no longer looks like the thing it was copied from.
  //
  // The accents of the scale are the ones that matter, because they are what
  // the eye reads as "same app": the window's dominant field, the chrome above
  // it, and the chip that sits on both.
  const tokens = (name: string) =>
    new RegExp(`--${name}: *(#[0-9a-f]{6})`, "i").exec(STYLESHEET)?.[1];

  test("the three surfaces are the reference's three", () => {
    assert.equal(tokens("bg"), "#1c1d1c", "the dominant field is not the reference's");
    assert.equal(tokens("chrome"), "#292b2a", "the bar is not the reference's");
    assert.equal(tokens("chip"), "#3b3e3a", "the chip is a step off the reference's");
  });

  test("and they are warm greys, not neutral ones", () => {
    // The reference is 99.5% neutral with a green cast (0.47% of its pixels
    // carry any chroma, and all of that is the accent). A neutral #1c1c1c is a
    // different colour that reads as a different app beside it, and it is the
    // kind of "tidy" edit nobody notices making.
    for (const name of ["bg", "chrome", "chip"]) {
      const hex = tokens(name)!;
      const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16));
      assert.ok(
        Math.abs(r - b) <= 2 && g >= r && g >= b,
        `--${name} ${hex} is not the reference's warm grey`,
      );
    }
  });

  test("the text ramp is three steps, brightest first", () => {
    const luminance = (name: string) => {
      const hex = tokens(name)!;
      const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16));
      return 0.2126 * r + 0.7152 * g + 0.0722 * b;
    };
    assert.ok(
      luminance("fg") > luminance("fg-dim") &&
        luminance("fg-dim") > luminance("fg-mute"),
      "the text ramp is not descending",
    );
  });

  test("the accent is this app's own, read off its own icon", () => {
    // The neutrals above are borrowed on purpose, and stay borrowed. The accent
    // is not: it used to be the reference's sage, which meant the app shipped a
    // blue icon on the taskbar and a sage window around it. It is now a value
    // out of the shipped artwork -- #2f6feb is 80-87% of the opaque pixels of
    // every icon size, and #6393f0 is the step on its own antialias ramp.
    //
    // Pinned to #6393f0 rather than #2f6feb on purpose: the icon blue is 3.70:1
    // on --bg, which is short of the 4.5:1 body text needs, and the accent also
    // paints small text. The ramp step is 5.61:1. Both are the icon's.
    assert.equal(tokens("accent"), "#6393f0");
    // And it must be readable as ink on top of itself.
    assert.equal(tokens("accent-fg"), "#0b1020");
  });

  test("the accent and --ok are not the same hue wearing two names", () => {
    // --ok was a green 63/765 from a green accent, so a success dot beside a
    // filled button was a distinction of degree. Against a blue accent the same
    // green sits on the other side of the wheel.
    //
    // Measured as an angle in HSL rather than a channel distance: comparing one
    // RGB channel says nothing about hue, because blue is low in red and green
    // is high in it, and a test built that way would have passed on two
    // colours a person cannot tell apart.
    const hue = (name: string) => {
      const [r, g, b] = [1, 3, 5]
        .map((i) => parseInt(tokens(name)!.slice(i, i + 2), 16) / 255)
        .map((v) => (v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4));
      const max = Math.max(r, g, b);
      const min = Math.min(r, g, b);
      const d = max - min;
      if (d === 0) return 0;
      let h: number;
      if (max === r) h = ((g - b) / d) % 6;
      else if (max === g) h = (b - r) / d + 2;
      else h = (r - g) / d + 4;
      return ((h * 60) % 360 + 360) % 360;
    };
    const apart = Math.abs(hue("accent") - hue("ok"));
    const separation = Math.min(apart, 360 - apart);
    assert.ok(
      separation >= 60,
      `--accent ${tokens("accent")} and --ok ${tokens("ok")} are only `
        + `${separation.toFixed(0)} degrees apart on the wheel`,
    );
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
    // paint themselves light inside a #1c1d1c window.
    assert.match(body(":root"), /color-scheme:\s*dark/);
  });
});

// --- the chips ---------------------------------------------------------------
describe("chips are rounded rectangles, not stadiums", () => {
  test("the conversation tab uses the fixed radius", () => {
    // The reference rounds its chips to one radius everywhere -- the tab, the
    // selected row, the composer's segmented tabs -- and reserves the stadium
    // for pills that are actually pills (counters, badges). A stadium on the
    // tab reads as a different control at the same colour.
    assert.match(body(".tab"), /border-radius:\s*var\(--radius\)/);
    assert.doesNotMatch(body(".tab"), /border-radius:\s*var\(--radius-pill\)/);
  });

  test("it is the chip colour, and the selected row is the same one", () => {
    // Both measured at #3b3e3a in the reference. Two literals for one step of a
    // scale is how the scale stops meaning anything.
    assert.match(body(".tab"), /background:\s*var\(--chip\)/);
    assert.match(body(".chatrow.is-active"), /background:\s*var\(--chip\)/);
  });
});

// --- the bar's indent --------------------------------------------------------
describe("the title bar is indented past the left column", () => {
  test("it starts inside the main column, not against the window", () => {
    // The reference's bar is split by the same boundary the content below it
    // is, and its conversation tab starts 8px inside that split. The caption
    // stays hard against the right edge, so the bar's two ends are deliberately
    // not symmetrical.
    assert.match(body(".topbar"), /padding:\s*0 0 0 calc\(var\(--rail-w\) \+ 8px\)/);
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
    assert.match(body(".chatlist"), /left:\s*var\(--rail-w\)/);
    assert.match(body(".chatlist"), /bottom:\s*0\b/);
    // `absolute` with no `grid-column`/`grid-row`: those would be inert, and
    // inert declarations are how a rule ends up documenting an arrangement that
    // stopped existing.
    assert.doesNotMatch(body(".chatlist"), /grid-/);
  });

  test("and it is the reference's 255px, pinned to the rail's right edge", () => {
    // Measured at x=92..538 of a full-DPI capture, beside the rail's x=0..92.
    // The old 236px was a compromise against truncating titles in a column the
    // rail shared; the rail is out of the way now, so the reference's own width
    // costs nothing and the compromise can go.
    assert.match(STYLESHEET, /--list-w:\s*255px/);
    assert.match(body(".chatlist"), /width:\s*var\(--list-w\)/);
    // The sum is still the reference's 307px of sidebar, measured from the
    // window's left edge to the panel's right edge. Worth pinning because it is
    // the number a reader will check against the reference.
    assert.equal(52 + 255, 307);
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
    assert.match(body(".rail"), /background:\s*var\(--chrome\)/);
    assert.match(body(".chatlist"), /background:\s*var\(--bg\)/);
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
});

// --- the composer's measured box --------------------------------------------
describe("the composer is the size the reference draws it", () => {
  test("720px wide, because 1258 physical pixels at 1.75 scale is 719", () => {
    // The old 860px came from a downscaled screen-rect capture, so it was
    // really measuring something else. In the full-DPI capture the field spans
    // x=840..2098 and sits centred in the transcript column with a ~171px
    // gutter either side, which is a deliberate maximum rather than a fill.
    assert.match(body(".composer-inner"), /max-width:\s*720px/);
  });

  test("and its field is the reference's one recessed panel", () => {
    // #222423 is 4.6% of the reference's window, and every one of those pixels
    // lies inside the composer's bounds -- it is the only panel big enough to
    // read a recessed colour off.
    assert.match(STYLESHEET, /--surface: *#222423/i);
  });
});

// --- re-measured at full DPI ------------------------------------------------
describe("the bar and the tab pill, re-measured at full DPI", () => {
  test("the title bar is 48px, not the 46px the downscaled capture gave", () => {
    // 85 physical pixels of bar in the reference. 46px was read off a capture
    // that had already lost the 1.75 scale factor.
    assert.match(STYLESHEET, /--topbar-h:\s*48px/);
  });

  test("the tab pill's hairline is --border, not the lighter --border-strong", () => {
    // #363936 outlines the reference's pill, which is --border. --border-strong
    // is two steps up the scale and draws a visible frame around a chip that is
    // meant to sit flush on the chrome.
    assert.match(body(".tab"), /border:\s*1px solid var\(--border\)/);
    assert.doesNotMatch(body(".tab"), /var\(--border-strong\)/);
  });
});

// --- projects in the conversation panel -------------------------------------
describe("conversations are grouped under a project header", () => {
  test("the group's rows are indented, so the hierarchy reads without a legend", () => {
    // A list is scanned, not read. Indent is the cue that says "these belong to
    // the name above" without needing a colour key or a border, and it is what
    // the reference does.
    assert.match(body(".chatproj-rows"), /padding:\s*0 0 0 14px/);
  });

  test("the header is a control, so it says whether it is open", () => {
    // It folds its conversations away, and a fold that only shows in the caret's
    // shape leaves a screen reader reporting a full project as though it were
    // the only thing on screen.
    assert.match(body(".chatproj-head"), /display:\s*flex/);
    // The header is not selectable-looking: a filled row here would be one more
    // thing in the list that looks like a conversation and is not.
    assert.doesNotMatch(body(".chatproj-head"), /background:\s*var\(--(raised|chip)\)/);
  });

  test("the header can shrink its own name rather than widening the panel", () => {
    // The panel is 255px and a project is a full path. Without `min-width: 0`
    // the flex item's automatic minimum size is its content, so one long
    // folder name would push the panel past its fixed width -- the same trap
    // `.chatlist` itself is documented against.
    assert.match(body(".chatproj-toggle"), /min-width:\s*0\b/);
    assert.match(body(".chatproj-name"), /text-overflow:\s*ellipsis/);
  });

  test("the caret has its own box, because a glyph's box is not its shape", () => {
    // Without the fixed width the arrow's advance box sits a pixel off the
    // folder outline beside it, and the two read as misaligned rather than as
    // one row.
    assert.match(body(".chatproj-caret"), /width:\s*8px/);
  });

  test("the project name on the New chat button is pushed to the far edge", () => {
    // `margin-left: auto` is what puts it there. It is the button's state rather
    // than a second label, so it belongs at the end of the line where the eye
    // finishes, and it has to truncate rather than push "New chat" off.
    assert.match(body(".chatlist-new-project"), /margin-left:\s*auto/);
    assert.match(body(".chatlist-new-project"), /text-overflow:\s*ellipsis/);
  });

  test("and the scroll region still holds the groups", () => {
    // The groups went *inside* `.chatlist-rows` rather than beside it, so the
    // "New chat" button above stays put while a long project's conversations
    // scroll. A structure that put the label outside this box would scroll the
    // heading away with its rows.
    assert.match(body(".chatlist-rows"), /flex:\s*1/);
    assert.match(body(".chatlist-rows"), /overflow-y:\s*auto/);
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
    assert.match(body(".permchoice-warn"), /color:\s*var\(--accent\)/);
    assert.doesNotMatch(body(".permchoice-warn"), /var\(--danger\)/);
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
    assert.doesNotMatch(body(".permchoice"), /max-width:\s*720px/);
    assert.match(body(".permchoice"), /width:\s*100%/);
  });

  test("the selected mode pill is the palette's selected step, not a light box", () => {
    // It was #d0d0d0 on #141414 -- the brightest thing in an app whose darkest
    // surface is #1c1d1c -- and no token reached it, so nothing could have
    // retinted it. It now uses the same `--chip` the conversation row, the tab
    // pill and the selected rail item use, which is what makes all four read as
    // one "selected" rather than as four unrelated fills.
    assert.match(body(".mode.is-active"), /background:\s*var\(--chip\)/);
    assert.match(body(".mode.is-active"), /color:\s*var\(--fg\)/);
    assert.doesNotMatch(body(".mode.is-active"), /#[0-9a-fA-F]{3,8}/);
  });

  test("the value is pushed to the far edge, so the eye finishes on the answer", () => {
    // Without the auto margin the label, the ladder and the value sit in a
    // cluster at the left and the caret has nowhere to go.
    assert.match(body(".permchoice-value"), /margin-left:\s*auto/);
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
    assert.match(body(".chatlist-scrim"), /inset:\s*var\(--topbar-h\) 0 0 var\(--rail-w\)/);
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
