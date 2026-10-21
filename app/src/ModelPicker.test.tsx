/**
 * Choosing a model from the composer.
 *
 * The chip used to read "Model -- coming soon" and do nothing when clicked.
 * These cover the three rules that are not visible in the markup and that each
 * correspond to a way the picker can be quietly wrong:
 *
 * - **Switching is refused while a turn is in flight.** A turn's history is
 *   being written by one model; binding another mid-turn interleaves two
 *   models' answers into one conversation. The menu has to say so rather than
 *   being silently inert.
 * - **The list is fetched once, on first open.** OpenRouter answers with
 *   several hundred entries, and a refetch per click spends a request per click.
 * - **A failed read is a message, not an empty list.** "The provider returned
 *   no models" and "we could not ask it" look identical in a dropdown, and only
 *   one of them is fixable by the user.
 */

import "./test-dom.js";
import assert from "node:assert/strict";
import { describe, test } from "node:test";

import { useState } from "react";

import { ModelPicker, matchingModels, type ModelDetails, type ModelList } from "./ModelPicker.js";
import { all, click, one, pointerDown, press, render, setValue, texts, wait } from "./test-render.js";

const MODELS = [
  "anthropic/claude-sonnet-4.5",
  "anthropic/claude-opus-4.1",
  "openai/gpt-5",
  "google/gemini-2.5-pro",
  "deepseek/deepseek-chat",
];

const list = (models: string[] = MODELS, current = "openai/gpt-5"): ModelList => ({
  models,
  current,
});

interface Harness {
  container: HTMLElement;
  /** The models picked, as a function -- not a value read at destructure time. */
  chosen(): string[];
  /** How many times the core was asked for the list. */
  loads(): number;
}

/** A picker the test can actually open, close and choose from. */
function Live(props: {
  model?: string;
  busy?: boolean;
  disabled?: boolean;
  initialList?: ModelList | null;
  error?: string | null;
  /** Leave the list unread, so the in-between state can be seen. */
  neverResolves?: boolean;
} = {}) {
  const [open, setOpen] = useState(false);
  const [current, setCurrent] = useState(props.model ?? "openai/gpt-5");
  const [choices, setChoices] = useState<string[]>([]);
  const [loads, setLoads] = useState(0);
  const [data, setData] = useState<ModelList | null>(props.initialList ?? null);

  return (
    <>
      <ModelPicker
        model={current}
        busy={props.busy ?? false}
        disabled={props.disabled ?? false}
        list={data}
        error={props.error ?? null}
        onOpen={() => setOpen(true)}
        onClose={() => setOpen(false)}
        onChange={(id) => {
          setChoices((prev) => [...prev, id]);
          setCurrent(id);
          setData((prev) => prev ?? list());
        }}
        onLoad={() => {
          setLoads((n) => n + 1);
          // 'neverResolves' stands in for a gateway that has not answered yet.
          // Without it the list arrives inside the same act() as the click and
          // the loading state is never observable -- which is the state the
          // test is about.
          if (data === null && !props.error && !props.neverResolves) setData(list());
        }}
      />
      <span data-testid="choices">{choices.join(",")}</span>
      <span data-testid="loads">{loads}</span>
      <span data-testid="open">{String(open)}</span>
    </>
  );
}

/**
 * Mount the picker and hand back ways to ask what it did.
 *
 * The counts are *functions* rather than values. Destructuring a getter
 * evaluates it once, at the moment of the destructure -- so a harness that
 * returned `loads` as a property read 0 and every assertion after the click
 * was reading the number from before it. The first version of this file had
 * that bug, and it looked exactly like the component failing to load.
 */
const live = async (props?: Parameters<typeof Live>[0]): Promise<Harness> => {
  const container = await render(<Live {...props} />);
  const read = (testid: string) => one(container, `[data-testid="${testid}"]`)?.textContent ?? "";
  return {
    container,
    chosen: () => read("choices").split(",").filter(Boolean),
    loads: () => Number(read("loads")),
  };
};

const chip = (container: HTMLElement) => one(container, ".chip") as HTMLButtonElement;
const menu = (container: HTMLElement) => one(container, ".modelpicker");
const field = (container: HTMLElement) =>
  one(container, ".modelpicker-filter") as HTMLInputElement | null;
const itemLabels = (container: HTMLElement) => texts(container, ".modelpicker-item");

// --- the pure filter -------------------------------------------------------
describe("the model filter", () => {
  const models = MODELS;

  test("an empty filter shows everything", () => {
    assert.deepEqual(matchingModels(models, ""), models);
    assert.deepEqual(matchingModels(models, "   "), models);
  });

  test("it matches a substring of the whole id", () => {
    // Users remember the model, not the vendor: "gemini" has to find
    // "google/gemini-2.5-pro".
    assert.deepEqual(matchingModels(models, "gemini"), ["google/gemini-2.5-pro"]);
  });

  test("it matches the vendor too", () => {
    assert.deepEqual(matchingModels(models, "anthropic"), [
      "anthropic/claude-sonnet-4.5",
      "anthropic/claude-opus-4.1",
    ]);
  });

  test("it is case insensitive, because a capitalised name still has to find it", () => {
    assert.deepEqual(matchingModels(models, "CLAUDE"), [
      "anthropic/claude-sonnet-4.5",
      "anthropic/claude-opus-4.1",
    ]);
  });

  test("every term must match, so more words mean fewer models", () => {
    // The point of a filter on a three-hundred-entry list is to narrow. An
    // "any term" match would widen, and "claude sonnet" would list all three
    // Claude models.
    assert.deepEqual(matchingModels(models, "claude sonnet"), [
      "anthropic/claude-sonnet-4.5",
    ]);
  });

  test("a term that matches nothing yields nothing, rather than everything", () => {
    assert.deepEqual(matchingModels(models, "llama"), []);
  });
});

// --- opening ---------------------------------------------------------------
describe("the model menu", () => {
  test("the chip is not a dead control", async () => {
    const { container } = await live();
    await click(chip(container));
    assert.ok(menu(container), "clicking the model did nothing");
  });

  test("it is named for a screen reader", async () => {
    const { container } = await live();
    assert.equal(chip(container).getAttribute("aria-haspopup"), "dialog");
    assert.equal(chip(container).getAttribute("aria-expanded"), "false");
    await click(chip(container));
    assert.equal(chip(container).getAttribute("aria-expanded"), "true");
  });

  test("it asks for the list when it first opens", async () => {
    // Not at launch: a window that reads several hundred model ids on every
    // start spends a request to render a chip the user may never click.
    const { container, loads } = await live();
    assert.equal(loads(), 0, "the list was fetched before the menu was opened");
    await click(chip(container));
    assert.equal(loads(), 1);
  });

  test("it does not ask again on a second visit", async () => {
    const { container, loads } = await live();
    await click(chip(container));
    await wait(200);
    await click(chip(container));
    await click(chip(container));
    assert.equal(loads(), 1, "the gateway was asked once per open");
  });

  test("it says it is loading rather than showing an empty list", async () => {
    // A provider that has not answered yet and a provider with no models look
    // identical in a dropdown. One of them is still in progress, and a user
    // who cannot tell which is looking at a list that may never arrive.
    const container = await render(<Live neverResolves />);
    await click(chip(container));
    const note = one(container, ".modelpicker-note")?.textContent ?? "";
    assert.match(note, /Loading/);
  });
});

// --- choosing --------------------------------------------------------------
describe("choosing a model", () => {
  test("every model the core sent is offered", async () => {
    const { container } = await live();
    await click(chip(container));
    assert.equal(itemLabels(container).length, MODELS.length);
  });

  test("the vendor is shown, because the id is namespaced", async () => {
    // "anthropic/claude-sonnet-4.5" tells you at a glance that you would be
    // moving to a different family of model. That is the risk in a one-click
    // switch, so the prefix is not decoration.
    const { container } = await live();
    await click(chip(container));
    assert.deepEqual(texts(container, ".modelpicker-vendor"), [
      "Anthropic",
      "Anthropic",
      "Openai",
      "Google",
      "Deepseek",
    ]);
  });

  test("the current model is the one that is ticked", async () => {
    // Ticked from `list.current` as the core reported it, not from a guess
    // about which entry is bound. A guess that drifts ticks the wrong model.
    const { container } = await live({ model: "google/gemini-2.5-pro" });
    await click(chip(container));
    const current = all(container, ".modelpicker-item.is-current");
    assert.equal(current.length, 1);
    assert.match(current[0].textContent ?? "", /Gemini 2\.5 Pro/);
  });

  test("the chip reads as words, and the tooltip keeps the exact id", async () => {
    // The chip is what a person reads, so it reads as a person would write
    // it. The id is what gets bound on click, so it rides in the tooltip --
    // a display that hid the address would be a chip that cannot be checked.
    const { container } = await live({ model: "deepseek/deepseek-chat" });
    assert.match(chip(container).textContent ?? "", /Deepseek Chat/);
    assert.match(chip(container).getAttribute("title") ?? "", /deepseek\/deepseek-chat/);
  });

  test("picking one asks for it", async () => {
    const { container, chosen } = await live();
    await click(chip(container));
    const items = all(container, ".modelpicker-item");
    await click(items[0]);
    assert.deepEqual(chosen(), ["anthropic/claude-sonnet-4.5"]);
  });

  test("picking closes the menu", async () => {
    const { container } = await live();
    await click(chip(container));
    await click(all(container, ".modelpicker-item")[0]);
    await wait(250);
    assert.equal(menu(container), null, "the menu stayed open over the choice");
  });

  test("typing narrows the list", async () => {
    const { container } = await live();
    await click(chip(container));
    await setValue(field(container)!, "claude");
    assert.equal(itemLabels(container).length, 2);
  });

  test("a filter matching nothing says so, rather than showing an empty box", async () => {
    const { container } = await live();
    await click(chip(container));
    await setValue(field(container)!, "llama");
    assert.match(one(container, ".modelpicker-note")?.textContent ?? "", /llama/);
  });

  test("Enter picks the first match", async () => {
    // What a user means by "the one I typed" when the list is three hundred
    // long and the filter has already narrowed it to a few.
    const { container, chosen } = await live();
    await click(chip(container));
    await setValue(field(container)!, "gpt");
    await press("Enter", field(container)!);
    assert.deepEqual(chosen(), ["openai/gpt-5"]);
  });
});

// --- while the agent is working -------------------------------------------
describe("choosing a model mid-turn", () => {
  test("the menu refuses to offer a choice", async () => {
    // The turn's history is being written by one model. Rebinding mid-turn
    // interleaves another model's answers into the same conversation, so this
    // is refused rather than left to the user to notice.
    const { container } = await live({ busy: true });
    await click(chip(container));
    assert.equal(
      all(container, ".modelpicker-item").length,
      0,
      "offered a switch while a turn was in flight",
    );
  });

  test("it says why, instead of being quietly inert", async () => {
    const { container } = await live({ busy: true });
    await click(chip(container));
    const note = one(container, ".modelpicker-note")?.textContent ?? "";
    assert.match(note, /turn/i);
    assert.match(note, /stop/i);
  });

  test("the chip explains it on hover too", async () => {
    // Before the menu is even open, a chip that looks enabled and does nothing
    // is the confusing version of this.
    const { container } = await live({ busy: true });
    assert.match(chip(container).getAttribute("title") ?? "", /stop/i);
  });
});

// --- when the list cannot be read -----------------------------------------
describe("when the model list cannot be read", () => {
  test("it shows the reason rather than an empty menu", async () => {
    // "The provider returned no models" and "we could not ask it" are the same
    // pixels in an empty dropdown, and only the second one is fixable by the
    // user checking their key.
    const container = await render(<Live error="Could not reach the provider" />);
    await click(chip(container));
    const note = one(container, ".modelpicker-note");
    assert.match(note?.textContent ?? "", /could not reach/i);
    assert.equal(note?.classList.contains("is-error"), true);
  });

  test("a list that came back empty says so too", async () => {
    const container = await render(<Live initialList={list([], "")} />);
    await click(chip(container));
    assert.match(
      one(container, ".modelpicker-note")?.textContent ?? "",
      /no models/i,
    );
  });

  test("the chip is disabled when the core is not reachable", async () => {
    const { container } = await live({ disabled: true });
    assert.equal(chip(container).disabled, true);
  });
});

// --- dismissal -------------------------------------------------------------
describe("dismissing the model menu", () => {
  test("a click elsewhere closes it", async () => {
    const { container } = await live();
    await click(chip(container));
    await pointerDown(document.body);
    await wait(250);
    assert.equal(menu(container), null);
  });

  test("Escape closes it", async () => {
    const { container } = await live();
    await click(chip(container));
    await press("Escape");
    await wait(250);
    assert.equal(menu(container), null);
  });

  test("the chip toggles it shut", async () => {
    const { container } = await live();
    await click(chip(container));
    await click(chip(container));
    await wait(250);
    assert.equal(menu(container), null);
  });

  test("pressing the filter does not close the menu the filter is in", async () => {
    // The bug that sent this to a session: `window.addEventListener("pointerdown",
    // close, true)` fires on the way *down*, for every press, and this one
    // landed inside the menu. Clicking the box meant closing the menu before
    // the box could be typed into.
    //
    // Asserted on `data-state`, because the node stays mounted after a close so
    // the exit has something to animate -- "closed" here is a state, and an
    // assertion on the node merely being present would pass either way.
    const { container } = await live();
    await click(chip(container));
    await pointerDown(field(container)!);
    assert.equal(
      menu(container)!.dataset.state,
      "open",
      "pressing the filter dismissed the menu it was in",
    );
  });

  test("pressing an item does not close the menu before the item is trusted", async () => {
    // The same listener, one step further on. A dismissal on the way down means
    // the item's own click lands on a menu that is already closing, which is
    // how "clicking an entry did nothing" happens.
    const { container, chosen } = await live();
    await click(chip(container));
    await pointerDown(all(container, ".modelpicker-item")[0]);
    assert.equal(
      menu(container)!.dataset.state,
      "open",
      "pressing an item dismissed the menu it was in",
    );
    // And the click behind that press still lands, which is the part that
    // matters: the state above could be right while the handler was ignored.
    await click(all(container, ".modelpicker-item")[0]);
    assert.deepEqual(chosen(), ["anthropic/claude-sonnet-4.5"]);
    await wait(250);
    assert.equal(menu(container), null, "the choice did not close the menu");
  });
});

// --- catalog detail lines ----------------------------------------------------
describe("catalog detail lines", () => {
  const details: Record<string, ModelDetails> = {
    "kimi-k3": {
      name: "Kimi K3",
      context_length: 1048576,
      max_tokens: 131072,
      input_modalities: ["text", "image"],
      protocol: "chat",
    },
    "muse-spark-1.3-contributor": {
      name: "Muse Spark 1.3 Contributor",
      context_length: 1048576,
      max_tokens: 131072,
      input_modalities: ["text", "image"],
      protocol: "responses",
    },
  };

  const catalogued = () =>
    render(
      <ModelPicker
        model="kimi-k3"
        busy={false}
        disabled={false}
        list={{ models: ["kimi-k3", "muse-spark-1.3-contributor", "glm-5.3"], current: "kimi-k3" }}
        details={details}
        error={null}
        onOpen={() => {}}
        onClose={() => {}}
        onChange={() => {}}
        onLoad={() => {}}
      />,
    );

  test("the filter matches display names, not only ids", () => {
    assert.deepEqual(matchingModels(["kimi-k3", "glm-5.3"], "kimi k3", details), [
      "kimi-k3",
    ]);
  });

  test("rows show the display name and the facts", async () => {
    const container = await catalogued();
    await click(chip(container));
    const rows = texts(container, ".modelpicker-item").map((t) => t ?? "");
    assert.match(rows[0], /Kimi K3/);
    assert.match(rows[0], /1M ctx/);
    assert.match(rows[0], /131K out/);
    assert.match(rows[0], /image/);
    assert.match(rows[1], /Muse Spark 1\.3 Contributor/);
    assert.match(rows[1], /Responses/);
  });

  test("rows without facts render prettified words, and no detail line", async () => {
    // glm-5.3 has no entry: no display name and no facts to line up. The row
    // reads as words rather than the raw id -- the catalog wins wherever it
    // answers, and this is the fallback -- but there is still no detail line.
    const container = await catalogued();
    await click(chip(container));
    const rows = texts(container, ".modelpicker-item").map((t) => t ?? "");
    assert.match(rows[2], /Glm 5\.3/);
    assert.equal(all(container, ".modelpicker-detail").length, 2);
  });
});
