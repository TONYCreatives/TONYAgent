/**
 * Tests for the project tree's arithmetic.
 *
 * The properties worth pinning are the ones a reader would notice: a row is
 * indented by its depth, a collapsed folder hides its whole subtree, a filter
 * surfaces a match *with* the ancestors that make it reachable, and a change
 * badge belongs to the file it was reported for. All of it is pure, so none
 * of it needs a DOM.
 */

import { test } from "node:test";
import assert from "node:assert/strict";

import {
  ancestorsOf,
  buildTree,
  changesFrom,
  depthOf,
  nameOf,
  type CoreTreeEntry,
} from "./filetree.js";

const TREE: CoreTreeEntry[] = [
  { path: "src", kind: "dir" },
  { path: "src/app.ts", kind: "file" },
  { path: "src/lib", kind: "dir" },
  { path: "src/lib/util.ts", kind: "file" },
  { path: "README.md", kind: "file" },
  { path: "tests", kind: "dir" },
  { path: "tests/app.test.ts", kind: "file" },
];

const noChanges = new Map();
const nothingCollapsed: ReadonlySet<string> = new Set();

test("path helpers agree with each other", () => {
  assert.equal(nameOf("src/lib/util.ts"), "util.ts");
  assert.equal(nameOf("README.md"), "README.md");
  assert.equal(depthOf("README.md"), 0);
  assert.equal(depthOf("src/app.ts"), 1);
  assert.equal(depthOf("src/lib/util.ts"), 2);
  assert.deepEqual(ancestorsOf("src/lib/util.ts"), ["src", "src/lib"]);
  assert.deepEqual(ancestorsOf("README.md"), []);
});

test("the tree is indented by depth and keeps directory order", () => {
  const rows = buildTree(TREE, noChanges, nothingCollapsed);
  assert.deepEqual(
    rows.map((row) => [row.name, row.depth, row.kind]),
    [
      ["README.md", 0, "file"],
      ["src", 0, "dir"],
      ["app.ts", 1, "file"],
      ["lib", 1, "dir"],
      ["util.ts", 2, "file"],
      ["tests", 0, "dir"],
      ["app.test.ts", 1, "file"],
    ],
  );
});

test("a collapsed directory hides its whole subtree", () => {
  const rows = buildTree(TREE, noChanges, new Set(["src"]));
  assert.deepEqual(
    rows.map((row) => row.path),
    ["README.md", "src", "tests", "tests/app.test.ts"],
    "src's children must be gone, not merely un-indented",
  );
  // And the row says it is closed, which is what draws the caret.
  assert.equal(rows.find((row) => row.path === "src")!.open, false);
});

test("an open directory says so", () => {
  const rows = buildTree(TREE, noChanges, nothingCollapsed);
  assert.equal(rows.find((row) => row.path === "src/lib")!.open, true);
});

test("a filter keeps the ancestors of a match", () => {
  const rows = buildTree(TREE, noChanges, nothingCollapsed, "util");
  assert.deepEqual(
    rows.map((row) => row.path),
    ["src", "src/lib", "src/lib/util.ts"],
    "a match has to arrive with the folders that lead to it",
  );
});

test("a filter ignores collapse, because the match is what was asked for", () => {
  const collapsed = new Set(["src", "src/lib"]);
  const rows = buildTree(TREE, noChanges, collapsed, "util");
  assert.deepEqual(
    rows.map((row) => row.path),
    ["src", "src/lib", "src/lib/util.ts"],
  );
  // Without a filter, the same collapse hides it -- the two are different
  // questions and must not be answered with one rule.
  assert.deepEqual(
    buildTree(TREE, noChanges, collapsed).map((row) => row.path),
    ["README.md", "src", "tests", "tests/app.test.ts"],
  );
});

test("a filter matches on the full path, not just the name", () => {
  const rows = buildTree(TREE, noChanges, nothingCollapsed, "tests/");
  assert.deepEqual(
    rows.map((row) => row.path),
    ["tests", "tests/app.test.ts"],
  );
});

test("the filter is case-insensitive and trimmed", () => {
  const rows = buildTree(TREE, noChanges, nothingCollapsed, "  README  ");
  assert.deepEqual(
    rows.map((row) => row.path),
    ["README.md"],
  );
});

test("a filter that matches nothing yields nothing", () => {
  assert.deepEqual(buildTree(TREE, noChanges, nothingCollapsed, "zzz"), []);
});

test("change badges land on the file they were reported for", () => {
  const changes = new Map([
    ["src/app.ts", { added: 12, removed: 3 }],
    ["src/lib/util.ts", { added: 4, removed: 0 }],
  ]);
  const rows = buildTree(TREE, changes, nothingCollapsed);

  const app = rows.find((row) => row.path === "src/app.ts")!;
  assert.equal(app.added, 12);
  assert.equal(app.removed, 3);

  // A pure addition has no "-N" to draw, and a zero is the absence of a
  // change rather than a change of zero.
  const util = rows.find((row) => row.path === "src/lib/util.ts")!;
  assert.equal(util.added, 4);
  assert.equal(util.removed, undefined);

  // A directory never wears a file's badge.
  const dir = rows.find((row) => row.path === "src")!;
  assert.equal(dir.added, undefined);
  assert.equal(dir.removed, undefined);
});

test("an untouched file has no badge at all", () => {
  const rows = buildTree(TREE, new Map([["src/app.ts", { added: 1, removed: 1 }]]), nothingCollapsed);
  assert.equal(rows.find((row) => row.path === "README.md")!.added, undefined);
});

test("changes are summed across the session, not overwritten", () => {
  const changes = changesFrom([
    { path: "a.ts", added: 3, removed: 1 },
    { path: "a.ts", added: 2, removed: 4 },
    { path: "b.ts", added: 5 },
    { added: 9 }, // no path: not a file change, ignored
  ]);
  assert.deepEqual(changes.get("a.ts"), { added: 5, removed: 5 });
  assert.deepEqual(changes.get("b.ts"), { added: 5, removed: 0 });
  assert.equal(changes.size, 2);
});

test("an empty tree is an empty list, not an error", () => {
  assert.deepEqual(buildTree([], noChanges, nothingCollapsed), []);
});
