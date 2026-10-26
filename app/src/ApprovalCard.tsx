import { useEffect } from "react";

import type { ChatState } from "./events.js";
import { useAnswerOnce } from "./useAnswerOnce.js";

interface Props {
  /** What to show. Not nullable for the reason the modal's prop is not. */
  request: NonNullable<ChatState["pendingConfirm"]>;
  onRespond: (id: string, confirmed: boolean) => void;
}

/**
 * A permission request, inline above the composer.
 *
 * The modal was the whole story: the turn stopped, the window dimmed, and the
 * only way forward was to answer a dialog — which meant a confirmable read could
 * take the screen away from the conversation it was about. Now the ordinary
 * prompt is a card where the composer is, so the prose that asked for it stays
 * visible above and the answer is a press away. The modal survives for the one
 * case that deserves to interrupt: a call that says it is destructive, where the
 * safe answer has to be the default and a misclick must not be one.
 *
 * What it deliberately does not have is "Always". The core takes a boolean —
 * `confirm.respond {id, confirmed}` — and nothing else, so a third button would
 * have been a promise this window cannot keep. Teaching the core a scope is a
 * change to the permission ladder, which is not this phase's to make.
 */
export function ApprovalCard({ request, onRespond }: Props) {
  const answer = useAnswerOnce(request.id, onRespond);

  /**
   * The keys, for parity with the modal.
   *
   * The card is above the composer and the field is disabled while the turn is
   * blocked, so Enter and Escape are free -- and a prompt that can only be
   * answered by finding a small button is a prompt that is harder to answer than
   * the dialog it replaced. Escape denies, always: it is the reflexive way off a
   * screen, and a user reaching for it is not reading the tool name.
   */
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        // Capture, and stop here -- the same reasoning as the modal's: the Files
        // overlay and a row menu both close on Escape, and neither is what the
        // user is looking at while a call is waiting on them.
        event.stopPropagation();
        answer(false);
        return;
      }
      if (event.key !== "Enter") return;
      // A text field keeps its own Enter: the answer here is a button, and the
      // keys that reach one should reach it through the browser rather than
      // through this handler.
      // `instanceof` rather than a cast: the event can be dispatched at
      // `window`, which has no `tagName` and no `closest` -- a key pressed with
      // nothing focused is exactly the case this handler is for.
      const target = event.target instanceof HTMLElement ? event.target : null;
      if (target && (target.tagName === "TEXTAREA" || target.tagName === "INPUT")) return;
      // A focused Allow or Deny button activates itself; answering here as well
      // would give Enter the wrong answer on the Deny button.
      if (target?.closest(".approval-actions")) return;
      event.preventDefault();
      event.stopPropagation();
      answer(true);
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [answer]);

  // The argument list, when there is one, is the honest one-line risk: it is
  // what the tool is about to do, quoted rather than paraphrased into a sentence
  // that could be softer than the call itself.
  const risk = request.description || request.arguments;

  return (
    <div
      className="approval"
      role="group"
      aria-labelledby="approval-tool"
      data-destructive={request.destructive ? "true" : "false"}
    >
      {/* The rail is the reason this reads as a blocked turn rather than as
          another message: amber, the one colour in the window allowed to pull
          the eye away from signal. */}
      <div className="approval-main">
        <div className="approval-head">
          <span className="approval-kicker">Needs permission</span>
          <span className="approval-tool" id="approval-tool">
            {request.name}
          </span>
        </div>
        {risk && (
          <code className="approval-risk" title={risk}>
            {risk}
          </code>
        )}
      </div>
      <div className="approval-actions">
        <button
          type="button"
          className="btn approval-allow"
          onClick={() => answer(true)}
          title="Run this call"
        >
          Allow
        </button>
        <button
          type="button"
          className="btn approval-deny"
          onClick={() => answer(false)}
          title="Refuse this call; the turn continues without it"
        >
          Deny
        </button>
      </div>
    </div>
  );
}
