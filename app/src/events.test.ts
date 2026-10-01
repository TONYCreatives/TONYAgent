/**
 * Tests for the event reducer.
 *
 * These were missing while the reducer was pure plumbing, which was a
 * reasonable thing to skip. Phase 3 changed that: the reducer now parses the
 * core's `file_change` artifact to decide what the Files tree claims about
 * every changed file, and a silent parse failure there shows up as a tree
 * that is simply empty rather than as an error.
 *
 * The reducer is the only place that knows the shape of a tool result, so it
 * is the right place to pin that shape.
 */

import { test } from "node:test";
import assert from "node:assert/strict";

import { applyEvent, appendUserMessage, initialState, type ChatState } from "./events.js";
import type { CoreEvent } from "./backend.js";

let seq = 0;

function event(
  type: CoreEvent["type"],
  payload: Record<string, unknown> = {},
  turnId: string | null = "t1",
): CoreEvent {
  seq += 1;
  return { event: true, type, seq, turn_id: turnId, payload };
}

/** Drive a whole turn: assistant message, one tool, then the tool's result. */
function turnWithTool(
  name: string,
  result: unknown,
  status: "tool.completed" | "tool.failed" = "tool.completed",
): ChatState {
  let state = applyEvent(initialState, event("turn.started"));
  state = applyEvent(state, event("tool.started", { id: "c1", name }));
  return applyEvent(state, event(status, { id: "c1", result }));
}

function onlyTool(state: ChatState) {
  const tools = state.messages.flatMap((m) => m.tools);
  assert.equal(tools.length, 1, "expected exactly one tool call");
  return tools[0];
}

const changeResult = (path: string, added: number, removed: number) => ({
  status: "success",
  output: "Written 42 chars to whatever.py",
  error: null,
  artifacts: [{ type: "file_change", data: { path, added, removed } }],
  duration_ms: 1,
});

// --- the file_change artifact ---------------------------------------------

test("a file change carries its real path and line counts", () => {
  const state = turnWithTool("write_file", changeResult("src/app.py", 12, 3));
  const call = onlyTool(state);
  assert.equal(call.path, "src/app.py");
  assert.equal(call.added, 12);
  assert.equal(call.removed, 3);
});

test("the path comes from the artifact, not from the human-readable output", () => {
  // The output sentence names a *different* file than the artifact. If the
  // reducer scraped the sentence it would show the wrong file -- which is
  // exactly what it used to do.
  const state = turnWithTool("write_file", changeResult("real.py", 1, 0));
  assert.equal(onlyTool(state).path, "real.py");
});

test("a tool with no change artifact reports no path", () => {
  const state = turnWithTool("read_file", { status: "success", output: "file body" });
  const call = onlyTool(state);
  assert.equal(call.path, undefined);
  assert.equal(call.added, undefined);
  assert.equal(call.status, "ok");
});

test("a failed tool reports no change even when it carries an artifact", () => {
  // The decisive case. A refused write changed nothing, so a badge would be a
  // claim the filesystem contradicts.
  const state = turnWithTool(
    "write_file",
    changeResult("nope.py", 5, 0),
    "tool.failed",
  );
  const call = onlyTool(state);
  assert.equal(call.status, "failed");
  assert.equal(call.path, undefined);
  assert.equal(call.added, undefined);
});

test("a failure is read from the result, because the core sends one event type", () => {
  // `tool.failed` exists and the core never emits it: every finished call
  // arrives as `tool.completed`, whatever happened. Deriving the status from
  // the event therefore painted every failure in the colour that means "done".
  // Running for real is what showed it -- a card reading "No project folder
  // selected" with a green tick.
  const failed = onlyTool(
    turnWithTool("write_file", {
      status: "error",
      output: null,
      error: "No project folder selected",
      artifacts: [],
      duration_ms: 0,
    }),
  );
  assert.equal(failed.status, "failed");
  assert.equal(failed.detail, "No project folder selected");

  const cancelled = onlyTool(
    turnWithTool("write_file", { status: "cancelled", artifacts: [] }),
  );
  assert.equal(cancelled.status, "failed", "a stopped call is not a done call");

  const succeeded = onlyTool(
    turnWithTool("read_file", { status: "success", output: "file body" }),
  );
  assert.equal(succeeded.status, "ok");
});

test("a result with no status at all is not treated as a failure", () => {
  // Older frames and hand-written events may carry a bare result. Guessing
  // "failed" would paint working tools red, which is its own lie.
  const call = onlyTool(turnWithTool("read_file", { output: "just a string" }));
  assert.equal(call.status, "ok");
});

test("a zero/zero change is passed through rather than invented", () => {
  // The sidebar hides a 0/0 badge, but the reducer must not turn it into a
  // fake +1 to make something visible.
  const state = turnWithTool("write_file", changeResult("same.py", 0, 0));
  const call = onlyTool(state);
  assert.equal(call.added, 0);
  assert.equal(call.removed, 0);
});

test("a malformed artifact is ignored rather than crashing the turn", () => {
  const bad = [
    { status: "success", artifacts: "not a list" },
    { status: "success", artifacts: [null, 42, { type: "file_change" }] },
    { status: "success", artifacts: [{ type: "file_change", data: { added: 1 } }] },
    { status: "success", artifacts: [{ type: "other", data: { path: "x" } }] },
    { status: "success" },
  ];
  for (const result of bad) {
    const state = turnWithTool("write_file", result);
    assert.equal(onlyTool(state).path, undefined, JSON.stringify(result));
  }
});

test("non-numeric counts fall back to zero instead of NaN", () => {
  const state = turnWithTool("write_file", {
    status: "success",
    artifacts: [{ type: "file_change", data: { path: "a.py", added: "3", removed: null } }],
  });
  const call = onlyTool(state);
  assert.equal(call.path, "a.py");
  assert.equal(call.added, 0);
  assert.equal(call.removed, 0);
});

// --- turn lifecycle -------------------------------------------------------

test("a turn that produced nothing leaves no empty bubble", () => {
  let state = applyEvent(initialState, event("turn.started"));
  state = applyEvent(state, event("turn.finished"));
  assert.deepEqual(state.messages, []);
});

test("a failed turn leaves no empty bubble either", () => {
  // Found by running the packaged app with a credit-exhausted key: the error
  // banner rendered correctly and an empty assistant bubble sat under it,
  // which reads as a broken UI rather than as a rejected key. `turn.finished`
  // already cleaned up; the two failure paths did not.
  let state = applyEvent(initialState, event("turn.started"));
  state = applyEvent(state, event("turn.failed", { message: "Key limit exceeded" }));
  assert.deepEqual(state.messages, []);
  assert.equal(state.error, "Key limit exceeded");

  // A bare `error` event, which is how a failure outside a turn arrives, is
  // the same story and must be treated the same way.
  state = applyEvent(initialState, event("turn.started", {}, "t2"));
  state = applyEvent(state, event("error", { message: "Backend error." }, "t2"));
  assert.deepEqual(state.messages, []);
  assert.equal(state.error, "Backend error.");
});

test("a failed turn that did produce text keeps its message", () => {
  // The cleanup is about empty placeholders, not about hiding failures. A turn
  // that streamed an answer and then failed must keep the answer.
  let state = applyEvent(initialState, event("turn.started"));
  state = applyEvent(state, event("message.delta", { text: "partial answer" }));
  state = applyEvent(state, event("turn.failed", { message: "upstream 500" }));
  assert.equal(state.messages.length, 1);
  assert.equal(state.messages[0].text, "partial answer");
  assert.equal(state.error, "upstream 500");
});

test("a tool call with no prose is not an empty bubble", () => {
  // A turn that only ran a tool carries no assistant text, and deleting it
  // would erase the tool row -- the one thing the turn actually did.
  const state = turnWithTool("read_file", { status: "success" });
  assert.equal(state.messages.length, 1);
  assert.equal(state.messages[0].tools.length, 1);
  assert.equal(state.messages[0].text, "");
});

test("turn.finished clears busy and turn.failed reports the message", () => {
  let state = applyEvent(initialState, event("turn.started"));
  assert.equal(state.busy, true);
  state = applyEvent(state, event("turn.finished"));
  assert.equal(state.busy, false);

  state = applyEvent(state, event("turn.started", {}, "t2"));
  state = applyEvent(state, event("turn.failed", { message: "upstream 500" }, "t2"));
  assert.equal(state.busy, false);
  assert.equal(state.error, "upstream 500");
});

test("message.completed replaces the streamed text rather than appending", () => {
  let state = applyEvent(initialState, event("turn.started"));
  state = applyEvent(state, event("message.delta", { text: "par" }));
  state = applyEvent(state, event("message.delta", { text: "tial" }));
  assert.equal(state.messages[0].text, "partial");
  // A lost chunk must not be papered over by duplicating what did arrive.
  state = applyEvent(state, event("message.completed", { text: "partial and final" }));
  assert.equal(state.messages[0].text, "partial and final");
});

test("a tool result is paired by call id, not by position", () => {
  let state = applyEvent(initialState, event("turn.started"));
  state = applyEvent(state, event("tool.started", { id: "a", name: "read_file" }));
  state = applyEvent(state, event("tool.started", { id: "b", name: "write_file" }));
  state = applyEvent(
    state,
    event("tool.completed", { id: "b", result: changeResult("b.py", 1, 0) }),
  );
  const [first, second] = state.messages[0].tools;
  assert.equal(first.name, "read_file");
  assert.equal(first.path, undefined, "read_file must not inherit b's result");
  assert.equal(second.path, "b.py");
});

test("a confirmation request and its resolution clear the modal", () => {
  let state = applyEvent(
    initialState,
    event("confirmation.requested", {
      id: "c1",
      name: "delete_file",
      arguments: { path: "a.py" },
      destructive: true,
    }),
  );
  assert.equal(state.pendingConfirm?.name, "delete_file");
  assert.equal(state.pendingConfirm?.destructive, true);
  state = applyEvent(state, event("confirmation.resolved", { id: "c1" }));
  assert.equal(state.pendingConfirm, null);
});

test("sandbox and log events are ignored without disturbing the view", () => {
  const before = applyEvent(initialState, event("turn.started"));
  const after = applyEvent(before, event("sandbox.status", { status: "running" }));
  assert.deepEqual(after.messages, before.messages);
  assert.equal(after.busy, before.busy);
});

test("appendUserMessage is a local echo the core never sends", () => {
  const state = appendUserMessage(initialState, "hello");
  assert.equal(state.messages.length, 1);
  assert.equal(state.messages[0].role, "user");
  assert.equal(state.messages[0].text, "hello");
});

test("the reducer does not mutate the state it was given", () => {
  const before = applyEvent(initialState, event("turn.started"));
  const snapshot = JSON.stringify(before);
  applyEvent(before, event("tool.started", { id: "x", name: "read_file" }));
  assert.equal(JSON.stringify(before), snapshot);
});

// --- reasoning ------------------------------------------------------------
//
// The whole point of the separate channel, restated as assertions: a
// reasoning model's thinking must not end up inside its own answer, and it
// must survive the same append/replace contract `message.delta` has.

test("reasoning deltas append to their own field, never to the answer", () => {
  let state = applyEvent(initialState, event("turn.started"));
  state = applyEvent(state, event("reasoning.delta", { text: "Let me " }));
  state = applyEvent(state, event("reasoning.delta", { text: "look." }));
  state = applyEvent(state, event("message.delta", { text: "Found it." }));

  const message = state.messages[0];
  assert.equal(message.reasoning, "Let me look.");
  assert.equal(message.text, "Found it.");
  assert.ok(!message.text.includes("Let me"), "thinking leaked into the answer");
});

test("reasoning.completed replaces the text rather than appending it", () => {
  let state = applyEvent(initialState, event("turn.started"));
  state = applyEvent(state, event("reasoning.delta", { text: "half" }));
  state = applyEvent(
    state,
    event("reasoning.completed", { text: "half and the rest" }),
  );
  // Appending would give "halffull..." -- a duplicate is how a lost delta
  // turns into a text that reads like two thoughts glued together.
  assert.equal(state.messages[0].reasoning, "half and the rest");
  assert.equal(state.messages[0].reasoningComplete, true);
});

test("a budget-exhausted turn is flagged on the message, not just the banner", () => {
  let state = applyEvent(initialState, event("turn.started"));
  state = applyEvent(state, event("reasoning.delta", { text: "thinking" }));
  state = applyEvent(
    state,
    event("reasoning.completed", { text: "thinking", truncated: true, notice: "ran out" }),
  );
  const message = state.messages[0];
  assert.equal(message.reasoningTruncated, true);
  assert.equal(message.reasoningNotice, "ran out");
});

test("a turn that only thought is not dropped as an empty bubble", () => {
  let state = applyEvent(initialState, event("turn.started"));
  state = applyEvent(state, event("reasoning.delta", { text: "thinking" }));
  state = applyEvent(state, event("turn.finished"));
  // It produced no answer, but it produced something worth showing and
  // something worth explaining. Dropping it leaves the user with a turn that
  // appears to have done nothing.
  assert.equal(state.messages.length, 1);
});

test("an answer with no reasoning leaves the panel with nothing to render", () => {
  let state = applyEvent(initialState, event("turn.started"));
  state = applyEvent(state, event("message.delta", { text: "Just an answer." }));
  state = applyEvent(state, event("message.completed", { text: "Just an answer." }));
  state = applyEvent(state, event("turn.finished"));
  assert.equal(state.messages[0].reasoning, "");
  assert.equal(state.messages[0].reasoningComplete, false);
});

test("a new turn does not inherit the previous turn's reasoning", () => {
  let state = applyEvent(initialState, event("turn.started", {}, "t1"));
  state = applyEvent(state, event("reasoning.delta", { text: "first" }, "t1"));
  state = applyEvent(state, event("turn.finished", {}, "t1"));
  state = applyEvent(state, event("turn.started", {}, "t2"));
  state = applyEvent(state, event("reasoning.delta", { text: "second" }, "t2"));
  const byId = Object.fromEntries(state.messages.map((m) => [m.id, m]));
  assert.equal(byId.t1.reasoning, "first");
  assert.equal(byId.t2.reasoning, "second");
});

test("a user message carries no reasoning to render", () => {
  const state = appendUserMessage(initialState, "hi");
  assert.equal(state.messages[0].reasoning, "");
  assert.equal(state.messages[0].reasoningComplete, false);
});

// --- the tool call budget -------------------------------------------------
/*
 * The core counts tool calls and reports where the turn stands, as
 * "Tool call 3/10", on the event and inside the result the model reads.
 *
 * The reducer's job is to carry that number, not to produce it. A budget
 * counted here -- by tallying the tool cards in the transcript -- would
 * disagree with the core the moment a call was refused, a conversation was
 * restored from disk, or an event was dropped, and the number on the card is
 * the number that bounds what the model can spend.
 */

const budget = (index: number, limit: number) => ({
  index,
  limit,
  label: `Tool call ${index}/${limit}`,
});

function turnWithBudget(
  result: unknown = { status: "success", output: "ok", artifacts: [] },
) {
  let state = applyEvent(initialState, event("turn.started"));
  state = applyEvent(state, event("tool.started", { id: "c1", name: "read_file" }));
  return applyEvent(
    state,
    event("tool.completed", { id: "c1", result, tool_call_budget: budget(3, 10) }),
  );
}

test("a tool result carries the turn's tool-call standing", () => {
  assert.equal(onlyTool(turnWithBudget()).budget, "Tool call 3/10");
});

test("the budget is read from the event, not counted from the cards", () => {
  // One card, but the core says this was the third call of ten. A counter
  // would say 1/10, which understates the turn by two calls and would never
  // show the warning that the budget is nearly gone.
  const call = onlyTool(turnWithBudget());
  assert.equal(call.budget, "Tool call 3/10");
  assert.notEqual(call.budget, "Tool call 1/10");
});

test("a refused call still carries a number", () => {
  // The one card where the number matters most: this is the call the budget
  // would not pay for, and the reader needs to see where the turn ended up.
  const call = onlyTool(
    turnWithBudget({ status: "error", error: "Not run: budget exhausted" }),
  );
  assert.equal(call.status, "failed");
  assert.equal(call.budget, "Tool call 3/10");
});

test("a call with no budget shows no number", () => {
  // A gateway that does not report one, or a result from a restored
  // conversation. Inventing "Tool call 1/10" here would be a claim about a
  // turn this file knows nothing about.
  const call = onlyTool(turnWithTool("read_file", { status: "success", artifacts: [] }));
  assert.equal(call.budget, undefined);
});

test("an unlabelled budget is not drawn as one", () => {
  // The label is what the core asserts; a budget object without one is not
  // something this file can turn into a number it did not measure.
  let state = applyEvent(initialState, event("turn.started"));
  state = applyEvent(state, event("tool.started", { id: "c1", name: "read_file" }));
  state = applyEvent(
    state,
    event("tool.completed", {
      id: "c1",
      result: { status: "success", artifacts: [] },
      tool_call_budget: { index: 2, limit: 10 },
    }),
  );
  assert.equal(onlyTool(state).budget, undefined);
});
