import { useEffect } from "react";

import type { ChatState } from "./events.js";
import { useAnswerOnce } from "./useAnswerOnce.js";

interface Props {
  /**
   * What to show.
   *
   * Deliberately not nullable. Whether to show it belongs to the `Overlay` the
   * window puts around this, and that overlay keeps the dialog mounted after a
   * close so it can animate out -- which is why the window holds on to the
   * last request rather than passing null.
   */
  request: NonNullable<ChatState["pendingConfirm"]>;
  onRespond: (id: string, confirmed: boolean) => void;
}

/**
 * Blocking prompt for a destructive tool call.
 *
 * The core holds the tool open until `confirm.respond` arrives, so the turn
 * stays busy while this is up. It is rendered as a modal rather than inline
 * because denying is the safe default and should not be a misclick -- the
 * ordinary prompt is `ApprovalCard` above the composer, and this is the one that
 * takes the screen because the call said it cannot be undone.
 *
 * Not dismissible by clicking away: this one is a decision, not a peek, and a
 * stray click must not be readable as an answer. Escape *does* dismiss it, but
 * only ever by denying -- see the key handler below.
 */
export function ConfirmDialog({ request, onRespond }: Props) {
  /**
   * Answer once, whichever way the answer arrived.
   *
   * The buttons and the key handler both come through here rather than calling
   * `onRespond` themselves, because "exactly once" has to be a property of this
   * component rather than of each call site. A held-down key emits repeats, and
   * the dialog is still mounted and still listening for the length of its own
   * exit animation after the answer that dismissed it.
   */
  const answer = useAnswerOnce(request.id, onRespond);

  /**
   * Escape denies, and nothing behind this dialog hears the key.
   *
   * A prompt with no way off it but two small buttons is a trap for the
   * keyboard, and the scrim makes the click-anywhere target invisible -- there
   * is nothing on screen to say "click here to close". Escape is the affordance
   * that does not depend on seeing anything, and it was the one Escape the rest
   * of this app already honours.
   */
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      // Capture, and stop here.
      //
      // Escape already means "get this off my screen" to the two other places
      // that listen for it -- the Files overlay and a conversation's row menu
      // both close on it -- and while a blocking prompt is up neither of those
      // is what the user is looking at. Capture runs before the event reaches
      // the target, so stopping propagation here means the other two window
      // listeners never see the key at all.
      event.stopPropagation();
      // Denying, never allowing. Escape is the reflexive way off a screen that
      // is in the way, and a user who reaches for it is not reading the tool
      // name -- so the answer it gives has to be the one that does nothing.
      answer(false);
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [answer]);

  return (
    <div className="modal" role="dialog" aria-modal="true" aria-labelledby="confirm-title">
        <h2 id="confirm-title">Confirm tool execution</h2>

        <dl className="confirm-detail">
          <dt>Tool</dt>
          <dd>{request.name}</dd>
          {request.arguments && (
            <>
              <dt>Arguments</dt>
              <dd>
                <code>{request.arguments}</code>
              </dd>
            </>
          )}
        </dl>

        {request.destructive && (
          <p className="warn">This action is destructive and cannot be undone.</p>
        )}

        <div className="modal-actions">
          <button type="button" className="btn btn-danger" onClick={() => answer(true)}>
            Allow
          </button>
          <button type="button" className="btn" onClick={() => answer(false)}>
            Deny
          </button>
        </div>
    </div>
  );
}
