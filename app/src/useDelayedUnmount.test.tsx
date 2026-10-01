/**
 * `useDelayedUnmount` is the only thing standing between "closed" and
 * "animated closed". Every dismissible surface in this app renders
 * conditionally, so without a delay between the close and the unmount there is
 * no node left to fade out of and the disappearance is a hard cut.
 *
 * The assertions are all about the window in which the node is still present
 * *after* the caller said close -- the part that is easy to get wrong. A hook
 * that unmounts on the next tick, or one that forgets to re-arm and so never
 * unmounts at all, both pass a naive "is it gone now?" test.
 *
 * The default delay is read from `--motion-fast` rather than written down here,
 * so two of these tests put a stylesheet in the document instead of asserting a
 * literal: if the stylesheet and the hook ever disagree about how long an exit
 * takes, one of them is going to cut an animation off mid-frame, and that is a
 * test failure rather than something to notice by eye.
 *
 * Fake timers, not sleeps: the whole point is a delay measured in
 * milliseconds, and a real 140ms wait per assertion is both slower and less
 * precise than advancing the clock.
 */

import "./test-dom.js";
import assert from "node:assert/strict";
import { test } from "node:test";

import { act } from "react";

import { render, rerender, one } from "./test-render.js";
import { useDelayedUnmount, exitDurationMs } from "./useDelayedUnmount.js";
import { dom } from "./test-dom.js";

const DELAY = 150;

/**
 * A surface that reports what the hook said rather than what it drew.
 *
 * `data-mounted` instead of visible text so the assertion cannot pass because
 * some other node happened to contain the word.
 */
function Probe({ open, delay }: { open: boolean; delay?: number }) {
  const mounted = useDelayedUnmount(open, delay);
  return <div className="probe" data-mounted={String(mounted)} />;
}

function mounted(container: HTMLElement): string {
  return one(container, ".probe")!.dataset.mounted!;
}

/** Declare a `--motion-fast` for the duration of a test. */
function withToken(value: string): () => void {
  const style = dom.window.document.createElement("style");
  style.textContent = `:root { --motion-fast: ${value}; }`;
  dom.window.document.head.appendChild(style);
  return () => style.remove();
}

/** Make `matchMedia` answer `matches` for every query. jsdom has none. */
function withReducedMotion(matches: boolean): () => void {
  const had = Object.getOwnPropertyDescriptor(dom.window, "matchMedia");
  Object.defineProperty(dom.window, "matchMedia", {
    configurable: true,
    writable: true,
    value: () => ({ matches }),
  });
  return () => {
    if (had) Object.defineProperty(dom.window, "matchMedia", had);
    else delete (dom.window as unknown as Record<string, unknown>).matchMedia;
  };
}

test("is mounted on the first render when it starts open", async () => {
  const container = await render(<Probe open />);
  assert.equal(mounted(container), "true");
});

test("is not mounted on the first render when it starts closed", async () => {
  const container = await render(<Probe open={false} />);
  assert.equal(mounted(container), "false");
});

test("stays mounted after closing, then unmounts once the delay elapses", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  try {
    const container = await render(<Probe open delay={DELAY} />);
    assert.equal(mounted(container), "true");

    await rerender(<Probe open={false} delay={DELAY} />);
    // The point of the hook: closed, but still here, so there is something to
    // animate. Unmounting here would be the bug this hook exists to prevent.
    assert.equal(mounted(container), "true");

    await act(async () => {
      t.mock.timers.tick(DELAY);
    });
    assert.equal(mounted(container), "false");
  } finally {
    t.mock.timers.reset();
  }
});

test("does not unmount before the delay has fully elapsed", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  try {
    const container = await render(<Probe open delay={DELAY} />);
    await rerender(<Probe open={false} delay={DELAY} />);

    await act(async () => {
      t.mock.timers.tick(DELAY - 1);
    });
    assert.equal(mounted(container), "true");
  } finally {
    t.mock.timers.reset();
  }
});

test("re-opening before the delay elapses keeps it mounted", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  try {
    const container = await render(<Probe open delay={DELAY} />);
    await rerender(<Probe open={false} delay={DELAY} />);
    // Re-open inside the exit window: the pending unmount has to be cancelled,
    // or the surface vanishes out from under a user who reopened it. This is
    // the Escape-then-click-again case, and it is the one that separates a
    // hook that clears its timer from one that does not.
    await rerender(<Probe open delay={DELAY} />);

    await act(async () => {
      t.mock.timers.tick(DELAY * 2);
    });
    assert.equal(mounted(container), "true");
  } finally {
    t.mock.timers.reset();
  }
});

test("uses the caller's delay", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  try {
    const container = await render(<Probe open delay={40} />);
    await rerender(<Probe open={false} delay={40} />);

    await act(async () => {
      t.mock.timers.tick(39);
    });
    assert.equal(mounted(container), "true");

    await act(async () => {
      t.mock.timers.tick(1);
    });
    assert.equal(mounted(container), "false");
  } finally {
    t.mock.timers.reset();
  }
});

test("with no delay given, lingers past the animation the stylesheet declares", async (t) => {
  const restore = withToken("200ms");
  t.mock.timers.enable({ apis: ["setTimeout"] });
  try {
    const container = await render(<Probe open />);
    await rerender(<Probe open={false} />);

    // Exactly the declared animation length: still here. The animation ends
    // here, and a node removed on the same frame as the last frame is a node
    // that was cut off rather than one that finished.
    await act(async () => {
      t.mock.timers.tick(200);
    });
    assert.equal(mounted(container), "true");

    await act(async () => {
      t.mock.timers.tick(60);
    });
    assert.equal(mounted(container), "false");
  } finally {
    t.mock.timers.reset();
    restore();
  }
});

test("a duration declared in seconds is read as seconds", async (t) => {
  // Chromium re-serialises a custom property that holds a time, so a
  // stylesheet declaring `110ms` reads back as `0.11s`. jsdom keeps the text
  // as written, so this spelling has to be asserted here or nothing covers it:
  // parse the number, assume milliseconds, and every exit animation gets cut
  // off at 30ms of its 110ms while every test still passes.
  const restore = withToken("0.2s");
  t.mock.timers.enable({ apis: ["setTimeout"] });
  try {
    const container = await render(<Probe open />);
    await rerender(<Probe open={false} />);

    await act(async () => {
      t.mock.timers.tick(199);
    });
    assert.equal(mounted(container), "true", "0.2s was read as 0.2ms, not 200ms");

    await act(async () => {
      t.mock.timers.tick(61);
    });
    assert.equal(mounted(container), "false");
  } finally {
    t.mock.timers.reset();
    restore();
  }
});

test("an unreadable duration falls back instead of returning zero", () => {
  // A token that is empty, or is not a time at all, must not become a delay of
  // 0 -- that would silently turn every exit back into a hard cut.
  assert.equal(exitDurationMs(), 110 + 30);
});

test("reduced motion drops the surface at once instead of lingering", async (t) => {
  const restore = withReducedMotion(true);
  t.mock.timers.enable({ apis: ["setTimeout"] });
  try {
    const container = await render(<Probe open />);
    await rerender(<Probe open={false} />);

    // The stylesheet replaces every animation with `none` under reduced
    // motion, so there is nothing to wait for. Lingering anyway would leave a
    // ghost element exactly where the user asked for things not to linger.
    assert.equal(mounted(container), "false");
    await act(async () => {
      t.mock.timers.tick(1000);
    });
    assert.equal(mounted(container), "false");
  } finally {
    t.mock.timers.reset();
    restore();
  }
});

test("a normal motion preference still lingers", async (t) => {
  const restore = withReducedMotion(false);
  t.mock.timers.enable({ apis: ["setTimeout"] });
  try {
    const container = await render(<Probe open />);
    await rerender(<Probe open={false} />);
    assert.equal(mounted(container), "true");
  } finally {
    t.mock.timers.reset();
    restore();
  }
});
