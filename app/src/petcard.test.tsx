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

import { MARK_RECTS, MARK_VIEWBOX } from "./AppMark.js";
import {
  eyesFor,
  PET_DESK,
  PET_EYES,
  PET_FRAME,
  PET_IDLE,
  PetCard,
  PET_ZS,
  PET_Z_RISE,
  readStatus,
  WIDE_EYE_SCALE,
} from "./petcard.js";
import { SLEEP_AFTER_MS } from "./pet-status.js";
import { all, one, render, wait } from "./test-render.js";

/** Stand in for the host, recording what the card asked it to do. */
let asked: string[] = [];
/** What the next drag reports: whether the OS's move loop actually moved it. */
let dragMoved = false;

function insideHost(): void {
  asked = [];
  dragMoved = false;
  (window as unknown as Record<string, unknown>).pywebview = {
    api: {
      pet: (action: string) => {
        asked.push(action);
        // A drag answers with the position and whether it moved; every other
        // action answers with the two booleans. See `PetDragReply`.
        return Promise.resolve(
          action === "drag"
            ? { moved: dragMoved, x: 900, y: 700 }
            : { open: true, wanted: true },
        );
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

/**
 * The card's sleep clock, caught rather than waited on.
 *
 * `SLEEP_AFTER_MS` is ninety seconds and the test needs the pose on the other side
 * of it, so the global `setTimeout` is wrapped and the card's own long timer is
 * recorded instead of run. Everything else -- React's scheduling, the card's
 * `ready` retries at 250ms -- passes straight through, which is what keeps this
 * from being a fake clock the rest of the test has to think about.
 *
 * Asserted on rather than assumed: a test that waits on a timer it never captured
 * would sit on a ninety-second delay and *pass*, which is the failure mode this
 * helper exists to make impossible.
 */
let sleepTimer: (() => void) | null = null;
let sleepDelays: number[] = [];
/** Set while a test has the global `setTimeout` wrapped; cleared by `afterEach`. */
let restoreTimers: (() => void) | null = null;

function captureSleepTimers(): () => void {
  const real = window.setTimeout;
  sleepTimer = null;
  sleepDelays = [];
  window.setTimeout = ((fn: () => void, ms?: number) => {
    if (ms === SLEEP_AFTER_MS) {
      sleepTimer = fn;
      sleepDelays.push(ms);
      return 0 as unknown as number;
    }
    return real(fn as never, ms);
  }) as typeof window.setTimeout;
  return () => {
    window.setTimeout = real;
  };
}

/** How long the clock that is armed right now was set for, or null if none is. */
function sleepTimerDelay(): number | null {
  return sleepDelays.length ? sleepDelays[sleepDelays.length - 1] : null;
}

/** Run the armed sleep clock, which is what ninety quiet seconds would do. */
async function fireSleepTimer(): Promise<void> {
  assert.ok(sleepTimer, "the card never armed its sleep clock");
  await act(async () => {
    sleepTimer!();
  });
}

afterEach(() => {
  restoreTimers?.();
  restoreTimers = null;
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

describe("the frame the character is drawn in", () => {
  test("it contains everything drawn, so nothing is clipped", () => {
    // The frame is the drawing's own bounds rather than the mark's 1024-unit
    // canvas, and the whole risk of cropping is a pose that leaves it: an eye cut
    // by the edge reads as a wink, which this card does not mean.
    const left = PET_FRAME.x;
    const top = PET_FRAME.y;
    const right = left + PET_FRAME.width;
    const bottom = top + PET_FRAME.height;

    const inside = (x: number, y: number, what: string) => {
      assert.ok(x >= left && x <= right, `${what} is outside the frame horizontally at ${x}`);
      assert.ok(y >= top && y <= bottom, `${what} is outside the frame vertically at ${y}`);
    };

    for (const rect of MARK_RECTS) {
      inside(rect.x, rect.y, "the mark");
      inside(rect.x + rect.width, rect.y + rect.height, "the mark");
    }
    for (const eye of eyesFor("waiting")) {
      inside(eye.cx - eye.r, eye.cy - eye.r, "a wide eye");
      inside(eye.cx + eye.r, eye.cy + eye.r, "a wide eye");
    }
    inside(PET_DESK.x, PET_DESK.y, "the keyboard");
    inside(PET_DESK.x + PET_DESK.width, PET_DESK.y + PET_DESK.height, "the keyboard");

    assert.equal(PET_FRAME.width, PET_FRAME.height, "a non-square frame would stretch it");
    assert.ok(
      PET_FRAME.height < MARK_VIEWBOX,
      "the frame is the whole canvas again, so a third of the figure is empty",
    );
  });

  test("the Zs have the whole of their rise to travel through", () => {
    // `PET_Z_RISE` is in `pet.css` and the frame is here, so the two are a pair
    // held together by this assertion rather than by a comment. The first version
    // failed it in the other direction: the Zs crossed the head, which is near-white
    // where they are grey.
    const highest = Math.min(...PET_ZS.map((z) => z.y));
    assert.ok(
      highest - PET_Z_RISE >= PET_FRAME.y,
      `the Zs rise ${PET_Z_RISE} from ${highest}, past the frame's top at ${PET_FRAME.y}`,
    );
  });

  test("no Z is drawn over the head", () => {
    // The head is the crossbar, drawn in the card's foreground colour -- a Z over
    // it is a light grey glyph on a near-white bar, which is what made the first
    // version's Zs invisible. They rise above it now, and the invariant is the
    // rectangle test rather than "above" or "beside": whichever arrangement a later
    // change picks, the glyph and the bar must not meet, and the whole rise is
    // included because a Z travels as it fades.
    const head = MARK_RECTS[0]!;
    const bar = {
      left: head.x,
      top: head.y,
      right: head.x + head.width,
      bottom: head.y + head.height,
    };

    for (const z of PET_ZS) {
      const box = {
        left: z.x,
        top: z.y - PET_Z_RISE,
        right: z.x + 44 * z.scale,
        bottom: z.y + 34 * z.scale,
      };
      const overlaps =
        box.left < bar.right &&
        bar.left < box.right &&
        box.top < bar.bottom &&
        bar.top < box.bottom;
      assert.ok(
        !overlaps,
        `a Z at ${JSON.stringify(z)} is drawn over the head ${JSON.stringify(bar)}`,
      );
    }
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
    // The lamp's colour is selected by `[data-mood]`, so a mood that reached the
    // label but not the root would be a card that says "working" and is painted as
    // if it were idle.
    insideHost();
    const container = await render(<PetCard />);
    await wait(0);
    assert.equal(one(container, ".pet")!.getAttribute("data-mood"), "idle");

    await act(async () => {
      push({ mood: "failed", label: "Stopped with an error", detail: "" });
    });
    assert.equal(one(container, ".pet")!.getAttribute("data-mood"), "failed");
  });

  test("the pose is on the root too, and it is what moves", async () => {
    // Two vocabularies on one element: `data-mood` is the agent's word and paints
    // the lamp, `data-pose` is the character's and drives every animation. They
    // agree until the card falls asleep, which is the only pose no status sends.
    insideHost();
    const container = await render(<PetCard />);
    await wait(0);

    await act(async () => {
      push({ mood: "working", label: "Running grep", detail: "" });
    });

    const card = one(container, ".pet")!;
    assert.equal(card.getAttribute("data-mood"), "working");
    assert.equal(card.getAttribute("data-pose"), "working");
  });

  test("pressing it drags it, and raising the app is the click half", async () => {
    // The card is its own handle now, so a press starts the OS's move loop. The
    // loop swallows every event until the user lets go, which is why the *host*
    // answers whether the card moved: that answer is the only thing left that can
    // tell a drag from a click.
    insideHost();
    const container = await render(<PetCard />);
    await wait(0);

    await act(async () => {
      one(container, ".pet")!.dispatchEvent(
        new window.MouseEvent("pointerdown", { bubbles: true }),
      );
    });
    await wait(0);

    assert.ok(asked.includes("drag"), `pressing the card asked for ${JSON.stringify(asked)}`);
    assert.ok(
      asked.includes("focus"),
      "a press that moved nothing must still open the app -- the click event never arrives",
    );
  });

  test("a press that moved the card does not also raise the app", async () => {
    // Otherwise dragging the pet out of the way would throw the app into the
    // foreground every time, which is the opposite of what the card is for.
    insideHost();
    dragMoved = true;
    const container = await render(<PetCard />);
    await wait(0);

    await act(async () => {
      one(container, ".pet")!.dispatchEvent(
        new window.MouseEvent("pointerdown", { bubbles: true }),
      );
    });
    await wait(0);

    assert.ok(asked.includes("drag"));
    assert.ok(!asked.includes("focus"), `a drag raised the app: ${JSON.stringify(asked)}`);
  });
});

describe("the character", () => {
  /** The parts of the drawing, by the class the stylesheet animates. */
  const parts = (container: HTMLElement) => ({
    eyes: all(container, ".pet-eye").length,
    lids: all(container, ".pet-lid path").length,
    cross: all(container, ".pet-cross path").length,
    hands: all(container, ".pet-hand").length,
    keys: all(container, ".pet-key").length,
    zs: all(container, ".pet-z").length,
  });

  const withStatus = async (status: Record<string, unknown>) => {
    insideHost();
    // Caught before the mount, because the clock is armed by an effect: a
    // capture installed afterwards would be watching a timer nobody set.
    restoreTimers = captureSleepTimers();
    const container = await render(<PetCard />);
    await wait(0);
    await act(async () => {
      push(status);
    });
    return container;
  };

  test("idle is a face and nothing else", async () => {
    const container = await withStatus({ mood: "idle", label: "Ready when you are", detail: "" });
    assert.deepEqual(parts(container), {
      eyes: 2,
      lids: 0,
      cross: 0,
      hands: 0,
      keys: 0,
      zs: 0,
    });
  });

  test("working is a keyboard in front of it, with both hands on it", async () => {
    const container = await withStatus({ mood: "working", label: "Running grep", detail: "" });

    assert.equal(parts(container).hands, 2, "a keyboard with nobody at it");
    assert.equal(parts(container).keys, 4, "four keys is what reads as a keyboard at this size");
    assert.equal(parts(container).eyes, 2, "it is awake and looking at the screen");
    assert.equal(parts(container).zs, 0, "the Zs are for the other pose");
  });

  test("the hands type out of phase, or it is a flap rather than two hands", async () => {
    const container = await withStatus({ mood: "working", label: "Running grep", detail: "" });
    const delays = all(container, ".pet-hand").map(
      (hand) => (hand as unknown as SVGElement).style.animationDelay,
    );
    assert.equal(delays.length, 2);
    assert.notEqual(delays[0], delays[1], `both hands are on the same delay: ${delays.join(", ")}`);
  });

  test("the wide eyes of a card that wants you are geometry, not a transform", async () => {
    // The blink owns the one transform these elements have, so a CSS scale here
    // would be overwritten by the next blink -- a wide eye that closes to normal
    // width and stays there.
    const idle = eyesFor("idle");
    const waiting = eyesFor("waiting");

    assert.equal(waiting.length, 2);
    assert.ok(waiting[0].r > idle[0].r, "waiting is not wider than idle");
    assert.equal(waiting[0].r / idle[0].r, WIDE_EYE_SCALE);
    assert.equal(waiting[0].cy, idle[0].cy, "an eye moved while it widened");
  });

  test("a failure is crossed out rather than looked at", async () => {
    const container = await withStatus({ mood: "failed", label: "Stopped", detail: "" });

    assert.equal(parts(container).cross, 4, "two strokes per eye");
    assert.equal(parts(container).eyes, 0, "open eyes were drawn under the cross");
  });

  test("asleep is shut lids, three Zs, and no open eyes", async () => {
    const container = await withStatus({ mood: "idle", label: "Ready", detail: "" });
    await fireSleepTimer();

    assert.equal(parts(container).lids, 2, "the eyes are not shut");
    assert.equal(parts(container).eyes, 0, "open eyes were drawn under the lids");
    assert.equal(parts(container).zs, 3);
    assert.equal(one(container, ".pet")!.getAttribute("data-pose"), "asleep");
    // The mood is still the wire's word: nothing invented "asleep" as a status.
    assert.equal(one(container, ".pet")!.getAttribute("data-mood"), "idle");
  });

  test("the keyboard goes away when the work does", async () => {
    const container = await withStatus({ mood: "working", label: "Running grep", detail: "" });
    assert.equal(parts(container).hands, 2);

    await act(async () => {
      push({ mood: "idle", label: "Ready when you are", detail: "" });
    });

    assert.equal(parts(container).hands, 0, "the desk outlived the work");
    assert.equal(parts(container).keys, 0);
  });

  test("a push restarts the quiet clock", async () => {
    // Otherwise the card falls asleep 90 seconds after it opened no matter how
    // much has happened since.
    const container = await withStatus({ mood: "idle", label: "Ready", detail: "" });
    const first = sleepTimerDelay();
    assert.equal(first, SLEEP_AFTER_MS);

    await act(async () => {
      push({ mood: "idle", label: "Ready", detail: "" });
    });

    assert.equal(one(container, ".pet")!.getAttribute("data-pose"), "idle");
    assert.equal(sleepTimerDelay(), SLEEP_AFTER_MS, "no second clock was armed");
  });
});
