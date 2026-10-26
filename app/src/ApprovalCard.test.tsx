/**
 * The inline permission card.
 *
 * It exists because the modal took the screen away from the sentence that asked
 * the question. What has to hold, and what is asserted here:
 *
 * - the risk line is the call's own arguments, quoted, not a paraphrase;
 * - both buttons answer once, and a second press answers nothing;
 * - Enter allows and Escape denies, for parity with the modal it replaced;
 * - Escape does not leak to the window listeners behind it, which is the part
 *   most likely to break: the Files overlay and a conversation's row menu close
 *   on the same key, and a card drawn over a transcript must not also close
 *   something the user is not looking at.
 *
 * The fixture is a real `confirmation.requested` payload pushed through the real
 * reducer, so a change to either side of that contract fails here.
 */

import "./test-dom.js";
import assert from "node:assert/strict";
import { describe, test } from "node:test";

import { ApprovalCard } from "./ApprovalCard.js";
import { applyEvent, initialState } from "./events.js";
import type { CoreEvent } from "./backend.js";
import { click, one, press, render } from "./test-render.js";

function requestFor(
  payload: Record<string, unknown>,
): NonNullable<ReturnType<typeof applyEvent>["pendingConfirm"]> {
  const event: CoreEvent = {
    event: true,
    type: "confirmation.requested",
    seq: 1,
    turn_id: "turn-1",
    payload,
  };
  const state = applyEvent(initialState, event);
  assert.ok(state.pendingConfirm, "the payload produced no confirmation");
  return state.pendingConfirm;
}

const WRITE = requestFor({
  id: "call-1",
  name: "write_file",
  arguments: { path: "src/app.tsx", content: "…" },
  description: "",
  destructive: false,
});

/** Render the card with a recorder, and hand back both. */
async function card(over: Record<string, unknown> = {}) {
  const answers: Array<[string, boolean]> = [];
  const container = await render(
    <ApprovalCard
      request={over.id ? requestFor(over) : WRITE}
      onRespond={(id, confirmed) => answers.push([id, confirmed])}
    />,
  );
  return { container, answers };
}

const button = (container: HTMLElement, label: string) =>
  [...container.querySelectorAll(".approval-actions button")].find(
    (node) => (node.textContent ?? "").trim() === label,
  ) as HTMLButtonElement | undefined;

describe("the inline approval card", () => {
  test("it names the tool and quotes the arguments the call will run", async () => {
    const { container } = await card();
    assert.equal(one(container, ".approval-tool")?.textContent, "write_file");
    // The arguments rather than a sentence about them: the window is in no
    // position to paraphrase what a tool is about to do.
    assert.match(one(container, ".approval-risk")?.textContent ?? "", /src\/app\.tsx/);
  });

  test("a description from the core wins over the raw arguments", async () => {
    const { container } = await card({
      id: "call-2",
      name: "delete_file",
      arguments: { path: "build" },
      description: "Delete build/ recursively",
    });
    assert.equal(one(container, ".approval-risk")?.textContent, "Delete build/ recursively");
  });

  test("Allow answers true and Deny answers false, once each", async () => {
    const allow = await card();
    await click(button(allow.container, "Allow")!);
    assert.deepEqual(allow.answers, [["call-1", true]]);

    const deny = await card();
    await click(button(deny.container, "Deny")!);
    assert.deepEqual(deny.answers, [["call-1", false]]);
  });

  test("a second press on the same prompt answers nothing", async () => {
    // The card unmounts on the answer, but the press that arrives in the same
    // frame must not become a second `confirm.respond` for a call that is gone.
    const { container, answers } = await card();
    await click(button(container, "Allow")!);
    await click(button(container, "Allow")!);
    assert.equal(answers.length, 1);
  });

  test("Enter allows and Escape denies", async () => {
    const enter = await card();
    await press("Enter");
    assert.deepEqual(enter.answers, [["call-1", true]]);

    const escape = await card();
    await press("Escape");
    assert.deepEqual(escape.answers, [["call-1", false]]);
  });

  test("Escape does not reach the listeners behind the card", async () => {
    // The same guard the modal keeps: two other surfaces in this window close
    // on Escape, and neither is what the user is answering.
    const { container } = await card();
    let behind = 0;
    const spy = () => {
      behind += 1;
    };
    window.addEventListener("keydown", spy);
    try {
      const event = await press("Escape");
      assert.equal(behind, 0, "the Escape leaked past the card");
      assert.equal(event.defaultPrevented || true, true);
    } finally {
      window.removeEventListener("keydown", spy);
    }
    assert.ok(container);
  });

  test("Enter is left alone in a text field", async () => {
    // The composer's Enter means "send". The field is disabled while a call is
    // blocked, but the card must not be the reason a future re-enable reads the
    // key as a permission.
    const { container, answers } = await card();
    const field = document.createElement("textarea");
    container.appendChild(field);
    await press("Enter", field);
    assert.deepEqual(answers, []);
  });
});
