/**
 * The thinking panel, and the fact that a model which did not think gets no panel.
 *
 * These are interaction tests, not render snapshots. Every rule here is a
 * decision the component makes over time -- born open while the reasoning
 * streams, folded once it completes, left alone once the reader has touched it
 * -- and a snapshot of the markup would pass unchanged while all three were
 * inverted.
 *
 * The two that are easiest to break by accident:
 *
 * - **Nothing renders for a model that cannot think.** A permanently collapsed
 *   "Thinking" header above every answer is furniture the user has to learn to
 *   ignore, and it is invisible once you are used to it. So "no panel" is
 *   asserted rather than assumed.
 * - **A manual unfold outranks the fold.** The panel folds when the stream
 *   ends, because the trace is often longer than the answer. But someone who
 *   opened it mid-stream was looking at something, and having it snap shut
 *   under their eyes is a different thing from folding when nobody was watching.
 */

import "./test-dom.js";
import assert from "node:assert/strict";
import { describe, test } from "node:test";

import { MessageList } from "./MessageList.js";
import { all, click, one, rerender, render, texts } from "./test-render.js";
import type { ChatMessage } from "./events.js";

function message(over: Partial<ChatMessage> = {}): ChatMessage {
  return {
    id: "a1",
    role: "assistant",
    text: "The answer.",
    tools: [],
    reasoning: "",
    reasoningComplete: false,
    reasoningTruncated: false,
    ...over,
  };
}

/** Render a one-message transcript, and hand back the container. */
function transcript(m: ChatMessage) {
  return render(<MessageList messages={[m]} busy={false} />);
}

/** The panel's toggle button, which is also its header. */
const head = (container: HTMLElement) => one(container, ".thinking-head");

const isOpen = (container: HTMLElement) => {
  const panel = one(container, ".thinking");
  return panel !== null && panel.classList.contains("is-open");
};

const body = (container: HTMLElement) => one(container, ".thinking-body");

// --- when the panel is absent ---------------------------------------------
describe("the thinking panel", () => {
  test("a model that did not think gets no panel at all", async () => {
    const container = await transcript(message());
    // Counted, not compared to null. `assert.equal(node, null)` on a failure
    // makes node:test serialise the whole jsdom element to build its message,
    // which takes over a minute; a count fails the same way and reads at once.
    assert.equal(
      all(container, ".thinking").length,
      0,
      "an empty Thinking header rendered",
    );
  });

  test("a user's message never gets one either", async () => {
    const container = await transcript(
      message({ role: "user", text: "Hi", reasoning: "not yours to show" }),
    );
    assert.equal(all(container, ".thinking").length, 0);
  });

  test("the answer is shown whether or not there was thinking", async () => {
    const withThought = await transcript(
      message({ reasoning: "Step one.", reasoningComplete: true }),
    );
    assert.deepEqual(texts(withThought, ".md-p"), ["The answer."]);
    const without = await transcript(message());
    assert.deepEqual(texts(without, ".md-p"), ["The answer."]);
  });
});

// --- opening, folding, and hands off --------------------------------------
describe("the thinking panel over a turn", () => {
  test("it is open while the thinking is still arriving", async () => {
    const container = await transcript(message({ reasoning: "Step one." }));
    assert.ok(head(container), "no panel while reasoning is streaming");
    assert.equal(isOpen(container), true, "the panel was folded mid-stream");
    assert.equal(head(container)!.getAttribute("aria-expanded"), "true");
    assert.equal(body(container)!.textContent, "Step one.");
    assert.ok(one(container, ".thinking-live"), "no indication that this is still running");
  });

  test("reasoning.completed folds it, because the trace outlives its usefulness", async () => {
    const streaming = message({ reasoning: "Step one." });
    const container = await transcript(streaming);
    assert.equal(isOpen(container), true);

    // The same message, one event later. The id is unchanged on purpose: this
    // is the panel deciding to fold, not a new panel being born.
    await rerender(
      <MessageList
        messages={[message({ reasoning: "Step one.", reasoningComplete: true })]}
        busy={false}
      />,
    );

    assert.equal(isOpen(container), false, "the finished panel stayed open");
    assert.equal(head(container)!.getAttribute("aria-expanded"), "false");
    assert.equal(body(container), null, "a folded panel still shows its body");
    assert.equal(one(container, ".thinking-live"), null);
  });

  test("a panel the reader opened on purpose is not folded when the turn ends", async () => {
    // The reader arrives while the reasoning is still streaming, folds it to get
    // the answer out of the way, then opens it again because they are following
    // the trace. That last click is the point: they chose to be looking at it.
    const container = await transcript(message({ reasoning: "Step one." }));
    assert.equal(isOpen(container), true);
    await click(head(container)!);
    await click(head(container)!);
    assert.equal(isOpen(container), true, "the second click closed it");

    // The stream ends, and the effect that folds a finished panel runs.
    await rerender(
      <MessageList
        messages={[message({ reasoning: "Step one.", reasoningComplete: true })]}
        busy={false}
      />,
    );

    assert.equal(
      isOpen(container),
      true,
      "the panel folded under a reader who had opened it on purpose",
    );
    assert.equal(head(container)!.getAttribute("aria-expanded"), "true");
    assert.equal(body(container)!.textContent, "Step one.");
  });

  test("a panel nobody touched still folds, which is the rule the one above bends", async () => {
    // Same event, no clicks. If this one ever passes because the fold was
    // removed rather than because the fold happened, the test above is pinning
    // nothing at all.
    const container = await transcript(message({ reasoning: "Step one." }));
    await rerender(
      <MessageList
        messages={[message({ reasoning: "Step one.", reasoningComplete: true })]}
        busy={false}
      />,
    );
    assert.equal(isOpen(container), false);
  });

  test("clicking it toggles, and the header says which way round it is", async () => {
    const container = await transcript(message({ reasoning: "Step one." }));
    const before = head(container)!.getAttribute("aria-expanded");
    assert.deepEqual(
      texts(container, ".thinking-caret"),
      ["▾"],
      "an open panel should point down",
    );

    await click(head(container)!);
    assert.equal(head(container)!.getAttribute("aria-expanded"), "false");
    assert.deepEqual(texts(container, ".thinking-caret"), ["▸"]);

    await click(head(container)!);
    assert.equal(head(container)!.getAttribute("aria-expanded"), before);
  });
});

// --- the turn that ran out of budget --------------------------------------
describe("a turn that ran out of thinking budget", () => {
  const truncated = message({
    text: "",
    reasoning: "",
    reasoningComplete: true,
    reasoningTruncated: true,
    reasoningNotice: "The model used its whole budget thinking and never answered.",
  });

  test("it still gets a panel, because there is something to explain", async () => {
    const container = await transcript(truncated);
    assert.ok(head(container), "a truncated turn rendered nothing to explain itself");
  });

  test("the badge and the notice are both on screen without opening anything", async () => {
    const container = await transcript(truncated);
    assert.equal(isOpen(container), false, "it opened, with an empty body to show");
    assert.deepEqual(texts(container, ".thinking-warn"), ["ran out of budget"]);
    assert.deepEqual(texts(container, ".thinking-notice"), [
      truncated.reasoningNotice,
    ]);
  });

  test("a truncated turn that did think shows its reasoning when opened", async () => {
    const container = await transcript({ ...truncated, reasoning: "Nearly had it." });
    await click(head(container)!);
    assert.equal(body(container)!.textContent, "Nearly had it.");
  });
});

// --- separation from the answer -------------------------------------------
describe("reasoning beside the answer", () => {
  test("the two are different nodes, so folding one cannot hide the other", async () => {
    const container = await transcript(
      message({ reasoning: "Internal deliberation.", reasoningComplete: true }),
    );
    assert.deepEqual(texts(container, ".thinking-body"), []);
    assert.deepEqual(texts(container, ".md-p"), ["The answer."]);

    await click(head(container)!);
    assert.deepEqual(texts(container, ".thinking-body"), ["Internal deliberation."]);
    assert.deepEqual(
      texts(container, ".md-p"),
      ["The answer."],
      "opening the reasoning disturbed the answer",
    );
  });

  test("a fold is a display choice, not a deletion", async () => {
    const container = await transcript(
      message({ reasoning: "Internal deliberation.", reasoningComplete: true }),
    );
    // Folded, but the text is one click away and was never re-parsed away.
    assert.equal(all(container, ".thinking").length, 1);
    assert.equal(body(container), null);
    await click(head(container)!);
    assert.equal(body(container)!.textContent, "Internal deliberation.");
  });
});
