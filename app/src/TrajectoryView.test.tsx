import "./test-dom.js";
import assert from "node:assert/strict";
import { describe, test } from "node:test";

import { TrajectoryView, captureEvent, type CapturedEvent } from "./TrajectoryView.js";
import type { CoreEvent } from "./backend.js";
import { click, one, render } from "./test-render.js";

/** One captured event, built the way App builds them from a pushed frame. */
function ev(type: string, payload: Record<string, unknown> = {}, n = 0): CapturedEvent {
  const raw = { event: true, type, turn_id: "t1", payload } as unknown as CoreEvent;
  return captureEvent(raw, n, 1_700_000_000_000 + n);
}

describe("the trajectory view", () => {
  test("an empty session explains what it is, not a blank pane", async () => {
    const container = await render(<TrajectoryView events={[]} />);
    assert.match(one(container, ".traj-empty")!.textContent ?? "", /tool calls/);
  });

  test("every event is shown, and the arguments and output reach the reader", async () => {
    const container = await render(
      <TrajectoryView
        events={[
          ev("message.completed", { text: "Let me look." }, 0),
          ev("tool.started", { id: "c1", name: "execute_command", arguments: { command: "ls" } }, 1),
          ev("tool.completed", { id: "c1", name: "execute_command", result: { status: "success", output: "a\nb" } }, 2),
        ]}
      />,
    );
    const text = container.textContent ?? "";
    assert.match(text, /message\.completed/);
    assert.match(text, /Let me look\./);
    assert.match(text, /execute_command/);
    // The exact arguments and the full output -- not just the tool's name.
    assert.match(text, /"ls"/);
    assert.match(text, /a\nb/);
  });

  test("a file change draws the real diff, coloured add and del", async () => {
    const container = await render(
      <TrajectoryView
        events={[
          ev("tool.completed", {
            id: "c1",
            name: "edit",
            result: {
              status: "success",
              output: "Replaced 1 in f.py",
              artifacts: [
                { type: "file_change", data: { path: "f.py", added: 1, removed: 1, diff: "@@ -1 +1 @@\n-alpha\n+beta" } },
              ],
            },
          }),
        ]}
      />,
    );
    const added = one(container, ".traj-diff-add");
    const removed = one(container, ".traj-diff-del");
    assert.ok(added, "the added diff line is not drawn, or not coloured");
    assert.ok(removed, "the removed diff line is not drawn, or not coloured");
    assert.match(added!.textContent ?? "", /\+beta/);
    assert.match(removed!.textContent ?? "", /-alpha/);
  });

  test("raw JSON is hidden until it is asked for", async () => {
    const container = await render(
      <TrajectoryView events={[ev("sandbox.status", { status: "running" })]} />,
    );
    assert.equal(one(container, ".traj-rawjson"), null, "the raw payload is on by default");
    await click(one(container, ".traj-rawtoggle input")!);
    assert.ok(one(container, ".traj-rawjson"), "the raw payload never appeared");
  });
});
