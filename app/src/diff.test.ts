/**
 * Tests for the line diff behind the edit report.
 *
 * The cases are the shapes a person actually produces while editing: a
 * changed line, a deleted line, an inserted block, two edits apart in one
 * file, and a whole-file rewrite. The last one is where the approximation is
 * visible, and the test says so rather than pretending otherwise.
 */

import { test } from "node:test";
import assert from "node:assert/strict";

import { diffLines, editReport } from "./diff.js";

const lines = (...rows: string[]) => rows.join("\n") + "\n";

test("an unchanged file is no change at all", () => {
  const text = lines("a", "b", "c");
  assert.deepEqual(diffLines(text, text), { added: 0, removed: 0, ranges: [] });
});

test("changing one line reports that line", () => {
  const before = lines("one", "two", "three");
  const after = lines("one", "TWO", "three");
  const diff = diffLines(before, after);

  assert.equal(diff.added, 1);
  assert.equal(diff.removed, 1);
  assert.deepEqual(diff.ranges, [{ start: 2, end: 2 }]);
});

test("appending a line reports the new last line", () => {
  const before = lines("one", "two");
  const after = lines("one", "two", "three");
  const diff = diffLines(before, after);

  assert.equal(diff.added, 1);
  assert.equal(diff.removed, 0);
  assert.deepEqual(diff.ranges, [{ start: 3, end: 3 }]);
});

test("inserting a block reports the block's span", () => {
  const before = lines("head", "tail");
  const after = lines("head", "new one", "new two", "tail");
  const diff = diffLines(before, after);

  assert.equal(diff.added, 2);
  assert.equal(diff.removed, 0);
  assert.deepEqual(diff.ranges, [{ start: 2, end: 3 }]);
});

test("deleting a line points at where it was", () => {
  const before = lines("one", "two", "three");
  const after = lines("one", "three");
  const diff = diffLines(before, after);

  assert.equal(diff.added, 0);
  assert.equal(diff.removed, 1);
  // Zero-width: the line that used to hold "two" now holds "three", which is
  // the line the agent should look at.
  assert.deepEqual(diff.ranges, [{ start: 2, end: 2 }]);
});

test("deleting the last line points at the new last line", () => {
  const before = lines("one", "two");
  const after = lines("one");
  const diff = diffLines(before, after);

  assert.equal(diff.removed, 1);
  assert.deepEqual(diff.ranges, [{ start: 2, end: 2 }]);
});

test("two edits apart in one file are two ranges", () => {
  const before = lines("a", "b", "c", "d", "e", "f");
  const after = lines("a", "B", "c", "d", "e", "F");
  const diff = diffLines(before, after);

  assert.equal(diff.added, 2);
  assert.equal(diff.removed, 2);
  assert.deepEqual(diff.ranges, [{ start: 2, end: 2 }, { start: 6, end: 6 }]);
});

test("a rewrite reports the rewritten region", () => {
  const before = lines("a", "b", "c", "d");
  const after = lines("a", "w", "x", "y", "z", "d");
  const diff = diffLines(before, after);

  assert.equal(diff.added, 4);
  assert.equal(diff.removed, 2);
  assert.deepEqual(diff.ranges, [{ start: 2, end: 5 }]);
});

test("an edit that changes the indentation of a block is one range", () => {
  const before = lines("def f():", "    a = 1", "    b = 2", "    return a");
  const after = lines("def f():", "  a = 1", "  b = 2", "  return a");
  const diff = diffLines(before, after);

  assert.deepEqual(diff.ranges, [{ start: 2, end: 4 }]);
});

test("an emptied file reports the removal without inventing a line", () => {
  const diff = diffLines(lines("a", "b"), "");
  assert.equal(diff.removed, 2);
  assert.equal(diff.added, 0);
  assert.deepEqual(diff.ranges, [{ start: 1, end: 1 }]);
});

test("a file created from nothing reports the whole new file", () => {
  const diff = diffLines("", lines("x", "y"));
  assert.equal(diff.added, 2);
  assert.equal(diff.removed, 0);
  assert.deepEqual(diff.ranges, [{ start: 1, end: 2 }]);
});

test("line numbers count from one and never run past the new file", () => {
  const before = lines("a", "b", "c", "d", "e");
  const after = lines("a", "b", "X", "Y");
  const diff = diffLines(before, after);
  const count = after.split("\n").length;

  for (const range of diff.ranges) {
    assert.ok(range.start >= 1, `range starts before the file: ${range.start}`);
    assert.ok(range.end <= count, `range runs past the file: ${range.end} > ${count}`);
    assert.ok(range.end >= range.start, "a range ends before it starts");
  }
});

test("an edit in a huge file stays cheap and reports one range", () => {
  // The trim is what makes this true: five thousand identical lines are not
  // compared line by line, they are stepped over as a prefix.
  const body = Array.from({ length: 5000 }, (_, index) => `line ${index}`);
  const before = lines(...body);
  const after = lines(...body.slice(0, 2500), "line 2500 changed", ...body.slice(2501));

  const started = Date.now();
  const diff = diffLines(before, after);
  const elapsed = Date.now() - started;

  assert.deepEqual(diff.ranges, [{ start: 2501, end: 2501 }]);
  assert.ok(elapsed < 500, `the diff took ${elapsed}ms on a 5,000-line file`);
});

test("the report form carries the core's counts and this module's ranges", () => {
  const diff = diffLines(lines("a", "b"), lines("a", "B"));
  const report = editReport("app/src/App.tsx", diff, 1, 1);

  assert.deepEqual(report, {
    path: "app/src/App.tsx",
    added: 1,
    removed: 1,
    lines: [{ start: 2, end: 2 }],
  });
});
