/**
 * The pet card: its drawing, and what it does with what it is pushed.
 *
 * The window around it -- always-on-top, never activated, positioned in the
 * corner of the work area -- is `tests/unit/test_pet.py`'s, because it is the
 * host's and needs no DOM. What is here is the page: the geometry of the
 * character, and the one input it takes.
 */

import "./test-dom.js";
import assert from "node:assert/strict";
import { afterEach, describe, test } from "node:test";

import { act } from "react";

import { MARK_RECTS } from "./AppMark.js";
import { PET_EYES, PET_IDLE, PetCard, readStatus } from "./petcard.js";
import { all, one, render, wait } from "./test-render.js";

/** Stand in for the host, recording what the card asked it to do. */
let asked: string[] = [];

function insideHost(): void {
  asked = [];
  (window as unknown as Record<string, unknown>).pywebview = {
    api: {
      pet: (action: string) => {
        asked.push(action);
        return Promise.resolve({ open: true, wanted: true });
      },
    },
  };
}

/** The pushed-status entry point the host calls into. */
function push(status: unknown): void {
  const target = (window as unknown as Record<string, unknown>).__tonyAgent as {
    onStatus: (status: unknown) => void;
  };
  target.onStatus(status);
}

afterEach(() => {
  delete (window as unknown as Record<string, unknown>).pywebview;
  delete (window as unknown as Record<string, unknown>).__tonyAgent;
});

describe("the pet's eyes", () => {
  test("both are inside the head, which is the crossbar", () => {
    // The mark is a crossbar and a stem, and the eyes are placed on the crossbar
    // so the stem below reads as the body. An eye that spills past its edge is a
    // drawing bug that reads as a wink -- and a wink is not something this card
    // means, so the containment is the assertion rather than the coordinates.
    const head = MARK_RECTS[0];
    assert.ok(head, "the mark no longer has a crossbar to put eyes on");

    for (const eye of PET_EYES) {
      assert.ok(
        eye.cx - eye.r >= head.x && eye.cx + eye.r <= head.x + head.width,
        `an eye overhangs the head horizontally: ${JSON.stringify(eye)}`,
      );
      assert.ok(
        eye.cy - eye.r >= head.y && eye.cy + eye.r <= head.y + head.height,
        `an eye overhangs the head vertically: ${JSON.stringify(eye)}`,
      );
    }
  });

  test("there are two of them, and they are the same size", () => {
    assert.equal(PET_EYES.length, 2);
    assert.equal(PET_EYES[0].r, PET_EYES[1].r);
  });
});

describe("what the card draws with", () => {
  test("a status missing anything it needs is dropped for the idle one", () => {
    // The push crosses three hops to get here and this window is the last one: a
    // status without a label would render the word "undefined" on a card whose
    // entire job is to be glanceable at a look.
    for (const junk of [
      null,
      undefined,
      "working",
      42,
      {},
      { mood: "working" },
      { mood: "smug", label: "Label" },
      { mood: "working", label: "" },
      { mood: "working", label: 7 },
    ]) {
      assert.deepEqual(readStatus(junk), PET_IDLE, `took ${JSON.stringify(junk)}`);
    }
  });

  test("a good one passes through, and a missing detail is empty rather than undefined", () => {
    assert.deepEqual(readStatus({ mood: "working", label: "Running grep" }), {
      mood: "working",
      label: "Running grep",
      detail: "",
    });
    assert.deepEqual(readStatus({ mood: "waiting", label: "x", detail: "y" }), {
      mood: "waiting",
      label: "x",
      detail: "y",
    });
    assert.deepEqual(readStatus({ mood: "waiting", label: "x", detail: 9 }), {
      mood: "waiting",
      label: "x",
      detail: "",
    });
  });
});

describe("the card", () => {
  test("it says it is listening, once, before anything is pushed to it", async () => {
    // Order matters and is the deadlock guard's other half: the host flushes what
    // it remembered *during* `ready`, so a card that announced itself after
    // installing nothing would miss the first status entirely.
    insideHost();
    const container = await render(<PetCard />);
    await wait(0);

    assert.deepEqual(asked, ["ready"]);
    assert.match(container.innerHTML, /Ready when you are|TONYAgent/);
  });

  test("a pushed status is what the card shows, mood and words both", async () => {
    insideHost();
    const container = await render(<PetCard />);
    await wait(0);

    await act(async () => {
      push({ mood: "working", label: "Running read_file", detail: "src/app.py" });
    });

    const card = one(container, ".pet")!;
    assert.equal(card.getAttribute("data-mood"), "working");
    assert.equal(one(container, ".pet-label")!.textContent, "Running read_file");
    assert.equal(one(container, ".pet-detail")!.textContent, "src/app.py");
    assert.equal(all(container, "button").length, 0, "the card grew a button to compete with the drag");
  });

  test("the mood is on the root, because that is what the stylesheet reads", async () => {
    // The animations and the colours are selected by `[data-mood]`, so a mood that
    // reached the label but not the root would be a card that says "working" and
    // animates as if it were idle.
    insideHost();
    const container = await render(<PetCard />);
    await wait(0);
    assert.equal(one(container, ".pet")!.getAttribute("data-mood"), "idle");

    await act(async () => {
      push({ mood: "failed", label: "Stopped with an error", detail: "" });
    });
    assert.equal(one(container, ".pet")!.getAttribute("data-mood"), "failed");
  });

  test("pressing it raises the app", async () => {
    insideHost();
    const container = await render(<PetCard />);
    await wait(0);

    await act(async () => {
      one(container, ".pet")!.dispatchEvent(
        new window.MouseEvent("pointerdown", { bubbles: true }),
      );
    });
    await wait(0);

    assert.ok(
      asked.includes("focus"),
      `pressing the card asked for ${JSON.stringify(asked)}, so the app stays hidden`,
    );
  });
});
