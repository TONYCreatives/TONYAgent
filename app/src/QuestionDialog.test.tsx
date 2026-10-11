/**
 * The one surface that asks the user anything.
 *
 * The core is blocked while this is up -- the tool that raised it is suspended
 * until `user.respond` arrives -- so unlike every other component in this app,
 * a bug here is not a wrong render. It is a turn that never finishes, or a
 * dialog that answers a question the user never saw. Both are what these tests
 * are for, and the second is why the fixture comes out of the *reducer* rather
 * than being written by hand: the props are built from the exact payload
 * `core/user_io.py::QuestionRequest.to_payload` emits, so a change to either
 * side of that contract fails here rather than in the window.
 *
 * The stylesheet is loaded for one reason: `ask-body` has to keep the line
 * breaks the core wrote *and* still wrap. That is the assertion the real
 * cascade can make and jsdom's computed style cannot, and a presentation that
 * lost its newlines would render as one unbroken paragraph.
 */

import "./test-dom.js";
import assert from "node:assert/strict";
import { test } from "node:test";

import { render, rerender, click, press, setValue, one, all, wait } from "./test-render.js";
import { QuestionDialog } from "./QuestionDialog.js";
import { Overlay } from "./Overlay.js";
import { applyEvent, initialState } from "./events.js";
import type { CoreEvent } from "./backend.js";
import { dom } from "./test-dom.js";
import { exitDurationMs } from "./useDelayedUnmount.js";
import { readStylesheetSource } from "./stylesheet.js";

const STYLESHEET = readStylesheetSource();

const style = dom.window.document.createElement("style");
style.textContent = STYLESHEET;
dom.window.document.head.appendChild(style);

/** The declarations the stylesheet gives one exact selector. */
function declaredFor(selector: string): string {
  return [...STYLESHEET.matchAll(/([^{}]+)\{([^{}]*)\}/g)]
    .filter(([, block]) => block.split(",").map((part) => part.trim()).includes(selector))
    .map(([, , body]) => body.replace(/\s+/g, " ").trim())
    .join(" ");
}

/** The props the window hands the dialog, built the way it builds them. */
function askFor(payload: Record<string, unknown>): NonNullable<ReturnType<typeof applyEvent>["pendingAsk"]> {
  const event: CoreEvent = {
    event: true,
    type: "user.asked",
    seq: 1,
    turn_id: "turn-1",
    payload,
  };
  const state = applyEvent(initialState, event);
  assert.ok(state.pendingAsk, "the payload produced no ask");
  return state.pendingAsk;
}

/** A real `ask_user_question` payload, as the core sends it. */
function question(overrides: Record<string, unknown> = {}) {
  return askFor({
    id: "q-1",
    name: "ask_user_question",
    kind: "question",
    prompt: "Postgres or SQLite?",
    content: "",
    options: ["Postgres", "SQLite"],
    ...overrides,
  });
}

/** A real `present` payload. */
function presentation(overrides: Record<string, unknown> = {}) {
  return askFor({
    id: "q-9",
    name: "present",
    kind: "presentation",
    prompt: "What I found",
    content: "Line one\nLine two",
    options: [],
    ...overrides,
  });
}

/** A recorded answer, so "exactly once" is an assertion and not a hope. */
function recorder(): { calls: [string, string][]; onRespond: (id: string, answer: string) => void } {
  const calls: [string, string][] = [];
  return { calls, onRespond: (id, answer) => void calls.push([id, answer]) };
}

function state(container: HTMLElement): string | null {
  return one(container, ".modal-backdrop")?.dataset.state ?? null;
}

function buttons(container: HTMLElement, label: string): HTMLElement | null {
  return all(container, "button").find((node) => node.textContent?.trim() === label) ?? null;
}

test("shows the question, and the core's options as buttons", async () => {
  const request = question();
  const { onRespond } = recorder();
  const container = await render(
    <Overlay open>
      <QuestionDialog request={request} onRespond={onRespond} />
    </Overlay>,
  );

  const dialog = one(container, ".modal")!;
  assert.equal(dialog.getAttribute("role"), "dialog");
  assert.equal(dialog.getAttribute("aria-modal"), "true");
  assert.equal(one(container, "#ask-title")!.textContent, "The agent has a question");
  assert.equal(one(container, ".ask-question")!.textContent, "Postgres or SQLite?");
  assert.equal(one(container, ".ask-from")!.textContent, "ask_user_question");

  // The options are what the buttons say, in the order the core sent them: the
  // user is choosing between these, and a reordered or renamed set is a
  // different question.
  assert.deepEqual(
    all(container, ".ask-options button").map((node) => node.textContent),
    ["Postgres", "SQLite"],
  );
});

test("a question with no options offers the box and nothing else", async () => {
  const request = question({ options: [] });
  const { onRespond } = recorder();
  const container = await render(
    <Overlay open>
      <QuestionDialog request={request} onRespond={onRespond} />
    </Overlay>,
  );
  assert.equal(all(container, ".ask-options button").length, 0);
  assert.ok(one(container, ".ask-note"));
  assert.ok(buttons(container, "Send answer"));
});

test("clicking an option answers with that option, once", async () => {
  const request = question();
  const { calls, onRespond } = recorder();
  const container = await render(
    <Overlay open>
      <QuestionDialog request={request} onRespond={onRespond} />
    </Overlay>,
  );
  await click(buttons(container, "Postgres")!);
  assert.deepEqual(calls, [["q-1", "Postgres"]]);
});

test("Enter in the box sends what was typed", async () => {
  const request = question();
  const { calls, onRespond } = recorder();
  const container = await render(
    <Overlay open>
      <QuestionDialog request={request} onRespond={onRespond} />
    </Overlay>,
  );
  const note = one(container, ".ask-note") as HTMLTextAreaElement;
  await setValue(note, "  Neither -- MongoDB  ");
  await press("Enter", note);
  // Trimmed, because the answer is pasted into a sentence the model reads.
  assert.deepEqual(calls, [["q-1", "Neither -- MongoDB"]]);
});

test("Shift+Enter is a newline, not an answer", async () => {
  const request = question();
  const { calls, onRespond } = recorder();
  const container = await render(
    <Overlay open>
      <QuestionDialog request={request} onRespond={onRespond} />
    </Overlay>,
  );
  const note = one(container, ".ask-note") as HTMLTextAreaElement;
  await setValue(note, "two lines");
  await press("Enter", note, { shiftKey: true });
  assert.deepEqual(calls, []);
});

test("Escape answers with nothing", async () => {
  // Not a refusal and not a cancellation -- an empty answer, which the core
  // reads as "no comment" and the model can act on. There is no third state to
  // send, and inventing one would be a thing the frontend and core had to agree
  // on for no gain.
  const request = question();
  const { calls, onRespond } = recorder();
  await render(
    <Overlay open>
      <QuestionDialog request={request} onRespond={onRespond} />
    </Overlay>,
  );
  await press("Escape");
  assert.deepEqual(calls, [["q-1", ""]]);
});

test("a presentation shows its content and acknowledges", async () => {
  const request = presentation();
  const { calls, onRespond } = recorder();
  const container = await render(
    <Overlay open>
      <QuestionDialog request={request} onRespond={onRespond} />
    </Overlay>,
  );

  // The presentation's own title, not a generic heading: the model chose it,
  // and a presentation that arrived under a fixed heading would be one the user
  // cannot tell from any other.
  assert.equal(one(container, "#ask-title")!.textContent, "What I found");
  assert.equal(one(container, ".ask-body")!.textContent, "Line one\nLine two");
  // No options: a presentation is not a choice.
  assert.equal(all(container, ".ask-options button").length, 0);
  assert.ok(buttons(container, "Acknowledge"));

  await click(buttons(container, "Acknowledge")!);
  assert.deepEqual(calls, [["q-9", ""]]);
});

test("a note on a presentation is sent with the acknowledgement", async () => {
  const request = presentation();
  const { calls, onRespond } = recorder();
  const container = await render(
    <Overlay open>
      <QuestionDialog request={request} onRespond={onRespond} />
    </Overlay>,
  );
  await setValue(one(container, ".ask-note") as HTMLTextAreaElement, "skip the migration");
  await click(buttons(container, "Acknowledge")!);
  assert.deepEqual(calls, [["q-9", "skip the migration"]]);
});

test("the content keeps its line breaks, in the real cascade", async () => {
  // `pre-wrap` is the whole difference between a presentation and a paragraph
  // run together. jsdom has no layout, so this is read off the stylesheet's own
  // text -- which also fails if the module ever stops being imported.
  const rule = declaredFor(".ask-body");
  assert.match(rule, /white-space:\s*pre-wrap/);
  assert.match(rule, /overflow-y:\s*auto/);
});

test("a second ask while the first is fading is answered for the new one", async () => {
  // The dialog outlives the flag that opened it by an animation's worth of
  // time, so a batch can produce a second ask before the first has left the
  // screen. Answering twice, or answering for the first, is what this pins.
  const first = question();
  const second = question({ id: "q-2", prompt: "Which schema?", options: ["public", "app"] });
  const { calls, onRespond } = recorder();
  const container = await render(
    <Overlay open>
      <QuestionDialog request={first} onRespond={onRespond} />
    </Overlay>,
  );

  await rerender(
    <Overlay open>
      <QuestionDialog request={second} onRespond={onRespond} />
    </Overlay>,
  );
  assert.equal(one(container, ".ask-question")!.textContent, "Which schema?");
  await click(buttons(container, "app")!);
  assert.deepEqual(calls, [["q-2", "app"]]);
});

test("answering waits for the window to close it, and stays mounted meanwhile", async () => {
  // The window clears `pendingAsk` locally first, so the overlay starts closing
  // while the core round trip is still in flight. The dialog must still be
  // there, and must not lose the request, for the length of that exit.
  const request = question();
  const { calls, onRespond } = recorder();
  const container = await render(
    <Overlay open>
      <QuestionDialog request={request} onRespond={onRespond} />
    </Overlay>,
  );

  await rerender(
    <Overlay open={false}>
      <QuestionDialog request={request} onRespond={onRespond} />
    </Overlay>,
  );
  assert.equal(state(container), "closed");
  assert.equal(one(container, ".ask-question")!.textContent, "Postgres or SQLite?");

  await click(buttons(container, "SQLite")!);
  assert.deepEqual(calls, [["q-1", "SQLite"]]);

  // The exit takes as long as the stylesheet says, so wait that plus a frame:
  // a shorter wait would fail this and serialise the still-mounted jsdom tree
  // into the failure message. A count rather than a node, for the same reason.
  await wait(exitDurationMs() + 40);
  assert.equal(all(container, ".modal-backdrop").length, 0, "the closed backdrop outlived its animation");
});


