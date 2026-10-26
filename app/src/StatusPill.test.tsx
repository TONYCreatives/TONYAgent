/**
 * The run pill: the window's one live state.
 *
 * Two things it must not become. It must not be a *reporter only* in Agent --
 * the panel's handle lives here, and a handle that appears only while something
 * runs is a handle nobody learns. And it must not vanish in the other modes when
 * a turn is running: a working dot that does nothing is worse than a dot that
 * takes you to the transcript where the work is.
 */

import "./test-dom.js";
import assert from "node:assert/strict";
import { describe, test } from "node:test";

import { StatusPill } from "./StatusPill.js";
import { all, click, one, render } from "./test-render.js";

const pillOf = (container: HTMLElement) =>
  one(container, ".statuspill") as HTMLButtonElement | null;
const label = (container: HTMLElement) =>
  pillOf(container)?.getAttribute("aria-label") ?? "";
/**
 * What the pill reads, as a person reads it.
 *
 * Scoped to the container, and assembled from the two named parts: the pill
 * itself is one element, so its `textContent` arrives as "Working·read_file"
 * with no space -- the separator is a glyph between two spans, not a word. The
 * dot is the piece this helper exists to supply.
 */
const text = (container: HTMLElement) =>
  all(container, ".statuspill-state, .statuspill-detail")
    .map((node) => (node.textContent ?? "").trim())
    .filter(Boolean)
    .join(" · ");

describe("in the view with a run panel", () => {
  test("idle is still a button, and it opens the panel", async () => {
    let toggles = 0;
    const container = await render(
      <StatusPill
        run="idle"
        detail=""
        panel={{ open: false, onToggle: () => (toggles += 1) }}
        onReturn={() => {}}
      />,
    );

    assert.equal(text(container), "Idle");
    assert.match(label(container), /^Idle\. Show the run panel$/);
    assert.equal(
      pillOf(container)?.getAttribute("aria-expanded"),
      "false",
    );

    await click(pillOf(container)!);
    assert.equal(toggles, 1);
  });

  test("open says so, and the word becomes the way to close it", async () => {
    const container = await render(
      <StatusPill
        run="idle"
        detail=""
        panel={{ open: true, onToggle: () => {} }}
        onReturn={() => {}}
      />,
    );
    assert.equal(
      pillOf(container)?.getAttribute("aria-expanded"),
      "true",
    );
    assert.match(label(container), /Hide the run panel/);
  });

  test("working carries the tool it is running", async () => {
    const container = await render(
      <StatusPill
        run="working"
        detail="read_file"
        panel={{ open: false, onToggle: () => {} }}
        onReturn={() => {}}
      />,
    );
    assert.equal(text(container), "Working · read_file");
    assert.match(label(container), /Working, read_file\. Show the run panel/);
    assert.equal(
      pillOf(container)?.getAttribute("data-run"),
      "working",
    );
  });

  test("waiting and error are their own states, not a generic busy", async () => {
    for (const [run, word] of [
      ["waiting", "Waiting"],
      ["error", "Error"],
    ] as const) {
      const container = await render(
        <StatusPill
          run={run}
          detail=""
          panel={{ open: false, onToggle: () => {} }}
          onReturn={() => {}}
        />,
      );
      assert.equal(text(container), word);
      assert.equal(
        pillOf(container)?.getAttribute("data-run"),
        run,
      );
    }
  });

  test("the tool name is only shown while working", async () => {
    const container = await render(
      <StatusPill
        run="waiting"
        detail="read_file"
        panel={{ open: false, onToggle: () => {} }}
        onReturn={() => {}}
      />,
    );
    assert.equal(all(container, ".statuspill-detail").length, 0);
  });
});

describe("in a view without a run panel", () => {
  test("nothing running means nothing drawn", async () => {
    const container = await render(
      <StatusPill run="idle" detail="" onReturn={() => {}} />,
    );
    assert.equal(all(container, ".statuspill").length, 0);
  });

  test("a running turn is a signpost back to the conversation", async () => {
    let returns = 0;
    const container = await render(
      <StatusPill
        run="working"
        detail="apply_patch"
        onReturn={() => (returns += 1)}
      />,
    );
    const pill = pillOf(container)!;
    // A dot, not a report: the words belong to the transcript, which is a mode
    // away. The name still carries them, because that is what a reader hears.
    assert.equal(pill.classList.contains("is-dot"), true);
    assert.equal(text(container), "", "the pill reports a turn it cannot show");
    assert.equal(pill.hasAttribute("aria-expanded"), false);
    assert.match(label(container), /Working, apply_patch\. Show the conversation$/);

    await click(pill);
    assert.equal(returns, 1);
  });

  test("waiting and error are signposts too, not silence", async () => {
    for (const run of ["waiting", "error"] as const) {
      const container = await render(
        <StatusPill run={run} detail="" onReturn={() => {}} />,
      );
      assert.equal(all(container, ".statuspill").length, 1, `${run} drew nothing`);
    }
  });
});
