/**
 * The confirmation is the only surface in this app that had never been watched
 * opening or closing.
 *
 * Reaching it in the packaged app needs a project folder, and a project folder
 * is only ever set by the native folder picker: `chooseFolder` in `App.tsx`
 * calls `pickFolder()`, and the picker is the sole caller of `sandbox.start`.
 * That matters because `tools/orchestrator.py` checks for a folder *before* it
 * asks for confirmation --
 *
 *     if tool_call.name != "http_request" and not folder_manager.current_folder:
 *         return ToolResult(status=ERROR, error="No project folder selected")
 *     if tool.destructive and tool.requires_confirmation:
 *         ... await self._request_confirmation(...)
 *
 * -- and the one tool exempt from the folder check, `http_request`, is
 * `destructive = False`, so it can never reach the confirmation branch. No
 * prompt from the model, and no CDP-driven click, gets past that. So the
 * observation happens here instead: the real component, through the props the
 * real reducer produces, inside the real `Overlay` the window puts around it.
 *
 * The fixture is built by feeding a real `confirmation.requested` payload --
 * the exact keys `core/session.py::_on_confirmation_requested` emits -- through
 * the real `applyEvent`, so a change to either side that breaks the contract
 * fails here rather than at runtime over a blocked turn.
 *
 * The real stylesheet is loaded into the document on purpose. jsdom resolves no
 * `animation-name` (there is no animation engine, so every one of them reads
 * back as `none`), which is why the animation names are asserted against the
 * stylesheet's own text below rather than against computed style. It *does*
 * cascade ordinary declarations, so `pointer-events` and `--motion-fast` here
 * are the real ones the browser would use -- which is what makes "the closed
 * backdrop cannot swallow a click" and "the exit lasts as long as the animation
 * declares" testable at all. The keyframe names are confirmed in the real
 * webview separately, on the settings overlay, which shares the identical
 * `.modal-backdrop[data-state] > .modal` rules.
 */

import "./test-dom.js";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import { render, rerender, click, press, one, all, wait } from "./test-render.js";
import { ConfirmDialog } from "./ConfirmDialog.js";
import { Overlay } from "./Overlay.js";
import { applyEvent, initialState } from "./events.js";
import type { CoreEvent } from "./backend.js";
import { exitDurationMs } from "./useDelayedUnmount.js";
import { dom } from "./test-dom.js";

/**
 * The real stylesheet, in the document.
 *
 * `tsc` emits the tests to `.tmp/` and copies no other file, so the stylesheet
 * is one directory up from the compiled module rather than beside it.
 */
const STYLESHEET = readFileSync(new URL("../src/styles.css", import.meta.url), "utf8")
  // Comments go before the rules are read, not inside the reader. styles.css
  // documents each of these rules in a comment that mentions the very selector
  // it documents -- and contains commas and brackets doing it -- so a comment
  // left in place is parsed as part of the selector it precedes, and the rule
  // after it becomes unfindable.
  .replace(/\/\*[\s\S]*?\*\//g, "");

const style = dom.window.document.createElement("style");
style.textContent = STYLESHEET;
dom.window.document.head.appendChild(style);

/**
 * The declarations the stylesheet gives one exact selector.
 *
 * Selectors are matched exactly rather than by substring, because the two
 * states of every surface are written as the same class with a different
 * attribute -- `.modal-backdrop[data-state="open"]` and `..."closed"` -- and a
 * substring match would let the exit test pass on the entrance's rule.
 */
function declaredFor(selector: string): string {
  return [...STYLESHEET.matchAll(/([^{}]+)\{([^{}]*)\}/g)]
    .filter(([, block]) => block.split(",").map((part) => part.trim()).includes(selector))
    .map(([, , body]) => body.replace(/\s+/g, " ").trim())
    .join(" ");
}

/**
 * The props the window hands the dialog, built the way it builds them.
 *
 * `pendingConfirm` comes out of the reducer rather than being written by hand,
 * so `arguments` is the string the dialog actually displays -- the core sends a
 * dict and `formatArguments` is what turns it into something readable.
 */
function requestFor(payload: Record<string, unknown>): NonNullable<ReturnType<typeof applyEvent>["pendingConfirm"]> {
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

/** What a real destructive `write_file` confirmation looks like on the wire. */
function destructiveWrite(overrides: Record<string, unknown> = {}) {
  return requestFor({
    id: "call-1",
    name: "write_file",
    arguments: { path: "notes.txt", content: "hello" },
    description: "Write a file, replacing any existing content.",
    destructive: true,
    ...overrides,
  });
}

/** A recorded answer, so "exactly once" is an assertion and not a hope. */
function recorder(): { calls: [string, boolean][]; onRespond: (id: string, confirmed: boolean) => void } {
  const calls: [string, boolean][] = [];
  return { calls, onRespond: (id, confirmed) => void calls.push([id, confirmed]) };
}

/** The backdrop's published state, or null once it is gone. */
function state(container: HTMLElement): string | null {
  return one(container, ".modal-backdrop")?.dataset.state ?? null;
}

/** The answer button with this label, or null. */
function button(container: HTMLElement, label: string): HTMLElement | null {
  return all(container, ".modal-actions button").find((node) => node.textContent?.trim() === label) ?? null;
}

test("shows the tool the core asked about, through the props the core sends", async () => {
  const request = destructiveWrite();
  const { onRespond } = recorder();
  const container = await render(
    <Overlay open>
      <ConfirmDialog request={request} onRespond={onRespond} />
    </Overlay>,
  );

  const dialog = one(container, ".modal")!;
  assert.equal(dialog.getAttribute("role"), "dialog");
  assert.equal(dialog.getAttribute("aria-modal"), "true");
  assert.equal(one(container, "#confirm-title")!.textContent, "Confirm tool execution");

  // The name and the arguments are the whole point of the prompt: a user who
  // cannot see which tool is about to run, and against what, has been asked to
  // approve a guess.
  assert.equal(one(container, ".confirm-detail dd")!.textContent, "write_file");
  assert.equal(one(container, ".confirm-detail code")!.textContent, '{"path":"notes.txt","content":"hello"}');

  // Destructive is the flag the core sets from `tool.destructive`, and it is the
  // difference between "this will change something" and "this is a decision".
  assert.equal(one(container, ".warn")!.textContent, "This action is destructive and cannot be undone.");
});

test("a non-destructive tool gets no warning, and no arguments block when it has none", async () => {
  // Both fields are conditional on the payload. Rendering an empty Arguments
  // row or a red "cannot be undone" line over a read-only tool teaches the user
  // that the warnings are decoration.
  const request = requestFor({ id: "call-2", name: "read_file", destructive: false });
  assert.equal(request.arguments, "");
  const { onRespond } = recorder();
  const container = await render(
    <Overlay open>
      <ConfirmDialog request={request} onRespond={onRespond} />
    </Overlay>,
  );
  assert.equal(all(container, ".confirm-detail dt").map((dt) => dt.textContent).join(","), "Tool");
  assert.equal(one(container, ".warn"), null);
});

test("opening plays the backdrop fade and the dialog rise", async () => {
  const request = destructiveWrite();
  const { onRespond } = recorder();
  const container = await render(
    <Overlay open>
      <ConfirmDialog request={request} onRespond={onRespond} />
    </Overlay>,
  );

  // The contract the stylesheet keys off. `data-state` is what selects the
  // animation, so an overlay that published anything else would sit unanimated
  // no matter what the CSS says.
  assert.equal(state(container), "open");

  // Exactly one backdrop. A dialog that also carried an `Overlay` of its own
  // shipped once: the window behind was scrimmed twice and the inner backdrop
  // was permanently `open`, so the dialog could never play its exit at all.
  assert.equal(all(container, ".modal-backdrop").length, 1);

  // jsdom has no animation engine and reports every `animation-name` as `none`,
  // so the names are read off the stylesheet instead. Both halves matter: a
  // fade on the backdrop with no rise on the dialog makes the dialog look like
  // it is fading rather than arriving, which is why there are two rules.
  assert.match(declaredFor('.modal-backdrop[data-state="open"]'), /animation:\s*fade-in\b/);
  assert.match(declaredFor('.modal-backdrop[data-state="open"] > .modal'), /animation:\s*rise-in\b/);
});

test("closing plays the exit pair for the full delay the stylesheet declares", async () => {
  const request = destructiveWrite();
  const { onRespond } = recorder();
  const open = (
    <Overlay open>
      <ConfirmDialog request={request} onRespond={onRespond} />
    </Overlay>
  );
  const container = await render(open);

  // The delay is read from the same token the exits are written in, so this is
  // the number the browser would use and not a constant copied into a test.
  const delay = exitDurationMs();
  assert.equal(
    dom.window.getComputedStyle(dom.window.document.documentElement).getPropertyValue("--motion-fast").trim(),
    "110ms",
    "the stylesheet token the exit delay is read from changed",
  );
  assert.equal(delay, 140, "110ms of animation plus the slack that covers the removal frame");

  await rerender(
    <Overlay open={false}>
      <ConfirmDialog request={request} onRespond={onRespond} />
    </Overlay>,
  );
  assert.equal(state(container), "closed");

  // Still on screen a long way into the exit: the animation runs for 110ms, so
  // a node that has already gone at 90ms was cut off mid-frame rather than
  // animated out.
  await wait(90);
  assert.equal(state(container), "closed", "the dialog vanished before its exit had finished");
  assert.equal(all(container, ".modal").length, 1);

  await wait(delay);
  assert.equal(one(container, ".modal-backdrop"), null, "the closed backdrop outlived its animation");

  // The exit pair, read off the stylesheet: the backdrop fades out and the
  // dialog rises back out of place, both on the fast token the delay above was
  // read from.
  assert.match(declaredFor('.modal-backdrop[data-state="closed"]'), /animation:\s*fade-out[^;]*var\(--motion-fast\)/);
  assert.match(declaredFor('.modal-backdrop[data-state="closed"] > .modal'), /animation:\s*rise-out[^;]*var\(--motion-fast\)/);
});

test("the request survives the exit window, answer and all", async () => {
  const request = destructiveWrite();
  const { calls, onRespond } = recorder();
  const container = await render(
    <Overlay open>
      <ConfirmDialog request={request} onRespond={onRespond} />
    </Overlay>,
  );

  await rerender(
    <Overlay open={false}>
      <ConfirmDialog request={request} onRespond={onRespond} />
    </Overlay>,
  );
  await wait(exitDurationMs() - 60);

  // The dialog is stateless and its payload is held by the window, so nothing
  // here can blank itself -- but a dialog that emptied itself on the way out
  // would be the worst version of this: the user sees the tool name fade away
  // while the answer they are about to give stops meaning anything.
  assert.equal(one(container, ".confirm-detail dd")!.textContent, "write_file");
  assert.ok(button(container, "Allow"), "Allow disappeared during the exit");
  assert.ok(button(container, "Deny"), "Deny disappeared during the exit");

  // The id is still the one that was asked about, so an answer given in the
  // window still reaches the core's pending call rather than nothing.
  await click(button(container, "Deny")!);
  assert.deepEqual(calls, [["call-1", false]]);
});

test("the closed backdrop cannot intercept a click", async () => {
  const request = destructiveWrite();
  const { calls, onRespond } = recorder();
  const container = await render(
    <Overlay open>
      <ConfirmDialog request={request} onRespond={onRespond} />
    </Overlay>,
  );

  // Real cascade from the real stylesheet, which is the whole reason that file
  // is loaded: while the dialog is up the backdrop is a click target, and once
  // it is closing it is not. A full-window backdrop still catching clicks after
  // the user answered swallows their next click -- the click that was meant for
  // the transcript underneath.
  assert.equal(
    dom.window.getComputedStyle(one(container, ".modal-backdrop")!).pointerEvents,
    "auto",
  );

  await rerender(
    <Overlay open={false}>
      <ConfirmDialog request={request} onRespond={onRespond} />
    </Overlay>,
  );
  const backdrop = one(container, ".modal-backdrop")!;
  assert.equal(dom.window.getComputedStyle(backdrop).pointerEvents, "none");

  // jsdom does no hit testing, so what is asserted here is the mechanism: the
  // closed state is declared unclickable, and a click delivered to it anyway
  // reaches nothing -- no dismissal, and above all no answer, because this
  // dialog has no dismiss handler and a stray click must not be readable as a
  // decision.
  await click(backdrop);
  assert.equal(state(container), "closed");
  assert.deepEqual(calls, []);
});

test("Allow and Deny each answer exactly once, with the right call and polarity", async () => {
  const request = destructiveWrite();
  const { calls, onRespond } = recorder();
  const container = await render(
    <Overlay open>
      <ConfirmDialog request={request} onRespond={onRespond} />
    </Overlay>,
  );

  await click(button(container, "Allow")!);
  assert.deepEqual(calls, [["call-1", true]]);

  await click(button(container, "Deny")!);
  assert.deepEqual(calls, [
    ["call-1", true],
    ["call-1", false],
  ]);

  // The polarity is the whole safety property. `true` runs the tool and `false`
  // does not, and a swapped pair here would make Deny the dangerous button.
  assert.equal(button(container, "Allow")!.className.includes("btn-danger"), true);
});

test("Escape does not answer it, and the dialog stays up", async () => {
  const request = destructiveWrite();
  const { calls, onRespond } = recorder();
  const container = await render(
    <Overlay open>
      <ConfirmDialog request={request} onRespond={onRespond} />
    </Overlay>,
  );

  // Observed, not wished for: nothing in the app handles Escape while this is
  // up. `App.tsx` binds Escape for the Files overlay and `ConversationList`
  // binds it for its inline rename; `ConfirmDialog` binds no key at all. The
  // turn stays blocked until Allow or Deny is clicked, or until the core's own
  // 60-second timeout denies it (`orchestrator.py::_request_confirmation`).
  //
  // The dialog's own comment explains why it is not dismissible by clicking
  // away -- a stray click must not read as an answer -- and that reasoning has
  // not been carried over to the keyboard, where Escape is the reflexive "get
  // this off my screen". Asserted here so the gap is a failing test someone
  // can see rather than a blocked turn someone has to diagnose.
  await press("Escape");
  assert.deepEqual(calls, [], "Escape answered the confirmation");
  assert.equal(state(container), "open", "Escape dismissed a dialog that must not be dismissed");
  assert.ok(one(container, ".modal"), "the dialog was removed by a key it does not handle");
});

test("re-opening inside the exit window cancels the pending unmount", async () => {
  const first = destructiveWrite();
  const second = requestFor({
    id: "call-2",
    name: "delete_file",
    arguments: { path: "notes.txt" },
    description: "Move a file to the recycle bin.",
    destructive: true,
  });
  const { calls, onRespond } = recorder();
  const container = await render(
    <Overlay open>
      <ConfirmDialog request={first} onRespond={onRespond} />
    </Overlay>,
  );

  await rerender(
    <Overlay open={false}>
      <ConfirmDialog request={first} onRespond={onRespond} />
    </Overlay>,
  );
  await wait(exitDurationMs() - 70);
  // A second tool call can arrive while the first prompt is still fading. If
  // the pending unmount were not cancelled, the new request would be handed to
  // a dialog that is about to be deleted -- the user answers a prompt that
  // vanishes, and the core is left holding the second call until it times out.
  await rerender(
    <Overlay open>
      <ConfirmDialog request={second} onRespond={onRespond} />
    </Overlay>,
  );

  await wait(exitDurationMs() + 80);
  assert.equal(state(container), "open", "the pending unmount was not cancelled");
  assert.equal(one(container, ".confirm-detail dd")!.textContent, "delete_file");

  // And it answers for the *new* call, not the one it replaced.
  await click(button(container, "Allow")!);
  assert.deepEqual(calls, [["call-2", true]]);
});
