/**
 * The thinking-effort dial, and the models that must not get one.
 *
 * The dropdown is one conditional:
 *
 *     reasoning && reasoning.efforts.length > 0
 *
 * That is a small amount of logic guarding a real lie. Show the control on a
 * model that cannot reason, or on one that reasons with no choice to make, and
 * the composer offers a dial that either does nothing or is refused -- which
 * teaches the reader that this row is decoration. So both negatives are
 * asserted, not just the positive.
 *
 * The other rule here is the same one the mode pills follow: the displayed
 * effort is whatever the core last reported, never a local guess written the
 * instant a value was clicked. A local value would keep showing the effort the
 * user asked for even after the core refused it, and the composer would be
 * describing a state that does not exist.
 */

import "./test-dom.js";
import assert from "node:assert/strict";
import { describe, test } from "node:test";
import { createRef, type RefObject } from "react";

import { Composer, type ModeInfo, type ReasoningInfo } from "./Composer.js";
import type { ModelList } from "./ModelPicker.js";
import { all, click, one, press, render, setValue, texts } from "./test-render.js";
import { dom } from "./test-dom.js";

const MODES: ModeInfo[] = [
  { name: "build", label: "Build", description: "Anything goes", writes: true },
  { name: "plan", label: "Plan", description: "Read only", writes: false },
];

/** A model that can be asked to think at five different depths. */
function reasoning(over: Partial<ReasoningInfo> = {}): ReasoningInfo {
  return {
    supported: true,
    efforts: ["max", "xhigh", "high", "medium", "low"],
    default_effort: "max",
    mandatory: true,
    effort: "high",
    ...over,
  };
}

/** Mount a composer and record what it asks the core to do. */
async function composer(props: {
  reasoning: ReasoningInfo | null;
  busy?: boolean;
  disabled?: boolean;
  maxToolCalls?: number | null;
  modelList?: ModelList | null;
  /** Injected by the window when it needs to move the caret here. */
  inputRef?: RefObject<HTMLTextAreaElement | null>;
}) {
  const calls = { efforts: [] as string[], sent: [] as string[], cancelled: 0 };
  const container = await render(
    <Composer
      inputRef={props.inputRef}
      busy={props.busy ?? false}
      disabled={props.disabled ?? false}
      model="stealth/space-bunny-alpha"
      modes={MODES}
      mode="build"
      reasoning={props.reasoning}
      onReasoningChange={(effort) => calls.efforts.push(effort)}
      onModeChange={() => {}}
      onSend={(text, files) => calls.sent.push(text || `(${files.length} files)`)}
      onCancel={() => {
        calls.cancelled += 1;
      }}
      maxToolCalls={props.maxToolCalls ?? 10}
      modelList={props.modelList ?? null}
      modelListError={null}
      onModelMenuOpen={() => {}}
      onModelMenuClose={() => {}}
      onModelChange={() => {}}
      onModelListLoad={() => {}}
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

const dial = (container: HTMLElement) =>
  one(container, ".thinking-select") as HTMLSelectElement | null;

/** The option labels, in the order the model reported them. */
const options = (container: HTMLElement) => texts(container, ".thinking-select option");

// --- when there is nothing to dial ----------------------------------------
describe("the thinking effort dial", () => {
  test("a model that cannot reason gets no dial", async () => {
    const { container } = await composer({
      reasoning: reasoning({ supported: false, efforts: [], default_effort: "" }),
    });
    assert.equal(
      all(container, ".thinking-select").length,
      0,
      "offered a dial that cannot change anything",
    );
  });

  test("a model that reasons with no choice to make gets no dial", async () => {
    // Supported, but the provider named no efforts. The support flag alone is
    // not enough to justify the control.
    const { container } = await composer({ reasoning: reasoning({ efforts: [] }) });
    assert.equal(
      all(container, ".thinking-select").length,
      0,
      "an empty dropdown leaked onto the composer",
    );
    assert.equal(all(container, ".thinking-chip").length, 0);
  });

  test("it stays put while the core has not answered yet", async () => {
    // Null means "not read", which is not the same as "not supported": the
    // first keeps the control where it is, the second removes it.
    const { container } = await composer({ reasoning: null });
    assert.equal(all(container, ".thinking-select").length, 0);
    assert.equal(
      all(container, ".composer-row").length,
      1,
      "the whole control row disappeared with it",
    );
  });
});

// --- when there is a dial -------------------------------------------------
describe("the thinking effort dial on a model that reasons", () => {
  test("it offers the model's own default first, then its efforts in order", async () => {
    const { container } = await composer({ reasoning: reasoning() });
    assert.deepEqual(options(container), [
      "default (max)",
      "max",
      "xhigh",
      "high",
      "medium",
      "low",
    ]);
  });

  test("a model with no named default says so rather than inventing one", async () => {
    const { container } = await composer({ reasoning: reasoning({ default_effort: "" }) });
    assert.equal(options(container)?.[0], "default");
  });

  test("the efforts the provider reported are the efforts offered", async () => {
    // The order is the provider's, and the names are the provider's. Hardcoding
    // either would drift the moment a model changed.
    const { container } = await composer({
      reasoning: reasoning({ efforts: ["off", "on"], default_effort: "on" }),
    });
    assert.deepEqual(options(container), ["default (on)", "off", "on"]);
  });

  test("it shows the effort the core reported, not the one last clicked", async () => {
    const { container } = await composer({ reasoning: reasoning({ effort: "medium" }) });
    assert.equal(dial(container)!.value, "medium");
  });

  test("choosing an effort asks the core for it", async () => {
    const { container, calls } = await composer({ reasoning: reasoning() });
    await setValue(dial(container)!, "xhigh");
    assert.deepEqual(calls.efforts, ["xhigh"]);
  });

  test("choosing the default asks for the absence of a choice", async () => {
    const { container, calls } = await composer({
      reasoning: reasoning({ effort: "low" }),
    });
    // The default option's `value` is the empty string, and it has to stay
    // distinct from the efforts: sending "max" instead would pin the model to
    // its default forever, which is the opposite of offering the model a
    // choice. The option's own value is read back here so the assertion is on
    // what the user actually selected rather than on what we hoped they did.
    const defaultOption = all(container, ".thinking-select option")[0];
    assert.equal(defaultOption.getAttribute("value"), "");

    await setValue(dial(container)!, defaultOption.getAttribute("value")!);
    assert.deepEqual(
      calls.efforts,
      [""],
      "the default must arrive as an empty effort, not as the effort in the label",
    );
  });

  test("it is labelled, because a chip reading \"Thinking\" is not a control", async () => {
    const { container } = await composer({ reasoning: reasoning() });
    assert.equal(dial(container)!.getAttribute("aria-label"), "Thinking effort");
    assert.deepEqual(texts(container, ".thinking-chip-label"), ["Thinking"]);
  });
});

// --- while the agent is working -------------------------------------------
describe("the thinking effort dial while the agent is working", () => {
  test("it is disabled mid-turn, because effort applies to the next turn", async () => {
    const { container } = await composer({ reasoning: reasoning(), busy: true });
    assert.equal(dial(container)!.disabled, true);
  });

  test("it is disabled when the window is disabled", async () => {
    const { container } = await composer({ reasoning: reasoning(), disabled: true });
    assert.equal(dial(container)!.disabled, true);
  });

  test("it is enabled on an idle composer", async () => {
    const { container } = await composer({ reasoning: reasoning() });
    assert.equal(dial(container)!.disabled, false);
    assert.equal(all(container, ".thinking-select").length, 1, "the dial is duplicated");
  });
});

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
    const { container } = await composer({ reasoning: null });
    const text = (container as HTMLElement).textContent ?? "";
    assert.equal(
      text.includes("Continue"),
      false,
      'the button still offers a word for a different action',
    );
  });

  test("it is named for a screen reader, since a bare icon is not a control", async () => {
    const { container } = await composer({ reasoning: null });
    const button = sendButton(container)!;
    assert.ok(button, "no send button rendered");
    assert.equal(button.getAttribute("aria-label"), "Send");
    assert.equal(button.getAttribute("title"), "Send");
  });

  test("the icon is hidden from assistive tech, because the name is the label", async () => {
    const { container } = await composer({ reasoning: null });
    const svg = one(sendButton(container)!, "svg")!;
    assert.equal(svg.getAttribute("aria-hidden"), "true");
  });

  test("clicking it sends what was typed", async () => {
    const { container, calls } = await composer({ reasoning: null });
    await setValue(messageField(container)!, "list the files in src/core");
    await click(sendButton(container)!);
    assert.deepEqual(calls.sent, ["list the files in src/core"]);
  });

  test("it is the same action from the keyboard", async () => {
    const { container, calls } = await composer({ reasoning: null });
    await setValue(messageField(container)!, "hello");
    await press("Enter", messageField(container)!);
    assert.deepEqual(calls.sent, ["hello"], "Enter no longer sends");
  });

  test("an empty message is not sent", async () => {
    // Not an error worth surfacing; the button just does nothing, as before.
    const { container, calls } = await composer({ reasoning: null });
    await click(sendButton(container)!);
    assert.deepEqual(calls.sent, []);
  });

  test("whitespace is not a message either", async () => {
    const { container, calls } = await composer({ reasoning: null });
    await setValue(messageField(container)!, "   \n  ");
    await click(sendButton(container)!);
    assert.deepEqual(calls.sent, []);
  });

  test("it is disabled when the window is disabled", async () => {
    const { container } = await composer({ reasoning: null, disabled: true });
    assert.equal(sendButton(container)!.disabled, true);
  });
});

// --- while the agent is working -------------------------------------------
describe("the send button while the agent is working", () => {
  test("send is replaced by Stop, not merely disabled", async () => {
    // Showing a dead send button next to a live Stop button reads as "you can
    // interrupt" and "you can also send", which is only half true.
    const { container } = await composer({ reasoning: null, busy: true });
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
    const { container } = await composer({ reasoning: null, busy: true });
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

  test("and it stops rather than sending", async () => {
    // The two buttons look alike on purpose -- same box, same fill -- so this is
    // the assertion that keeps "alike" from becoming "the same control".
    const { container, calls } = await composer({ reasoning: null, busy: true });
    await click(stopButton(container)!);
    assert.equal(calls.cancelled, 1);
    assert.deepEqual(calls.sent, [], "the interrupt sent a message");
  });

  test("Stop is the button that interrupts, and it says what it does", async () => {
    const { container, calls } = await composer({ reasoning: null, busy: true });
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
    const { container } = await composer({ reasoning: null, inputRef: ref });

    assert.ok(ref.current, "the ref was never filled");
    assert.equal(ref.current, messageField(container));
    assert.equal(ref.current.tagName, "TEXTAREA");

    ref.current!.focus();
    assert.equal(ref.current, dom.window.document.activeElement);
  });

  test("it is optional, because a composer rendered on its own still works", async () => {
    // Nothing else may pass one -- the settings preview and any future embed.
    // A required ref would be a prop with exactly one caller.
    const { container } = await composer({ reasoning: null });
    assert.ok(messageField(container), "the field went missing without a ref");
  });
});
