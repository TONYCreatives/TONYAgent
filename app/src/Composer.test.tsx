/**
 * The composer's own controls: the mode pills, the model chip, the tool
 * budget, the attach button, send and stop.
 *
 * **The thinking-effort dial used to be tested here and is not any more.**
 * It moved to the settings panel, where it is drawn from the same parts as
 * the permission menu, so its tests are in SettingsMenus.test.tsx next to
 * that menu's. A second copy of them here would be a second place for the
 * two to drift apart, which is what the shared component exists to stop.
 *
 * The mode pills follow one rule worth keeping here: the displayed mode is
 * whatever the core last reported, never a local guess written the instant
 * a value was clicked. A local value would keep showing the mode the user
 * asked for even after the core refused it.
 */

import "./test-dom.js";
import assert from "node:assert/strict";
import { describe, test } from "node:test";
import { createRef, type RefObject } from "react";

import { Composer, type ModeInfo } from "./Composer.js";
import { click, one, press, render, setValue } from "./test-render.js";
import { dom } from "./test-dom.js";

const MODES: ModeInfo[] = [
  { name: "build", label: "Build", description: "Anything goes", writes: true },
  { name: "plan", label: "Plan", description: "Read only", writes: false },
];

/** Mount a composer and record what it asks the core to do. */
async function composer(props: {
  busy?: boolean;
  disabled?: boolean;
  maxToolCalls?: number | null;
  /** Injected by the window when it needs to move the caret here. */
  inputRef?: RefObject<HTMLTextAreaElement | null>;
}) {
  const calls = { sent: [] as string[], cancelled: 0 };
  const container = await render(
    <Composer
      inputRef={props.inputRef}
      busy={props.busy ?? false}
      disabled={props.disabled ?? false}
      modes={MODES}
      mode="build"
      onModeChange={() => {}}
      onSend={(text, files) => calls.sent.push(text || `(${files.length} files)`)}
      onCancel={() => {
        calls.cancelled += 1;
      }}
      maxToolCalls={props.maxToolCalls ?? 10}
      budgetOpen={false}
      onBudgetOpen={() => {}}
      onBudgetClose={() => {}}
      onBudgetChange={() => {}}
    />,
  );
  return { container, calls };
}

const sendButton = (container: HTMLElement) =>
  one(container, ".send-btn") as HTMLButtonElement | null;

const stopButton = (container: HTMLElement) =>
  one(container, ".stop-btn") as HTMLButtonElement | null;

const messageField = (container: HTMLElement) =>
  one(container, ".composer-inner textarea") as HTMLTextAreaElement | null;

// --- what the send button says --------------------------------------------
/*
 * The send button used to render the word "Continue". That is a word from
 * somewhere else entirely -- it is not what the button does, and a user
 * reading it has to work out the translation. It was also a `<button>` whose
 * only label was text, so the moment it became an icon the name would have
 * gone with it. These assert the icon carries a name, not that it looks a
 * certain way, because the name is the part that is actually load-bearing.
 */
describe("the send button", () => {
  test("it does not read Continue", async () => {
    const { container } = await composer({ });
    const text = (container as HTMLElement).textContent ?? "";
    assert.equal(
      text.includes("Continue"),
      false,
      'the button still offers a word for a different action',
    );
  });

  test("it is named for a screen reader, since a bare icon is not a control", async () => {
    const { container } = await composer({ });
    const button = sendButton(container)!;
    assert.ok(button, "no send button rendered");
    assert.equal(button.getAttribute("aria-label"), "Send");
    assert.equal(button.getAttribute("title"), "Send");
  });

  test("the icon is hidden from assistive tech, because the name is the label", async () => {
    const { container } = await composer({ });
    const svg = one(sendButton(container)!, "svg")!;
    assert.equal(svg.getAttribute("aria-hidden"), "true");
  });

  test("clicking it sends what was typed", async () => {
    const { container, calls } = await composer({ });
    await setValue(messageField(container)!, "list the files in src/core");
    await click(sendButton(container)!);
    assert.deepEqual(calls.sent, ["list the files in src/core"]);
  });

  test("it is the same action from the keyboard", async () => {
    const { container, calls } = await composer({ });
    await setValue(messageField(container)!, "hello");
    await press("Enter", messageField(container)!);
    assert.deepEqual(calls.sent, ["hello"], "Enter no longer sends");
  });

  test("an empty message is not sent", async () => {
    // Not an error worth surfacing; the button just does nothing, as before.
    const { container, calls } = await composer({ });
    await click(sendButton(container)!);
    assert.deepEqual(calls.sent, []);
  });

  test("whitespace is not a message either", async () => {
    const { container, calls } = await composer({ });
    await setValue(messageField(container)!, "   \n  ");
    await click(sendButton(container)!);
    assert.deepEqual(calls.sent, []);
  });

  test("it is disabled when the window is disabled", async () => {
    const { container } = await composer({ disabled: true });
    assert.equal(sendButton(container)!.disabled, true);
  });
});

// --- while the agent is working -------------------------------------------
describe("the send button while the agent is working", () => {
  test("send is replaced by Stop, not merely disabled", async () => {
    // Showing a dead send button next to a live Stop button reads as "you can
    // interrupt" and "you can also send", which is only half true.
    const { container } = await composer({ busy: true });
    assert.equal(sendButton(container), null, "a send button survived into a busy turn");
    // Named by an icon now, so the name lives in the accessibility tree rather
    // than in the pixels -- which is the only place it can still be read.
    assert.equal(stopButton(container)!.getAttribute("aria-label"), "Stop");
  });

  test("Stop occupies the send button's own box", async () => {
    // It used to be a `.btn` -- a pill with the word "Stop" in it -- sitting in
    // the send button's slot, so it was wider than the icon it replaced and the
    // control row reflowed every time a turn started, dragging the model chip
    // and the `+` sideways mid-turn.
    //
    // jsdom has no layout engine, so this cannot compare boxes. What it *can*
    // check is the rule that makes them agree: both are `.icon-btn`, whose one
    // declaration sets a fixed 28x28. Sharing `.send-btn` would have been the
    // wrong way to do it -- that class carries Send's accent fill, and reusing
    // it made "is there a send button?" answer yes while Stop was on screen.
    const { container } = await composer({ busy: true });
    const stop = stopButton(container)!;
    assert.ok(
      stop.classList.contains("icon-btn"),
      "Stop is not an icon button, so it cannot take Send's 28x28 box",
    );
    assert.ok(
      !stop.classList.contains("send-btn"),
      "Stop reuses Send's class, so anything asking 'is send on screen?' is lied to",
    );
  });

  test("the icon is a filled square, which is what says 'stop'", async () => {
    // An arrow against a square is the whole distinction between the two
    // states at a glance, and it is drawn rather than written -- so nothing in
    // the accessibility tree carries it and no plain-text assertion can see
    // it. A `<rect>` that is filled, and square, is the claim: the send arrow
    // is a stroked path, so a regression to it here would be a control that
    // looks like it sends while it interrupts.
    const { container } = await composer({ busy: true });
    const rect = one(stopButton(container)!, "rect");
    assert.ok(rect, "the stop button has no square in it");
    assert.equal(rect.getAttribute("width"), rect.getAttribute("height"));
    assert.equal(
      one(stopButton(container)!, "svg")!.getAttribute("fill"),
      "currentColor",
      "the square is an outline rather than a solid",
    );
    assert.equal(one(stopButton(container)!, "path"), null, "the send arrow came back");
  });

  test("and it stops rather than sending", async () => {
    // The two buttons look alike on purpose -- same box, same fill -- so this is
    // the assertion that keeps "alike" from becoming "the same control".
    const { container, calls } = await composer({ busy: true });
    await click(stopButton(container)!);
    assert.equal(calls.cancelled, 1);
    assert.deepEqual(calls.sent, [], "the interrupt sent a message");
  });

  test("Stop is the button that interrupts, and it says what it does", async () => {
    const { container, calls } = await composer({ busy: true });
    await click(stopButton(container)!);
    assert.equal(calls.cancelled, 1);
  });
});

// --- the caret the window puts somewhere ----------------------------------
describe("the field the window can put the caret in", () => {
  test("an injected ref lands on the textarea, and focus really moves there", async () => {
    // Choosing a conversation closes the sidebar, and the click landed inside
    // it -- so the element holding the caret is about to leave the document.
    // The window has to put it somewhere deliberate, and the only thing that
    // works is if the ref points at the element a user would actually type in.
    // Asserting the identity rather than "focus went somewhere": focusing the
    // wrapper would look the same on screen and swallow every keystroke.
    const ref = createRef<HTMLTextAreaElement>();
    const { container } = await composer({ inputRef: ref });

    assert.ok(ref.current, "the ref was never filled");
    assert.equal(ref.current, messageField(container));
    assert.equal(ref.current.tagName, "TEXTAREA");

    ref.current!.focus();
    assert.equal(ref.current, dom.window.document.activeElement);
  });

  test("it is optional, because a composer rendered on its own still works", async () => {
    // Nothing else may pass one -- the settings preview and any future embed.
    // A required ref would be a prop with exactly one caller.
    const { container } = await composer({ });
    assert.ok(messageField(container), "the field went missing without a ref");
  });
});
