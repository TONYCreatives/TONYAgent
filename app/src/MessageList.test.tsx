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
import { readFileSync } from "node:fs";
import { describe, test } from "node:test";

import { MessageList } from "./MessageList.js";
import { MARK_RECTS } from "./AppMark.js";
import { FOCUSABLE, all, click, one, rerender, render, texts } from "./test-render.js";
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
  return render(<MessageList messages={[m]} busy={false} project="" />);
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
        project=""
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
        project=""
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
        project=""
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

// --- before the first message ----------------------------------------------
/*
 * The first-run panel, and the one constraint on it that has to be held rather
 * than intended: it is a picture, and pictures are not controls.
 *
 * Everything else in this file is about what a component does over time. This
 * is about what it must never do, which is the harder kind to keep, because the
 * failure is always an addition -- somebody adds a "load a demo conversation"
 * button, or makes the `/` hint a link to the skills list, or wraps the mark in
 * something clickable -- and every one of those additions reads locally like an
 * improvement. It is also invisible in a snapshot: a button here would be one
 * more line of markup.
 *
 * So the assertions below are negative ones, and they are negative on purpose:
 * a count of focusable things rather than a comparison against a string, a tag
 * allowlist rather than a tag comparison, the panel's own source read for the
 * one thing the DOM cannot show, and the mark's own path data pinned to the
 * shape on the taskbar so "the same glyph" is a fact about the file rather than
 * an intention in a comment.
 */


/**
 * The tags the panel is allowed to be built from.
 *
 * `rect` rather than `path`: the mark is two rects, and this allowlist
 * was written when it was two stroked paths. Both are SVG shapes that cannot
 * carry a React handler, which is the property being asserted -- the list is
 * about reachability, not about how the glyph is drawn, so it moves with the
 * artwork rather than with the artwork's construction.
 */
/**
 * The panel is built from these and nothing else.
 *
 * `button` is here for one element -- the folder's own. A tag allowlist cannot
 * say *one*, so it says which tags are allowed and the test below counts the
 * buttons separately; that split is why neither list alone is the test.
 */
const ALLOWED_TAGS = new Set([
  "div",
  "svg",
  "rect",
  "h1",
  "p",
  "ul",
  "li",
  "kbd",
  "button",
]);

/**
 * The empty panel, with the folder arguments a caller would pass.
 *
 * Defaults to "no folder, no picker" because that is the state the rest of
 * these tests are about -- the wordmark, the mark, the hints -- and none of
 * them care which folder is in force.
 */
const firstRun = (
  over: Partial<React.ComponentProps<typeof MessageList>> = {},
) =>
  render(<MessageList messages={[]} busy={false} project="" {...over} />);

describe("the first run", () => {
  test("the only thing on it to click is the folder", async () => {
    const container = await firstRun({
      project: "C:\\Users\\me\\project",
      onChooseFolder: () => {},
    });
    const panel = one(container, ".empty");
    assert.ok(panel, "the empty conversation renders no panel at all");

    // The panel itself is in the list, not only its descendants. `querySelector`
    // does not match the element it is called on, so a `tabIndex={-1}` written
    // on `.empty` itself passed the first version of this test -- which is the
    // whole reason this one is written the long way round.
    const everything = [panel, ...panel.querySelectorAll("*")];

    // One, named, rather than zero. This panel used to promise that nothing on
    // it was reachable, and it was true; the folder button is the exception the
    // user asked for, so the promise is now "one, and here is which" -- which
    // still fails on a second control, and says what the second one is.
    assert.deepEqual(
      everything
        .filter((el) => el.matches(FOCUSABLE))
        .map((el) => `${el.tagName.toLowerCase()}.${el.getAttribute("class") ?? ""}`),
      ["button.btn"],
      "the first-run panel has more on it than the folder button",
    );

    // The allowlist is the same promise stated differently, and it is the half
    // that survives a container React gave a handler: `onclick` is not an
    // attribute in the serialised markup, so nothing above can see it, but a
    // `<div onClick>` is still a click target. The tags below cannot carry one.
    const tags = everything.map((el) => el.tagName.toLowerCase());
    assert.deepEqual(
      [...new Set(tags)].filter((t) => !ALLOWED_TAGS.has(t)).sort(),
      [],
      "the first-run panel is built from a tag that can carry a handler",
    );

    // ...and `button` is the one allowed tag that can, so it is counted. An
    // allowlist that grew `button` and nothing else would still pass with five
    // of them on the panel; this is the half that says there is one.
    assert.equal(
      tags.filter((t) => t === "button").length,
      1,
      "the first-run panel has more than one button on it",
    );

    for (const el of everything) {
      for (const attr of el.getAttributeNames()) {
        assert.ok(
          !attr.startsWith("on") &&
            attr !== "tabindex" &&
            attr !== "role" &&
            attr !== "href" &&
            attr !== "contenteditable",
          `<${el.tagName.toLowerCase()}> carries ${attr}`,
        );
      }
    }
  });

  test("the folder button holds the panel's only handler", async () => {
    // The one hole in the DOM assertions above, found by trying it: React does
    // not put an event handler in the markup, so a `<div onClick>` or an
    // `onKeyDown` on the panel itself passes every assertion in the test above
    // and every one of them would keep passing. Nothing in jsdom can see it --
    // the handler simply is not there to see -- so this reads the component's
    // own source instead, which is where the mistake would be made.
    //
    // Scoped to `FirstRun` rather than the file, because the transcript below it
    // has no handlers either but does have perfectly good reasons to grow some,
    // and a test that failed on those would be a test that got switched off.
    //
    // It asserted *none*. It now asserts *one*, and the one is the folder: a
    // keydown on the panel would be a shortcut nothing can see, and a click on
    // the wordmark would be a control that is not one. Counting is the promise
    // that survives the button being there at all.
    const source = readFileSync(
      new URL("../src/MessageList.tsx", import.meta.url),
      "utf8",
    );
    const start = source.indexOf("function FirstRun(");
    assert.ok(start > -1, "FirstRun is gone from MessageList.tsx");
    const panel = source.slice(start, source.indexOf("\nexport function", start));
    assert.ok(panel.length > 0, "FirstRun has no body left to inspect");

    const handlers = [...panel.matchAll(/\bon[A-Z]\w*\s*[=:]/g)].map((m) => m[0]);
    assert.deepEqual(
      handlers,
      ["onClick="],
      `the first-run panel's handlers are ${JSON.stringify(handlers)}: only the `
        + "folder button's onClick is meant to be here",
    );
    for (const attr of ["tabIndex", "role=", "href=", "contentEditable"]) {
      assert.ok(
        !panel.includes(attr),
        `FirstRun writes ${attr}, which makes the panel something to reach`,
      );
    }
  });

  test("it names the folder in force, and says so with a Change button", async () => {
    // The name is what makes "you did not have to change anything" visible.
    // Without it the button would be an invitation to do a thing the user may
    // not need to do, and the panel would be asking rather than telling.
    const container = await firstRun({
      project: "C:\\Users\\me\\project",
      onChooseFolder: () => {},
    });

    const name = one(container, ".empty-folder-name");
    assert.equal(name?.textContent, "project");
    // The whole path, because a folder called `project` under two different
    // parents is the same label twice and the user cannot tell them apart.
    assert.equal(name?.getAttribute("title"), "C:\\Users\\me\\project");

    // "Change...", not "Choose...": there is a folder to change. "Choose" on a
    // panel that already has one reads as though nothing were selected.
    const button = one(container, ".empty-folder button");
    assert.equal(button?.textContent, "Change...");
    assert.equal(button?.getAttribute("type"), "button");
  });

  test("with no folder it says so, and the button offers to pick one", async () => {
    const container = await firstRun({ onChooseFolder: () => {} });
    assert.equal(
      one(container, ".empty-folder-name")?.textContent,
      "No project folder",
    );
    assert.equal(
      one(container, ".empty-folder button")?.textContent,
      "Choose folder...",
    );
  });

  test("a forward-slash path names the same folder as a backslash one", async () => {
    // The paths here come from Windows and from the picker, which on some
    // machines hands back a forward-slash form. Both name the last segment, so
    // the label does not change shape with the separator.
    const container = await firstRun({
      project: "/home/me/project",
      onChooseFolder: () => {},
    });
    assert.equal(one(container, ".empty-folder-name")?.textContent, "project");
  });

  test("the button is the panel's only action, and it fires once", async () => {
    // Not decoration, and not a second one: one handler, called once per click.
    let calls = 0;
    const container = await firstRun({
      project: "C:\\p",
      onChooseFolder: () => { calls += 1; },
      // Without this the button renders disabled -- correctly, since a window
      // that is busy cannot open a picker -- and a click on a disabled button
      // is nothing, which is how the first version of this test pressed one
      // and counted zero calls and nearly called the component broken.
      canChooseFolder: true,
    });
    const button = one(container, ".empty-folder button");
    assert.ok(button, "the panel has no folder button");
    await click(button);
    assert.equal(calls, 1, `the button was pressed ${calls} times`);

    // And the mark, the wordmark and the hints do not react to a click on
    // them -- they are not controls, and the count above would not catch one
    // that grew a handler of its own.
    for (const quiet of [".empty-mark", ".empty h1", ".empty-hints"]) {
      assert.ok(one(container, quiet), `${quiet} is gone from the panel`);
    }
    await click(one(container, ".empty h1")!);
    assert.equal(calls, 1, "clicking the wordmark did something");
  });

  test("it cannot be pressed while the caller says the window is busy", async () => {
    const container = await firstRun({
      project: "C:\\p",
      onChooseFolder: () => {},
      canChooseFolder: false,
    });
    assert.equal(
      one(container, ".empty-folder button")?.hasAttribute("disabled"),
      true,
    );

    const enabled = await firstRun({
      project: "C:\\p",
      onChooseFolder: () => {},
      canChooseFolder: true,
    });
    assert.equal(
      one(enabled, ".empty-folder button")?.hasAttribute("disabled"),
      false,
    );
  });

  test("with no picker to open it shows the folder and no button", async () => {
    // `onChooseFolder` is optional, so a caller that has nothing to open must
    // get a label rather than a dead button sitting next to it.
    const container = await firstRun({ project: "C:\\p" });
    assert.equal(one(container, ".empty-folder-name")?.textContent, "p");
    assert.equal(
      all(container, ".empty-folder button").length,
      0,
      "a folder button with nothing behind it",
    );
  });

  test("the mark is the app's own, drawn from the shipped path data", async () => {
    const container = await firstRun();
    const mark = one(container, ".empty-mark");
    assert.ok(mark, "the first-run panel does not draw the mark");

    assert.equal(mark.tagName.toLowerCase(), "svg");
    // Decorative, and said so: the wordmark right beside it is the name, so an
    // assistive technology reading the glyph out loud would repeat it.
    assert.equal(mark.getAttribute("aria-hidden"), "true");

    // The glyph is rects rather than paths, so this compares the five numbers
    // that describe each stroke. Read off the rendered DOM rather than off the
    // component, so what is checked is what the browser was handed.
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

    // Same reasoning as the rail's copy: the colour comes from the surface it
    // sits on, so a literal here would be the one pixel value in the app that
    // a change of `--accent` could not reach. `fill` rather than `stroke`,
    // because the glyph is drawn as filled rects -- a stroked mark would carry
    // the paint on `stroke` and this assertion would be testing the wrong one.
    assert.equal(mark.getAttribute("fill"), "currentColor");
    assert.equal(mark.getAttribute("stroke"), null);
    for (const attr of ["stroke", "fill", "color", "stop-color"]) {
      const value = mark.getAttribute(attr);
      if (value) {
        assert.ok(
          !/^#|rgb|hsl/i.test(value),
          `the mark names the colour ${value} instead of taking the surface's`,
        );
      }
    }
  });

  test("the hints are the ones the composer was hiding in its placeholder", async () => {
    const container = await firstRun();
    const hints = all(container, ".empty-hints > li").map(
      (li) => li.textContent ?? "",
    );
    assert.deepEqual(
      hints,
      ["/ for skills", "@ for threads or files"],
      "the promoted hints are not the placeholder's two keys",
    );

    // Drawn as keys rather than as buttons. A `<kbd>` says "this is a key you
    // press"; a `<button>` says "press this", and pressing one here would have
    // to either do nothing or steal the keystroke from the composer.
    for (const li of all(container, ".empty-hints > li")) {
      assert.equal(li.querySelectorAll("kbd").length, 1);
      assert.equal(li.querySelectorAll("button, a").length, 0);
    }
  });

  test("the wordmark and the line of orientation are both still here", async () => {
    // The two that were already on this panel, unchanged: the pass added to
    // them and did not rewrite them, so they are asserted rather than assumed.
    const container = await firstRun();
    assert.equal(one(container, ".empty h1")?.textContent, "TONYAgent");
    assert.equal(
      one(container, ".empty p")?.textContent,
      "Ask for something. The agent will use its tools to do it.",
    );
  });

  test("a first message replaces the panel rather than sitting under it", async () => {
    const container = await firstRun();
    await rerender(<MessageList messages={[message()]} busy={false} project="" />);
    assert.equal(
      all(container, ".empty").length,
      0,
      "the first-run panel is still on screen under the first answer",
    );

    // ...and clearing the conversation brings it back, rather than leaving a
    // blank field where the panel was.
    await rerender(<MessageList messages={[]} busy={false} project="" />);
    assert.equal(all(container, ".empty").length, 1);
  });
});
