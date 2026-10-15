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

/**
 * A turn as the model actually works: prose, calls, more prose, more calls.
 *
 * The core emits one `message.started`/`message.completed` pair per pass, and
 * every pass writes into the same message -- so a completion was deleting the
 * paragraphs written before it, and the rows that survived could only be drawn
 * after the final answer. The two integers asserted here are what the window
 * draws from: each call's place in the prose, and the whole turn's prose.
 */
test("a turn keeps its prose in order and marks where each call fell", () => {
  let state = applyEvent(initialState, event("turn.started"));

  state = applyEvent(state, event("message.started"));
  state = applyEvent(state, event("message.delta", { text: "Let me look. " }));
  state = applyEvent(state, event("message.completed", { text: "Let me look. " }));
  state = applyEvent(state, event("tool.started", { id: "c1", name: "read_file" }));
  state = applyEvent(state, event("tool.started", { id: "c2", name: "grep" }));

  state = applyEvent(state, event("message.started"));
  state = applyEvent(state, event("message.delta", { text: "Found it. " }));
  state = applyEvent(state, event("message.completed", { text: "Found it. " }));
  state = applyEvent(state, event("tool.started", { id: "c3", name: "edit_file" }));

  state = applyEvent(state, event("message.started"));
  state = applyEvent(state, event("message.completed", { text: "Done." }));

  const [message] = state.messages;
  assert.equal(message.text, "Let me look. Found it. Done.");
  assert.deepEqual(
    message.tools.map((tool) => [tool.name, tool.after]),
    [
      ["read_file", "Let me look. ".length],
      ["grep", "Let me look. ".length],
      ["edit_file", "Let me look. Found it. ".length],
    ],
  );
});

/**
 * The other half of the same contract, from the outside: a pass that ends with
 * text still replaces its own slice rather than only appending.
 *
 * A delta stream that dropped a chunk must not leave the turn with both the
 * streamed text and the authoritative one.
 */
test("a completion replaces its own pass and leaves the pass before it alone", () => {
  let state = applyEvent(initialState, event("turn.started"));
  state = applyEvent(state, event("message.delta", { text: "Let me look. " }));
  state = applyEvent(state, event("message.completed", { text: "Let me look. " }));
  state = applyEvent(state, event("tool.started", { id: "c1", name: "read_file" }));

  // The second pass streams a truncated version of its own sentence -- the
  // chunk carrying the rest was lost -- and its completion has to repair that
  // sentence without touching the one above the tool rows.
  state = applyEvent(state, event("message.started"));
  state = applyEvent(state, event("message.delta", { text: "The file is " }));
  state = applyEvent(state, event("message.completed", { text: "The file is small. " }));

  assert.equal(state.messages[0].text, "Let me look. The file is small. ");
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

test("a stopped turn takes its confirmation dialog down with it", () => {
  // The core settles a prompt its turn ended on, and the window must not
  // depend on that frame arriving: a stopped turn is exactly where the two can
  // get out of order, and a dialog the turn can no longer answer is a dialog
  // neither button means anything on. Measured before this: Stop during a
  // destructive call left Allow / Deny on screen over a turn that had ended.
  let state = applyEvent(initialState, event("turn.started"));
  state = applyEvent(state, event("tool.started", { id: "d1", name: "delete_file" }));
  state = applyEvent(
    state,
    event("confirmation.requested", {
      id: "d1",
      name: "delete_file",
      arguments: { path: "a.py" },
      destructive: true,
    }),
  );
  assert.equal(state.pendingConfirm?.id, "d1");

  state = applyEvent(state, event("turn.finished", { cancelled: true }));

  assert.equal(state.pendingConfirm, null, "the dialog outlived the turn it belonged to");
  assert.equal(state.busy, false);
});

test("another turn's terminal frame is not this turn's dialog closing", () => {
  // The subagent guard from the nested-UI pass, from the other side: a foreign
  // turn's `turn.finished` is ignored, so it must not take down a prompt the
  // turn this window is rendering is still waiting on.
  let state = applyEvent(initialState, event("turn.started", { model: "m" }, "t1"));
  state = applyEvent(state, event("confirmation.requested", {
    id: "d2",
    name: "delete_file",
    arguments: { path: "a.py" },
    destructive: true,
  }, "t1"));

  state = applyEvent(state, event("turn.finished", {}, "t-other"));

  assert.equal(state.pendingConfirm?.id, "d2");
  assert.equal(state.busy, true, "a foreign turn ended this one");
});

test("a question and its resolution clear the ask modal", () => {
  let state = applyEvent(
    initialState,
    event("user.asked", {
      id: "q1",
      name: "ask_user_question",
      kind: "question",
      prompt: "Postgres or SQLite?",
      content: "",
      options: ["Postgres", "SQLite"],
    }),
  );
  assert.equal(state.pendingAsk?.prompt, "Postgres or SQLite?");
  assert.deepEqual(state.pendingAsk?.options, ["Postgres", "SQLite"]);
  assert.equal(state.pendingAsk?.kind, "question");
  assert.equal(state.pendingAsk?.name, "ask_user_question");
  state = applyEvent(state, event("user.resolved", { id: "q1" }));
  assert.equal(state.pendingAsk, null);
});

test("a presentation is told apart from a question, and carries its body", () => {
  const state = applyEvent(
    initialState,
    event("user.asked", {
      id: "q2",
      name: "present",
      kind: "presentation",
      prompt: "What I found",
      content: "Line one\nLine two",
      options: [],
    }),
  );
  assert.equal(state.pendingAsk?.kind, "presentation");
  assert.equal(state.pendingAsk?.prompt, "What I found");
  assert.equal(state.pendingAsk?.content, "Line one\nLine two");
  assert.deepEqual(state.pendingAsk?.options, []);
});

test("a question with no options opens anyway, with none to click", () => {
  // A payload with a junk or absent `options` must still open the dialog: the
  // dialog is what unblocks the turn, and a blank button is a better outcome
  // than no dialog at all.
  const state = applyEvent(
    initialState,
    event("user.asked", { id: "q3", name: "ask_user_question", kind: "question", prompt: "Which?" }),
  );
  assert.deepEqual(state.pendingAsk?.options, []);
});

test("a finished turn cannot leave an ask behind", () => {
  // A stopped turn is the one path where the core may settle an ask after the
  // window has already ended the turn. A dialog the turn can no longer answer
  // is a dialog that can never be closed, so `turn.finished` takes it down
  // rather than waiting for the core to say so.
  let state = applyEvent(
    initialState,
    event("user.asked", {
      id: "q4",
      name: "ask_user_question",
      kind: "question",
      prompt: "Still there?",
    }),
  );
  assert.ok(state.pendingAsk);
  state = applyEvent(state, event("turn.finished"));
  assert.equal(state.pendingAsk, null);
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

// --- reasoning placed in order --------------------------------------------
//
// A turn that thinks, acts, then thinks again used to stack every thought into
// one block at the top, in the order they were reported rather than the order
// they happened. These pin the runs that fix it: each pass is its own block,
// placed against the prose, so the transcript reads "thought this, ran that,
// thought this."

test("each thinking pass becomes its own run, placed where it happened", () => {
  let state = applyEvent(initialState, event("turn.started"));
  // Pass one thinks, then writes a little prose, then asks for a tool.
  state = applyEvent(state, event("reasoning.delta", { text: "Let me look." }));
  state = applyEvent(state, event("message.delta", { text: "Checking." }));
  state = applyEvent(state, event("reasoning.completed", { text: "Let me look." }));
  state = applyEvent(state, event("tool.started", { id: "c1", name: "read_file" }));
  state = applyEvent(state, event("tool.completed", { id: "c1", result: changeResult("a.py", 1, 0) }));
  // Pass two thinks again before answering.
  state = applyEvent(state, event("reasoning.delta", { text: "Now I know." }));
  state = applyEvent(state, event("reasoning.completed", { text: "Now I know." }));

  const runs = state.messages[0].reasonRuns ?? [];
  assert.equal(runs.length, 2, "the two passes were not kept apart");
  assert.equal(runs[0].text, "Let me look.");
  assert.equal(runs[1].text, "Now I know.");
  // The second pass began after the prose of the first, so it is placed later.
  assert.ok(
    runs[1].after > runs[0].after,
    "the later thought was not placed after the earlier one's prose",
  );
});

test("a second pass's completion does not delete the first pass's thought", () => {
  // The latent bug: `reasoning.completed` used to overwrite the whole flat
  // field with *this pass's* text, so the first thought vanished the moment the
  // second one completed.
  let state = applyEvent(initialState, event("turn.started"));
  state = applyEvent(state, event("reasoning.delta", { text: "first" }));
  state = applyEvent(state, event("reasoning.completed", { text: "first" }));
  state = applyEvent(state, event("reasoning.delta", { text: "second" }));
  state = applyEvent(state, event("reasoning.completed", { text: "second" }));
  assert.equal(state.messages[0].reasoning, "firstsecond");
});

test("deltas that continue the open pass extend it rather than opening a new one", () => {
  let state = applyEvent(initialState, event("turn.started"));
  state = applyEvent(state, event("reasoning.delta", { text: "Let me " }));
  state = applyEvent(state, event("reasoning.delta", { text: "look." }));
  const runs = state.messages[0].reasonRuns ?? [];
  assert.equal(runs.length, 1, "one pass's deltas became more than one run");
  assert.equal(runs[0].text, "Let me look.");
});

test("a completion that loses its deltas still yields a placed pass", () => {
  // A provider may send only the finished thought. It must still be shown.
  let state = applyEvent(initialState, event("turn.started"));
  state = applyEvent(state, event("reasoning.completed", { text: "Just the tail." }));
  const runs = state.messages[0].reasonRuns ?? [];
  assert.equal(runs.length, 1);
  assert.equal(runs[0].text, "Just the tail.");
  assert.equal(runs[0].complete, true);
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

// --- a subagent's turn on the shared bus ----------------------------------
/*
 * A child session emits its own `turn.started` .. `turn.finished` on the same
 * bus as its parent, under its own turn id, and every one of its frames
 * carries `subagent`/`parent_call_id` -- the link to the call that spawned it
 * (see the core's `Event.subagent`). The frames below were captured from a
 * real run -- one parent turn that calls `subagent`, the child running a real
 * tool and answering, then the parent's answer -- with
 * `scripts/capture_child_frames.py`, because a hand-written sequence is the
 * thing the handoff warns about. Run that script to regenerate it; the ids and
 * the stub's text differ each run, the shape is the point.
 *
 * Before the card existed, these frames either rendered the child as an extra,
 * unlabelled assistant bubble (and cleared `busy` mid-turn), or -- after the
 * active-turn guard -- vanished. They now accumulate under the `subagent`
 * card, and these tests are the whole contract of that: one assistant message,
 * the child's tools and answer nested in its card, `busy` owned by the parent.
 */
const PARENT_TURN = "6d28ea180f744f289e4da1b6fc3711d7";
const CHILD_TURN = "1198ae0ab9dc44c4ac8de33a28515e91";

/** A frame from the child: every one of them says which call owns it. */
function childEvent(
  type: CoreEvent["type"],
  payload: Record<string, unknown> = {},
): CoreEvent {
  return { ...event(type, payload, CHILD_TURN), subagent: "probe", parent_call_id: "sub-1" };
}

const SUBAGENT_RUN: CoreEvent[] = [
  // The parent's turn opens and announces the subagent call.
  event("turn.started", { model: "stub-model" }, PARENT_TURN),
  event("message.started", {}, PARENT_TURN),
  event("message.completed", { text: "" }, PARENT_TURN),
  event("tool.started", { id: "sub-1", name: "subagent" }, PARENT_TURN),
  // The child's own turn, on its own id: one real tool, then its answer.
  childEvent("turn.started", { model: "stub-model" }),
  childEvent("message.started"),
  childEvent("message.completed", { text: "" }),
  childEvent("tool.started", { id: "kid-1", name: "list_agents" }),
  childEvent("tool.completed", {
    id: "kid-1",
    name: "list_agents",
    result: {
      status: "success",
      output: "- probe: running, mode build, permission medium, 1 used of 10 tool calls",
      summary: "1 subagent(s)",
      error: null,
      artifacts: [],
    },
  }),
  childEvent("message.started"),
  childEvent("message.delta", { text: "child answer" }),
  childEvent("message.completed", { text: "child answer" }),
  childEvent("turn.finished"),
  // The parent resumes and answers.
  event(
    "tool.completed",
    {
      id: "sub-1",
      name: "subagent",
      result: {
        status: "success",
        output: "child answer",
        summary: "subagent probe: 1/10 tool calls",
        error: null,
        artifacts: [],
      },
      tool_call_budget: { index: 1, limit: 10, label: "Tool call 1/10" },
    },
    PARENT_TURN,
  ),
  event("message.started", {}, PARENT_TURN),
  event("message.delta", { text: "parent answer" }, PARENT_TURN),
  event("message.completed", { text: "parent answer" }, PARENT_TURN),
  event("turn.finished", {}, PARENT_TURN),
];

test("a subagent's run is not rendered as the assistant's own", () => {
  let state = appendUserMessage(initialState, "delegate this");
  for (const frame of SUBAGENT_RUN) state = applyEvent(state, frame);

  const assistant = state.messages.filter((m) => m.role === "assistant");
  assert.equal(assistant.length, 1, "the child's turn was rendered as a second message");
  assert.equal(assistant[0].text, "parent answer");
  assert.ok(
    !assistant[0].text.includes("child answer"),
    "the child's answer leaked into the parent's own text",
  );
  assert.equal(assistant[0].tools.length, 1);
  assert.equal(assistant[0].tools[0].name, "subagent");
  // The parent's card reports the parent's call, not the child's work: the
  // summary the core wrote for this call.
  assert.equal(assistant[0].tools[0].detail, "subagent probe: 1/10 tool calls");
  assert.equal(state.busy, false);
  assert.equal(state.activeTurnId, null);
});

test("the child's work lands under the card that spawned it", () => {
  let state = appendUserMessage(initialState, "delegate this");
  for (const frame of SUBAGENT_RUN) state = applyEvent(state, frame);

  const child = state.messages.filter((m) => m.role === "assistant")[0].tools[0].child;
  assert.ok(child, "the child's frames left no nested work behind");
  assert.equal(child.name, "probe");
  assert.equal(child.text, "child answer");
  assert.equal(child.running, false);
  assert.equal(child.tools.length, 1, "the child's own tool call was not recorded");
  assert.equal(child.tools[0].name, "list_agents");
  assert.equal(child.tools[0].status, "ok");
  assert.equal(child.tools[0].detail, "1 subagent(s)");
});

test("while the child is working, its block says so", () => {
  let state = applyEvent(initialState, event("turn.started", { model: "m" }, PARENT_TURN));
  state = applyEvent(state, event("tool.started", { id: "sub-1", name: "subagent" }, PARENT_TURN));
  state = applyEvent(state, childEvent("turn.started", { model: "m" }));

  const running = state.messages[0].tools[0].child;
  assert.equal(running?.running, true, "a starting child must not look finished");
  assert.equal(running?.name, "probe");

  state = applyEvent(state, childEvent("turn.finished"));
  assert.equal(state.messages[0].tools[0].child?.running, false);
  // The child finishing is not the parent's call finishing, and it is not the
  // parent's turn finishing either.
  assert.equal(state.busy, true);
  assert.equal(state.messages[0].tools[0].status, "running");
});

test("a child finishing inside the parent's turn does not end it", () => {
  // The composer's lock and the Stop button both read `busy`; a child's
  // `turn.finished` that cleared it mid-turn re-enabled a composer the core
  // would refuse with "a turn is already running".
  let state = appendUserMessage(initialState, "delegate this");
  for (const frame of SUBAGENT_RUN) {
    state = applyEvent(state, frame);
    const parentDone = frame.type === "turn.finished" && frame.turn_id === PARENT_TURN;
    assert.equal(state.busy, !parentDone, `busy moved the wrong way at ${frame.type}`);
  }
});

test("a child with no card to land in is dropped, not bubbled", () => {
  // The conversation was switched away, or this is a restored transcript with
  // no cards. There is nowhere to show the child, and inventing a message for
  // it is the bug the nested view replaced.
  let state = initialState;
  for (const frame of SUBAGENT_RUN.filter((f) => f.parent_call_id)) {
    state = applyEvent(state, frame);
  }
  assert.equal(state.messages.length, 0);
  assert.equal(state.busy, false);
});

test("a child that cannot say whose it is stays a foreign turn", () => {
  // A child spawned outside a tool call (a script, a direct test) carries no
  // `parent_call_id`, and the window has no way to attribute it. The
  // active-turn guard is the fallback: ignored, not rendered.
  let state = applyEvent(initialState, event("turn.started", { model: "m" }, PARENT_TURN));
  state = applyEvent(state, event("turn.started", { model: "m" }, CHILD_TURN));
  state = applyEvent(state, event("message.delta", { text: "stray" }, CHILD_TURN));
  state = applyEvent(state, event("turn.finished", {}, CHILD_TURN));
  assert.equal(state.messages.length, 1, "a foreign turn created a message");
  assert.equal(state.messages[0].text, "");
  assert.equal(state.busy, true);
});

test("a child's failure is not the parent's banner", () => {
  // The audited runtime paths in tests/unit/test_subagents.py produce a real
  // child whose provider raises. The parent reads that as a failed subagent
  // in its tool result and carries on -- so the window must not paint the
  // turn failed while it is still running.
  let state = applyEvent(initialState, event("turn.started", { model: "m" }, PARENT_TURN));
  state = applyEvent(state, event("tool.started", { id: "sub-1", name: "subagent" }, PARENT_TURN));
  state = applyEvent(state, childEvent("turn.started", { model: "m" }));
  state = applyEvent(state, childEvent("turn.failed", { message: "provider exploded" }));
  assert.equal(state.error, null);
  assert.equal(state.busy, true);
  assert.equal(state.messages[0].tools[0].child?.running, false);

  state = applyEvent(state, event("message.delta", { text: "parent answer" }, PARENT_TURN));
  state = applyEvent(state, event("turn.finished", {}, PARENT_TURN));
  assert.equal(state.busy, false);
  assert.equal(state.error, null);
  assert.equal(state.messages.filter((m) => m.role === "assistant")[0].text, "parent answer");
});

// --- the workflow verbs: a follow-up's frames land on their own card --------
/*
 * Phase 6 lets one child be talked to again (`send_message`) and copied
 * (`subagent_fork`). The core stamps *each turn* with the id of the call that
 * asked for it (`Event.parent_call_id`), so a follow-up's frames carry
 * `send_message`'s call id and not the id of the `subagent` call that created
 * the child.
 *
 * The reducer routes child frames by that id alone and never looks at the
 * tool's name, which is what makes a follow-up render under its own card --
 * and this is the test that would fail if that ever changed to keying off the
 * `subagent` name.
 */
const CHILD_TURN_2 = "58f0d0c5f6a94e9f8a0e0d4b4e3a2c11";

function childEventFor(
  callId: string,
  type: CoreEvent["type"],
  payload: Record<string, unknown> = {},
  turn = CHILD_TURN,
): CoreEvent {
  return { ...event(type, payload, turn), subagent: "probe", parent_call_id: callId };
}

test("a follow-up turn is drawn under the send_message card, not the subagent card", () => {
  let state = appendUserMessage(initialState, "delegate this");
  state = applyEvent(state, event("turn.started", { model: "m" }, PARENT_TURN));

  // The first turn: `subagent` spawns `probe`, which answers.
  state = applyEvent(state, event("tool.started", { id: "sub-1", name: "subagent" }, PARENT_TURN));
  state = applyEvent(state, childEventFor("sub-1", "turn.started", { model: "m" }));
  state = applyEvent(state, childEventFor("sub-1", "message.completed", { text: "child one" }));
  state = applyEvent(state, childEventFor("sub-1", "turn.finished"));

  // The second: `send_message` hands the same child another turn on the same
  // transcript, under a different call id and a different turn id.
  state = applyEvent(
    state,
    event("tool.started", { id: "msg-1", name: "send_message" }, PARENT_TURN),
  );
  state = applyEvent(
    state,
    childEventFor("msg-1", "turn.started", { model: "m" }, CHILD_TURN_2),
  );
  state = applyEvent(
    state,
    childEventFor("msg-1", "message.completed", { text: "child two" }, CHILD_TURN_2),
  );
  state = applyEvent(state, childEventFor("msg-1", "turn.finished", {}, CHILD_TURN_2));

  const tools = state.messages.filter((m) => m.role === "assistant")[0].tools;
  assert.equal(tools.length, 2, "the follow-up did not get a card of its own");
  assert.equal(tools[0].name, "subagent");
  assert.equal(tools[0].child?.text, "child one");
  assert.equal(tools[1].name, "send_message");
  assert.equal(tools[1].child?.text, "child two", "the follow-up landed on the wrong card");
  // Both cards name the same child: one conversation, two of its turns.
  assert.equal(tools[1].child?.name, "probe");
  assert.equal(tools[1].child?.running, false);
});

test("interleaved children each keep their own card", () => {
  // Fan-out: several children run at once, so their frames arrive interleaved
  // -- start, start, delta, start, delta, delta. Routing by `parent_call_id`
  // is what keeps them apart; anything that tracked "the current child" would
  // append every delta to whichever one started last.
  let state = appendUserMessage(initialState, "fan out");
  state = applyEvent(state, event("turn.started", { model: "m" }, PARENT_TURN));
  for (const id of ["c1", "c2", "c3", "c4"]) {
    state = applyEvent(state, event("tool.started", { id, name: "subagent" }, PARENT_TURN));
  }

  const script: [string, string][] = [
    ["c1", "one"],
    ["c2", "two"],
    ["c1", " and one again"],
    ["c3", "three"],
    ["c2", " and two again"],
    ["c4", "four"],
  ];
  for (const [id, text] of script) {
    state = applyEvent(
      state,
      { ...event("message.delta", { text }, `${id}-turn`), subagent: id, parent_call_id: id },
    );
  }

  const tools = state.messages.filter((m) => m.role === "assistant")[0].tools;
  assert.deepEqual(
    tools.map((t) => t.child?.text),
    ["one and one again", "two and two again", "three", "four"],
  );
  assert.deepEqual(tools.map((t) => t.child?.name), ["c1", "c2", "c3", "c4"]);
});
