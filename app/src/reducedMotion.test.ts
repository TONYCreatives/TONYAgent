/**
 * The reduced-motion block is a hand-written list, and a hand-written list is
 * only as good as the last person who remembered to update it.
 *
 * Every animation in styles.css outside the `@media (prefers-reduced-motion:
 * reduce)` block is motion somebody can be shown against their stated
 * preference. One was already missed that way: `.tab-spinner`, the busy
 * indicator in the top bar, which is `spin ... infinite` and so never stops.
 * Found by running the packaged app with the preference emulated over CDP, not
 * by reading the stylesheet -- the rule looked entirely ordinary next to the
 * others.
 *
 * So the list is checked against the stylesheet rather than trusted. This is
 * the same audit as `scripts/audit_reduced_motion.py`, in the form that runs on
 * every `npm test`; the script is for looking at the whole picture by hand.
 *
 * The matching below has to understand the two idioms the block is written in,
 * or it cries wolf on every `[data-state]` rule and gets ignored:
 *
 *   - naming the selector outright -- `.chatrow`
 *   - naming it with the attribute *value* dropped -- `.rowmenu[data-state]`
 *     for `.rowmenu[data-state="open"]`, which matches both states at once and
 *     wins the tie on source order because the media block is declared later
 *
 * Specificity is compared rather than assumed, since the block's own comment
 * says the repeated `[data-state]` halves exist precisely to match it.
 */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

// `tsc` emits the tests to `.tmp/` and copies no other file, so the stylesheet
// is one directory up from the compiled module rather than beside it.
const STYLESHEET = readFileSync(new URL("../src/styles.css", import.meta.url), "utf8");

/** `selector { body }` pairs, brace nesting stepped over. */
function rules(css: string): { block: string; body: string }[] {
  // Comments go first. This stylesheet documents each rule in a comment that
  // names the very selector it documents, so a comment left in place is parsed
  // as part of the selector it precedes.
  const clean = css.replace(/\/\*[\s\S]*?\*\//g, "");
  return [...clean.matchAll(/([^{}]+)\{([^{}]*)\}/g)].map((m) => ({
    block: m[1].trim(),
    body: m[2],
  }));
}

/** The rules inside the reduced-motion block, and everything outside it. */
function splitOnReducedMotion(css: string) {
  const clean = css.replace(/\/\*[\s\S]*?\*\//g, "");
  const inside: typeof rules extends never ? never : ReturnType<typeof rules> = [];
  const outside: ReturnType<typeof rules> = [];
  let cursor = 0;
  const opener = /@media[^{]*prefers-reduced-motion:\s*reduce[^{]*\{/g;
  for (const match of clean.matchAll(opener)) {
    outside.push(...rules(clean.slice(cursor, match.index)));
    let depth = 1;
    let index = match.index + match[0].length;
    while (depth && index < clean.length) {
      if (clean[index] === "{") depth += 1;
      else if (clean[index] === "}") depth -= 1;
      index += 1;
    }
    inside.push(...rules(clean.slice(match.index + match[0].length, index - 1)));
    cursor = index;
  }
  outside.push(...rules(clean.slice(cursor)));
  return { inside, outside };
}

/** The value in a selector's only attribute selector, or null if it has none. */
function attributeValue(selector: string): string | null {
  const found = /\[[\w-]+=(?:"([^"]*)"|'([^']*)')\]/.exec(selector);
  if (!found) return null;
  return found[1] ?? found[2] ?? null;
}

/** The selector with its attribute conditions removed. */
function base(selector: string): string {
  return selector.replace(/\[[^\]]*\]/g, "").replace(/\s+/g, " ").trim();
}

/** Classes plus attribute selectors, which is all these selectors use. */
function specificity(selector: string): number {
  return (selector.match(/\.[\w-]+/g) ?? []).length + (selector.match(/\[[^\]]*\]/g) ?? []).length;
}

/** Whether one selector from the block reaches an animated rule. */
function covers(cancelled: string, animated: string): boolean {
  if (cancelled === animated) return true;
  if (base(cancelled) !== base(animated)) return false;
  // `[data-state="open"]` does not stand in for `[data-state="closed"]`.
  const a = attributeValue(cancelled);
  const b = attributeValue(animated);
  if (a !== null && b !== null && a !== b) return false;
  return specificity(cancelled) >= specificity(animated);
}

function splitSelectors(block: string): string[] {
  return block.split(",").map((s) => s.trim()).filter(Boolean);
}

test("every animation in the stylesheet is cancelled under reduced motion", () => {
  const { inside, outside } = splitOnReducedMotion(STYLESHEET);
  assert.ok(inside.length > 0, "the reduced-motion block was not found at all");

  const cancelled = inside
    .filter((rule) => /animation\s*:/.test(rule.body) && /\bnone\b/.test(rule.body))
    .flatMap((rule) => splitSelectors(rule.block));

  const missed: string[] = [];
  for (const rule of outside) {
    const match = /(?<![\w-])animation\s*:\s*([^;]+)/.exec(rule.body);
    if (!match) continue;
    const declaration = match[1].trim();
    if (declaration === "none") continue;
    for (const selector of splitSelectors(rule.block)) {
      if (!cancelled.some((candidate) => covers(candidate, selector))) {
        missed.push(`${selector} -> ${declaration}`);
      }
    }
  }

  // The message names the selectors, because "add it to the block" is the whole
  // fix and a bare count would send the next person looking.
  assert.deepEqual(
    missed,
    [],
    `these still animate under prefers-reduced-motion: reduce -- add them to the block:\n  ${missed.join("\n  ")}`,
  );
});

test("a cancelled indicator keeps its information, not just its motion", () => {
  // The block cancels motion; it must not cancel meaning. `.tab-spinner` is a
  // progress indicator, and hiding it to satisfy a motion preference would trade
  // a real signal for a cosmetic one -- a turn that looks finished is worse
  // than a turn that looks still. Cancelling only the animation leaves the ring
  // painted, with its lighter top edge, which still reads as "busy".
  const { inside } = splitOnReducedMotion(STYLESHEET);
  const cancelled = inside
    .filter((rule) => /animation\s*:/.test(rule.body) && /\bnone\b/.test(rule.body))
    .flatMap((rule) => splitSelectors(rule.block));

  assert.ok(
    cancelled.includes(".tab-spinner"),
    "the busy indicator is no longer cancelled, so it will spin forever for reduced-motion users",
  );

  const spinner = rules(STYLESHEET).find((rule) => splitSelectors(rule.block).includes(".tab-spinner"));
  assert.ok(spinner, "the .tab-spinner rule itself is missing from the stylesheet");
  // Cancelled by animation alone: nothing about the ring's own painting is
  // touched, so it is still a visible, asymmetric ring when it stops turning.
  assert.ok(/border-top-color/.test(spinner.body), "the ring lost the edge that makes it read as busy");
  assert.ok(/border-radius/.test(spinner.body));
  assert.ok(!/display\s*:\s*none/.test(spinner.body), "the indicator is hidden, not just still");
  assert.ok(!/visibility\s*:\s*hidden/.test(spinner.body));
});

test("the block matches the specificity it claims to match", () => {
  // The block's own comment says the repeated `[data-state]` halves are there to
  // match two-class specificity, and that `!important` was avoided for that
  // reason. If a cancellation ever drops below the rule it overrides, it loses
  // the cascade no matter how much later it is declared -- and the animation
  // plays for exactly the people who asked for it not to.
  const { inside, outside } = splitOnReducedMotion(STYLESHEET);
  const cancellations = inside
    .filter((rule) => /animation\s*:/.test(rule.body) && /\bnone\b/.test(rule.body))
    .flatMap((rule) => splitSelectors(rule.block));

  for (const rule of outside) {
    const match = /(?<![\w-])animation\s*:\s*([^;]+)/.exec(rule.body);
    if (!match || match[1].trim() === "none") continue;
    for (const selector of splitSelectors(rule.block)) {
      const reaching = cancellations.filter((candidate) => covers(candidate, selector));
      for (const candidate of reaching) {
        assert.ok(
          specificity(candidate) >= specificity(selector),
          `${candidate} cannot override ${selector}: specificity ${specificity(candidate)} < ${specificity(selector)}`,
        );
      }
    }
  }

  assert.ok(
    !STYLESHEET.includes("animation: none !important"),
    "the block says it avoids !important to keep winning on specificity, but now uses it",
  );
});
