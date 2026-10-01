/**
 * `Overlay` is the one place a dismissible surface's whole lifecycle lives, so
 * these assert the parts a caller cannot see and would otherwise only discover
 * by opening the app.
 *
 * The first one is here because of a bug that shipped: a dialog was rendered
 * inside an `Overlay` *and* carried one of its own, so the window behind the
 * user was scrimmed twice -- visibly darker than the design -- and the inner
 * backdrop was permanently `open`, which meant the dialog could never play its
 * exit no matter what closed it. Nothing about the markup looked wrong and no
 * existing test noticed; it took running the app. "Exactly one backdrop" is
 * now the invariant that would have caught it.
 */

import "./test-dom.js";
import assert from "node:assert/strict";
import { test } from "node:test";

import { render, rerender, click, one, all, wait } from "./test-render.js";
import { Overlay } from "./Overlay.js";
import { exitDurationMs } from "./useDelayedUnmount.js";

function state(container: HTMLElement): string | undefined {
  return one(container, ".modal-backdrop")?.dataset.state;
}

test("renders nothing at all before it has ever been open", async () => {
  const container = await render(
    <Overlay open={false}>
      <div className="modal">hi</div>
    </Overlay>,
  );
  assert.equal(one(container, ".modal-backdrop"), null);
  // A closed overlay that still rendered its children would keep a panel's
  // effects -- a fetch on mount, a focus call -- running for the whole session.
  assert.equal(one(container, ".modal"), null);
});

test("renders exactly one backdrop around its children", async () => {
  const container = await render(
    <Overlay open>
      <div className="modal">hi</div>
    </Overlay>,
  );
  assert.equal(all(container, ".modal-backdrop").length, 1);
  assert.equal(all(container, ".modal").length, 1);
  assert.equal(state(container), "open");
});

test("publishes open, then closed, while it lingers", async () => {
  const container = await render(
    <Overlay open>
      <div className="modal">hi</div>
    </Overlay>,
  );
  assert.equal(state(container), "open");

  await rerender(
    <Overlay open={false}>
      <div className="modal">hi</div>
    </Overlay>,
  );
  // Still here, still holding its content: this is the window the exit
  // animation plays in, and a dialog that emptied itself here would visibly
  // collapse while fading out.
  assert.equal(state(container), "closed");
  assert.equal(all(container, ".modal").length, 1);

  await wait(exitDurationMs() + 60);
  assert.equal(one(container, ".modal-backdrop"), null);
});

test("clicking the backdrop dismisses", async () => {
  let dismissed = 0;
  const container = await render(
    <Overlay open onDismiss={() => (dismissed += 1)}>
      <div className="modal">hi</div>
    </Overlay>,
  );
  await click(one(container, ".modal-backdrop")!);
  assert.equal(dismissed, 1);
});

test("a backdrop with no dismiss handler does not throw on click", async () => {
  // The confirmation is deliberately not dismissible: it is a decision, and a
  // stray click must not be readable as an answer.
  const container = await render(
    <Overlay open>
      <div className="modal">hi</div>
    </Overlay>,
  );
  await click(one(container, ".modal-backdrop")!);
  assert.equal(state(container), "open");
});

test("re-opening inside the exit window brings it straight back", async () => {
  const container = await render(
    <Overlay open>
      <div className="modal">hi</div>
    </Overlay>,
  );
  await rerender(
    <Overlay open={false}>
      <div className="modal">hi</div>
    </Overlay>,
  );
  await rerender(
    <Overlay open>
      <div className="modal">hi</div>
    </Overlay>,
  );
  await wait(exitDurationMs() + 60);
  assert.equal(state(container), "open", "the pending unmount was not cancelled");
});
