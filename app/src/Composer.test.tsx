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

import { Composer, type ModeInfo, type ReasoningInfo } from "./Composer.js";
import { all, one, render, setValue, texts } from "./test-render.js";

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
}) {
  const calls = { efforts: [] as string[] };
  const container = await render(
    <Composer
      busy={props.busy ?? false}
      disabled={props.disabled ?? false}
      model="stealth/space-bunny-alpha"
      modes={MODES}
      mode="build"
      reasoning={props.reasoning}
      onReasoningChange={(effort) => calls.efforts.push(effort)}
      onModeChange={() => {}}
      onSend={() => {}}
      onCancel={() => {}}
    />,
  );
  return { container, calls };
}

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
