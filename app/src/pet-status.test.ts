/**
 * What the pet says, given a chat state.
 *
 * The reducer's state is the input, so these are claims about the *reading* of it
 * rather than about the events: which of the true things wins when more than one
 * is true, and what the card says when nothing is.
 */

import "./test-dom.js";
import assert from "node:assert/strict";
import { describe, test } from "node:test";

import { initialState, type ChatState, type ChatMessage, type ToolCall } from "./events.js";
import { firstLine, petStatus } from "./pet-status.js";

function message(tools: ToolCall[]): ChatMessage {
  return {
    id: "m1",
    role: "assistant",
    text: "",
    tools,
    reasoning: "",
    reasoningComplete: true,
    reasoningTruncated: false,
  };
}

function tool(over: Partial<ToolCall> = {}): ToolCall {
  return { id: "t1", name: "read_file", status: "running", ...over };
}

function state(over: Partial<ChatState> = {}): ChatState {
  return { ...initialState, ...over };
}

describe("the pet's status", () => {
  test("at rest it says so without claiming anything is happening", () => {
    const status = petStatus(state());
    assert.equal(status.mood, "idle");
    assert.equal(status.detail, "");
  });

  test("a turn blocked on the user is waiting, not working", () => {
    // **The order in `petStatus` is the whole design, and this is why.** A tool
    // that stopped to ask a question keeps the turn open while nothing at all
    // happens, so the reducer still reports `busy`. A card that said "working"
    // through a wait for the user would be the one moment the card is looked at,
    // saying the one thing that is not true.
    const waiting = petStatus(
      state({
        busy: true,
        messages: [message([tool()])],
        pendingConfirm: {
          id: "c1",
          name: "execute_command",
          arguments: "{}",
          description: "rm -rf build",
          destructive: true,
        },
      }),
    );

    assert.equal(waiting.mood, "waiting");
    assert.equal(waiting.label, "Needs your approval");
    assert.equal(waiting.detail, "rm -rf build");
  });

  test("a question is waiting too, and it says what was asked", () => {
    const asking = petStatus(
      state({
        busy: true,
        pendingAsk: {
          id: "q1",
          name: "ask_user_question",
          kind: "question",
          prompt: "Which database?",
          content: "",
          options: ["sqlite", "postgres"],
        },
      }),
    );

    assert.equal(asking.mood, "waiting");
    assert.equal(asking.detail, "Which database?");
  });

  test("a failure outranks the work it stopped", () => {
    // `turn.failed` leaves `busy` false usually, but not always -- a failure that
    // arrives mid-stream is the case where the two are both true, and the failure
    // is the one the user has to act on.
    const failed = petStatus(
      state({ busy: true, error: "connection reset by peer" }),
    );

    assert.equal(failed.mood, "failed");
    assert.equal(failed.detail, "connection reset by peer");
  });

  test("working names the tool it is inside, and only if one is running", () => {
    const running = petStatus(
      state({ busy: true, messages: [message([tool({ name: "grep" })])] }),
    );
    assert.equal(running.mood, "working");
    assert.equal(running.label, "Running grep");

    // Busy with nothing running yet is the model thinking, which is not a tool
    // and must not be named as one.
    const thinking = petStatus(state({ busy: true, messages: [message([])] }));
    assert.equal(thinking.mood, "working");
    assert.equal(thinking.label, "Thinking");
  });

  test("the running tool is the last one, not the first", () => {
    const nested = petStatus(
      state({
        busy: true,
        messages: [message([tool({ id: "a", name: "read_file" }), tool({ id: "b", name: "grep" })])],
      }),
    );
    assert.equal(nested.label, "Running grep");
  });

  test("a finished tool is not what it is doing", () => {
    const done = petStatus(
      state({
        busy: true,
        messages: [
          message([
            tool({ id: "a", name: "read_file", status: "ok", detail: "read 200 lines" }),
          ]),
        ],
      }),
    );
    assert.equal(done.label, "Thinking", "a tool that finished is being reported as running");
  });

  test("the second line is one line, and it knows when to stop", () => {
    assert.equal(firstLine("boom\nstack line"), "boom");
    assert.equal(firstLine("\n\n  padded  \n"), "padded");
    assert.equal(firstLine(""), "");
    const long = "x".repeat(400);
    assert.equal(firstLine(long).length, 120, "the truncation is not the length it claims");
    assert.ok(firstLine(long).endsWith("..."));
  });
});
