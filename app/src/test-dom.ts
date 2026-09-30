/**
 * A DOM, installed as a side effect, for the component tests.
 *
 * This has to be its own module, imported *before* react-dom. React DOM works
 * out whether it is running in a browser while it is being imported -- it sets
 * an internal "can I use the DOM" flag at module scope -- so a jsdom created
 * after that import is a document React has already decided does not exist.
 *
 * ES modules evaluate imports in order, so a test file whose first import is
 * this one gets the DOM in place in time. Doing the same setup inline in the
 * test file would not work: imports are hoisted above the module body, so the
 * `new JSDOM(...)` would run after react-dom had already been evaluated.
 *
 * jsdom rather than a hand-rolled stub, because what is being tested here is
 * React's own event delegation -- a synthetic `onBlur` is delivered as a
 * bubbling `focusout`, and only a real DOM reproduces that faithfully.
 */

import { JSDOM } from "jsdom";

const dom = new JSDOM("<!doctype html><html><body></body></html>", {
  pretendToBeVisual: true,
  url: "http://localhost/",
});

const globals = globalThis as unknown as Record<string, unknown>;

globals.window = dom.window;
globals.document = dom.window.document;
globals.getComputedStyle = dom.window.getComputedStyle.bind(dom.window);
globals.requestAnimationFrame = dom.window.requestAnimationFrame.bind(dom.window);
globals.cancelAnimationFrame = dom.window.cancelAnimationFrame.bind(dom.window);

for (const name of [
  "Event",
  "CustomEvent",
  "MouseEvent",
  "KeyboardEvent",
  "FocusEvent",
  "InputEvent",
  "Node",
  "Element",
  "HTMLElement",
  "HTMLInputElement",
  "HTMLButtonElement",
]) {
  globals[name] = (dom.window as unknown as Record<string, unknown>)[name];
}

// `navigator` is a read-only getter on modern Node, so a plain assignment
// throws. React does not read it for rendering, but jsdom's own focus and
// event code touches `window.navigator`, which is already set above; this is
// only here so a stray global read does not take the process down.
try {
  Object.defineProperty(globalThis, "navigator", {
    value: dom.window.navigator,
    configurable: true,
  });
} catch {
  // Node refused; not fatal for these tests.
}

/**
 * Tells React that `act()` is legal here.
 *
 * Without it React warns on every update and, in React 19, refuses to run
 * effects synchronously -- which would make the assertions below test the
 * wrong timing.
 */
globals.IS_REACT_ACT_ENVIRONMENT = true;

export { dom };
