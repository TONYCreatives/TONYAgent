/**
 * The Files pane: a project tree, not a session log.
 *
 * The behaviour worth pinning is the pair of things a tree does -- a folder
 * closes, a file opens -- plus the empty and truncated states, because a
 * pane that silently shows a partial tree is the failure this pane was
 * rebuilt to avoid.
 */

import "./test-dom.js";
import assert from "node:assert/strict";
import { describe, test } from "node:test";

import { FilesPane } from "./FileSidebar.js";
import type { CoreTreeEntry } from "./filetree.js";
import { all, click, one, press, render, setValue, texts } from "./test-render.js";

const TREE: CoreTreeEntry[] = [
  { path: "src", kind: "dir" },
  { path: "src/app.ts", kind: "file" },
  { path: "src/lib", kind: "dir" },
  { path: "src/lib/util.ts", kind: "file" },
  { path: "README.md", kind: "file" },
];

function props(over: Partial<React.ComponentProps<typeof FilesPane>> = {}) {
  return {
    entries: TREE,
    changes: new Map(),
    filter: "",
    onFilterChange: () => {},
    onChooseFolder: () => {},
    hasProject: true,
    onOpenFile: () => {},
    ...over,
  };
}

const names = (container: HTMLElement) => texts(container, ".tree-name");

/** The row whose *name* is `name` -- its text also carries the caret glyph. */
function rowFor(container: HTMLElement, name: string): HTMLElement {
  const row = all(container, ".tree-row").find(
    (candidate) => one(candidate, ".tree-name")?.textContent === name,
  );
  assert.ok(row, `no row named ${name}`);
  return row;
}

describe("the tree it draws", () => {
  test("it lists the project, nested by depth", async () => {
    const container = await render(<FilesPane {...props()} />);
    assert.deepEqual(names(container), ["README.md", "src", "app.ts", "lib", "util.ts"]);

    const depths = all(container, ".tree-row").map(
      (row) => (row as HTMLElement).style.paddingLeft,
    );
    assert.deepEqual(depths, ["8px", "8px", "22px", "22px", "36px"]);
  });

  test("a folder closes its subtree when clicked", async () => {
    const container = await render(<FilesPane {...props()} />);

    await click(rowFor(container, "src"));

    assert.deepEqual(names(container), ["README.md", "src"], "src's children stayed");
  });

  test("clicking a file opens it", async () => {
    const opened: string[] = [];
    const container = await render(<FilesPane {...props({ onOpenFile: (p) => opened.push(p) })} />);

    await click(rowFor(container, "app.ts"));

    assert.deepEqual(opened, ["src/app.ts"], "the row must open the path, not the name");
  });

  test("a row is reachable and operable from the keyboard", async () => {
    const opened: string[] = [];
    const container = await render(<FilesPane {...props({ onOpenFile: (p) => opened.push(p) })} />);
    const row = rowFor(container, "app.ts");

    assert.equal(row.getAttribute("tabindex"), "0", "a click-only tree is unreachable");
    await press("Enter", row);
    assert.deepEqual(opened, ["src/app.ts"]);
  });

  test("change badges come from the agent's own artifacts", async () => {
    const container = await render(
      <FilesPane
        {...props({ changes: new Map([["src/app.ts", { added: 7, removed: 2 }]]) })}
      />,
    );
    assert.deepEqual(texts(container, ".tree-add"), ["+7"]);
    assert.deepEqual(texts(container, ".tree-del"), ["-2"]);
  });

  test("the filter is reported upward as the user types", async () => {
    const typed: string[] = [];
    const container = await render(<FilesPane {...props({ onFilterChange: (v) => typed.push(v) })} />);
    await setValue(one(container, "input")! as HTMLInputElement, "util");
    assert.deepEqual(typed, ["util"]);
  });

  test("a filter with no matches says so", async () => {
    const container = await render(<FilesPane {...props({ filter: "zzz" })} />);
    assert.match(one(container, ".sidebar-empty")!.textContent ?? "", /Nothing matches/);
  });

  test("an empty folder offers the picker", async () => {
    let picked = 0;
    const container = await render(
      <FilesPane {...props({ entries: [], hasProject: false, onChooseFolder: () => (picked += 1) })} />,
    );
    await click(all(container, "button").find((b) => /Choose folder/.test(b.textContent ?? ""))!);
    assert.equal(picked, 1);
  });

  test("a folder that is still being read says so", async () => {
    const container = await render(<FilesPane {...props({ entries: [], loading: true })} />);
    assert.match(one(container, ".sidebar-empty")!.textContent ?? "", /Reading the project/);
  });

  test("a truncated walk is admitted rather than hidden", async () => {
    const container = await render(<FilesPane {...props({ truncated: true })} />);
    assert.match(
      one(container, ".sidebar-empty")!.textContent ?? "",
      /stops where the walk did/,
    );
  });
});
