/**
 * Tests for the line window the viewer renders.
 *
 * The arithmetic is what decides whether a big file is usable, so the cases
 * here are the ones that would show up as a bug on screen: a window that
 * starts before the first line or after the last, a scroll position past the
 * end of the file, and the zero-height reading a component gets before
 * anything has been laid out (which is *every* reading in jsdom).
 */

import { test } from "node:test";
import assert from "node:assert/strict";

import { visibleRange } from "./virtual.js";

const ROW = 20;

test("the top of a long file renders a screenful plus the overscan", () => {
  const range = visibleRange(1000, 0, 400, ROW, 12);
  assert.equal(range.start, 0, "nothing above the first line to pad for");
  assert.equal(range.end, 20 + 12, "20 visible rows plus one overscan margin");
  assert.equal(range.paddingTop, 0);
  assert.equal(range.paddingBottom, (1000 - 32) * ROW);
});

test("scrolling moves the window and pads both sides by the same amount", () => {
  const range = visibleRange(1000, 2000, 400, ROW, 12);
  // 2000px down is line 100; the window starts an overscan above it.
  assert.equal(range.start, 100 - 12);
  assert.equal(range.paddingTop, range.start * ROW);
  const rendered = range.end - range.start;
  assert.equal(range.paddingBottom, (1000 - range.start - rendered) * ROW);
});

test("the window never runs off either end of the file", () => {
  const atTop = visibleRange(10, 0, 400, ROW);
  assert.equal(atTop.start, 0);
  assert.equal(atTop.end, 10, "a file shorter than the viewport renders whole");
  assert.equal(atTop.paddingTop, 0);
  assert.equal(atTop.paddingBottom, 0);

  const past = visibleRange(10, 999_999, 400, ROW);
  assert.ok(past.end <= 10, "a scroll past the end must not invent lines");
  assert.ok(past.start < 10);
});

test("a zero-height viewport renders a screenful rather than nothing", () => {
  // This is the jsdom case, and the first paint in a real window: a viewer
  // that showed an empty file until something measured it would look broken.
  const range = visibleRange(500, 0, 0, ROW);
  assert.ok(range.end > 0, "nothing would be rendered at all");
  assert.ok(range.end >= 40, "a screenful, not one row");
});

test("an empty file has an empty range", () => {
  assert.deepEqual(visibleRange(0, 0, 400, ROW), {
    start: 0,
    end: 0,
    paddingTop: 0,
    paddingBottom: 0,
  });
});

test("the range is always non-empty when there are lines", () => {
  // `end` must exceed `start` even for a one-line file scrolled anywhere, or
  // the render shows a blank body for a file that has content.
  for (const [lines, top] of [
    [1, 0],
    [1, 500],
    [3, 40],
    [100, 1980],
  ] as Array<[number, number]>) {
    const range = visibleRange(lines, top, 400, ROW);
    assert.ok(range.end > range.start, `${lines} lines at ${top}px rendered nothing`);
    assert.ok(range.start >= 0 && range.end <= lines, "the range stays inside the file");
  }
});

test("a nonsensical row height cannot divide by zero", () => {
  const range = visibleRange(50, 0, 400, 0);
  assert.ok(range.end > range.start);
  assert.ok(Number.isFinite(range.paddingBottom));
});
