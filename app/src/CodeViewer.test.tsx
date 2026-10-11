/**
 * The code viewer.
 *
 * The assertions fall into two groups, and the second is the one worth
 * having. The first is that it *renders*: line numbers, the file's text, a
 * token coloured from the palette, the footer's arithmetic. The second is
 * that it cannot be typed into -- there is no editable element in the whole
 * surface, and the body is marked read-only -- because that is the property
 * the feature exists to guarantee, and it is exactly the property a later
 * "small" change (making the body a textarea to get selection for free) would
 * quietly remove.
 */

import "./test-dom.js";
import assert from "node:assert/strict";
import { describe, test } from "node:test";

import { CodeViewer, type SourceFile } from "./CodeViewer.js";
import { all, click, one, render, setValue, texts } from "./test-render.js";

const SOURCE: SourceFile = {
  path: "src/app.ts",
  content: ["// a comment", "const answer = 42;", "", 'export const name = "agent";'].join("\n"),
  total_lines: 4,
  language: "typescript",
};

function props(over: Partial<React.ComponentProps<typeof CodeViewer>> = {}) {
  return {
    path: SOURCE.path,
    source: SOURCE,
    loading: false,
    error: null,
    locked: false,
    palette: "dark-plus",
    onPalette: () => {},
    onClose: () => {},
    ...over,
  };
}

describe("what the viewer draws", () => {
  test("it numbers every line and shows the file's text", async () => {
    const container = await render(<CodeViewer {...props()} />);

    assert.deepEqual(texts(container, ".code-gutter"), ["1", "2", "3", "4"]);
    const body = one(container, ".code-body")!.textContent ?? "";
    assert.match(body, /const answer = 42;/);
    assert.match(body, /export const name = "agent";/);
  });

  test("it colours a token from the chosen palette", async () => {
    const container = await render(<CodeViewer {...props()} />);
    const coloured = all(container, ".code-text span[style]").map(
      (node) => node.getAttribute("style") ?? "",
    );
    // Dark+ comment green and declaration blue are the two the fixture has.
    assert.ok(
      coloured.some((style) => style.includes("rgb(106, 153, 85)") || style.includes("#6a9955")),
      `no comment colour in ${coloured.join(" | ")}`,
    );
  });

  test("a different palette changes the colours", async () => {
    const dark = await render(<CodeViewer {...props()} />);
    const darkStyles = all(dark, ".code-text span[style]").map((n) => n.getAttribute("style"));
    const light = await render(<CodeViewer {...props({ palette: "light-plus" })} />);
    const lightStyles = all(light, ".code-text span[style]").map((n) => n.getAttribute("style"));
    assert.notDeepEqual(darkStyles, lightStyles, "the palette made no difference");
  });

  test("the header names the file and the language", async () => {
    const container = await render(<CodeViewer {...props()} />);
    assert.equal(one(container, ".code-path-name")!.textContent, "app.ts");
    assert.equal(one(container, ".code-path-dir")!.textContent, "src/");
    assert.deepEqual(texts(container, ".code-chip"), ["typescript", "🔒 read-only"]);
  });

  test("the footer counts lines and the language", async () => {
    const container = await render(<CodeViewer {...props()} />);
    const footer = one(container, ".code-footer")!.textContent ?? "";
    assert.match(footer, /4 lines/);
    assert.match(footer, /typescript/);
  });

  test("an empty file says so instead of drawing a blank body", async () => {
    const empty: SourceFile = { ...SOURCE, content: "", total_lines: 1 };
    const container = await render(<CodeViewer {...props({ source: empty })} />);
    assert.match(one(container, ".code-notice")!.textContent ?? "", /empty/i);
    assert.equal(one(container, ".code-body"), null);
  });

  test("a truncated read is announced, not hidden", async () => {
    const container = await render(
      <CodeViewer {...props({ source: { ...SOURCE, truncated: true } })} />,
    );
    assert.deepEqual(texts(container, ".code-chip"), [
      "typescript",
      "truncated",
      "🔒 read-only",
    ]);
  });

  test("a failure is shown as the core's sentence", async () => {
    const container = await render(
      <CodeViewer {...props({ source: null, error: "blob.bin is a binary file, which the viewer does not show." })} />,
    );
    const notice = one(container, ".code-notice-error")!;
    assert.match(notice.textContent ?? "", /binary file/);
    assert.equal(notice.getAttribute("role"), "alert");
  });

  test("a read in flight says so rather than showing nothing", async () => {
    const container = await render(<CodeViewer {...props({ source: null, loading: true })} />);
    assert.match(one(container, ".code-notice")!.textContent ?? "", /Reading src\/app\.ts/);
  });
});

describe("it is read-only, and says so", () => {
  test("there is no editable element anywhere in the surface", async () => {
    // This is the feature's whole point. A `textarea` or a
    // `contenteditable` here would look identical and be an editor.
    const container = await render(<CodeViewer {...props()} />);
    assert.equal(one(container, "textarea"), null, "a textarea is an editor");
    assert.equal(one(container, "[contenteditable]"), null, "contenteditable is an editor");
    assert.equal(one(container, "input[type=text]"), null, "a text field is an editor");
  });

  test("the body is marked read-only for assistive technology too", async () => {
    const container = await render(<CodeViewer {...props()} />);
    const body = one(container, ".code-body")!;
    assert.equal(body.getAttribute("aria-readonly"), "true");
    assert.equal(body.getAttribute("role"), "textbox");
  });

  test("the lock is stated while the agent is working", async () => {
    const container = await render(<CodeViewer {...props({ locked: true })} />);
    assert.equal(container.querySelector("section")!.getAttribute("data-locked"), "true");
    assert.match(one(container, ".code-lock")!.textContent ?? "", /agent working/);
    assert.ok(one(container, ".code-lock")!.className.includes("locked"));
  });

  test("and it stays read-only when nothing is running", async () => {
    // The lock is a *statement*, not the thing that makes it read-only: the
    // absence of editing affordances is what does that, in both states.
    const container = await render(<CodeViewer {...props({ locked: false })} />);
    assert.equal(one(container, ".code-body")!.getAttribute("aria-readonly"), "true");
    assert.equal(one(container, "textarea"), null);
    assert.match(one(container, ".code-lock")!.textContent ?? "", /read-only/);
  });
});

describe("its controls", () => {
  test("choosing a palette reports it upward", async () => {
    const chosen: string[] = [];
    const container = await render(
      <CodeViewer {...props({ onPalette: (name) => chosen.push(name) })} />,
    );
    const select = one(container, "select")!;
    await setValue(select as HTMLSelectElement, "monokai");
    assert.deepEqual(chosen, ["monokai"]);
  });

  test("the palette menu offers every palette the build has", async () => {
    const container = await render(<CodeViewer {...props()} />);
    assert.deepEqual(texts(container, "option"), [
      "Dark+ (default dark)",
      "Light+ (default light)",
      "Monokai",
    ]);
  });

  test("closing is reported upward", async () => {
    let closed = 0;
    const container = await render(<CodeViewer {...props({ onClose: () => (closed += 1) })} />);
    await click(one(container, ".code-close")!);
    assert.equal(closed, 1);
  });

  test("copy is offered, and is a no-op rather than a crash without a clipboard", async () => {
    // jsdom has no clipboard: the button must exist for the real window and
    // must not throw here.
    const container = await render(<CodeViewer {...props()} />);
    const button = all(container, "button").find((node) => node.textContent === "Copy")!;
    assert.ok(button, "no copy control");
    await click(button);
  });

  test("copy is disabled when there is nothing to copy", async () => {
    const container = await render(<CodeViewer {...props({ source: null, loading: true })} />);
    const button = all(container, "button").find((node) => node.textContent === "Copy")!;
    assert.equal((button as HTMLButtonElement).disabled, true);
  });
});
