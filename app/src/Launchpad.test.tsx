/**
 * The launchpad: the first screen of a chat.
 *
 * It replaced `FirstRun` inside `MessageList`, and it broke that component's
 * one real promise on purpose: the old panel had exactly one focusable control
 * and a test that said so. This panel has suggestions and recent chats because
 * an empty window that offers nothing to press is the dead end the pass was for.
 * What survives is the half of the promise that mattered -- **nothing on the
 * panel is decoration that looks pressable**: every button does one named thing,
 * and none of them sends a message.
 *
 * The four claims worth keeping:
 *  - suggestions *prefill*, never send;
 *  - the setup card names only what is actually missing;
 *  - a window with no core gets no suggestions, because it cannot send them;
 *  - the folder row is the whole setup when nothing is missing, and the card's
 *    own row when something is -- never both.
 */

import "./test-dom.js";
import assert from "node:assert/strict";
import { describe, test } from "node:test";

import { Launchpad } from "./Launchpad.js";
import { MARK_RECTS } from "./AppMark.js";
import type { ConversationSummary } from "./ConversationList.js";
import { all, click, one, render, texts } from "./test-render.js";

const chat = (over: Partial<ConversationSummary> = {}): ConversationSummary => ({
  id: "c1",
  title: "Explain the sidecar",
  project: "D:/work/api",
  created_at: 1_700_000_000,
  updated_at: 1_700_000_100,
  message_count: 4,
  track: "build",
  ...over,
});

const mount = (over: Partial<React.ComponentProps<typeof Launchpad>> = {}) =>
  render(
    <Launchpad
      project="D:/work/api"
      connected
      needsProvider={false}
      model="stealth/space-bunny-alpha"
      conversations={[]}
      activeId=""
      onOpen={() => {}}
      onPrefill={() => {}}
      onSetup={() => {}}
      {...over}
    />,
  );

const labels = (c: HTMLElement) =>
  texts(c, ".launch-card-label").map((t) => (t ?? "").trim());

describe("what the panel says it is", () => {
  test("the mark is the app's own, drawn from the shipped path data", async () => {
    const container = await mount();
    const mark = one(container, ".empty-mark");
    assert.ok(mark, "the launchpad does not draw the mark");
    assert.equal(mark.getAttribute("aria-hidden"), "true");

    const rects = [...mark.querySelectorAll("rect")].map((r) => [
      r.getAttribute("x"),
      r.getAttribute("y"),
      r.getAttribute("width"),
      r.getAttribute("height"),
      r.getAttribute("rx"),
    ]);
    assert.deepEqual(
      rects,
      MARK_RECTS.map((r) => [
        String(r.x),
        String(r.y),
        String(r.width),
        String(r.height),
        String(r.rx),
      ]),
      "the mark is not the two strokes of the shipped glyph",
    );
    assert.equal(mark.getAttribute("fill"), "currentColor");
  });

  test("the wordmark and the line of orientation are both here", async () => {
    const container = await mount();
    assert.equal(one(container, ".empty h1")?.textContent, "TONYAgent");
    assert.equal(
      one(container, ".empty p")?.textContent,
      "Ask for something. The agent will use its tools to do it.",
    );
  });

  test("the two key hints are still the composer's placeholder, promoted", async () => {
    const container = await mount();
    assert.deepEqual(
      all(container, ".empty-hints > li").map((li) => li.textContent ?? ""),
      ["/ for skills", "@ for threads or files"],
    );
  });
});

describe("the four ways to begin", () => {
  test("with a project, they are about this project", async () => {
    const container = await mount();
    assert.deepEqual(labels(container), [
      "Explain how this project is laid out",
      "Find the entry point",
      "Find the tests and what they cover",
      "Turn an idea into a plan",
    ]);
  });

  test("with no project, they promise nothing about files", async () => {
    const container = await mount({ project: "" });
    assert.deepEqual(labels(container), [
      "Explain what you can do",
      "Turn an idea into a plan",
      "Draft a technical spec",
      "Show me a good first project",
    ]);
    for (const label of labels(container)) {
      assert.doesNotMatch(
        label,
        /this project|entry point|tests/i,
        `"${label}" talks about a project the window does not have`,
      );
    }
  });

  test("a press writes the whole sentence into the field, and sends nothing", async () => {
    // The copy on the card is a short label; the text in the field is the
    // sentence, because the label has to fit a 240px card and the sentence has
    // to be editable. `onPrefill` is the *only* channel -- there is no send
    // prop on this component at all, which is what makes "never sends" true by
    // construction rather than by a check.
    const prefilled: string[] = [];
    const container = await mount({ onPrefill: (text) => prefilled.push(text) });
    const card = all(container, ".launch-card")[0];

    await click(card);

    assert.deepEqual(prefilled, [
      "Explain how this project is laid out, starting with the top-level folders.",
    ]);
  });

  test("the unfinished sentence stays unfinished", async () => {
    // A prefill that reads like a complete command is a button that sends by
    // another name. The plan card ends with a colon and a space so the caret is
    // waiting for the user's idea.
    const prefilled: string[] = [];
    const container = await mount({ onPrefill: (text) => prefilled.push(text) });
    const plan = all(container, ".launch-card").find((card) =>
      card.textContent?.includes("Turn an idea into a plan"),
    )!;
    await click(plan);
    assert.equal(prefilled[0], "Turn this idea into a step-by-step plan: ");
  });

  test("no core, no suggestions: a prefill into a dead field is a promise", async () => {
    const container = await mount({ connected: false });
    assert.equal(all(container, ".launch-card").length, 0);
  });
});

describe("the setup card", () => {
  test("a configured window draws no card at all", async () => {
    const container = await mount();
    assert.equal(one(container, ".launch-setup"), null);
  });

  test("no folder: the card offers the picker, and the folder row goes away", async () => {
    let chosen = 0;
    const container = await mount({
      project: "",
      onChooseFolder: () => (chosen += 1),
    });
    const card = one(container, ".launch-setup")!;
    assert.ok(card, "no setup card with no folder");
    assert.match(
      texts(card, ".launch-setup-label").join(" "),
      /No project folder/,
    );
    assert.equal(
      one(container, ".empty-folder"),
      null,
      "the panel says the folder is missing twice",
    );

    const button = one(card, "button.btn")!;
    assert.equal(button.textContent, "Choose folder...");
    await click(button);
    assert.equal(chosen, 1);
  });

  test("a missing provider points at the page that fixes it", async () => {
    let setup = 0;
    const container = await mount({
      needsProvider: true,
      model: "",
      onSetup: () => (setup += 1),
    });
    const card = one(container, ".launch-setup")!;
    assert.match(texts(card, ".launch-setup-label").join(" "), /No provider/);
    const button = all(card, "button.btn").find((b) => b.textContent === "Open settings")!;
    await click(button);
    assert.equal(setup, 1);
  });

  test("no model is a sentence, not a second control for the title bar", async () => {
    // The model menu is in the bar one glance up. A row here that opened a menu
    // the window already shows would be a second control to keep in step -- and
    // the card would outlive the problem, because nobody would know which of
    // the two is authoritative.
    const container = await mount({ model: "" });
    const card = one(container, ".launch-setup")!;
    assert.match(texts(card, ".launch-setup-label").join(" "), /No model chosen/);
    assert.match(texts(card, ".launch-setup-hint").join(" "), /title bar/);
    assert.equal(all(card, "button").length, 0);
  });

  test("the folder is named, with the whole path on hover", async () => {
    const container = await mount({ onChooseFolder: () => {} });
    const name = one(container, ".empty-folder-name")!;
    assert.equal(name.textContent, "api");
    assert.equal(name.getAttribute("title"), "D:/work/api");
    assert.equal(one(container, ".empty-folder button")?.textContent, "Change...");
  });

  test("the folder button cannot be pressed while the window is busy", async () => {
    const container = await mount({
      onChooseFolder: () => {},
      canChooseFolder: false,
    });
    assert.equal(
      one(container, ".empty-folder button")?.hasAttribute("disabled"),
      true,
    );
  });
});

describe("the recent chats", () => {
  test("the last three, newest first, and not the one already open", async () => {
    const container = await mount({
      activeId: "open",
      conversations: [
        chat({ id: "old", title: "Old", updated_at: 100 }),
        chat({ id: "new", title: "Newest", updated_at: 900 }),
        chat({ id: "open", title: "Open", updated_at: 1000 }),
        chat({ id: "empty", title: "Empty", updated_at: 950, message_count: 0 }),
        chat({ id: "mid", title: "Middle", updated_at: 500 }),
        chat({ id: "another", title: "Another", updated_at: 200 }),
      ],
    });

    assert.deepEqual(texts(container, ".launch-recent-name"), [
      "Newest",
      "Middle",
      "Another",
    ]);
  });

  test("pressing one opens it", async () => {
    const opened: string[] = [];
    const container = await mount({
      conversations: [chat({ id: "c9", title: "Deploy notes" })],
      onOpen: (id) => opened.push(id),
    });
    await click(one(container, ".launch-recent-row")!);
    assert.deepEqual(opened, ["c9"]);
  });

  test("no chats, no heading: an empty section is a promise of nothing", async () => {
    const container = await mount({ conversations: [] });
    assert.equal(one(container, ".launch-recent"), null);
  });
});

describe("nothing on the panel is a dead control", () => {
  test("every button has a name, and only buttons are focusable", async () => {
    const container = await mount({
      project: "",
      needsProvider: true,
      model: "",
      conversations: [chat()],
      onChooseFolder: () => {},
    });

    const buttons = all(container, "button");
    assert.ok(buttons.length >= 6, `only ${buttons.length} buttons to check`);
    for (const button of buttons) {
      const name =
        button.getAttribute("aria-label") ??
        button.getAttribute("title") ??
        (button.textContent ?? "").trim();
      assert.ok(name, "a launchpad button has no name");
    }

    // The panel's only other tab stops are the list's own buttons and the
    // field below it: no anchors, no tabindex, no clickable boxes.
    assert.equal(all(container, "a, [tabindex]").length, 0);
  });
});
