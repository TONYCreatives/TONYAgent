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

// --- several thoughts, in the order they happened --------------------------
/*
 * A turn that thinks, acts, then thinks again used to stack every thought into
 * one block at the top of the bubble, ahead of the prose and the calls they
 * belong with. The fix gives each pass its own `ReasonRun` placed against the
 * prose, so the transcript reads "thought this, ran that, thought this" in the
 * order it happened rather than the order it was reported.
 */
describe("a turn that thinks more than once", () => {
  // One message, built the way the reducer builds it mid-turn: the first
  // thought sits at prose offset 0, the prose runs to the end of the first
  // sentence, the tool call and the second thought follow it. Each carries its
  // own placement mark, and both are still open (streaming) so the test can
  // read what each one says. Offsets land on sentence boundaries so the prose
  // splits into clean pieces.
  const interleaved = message({
    text: "Reading the file now. Done.",
    reasonRuns: [
      { text: "I should read the file.", after: 0, complete: false, truncated: false },
      { text: "Now I can answer.", after: 22, complete: false, truncated: false },
    ],
    tools: [
      { id: "c1", name: "read_file", status: "ok", detail: "Read a.py", after: 21 },
    ],
  });

  test("each pass is its own panel, not one block holding every thought", async () => {
    const container = await transcript(interleaved);
    // Two separate panels, not one concatenated block: the whole bug in one
    // number.
    assert.equal(
      all(container, ".thinking").length,
      2,
      "two thinking passes rendered as one block",
    );
  });

  test("they appear in the order they happened, interleaved with the work", async () => {
    const container = await transcript(interleaved);
    // Walk the bubble's children in document order and confirm the sequence:
    // think, act, think again -- each thought before the work that followed it.
    const bubble = one(container, ".bubble-assistant")!;
    const order = Array.from(bubble.children).map((el) => {
      if (el.classList.contains("thinking")) {
        const label = el.querySelector(".thinking-body");
        return `think:${label?.textContent ?? ""}`;
      }
      if (el.classList.contains("tools")) return "tools";
      return "text";
    });
    // The second thought (offset 19) lands after the tool (offset 18) and its
    // prose, so it is drawn after them rather than hoisted to the top.
    assert.deepEqual(order, ["think:I should read the file.", "text", "tools", "think:Now I can answer.", "text"]);
  });
});

// --- the tool call budget on a card ---------------------------------------
/*
 * The card shows where the turn stands: "Tool call 3/10". Two rules are easy
 * to break here.
 *
 * The number is not decoration. Once the budget is nearly spent, it is the
 * only thing on the card warning that the next call may be refused, so it
 * takes a warning tint instead of staying muted. And the threshold is two
 * calls, not one: a model refused on the call it was told it could make has
 * already wasted that call, so a warning that arrived at the last call would
 * have come one step too late to help.
 */

function toolCard(over: Partial<ChatMessage["tools"][number]> = {}) {
  return message({
    tools: [
      {
        id: "t1",
        name: "read_file",
        status: "ok",
        detail: "Read 42 lines",
        ...over,
      },
    ],
  });
}

const budgetLabel = (container: HTMLElement) => one(container, ".tool-budget");

describe("the tool call budget on a card", () => {
  test("the number the core sent is the number shown", async () => {
    const container = await transcript(toolCard({ budget: "Tool call 3/10" }));
    assert.equal(budgetLabel(container)?.textContent, "Tool call 3/10");
  });

  test("a call with no budget shows nothing at all", async () => {
    // The core has not reported one -- a restored conversation, or a gateway
    // that does not count. An invented number would be a claim about a turn
    // this file knows nothing about.
    const container = await transcript(toolCard());
    assert.equal(budgetLabel(container), null);
  });

  test("a turn early in its budget stays muted", async () => {
    const container = await transcript(toolCard({ budget: "Tool call 3/10" }));
    assert.equal(
      budgetLabel(container)?.classList.contains("is-near-limit"),
      false,
      "a turn with seven calls left does not warrant a warning",
    );
  });

  test("the penultimate call is warned about", async () => {
    // 9/10: the next call is the last one. This is the warning that has to
    // appear before the turn is cut off, not on the call that got refused.
    const container = await transcript(toolCard({ budget: "Tool call 9/10" }));
    assert.equal(budgetLabel(container)?.classList.contains("is-near-limit"), true);
  });

  test("the final call is warned about too", async () => {
    const container = await transcript(toolCard({ budget: "Tool call 10/10" }));
    assert.equal(budgetLabel(container)?.classList.contains("is-near-limit"), true);
  });

  test("a refused call is still warned about, since it is the last one", async () => {
    const container = await transcript(
      toolCard({ budget: "Tool call 10/10", status: "failed" }),
    );
    assert.equal(budgetLabel(container)?.classList.contains("is-near-limit"), true);
  });

  test("a budget of one is warned about from the first call", async () => {
    // There is no "early" in a one-call budget, so a threshold that only
    // triggers on the second-to-last call would never fire at all.
    const container = await transcript(toolCard({ budget: "Tool call 1/1" }));
    assert.equal(budgetLabel(container)?.classList.contains("is-near-limit"), true);
  });

  test("a label the core did not write is not guessed at", async () => {
    // Parsed, not assumed. A malformed label must not throw and must not be
    // turned into a near-limit warning nobody measured.
    const container = await transcript(toolCard({ budget: "lots" }));
    assert.equal(budgetLabel(container)?.classList.contains("is-near-limit"), false);
  });
});

// --- the order a turn happened in -----------------------------------------
/*
 * A turn is several passes: prose, tool calls, more prose, more calls. All of
 * them write into one message, and `ToolCall.after` records how much of the
 * prose existed when each call started -- so this is where the rows have to be
 * drawn from it. The failure mode is not a missing row but a misleading
 * transcript: every row stacked under the turn's last paragraph reads as an
 * answer that decided what to do after saying it had done it, and the
 * paragraphs written before the first call used to be deleted outright by the
 * pass that followed them.
 */

/** The assistant bubble's children, in document order, as labelled runs. */
function runs(container: HTMLElement): string[] {
  const bubble = one(container, ".bubble-assistant")!;
  return [...bubble.children].map((child) => {
    if (child.classList.contains("tools")) {
      const names = [...child.querySelectorAll(".tool-name")]
        .map((name) => name.textContent)
        .join(",");
      return `tools:${names}`;
    }
    if (child.classList.contains("md")) return "text";
    return `other:${child.className}`;
  });
}

const call = (
  id: string,
  name: string,
  after?: number,
): ChatMessage["tools"][number] => ({ id, name, status: "ok", after });

describe("the order a turn happened in", () => {
  const first = "Let me look at the file. ";
  const second = first + "It is one line. ";

  test("each row is drawn under the words that asked for it", async () => {
    const container = await transcript(
      message({
        text: "Let me look at the file. It is one line. Done.",
        tools: [
          call("c1", "read_file", first.length),
          call("c2", "grep", first.length),
          call("c3", "edit_file", second.length),
        ],
      }),
    );

    assert.deepEqual(runs(container), [
      "text",
      "tools:read_file,grep",
      "text",
      "tools:edit_file",
      "text",
    ]);

    // The same thing said the other way round, because the order is the whole
    // claim: the turn's last words are last. A row after them means the calls
    // were collected at the end, which is the bug this replaces.
    assert.equal(runs(container).at(-1), "text");
  });

  test("the sentences land with the rows they belong to", async () => {
    const container = await transcript(
      message({
        text: "Let me look at the file. It is one line. Done.",
        tools: [call("c1", "read_file", first.length), call("c2", "edit_file", second.length)],
      }),
    );
    const prose = texts(container, ".md-p").map((piece) => piece ?? "");
    assert.equal(prose.length, 3, "a paragraph of the turn went missing");
    assert.match(prose[0], /Let me look at the file/);
    assert.match(prose[1], /It is one line/);
    assert.match(prose[2], /Done/);
  });

  test("consecutive calls stay one tight block", async () => {
    // A model that asks for five tools in one message asked for them together.
    // Five separate blocks would put air between calls that were batched, and
    // the block is what the 3px gap between rows belongs to.
    const container = await transcript(
      message({ text: "Fetching.", tools: [call("a", "read_file", 9), call("b", "grep", 9)] }),
    );
    assert.deepEqual(runs(container), ["text", "tools:read_file,grep"]);
    assert.equal(all(container, ".tools").length, 1);
  });

  test("a call nobody placed keeps the old place, after the prose", async () => {
    // A restored transcript from before the marks existed, or a message a test
    // built by hand. Dropping the row would lose a call the turn really made.
    const container = await transcript(
      message({ text: "An answer.", tools: [call("c1", "read_file")] }),
    );
    assert.deepEqual(runs(container), ["text", "tools:read_file"]);
  });

  test("a mark past the end of the prose cannot lose the row", async () => {
    // The prose a mark points into can be shorter than the mark -- a completion
    // that shortened a pass will do it. Clamped, not trusted.
    const container = await transcript(
      message({ text: "Short.", tools: [call("c1", "read_file", 999)] }),
    );
    assert.deepEqual(runs(container), ["text", "tools:read_file"]);
  });

  test("a turn whose calls came first keeps them first", async () => {
    // No prose before the first call: the rows lead and the answer follows,
    // which is the order those passes ran in.
    const container = await transcript(
      message({ text: "Done.", tools: [call("c1", "read_file", 0), call("c2", "edit_file", 0)] }),
    );
    assert.deepEqual(runs(container), ["tools:read_file,edit_file", "text"]);
  });

  test("the thinking panel still leads the turn it belongs to", async () => {
    const container = await transcript(
      message({
        text: "Answer.",
        reasoning: "Step one.",
        reasoningComplete: true,
        tools: [call("c1", "read_file", 0)],
      }),
    );
    const bubble = one(container, ".bubble-assistant")!;
    assert.equal(bubble.children[0].classList.contains("thinking"), true);
  });
});

// --- a subagent's nested work ---------------------------------------------
/*
 * Phase 5's nested UI: a child's frames accumulate under the `subagent` card
 * that spawned it (`applySubagentEvent` in events.ts) and render here. The
 * decision these pin is that the child is not a second assistant -- its answer
 * and its tool calls read as the *call's* work, one indent under the row. The
 * card's own status stays the parent call's; the nested head only says whether
 * the child itself is still working.
 */

function subagentCard(child?: ChatMessage["tools"][number]["child"]) {
  return toolCard({
    id: "sub-1",
    name: "subagent",
    detail: "subagent probe: 1/7 tool calls",
    child: child ?? {
      name: "probe",
      text: "child answer",
      tools: [
        { id: "kid-1", name: "list_agents", status: "ok", detail: "1 subagent(s)" },
      ],
      running: false,
    },
  });
}

describe("a subagent's nested work", () => {
  test("the child's tools and answer render under the card", async () => {
    const container = await transcript(subagentCard());
    assert.equal(all(container, ".subagent").length, 1);
    assert.equal(one(container, ".subagent-name")?.textContent, "probe");
    assert.equal(one(container, ".subagent-state")?.textContent, "answered");
    const rows = all(container, ".subagent-tool");
    assert.equal(rows.length, 1);
    assert.equal(one(rows[0], ".tool-name")?.textContent, "list_agents");
    assert.equal(one(rows[0], ".tool-detail")?.textContent, "1 subagent(s)");
    assert.equal(one(container, ".subagent-answer")?.textContent, "child answer");
  });

  test("a running child says so, and the rule takes the accent", async () => {
    const container = await transcript(
      subagentCard({ name: "probe", text: "", tools: [], running: true }),
    );
    assert.equal(one(container, ".subagent")?.classList.contains("is-running"), true);
    assert.equal(one(container, ".subagent-state")?.textContent, "working\u2026");
  });

  test("a failed child tool keeps its status", async () => {
    const container = await transcript(
      subagentCard({
        name: "probe",
        text: "",
        tools: [{ id: "kid-1", name: "write", status: "failed", detail: "denied" }],
        running: false,
      }),
    );
    assert.equal(all(container, ".subagent-tool-failed").length, 1);
  });

  test("a card with no child renders no nested block", async () => {
    const container = await transcript(toolCard({ name: "subagent" }));
    assert.equal(all(container, ".subagent").length, 0);
  });
});
