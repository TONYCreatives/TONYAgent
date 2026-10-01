/**
 * Mount a component, drive it like a person, and take it down again.
 *
 * The three things every component test in this repo does are the same three
 * things: create a root inside jsdom, dispatch real DOM events at it, and
 * unmount between tests so one test's state cannot reach the next. Copying that
 * per file is how three copies of the same subtle bug happen -- particularly
 * the native-value-setter dance below, which every file would have to get
 * right on its own.
 *
 * This module imports `./test-dom.js` for its side effect, so a test file that
 * imports this one still gets the DOM in place before react-dom is evaluated.
 * The order matters: React decides whether it is in a browser at import time.
 */

import "./test-dom.js";
import { afterEach } from "node:test";

import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";

import { dom } from "./test-dom.js";

const { window } = dom;

/** Unmount whatever the last test rendered. */
let root: Root | null = null;

afterEach(async () => {
  if (root) {
    const current = root;
    root = null;
    await act(async () => {
      current.unmount();
    });
  }
  window.document.body.innerHTML = "";
});

/** Render `element` into a fresh container and return that container. */
export async function render(element: ReactNode): Promise<HTMLElement> {
  const container = window.document.createElement("div");
  window.document.body.appendChild(container);
  root = createRoot(container);
  await act(async () => {
    root!.render(element);
  });
  return container;
}

/**
 * Re-render the same root with a new element.
 *
 * Separate from `render` on purpose. The rules being tested in the transcript
 * are all about what a *new* message does to an existing panel -- a fold on
 * `reasoning.completed`, or the absence of one after a manual unfold -- and
 * those are invisible if every step mounts a fresh component, because the fold
 * is a decision the component made last time.
 */
export async function rerender(element: ReactNode): Promise<void> {
  await act(async () => {
    root!.render(element);
  });
}

/**
 * Let real time pass while React is still told it is inside `act`.
 *
 * Some of the app's behaviour is measured in milliseconds -- a dismissed
 * overlay stays in the DOM for the length of its exit animation -- so a test
 * that wants to see the *end* state has to wait for it, not just re-render.
 *
 * The wait is wrapped in `act` because the timer callback updates React state.
 * An update outside `act` is a warning at best and an unflushed render at
 * worst, and the assertion after it would then be testing a component that had
 * not actually changed.
 */
export async function wait(ms: number): Promise<void> {
  await act(async () => {
    await new Promise((resolve) => dom.window.setTimeout(resolve, ms));
  });
}

/** Click an element the way a person would. */
export async function click(element: Element): Promise<void> {
  await act(async () => {
    (element as HTMLElement).click();
  });
}

/** Fire a context menu at a row. */
export async function contextMenu(
  element: Element,
  position: { clientX: number; clientY: number } = { clientX: 40, clientY: 20 },
): Promise<void> {
  await act(async () => {
    element.dispatchEvent(
      new window.MouseEvent("contextmenu", { bubbles: true, ...position }),
    );
  });
}

/**
 * Press the pointer somewhere, which is how a menu is dismissed.
 *
 * Deliberately not `click`. jsdom synthesises `click` but not the `pointerdown`
 * that a component listens for, so clicking a test body can leave a menu open
 * and the assertion that follows passes for the wrong reason.
 */
export async function pointerDown(element: Element): Promise<void> {
  await act(async () => {
    element.dispatchEvent(
      new dom.window.MouseEvent("pointerdown", { bubbles: true }),
    );
  });
}

/**
 * Move focus off a field.
 *
 * `onBlur` is a synthetic React event delivered as a bubbling `focusout`, so
 * `.blur()` on the node is the real thing and `dispatchEvent("blur")` would be a
 * different event entirely.
 */
export async function blur(element: HTMLElement): Promise<void> {
  await act(async () => {
    element.blur();
  });
}

/** Press a key, bubbling from `element` (or the window when omitted). */
export async function press(key: string, element?: Element): Promise<void> {
  await act(async () => {
    const event = new window.KeyboardEvent("keydown", { key, bubbles: true });
    (element ?? window).dispatchEvent(event);
  });
}

/**
 * Set a field's value the way a browser reports a keystroke.
 *
 * Assigning `input.value` patches the DOM node's own property without notifying
 * React -- React listens for the `input` event -- so the native setter from the
 * prototype is used, exactly as a browser would. Without this, a test types into
 * a component that works perfectly well and then asserts on a value React never
 * saw.
 *
 * A `<select>` is different: React's `onChange` for one is wired to `change`,
 * not `input`, and the value has to be set to a real option or the assignment
 * is rejected outright.
 */
export async function setValue(
  field: HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement,
  value: string,
): Promise<void> {
  const isSelect = field instanceof dom.window.HTMLSelectElement;
  const isTextArea = field instanceof dom.window.HTMLTextAreaElement;
  // A textarea has its own value setter. Reusing the input's would set the
  // property on the wrong prototype and the node React is holding would never
  // see the text -- a test typing into the composer and asserting on a
  // message that was never sent.
  const prototype = isSelect
    ? dom.window.HTMLSelectElement.prototype
    : isTextArea
      ? dom.window.HTMLTextAreaElement.prototype
      : dom.window.HTMLInputElement.prototype;
  const setter = Object.getOwnPropertyDescriptor(prototype, "value")!.set!;
  await act(async () => {
    setter.call(field, value);
    field.dispatchEvent(
      new window.Event(isSelect ? "change" : "input", { bubbles: true }),
    );
  });
}

/** Every element matching `selector`, as a real array. */
export function all(container: ParentNode, selector: string): HTMLElement[] {
  return [...container.querySelectorAll<HTMLElement>(selector)];
}

/** The first element matching `selector`, or a test failure with a reason. */
export function one(container: ParentNode, selector: string): HTMLElement | null {
  return container.querySelector<HTMLElement>(selector);
}

/** Text content of every element matching `selector`. */
export function texts(container: ParentNode, selector: string): (string | null)[] {
  return all(container, selector).map((node) => node.textContent);
}
