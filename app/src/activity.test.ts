import assert from "node:assert/strict";
import { describe, test } from "node:test";

import {
  elapsedMs,
  formatElapsed,
  runState,
  turnActivity,
} from "./activity.js";
import { blankMessage, initialState, type ChatState, type ToolCall } from "./events.js";

function tool(id: string, over: Partial<ToolCall> = {}): ToolCall {
  return { id, name: "read_file", status: "ok", ...over };
}

function assistant(id: string, tools: ToolCall[], over: Partial<ChatState> = {}): ChatState {
  return {
    ...initialState,
    messages: [{ ...blankMessage(id, "assistant"), tools }],
    ...over,
  };
}

describe("the run's state", () => {
  test("a dialog outranks the busy flag, because the agent is not working", () => {
    const state: ChatState = {
      ...assistant("t1", []),
      busy: true,
      activeTurnId: "t1",
      pendingConfirm: {
        id: "c1",
        name: "write_file",
        arguments: "{}",
        description: "write a file",
        destructive: true,
      },
    };
    assert.equal(runState(state), "waiting");
  });

  test("a question is the same state as a confirmation", () => {
    const state: ChatState = {
      ...initialState,
      busy: true,
      pendingAsk: {
        id: "q1",
        name: "ask_user_question",
        kind: "question",
        prompt: "Which one?",
        content: "",
        options: ["a", "b"],
      },
    };
    assert.equal(runState(state), "waiting");
  });

  test("a failed turn reports the failure, not the idle it fell back to", () => {
    assert.equal(runState({ ...initialState, error: "No API key" }), "error");
  });

  test("idle is the absence of all three", () => {
    assert.equal(runState(initialState), "idle");
  });
});

describe("the activity feed", () => {
  test("it reads the running turn's message, not the one before it", () => {
    const state: ChatState = {
      ...initialState,
      activeTurnId: "t2",
      busy: true,
      messages: [
        { ...blankMessage("t1", "assistant"), tools: [tool("old")] },
        { ...blankMessage("t2", "assistant"), tools: [tool("new")] },
      ],
    };
    const activity = turnActivity(state, 0);
    assert.deepEqual(
      activity.steps.map((step) => step.id),
      ["new"],
    );
  });

  test("with no turn running it keeps the last assistant run on screen", () => {
    const state: ChatState = {
      ...initialState,
      messages: [
        { ...blankMessage("u1", "user") },
        { ...blankMessage("t1", "assistant"), tools: [tool("a"), tool("b")] },
      ],
    };
    assert.deepEqual(
      turnActivity(state, 0).steps.map((step) => step.id),
      ["a", "b"],
    );
  });

  test("a step's summary is what the core said, and its name while it runs", () => {
    const state = assistant("t1", [
      tool("a", { name: "read_file", detail: "Read 42 lines" }),
      tool("b", { name: "grep", status: "running" }),
    ]);
    const [done, running] = turnActivity(state, 0).steps;
    assert.equal(done.summary, "Read 42 lines");
    assert.equal(running.summary, "grep");
  });

  test("one file edited in three passes is one row with the counts added up", () => {
    const state = assistant("t1", [
      tool("a", { path: "src/app.py", added: 12, removed: 3 }),
      tool("b", { path: "src/app.py", added: 2, removed: 1 }),
      tool("c", { path: "README.md", added: 1, removed: 0 }),
    ]);
    assert.deepEqual(turnActivity(state, 0).files, [
      { path: "src/app.py", added: 14, removed: 4 },
      { path: "README.md", added: 1, removed: 0 },
    ]);
  });

  test("a call that touched no file is not a file row", () => {
    const state = assistant("t1", [tool("a"), tool("b", { path: "a.py" })]);
    assert.deepEqual(
      turnActivity(state, 0).files.map((file) => file.path),
      ["a.py"],
    );
  });

  test("the counts are per status, and a failed call is not a done one", () => {
    const state = assistant("t1", [
      tool("a", { status: "ok" }),
      tool("b", { status: "failed" }),
      tool("c", { status: "running" }),
    ]);
    assert.deepEqual(turnActivity(state, 0).counts, { running: 1, done: 1, failed: 1 });
  });

  test("elapsed only exists while a turn is running, and only from a real start", () => {
    assert.equal(elapsedMs(null, 5000), null);
    assert.equal(elapsedMs(1000, 5000), 4000);
    assert.equal(elapsedMs(5000, 1000), 0, "a clock that went backwards is zero, not negative");

    const running: ChatState = {
      ...initialState,
      busy: true,
      activeTurnId: "t1",
      turnStartedAt: 1000,
    };
    assert.equal(turnActivity(running, 4000).elapsedMs, 3000);
    assert.equal(turnActivity(initialState, 4000).elapsedMs, null);
  });
});

describe("the run clock's text", () => {
  test("minutes and seconds, zero-padded", () => {
    assert.equal(formatElapsed(0), "0:00");
    assert.equal(formatElapsed(42_000), "0:42");
    assert.equal(formatElapsed(3_723_000), "1:02:03");
  });
});
