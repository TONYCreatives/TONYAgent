/**
 * The bridge's two questions, which are not the same question.
 *
 * "Is a host here" and "is it ready" are one thing to a page in a browser and
 * two things under pywebview, because pywebview injects the bridge in halves:
 * `api.js` runs at document start and sets `window.pywebview = { ..., api: {} }`,
 * and `finish.js` calls `_createApi(...)` to put the methods on that object and
 * only *then* dispatches `pywebviewready`. Between those two injections the
 * object is truthy and empty.
 *
 * A page whose script wins that race used to take the empty object for a host:
 * `whenHostReady` short-circuited on it, `start()` called `api.ready()`, and the
 * window opened with `TypeError: a.ready is not a function` across the top of
 * it. Nothing about that sentence names the race, or pywebview, or which of the
 * two questions was answered wrongly.
 */

import "./test-dom.js";
import assert from "node:assert/strict";
import { afterEach, describe, test } from "node:test";

import { CoreBackend } from "./backend.js";
import { host, whenHostReady, type HostApi } from "./bridge.js";
import { dom } from "./test-dom.js";

const { window: domWindow } = dom;

/** Enough of the api to be one: `ready` is the sentinel, `send` is the traffic. */
const api = () =>
  ({
    send: async () => ({ ok: true }),
    ready: async () => ({ ok: true }),
  }) as unknown as HostApi;

function place(value: unknown): void {
  (domWindow as unknown as Record<string, unknown>).pywebview = value;
}

function ready(): void {
  domWindow.dispatchEvent(new domWindow.CustomEvent("pywebviewready"));
}

afterEach(() => {
  delete (domWindow as unknown as Record<string, unknown>).pywebview;
});

describe("is a host here", () => {
  test("pywebview's empty placeholder is not one", () => {
    place({ api: {} });
    assert.equal(host(), null, "an api with no methods was taken for a host");
  });

  test("no pywebview at all is not one either", () => {
    assert.equal(host(), null);
  });

  test("an api with the methods is", () => {
    place({ api: api() });
    assert.ok(host());
  });
});

describe("waiting for one", () => {
  test("the placeholder is waited past rather than handed over", async () => {
    // The race in the order it happens: the empty object first, the methods and
    // the event after.
    place({ api: {} });
    const waiting = whenHostReady(20);
    place({ api: api() });
    ready();

    const found = await waiting;
    assert.ok(found, "the populated api was not handed over");
    assert.equal(typeof found!.ready, "function");
  });

  test("a page with no host at all is answered rather than left hanging", async () => {
    // The half the timeout exists for: a browser preview, a `vite dev` session
    // and every test in this directory run this page with no host, and each
    // needs an answer rather than a promise that can never settle.
    assert.equal(await whenHostReady(20), null);
  });

  test("a slow bridge is waited for rather than called absent", async () => {
    // An empty `api` with a `pywebview` beside it is a bridge *being built*, so
    // the wait re-arms instead of answering null. Without that, a cold start
    // slower than the timeout would say "No window host answered" about a window
    // that was about to work -- a worse sentence than the one this replaced.
    place({ api: {} });
    const waiting = whenHostReady(20);
    await new Promise((resolve) => setTimeout(resolve, 90));
    place({ api: api() });
    ready();

    assert.ok(await waiting, "the slow bridge was given up on");
  });
});

describe("the window's own startup", () => {
  test("it survives the placeholder arriving first", async () => {
    // The symptom end to end: the banner read `a.ready is not a function`, and
    // this is that race reaching `start()`.
    place({ api: {} });
    const backend = new CoreBackend();
    const starting = backend.start();
    place({ api: api() });
    ready();

    await starting; // must not throw
  });
});
