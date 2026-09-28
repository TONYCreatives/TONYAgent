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
